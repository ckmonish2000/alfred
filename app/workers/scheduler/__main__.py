"""Fires CronTriggers. It only queues runs and never executes a graph itself.
Run exactly one: `python -m app.workers.scheduler`
"""

from app.workers.scheduler.loop import run_scheduler

if __name__ == "__main__":
    run_scheduler()
