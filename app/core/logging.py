import logging

from app.runtime.observe import RunContextFilter

FORMAT = "%(asctime)s %(levelname)s %(name)s [%(flow)s run=%(run_id)s trace=%(trace_id)s] %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Every log line is tagged with the current run, so `grep <trace_id>` follows one chain."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(FORMAT))
    handler.addFilter(RunContextFilter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
