# from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime
# from sqlalchemy.dialects.postgresql import JSONB
# from sqlalchemy.orm import relationship
# from sqlalchemy.sql import func
# from database import Base


# class AudioRecord(Base):
#     __tablename__ = "audio_records"

#     id           = Column(Integer, primary_key=True, index=True)
#     audio_id     = Column(String, unique=True, index=True, nullable=False)
#     prompt_id    = Column(String, index=True, nullable=False)
#     source_url   = Column(Text, nullable=True)   # original value passed in (local path or s3:// uri)
#     audio_path   = Column(Text, nullable=True)   # resolved local path (set after download if S3)
#     status       = Column(String, default="pending")
#     error_detail = Column(Text, nullable=True)
#     notify_url   = Column(Text, nullable=True)
#     created_at   = Column(DateTime(timezone=True), server_default=func.now())
#     updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

#     transcript = relationship("TranscriptResult", back_populates="audio", uselist=False)


# class TranscriptResult(Base):
#     __tablename__ = "transcript_results"

#     id                  = Column(Integer, primary_key=True, index=True)
#     audio_id            = Column(String, ForeignKey("audio_records.audio_id"), unique=True, nullable=False)
#     transcript_text     = Column(Text, nullable=True)
#     english_translation = Column(Text, nullable=True)
#     transcript_json     = Column(JSONB, nullable=True)
#     created_at          = Column(DateTime(timezone=True), server_default=func.now())

#     audio = relationship("AudioRecord", back_populates="transcript")


from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class AudioRecord(Base):
    __tablename__ = "audio_records"

    id           = Column(Integer, primary_key=True, index=True)
    audio_id     = Column(String, unique=True, index=True, nullable=False)
    prompt_id    = Column(String, index=True, nullable=False)
    source_url   = Column(Text, nullable=True)   # original value passed in (local path or s3:// uri)
    audio_path   = Column(Text, nullable=True)   # resolved local path (set after download if S3)
    status       = Column(String, default="pending")
    error_detail = Column(Text, nullable=True)
    notify_url   = Column(Text, nullable=True)
    vendor       = Column(String, nullable=False, default="groq")   # groq | gemini
    gemini_model = Column(String, nullable=True)                    # model used (gemini jobs)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    transcript = relationship("TranscriptResult", back_populates="audio", uselist=False)


class TranscriptResult(Base):
    __tablename__ = "transcript_results"

    id                  = Column(Integer, primary_key=True, index=True)
    audio_id            = Column(String, ForeignKey("audio_records.audio_id"), unique=True, nullable=False)
    transcript_text     = Column(Text, nullable=True)
    english_translation = Column(Text, nullable=True)
    transcript_json     = Column(JSONB, nullable=True)
    rating_json         = Column(JSONB, nullable=True) # <-- NEW COLUMN ADDED HERE
    usage_json          = Column(JSONB, nullable=True) # token counts + ₹ cost per job
    created_at          = Column(DateTime(timezone=True), server_default=func.now())

    audio = relationship("AudioRecord", back_populates="transcript")


class PromptRecord(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True) # Automatically creates your 1, 2, 3 index
    prompt_id = Column(String, unique=True, index=True, nullable=False) # Auto-generated ID
    prompt = Column(Text, nullable=False)  # Stores the raw Markdown text
    service_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")     # draft | verified
    source = Column(String, nullable=False, default="manual")    # manual | pdf | md
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AppSetting(Base):
    """Simple key/value store for admin-configurable settings (e.g. gemini_model)."""
    __tablename__ = "app_settings"

    id    = Column(Integer, primary_key=True, index=True)
    key   = Column(String, unique=True, index=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())