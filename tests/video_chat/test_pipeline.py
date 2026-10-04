import pytest

from app.features.video_chat.pipeline.chunking import chunk_segments
from app.features.video_chat.pipeline.metadata import parse_youtube_id
from app.features.video_chat.pipeline.types import Segment


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
    ],
)
def test_parse_youtube_id(url):
    assert parse_youtube_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://vimeo.com/123",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/@channel",
        "https://evil.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_parse_youtube_id_rejects(url):
    assert parse_youtube_id(url) is None


def _segs(n: int, text: str = "word " * 9) -> list[Segment]:
    return [Segment(start=i * 2.0, end=i * 2.0 + 2.0, text=text) for i in range(n)]


def test_chunks_respect_max_and_keep_timestamps():
    chunks = chunk_segments(_segs(30), max_chars=120, overlap_chars=0)
    assert len(chunks) > 1
    assert all(len(c.text) <= 120 for c in chunks)
    assert chunks[0].start == 0.0
    assert chunks[-1].end == 60.0
    assert [c.index for c in chunks] == list(range(len(chunks)))
    # no overlap: each chunk starts where the previous ended
    for a, b in zip(chunks, chunks[1:]):
        assert b.start == a.end


def test_chunks_overlap():
    chunks = chunk_segments(_segs(30), max_chars=120, overlap_chars=50)
    for a, b in zip(chunks, chunks[1:]):
        assert b.start < a.end


def test_chunking_cleans_whitespace_and_drops_empty():
    segs = [Segment(0, 1, "  hello\n world "), Segment(1, 2, "   "), Segment(2, 3, "bye")]
    [chunk] = chunk_segments(segs, max_chars=1000, overlap_chars=0)
    assert chunk.text == "hello world bye"
    assert (chunk.start, chunk.end) == (0, 3)


def test_oversized_segment_becomes_own_chunk():
    segs = [Segment(0, 1, "a"), Segment(1, 2, "x" * 500), Segment(2, 3, "b")]
    chunks = chunk_segments(segs, max_chars=100, overlap_chars=0)
    assert [c.text for c in chunks] == ["a", "x" * 500, "b"]
