r"""athena.transcribe: build a transcript with Whisper when YouTube has no captions.

    load_video -> download_audio -> transcribe -> index -> END

Runs on the `media` queue. The audio file is deleted after transcribing, and by the
on_failure hook if the run gives up.
"""

import uuid
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.athena.flows.transcribe import nodes
from app.tools.types import Segment


class TranscribeState(TypedDict, total=False):
    video_id: uuid.UUID
    youtube_id: str
    audio_path: Path
    segments: list[Segment]
    language: str | None


def build_graph():
    graph = StateGraph(TranscribeState)
    graph.add_node("load_video", nodes.load_video)
    graph.add_node("download_audio", nodes.download_audio)
    graph.add_node("transcribe", nodes.transcribe)
    graph.add_node("index", nodes.index)

    graph.add_edge(START, "load_video")
    graph.add_edge("load_video", "download_audio")
    graph.add_edge("download_audio", "transcribe")
    graph.add_edge("transcribe", "index")
    graph.add_edge("index", END)
    return graph.compile()


graph = build_graph()
