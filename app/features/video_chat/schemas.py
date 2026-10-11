import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

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


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = []


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_index: int
    start_sec: float
    end_sec: float
    text: str
