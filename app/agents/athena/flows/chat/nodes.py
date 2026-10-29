"""Retrieval-augmented chat over one video's transcript chunks."""

from dataclasses import asdict, dataclass

import httpx
from fastapi import status
from langgraph.config import get_stream_writer
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agents.athena.models import Video, VideoChunk, VideoStatus
from app.agents.athena.schemas import ChatMessage
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.embeddings import embed_query
from app.core.llm import stream_chat
from app.runtime.spec import FlowError

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


def search_chunks(db: Session, video_id, question: str, k: int) -> list[Source]:
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


# --- graph nodes ---


def load_video(state: dict) -> dict:
    with SessionLocal() as db:
        video = db.get(Video, state["video_id"])
    if video is None:
        raise FlowError(status.HTTP_404_NOT_FOUND, "Video not found")
    if video.status != VideoStatus.ready:
        raise FlowError(status.HTTP_409_CONFLICT, f"Video is {video.status.value}, not ready")
    return {"video": video}


def retrieve(state: dict) -> dict:
    history = [ChatMessage.model_validate(m) for m in state.get("history", [])]
    query = retrieval_query(history, state["message"])
    try:
        with SessionLocal() as db:
            sources = search_chunks(db, state["video_id"], query, settings.chat_top_k)
    except httpx.HTTPError as exc:
        raise FlowError(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Embedding service unavailable: {exc}"
        ) from exc
    get_stream_writer()({"type": "sources", "sources": [asdict(s) for s in sources]})
    return {"sources": sources}


def generate(state: dict) -> dict:
    history = [ChatMessage.model_validate(m) for m in state.get("history", [])]
    messages = build_messages(state["video"], state["sources"], history, state["message"])
    write = get_stream_writer()
    for delta in stream_chat(messages):
        write({"type": "token", "text": delta})
    return {}
