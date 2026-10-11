import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import {
  formatTime,
  parseTime,
  streamChat,
  timestampUrl,
  type ChatMessage,
  type ChatSource,
  type Video,
} from './api'

interface Message extends ChatMessage {
  sources?: ChatSource[]
  error?: string
}

// Matches citations like [3:15], [1:02:03] or [3:15 - 4:00]; links to the start time.
const TS_RE = /\[(\d{1,2}(?::\d{2}){1,2})(?:\s*[-–]\s*\d{1,2}(?::\d{2}){1,2})?\]/g

function renderWithTimestamps(text: string, youtubeId: string): ReactNode[] {
  const parts: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(TS_RE)) {
    const i = match.index
    if (i > last) parts.push(text.slice(last, i))
    parts.push(
      <a key={i} href={timestampUrl(youtubeId, parseTime(match[1]))} target="_blank" rel="noreferrer">
        {match[0]}
      </a>,
    )
    last = i + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

export default function Chat({ video }: { video: Video }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [messages])

  // Update the in-progress assistant message (always the last one).
  const updateLast = (fn: (m: Message) => Message) =>
    setMessages((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])])

  async function send(e?: FormEvent) {
    e?.preventDefault()
    const question = input.trim()
    if (!question || streaming) return

    const history: ChatMessage[] = messages
      .filter((m) => !m.error && m.content)
      .map(({ role, content }) => ({ role, content }))

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: question }, { role: 'assistant', content: '' }])
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      for await (const event of streamChat(video.id, question, history, controller.signal)) {
        if (event.type === 'sources') updateLast((m) => ({ ...m, sources: event.sources }))
        else if (event.type === 'token') updateLast((m) => ({ ...m, content: m.content + event.text }))
        else if (event.type === 'error') updateLast((m) => ({ ...m, error: event.message }))
      }
    } catch (err) {
      if (!controller.signal.aborted) updateLast((m) => ({ ...m, error: (err as Error).message }))
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="chat">
      <div className="chat-messages" ref={listRef}>
        {messages.length === 0 && (
          <p className="muted">Ask anything about this video. Answers cite timestamps you can click.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            {m.role === 'assistant' && !m.content && !m.error && streaming && i === messages.length - 1 ? (
              <span className="muted">
                <span className="spinner" /> Thinking…
              </span>
            ) : (
              <div className="msg-text">{renderWithTimestamps(m.content, video.youtube_id)}</div>
            )}
            {m.error && <p className="error">{m.error}</p>}
            {m.sources && m.sources.length > 0 && (
              <details className="sources">
                <summary>Sources ({m.sources.length})</summary>
                <ol>
                  {m.sources.map((s) => (
                    <li key={s.chunk_index}>
                      <a href={timestampUrl(video.youtube_id, s.start_sec)} target="_blank" rel="noreferrer">
                        {formatTime(s.start_sec)} – {formatTime(s.end_sec)}
                      </a>{' '}
                      <span className="muted">· {s.score.toFixed(2)}</span>
                      <p>{s.text}</p>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </div>
        ))}
      </div>

      <form className="chat-input" onSubmit={send}>
        <textarea
          rows={2}
          placeholder="Ask about this video…  (Enter to send, Shift+Enter for a new line)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {streaming ? (
          <button type="button" onClick={() => abortRef.current?.abort()}>
            Stop
          </button>
        ) : (
          <button type="submit" disabled={!input.trim()}>
            Send
          </button>
        )}
      </form>
    </div>
  )
}
