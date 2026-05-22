# AI Call Review & Transcription API

An AI-powered FastAPI backend for automated call transcription, speaker diarization, and multilingual audio processing using Groq Whisper and PyAnnote.

This project processes call recordings from local uploads, HTTP URLs, or AWS S3 links and generates structured transcripts with speaker separation for call review systems, CRM integrations, and quality monitoring platforms.

---

## Features

- FastAPI-based REST API
- AI-powered transcription using Groq Whisper Large V3
- Speaker diarization using PyAnnote
- Parallel audio processing pipeline
- Supports:
  - Local audio uploads
  - Public audio URLs
  - AWS S3 audio files
- Background task processing
- Processing status tracking
- PostgreSQL database integration
- Pagination support
- Webhook notification support
- Automatic transcript alignment
- Docker-ready backend structure

---

## Tech Stack

### Backend

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL

### AI & Audio Processing

- Groq Whisper Large V3
- PyAnnote AI
- FFmpeg
- Pydub

### Cloud & Storage

- AWS S3
- Boto3

---

## Project Structure

```bash
.
├── main.py                     # FastAPI application entry point
├── call_audio_pipeline.py      # Audio processing pipeline
├── aligned_transcript.py       # Transcript alignment logic
├── database.py                 # Database configuration
├── models.py                   # SQLAlchemy models
├── requirements.txt            # Project dependencies
└── .env                        # Environment variables
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
DATABASE_URL=postgresql://username:password@localhost/db_name

# Groq API
GROQ_API_KEY=your_groq_api_key

# PyAnnote
PYANNOTE_API_KEY=your_pyannote_api_key

# AWS S3 (Optional)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=ap-south-1

# Storage
AUDIO_STORAGE_DIR=audio_files
```

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

### Upload & Process Audio

```http
POST /process-audio
```

Supports:

- File upload
- Audio URL
- S3 audio links

---

### Check Processing Status

```http
GET /status/{audio_id}
```

Returns:

- Current processing stage
- Transcript status
- Error details (if any)

---

### Get Audio Records

```http
GET /records
```

Paginated API for retrieving processed audio records.

---

## Processing Pipeline

1. Audio Upload / Download
2. Speaker Diarization
3. Whisper Transcription
4. Transcript Alignment
5. Database Storage
6. Response Generation

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
