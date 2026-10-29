from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Segment:
    """A timestamped piece of transcript, from YouTube captions or Whisper."""

    start: float
    end: float
    text: str
