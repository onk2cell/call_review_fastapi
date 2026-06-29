# AI Call Review & Transcription API

An AI-powered FastAPI backend for automated call transcription, speaker diarization, multilingual translation, and call-quality scoring.

It processes call recordings (local path, HTTP URL, or AWS S3) and produces a diarized English transcript plus a rubric-based QA score. There are **two interchangeable processing vendors**, selectable per request:

- **Groq vendor** — PyAnnote diarization + RunPod/Groq Whisper transcription + Groq LLM scoring (parallel pipeline).
- **Gemini vendor** — a single Gemini call does transcription + diarization + English translation, then a cheap text-only Gemini call scores the transcript. No PyAnnote/Whisper needed. Includes silence-trimming and per-call token tracking.

It also ships an **admin dashboard** for usage metrics and live model selection, and a **prompt builder** that turns a PDF or rubric file into a scoring prompt.

---

## Features

- FastAPI-based REST API
- **Two vendors** (Groq or Gemini) selectable per `/process-audio` request
- **Gemini single-call** transcription + diarization + translation + scoring
- Groq Whisper / PyAnnote pipeline with automatic transcript alignment
- **PDF / rubric → scoring prompt** generation (`/prompts/from-file`), with draft → verify-in-place workflow
- **Admin dashboard** (`/admin`): live model catalog, vendor/model selection, usage metrics (tokens, call-minutes) — Basic-auth from `.env`
- Per-call **token usage** stored in the DB
- Silence-trimming for Gemini (lower audio token cost)
- Sources: local path, public HTTP/HTTPS URL, AWS S3
- Background task processing, status tracking, webhook notifications
- PostgreSQL + pagination
- Docker-ready (app + Postgres via `docker compose`)

---

## Tech Stack

### Backend

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL

### AI & Audio Processing

- Google Gemini (transcription + diarization + translation + scoring)
- Groq Whisper Large V3 / Groq LLM scoring
- PyAnnote AI (diarization)
- FFmpeg + Pydub (silence-trim)
- pymupdf4llm (PDF → markdown for prompt building)

### Cloud & Storage

- AWS S3
- Boto3

---

## Project Structure

```bash
.
├── main.py                     # FastAPI app + routes (process-audio, prompts, admin)
├── call_audio_pipeline.py      # Groq vendor pipeline (PyAnnote + RunPod/Whisper)
├── aligned_transcript.py       # Transcript alignment logic
├── gemini_pipeline.py          # Gemini vendor: transcribe/diarize/translate + rating
├── prompt_builder.py           # PDF/rubric -> Gemini-drafted scoring prompt
├── admin_core.py               # Admin settings store, live model catalog, auth
├── database.py                 # DB config + idempotent schema migration
├── models.py                   # SQLAlchemy models
├── requirements.txt            # Project dependencies
├── Dockerfile                  # App image (Python + ffmpeg)
├── docker-compose.yml          # App + Postgres
└── .env                        # Environment variables (not committed)
```

---

## Installation

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd <project-folder>
```

---

### 2. Create Virtual Environment

```bash
python -m venv venv
```

Activate environment:

#### Windows

```bash
venv\Scripts\activate
```

#### Linux / Mac

```bash
source venv/bin/activate
```

---

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file:

```env
# Database
DATABASE_URL=postgresql://username:password@localhost:5432/db_name

# Gemini vendor
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash-lite      # default Gemini model

# Groq vendor
GROQ_API_KEY=your_groq_api_key

# Groq-vendor diarization + transcription
PYANNOTE_API_KEY=your_pyannote_api_key
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_ENDPOINT_ID=your_runpod_endpoint_id

# Admin dashboard login (/admin)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_me

# AWS S3 (Optional)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=ap-south-1

# Storage
AUDIO_STORAGE_DIR=audio_files
```

> `.env` is git-ignored — never commit your keys.

---

## Run the Application

### Development

```bash
uvicorn main:app --reload
```

### Production

```bash
gunicorn -k uvicorn.workers.UvicornWorker main:app
```

---

## API Endpoints

### Process audio (choose vendor)

```http
POST /process-audio/
```

```json
{
  "vendor": "gemini",                       // "groq" (default) or "gemini"
  "gemini_model": "gemini-2.5-flash-lite",  // optional per-request override
  "prompt_id": "<verified prompt id>",
  "audio_sources": [
    { "audio_id": "call_01", "source": "C:\\path\\to\\call.wav" }
  ],
  "notify_url": null
}
```

- `vendor` / `gemini_model` fall back to the admin dashboard settings, then to defaults.
- `source` may be a local path, HTTP/HTTPS URL, or `s3://` URI.
- Returns immediately; jobs run in the background.

### Check status / results

```http
GET /status/{audio_id}
```

Returns phase (`pending → processing_audio → processing_rating → completed`, or the
Groq-vendor phases), and once complete: `transcript`, `rating_json`, token `usage`,
`vendor`, `gemini_model`.

### Prompts (PDF / rubric → scoring prompt)

```http
POST /prompts/from-file     # upload a PDF or .md/.txt -> Gemini drafts a prompt (status=draft)
GET  /prompts/{prompt_id}   # review
PUT  /prompts/{prompt_id}   # edit/approve IN PLACE (same prompt_id; set status=verified)
POST /prompts/              # legacy: upload a .md prompt directly
GET  /prompts/              # paginated list
```

### Admin (Basic auth from `.env`)

```http
GET  /admin                 # HTML dashboard (usage metrics + model selection)
GET  /admin/models          # live model catalog (gemini + groq)
GET  /admin/settings        # current vendor + per-vendor model
POST /admin/settings        # set active_vendor / gemini_model / groq_model
GET  /admin/dashboard       # JSON aggregates (jobs, call-minutes, tokens)
```

### Audio records

```http
GET /audio-ids/             # list audio ids + status
```

---

## Processing Pipelines

**Gemini vendor**

1. Resolve + (optionally) download audio, trim silence
2. One Gemini call → diarized segments + English translation
3. Text-only Gemini call → rubric-based score
4. Store transcript + rating + token usage

**Groq vendor**

1. Resolve audio
2. PyAnnote diarization ‖ RunPod/Whisper transcription (parallel)
3. Transcript alignment
4. Groq LLM scoring against the prompt
5. Store transcript + rating

---

## Supported Audio Sources

- Local uploads
- Public HTTP/HTTPS audio URLs
- AWS S3 presigned URLs

---

## Use Cases

- Call center quality monitoring
- CRM call review systems
- Customer-agent conversation analysis
- AI-based voice analytics
- Automated multilingual transcription systems

---

## Future Improvements

- CRM integration
- Real-time streaming transcription
- Sentiment analysis
- Script compliance detection
- AI-generated call summaries
- Dashboard analytics

---

## API Documentation

After running the server:

### Swagger UI

```bash
http://127.0.0.1:8000/docs
```

### ReDoc

```bash
http://127.0.0.1:8000/redoc
```

---

## Call Review Pipeline Deployment Guide

Prerequisites:

Install Docker Desktop (for Mac/Windows) or Docker Engine (for Linux).

## Step 1: Setup Credentials

Create a file named .env in the root directory.

Add your API keys:

Plaintext
DATABASE_URL=postgresql://myuser:root@db:5432/call_review_db
GROQ_API_KEY=your_key_here
PYANNOTE_API_KEY=your_key_here

## Step 2: Start the Server

Open your terminal in this folder and run:

```bash
docker compose up -d --build
```

Note: The first time you run this, it will take a few minutes to download the requirements. The database tables will be created automatically.

Step 3: Access the Application

The API is now running at: http://localhost:8000

View the interactive API documentation at: http://localhost:8000/docs

Maintenance Commands:

To view live application logs:

```bash
docker compose logs -f web
```

To stop the server safely:

```bash
docker compose down
```

With these files, your client can take your codebase, run one command (docker compose up -d --build), and have a fully functioning, production-grade API and database running on their machine!
