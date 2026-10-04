import logging

import requests
from youtube_transcript_api import (
    NoTranscriptFound,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

from app.features.video_chat.pipeline.types import Segment

logger = logging.getLogger(__name__)


def fetch_youtube_transcript(
    youtube_id: str, languages: list[str]
) -> tuple[list[Segment], str] | None:
    """Return (segments, language_code) from YouTube captions, or None if unavailable.

    Prefers the requested languages (manual over auto-generated), then falls back
    to whatever transcript the video has.
    """
    try:
        transcripts = YouTubeTranscriptApi().list(youtube_id)
        try:
            transcript = transcripts.find_transcript(languages)
        except NoTranscriptFound:
            transcript = next(iter(transcripts), None)
            if transcript is None:
                return None
        fetched = transcript.fetch()
    except (YouTubeTranscriptApiException, requests.RequestException) as exc:
        logger.info("No YouTube transcript for %s: %s", youtube_id, type(exc).__name__)
        return None

    segments = [
        Segment(start=s.start, end=s.start + s.duration, text=s.text)
        for s in fetched.snippets
        if s.text.strip()
    ]
    if not segments:
        return None
    return segments, fetched.language_code
