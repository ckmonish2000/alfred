# Alfred

A home for agents. Each agent lives in `app/agents/<name>/`. The agents share one
runtime for triggers (API, cron, events), queues, workers and observability.

- **Architecture and how to add an agent:** [docs/architecture.md](docs/architecture.md)
- **Athena (chat with YouTube videos):** [app/agents/athena/README.md](app/agents/athena/README.md)

## Run it locally

You need Docker, [uv](https://docs.astral.sh/uv/) and LM Studio serving
`qwen2.5-coder-7b-instruct-mlx` and `text-embedding-nomic-embed-text-v1.5` on
`localhost:1234` (check with `scripts/check-lmstudio.sh`).

```bash
docker compose up -d db                  # Postgres + pgvector
uv sync
uv run alembic upgrade head

uv run fastapi dev app/main.py           # API on :8000
uv run python -m app.workers.local       # every queue + cron scheduler, one process

cd frontend && npm install && npm run dev
```

In production, run the workers separately:

```bash
uv run python -m app.workers.default     # light jobs
uv run python -m app.workers.media       # Whisper / audio
uv run python -m app.workers.scheduler   # cron (exactly one)
```

## Useful endpoints

| Endpoint | What |
|---|---|
| `GET /agents` | registered agents, flows, triggers |
| `POST /agents/{agent}/flows/{flow}/runs` | start any API-exposed flow |
| `GET /runs?trace_id=&flow=&source=&run_status=` | run history |
| `GET /runs/{id}` | one run's status, timings, error |

## Tests

```bash
uv run pytest
```
