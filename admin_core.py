"""
Admin core — settings store, live model catalog, and admin auth.

- Settings persist in the `app_settings` table (vendor + per-vendor model).
- Model catalog is fetched LIVE from each provider so the admin only sees
  models the configured API key can actually use.
- Auth is HTTP Basic, credentials from .env (ADMIN_USERNAME / ADMIN_PASSWORD).
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import models


# ---------------------------------------------------------------------------
# Settings store (app_settings table)
# ---------------------------------------------------------------------------
DEFAULTS: dict[str, str] = {
    "active_vendor": "groq",
    "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
    "groq_model": "llama-3.3-70b-versatile",
    "max_output_tokens": "32768",   # Gemini transcription output cap
}


def get_setting(db, key: str, default: str | None = None) -> str | None:
    row = db.query(models.AppSetting).filter_by(key=key).first()
    if row and row.value is not None:
        return row.value
    return DEFAULTS.get(key, default)


def set_setting(db, key: str, value: str) -> str:
    row = db.query(models.AppSetting).filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.add(models.AppSetting(key=key, value=value))
    db.commit()
    return value


def all_settings(db) -> dict[str, str | None]:
    """Effective settings (stored value or default) for the keys we manage."""
    return {k: get_setting(db, k) for k in DEFAULTS}


# ---------------------------------------------------------------------------
# Live model catalog
# ---------------------------------------------------------------------------
def list_gemini_models(api_key: str | None = None) -> list[dict[str, str]]:
    """Gemini models that support generateContent (excludes tts/embedding)."""
    from google import genai
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []
    client = genai.Client(api_key=api_key)
    out: list[dict[str, str]] = []
    for m in client.models.list():
        name = m.name or ""
        acts = getattr(m, "supported_actions", None) or []
        if "generateContent" in acts and "gemini" in name and "tts" not in name:
            out.append({
                "id": name.replace("models/", ""),
                "label": getattr(m, "display_name", None) or name,
            })
    return sorted(out, key=lambda x: x["id"])


_GROQ_EXCLUDE = ("whisper", "tts", "guard", "orpheus")


def list_groq_models(api_key: str | None = None) -> list[dict[str, str]]:
    """Groq chat models usable for rating (excludes whisper/tts/guard)."""
    from groq import Groq
    api_key = api_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        return []
    g = Groq(api_key=api_key)
    out: list[dict[str, str]] = []
    for m in g.models.list().data:
        mid = m.id
        if any(x in mid for x in _GROQ_EXCLUDE):
            continue
        out.append({"id": mid, "label": mid})
    return sorted(out, key=lambda x: x["id"])


# ---------------------------------------------------------------------------
# Auth — HTTP Basic from .env
# ---------------------------------------------------------------------------
_security = HTTPBasic()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def require_admin(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    """FastAPI dependency: 401 unless Basic creds match ADMIN_USERNAME/PASSWORD."""
    ok_user = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    ok_pass = bool(ADMIN_PASSWORD) and secrets.compare_digest(
        credentials.password, ADMIN_PASSWORD
    )
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
