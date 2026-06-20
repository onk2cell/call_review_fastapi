import os
import base64
from pathlib import Path
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from aligned_transcript import align_combined_data


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _verbose_json_to_words(tr: Any) -> list[dict[str, Any]]:
    if hasattr(tr, "model_dump"):
        raw = tr.model_dump()
    elif isinstance(tr, dict):
        raw = tr
    else:
        raw = dict(tr) if hasattr(tr, "keys") else {}

    words = raw.get("words") or []
    out: list[dict[str, Any]] = []
    for w in words:
        if isinstance(w, dict):
            t = str(w.get("word") or w.get("text") or "").strip()
            if t:
                out.append({"text": t, "start": float(w["start"]), "end": float(w["end"])})
        else:
            t = str(getattr(w, "word", None) or getattr(w, "text", "") or "").strip()
            if t:
                out.append({"text": t, "start": float(getattr(w, "start")), "end": float(getattr(w, "end"))})
    return out


def _segments_to_pseudo_words(tr: Any) -> list[dict[str, Any]]:
    if hasattr(tr, "model_dump"):
        raw = tr.model_dump()
    elif isinstance(tr, dict):
        raw = tr
    else:
        raw = {}

    segments = raw.get("segments") or []
    out: list[dict[str, Any]] = []
    for seg in segments:
        if isinstance(seg, dict):
            t = str(seg.get("text") or "").strip()
            if t:
                out.append({"text": t, "start": float(seg["start"]), "end": float(seg["end"])})
    return out


# ---------------------------------------------------------------------------
# Diarization
# ---------------------------------------------------------------------------

def run_diarization(
    pyannote_key: str,
    audio_url: str,
    audio_path: Path,
    num_speakers: int = 2,
) -> list[dict[str, Any]]:
    """
    Try diarizing via the URL first (works for presigned S3 URLs and public URLs).
    Falls back to uploading the local file if the URL route fails.
    """
    from pyannoteai.sdk import Client

    client = Client(pyannote_key)
    try:
        print("[Pyannote] Attempting diarization via URL...")
        job_id = client.diarize(audio_url, model="community-1", num_speakers=num_speakers)
    except Exception as e:
        print(f"[Pyannote] URL failed ({e}). Falling back to local file upload...")
        media_url = client.upload(audio_path)
        job_id = client.diarize(media_url, model="community-1", num_speakers=num_speakers)

    diarization = client.retrieve(job_id)
    return diarization["output"]["diarization"]


# ---------------------------------------------------------------------------
# Transcription (RunPod serverless Whisper)
# ---------------------------------------------------------------------------

def _runpod_segments_words(output: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Flatten a RunPod faster-whisper ``segments`` list into the
    ``{"text", "start", "end"}`` word format the aligner expects.

    Prefers per-word timestamps (``word_timestamps=True``); falls back to
    one pseudo-word per segment when only segment-level timing is present.
    """
    segments = output.get("segments") or []
    out: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        seg_words = seg.get("words") or []
        if seg_words:
            for w in seg_words:
                if not isinstance(w, dict):
                    continue
                t = str(w.get("word") or w.get("text") or "").strip()
                if t and w.get("start") is not None and w.get("end") is not None:
                    out.append({"text": t, "start": float(w["start"]), "end": float(w["end"])})
        else:
            t = str(seg.get("text") or "").strip()
            if t and seg.get("start") is not None and seg.get("end") is not None:
                out.append({"text": t, "start": float(seg["start"]), "end": float(seg["end"])})
    return out


def run_runpod_translate_words(
    runpod_key: str,
    endpoint_id: str,
    audio_path: Path,
) -> tuple[list[dict[str, Any]], str]:
    """
    Transcribe + translate to English via a RunPod serverless Whisper endpoint.

    Sends the audio as base64 to the endpoint's ``/runsync`` route (blocking,
    returns the result in one call). Assumes the faster-whisper worker schema
    (runpod-workers/worker-faster_whisper); adjust the ``input`` keys below if
    your endpoint uses a different handler.
    """
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = f"https://api.runpod.ai/v2/{endpoint_id}/runsync"
    headers = {
        "Authorization": f"Bearer {runpod_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": {
            "audio_base64": audio_b64,
            "model": "large-v3",
            "translate": True,            # -> English (matches Groq translations behaviour)
            "word_timestamps": True,
            "transcription": "plain_text",
        }
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=600)
    resp.raise_for_status()
    body = resp.json()

    status = body.get("status")
    if status and status not in ("COMPLETED", "IN_PROGRESS"):
        raise RuntimeError(f"RunPod job failed: {body}")

    output = body.get("output") or {}
    if isinstance(output, list):  # some workers return a list of results
        output = output[0] if output else {}

    words = _runpod_segments_words(output)
    if not words:
        words = _verbose_json_to_words(output)  # in case top-level "words" is present

    text = str(
        output.get("translation")
        or output.get("transcription")
        or output.get("text")
        or ""
    ).strip()

    return words, text


# ---------------------------------------------------------------------------
# Main pipeline — diarization + transcription run in PARALLEL
# ---------------------------------------------------------------------------

def process_call_recording(
    audio_url: str,
    audio_path: Path,
    num_speakers: int = 2,
    merge_gap: float = 0.9,
    agent_speaker: str | None = None,
    strict_two: bool = False,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Runs Pyannote diarization and Groq transcription in parallel using a
    ThreadPoolExecutor, then aligns the results.

    Timeline (before):
        diarization (30-120s) → transcription (10-40s) → alignment (1-3s)

    Timeline (after):
        diarization (30-120s)
        transcription (10-40s)   ← runs at the same time as diarization
        alignment (1-3s)         ← starts once both finish
    """
    pyannote_key        = os.getenv("PYANNOTE_API_KEY")
    runpod_key          = os.getenv("RUNPOD_API_KEY")
    runpod_endpoint_id  = os.getenv("RUNPOD_ENDPOINT_ID")

    if not pyannote_key:
        raise ValueError("Set PYANNOTE_API_KEY in .env")
    if not runpod_key:
        raise ValueError("Set RUNPOD_API_KEY in .env")
    if not runpod_endpoint_id:
        raise ValueError("Set RUNPOD_ENDPOINT_ID in .env")

    if on_stage:
        on_stage("processing_diarization")  # signals both are starting

    diar: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    english: str = ""

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_diar  = pool.submit(run_diarization, pyannote_key, audio_url, audio_path, num_speakers)
        fut_trans = pool.submit(run_runpod_translate_words, runpod_key, runpod_endpoint_id, audio_path)

        # Collect results as they finish; update stage when transcription done
        for fut in as_completed([fut_diar, fut_trans]):
            if fut is fut_trans:
                words, english = fut.result()
                if on_stage:
                    on_stage("processing_transcription")
            else:
                diar = fut.result()

    if on_stage:
        on_stage("processing_alignment")

    combined: dict[str, Any] = {
        "diarization": diar,
        "wordLevelTranscription": words,
    }

    aligned = align_combined_data(
        combined,
        merge_gap=merge_gap,
        agent_speaker=agent_speaker,
        strict_two=strict_two,
    )

    return {
        **aligned,
        "english_translation": english,
        "combined_json": combined,
        "diarization": diar,
    }