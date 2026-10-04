export type VideoStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface Video {
  id: string
  youtube_id: string
  url: string
  title: string | null
  channel: string | null
  duration_sec: number | null
  thumbnail_url: string | null
  language: string | null
  status: VideoStatus
  transcript_source: 'youtube' | 'whisper' | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface Chunk {
  chunk_index: number
  start_sec: number
  end_sec: number
  text: string
}

const BASE = '/api/video-chat'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg: string }) => d.msg).join(', ')
          : `${res.status} ${res.statusText}`
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export const api = {
  submitVideo: (url: string) =>
    request<Video>('/videos', { method: 'POST', body: JSON.stringify({ url }) }),
  listVideos: () => request<Video[]>('/videos'),
  getVideo: (id: string) => request<Video>(`/videos/${id}`),
  listChunks: (id: string) => request<Chunk[]>(`/videos/${id}/chunks`),
}

export const isInProgress = (v: Video) => v.status === 'pending' || v.status === 'processing'

export function formatTime(totalSec: number): string {
  const s = Math.floor(totalSec)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = String(s % 60).padStart(2, '0')
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

export const timestampUrl = (youtubeId: string, sec: number) =>
  `https://www.youtube.com/watch?v=${youtubeId}&t=${Math.floor(sec)}s`
