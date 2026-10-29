"""The one wrapper every run executes inside, inline or queued.

It owns the outcome: logs, timing, retry vs. fail, and the run's final status.
Swap in OpenTelemetry/Langfuse spans here and every agent gets them.
"""

import contextvars
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from app.runtime import runs
from app.runtime.models import Run, RunStatus
from app.runtime.spec import Flow, FlowError

logger = logging.getLogger("alfred.runs")

# The run executing in this context. Read by the log filter, emit() and spawn().
current_run: contextvars.ContextVar[Run | None] = contextvars.ContextVar("current_run", default=None)

RETRY_BASE_DELAY_S = 30


@contextmanager
def bind(run: Run) -> Iterator[None]:
    token = current_run.set(run)
    try:
        yield
    finally:
        current_run.reset(token)


class RunContextFilter(logging.Filter):
    """Adds flow/run_id/trace_id of the current run to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        run = current_run.get()
        record.flow = run.flow if run else "-"
        record.run_id = str(run.id)[:8] if run else "-"
        record.trace_id = run.trace_id if run else "-"
        return True


def graph_config(run: Run) -> dict:
    """LangGraph config so tracing tools tag every node and LLM call with the run."""
    return {
        "run_name": run.flow,
        "metadata": {"run_id": str(run.id), "trace_id": run.trace_id, "source": run.source},
    }


@contextmanager
def observe(run: Run, flow: Flow) -> Iterator[None]:
    logger.info("run.started source=%s actor=%s attempt=%s", run.source, run.actor, run.attempts)
    t0 = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - t0) * 1000)

    try:
        if run.attempts > run.max_attempts:
            raise RuntimeError(f"Gave up after {run.max_attempts} attempts (worker lease expired)")
        yield
    except GeneratorExit:
        runs.finish(run.id, RunStatus.cancelled, elapsed(), "client disconnected")
        logger.info("run.cancelled duration_ms=%s", elapsed())
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        retryable = (
            run.mode == "queued" and not isinstance(exc, FlowError) and run.attempts < run.max_attempts
        )
        if retryable:
            delay = RETRY_BASE_DELAY_S * 2 ** (run.attempts - 1)
            runs.retry_later(run.id, delay, error)
            logger.warning("run.retrying in %ss: %s", delay, error, exc_info=True)
        else:
            runs.finish(run.id, RunStatus.failed, elapsed(), error)
            logger.error("run.failed duration_ms=%s: %s", elapsed(), error, exc_info=not isinstance(exc, FlowError))
            if flow.on_failure is not None:
                try:
                    flow.on_failure(run.payload, exc)
                except Exception:
                    logger.exception("on_failure hook failed")
        raise
    else:
        runs.finish(run.id, RunStatus.done, elapsed())
        logger.info("run.done duration_ms=%s", elapsed())
