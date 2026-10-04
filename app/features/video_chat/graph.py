r"""Video ingestion pipeline as a LangGraph graph.

    fetch_metadata -> fetch_transcript --(captions)--> chunk -> embed_and_store
                                       \--(none)----> download_audio -> transcribe -^

Audio cleanup is done by the caller in a `finally`, so it runs even when a node fails.
"""

import uuid
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import delete

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.embeddings import embed_documents
from app.features.video_chat.models import TranscriptSource, Video, VideoChunk, VideoStatus
from app.features.video_chat.pipeline.audio import download_audio
from app.features.video_chat.pipeline.chunking import chunk_segments
from app.features.video_chat.pipeline.metadata import fetch_metadata
from app.features.video_chat.pipeline.transcribe import transcribe_audio
from app.features.video_chat.pipeline.transcript import fetch_youtube_transcript
from app.features.video_chat.pipeline.types import Chunk, Segment


class IngestState(TypedDict, total=False):
    video_id: uuid.UUID
    youtube_id: str
    segments: list[Segment]
    language: str | None
    transcript_source: TranscriptSource
    audio_path: Path
    chunks: list[Chunk]


def _fetch_metadata(state: IngestState) -> IngestState:
    meta = fetch_metadata(state["youtube_id"])
    with SessionLocal() as db:
        video = db.get_one(Video, state["video_id"])
        video.title = meta.title
        video.channel = meta.channel
        video.description = meta.description
        video.duration_sec = meta.duration_sec
        video.thumbnail_url = meta.thumbnail_url
        video.language = meta.language
        db.commit()
    return {"language": meta.language}


def _fetch_transcript(state: IngestState) -> IngestState:
    languages = [state["language"]] if state.get("language") else []
    languages += [lang for lang in settings.transcript_languages if lang not in languages]
    result = fetch_youtube_transcript(state["youtube_id"], languages)
    if result is None:
        return {}
    segments, language = result
    return {
        "segments": segments,
        "language": language,
        "transcript_source": TranscriptSource.youtube,
    }


def _route_after_transcript(state: IngestState) -> Literal["chunk", "download_audio"]:
    return "chunk" if state.get("segments") else "download_audio"


def _download_audio(state: IngestState) -> IngestState:
    return {"audio_path": download_audio(state["youtube_id"])}


def _transcribe(state: IngestState) -> IngestState:
    segments, language = transcribe_audio(state["audio_path"])
    if not segments:
        raise ValueError("Whisper produced an empty transcript")
    return {
        "segments": segments,
        "language": language,
        "transcript_source": TranscriptSource.whisper,
    }


def _chunk(state: IngestState) -> IngestState:
    chunks = chunk_segments(
        state["segments"], settings.chunk_max_chars, settings.chunk_overlap_chars
    )
    return {"chunks": chunks}


def _embed_and_store(state: IngestState) -> IngestState:
    chunks = state["chunks"]
    vectors = embed_documents([c.text for c in chunks])

    with SessionLocal() as db:
        video = db.get_one(Video, state["video_id"])
        # Replace any chunks from a previous attempt.
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
        video.transcript_source = state["transcript_source"]
        video.language = state.get("language") or video.language
        video.status = VideoStatus.ready
        video.error = None
        db.commit()
    return {}


def build_ingest_graph():
    graph = StateGraph(IngestState)
    graph.add_node("fetch_metadata", _fetch_metadata)
    graph.add_node("fetch_transcript", _fetch_transcript)
    graph.add_node("download_audio", _download_audio)
    graph.add_node("transcribe", _transcribe)
    graph.add_node("chunk", _chunk)
    graph.add_node("embed_and_store", _embed_and_store)

    graph.add_edge(START, "fetch_metadata")
    graph.add_edge("fetch_metadata", "fetch_transcript")
    graph.add_conditional_edges("fetch_transcript", _route_after_transcript)
    graph.add_edge("download_audio", "transcribe")
    graph.add_edge("transcribe", "chunk")
    graph.add_edge("chunk", "embed_and_store")
    graph.add_edge("embed_and_store", END)
    return graph.compile()


ingest_graph = build_ingest_graph()
