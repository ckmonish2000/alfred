"""Finds every agent under app/agents/ and indexes its flows and triggers.

Adding an agent = adding a folder with an agent.py that defines `spec`. Nothing here changes.
"""

import importlib
import importlib.util
import pkgutil
import threading
from collections import defaultdict
from dataclasses import dataclass, field

import app.agents
from app.runtime.spec import AgentSpec, ApiTrigger, CronTrigger, EventTrigger, Flow

_discover_lock = threading.Lock()


@dataclass(frozen=True)
class ScheduledFlow:
    flow_id: str
    trigger: CronTrigger


@dataclass(frozen=True)
class Listener:
    flow_id: str
    trigger: EventTrigger


@dataclass
class Registry:
    agents: dict[str, AgentSpec] = field(default_factory=dict)
    flows: dict[str, Flow] = field(default_factory=dict)  # "athena.ingest" -> Flow
    api_flows: set[str] = field(default_factory=set)
    crons: list[ScheduledFlow] = field(default_factory=list)
    listeners: dict[str, list[Listener]] = field(default_factory=lambda: defaultdict(list))
    events: set[str] = field(default_factory=set)  # every event some agent declares in `emits`

    def register(self, spec: AgentSpec) -> None:
        if spec.name in self.agents:
            raise ValueError(f"Agent {spec.name!r} registered twice")

        flows: dict[str, Flow] = {}
        for flow in spec.flows:
            if flow.name in flows:
                raise ValueError(f"{spec.name}: flow {flow.name!r} defined twice")
            flows[flow.name] = flow

        for trigger in spec.triggers:
            flow = flows.get(trigger.flow)
            if flow is None:
                raise ValueError(f"{spec.name}: {type(trigger).__name__} points to unknown flow {trigger.flow!r}")
            if not isinstance(trigger, ApiTrigger) and flow.mode == "inline":
                raise ValueError(f"{spec.name}.{flow.name} is inline; only an ApiTrigger can start it")

        for event in spec.emits:
            if not event.startswith(f"{spec.name}."):
                raise ValueError(f"{spec.name}: emitted event {event!r} must start with '{spec.name}.'")

        self.agents[spec.name] = spec
        self.flows.update({f"{spec.name}.{name}": flow for name, flow in flows.items()})
        self.events.update(spec.emits)
        for trigger in spec.triggers:
            flow_id = f"{spec.name}.{trigger.flow}"
            if isinstance(trigger, ApiTrigger):
                self.api_flows.add(flow_id)
            elif isinstance(trigger, CronTrigger):
                self.crons.append(ScheduledFlow(flow_id, trigger))
            else:
                self.listeners[trigger.on].append(Listener(flow_id, trigger))

    def validate(self) -> None:
        """Checks that need every agent loaded, e.g. listeners for events nobody emits."""
        unknown = set(self.listeners) - self.events
        if unknown:
            raise ValueError(f"Listening to events no agent emits: {sorted(unknown)}")

    def discover(self) -> None:
        """Import app/agents/<name>/agent.py for every agent folder. Safe to call twice."""
        with _discover_lock:
            if self.agents:
                return
            for info in pkgutil.iter_modules(app.agents.__path__):
                if info.ispkg:
                    module = importlib.import_module(f"app.agents.{info.name}.agent")
                    self.register(module.spec)
            self.validate()

    def flow(self, flow_id: str) -> Flow:
        try:
            return self.flows[flow_id]
        except KeyError:
            raise KeyError(f"Unknown flow {flow_id!r}") from None


registry = Registry()


def import_models() -> None:
    """Import every agent's models.py so SQLAlchemy (and Alembic) see all tables."""
    importlib.import_module("app.runtime.models")
    for info in pkgutil.iter_modules(app.agents.__path__):
        if info.ispkg and importlib.util.find_spec(f"app.agents.{info.name}.models"):
            importlib.import_module(f"app.agents.{info.name}.models")
