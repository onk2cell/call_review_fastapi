# ---------------------------------------------------------------------------
# Call Review API — FastAPI app image
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# System deps: ffmpeg is required by pydub for the Gemini silence-trim step.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

EXPOSE 8000

# DB schema is created/migrated automatically on startup (main.py).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
