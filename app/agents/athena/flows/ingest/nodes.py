import logging

from app.agents.athena.indexing import index_transcript
from app.agents.athena.models import TranscriptSource, Video, VideoStatus
from app.core.config import settings
from app.core.db import SessionLocal
from app.runtime.dispatch import spawn
from app.tools import youtube

logger = logging.getLogger(__name__)


def load_video(state: dict) -> dict:
    with SessionLocal() as db:
        video = db.get_one(Video, state["video_id"])
        video.status = VideoStatus.processing
        db.commit()
        return {"youtube_id": video.youtube_id}


def fetch_metadata(state: dict) -> dict:
    meta = youtube.fetch_metadata(state["youtube_id"])
    with SessionLocal() as db:
        video = db.get_one(Video, state["video_id"])
        video.title = meta.title
        video.channel = meta.channel
        video.description = meta.description
        video.duration_sec = meta.duration_sec
        video.thumbnail_url = meta.thumbnail_url
        video.language = meta.language
        db.commit()
    return {"language": meta.language}


def fetch_transcript(state: dict) -> dict:
    languages = [state["language"]] if state.get("language") else []
    languages += [lang for lang in settings.transcript_languages if lang not in languages]
    result = youtube.fetch_transcript(state["youtube_id"], languages)
    if result is None:
        return {}
    segments, language = result
    return {"segments": segments, "language": language}


def index(state: dict) -> dict:
    count = index_transcript(
        state["video_id"], state["segments"], TranscriptSource.youtube, state.get("language")
    )
    logger.info("Indexed %d chunks from YouTube captions", count)
    return {}


def request_transcription(state: dict) -> dict:
    child = spawn("athena.transcribe", {"video_id": str(state["video_id"])})
    logger.info("No captions; queued transcription run %s", child.run_id)
    return {}
