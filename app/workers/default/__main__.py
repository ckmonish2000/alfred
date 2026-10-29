"""Light work: API calls, DB writes, orchestration. `python -m app.workers.default`"""

from app.workers.base import run_worker

if __name__ == "__main__":
    run_worker("default", queues=["default"], concurrency=4)
