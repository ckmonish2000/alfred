import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.athena.models import Video, VideoStatus
from app.core.db import SessionLocal
from app.tools.youtube import canonical_url, delete_audio, parse_youtube_id


class InvalidYouTubeUrl(ValueError):
    pass


def get_or_create_video(db: Session, url: str) -> tuple[Video, bool]:
    """Return (video, needs_ingest).

    An existing video is reused; a previously failed one is reset so it can be retried.
    """
    youtube_id = parse_youtube_id(url)
    if youtube_id is None:
        raise InvalidYouTubeUrl(f"Not a YouTube video URL: {url}")

    video = db.scalar(select(Video).where(Video.youtube_id == youtube_id))
    if video is not None:
        if video.status != VideoStatus.failed:
            return video, False
        video.status = VideoStatus.pending
        video.error = None
        db.commit()
        return video, True

    video = Video(youtube_id=youtube_id, url=canonical_url(youtube_id))
    db.add(video)
    try:
        db.commit()
    except IntegrityError:
        # Another request inserted the same video concurrently.
        db.rollback()
        return db.scalars(select(Video).where(Video.youtube_id == youtube_id)).one(), False
    return video, True


def mark_failed(payload: dict, exc: BaseException) -> None:
    """on_failure hook for ingest/transcribe: surface the error on the video."""
    with SessionLocal() as db:
        video = db.get(Video, uuid.UUID(payload["video_id"]))
        if video is None:
            return
        video.status = VideoStatus.failed
        video.error = f"{type(exc).__name__}: {exc}"
        db.commit()


def mark_failed_and_delete_audio(payload: dict, exc: BaseException) -> None:
    mark_failed(payload, exc)
    with SessionLocal() as db:
        video = db.get(Video, uuid.UUID(payload["video_id"]))
        if video is not None:
            delete_audio(video.youtube_id)
