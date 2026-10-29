"""The single door into the runtime. API routes, cron, events and flows all call dispatch().

    inline flow -> run row (running) -> stream events back to the caller now
    queued flow -> run row (queued)  -> a worker picks it up later
"""

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.runtime import runs
from app.runtime.models import ACTIVE_STATUSES, Run, RunStatus
from app.runtime.observe import bind, current_run, graph_config, observe
from app.runtime.registry import registry
from app.runtime.spec import Flow, Invocation

logger = logging.getLogger("alfred.runs")


@dataclass(frozen=True)
class Dispatched:
    run_id: uuid.UUID
    trace_id: str
    status: RunStatus
    deduped: bool = False  # an identical run was already queued/running; this is that run
    stream: Iterator[dict] | None = None  # inline flows only: the flow's custom stream events


def dispatch(inv: Invocation, db: Session | None = None) -> Dispatched:
    """Record a run and start it (inline) or queue it.

    Pass `db` to create the run inside the caller's transaction; it is saved when the caller
    commits (transactional outbox), so work and follow-up runs land together or not at all.
    """
    flow = registry.flow(inv.flow)
    data = flow.input.model_validate(inv.payload)  # bad input fails here, not in a worker
    inline = flow.mode == "inline"
    if inline and db is not None:
        raise ValueError(f"{inv.flow} is inline; it can't join a caller's transaction")

    run = Run(
        flow=inv.flow,
        source=inv.source,
        actor=inv.actor,
        trace_id=inv.trace_id,
        parent_run_id=inv.parent_run_id,
        mode=flow.mode,
        queue=None if inline else flow.queue,
        payload=data.model_dump(mode="json"),
        status=RunStatus.running if inline else RunStatus.queued,
        attempts=1 if inline else 0,
        max_attempts=1 if inline else flow.max_attempts,
        started_at=runs.now() if inline else None,
        dedupe_key=flow.dedupe(data) if flow.dedupe and not inline else None,
    )

    if db is None:
        with SessionLocal() as own:
            run, deduped = _insert(own, run)
            own.commit()
    else:
        run, deduped = _insert(db, run)

    with bind(run):
        logger.info("run.%s", "deduped" if deduped else "created")

    stream = _stream_inline(run, flow, data.model_dump()) if inline else None
    return Dispatched(run.id, run.trace_id, run.status, deduped, stream)


def spawn(flow_id: str, payload: dict, db: Session | None = None) -> Dispatched:
    """Start a child run from inside a running flow; it joins the parent's trace."""
    parent = current_run.get()
    if parent is None:
        raise RuntimeError("spawn() must be called from inside a run")
    return dispatch(
        Invocation(
            flow=flow_id,
            payload=payload,
            source="flow",
            actor=f"run:{parent.id}",
            trace_id=parent.trace_id,
            parent_run_id=parent.id,
        ),
        db=db,
    )


def _insert(db: Session, run: Run) -> tuple[Run, bool]:
    try:
        with db.begin_nested():
            db.add(run)
    except IntegrityError:
        existing = db.scalars(
            select(Run).where(Run.dedupe_key == run.dedupe_key, Run.status.in_(ACTIVE_STATUSES))
        ).first()
        if existing is None:
            raise
        return existing, True
    return run, False


def _stream_inline(run: Run, flow: Flow, state: dict) -> Iterator[dict]:
    """Run an inline graph and yield what its nodes write with get_stream_writer().

    Starlette resumes a streaming generator on a fresh thread each step, which drops
    contextvars, so the run is re-bound around every step.
    """
    events = _observed_stream(run, flow, state)
    try:
        while True:
            with bind(run):
                try:
                    event = next(events)
                except StopIteration:
                    return
            yield event
    finally:
        with bind(run):
            events.close()


def _observed_stream(run: Run, flow: Flow, state: dict) -> Iterator[dict]:
    with observe(run, flow):
        yield from flow.graph.stream(state, config=graph_config(run), stream_mode="custom")
