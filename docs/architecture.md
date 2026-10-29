# Alfred architecture

Alfred is a team of **agents**. Each agent owns a few **flows** (LangGraph graphs).
Something has to **trigger** a flow: an API call, a cron schedule, or an event from
another agent. Every trigger goes through the same door, `dispatch()`, so every run
is recorded and observed the same way.

## The big picture

```
  HTTP request ──┐
  Chat message ──┤
  Cron tick ─────┼──► dispatch(Invocation) ──► runs table (one row per run)
  Event ─────────┤            │
  Parent flow ───┘    ┌───────┴────────┐
                   inline            queued
                      │                │
                observe(run)      a worker claims the row
                run graph now          │
                stream to caller  observe(run)
                                  run graph
```

| Question | Answer |
|---|---|
| Is a person waiting on screen? | `mode="inline"`: runs in the API, streams back |
| Will it take more than a few seconds? | queued: API replies `202` + `run_id` right away |
| Does it need heavy CPU or special software? | its own queue, e.g. `media` |
| Should it react to another agent? | `EventTrigger` |
| Should it happen at a fixed time? | `CronTrigger` |

## Folder layout

```
app/
├── main.py               API process: mounts the runtime routes + every agent's router
├── core/                 shared building blocks: config, db, llm, embeddings, logging
├── tools/                helpers any agent can use: youtube.py, whisper.py
│
├── runtime/              the plumbing, rarely touched
│   ├── spec.py               AgentSpec, Flow, triggers, Invocation, FlowError
│   ├── registry.py           finds every agent, indexes flows/triggers, validates
│   ├── dispatch.py           dispatch() and spawn(): the only way to start a run
│   ├── events.py             emit(): event -> one run per listener
│   ├── observe.py            observe(): logs, timing, retry/fail, final status
│   ├── runs.py               claim / finish / retry rows in the runs table
│   ├── models.py             the Run table
│   └── http.py               POST /agents/{agent}/flows/{flow}/runs, GET /runs
│
├── agents/               WHAT the work is: one folder per agent
│   └── athena/               video RAG bot (see its README.md)
│       ├── agent.py          ← start here: the AgentSpec
│       ├── router.py         agent-specific endpoints
│       ├── models.py, schemas.py, service.py
│       └── flows/<flow>/graph.py + nodes.py
│
└── workers/              WHERE the work runs: one folder per kind of work
    ├── base.py               shared claim -> execute loop
    ├── default/              light jobs (API calls, DB writes), concurrency 4
    ├── media/                audio download + Whisper, concurrency 1
    ├── scheduler/            fires CronTriggers; only queues, never executes
    └── local/                every queue + scheduler in one process (dev)
```

Agents and workers are deliberately separate:

- `agents/` says **what** to do (graphs, business logic).
- `workers/` says **where and how much** (which queues, concurrency, installed deps).
- A worker listens to **queues, not agents**. Any agent's flow on the `media`
  queue runs on the media worker. Name workers after the kind of work, never
  after an agent.

## The objects

### `AgentSpec`: who

```python
spec = AgentSpec(
    name="athena",
    router=router,                    # mounted at /agents/athena
    flows=[...],
    triggers=[...],
    emits=["athena.video_ready"],     # events this agent may emit()
)
```

The registry imports `app/agents/<name>/agent.py` for every folder and reads `spec`.
Adding an agent means adding a folder. No central list needs editing.

### `Flow`: what

```python
Flow(
    "ingest",                         # full id: "athena.ingest"
    ingest_graph,                     # compiled LangGraph
    input=IngestInput,                # pydantic model: the payload contract
    mode="queued",                    # or "inline"
    queue="default",                  # which worker picks it up
    max_attempts=3,                   # retries with backoff 30s, 60s, ...
    timeout_s=600,                    # worker lease; after this the run is re-claimed
    dedupe=lambda p: f"athena.ingest:{p.video_id}",   # one active copy at a time
    on_failure=service.mark_failed,   # called once when it gives up for good
)
```

`input` is checked twice. It's checked once when the run is created, so a bad
request fails right away. It's checked again when a worker picks the run up.

### Triggers: when

```python
ApiTrigger(flow="chat")                       # exposes POST /agents/athena/flows/chat/runs
CronTrigger("0 3 * * *", flow="retry_failed") # local time
EventTrigger(on="athena.video_ready", flow="summarize",
             map_payload=lambda e: {"video_id": e["video_id"]})
```

The registry rejects mistakes at startup:

- a trigger that points to a flow that doesn't exist
- a cron or event trigger on an inline flow
- a listener for an event that no agent declares in `emits`

### `Invocation`: a request to run

Every trigger builds one of these:

```python
Invocation(flow="athena.chat", payload={...}, source="api",
           actor="api:anonymous", trace_id="ad54c49f0f4f45f0")
```

| source | actor example | built by |
|---|---|---|
| `api` | `api:anonymous` (user id once there's auth) | `runtime/http.py`, agent routes |
| `cron` | `cron:0 3 * * *` | `workers/scheduler` |
| `event` | `event:athena.video_ready` | `runtime/events.emit()` |
| `flow` | `run:<parent run id>` | `runtime/dispatch.spawn()` |

`trace_id` is shared by every run in one chain. `parent_run_id` links a child run
to the run that started it.

## How a run works

### Inline (someone is waiting)

```
POST /agents/athena/flows/chat/runs  {"video_id": "...", "message": "what is RAG?"}
  │
  ├─ is athena.chat exposed by an ApiTrigger?       no  → 404
  ├─ does the body match ChatInput?                 no  → 422
  ├─ insert run row (status=running)
  ├─ pull the first event from the graph
  │     a node raised FlowError(404/409/503)?       yes → that HTTP status
  └─ 200, stream NDJSON:
        {"type":"sources",...}  {"type":"token",...} ...  {"type":"done"}
     headers: X-Run-Id, X-Trace-Id
```

Nodes stream to the caller with LangGraph's `get_stream_writer()`. The runtime adds
the last line: `done`, or `error` if the flow fails mid-stream. If the client
disconnects, the run is marked `cancelled`.

### Queued (nobody is waiting)

```
POST /agents/athena/flows/ingest/runs  {"video_id": "..."}
  → insert run row (status=queued, queue=default)
  → 202 {"run_id": "...", "status": "queued", "deduped": false}

worker loop (workers/base.py):
  claim()   SELECT ... FOR UPDATE SKIP LOCKED on its queues
            status=running, attempts+1, locked_until=now+timeout_s
  observe() run the graph
            ok          → done
            FlowError   → failed (never retried)
            other error → queued again at now + 30s·2^(attempt-1), until max_attempts
                          then failed + on_failure()
```

Check progress with `GET /runs/{run_id}`.

### Cron

`python -m app.workers.scheduler` computes each `CronTrigger`'s next tick and calls
`dispatch()` when it arrives. It never runs a graph itself, so a busy worker can't
make a schedule fire late. If the previous run is still active, `dedupe` turns the
new tick into a no-op. Ticks missed while the scheduler was down are skipped. Run
exactly one scheduler.

### Events

```python
# inside athena's indexing step, in the same DB transaction as the chunks
emit("athena.video_ready", {"video_id": str(video.id)}, db=db)
db.commit()
```

`emit()` creates one run per `EventTrigger` listening for that event. Passing `db`
puts those runs in the same transaction as the work (the *transactional outbox*).
That rules out "the video is ready but the event was lost", and the reverse.

### Child runs

```python
spawn("athena.transcribe", {"video_id": "..."})   # inside a running flow
```

A child run inherits `trace_id` and records `parent_run_id`. Athena uses this to send
Whisper work to the `media` queue.

## Observability

Everything lands in the `runs` table:

```
flow               source  actor                     trace     parent  status  ms
athena.chat        api     api:anonymous             ad54c49f  -       done    37135
athena.ingest      api     api:anonymous             e2e-demo  -       done     6994
athena.retry_failed cron   cron:0 3 * * *            1f0c...   -       done      120
athena.ingest      flow    run:04aeb1d9...           1f0c...   04aeb1  done     7012
```

- `GET /runs?trace_id=...` shows one chain: the API ingest, then the transcribe, then
  whatever reacted to `video_ready`.
- `GET /runs?source=cron&run_status=failed` shows what broke overnight.
- Every log line carries the current run:
  `[athena.ingest run=c52c6bce trace=e2e-demo] run.done duration_ms=6994`.
  To follow a chain, grep for its trace id.
- Pass an `X-Trace-Id` header to join a request to an existing trace.
- LangGraph gets `run_id` and `trace_id` as metadata through `graph_config()`. To add
  OpenTelemetry, Langfuse or LangSmith, change `runtime/observe.py` only. Agents
  don't change.

## Design patterns in use

| Pattern | Where | Why |
|---|---|---|
| Registry / plugin | `registry.discover()` | add an agent = add a folder |
| Declarative config | `AgentSpec`, `Flow`, triggers | `agent.py` reads like a table of contents |
| Command | a queued `Run` row | stored, retried, run on any worker |
| Observer / pub-sub | `emit()` + `EventTrigger` | agents never import each other |
| Strategy | `mode`, `queue` | same graph, different ways to run it |
| Transactional outbox | `dispatch(db=...)`, `emit(db=...)` | work and follow-up runs commit together |
| Idempotency | `dedupe`, delete-then-insert chunks | retries and double clicks are safe |

## Rules of thumb

- Starting work always goes through `dispatch()`, `spawn()` or `emit()`. Never call
  `graph.invoke()` from a route.
- Payloads carry **IDs**, not data. Send `{"video_id": ...}`, not a transcript.
- Queued flows must be safe to run twice. They will be, when a retry happens.
- Raise `FlowError(status, msg)` for expected failures, such as "not found" or
  "not ready". These are never retried.
- An agent must not import another agent. Share code through `tools/` or `core/`,
  and coordinate through events.
- Keep `agent.py` free of logic. Logic lives in nodes.

## Adding an agent

1. Create `app/agents/<name>/` with an `__init__.py`.
2. Write each flow as `flows/<flow>/graph.py` (wiring) plus `nodes.py` (code).
3. Define the input models in `schemas.py`, and the tables in `models.py` if you need any.
4. Write `agent.py` with `spec = AgentSpec(...)`.
5. If you added tables, run
   `uv run alembic revision --autogenerate -m "<name> tables"`, then
   `uv run alembic upgrade head`.
6. If a flow needs a new kind of worker, add `app/workers/<kind>/__main__.py`
   that calls `run_worker("<kind>", queues=["<kind>"], concurrency=N)`.

Check what got registered with `GET /agents`.

## Known limits

- **No auth yet.** API runs are recorded as `actor="api:anonymous"`.
- **Lease timeout.** A run that takes longer than its `timeout_s` is assumed dead
  and gets claimed again. Set `timeout_s` above the slowest real run.
- **Polling.** Workers poll every second. Postgres `LISTEN/NOTIFY` could remove the
  delay if it ever matters.
- **One scheduler.** Run a single scheduler process; it doesn't coordinate with a
  second one.
