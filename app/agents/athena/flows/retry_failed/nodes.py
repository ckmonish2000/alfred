import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.agents.athena.models import Video, VideoStatus
from app.core.db import SessionLocal
from app.runtime.dispatch import spawn

logger = logging.getLogger(__name__)


def requeue(state: dict) -> dict:
    since = datetime.now(UTC) - timedelta(hours=state["within_hours"])
    with SessionLocal() as db:
        videos = db.scalars(
            select(Video).where(Video.status == VideoStatus.failed, Video.updated_at >= since)
        ).all()
        for video in videos:
            video.status = VideoStatus.pending
            video.error = None
            # Same transaction as the status reset: both happen or neither does.
            spawn("athena.ingest", {"video_id": str(video.id)}, db=db)
        db.commit()
    logger.info("Re-queued %d failed videos", len(videos))
    return {}
