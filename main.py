import uuid
import httpx
import os
import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException, File, UploadFile, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from fastapi_pagination import Page, add_pagination
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination import Page, Params

from database import engine, Base, get_db, SessionLocal, ensure_audio_records_schema
import models
from call_audio_pipeline import process_call_recording

Base.metadata.create_all(bind=engine)
ensure_audio_records_schema()

app = FastAPI(title="Audio Transcription API")

# ---------------------------------------------------------------------------
# Local storage dir — only used when downloading from S3 or HTTP/HTTPS URLs for Groq
# ---------------------------------------------------------------------------
AUDIO_STORAGE_DIR = Path(os.getenv("AUDIO_STORAGE_DIR", "audio_files"))
AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


import os
import re
import json
import textwrap
from groq import Groq


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RUBRIC_TOKENS  = 100_000
MAX_ALIGNED_TOKENS =  48_000
MAX_ENGLISH_TOKENS =  24_000

# Rough char-based proxy for token budget (1 token ≈ 4 chars)
_CHARS_PER_TOKEN = 4


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clip_for_llm(text: str, token_budget: int) -> str:
    """
    Truncate *text* so it fits within *token_budget* (approximate).
    Appends a notice when clipping occurs so the LLM knows input was cut.
    """
    char_limit = token_budget * _CHARS_PER_TOKEN
    if len(text) <= char_limit:
        return text
    clipped = text[:char_limit]
    return clipped + "\n\n[... content clipped to fit context window ...]"


def _extract_json_object(text: str) -> dict | None:
    """
    Extract the first JSON object found in *text*.
    Handles:
      - bare JSON
      - JSON wrapped in ```json ... 
``` fences
      - JSON embedded in surrounding prose
    Returns None if no valid JSON object is found.
    """
    # 1. Try the whole string first (fastest path)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Try ```json ... ``` fenced block
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Greedy scan: find the outermost { ... } block
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break   # malformed — give up

    return None  # could not extract


def _build_rating_messages(rubric: str, aligned: str, english: str) -> list[dict]:
    """
    Build the Groq chat messages list for TVS rating.

    System prompt instructs the model to act as a strict scorer.
    User message supplies the rubric, transcript, and optional translation.
    """
    system_prompt = textwrap.dedent("""
        You are a strict, objective quality-scoring assistant.

        Your job:
        1. Read the RUBRIC provided by the user.
        2. Read the TRANSCRIPT (and optional ENGLISH TRANSLATION).
        3. Evaluate the transcript against every criterion in the rubric.
        4. Return your assessment as a single, valid JSON object — nothing else.

        JSON schema you MUST follow:
        {
            "overall_score": <integer 0-5>,
            "grade":         <"A" | "B" | "C" | "D" | "F">,
            "summary":       <one-sentence overall verdict>,
            "criteria": [
                {
                    "name":     <criterion name from rubric>,
                    "score":    <integer 0-5>,
                    "feedback": <one or two sentences>
                }
            ],
            "strengths":     [<string>, ...],
            "improvements":  [<string>, ...]
        }

        Rules:
        - Output ONLY the JSON object — no markdown fences, no prose before or after.
        - Be consistent: same input must always produce the same score (±2 points).
        - If the transcript is empty or unusable, set overall_score to 0 and explain in summary.
    """).strip()

    # Build the user content block
    user_parts = [
        "## RUBRIC\n" + rubric,
        "## TRANSCRIPT\n" + (aligned if aligned else "(empty)"),
    ]
    if english:
        user_parts.append("## ENGLISH TRANSLATION\n" + english)

    user_parts.append(
        "Now score the transcript against the rubric and return only the JSON object."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": "\n\n---\n\n".join(user_parts)},
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _run_tvs_rating(
    groq_key: str,
    aligned:  str,
    english:  str,
    rubric:   str,
) -> dict:
    """
    Score *aligned* transcript against *rubric* using Groq LLM.

    Parameters
    ----------
    groq_key : Groq API key.
    aligned  : Raw / aligned transcript text.
    english  : English translation of the transcript (may be empty).
    rubric   : Markdown rubric / prompt that defines scoring criteria.

    Returns
    -------
    {
        "raw":  <full LLM response string>,
        "data": <parsed JSON dict, or None if parsing failed>
    }

    Raises
    ------
    ValueError          – if rubric is empty or LLM returns empty response.
    groq.APIStatusError – on Groq API errors (propagated as-is).
    """
    # --- Validate rubric ---
    rubric = rubric.strip()
    if not rubric:
        raise ValueError(
            "Rubric is empty. Upload a valid .md prompt file before scoring."
        )

    # --- Clip inputs to fit context window ---
    rubric_c  = _clip_for_llm(rubric,                   MAX_RUBRIC_TOKENS)
    aligned_c = _clip_for_llm(aligned.strip(),          MAX_ALIGNED_TOKENS)
    english_c = _clip_for_llm((english or "").strip(),  MAX_ENGLISH_TOKENS)

    # --- Build messages ---
    messages = _build_rating_messages(rubric_c, aligned_c, english_c)

    # --- Call Groq ---
    client = Groq(api_key=groq_key)
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.1,        # low temp = consistent scores
        max_tokens=1_024,       # scores are compact; no need for more
    )

    raw = (resp.choices[0].message.content or "").strip()
    if not raw:
        raise ValueError("Groq returned an empty response for scoring.")

    return {
        "raw":  raw,
        "data": _extract_json_object(raw),   # None if JSON extraction fails
    }

# ---------------------------------------------------------------------------
# Status registry
# ---------------------------------------------------------------------------
STATUS_INFO: dict[str, dict] = {
    "pending": {
        "terminal": False,
        "summary": "Job created; waiting to start.",
    },
    "downloading": {
        "terminal": False,
        "summary": "Downloading audio from S3 or HTTP URL.",
    },
    "processing_diarization": {
        "terminal": False,
        "summary": "Speaker diarization and transcription running in parallel.",
    },
    "processing_transcription": {
        "terminal": False,
        "summary": "Transcription finished; waiting for diarization.",
    },
    "processing_alignment": {
        "terminal": False,
        "summary": "Aligning transcript with diarization.",
    },
    "completed": {
        "terminal": True,
        "summary": "Processing finished; transcript is available.",
    },
    "failed": {
        "terminal": True,
        "summary": "Processing failed; see error_detail.",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _status_payload(phase: str, error: str | None = None) -> dict:
    info = STATUS_INFO.get(phase, {})
    out = {
        "phase": phase,
        "terminal": info.get("terminal", phase in ("completed", "failed")),
        "summary": info.get("summary", "Processing update."),
    }
    if error:
        out["error_detail"] = error
    return out


def _persist_stage(audio_id: str, stage: str) -> None:
    """Opens its own session — safe to call from any thread."""
    s = SessionLocal()
    try:
        r = s.query(models.AudioRecord).filter_by(audio_id=audio_id).first()
        if r:
            r.status = stage
            s.commit()
    finally:
        s.close()


def _notify_job_terminal(
    notify_url: Optional[str],
    audio_id: str,
    prompt_id: str,
    phase: str,
    error_detail: Optional[str] = None,
) -> None:
    if not notify_url or not str(notify_url).strip():
        return

    import httpx
    body = {
        "event": "call_review.job_finished",
        "audio_id": audio_id,
        "prompt_id": prompt_id,
        "phase": phase,
        "results_ready": phase == "completed",
        "message": (
            "Results are ready; use GET /status/{audio_id} to fetch the transcript."
            if phase == "completed"
            else "Job finished with an error for this audio_id."
        ),
    }
    if error_detail:
        body["error_detail"] = error_detail

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            client.post(str(notify_url).strip(), json=body, headers={"Content-Type": "application/json"})
    except Exception:
        pass  # webhook failures must never surface


# ---------------------------------------------------------------------------
# Audio resolution — local path, S3 URI, or HTTP/HTTPS URL
# ---------------------------------------------------------------------------

def _get_s3_presigned_url(s3_uri: str, expires_in: int = 3600) -> str:
    """
    Generate a presigned HTTPS URL from an s3:// URI.
    Pyannote will use this to fetch the file directly — no local download needed.
    """
    without_scheme = s3_uri[len("s3://"):]
    bucket, _, key = without_scheme.partition("/")
    s3 = boto3.client("s3")
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


def _download_from_http(url: str, dest: Path, timeout: int = 300) -> None:
    """
    Download audio file from HTTP/HTTPS URL to local path.
    
    Args:
        url: HTTP/HTTPS URL to download from
        dest: Destination path
        timeout: Download timeout in seconds (default 5 minutes)
    """
    url = url.strip()  # defensive strip to avoid trailing spaces
    try:
        # Stream the download to handle large files efficiently
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()  # Raise exception for bad status codes
        
        # Get total file size if available
        total_size = int(response.headers.get('content-length', 0))
        
        # Write to file in chunks
        with open(dest, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                
        # Verify download if content-length was provided
        if total_size > 0 and dest.stat().st_size != total_size:
            raise RuntimeError(f"Incomplete download: expected {total_size} bytes, got {dest.stat().st_size}")
            
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise RuntimeError(
                f"File not found at URL: {url}. "
                "Check that the URL is correct and accessible (no trailing spaces, typos, or missing files)."
            ) from e
        raise RuntimeError(f"HTTP download failed for {url}: {e}") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"HTTP download failed for {url}: {e}") from e


def _download_from_s3(s3_uri: str, dest: Path) -> None:
    """Download S3 object to a local path. Only used for Groq (needs local bytes)."""
    without_scheme = s3_uri[len("s3://"):]
    bucket, _, key = without_scheme.partition("/")
    try:
        boto3.client("s3").download_file(bucket, key, str(dest))
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"S3 download failed for {s3_uri}: {e}") from e


def _download_file(url: str, dest: Path) -> None:
    """
    Generic download function that handles both S3 URIs and HTTP/HTTPS URLs.
    """
    if url.startswith("s3://"):
        _download_from_s3(url, dest)
    elif url.startswith(("http://", "https://")):
        _download_from_http(url, dest)
    else:
        raise ValueError(f"Unsupported URL scheme for download: {url}")


def _resolve_audio(source: str, audio_id: str) -> tuple[str, Path, bool]:
    """
    Resolve the audio source to:
      - pyannote_url : URL or path Pyannote will use (presigned URL for S3, original URL for HTTP, raw path for local)
      - local_path   : local Path Groq will read from
      - is_tmp       : True if local_path is a temp download that should be cleaned up after

    Local path      → no download, no cleanup
    S3 URI          → presigned URL for Pyannote, temp download for Groq, cleanup after job
    HTTP/HTTPS URL  → original URL for Pyannote (if accessible), temp download for Groq, cleanup after job
    """
    source = source.strip()  # defensive strip
    # Case 1: S3 URI
    if source.startswith("s3://"):
        presigned_url = _get_s3_presigned_url(source)
        dest = AUDIO_STORAGE_DIR / f"{audio_id}.wav"
        _download_from_s3(source, dest)
        return presigned_url, dest, True  # is_tmp = True
    
    # Case 2: HTTP/HTTPS URL
    elif source.startswith(("http://", "https://")):
        dest = AUDIO_STORAGE_DIR / f"{audio_id}.wav"
        _download_from_http(source, dest)
        # For Pyannote, we can use the original URL if it's publicly accessible,
        # or use the local path if needed. Using local path is more reliable.
        return str(dest), dest, True  # is_tmp = True
    
    # Case 3: Local file path
    else:
        local = Path(source)
        if not local.exists():
            raise FileNotFoundError(f"Local audio file not found: {source}")
        return source, local, False  # is_tmp = False


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AudioItem(BaseModel):
    """Single audio item with optional custom audio_id"""
    audio_id: Optional[str] = Field(
        default=None,
        description="Optional custom audio ID. If not provided, a UUID will be generated automatically.",
        min_length=1,
        max_length=255
    )
    source: str = Field(
        description="Audio location - local path, S3 URI, or HTTP/HTTPS URL"
    )
    
    @field_validator('audio_id')
    @classmethod
    def validate_audio_id(cls, v):
        if v is not None:
            # Add any custom validation rules for audio_id
            # For example, allow only alphanumeric, hyphens, underscores
            import re
            if not re.match(r'^[a-zA-Z0-9_-]+$', v):
                raise ValueError('audio_id must contain only alphanumeric characters, hyphens, and underscores')
        return v

    @field_validator('source')
    @classmethod
    def strip_source(cls, v: str) -> str:
        """Strip leading/trailing whitespace from source URL to avoid 404 errors."""
        return v.strip()


class AudioRequest(BaseModel):
    audio_sources: List[AudioItem] = Field(
        description=(
            "List of audio items. Each item can have:\n"
            "  - audio_id: optional custom ID (auto-generated if not provided)\n"
            "  - source: audio location (local path, S3 URI, or HTTP/HTTPS URL)\n\n"
            "Examples:\n"
            "  - With custom ID: {'audio_id': 'call_001', 'source': 'https://example.com/call.wav'}\n"
            "  - Auto-generate ID: {'source': '/tmp/audio/call.wav'}"
        )
    )
    prompt_id: str
    notify_url: Optional[str] = Field(
        default=None,
        description="Optional webhook URL. Receives a POST when each job finishes.",
    )


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _process_audio(audio_id: str) -> None:
    """
    Background task per audio_id:
      1. Resolve audio source:
           - Local path → use directly
           - S3 URI     → generate presigned URL for Pyannote + download locally for Groq
           - HTTP/HTTPS → download locally for both Pyannote and Groq
      2. Run diarization (Pyannote) and transcription (Groq) IN PARALLEL.
      3. Align results.
      4. Run TVS Rating with LLM and persist transcript/rating.
      5. Fire webhook.
    """
    db = SessionLocal()
    tmp_path: Path | None = None  # track temp downloads for cleanup

    try:
        record = db.query(models.AudioRecord).filter_by(audio_id=audio_id).first()
        if not record:
            print(f"[Error] Audio record not found for ID: {audio_id}")
            return

        source     = record.source_url
        notify_url = record.notify_url
        prompt_id  = record.prompt_id

        # ------------------------------------------------------------------
        # Step 1 — Resolve audio
        # For S3: generates presigned URL (Pyannote) + downloads locally (Groq)
        # For HTTP: downloads locally (Groq) and uses local path for Pyannote
        # For local: just validates the file exists
        # ------------------------------------------------------------------
        if source.startswith(("s3://", "http://", "https://")):
            record.status = "downloading"
            db.commit()

        try:
            pyannote_url, audio_path, is_tmp = _resolve_audio(source, audio_id)

            if is_tmp:
                tmp_path = audio_path  # mark for cleanup

            record = db.query(models.AudioRecord).filter_by(audio_id=audio_id).first()
            record.audio_path = str(audio_path)
            db.commit()

        except Exception as exc:
            db.rollback()
            record = db.query(models.AudioRecord).filter_by(audio_id=audio_id).first()
            if record:
                record.status = "failed"
                record.error_detail = str(exc)
                db.commit()
            _notify_job_terminal(notify_url, audio_id, prompt_id, "failed", str(exc))
            return

        # ------------------------------------------------------------------
        # Step 2 — AI pipeline (diarization + transcription run in parallel)
        # ------------------------------------------------------------------
        try:
            ai_results = process_call_recording(
                audio_url  = pyannote_url,   # presigned HTTPS URL, local path, or HTTP URL
                audio_path = audio_path,     # always a local Path for Groq
                on_stage   = lambda st: _persist_stage(audio_id, st),
            )

            transcript_text = ai_results.get("text", "")
            english_translation = ai_results.get("english_translation", "")

            # --- RUN TVS RATING ONCE HERE ---
            rating_result = None
            groq_key = os.getenv("GROQ_API_KEY", "")
            
            # Fetch the prompt text to use as the rubric
            prompt_record = db.query(models.PromptRecord).filter_by(prompt_id=prompt_id).first()
            prompt_text = prompt_record.prompt if prompt_record else None

            if groq_key and prompt_text and transcript_text:
                try:
                    rating_result = _run_tvs_rating(
                        groq_key=groq_key,
                        aligned=transcript_text,       # raw aligned transcript
                        english=english_translation,   # english translation (can be "")
                        rubric=prompt_text,            # prompt markdown as the rubric
                    )
                except FileNotFoundError as e:
                    rating_result = {"error": f"Rubric missing: {str(e)}"}
                except ValueError as e:
                    rating_result = {"error": f"LLM error: {str(e)}"}
                except Exception as e:
                    rating_result = {"error": f"Rating failed: {str(e)}"}
            else:
                missing = []
                if not groq_key:    missing.append("GROQ_API_KEY")
                if not prompt_text: missing.append("prompt")
                if not transcript_text: missing.append("transcript")
                rating_result = {"error": f"Skipped — missing: {', '.join(missing)}"}

            # --- SAVE EVERYTHING TO THE DATABASE ---
            db.add(models.TranscriptResult(
                audio_id            = audio_id,
                transcript_text     = transcript_text,
                english_translation = english_translation,
                transcript_json     = ai_results.get("combined_json", {}),
                rating_json         = rating_result,  # Saved directly to column!
            ))

            record = db.query(models.AudioRecord).filter_by(audio_id=audio_id).first()
            if record:
                record.status = "completed"
            db.commit()

            _notify_job_terminal(notify_url, audio_id, prompt_id, "completed")

        except Exception as exc:
            db.rollback()
            record = db.query(models.AudioRecord).filter_by(audio_id=audio_id).first()
            if record:
                record.status = "failed"
                record.error_detail = str(exc)
                db.commit()
            _notify_job_terminal(notify_url, audio_id, prompt_id, "failed", str(exc))

    finally:
        db.close()
        # Clean up temp downloads only (S3 and HTTP) — local files are never deleted
        if tmp_path and tmp_path.exists():
            os.remove(tmp_path)
            print(f"[Cleanup] Removed temp file: {tmp_path}")

class PromptListResponse(BaseModel):
    # index: int  # Mapping to the 'id' column
    prompt_id: str
    service_name: str
    # Notice: NO prompt_text field here!

    class Config:
        from_attributes = True 
        populate_by_name = True 
        alias_generator = lambda string: 'index' if string == 'id' else string


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# @app.post("/process-audio/")
# def process_audio(
#     request: AudioRequest,
#     background_tasks: BackgroundTasks,
#     db: Session = Depends(get_db),
# ):
    """
    Accept one or more audio sources with optional custom audio IDs.
    Returns audio_ids immediately; processing runs in the background.

    Examples:
        With custom IDs:
        {
            "audio_sources": [
                {"audio_id": "call_001", "source": "https://example.com/call1.wav"},
                {"audio_id": "call_002", "source": "s3://my-bucket/call2.wav"},
                {"audio_id": "call_003", "source": "/tmp/audio/call3.wav"}
            ],
            "prompt_id": "qa_rubric_v1"
        }
        
        With auto-generated IDs:
        {
            "audio_sources": [
                {"source": "https://example.com/call1.wav"},
                {"source": "s3://my-bucket/call2.wav"}
            ],
            "prompt_id": "qa_rubric_v1"
        }
    """
#     results = []

#     for audio_item in request.audio_sources:
#         source = audio_item.source
#         custom_audio_id = audio_item.audio_id
        
#         # Basic validation before queuing
#         if source.startswith("s3://") or source.startswith(("http://", "https://")):
#             # For URLs, we don't validate existence upfront (just queue)
#             pass
#         elif not Path(source).exists():
#             results.append({
#                 "source": source,
#                 "error": "Local file not found — skipped.",
#             })
#             continue
        
#         # Determine audio_id (use custom or generate new)
#         if custom_audio_id:
#             # Check if custom audio_id already exists
#             existing = db.query(models.AudioRecord).filter_by(audio_id=custom_audio_id).first()
#             if existing:
#                 results.append({
#                     "source": source,
#                     "audio_id": custom_audio_id,
#                     "error": f"Audio ID '{custom_audio_id}' already exists. Skipping.",
#                 })
#                 continue
#             unique_audio_id = custom_audio_id
#         else:
#             unique_audio_id = str(uuid.uuid4())
        
#         new_record = models.AudioRecord(
#             audio_id   = unique_audio_id,
#             prompt_id  = request.prompt_id,
#             source_url = source,
#             audio_path = None,        # filled in by the worker
#             status     = "pending",
#             notify_url = request.notify_url,
#         )
#         db.add(new_record)
#         db.commit()

#         background_tasks.add_task(_process_audio, unique_audio_id)

#         results.append({
#             "source": source,
#             "audio_id": unique_audio_id,
#             "custom_id_provided": custom_audio_id is not None,
#             **_status_payload("pending"),
#         })

#     return {
#         "message": (
#             "Jobs queued. Poll GET /status/{audio_id} for progress. "
#             "If notify_url was set, a POST is fired when each job finishes."
#         ),
#         "prompt_id": request.prompt_id,
#         "notify_url": request.notify_url,
#         "total_items": len(results),
#         "details": results,
#     }


@app.post("/process-audio/")
def process_audio(
    request: AudioRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Accept one or more audio sources with optional custom audio IDs.
    Returns audio_ids immediately; processing runs in the background.

    Examples:
        With custom IDs:
        {
            "audio_sources": [
                {"audio_id": "call_001", "source": "https://example.com/call1.wav"},
                {"audio_id": "call_002", "source": "s3://my-bucket/call2.wav"},
                {"audio_id": "call_003", "source": "/tmp/audio/call3.wav"}
            ],
            "prompt_id": "qa_rubric_v1"
        }
        
        With auto-generated IDs:
        {
            "audio_sources": [
                {"source": "https://example.com/call1.wav"},
                {"source": "s3://my-bucket/call2.wav"}
            ],
            "prompt_id": "qa_rubric_v1"
        }
    """
    results = []

    for audio_item in request.audio_sources:
        source = audio_item.source
        custom_audio_id = audio_item.audio_id
        
        # Basic validation before queuing
        if source.startswith("s3://") or source.startswith(("http://", "https://")):
            # For URLs, we don't validate existence upfront (just queue)
            pass
        elif not Path(source).exists():
            results.append({
                "source": source,
                "error": "Local file not found — skipped.",
            })
            continue
        
        # Determine audio_id (use custom or generate new)
        if custom_audio_id:
            # Check if custom audio_id already exists
            existing = db.query(models.AudioRecord).filter_by(audio_id=custom_audio_id).first()
            if existing:
                results.append({
                    "source": source,
                    "audio_id": custom_audio_id,
                    "error": f"Audio ID '{custom_audio_id}' already exists. Skipping.",
                })
                continue
            unique_audio_id = custom_audio_id
        else:
            unique_audio_id = str(uuid.uuid4())
        
        new_record = models.AudioRecord(
            audio_id   = unique_audio_id,
            prompt_id  = request.prompt_id,
            source_url = source,
            audio_path = None,        # filled in by the worker
            status     = "pending",
            notify_url = request.notify_url,
        )
        db.add(new_record)
        db.commit()

        background_tasks.add_task(_process_audio, unique_audio_id)

        results.append({
            "source": source,
            "audio_id": unique_audio_id,
            # Removed "custom_id_provided" here
            **_status_payload("pending"),
        })

    return {
        "message": (
            "Jobs queued. Poll GET /status/{audio_id} for progress. "
            "If notify_url was set, a POST is fired when each job finishes."
        ),
        "prompt_id": request.prompt_id,
        "notify_url": request.notify_url,
        "total_items": len(results),
        "details": results,
    }


@app.post("/process-audio/batch/")
def process_audio_batch(
    request: AudioRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Alias for /process-audio/ - same functionality.
    """
    return process_audio(request, background_tasks, db)


@app.get("/status/{audio_id}")
def check_status(audio_id: str, db: Session = Depends(get_db)):
    """Return current phase and, once completed, the transcript + TVS rating."""
    record = db.query(models.AudioRecord).filter_by(audio_id=audio_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Audio ID not found")

    phase = record.status or "unknown"
    err   = record.error_detail

    # Fetch the associated prompt text strictly for informational response metadata, if necessary
    prompt_text = None
    prompt_record = None
    if record.prompt_id:
        prompt_record = (
            db.query(models.PromptRecord)
            .filter_by(prompt_id=record.prompt_id)
            .first()
        )
        if prompt_record:
            prompt_text = prompt_record.prompt

    response = {
        "audio_id":   audio_id,
        "prompt_id":  record.prompt_id,
        #"prompt":     prompt_text,
        "source_url": record.source_url,
        "audio_path": record.audio_path,
        **_status_payload(phase, err if phase == "failed" else None),
    }

    if phase == "completed":
        transcript = (
            db.query(models.TranscriptResult)
            .filter_by(audio_id=audio_id)
            .first()
        )

        if transcript:
            response["transcript"] = transcript.transcript_text or ""
            
            # If you want english translation in the payload, uncomment:
            # if transcript.english_translation:
            #     response["english_translation"] = transcript.english_translation
            
            # --- Read TVS Rating straight from the database ---
            response["rating_json"] = transcript.rating_json

    return response

@app.get("/audio-ids/")
def list_audio_ids(
    skip: int = 0, 
    limit: int = 100, 
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    List all audio IDs with their status.
    Optional filter by status.
    """
    query = db.query(models.AudioRecord)
    
    if status:
        query = query.filter_by(status=status)
    
    records = query.offset(skip).limit(limit).all()
    
    return {
        "total": query.count(),
        "skip": skip,
        "limit": limit,
        "audio_ids": [
            {
                "audio_id": r.audio_id,
                "status": r.status,
                "prompt_id": r.prompt_id,
                "created_at": getattr(r, 'created_at', None)  # Add created_at to model if needed
            }
            for r in records
        ]
    }


@app.post("/prompts/")
async def create_prompt(
    service_name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a .md file to save as a prompt.
    prompt_id and index are generated automatically.
    """
    # 1. Read the uploaded markdown file
    content = await file.read()
    markdown_text = content.decode("utf-8")

    # 2. Automatically generate a unique prompt_id
    unique_prompt_id = str(uuid.uuid4())

    # 3. Save to database
    new_prompt = models.PromptRecord(
        prompt_id=unique_prompt_id,
        prompt=markdown_text,
        service_name=service_name
    )
    
    db.add(new_prompt)
    db.commit()
    db.refresh(new_prompt)
    
    return {
        "message": "Markdown prompt successfully saved.",
        "index": new_prompt.id,
        "prompt_id": new_prompt.prompt_id,
        "service_name": new_prompt.service_name
    }


@app.get("/prompts/{prompt_id}")
def get_prompt(prompt_id: str, db: Session = Depends(get_db)):
    """
    Fetch a prompt configuration by its auto-generated prompt_id.
    """
    record = db.query(models.PromptRecord).filter(models.PromptRecord.prompt_id == prompt_id).first()
    
    if not record:
        raise HTTPException(status_code=404, detail="Prompt ID not found")

    return {
        "index": record.id,
        "prompt_id": record.prompt_id,
        "service_name": record.service_name,
        "prompt": record.prompt # Returns the raw Markdown string
    }


@app.get("/prompts/", response_model=Page[PromptListResponse])
def list_prompts(
    db: Session = Depends(get_db),
    params: Params = Depends()   # Params injects ?page=1&size=50
):
    """
    Fetch a paginated list of all saved prompts.
    Does NOT include the actual prompt text to keep the response lightweight.
    
    Query Params:
        page: Page number (default: 1)
        size: Results per page (default: 50, max: 100)
    """
    query = db.query(models.PromptRecord).order_by(models.PromptRecord.id.desc())
    
    return paginate(db, query, params)


# Initialize fastapi-pagination
add_pagination(app)
