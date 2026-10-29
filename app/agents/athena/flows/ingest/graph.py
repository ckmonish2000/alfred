r"""athena.ingest: make a video chat-ready.

    load_video -> fetch_metadata -> fetch_transcript --(captions)--> index -> END
                                                     \--(none)----> request_transcription -> END

No captions: hand off to athena.transcribe on the media queue instead of doing heavy
Whisper work here. The video stays `processing` until that child run finishes.
"""

import uuid
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.athena.flows.ingest import nodes
from app.tools.types import Segment


class IngestState(TypedDict, total=False):
    video_id: uuid.UUID
    youtube_id: str
    language: str | None
    segments: list[Segment]


def _route_after_transcript(state: IngestState) -> Literal["index", "request_transcription"]:
    return "index" if state.get("segments") else "request_transcription"


def build_graph():
    graph = StateGraph(IngestState)
    graph.add_node("load_video", nodes.load_video)
    graph.add_node("fetch_metadata", nodes.fetch_metadata)
    graph.add_node("fetch_transcript", nodes.fetch_transcript)
    graph.add_node("index", nodes.index)
    graph.add_node("request_transcription", nodes.request_transcription)

    graph.add_edge(START, "load_video")
    graph.add_edge("load_video", "fetch_metadata")
    graph.add_edge("fetch_metadata", "fetch_transcript")
    graph.add_conditional_edges("fetch_transcript", _route_after_transcript)
    graph.add_edge("index", END)
    graph.add_edge("request_transcription", END)
    return graph.compile()


graph = build_graph()
