"""Shared last step of ingest and transcribe: chunk, embed, store, announce."""

import uuid

from sqlalchemy import delete

from app.agents.athena.chunking import chunk_segments
from app.agents.athena.models import TranscriptSource, Video, VideoChunk, VideoStatus
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.embeddings import embed_documents
from app.runtime.events import emit
from app.tools.types import Segment


def index_transcript(
    video_id: uuid.UUID,
    segments: list[Segment],
    source: TranscriptSource,
    language: str | None,
) -> int:
    """Replace the video's chunks, mark it ready and emit athena.video_ready. Returns chunk count."""
    chunks = chunk_segments(segments, settings.chunk_max_chars, settings.chunk_overlap_chars)
    vectors = embed_documents([c.text for c in chunks])

    with SessionLocal() as db:
        video = db.get_one(Video, video_id)
        # Replace any chunks from a previous attempt, so a retry is safe.
        db.execute(delete(VideoChunk).where(VideoChunk.video_id == video.id))
        db.add_all(
            VideoChunk(
                video_id=video.id,
                chunk_index=c.index,
                start_sec=c.start,
                end_sec=c.end,
                text=c.text,
                embedding=v,
            )
            for c, v in zip(chunks, vectors, strict=True)
        )
        video.transcript_source = source
        video.language = language or video.language
        video.status = VideoStatus.ready
        video.error = None
        # Same transaction: listeners are queued only if the chunks are saved.
        emit("athena.video_ready", {"video_id": str(video.id)}, db=db)
        db.commit()
    return len(chunks)
