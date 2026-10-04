from functools import lru_cache
from pathlib import Path

from faster_whisper import WhisperModel

from app.core.config import settings
from app.features.video_chat.pipeline.types import Segment


@lru_cache(maxsize=1)
def _model() -> WhisperModel:
    # Loaded lazily and kept in memory; first call downloads the weights.
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


def transcribe_audio(path: Path) -> tuple[list[Segment], str]:
    """Return (segments, detected_language)."""
    segments, info = _model().transcribe(str(path), vad_filter=True)
    result = [
        Segment(start=s.start, end=s.end, text=s.text)
        for s in segments  # generator: transcription happens while iterating
        if s.text.strip()
    ]
    return result, info.language
