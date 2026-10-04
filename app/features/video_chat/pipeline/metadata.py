import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import yt_dlp

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
