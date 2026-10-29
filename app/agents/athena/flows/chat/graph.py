"""athena.chat: answer a question about one video (inline, streamed).

    load_video -> retrieve -> generate -> END

Nodes stream to the caller with get_stream_writer():
    {"type": "sources", ...}  then many  {"type": "token", "text": ...}
The runtime adds the final {"type": "done"} / {"type": "error"}.
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.athena.flows.chat import nodes


class ChatState(TypedDict, total=False):
    video_id: Any
    message: str
    history: list[dict]
    video: Any  # Video, loaded by load_video
    sources: list[nodes.Source]


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("load_video", nodes.load_video)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("generate", nodes.generate)

    graph.add_edge(START, "load_video")
    graph.add_edge("load_video", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


graph = build_graph()
