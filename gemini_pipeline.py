"""
Gemini vendor pipeline — Step 1 (standalone, no DB / no FastAPI).

One Gemini call does transcription + speaker diarization + English translation
for a 2-speaker TVS lead-qualification call, returning structured JSON plus the
token usage and cost (₹).

This module is intentionally self-contained so it can be verified on its own:

    set GEMINI_API_KEY=...        (PowerShell:  $env:GEMINI_API_KEY="...")
    python gemini_pipeline.py path/to/audio.wav

Dependencies:
    pip install google-genai
    (optional) pip install pydub  + ffmpeg   -> enables silence trimming
"""

from __future__ import annotations

import os
import io
import json
import mimetypes
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

try:  # load .env when run standalone; harmless if python-dotenv is absent
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ---------------------------------------------------------------------------
# Pricing — USD per 1M tokens. "input" is the AUDIO rate (audio dominates).
# Output rate also applies to any hidden "thinking" tokens.
# Verify at https://ai.google.dev/gemini-api/docs/pricing
# ---------------------------------------------------------------------------
PRICING: dict[str, dict[str, float]] = {
    # text_input | audio_input | output  (USD per 1M tokens)
    "gemini-2.5-flash-lite": {"text_input": 0.10, "audio_input": 0.30, "output": 0.40},
    "gemini-2.5-flash":      {"text_input": 0.30, "audio_input": 0.60, "output": 2.50},
    "gemini-3.5-flash":      {"text_input": 1.50, "audio_input": 3.00, "output": 9.00},
}
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
USD_TO_INR = float(os.getenv("USD_TO_INR", "95.0"))


def _cost_inr(in_tok: int, out_tok: int, in_rate: float, out_rate: float) -> float:
    """Cost in ₹ given token counts and per-1M-token USD rates."""
    return (in_tok / 1_000_000 * in_rate + out_tok / 1_000_000 * out_rate) * USD_TO_INR


# ---------------------------------------------------------------------------
# Prompt + output schema
# ---------------------------------------------------------------------------
TRANSCRIBE_PROMPT = """You are an expert call-center transcriptionist and speaker diarizer.

DOMAIN: This is a call for TVS — the Indian automotive company — about TVS
automobiles and TVS THREE-WHEELERS (auto-rickshaws / passenger and cargo
three-wheelers such as the TVS King). Expect vehicle models, on-road price,
down payment, EMI / loan / finance, showroom, test ride, RTO, mileage, exchange
offers. Transcribe brand/model names like "TVS", "TVS King" exactly.

This is a LEAD-QUALIFICATION call with EXACTLY TWO speakers:
  - AGENT: the TVS representative. Greets, introduces TVS, leads, asks
    qualifying questions (name, location, vehicle, budget, finance, timeline).
  - CUSTOMER: the lead/prospect. Answers, gives details, asks about the offer.

Tasks:
1. Transcribe every turn and TRANSLATE it into natural English (audio may be
   Hindi / Marathi / Hinglish). Preserve numbers, names, money, and dates.
2. Diarize: label every turn AGENT or CUSTOMER using role cues; stay consistent.

Confidence rules (IMPORTANT):
- Do NOT guess the speaker. If you are not confident whether a turn is the
  AGENT or the CUSTOMER, label that turn "UNKNOWN" instead of guessing.
- Never merge two different speakers into one turn. The moment the voice
  changes, start a new turn — even if you must mark it UNKNOWN.
- The two real speakers are AGENT and CUSTOMER; only use UNKNOWN for genuine
  uncertainty, never as a third participant.
- For words you cannot clearly hear, write [inaudible] in place of those words.

Return the result using the provided JSON schema only.
"""

# Structured-output schema: ONLY segments. The flat english transcript is
# derived from segments (see segments_to_text) so the model never writes the
# transcript twice — halves output tokens and avoids truncation on long calls.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string", "enum": ["AGENT", "CUSTOMER", "UNKNOWN"]},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "text"],
            },
        },
    },
    "required": ["segments"],
}


# ---------------------------------------------------------------------------
# Optional silence trim (graceful no-op if pydub/ffmpeg unavailable)
# ---------------------------------------------------------------------------
def _locate_ffmpeg(AudioSegment) -> None:
    """Point pydub at the winget-installed ffmpeg if it isn't on PATH."""
    import glob
    if AudioSegment.converter and os.path.exists(str(AudioSegment.converter)):
        return
    pattern = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin",
    )
    for bindir in glob.glob(pattern, recursive=True):
        ffmpeg = os.path.join(bindir, "ffmpeg.exe")
        if os.path.exists(ffmpeg):
            AudioSegment.converter = ffmpeg
            AudioSegment.ffprobe = os.path.join(bindir, "ffprobe.exe")
            return


def _maybe_trim_silence(audio_bytes: bytes, fmt: str) -> tuple[bytes, str]:
    """Returns (bytes, mime_type). Falls back to the original if trimming fails."""
    try:
        from pydub import AudioSegment
        from pydub.silence import detect_nonsilent
        _locate_ffmpeg(AudioSegment)
    except Exception:
        return audio_bytes, mimetypes.types_map.get("." + fmt, "audio/mpeg")

    try:
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        chunks = detect_nonsilent(seg, min_silence_len=600, silence_thresh=-40)
        if not chunks:
            return audio_bytes, "audio/mpeg"
        out = AudioSegment.empty()
        for start, end in chunks:
            out += seg[max(0, start - 150): min(len(seg), end + 150)]
        buf = io.BytesIO()
        out.export(buf, format="mp3")
        return buf.getvalue(), "audio/mpeg"
    except Exception:
        return audio_bytes, mimetypes.types_map.get("." + fmt, "audio/mpeg")


# ---------------------------------------------------------------------------
# Resilient Gemini call: retry on 503/overload, then fall back to a stronger
# model once. Keeps transient Google-side capacity errors from failing jobs.
# ---------------------------------------------------------------------------
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
_RETRY_DELAYS = (2, 5, 10)  # seconds between attempts on 503


class PrimaryModelOverloaded(Exception):
    """Primary model still 503 after all retries (fallback not allowed here)."""


class TranscriptRunaway(PrimaryModelOverloaded):
    """
    Transcription hit MAX_TOKENS twice (degenerate generation loop on this
    audio). Subclasses PrimaryModelOverloaded so callers route to the
    rating-only fallback and the client still gets a scorecard.
    """


def _is_overloaded(exc: Exception) -> bool:
    s = str(exc)
    return "503" in s or "UNAVAILABLE" in s or "overloaded" in s.lower()


def _generate_with_retry(client, model: str, contents, config, allow_fallback: bool = True):
    """
    Call generate_content with retries on 503/UNAVAILABLE.
    - allow_fallback=True: after retries, try FALLBACK_MODEL once.
    - allow_fallback=False: after retries, raise PrimaryModelOverloaded so the
      caller can switch to a cheaper strategy (e.g. rating-only, no transcript).
    Returns (response, model_actually_used).
    """
    import time as _time

    last_exc: Exception | None = None
    for delay in (0, *_RETRY_DELAYS):
        if delay:
            _time.sleep(delay)
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config
            ), model
        except Exception as e:
            if not _is_overloaded(e):
                raise
            last_exc = e

    if not allow_fallback:
        raise PrimaryModelOverloaded(str(last_exc))

    # Still overloaded — try the fallback model once (if it's different)
    if FALLBACK_MODEL and FALLBACK_MODEL != model:
        try:
            return client.models.generate_content(
                model=FALLBACK_MODEL, contents=contents, config=config
            ), FALLBACK_MODEL
        except Exception as e:
            last_exc = e

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
def transcribe_diarize_translate(
    audio_path: str | Path,
    model: str | None = None,
    trim_silence: bool = True,
    api_key: str | None = None,
    max_output_tokens: int = 65536,
) -> dict[str, Any]:
    """
    Run the single Gemini audio call. Returns:
    {
        "english_transcript": str,
        "segments": [{"speaker": "AGENT"|"CUSTOMER", "text": str}, ...],
        "usage": {audio_input_tokens, output_tokens, total_tokens,
                  cost_inr, model}
    }
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model = model or DEFAULT_MODEL
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY (env var) or pass api_key=...")

    fmt = audio_path.suffix.lstrip(".").lower() or "mp3"
    audio_bytes = audio_path.read_bytes()
    if trim_silence:
        audio_bytes, mime_type = _maybe_trim_silence(audio_bytes, fmt)
    else:
        mime_type = mimetypes.guess_type(str(audio_path))[0] or "audio/mpeg"

    client = genai.Client(api_key=api_key)
    contents = [
        TRANSCRIBE_PROMPT,
        types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
    ]
    config = types.GenerateContentConfig(
        temperature=0,  # deterministic; prevents degenerate/runaway generations
        response_mime_type="application/json",
        response_schema=RESPONSE_SCHEMA,
        max_output_tokens=max_output_tokens,   # admin-configurable; guard below catches overflow
    )

    def _finish_is_max(resp) -> bool:
        cand = (resp.candidates or [None])[0]
        return "MAX_TOKENS" in str(getattr(cand, "finish_reason", ""))

    # No silent fallback here: if the primary model is overloaded, raise
    # PrimaryModelOverloaded so the caller can use the cheaper rating-only
    # path on the fallback model instead of paying for a full transcript.
    response, model = _generate_with_retry(client, model, contents, config, allow_fallback=False)

    # Guard: stopping at the output cap means truncated JSON — on a normal call
    # this is a degenerate repetition loop. Regenerating at temperature 0 would
    # deterministically reproduce the same runaway, so regenerate once at a
    # HIGHER temperature to break the loop.
    if _finish_is_max(response):
        retry_config = types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
            max_output_tokens=max_output_tokens,
        )
        response, model = _generate_with_retry(client, model, contents, retry_config, allow_fallback=False)
        if _finish_is_max(response):
            # Persistent runaway on this audio — escalate so the caller uses
            # the rating-only fallback (client still gets a scorecard).
            raise TranscriptRunaway(
                "Transcription hit MAX_TOKENS twice (degenerate generation loop)."
            )

    data = json.loads(response.text)

    usage = response.usage_metadata
    in_tok = usage.prompt_token_count or 0
    out_tok = (usage.candidates_token_count or 0) + (
        getattr(usage, "thoughts_token_count", 0) or 0
    )
    price = PRICING.get(model, PRICING[DEFAULT_MODEL])
    cost_inr = _cost_inr(in_tok, out_tok, price["audio_input"], price["output"])

    segments = data.get("segments", [])
    return {
        "english_transcript": segments_to_text(segments),  # derived, not re-generated
        "segments": segments,
        "usage": {
            "audio_input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "cost_inr": round(cost_inr, 4),
            "model": model,
        },
    }


def segments_to_text(segments: list[dict[str, Any]]) -> str:
    """Flatten diarized segments into 'AGENT: ...\\nCUSTOMER: ...' text."""
    return "\n".join(f"{s.get('speaker','?')}: {s.get('text','')}" for s in segments)


# ---------------------------------------------------------------------------
# Rating — text-only call that scores a transcript against a rubric (prompt).
# Same JSON shape the Groq path produces, so /status is identical per vendor.
# ---------------------------------------------------------------------------
RATING_SYSTEM = """You are a strict, objective call-quality scorer.

Read the RUBRIC, then evaluate the TRANSCRIPT (and optional ENGLISH TRANSLATION)
against every criterion in the rubric. Score the AGENT only.

Scoring scale (MUST follow exactly):
- Each criterion "score" is an integer 0-5.
- "overall_score" is an integer 0-5 — the ROUNDED AVERAGE of the criteria
  scores. It is NOT a sum and must never exceed 5.
- "grade" maps from overall_score: A (5), B (4), C (3), D (2), F (0-1).

Be consistent: identical input must yield identical scores. Return ONLY the JSON
object that matches the provided schema — no prose, no markdown fences. If the
transcript is empty or unusable, set overall_score to 0 and explain in summary.
"""

RATING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall_score": {"type": "integer"},
        "grade": {"type": "string"},
        "summary": {"type": "string"},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "score": {"type": "integer"},
                    "feedback": {"type": "string"},
                },
                "required": ["name", "score", "feedback"],
            },
        },
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overall_score", "grade", "summary", "criteria",
                 "strengths", "improvements"],
}


def rate_transcript(
    transcript_text: str,
    english_text: str,
    rubric: str,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Score *transcript_text* against *rubric* with a text-only Gemini call.
    Returns {"raw": <json str>, "data": <parsed dict>, "usage": {...}}.
    """
    rubric = (rubric or "").strip()
    if not rubric:
        raise ValueError("Rubric (prompt) is empty.")

    model = model or DEFAULT_MODEL
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY (env var) or pass api_key=...")

    user = "## RUBRIC\n" + rubric + "\n\n## TRANSCRIPT\n" + (transcript_text or "(empty)")
    if english_text:
        user += "\n\n## ENGLISH TRANSLATION\n" + english_text
    user += "\n\nScore the AGENT against the rubric and return only the JSON object."

    client = genai.Client(api_key=api_key)
    response, model = _generate_with_retry(
        client,
        model,
        contents=[RATING_SYSTEM, user],
        config=types.GenerateContentConfig(
            temperature=0,  # consistent scores
            response_mime_type="application/json",
            response_schema=RATING_SCHEMA,
        ),
    )

    raw = response.text
    data = json.loads(raw)

    usage = response.usage_metadata
    in_tok = usage.prompt_token_count or 0
    out_tok = (usage.candidates_token_count or 0) + (
        getattr(usage, "thoughts_token_count", 0) or 0
    )
    price = PRICING.get(model, PRICING[DEFAULT_MODEL])
    cost_inr = _cost_inr(in_tok, out_tok, price["text_input"], price["output"])

    return {
        "raw": raw,
        "data": data,
        "usage": {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "cost_inr": round(cost_inr, 4),
            "model": model,
        },
    }


RATING_ONLY_SYSTEM = """You are a strict, objective call-quality scorer.

Listen to the attached call recording (it may be in Hindi, Marathi, Hinglish or
English). It is a TVS lead-qualification call with two speakers: the AGENT (TVS
representative) and the CUSTOMER. Evaluate the AGENT against every criterion in
the RUBRIC below. Do NOT write a transcript — output ONLY the score JSON.

Scoring scale (MUST follow exactly):
- Each criterion "score" is an integer 0-5.
- "overall_score" is an integer 0-5 — the ROUNDED AVERAGE of the criteria
  scores. It is NOT a sum and must never exceed 5.
- "grade" maps from overall_score: A (5), B (4), C (3), D (2), F (0-1).

Return ONLY the JSON object matching the provided schema — no prose, no
markdown fences. If the audio has no usable conversation, set overall_score to
0 and explain in summary.
"""


def rate_audio_only(
    audio_path: str | Path,
    rubric: str,
    model: str | None = None,
    api_key: str | None = None,
    trim_silence: bool = True,
) -> dict[str, Any]:
    """
    Cost-saving fallback: ONE call that listens to the audio and returns ONLY
    the rating JSON (no transcript generated -> far fewer output tokens).
    Used when the cheap primary model is overloaded and we must run on the
    pricier fallback model. Returns {"raw", "data", "usage"}.
    """
    rubric = (rubric or "").strip()
    if not rubric:
        raise ValueError("Rubric (prompt) is empty.")

    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model = model or FALLBACK_MODEL
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY (env var) or pass api_key=...")

    fmt = audio_path.suffix.lstrip(".").lower() or "mp3"
    audio_bytes = audio_path.read_bytes()
    if trim_silence:
        audio_bytes, mime_type = _maybe_trim_silence(audio_bytes, fmt)
    else:
        mime_type = mimetypes.guess_type(str(audio_path))[0] or "audio/mpeg"

    client = genai.Client(api_key=api_key)
    response, model = _generate_with_retry(
        client,
        model,
        contents=[
            RATING_ONLY_SYSTEM + "\n## RUBRIC\n" + rubric,
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=RATING_SCHEMA,
        ),
        allow_fallback=True,  # already on the fallback path; let it try others
    )

    raw = response.text
    data = json.loads(raw)

    usage = response.usage_metadata
    in_tok = usage.prompt_token_count or 0
    out_tok = (usage.candidates_token_count or 0) + (
        getattr(usage, "thoughts_token_count", 0) or 0
    )
    price = PRICING.get(model, PRICING[DEFAULT_MODEL])
    cost_inr = _cost_inr(in_tok, out_tok, price["audio_input"], price["output"])

    return {
        "raw": raw,
        "data": data,
        "usage": {
            "audio_input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "cost_inr": round(cost_inr, 4),
            "model": model,
        },
    }


# ---------------------------------------------------------------------------
# Standalone runner — for verifying this step on its own
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        sys.exit("Usage: python gemini_pipeline.py <audio_file> [model]")

    model_arg = sys.argv[2] if len(sys.argv) > 2 else None
    result = transcribe_diarize_translate(sys.argv[1], model=model_arg)

    print("\n===== DIARIZED ENGLISH TRANSCRIPT =====")
    print(segments_to_text(result["segments"]))
    print("\n===== USAGE / COST =====")
    print(json.dumps(result["usage"], indent=2))
