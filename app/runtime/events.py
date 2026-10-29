"""Pub-sub between agents: emit() turns one event into a run for each EventTrigger listening."""

import logging

from sqlalchemy.orm import Session

from app.runtime.dispatch import Dispatched, dispatch
from app.runtime.observe import current_run
from app.runtime.registry import registry
from app.runtime.spec import Invocation, new_trace_id

logger = logging.getLogger("alfred.events")


def emit(event: str, data: dict, db: Session | None = None) -> list[Dispatched]:
    """Announce that something happened. The emitter never knows who listens.

    Pass the `db` session that saved the work so listener runs commit with it.
    """
    if event not in registry.events:
        raise ValueError(f"Event {event!r} is not declared in any agent's `emits`")

    parent = current_run.get()
    listeners = registry.listeners.get(event, [])
    logger.info("event.emitted %s listeners=%d", event, len(listeners))
    return [
        dispatch(
            Invocation(
                flow=listener.flow_id,
                payload=listener.trigger.map_payload(data),
                source="event",
                actor=f"event:{event}",
                trace_id=parent.trace_id if parent else new_trace_id(),
                parent_run_id=parent.id if parent else None,
            ),
            db=db,
        )
        for listener in listeners
    ]
