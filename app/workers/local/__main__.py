"""Every queue plus the cron scheduler in one process, for local development.
`python -m app.workers.local`
"""

import threading

from app.workers.base import run_worker
from app.workers.scheduler.loop import run_scheduler

if __name__ == "__main__":
    threading.Thread(target=run_scheduler, kwargs={"install_signals": False}, daemon=True).start()
    run_worker("local", queues=["default", "media"], concurrency=2)
