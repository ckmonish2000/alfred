import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.agents.athena.models import TranscriptSource, VideoStatus


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


class VideoCreated(VideoRead):
    run_id: uuid.UUID | None  # the ingest run, or None if the video was already known


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_index: int
    start_sec: float
    end_sec: float
    text: str


# Flow inputs: the payload contract for each flow, checked by the runtime.


class ChatInput(BaseModel):
    video_id: uuid.UUID
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = []


class IngestInput(BaseModel):
    video_id: uuid.UUID


class TranscribeInput(BaseModel):
    video_id: uuid.UUID


class RetryFailedInput(BaseModel):
    within_hours: int = 24

