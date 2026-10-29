# Athena: chat with YouTube videos

Athena turns a YouTube video into searchable transcript chunks. It then answers
questions about the video, citing timestamps.

| Flow | Runs | Started by |
|---|---|---|
| `athena.chat` | inline, streams NDJSON | API |
| `athena.ingest` | queue `default` | API (`POST /agents/athena/videos`), `retry_failed` |
| `athena.transcribe` | queue `media` | `ingest`, when the video has no captions |
| `athena.retry_failed` | queue `default` | cron, `0 3 * * *` |

It emits `athena.video_ready {"video_id"}` once a video's chunks are stored.

## Flows

### ingest

```
load_video ─► fetch_metadata ─► fetch_transcript ──(captions)──► index ─► END
                                       │
                                       └──(none)──► request_transcription ─► END
                                                        │
                                                        └─ spawn athena.transcribe (media)
```

### transcribe

```
load_video ─► download_audio ─► transcribe (Whisper) ─► index ─► END
```

- The audio file is deleted after transcribing.
- If the run gives up, `on_failure` deletes the audio and marks the video failed.

### index (the shared last step of ingest and transcribe)

```
chunk (~1500 chars, 200 overlap) ─► embed ("search_document: ") ─► replace video_chunks
   ─► video.status = ready ─► emit athena.video_ready   (all in one transaction)
```

### chat

```
load_video ─► retrieve ─► generate ─► END
   │              │            │
   │              │            └─ stream {"type":"token"} from the LLM
   │              └─ embed "search_query: <prev question>\n<question>"
   │                 top-5 cosine in pgvector, sorted by time
   │                 stream {"type":"sources"}
   └─ 404 not found / 409 not ready (FlowError → real HTTP status)
```

## API

```bash
# add a video (registers it, queues ingest)
curl -X POST localhost:8000/agents/athena/videos \
  -H 'content-type: application/json' -d '{"url": "https://youtu.be/..."}'

# chat (streams NDJSON)
curl -N -X POST localhost:8000/agents/athena/flows/chat/runs \
  -H 'content-type: application/json' \
  -d '{"video_id": "...", "message": "what is RAG?", "history": []}'

# re-ingest a known video
curl -X POST localhost:8000/agents/athena/flows/ingest/runs \
  -H 'content-type: application/json' -d '{"video_id": "..."}'

# read
curl localhost:8000/agents/athena/videos
curl localhost:8000/agents/athena/videos/<id>/chunks
```

## Files

| File | What |
|---|---|
| `agent.py` | the AgentSpec: start here |
| `router.py` | read endpoints and `POST /videos` |
| `models.py` | `videos`, `video_chunks` tables |
| `schemas.py` | API schemas and flow inputs |
| `service.py` | `get_or_create_video`, `on_failure` hooks |
| `chunking.py` | segments → overlapping chunks |
| `indexing.py` | chunk, embed, store, emit |
| `flows/*/graph.py` | each flow's wiring |
| `flows/*/nodes.py` | each step's code |
