import re

from app.features.video_chat.pipeline.types import Chunk, Segment

_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _build(index: int, window: list[Segment]) -> Chunk:
    return Chunk(
        index=index,
        start=window[0].start,
        end=window[-1].end,
        text=" ".join(s.text for s in window),
    )


def chunk_segments(
    segments: list[Segment], max_chars: int, overlap_chars: int
) -> list[Chunk]:
    """Greedily merge segments into ~max_chars windows.

    Each new window starts with the trailing segments of the previous one
    (up to overlap_chars) so context isn't cut mid-thought. Segments are never
    split, so every chunk keeps exact start/end timestamps.
    """
    cleaned = [
        Segment(start=s.start, end=s.end, text=t)
        for s in segments
        if (t := _clean(s.text))
    ]

    chunks: list[Chunk] = []
    window: list[Segment] = []
    size = 0

    for seg in cleaned:
        seg_len = len(seg.text) + 1
        if window and size + seg_len > max_chars:
            chunks.append(_build(len(chunks), window))
            carry: list[Segment] = []
            carry_size = 0
            for prev in reversed(window):
                prev_len = len(prev.text) + 1
                if carry_size + prev_len > overlap_chars:
                    break
                carry.insert(0, prev)
                carry_size += prev_len
            window, size = carry, carry_size
        window.append(seg)
        size += seg_len

    if window:
        chunks.append(_build(len(chunks), window))
    return chunks
