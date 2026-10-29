"""Heavy audio work: downloads and Whisper. One at a time; Whisper uses every core.
`python -m app.workers.media`
"""

from app.workers.base import run_worker

if __name__ == "__main__":
    run_worker("media", queues=["media"], concurrency=1)
