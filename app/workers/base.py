"""Shared worker loop. A worker listens to queues, not agents: any agent's flow on those
queues runs here. Each worker folder only picks its queues and concurrency.
"""

import logging
import signal
import threading

from app.core.logging import setup_logging
from app.runtime import runs
from app.runtime.models import Run, RunStatus
from app.runtime.observe import bind, graph_config, observe
from app.runtime.registry import registry

logger = logging.getLogger("alfred.worker")


def run_worker(name: str, queues: list[str], concurrency: int = 1, poll_s: float = 1.0) -> None:
    setup_logging()
    registry.discover()
    lease_s = {flow_id: flow.timeout_s for flow_id, flow in registry.flows.items()}
    stop = threading.Event()

    def request_stop(signum, _frame):
        logger.info("%s worker stopping after current runs (signal %s)", name, signum)
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    flows = sorted(f for f, flow in registry.flows.items() if flow.mode == "queued" and flow.queue in queues)
    logger.info("%s worker up: queues=%s concurrency=%d flows=%s", name, queues, concurrency, flows)

    threads = [
        threading.Thread(target=_loop, args=(queues, lease_s, poll_s, stop), name=f"{name}-{i}")
        for i in range(concurrency)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def _loop(queues: list[str], lease_s: dict[str, int], poll_s: float, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            run = runs.claim(queues, lease_s)
        except Exception:
            logger.exception("Could not claim a run; retrying")
            stop.wait(poll_s * 5)
            continue
        if run is None:
            stop.wait(poll_s)
            continue
        execute(run)


def execute(run: Run) -> None:
    with bind(run):
        flow = registry.flows.get(run.flow)
        if flow is None:
            runs.finish(run.id, RunStatus.failed, 0, f"Unknown flow {run.flow!r}")
            logger.error("run.failed: unknown flow")
            return
        try:
            with observe(run, flow):
                state = flow.input.model_validate(run.payload).model_dump()
                flow.graph.invoke(state, config=graph_config(run))
        except Exception:
            pass  # observe() already logged it and set retry/failed
