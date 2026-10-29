import logging

from app.agents.athena.indexing import index_transcript
from app.agents.athena.models import TranscriptSource, Video
from app.core.db import SessionLocal
from app.tools import whisper, youtube

logger = logging.getLogger(__name__)


def load_video(state: dict) -> dict:
    with SessionLocal() as db:
        return {"youtube_id": db.get_one(Video, state["video_id"]).youtube_id}


def download_audio(state: dict) -> dict:
    return {"audio_path": youtube.download_audio(state["youtube_id"])}


def transcribe(state: dict) -> dict:
    try:
        segments, language = whisper.transcribe_audio(state["audio_path"])
    finally:
        youtube.delete_audio(state["youtube_id"])
    if not segments:
        raise ValueError("Whisper produced an empty transcript")
    return {"segments": segments, "language": language}


def index(state: dict) -> dict:
    count = index_transcript(
        state["video_id"], state["segments"], TranscriptSource.whisper, state.get("language")
    )
    logger.info("Indexed %d chunks from Whisper", count)
    return {}
