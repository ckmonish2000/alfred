import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.features.video_chat import chat, service
from app.features.video_chat.models import Video, VideoChunk, VideoStatus
from app.features.video_chat.schemas import ChatRequest, ChunkRead, VideoCreate, VideoRead

router = APIRouter(prefix="/video-chat", tags=["video-chat"])


@router.post("/videos", response_model=VideoRead, status_code=status.HTTP_202_ACCEPTED)
def create_video(
    body: VideoCreate,
    background: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        video, needs_ingest = service.get_or_create_video(db, str(body.url))
    except service.InvalidYouTubeUrl as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    if needs_ingest:
        background.add_task(service.ingest_video, video.id)
    else:
        response.status_code = status.HTTP_200_OK
    return video


@router.get("/videos", response_model=list[VideoRead])
def list_videos(limit: int = 50, db: Session = Depends(get_db)):
    return db.scalars(select(Video).order_by(Video.created_at.desc()).limit(limit)).all()


@router.get("/videos/{video_id}", response_model=VideoRead)
def get_video(video_id: uuid.UUID, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    return video


@router.get("/videos/{video_id}/chunks", response_model=list[ChunkRead])
def list_chunks(video_id: uuid.UUID, db: Session = Depends(get_db)):
    if db.get(Video, video_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    return db.scalars(
        select(VideoChunk)
        .where(VideoChunk.video_id == video_id)
        .order_by(VideoChunk.chunk_index)
    ).all()


@router.post("/videos/{video_id}/chat")
def chat_with_video(video_id: uuid.UUID, body: ChatRequest, db: Session = Depends(get_db)):
    """Answer a question about the video. Streams NDJSON events (see chat.stream_answer)."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    if video.status != VideoStatus.ready:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Video is {video.status.value}, not ready")

    # Retrieve before streaming so the DB session isn't needed inside the generator.
    try:
        query = chat.retrieval_query(body.history, body.message)
        sources = chat.retrieve(db, video.id, query, settings.chat_top_k)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Embedding service unavailable: {exc}"
        ) from exc
    messages = chat.build_messages(video, sources, body.history, body.message)
    return StreamingResponse(
        chat.stream_answer(messages, sources), media_type="application/x-ndjson"
    )
