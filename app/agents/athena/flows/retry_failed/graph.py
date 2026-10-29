"""athena.retry_failed: nightly cron. Re-queue ingest for videos that failed recently.

    requeue -> END
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.athena.flows.retry_failed import nodes


class RetryFailedState(TypedDict, total=False):
    within_hours: int


def build_graph():
    graph = StateGraph(RetryFailedState)
    graph.add_node("requeue", nodes.requeue)
    graph.add_edge(START, "requeue")
    graph.add_edge("requeue", END)
    return graph.compile()


graph = build_graph()
