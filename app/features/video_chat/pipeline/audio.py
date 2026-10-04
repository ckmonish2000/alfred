import logging
from pathlib import Path

import yt_dlp

from app.core.config import settings
from app.features.video_chat.pipeline.metadata import canonical_url

logger = logging.getLogger(__name__)


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
