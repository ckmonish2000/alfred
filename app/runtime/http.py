"""One HTTP entry point for starting any flow, plus endpoints to inspect runs."""

import json
import uuid
from collections.abc import Iterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.runtime.dispatch import dispatch
from app.runtime.models import Run, RunStatus
from app.runtime.registry import registry
from app.runtime.spec import FlowError, Invocation, new_trace_id

router = APIRouter(tags=["runtime"])


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    flow: str
    source: str
    actor: str
    trace_id: str
    parent_run_id: uuid.UUID | None
    mode: str
    queue: str | None
    payload: dict
    status: RunStatus
    attempts: int
    max_attempts: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None


def api_invocation(flow: str, payload: dict, request: Request) -> Invocation:
    """The Invocation for an HTTP caller. Agent routes that start flows use this too."""
    return Invocation(
        flow=flow,
        payload=payload,
        source="api",
        actor="api:anonymous",  # becomes the user id once there is auth
        trace_id=request.headers.get("x-trace-id") or new_trace_id(),
    )


@router.post("/agents/{agent}/flows/{flow}/runs")
def create_run(agent: str, flow: str, body: dict, request: Request):
    """Start a flow. Inline flows stream NDJSON; queued flows return 202 with a run id."""
    flow_id = f"{agent}.{flow}"
    if flow_id not in registry.api_flows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No API trigger for {flow_id}")

    try:
        result = dispatch(api_invocation(flow_id, body, request))
    except ValidationError as exc:
        detail = jsonable_encoder(exc.errors(include_url=False, include_context=False))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from exc

    headers = {"X-Run-Id": str(result.run_id), "X-Trace-Id": result.trace_id}
    if result.stream is None:
        return JSONResponse(
            {"run_id": str(result.run_id), "status": result.status.value, "deduped": result.deduped},
            status_code=status.HTTP_202_ACCEPTED,
            headers=headers,
        )

    # Pull the first event before answering so early failures (404, 409, 503) become
    # real HTTP errors instead of a 200 followed by an error line.
    try:
        first = next(result.stream, None)
    except FlowError as exc:
        raise HTTPException(exc.status_code, exc.message, headers=headers) from exc
    return StreamingResponse(
        _ndjson(first, result.stream), media_type="application/x-ndjson", headers=headers
    )


def _ndjson(first: dict | None, rest: Iterator[dict]) -> Iterator[str]:
    """Flow events, then a final `done`, or `error` if the flow fails mid-stream."""
    try:
        if first is not None:
            yield json.dumps(first, default=str) + "\n"
        for event in rest:
            yield json.dumps(event, default=str) + "\n"
    except Exception as exc:  # already recorded on the run by observe()
        yield json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}) + "\n"
        return
    yield json.dumps({"type": "done"}) + "\n"


@router.get("/runs", response_model=list[RunRead])
def list_runs(
    trace_id: str | None = None,
    flow: str | None = None,
    source: str | None = None,
    run_status: RunStatus | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if trace_id:
        query = query.where(Run.trace_id == trace_id)
    if flow:
        query = query.where(Run.flow == flow)
    if source:
        query = query.where(Run.source == source)
    if run_status:
        query = query.where(Run.status == run_status)
    return db.scalars(query).all()


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run
