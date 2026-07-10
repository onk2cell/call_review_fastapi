"""
Tests for the rating-only fallback flow (no real API calls — Gemini is mocked).

Covers:
  1. Normal path: transcription succeeds on the primary model -> full result.
  2. Primary overloaded (503 on every retry) -> PrimaryModelOverloaded raised
     (transcription must NOT silently fall back to the pricier model).
  3. rate_audio_only: returns rating JSON + usage (audio tokens, model) and
     never generates a transcript field.
  4. rate_audio_only when even the fallback model is overloaded -> raises.

Run:  python test_rating_only_fallback.py   (exit code 0 = all pass)
"""

import json
import sys
import tempfile
from pathlib import Path

import gemini_pipeline as gp

gp._RETRY_DELAYS = (0, 0, 0)  # no real sleeps in tests

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeUsage:
    prompt_token_count = 1000
    candidates_token_count = 200
    thoughts_token_count = 0


class FakeCand:
    finish_reason = "STOP"


class FakeResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload)
        self.candidates = [FakeCand()]
        self.usage_metadata = FakeUsage()


class FakeModels:
    """overload_models: set of model names that always raise 503."""
    def __init__(self, payload, overload_models=()):
        self.payload = payload
        self.overload = set(overload_models)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        if model in self.overload:
            raise RuntimeError("503 UNAVAILABLE: The model is overloaded")
        return FakeResponse(self.payload)


class FakeClient:
    def __init__(self, models):
        self.models = models


def fake_client_factory(models_obj):
    class _Factory:
        def __init__(self, api_key=None):
            self.models = models_obj
    return _Factory


# temp fake audio file (content irrelevant; trim_silence=False)
_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
_tmp.write(b"RIFFfakewavdata")
_tmp.close()
AUDIO = Path(_tmp.name)

TRANSCRIPT_PAYLOAD = {"segments": [
    {"speaker": "AGENT", "text": "Hello from TVS."},
    {"speaker": "CUSTOMER", "text": "Tell me the price."},
]}
RATING_PAYLOAD = {
    "overall_score": 4, "grade": "B", "summary": "Good call.",
    "criteria": [{"name": "Greeting", "score": 4, "feedback": "Fine."}],
    "strengths": ["Polite"], "improvements": ["Discuss EMI"],
}


# ---------------------------------------------------------------------------
# 1. Normal path — transcription succeeds on primary
# ---------------------------------------------------------------------------
m = FakeModels(TRANSCRIPT_PAYLOAD)
gp.genai.Client = fake_client_factory(m)
r = gp.transcribe_diarize_translate(AUDIO, model="gemini-2.5-flash-lite",
                                    trim_silence=False, api_key="test")
check("1a normal path returns segments", len(r["segments"]) == 2)
check("1b transcript derived from segments", "AGENT: Hello from TVS." in r["english_transcript"])
check("1c stayed on primary model", r["usage"]["model"] == "gemini-2.5-flash-lite")
check("1d only primary model called", set(m.calls) == {"gemini-2.5-flash-lite"})

# ---------------------------------------------------------------------------
# 2. Primary overloaded — must raise, NOT fall back to pricier model
# ---------------------------------------------------------------------------
m = FakeModels(TRANSCRIPT_PAYLOAD, overload_models={"gemini-2.5-flash-lite"})
gp.genai.Client = fake_client_factory(m)
try:
    gp.transcribe_diarize_translate(AUDIO, model="gemini-2.5-flash-lite",
                                    trim_silence=False, api_key="test")
    check("2a raises PrimaryModelOverloaded", False, "no exception raised")
except gp.PrimaryModelOverloaded:
    check("2a raises PrimaryModelOverloaded", True)
except Exception as e:
    check("2a raises PrimaryModelOverloaded", False, f"wrong exception: {e}")
check("2b never called fallback model for transcription",
      gp.FALLBACK_MODEL not in m.calls, f"calls={m.calls}")
check("2c retried primary 4 times", m.calls.count("gemini-2.5-flash-lite") == 4,
      f"calls={m.calls}")

# ---------------------------------------------------------------------------
# 3. rate_audio_only — rating JSON + usage, no transcript anywhere
# ---------------------------------------------------------------------------
m = FakeModels(RATING_PAYLOAD)
gp.genai.Client = fake_client_factory(m)
r = gp.rate_audio_only(AUDIO, rubric="Score the agent 0-5 on greeting.",
                       trim_silence=False, api_key="test")
check("3a rating data parsed", r["data"]["grade"] == "B" and r["data"]["overall_score"] == 4)
check("3b usage has audio_input_tokens", r["usage"]["audio_input_tokens"] == 1000)
check("3c ran on fallback model by default", r["usage"]["model"] == gp.FALLBACK_MODEL)
check("3d no transcript in result", "english_transcript" not in r and "segments" not in r)
check("3e empty rubric rejected", True)  # exercised below
try:
    gp.rate_audio_only(AUDIO, rubric="  ", trim_silence=False, api_key="test")
    check("3f empty rubric raises ValueError", False, "no exception")
except ValueError:
    check("3f empty rubric raises ValueError", True)

# ---------------------------------------------------------------------------
# 4. rate_audio_only when fallback model ALSO overloaded — raises (job fails)
# ---------------------------------------------------------------------------
m = FakeModels(RATING_PAYLOAD, overload_models={gp.FALLBACK_MODEL})
gp.genai.Client = fake_client_factory(m)
try:
    gp.rate_audio_only(AUDIO, rubric="Score it.", trim_silence=False, api_key="test")
    check("4a raises when fallback overloaded too", False, "no exception")
except Exception:
    check("4a raises when fallback overloaded too", True)

# ---------------------------------------------------------------------------
AUDIO.unlink(missing_ok=True)
print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("ALL TESTS PASSED")
