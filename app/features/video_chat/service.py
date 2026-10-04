import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.features.video_chat.graph import ingest_graph
from app.features.video_chat.models import Video, VideoStatus
from app.features.video_chat.pipeline.audio import delete_audio
from app.features.video_chat.pipeline.metadata import canonical_url, parse_youtube_id

logger = logging.getLogger(__name__)


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


def ingest_video(video_id: uuid.UUID) -> None:
    """Run the ingestion graph for one video. Blocking; meant for a background task."""
    with SessionLocal() as db:
        video = db.get_one(Video, video_id)
        video.status = VideoStatus.processing
        db.commit()
        youtube_id = video.youtube_id

    try:
        ingest_graph.invoke({"video_id": video_id, "youtube_id": youtube_id})
    except Exception as exc:
        logger.exception("Ingestion failed for video %s (%s)", video_id, youtube_id)
        with SessionLocal() as db:
            video = db.get_one(Video, video_id)
            video.status = VideoStatus.failed
            video.error = f"{type(exc).__name__}: {exc}"
            db.commit()
    finally:
        delete_audio(youtube_id)
