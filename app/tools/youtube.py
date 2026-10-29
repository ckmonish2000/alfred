"""YouTube helpers: URL parsing, metadata, captions and audio download."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import yt_dlp
from youtube_transcript_api import (
    NoTranscriptFound,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

from app.core.config import settings
from app.tools.types import Segment

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/", "/v/")


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    title: str | None
    channel: str | None
    description: str | None
    duration_sec: int | None
    thumbnail_url: str | None
    language: str | None


def parse_youtube_id(url: str) -> str | None:
    """Extract the 11-char video id from any common YouTube URL shape."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    candidate: str | None = None

    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        else:
            for prefix in _PATH_PREFIXES:
                if parsed.path.startswith(prefix):
                    candidate = parsed.path[len(prefix) :].split("/")[0]
                    break

    return candidate if candidate and _ID_RE.match(candidate) else None


def canonical_url(youtube_id: str) -> str:
    return f"https://www.youtube.com/watch?v={youtube_id}"


def fetch_metadata(youtube_id: str) -> VideoMetadata:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(canonical_url(youtube_id), download=False)

    duration = info.get("duration")
    return VideoMetadata(
        title=info.get("title"),
        channel=info.get("channel") or info.get("uploader"),
        description=info.get("description"),
        duration_sec=int(duration) if duration is not None else None,
        thumbnail_url=info.get("thumbnail"),
        language=info.get("language"),
    )


def fetch_transcript(
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


def download_audio(youtube_id: str) -> Path:
    """Download the best audio-only stream as-is (faster-whisper decodes it directly)."""
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": str(settings.tmp_dir / f"{youtube_id}.%(ext)s"),
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(canonical_url(youtube_id), download=True)
        path = Path(ydl.prepare_filename(info))

    if not path.exists():
        raise FileNotFoundError(f"yt-dlp reported {path} but it was not written")
    return path


def delete_audio(youtube_id: str) -> None:
    """Remove the downloaded audio plus any partial/fragment files yt-dlp left behind."""
    if not settings.tmp_dir.exists():
        return
    for path in settings.tmp_dir.glob(f"{youtube_id}.*"):
        try:
            path.unlink()
        except OSError:
            logger.warning("Could not delete %s", path, exc_info=True)
