"""The objects an agent uses to describe itself. They hold no logic; the runtime reads them.

    AgentSpec = who   (name, flows, triggers, routes)
    Flow      = what  (a graph + how to run it)
    Trigger   = when  (API / cron / event)
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

Source = Literal["api", "cron", "event", "flow"]


@dataclass(frozen=True)
class Flow:
    name: str  # local name, e.g. "ingest"; the full id is "<agent>.<name>"
    graph: Any  # compiled LangGraph
    input: type[BaseModel]  # payload schema, checked when the run is created and again when it runs
    mode: Literal["inline", "queued"] = "queued"  # inline: runs in the API and streams back
    queue: str = "default"  # which worker picks it up (queued flows only)
    max_attempts: int = 3
    timeout_s: int = 600  # after this a worker is presumed dead and the run is picked up again
    # Key that stops a second copy from being queued while one is still queued/running.
    dedupe: Callable[[Any], str] | None = None
    # Called once when a queued run gives up for good, with its payload and the error.
    on_failure: Callable[[dict, BaseException], None] | None = None


@dataclass(frozen=True)
class ApiTrigger:
    """Exposes the flow at POST /agents/<agent>/flows/<flow>/runs."""

    flow: str


@dataclass(frozen=True)
class CronTrigger:
    schedule: str  # cron expression, local time, e.g. "0 3 * * *"
    flow: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EventTrigger:
    on: str  # "<agent>.<event>", e.g. "athena.video_ready"
    flow: str
    map_payload: Callable[[dict], dict] = lambda data: data  # event data -> flow input


Trigger = ApiTrigger | CronTrigger | EventTrigger


@dataclass(frozen=True)
class AgentSpec:
    name: str
    flows: list[Flow]
    triggers: list[Trigger] = field(default_factory=list)
    router: APIRouter | None = None  # agent-specific read endpoints, mounted at /agents/<name>
    emits: list[str] = field(default_factory=list)  # events this agent may emit()


@dataclass(frozen=True)
class Invocation:
    """A request to run a flow. Every trigger builds one and hands it to dispatch()."""

    flow: str  # full id, e.g. "athena.chat"
    payload: dict
    source: Source
    actor: str  # who asked: "api:anonymous", "cron:0 3 * * *", "event:athena.video_ready", "run:<id>"
    trace_id: str  # shared by every run in one chain
    parent_run_id: uuid.UUID | None = None


class FlowError(Exception):
    """An expected failure (bad request, missing record) that maps to an HTTP status.

    Never retried. Raised before an inline flow's first event, it becomes the HTTP error.
    """

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]
