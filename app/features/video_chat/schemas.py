import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl

from app.features.video_chat.models import TranscriptSource, VideoStatus


class VideoCreate(BaseModel):
    url: HttpUrl


class VideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    youtube_id: str
    url: str
    title: str | None
    channel: str | None
    duration_sec: int | None
    thumbnail_url: str | None
    language: str | None
    status: VideoStatus
    transcript_source: TranscriptSource | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_index: int
    start_sec: float
    end_sec: float
    text: str
