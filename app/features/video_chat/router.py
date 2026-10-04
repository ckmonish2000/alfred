import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.features.video_chat import service
from app.features.video_chat.models import Video, VideoChunk
from app.features.video_chat.schemas import ChunkRead, VideoCreate, VideoRead

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
