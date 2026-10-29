"""Athena's own endpoints: reading videos, and adding one by URL.

Starting work still goes through runtime.dispatch(), never a graph directly.
Chat lives on the generic runtime endpoint: POST /agents/athena/flows/chat/runs
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.athena import service
from app.agents.athena.models import Video, VideoChunk
from app.agents.athena.schemas import ChunkRead, VideoCreate, VideoCreated, VideoRead
from app.core.db import get_db
from app.runtime.dispatch import dispatch
from app.runtime.http import api_invocation

router = APIRouter(tags=["athena"])


@router.post("/videos", response_model=VideoCreated, status_code=status.HTTP_202_ACCEPTED)
def create_video(body: VideoCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    """Register a video and queue athena.ingest. A known video is returned as-is (200)."""
    try:
        video, needs_ingest = service.get_or_create_video(db, str(body.url))
    except service.InvalidYouTubeUrl as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    if not needs_ingest:
        response.status_code = status.HTTP_200_OK
        return _created(video, run_id=None)

    run = dispatch(api_invocation("athena.ingest", {"video_id": str(video.id)}, request))
    response.headers["X-Run-Id"] = str(run.run_id)
    response.headers["X-Trace-Id"] = run.trace_id
    return _created(video, run_id=run.run_id)


def _created(video: Video, run_id: uuid.UUID | None) -> VideoCreated:
    return VideoCreated(**VideoRead.model_validate(video).model_dump(), run_id=run_id)


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
