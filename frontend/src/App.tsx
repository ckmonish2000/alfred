import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, formatTime, isInProgress, timestampUrl, type Chunk, type Video } from './api'

const POLL_MS = 2000

export default function App() {
  const [videos, setVideos] = useState<Video[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const list = await api.listVideos()
      setVideos(list)
      setListError(null)
    } catch (e) {
      setListError(`Can't reach the API: ${(e as Error).message}`)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Keep polling while anything is still being ingested.
  const anyInProgress = videos.some(isInProgress)
  useEffect(() => {
    if (!anyInProgress) return
    const t = setInterval(refresh, POLL_MS)
    return () => clearInterval(t)
  }, [anyInProgress, refresh])

  const selected = videos.find((v) => v.id === selectedId) ?? null

  return (
    <div className="app">
      <header>
        <h1>Alfred</h1>
        <span className="subtitle">Video chat · ingestion</span>
      </header>

      <SubmitForm
        onSubmitted={(v) => {
          setSelectedId(v.id)
          refresh()
        }}
      />

      {listError && <p className="error">{listError}</p>}

      <main>
        <aside>
          <h2>Videos</h2>
          {videos.length === 0 && !listError && <p className="muted">Nothing yet. Paste a URL above.</p>}
          <ul className="video-list">
            {videos.map((v) => (
              <li key={v.id}>
                <button
                  className={v.id === selectedId ? 'video-item active' : 'video-item'}
                  onClick={() => setSelectedId(v.id)}
                >
                  <span className="video-item-title">{v.title ?? v.youtube_id}</span>
                  <StatusBadge video={v} />
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="detail">
          {selected ? (
            // Remount when the status changes so chunk state starts fresh.
            <VideoDetail key={`${selected.id}-${selected.status}`} video={selected} />
          ) : <p className="muted">Select a video.</p>}
        </section>
      </main>
    </div>
  )
}

function SubmitForm({ onSubmitted }: { onSubmitted: (v: Video) => void }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const video = await api.submitVideo(url.trim())
      setUrl('')
      onSubmitted(video)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="submit" onSubmit={submit}>
      <input
        type="url"
        required
        placeholder="https://www.youtube.com/watch?v=…"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        disabled={busy}
      />
      <button type="submit" disabled={busy || !url.trim()}>
        {busy ? 'Submitting…' : 'Ingest'}
      </button>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

function StatusBadge({ video }: { video: Video }) {
  return (
    <span className={`badge badge-${video.status}`}>
      {isInProgress(video) && <span className="spinner" />}
      {video.status}
    </span>
  )
}

function VideoDetail({ video }: { video: Video }) {
  const [chunks, setChunks] = useState<Chunk[] | null>(null)
  const [chunkError, setChunkError] = useState<string | null>(null)

  useEffect(() => {
    if (video.status !== 'ready') return
    let cancelled = false
    api
      .listChunks(video.id)
      .then((c) => !cancelled && setChunks(c))
      .catch((e) => !cancelled && setChunkError((e as Error).message))
    return () => {
      cancelled = true
    }
  }, [video.id, video.status])

  return (
    <>
      <div className="video-head">
        {video.thumbnail_url && <img src={video.thumbnail_url} alt="" />}
        <div>
          <h2>
            <a href={video.url} target="_blank" rel="noreferrer">
              {video.title ?? video.youtube_id}
            </a>
          </h2>
          <dl>
            <dt>Status</dt>
            <dd>
              <StatusBadge video={video} />
            </dd>
            {video.channel && (
              <>
                <dt>Channel</dt>
                <dd>{video.channel}</dd>
              </>
            )}
            {video.duration_sec != null && (
              <>
                <dt>Duration</dt>
                <dd>{formatTime(video.duration_sec)}</dd>
              </>
            )}
            {video.transcript_source && (
              <>
                <dt>Transcript</dt>
                <dd>{video.transcript_source === 'youtube' ? 'YouTube captions' : 'Whisper'}</dd>
              </>
            )}
            {video.language && (
              <>
                <dt>Language</dt>
                <dd>{video.language}</dd>
              </>
            )}
          </dl>
        </div>
      </div>

      {video.status === 'failed' && <pre className="error">{video.error}</pre>}
      {isInProgress(video) && (
        <p className="muted">
          Working on it… If the video has no captions, it gets downloaded and transcribed with Whisper, which can
          take a while for long videos.
        </p>
      )}

      {video.status === 'ready' && (
        <>
          <h3>Chunks {chunks && <span className="muted">({chunks.length})</span>}</h3>
          {chunkError && <p className="error">{chunkError}</p>}
          {!chunks && !chunkError && <p className="muted">Loading…</p>}
          <ol className="chunks">
            {chunks?.map((c) => (
              <li key={c.chunk_index}>
                <a href={timestampUrl(video.youtube_id, c.start_sec)} target="_blank" rel="noreferrer">
                  {formatTime(c.start_sec)} – {formatTime(c.end_sec)}
                </a>
                <p>{c.text}</p>
              </li>
            ))}
          </ol>
        </>
      )}
    </>
  )
}
