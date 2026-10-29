"""Reads and writes of the runs table. The only module that changes a run's status."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update

from app.core.db import SessionLocal
from app.runtime.models import Run, RunStatus


def now() -> datetime:
    return datetime.now(UTC)


def claim(queues: list[str], lease_s: dict[str, int], default_lease_s: int = 600) -> Run | None:
    """Take the next due run on these queues, or one whose worker lease ran out.

    FOR UPDATE SKIP LOCKED lets many workers poll the same table without double-claiming.
    """
    with SessionLocal() as db:
        run = db.scalars(
            select(Run)
            .where(
                Run.queue.in_(queues),
                or_(
                    and_(Run.status == RunStatus.queued, Run.run_at <= now()),
                    and_(Run.status == RunStatus.running, Run.locked_until < now()),
                ),
            )
            .order_by(Run.run_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if run is None:
            return None
        run.status = RunStatus.running
        run.attempts += 1
        run.started_at = now()
        run.locked_until = now() + timedelta(seconds=lease_s.get(run.flow, default_lease_s))
        db.commit()
        return run


def finish(run_id: uuid.UUID, status: RunStatus, duration_ms: int, error: str | None = None) -> None:
    with SessionLocal() as db:
        db.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                status=status,
                error=error,
                duration_ms=duration_ms,
                finished_at=now(),
                locked_until=None,
            )
        )
        db.commit()


def retry_later(run_id: uuid.UUID, delay_s: float, error: str) -> None:
    with SessionLocal() as db:
        db.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(
                status=RunStatus.queued,
                error=error,
                run_at=now() + timedelta(seconds=delay_s),
                locked_until=None,
            )
        )
        db.commit()
