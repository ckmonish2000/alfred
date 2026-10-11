"""Retrieval-augmented chat over one video's transcript chunks."""

import json
import logging
from collections.abc import Iterator
from dataclasses import asdict, dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.embeddings import embed_query
from app.core.llm import stream_chat
from app.features.video_chat.models import Video, VideoChunk
from app.features.video_chat.schemas import ChatMessage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You answer questions about a YouTube video using only the transcript excerpts provided.

Video: {title}
Channel: {channel}

Rules:
- Base your answer only on the excerpts. If they don't contain the answer, say you couldn't find it in the video.
- Cite the moment you got information from with its start timestamp in square brackets, like [3:15].
- Be concise. Answer in the language of the question.

Transcript excerpts:
{context}"""


@dataclass(frozen=True, slots=True)
class Source:
    chunk_index: int
    start_sec: float
    end_sec: float
    text: str
    score: float


def format_ts(sec: float) -> str:
    s = int(sec)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def retrieval_query(history: list[ChatMessage], question: str) -> str:
    """Prepend the previous user question so follow-ups ("which one is faster?") still match."""
    previous = next((m.content for m in reversed(history) if m.role == "user"), None)
    return f"{previous}\n{question}" if previous else question


def retrieve(db: Session, video_id, question: str, k: int) -> list[Source]:
    """Top-k chunks of this video by cosine similarity, returned in timeline order."""
    query_vec = embed_query(question)
    # Keep scanning the HNSW index until k rows survive the video_id filter.
    db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    distance = VideoChunk.embedding.cosine_distance(query_vec)
    rows = db.execute(
        select(VideoChunk, distance.label("distance"))
        .where(VideoChunk.video_id == video_id)
        .order_by(distance)
        .limit(k)
    ).all()
    sources = [
        Source(
            chunk_index=c.chunk_index,
            start_sec=c.start_sec,
            end_sec=c.end_sec,
            text=c.text,
            score=round(1 - d, 4),
        )
        for c, d in rows
    ]
    return sorted(sources, key=lambda s: s.start_sec)


def build_messages(
    video: Video, sources: list[Source], history: list[ChatMessage], question: str
) -> list[dict[str, str]]:
    context = "\n\n".join(
        f"[{format_ts(s.start_sec)} - {format_ts(s.end_sec)}]\n{s.text}" for s in sources
    )
    system = SYSTEM_PROMPT.format(
        title=video.title or video.youtube_id,
        channel=video.channel or "unknown",
        context=context or "(no excerpts found)",
    )
    recent = history[-settings.chat_history_messages :] if settings.chat_history_messages else []
    return [
        {"role": "system", "content": system},
        *({"role": m.role, "content": m.content} for m in recent),
        {"role": "user", "content": question},
    ]


def _event(**data) -> str:
    return json.dumps(data) + "\n"


def stream_answer(messages: list[dict[str, str]], sources: list[Source]) -> Iterator[str]:
    """NDJSON events: one `sources`, many `token`, then `done` (or `error`)."""
    yield _event(type="sources", sources=[asdict(s) for s in sources])
    try:
        for delta in stream_chat(messages):
            yield _event(type="token", text=delta)
    except Exception as exc:
        logger.exception("Chat generation failed")
        yield _event(type="error", message=f"{type(exc).__name__}: {exc}")
        return
    yield _event(type="done")
