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
    """
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE audio_records ADD COLUMN audio_path TEXT"))
            conn.commit()
            print("[DB] Added column: audio_path")
        except Exception:
            conn.rollback()  # already exists — fine

        try:
            conn.execute(text("ALTER TABLE audio_records DROP COLUMN audio_file"))
            conn.commit()
            print("[DB] Dropped column: audio_file")
        except Exception:
            conn.rollback()  # already gone — fine