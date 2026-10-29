import logging
import signal
import threading
from datetime import datetime

from croniter import croniter

from app.core.logging import setup_logging
from app.runtime.dispatch import dispatch
from app.runtime.registry import registry
from app.runtime.spec import Invocation, new_trace_id

logger = logging.getLogger("alfred.scheduler")


def run_scheduler(install_signals: bool = True) -> None:
    """Queue each CronTrigger's flow at its next tick. Missed ticks while down are skipped.

    Overlap is handled by the flow's `dedupe`: a tick is a no-op while the last one runs.
    """
    if install_signals:
        setup_logging()
    registry.discover()
    stop = threading.Event()
    if install_signals:
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())

    start = datetime.now().astimezone()
    schedule = [(s, croniter(s.trigger.schedule, start)) for s in registry.crons]
    next_at = [it.get_next(datetime) for _, it in schedule]
    for (s, _), at in zip(schedule, next_at, strict=True):
        logger.info("cron %s '%s' next at %s", s.flow_id, s.trigger.schedule, at.isoformat())
    if not schedule:
        logger.info("No CronTriggers registered")

    while not stop.is_set():
        now = datetime.now().astimezone()
        for i, (s, it) in enumerate(schedule):
            if next_at[i] > now:
                continue
            try:
                dispatch(
                    Invocation(
                        flow=s.flow_id,
                        payload=s.trigger.payload,
                        source="cron",
                        actor=f"cron:{s.trigger.schedule}",
                        trace_id=new_trace_id(),
                    )
                )
            except Exception:
                logger.exception("Could not queue %s", s.flow_id)
            next_at[i] = it.get_next(datetime)
        stop.wait(1.0)
