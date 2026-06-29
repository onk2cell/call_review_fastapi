"""
Prompt builder — turn a source file (PDF or rubric .md/.txt) into a structured
call-QA scoring prompt using Gemini.

Flow:  file bytes -> markdown -> Gemini drafts a scoring prompt -> user verifies.

Dependencies:
    pip install google-genai pymupdf4llm
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

try:  # load .env when run standalone
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Reuse pricing + cost helper from the Gemini pipeline (single source of truth)
from gemini_pipeline import DEFAULT_MODEL, PRICING, _cost_inr

SUPPORTED_EXTS = {".pdf", ".md", ".markdown", ".txt"}

DRAFT_SYSTEM = """You are an expert at writing call-quality-assurance scoring prompts.

You receive SOURCE MATERIAL (a rubric, QA guidelines, SOP, or notes — possibly
extracted from a PDF). Turn it into a single, clean Markdown PROMPT that another
LLM will use to score a call-center AGENT on a recorded call.

The prompt you write MUST:
- State the context (this is a TVS lead-qualification / sales call; speakers are
  AGENT and CUSTOMER; score the AGENT only).
- List clear, numbered scoring criteria (each scored 0-5) derived from the source.
- Define overall_score as the rounded average of the criteria (integer 0-5) and a
  grade A/B/C/D/F.
- Instruct the model to return ONLY a JSON object (overall_score, grade, summary,
  criteria[name,score,feedback], strengths[], improvements[]).
- Be self-contained and unambiguous.

Output ONLY the prompt Markdown — no preamble, no code fences, no commentary.
"""


def extract_markdown(filename: str, data: bytes) -> str:
    """Extract markdown/plain text from a PDF or rubric file (by extension)."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        import pymupdf            # PyMuPDF
        import pymupdf4llm
        doc = pymupdf.open(stream=data, filetype="pdf")
        return pymupdf4llm.to_markdown(doc)
    if ext in (".md", ".markdown", ".txt"):
        return data.decode("utf-8", errors="replace")
    raise ValueError(
        f"Unsupported file type '{ext}'. Allowed: {sorted(SUPPORTED_EXTS)}"
    )


def draft_prompt_from_source(
    source_markdown: str,
    service_name: str,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Draft a scoring prompt from source markdown using Gemini.
    Returns {"prompt": <markdown>, "usage": {...}}.
    """
    source_markdown = (source_markdown or "").strip()
    if not source_markdown:
        raise ValueError("Source material is empty.")

    model = model or DEFAULT_MODEL
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Set GEMINI_API_KEY (env var) or pass api_key=...")

    user = (
        f"SERVICE: {service_name}\n\n"
        f"SOURCE MATERIAL:\n{source_markdown}\n\n"
        "Write the scoring prompt now."
    )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=[DRAFT_SYSTEM, user],
        config=types.GenerateContentConfig(temperature=0.2),
    )

    prompt_md = (response.text or "").strip()

    usage = response.usage_metadata
    in_tok = usage.prompt_token_count or 0
    out_tok = (usage.candidates_token_count or 0) + (
        getattr(usage, "thoughts_token_count", 0) or 0
    )
    price = PRICING.get(model, PRICING[DEFAULT_MODEL])
    cost_inr = _cost_inr(in_tok, out_tok, price["text_input"], price["output"])

    return {
        "prompt": prompt_md,
        "usage": {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "cost_inr": round(cost_inr, 4),
            "model": model,
        },
    }


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        sys.exit("Usage: python prompt_builder.py <file.pdf|.md|.txt> [service_name]")
    path = Path(sys.argv[1])
    svc = sys.argv[2] if len(sys.argv) > 2 else "tvs_qa"
    md = extract_markdown(path.name, path.read_bytes())
    print(f"[extracted {len(md)} chars of markdown]\n")
    out = draft_prompt_from_source(md, svc)
    print("===== DRAFTED PROMPT =====\n")
    print(out["prompt"])
    print("\n===== USAGE =====")
    print(json.dumps(out["usage"], indent=2))
