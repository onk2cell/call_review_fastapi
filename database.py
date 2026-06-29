import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_audio_records_schema():
    """
    Idempotent migration run on every startup.
    - Adds audio_path column if missing.
    - Drops old audio_file (LargeBinary) column if still present.
    - Adds vendor columns (two-vendor support), prompt status/source, usage_json.
    Each statement is wrapped individually so an already-applied change is a no-op.
    """
    # (table, "ALTER ... ADD COLUMN ...", log label)
    migrations = [
        ("audio_records",      "ALTER TABLE audio_records ADD COLUMN audio_path TEXT",                       "audio_records.audio_path"),
        ("audio_records",      "ALTER TABLE audio_records ADD COLUMN vendor VARCHAR DEFAULT 'groq'",         "audio_records.vendor"),
        ("audio_records",      "ALTER TABLE audio_records ADD COLUMN gemini_model VARCHAR",                  "audio_records.gemini_model"),
        ("transcript_results", "ALTER TABLE transcript_results ADD COLUMN usage_json JSONB",                 "transcript_results.usage_json"),
        ("prompts",            "ALTER TABLE prompts ADD COLUMN status VARCHAR DEFAULT 'draft'",              "prompts.status"),
        ("prompts",            "ALTER TABLE prompts ADD COLUMN source VARCHAR DEFAULT 'manual'",             "prompts.source"),
        ("prompts",            "ALTER TABLE prompts ADD COLUMN created_at TIMESTAMPTZ DEFAULT now()",        "prompts.created_at"),
        ("prompts",            "ALTER TABLE prompts ADD COLUMN updated_at TIMESTAMPTZ",                      "prompts.updated_at"),
    ]

    with engine.connect() as conn:
        for _table, stmt, label in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"[DB] Added column: {label}")
            except Exception:
                conn.rollback()  # already exists — fine

        # Drop legacy column if still present
        try:
            conn.execute(text("ALTER TABLE audio_records DROP COLUMN audio_file"))
            conn.commit()
            print("[DB] Dropped column: audio_file")
        except Exception:
            conn.rollback()  # already gone — fine