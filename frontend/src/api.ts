// Typed client for the backend API + shared response types + small formatters.
// All UI data access goes through the `api` object below; nothing else calls fetch().

export type MatchKind = 'exact' | 'semantic'

export interface Match {
  start: number
  end: number
  snippet: string
  kind: MatchKind
}

export interface FileHit {
  id: number
  filename: string
  path: string
  duration: number
  source_kind: string
  format: string
  has_video: boolean
  ixml_scene: string | null
  ixml_take: string | null
  matches: Match[]
}

export interface Group {
  group_id: number
  score: number
  files: FileHit[]
}

export interface LibFile {
  id: number
  filename: string
  path: string
  duration: number | null
  format: string | null
  codec: string | null
  channels: number | null
  has_video: number
  source_kind: string
  ixml_scene: string | null
  ixml_take: string | null
  take_group_id: number | null
  status: string
  error: string | null
  size: number | null
}

export interface Folder {
  id: number
  path: string
  added_at: string
  file_count: number
}

export interface Stats {
  by_status: Record<string, number>
  total_files: number
  total_duration: number
  queue: number
  scanning: boolean
}

export interface Segment {
  start: number
  end: number
  text: string
}

export interface FileDetail extends LibFile {
  transcript: string | null
  segments: Segment[]
}

export interface PipelineEvent {
  type: string
  id?: number
  status?: string
  error?: string | null
  filename?: string
  state?: string
  folder?: string
  new_files?: number
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

// In the webapp the UI is served same-origin, so relative `/api` works. The native
// Tauri shell renders the UI from a different origin and runs the backend on a dynamic
// localhost port; it injects that base as `window.__AUDIO_SEARCH_API__` before load.
// Default '' keeps the webapp unchanged.
const API_BASE: string =
  (typeof window !== 'undefined' && (window as unknown as { __AUDIO_SEARCH_API__?: string }).__AUDIO_SEARCH_API__) || ''

// Prefix a relative `/api/...` path with the backend base (no-op in the webapp).
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}

// True when running inside the native Tauri shell (vs. the browser webapp).
export function isNative(): boolean {
  return API_BASE !== ''
}

export const api = {
  get: <T>(url: string) => fetch(apiUrl(url)).then((r) => handle<T>(r)),
  post: <T>(url: string, body?: unknown) =>
    fetch(apiUrl(url), {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).then((r) => handle<T>(r)),
  delete: <T>(url: string) => fetch(apiUrl(url), { method: 'DELETE' }).then((r) => handle<T>(r)),

  // One named method per endpoint — keeps URLs + response types in a single place.
  search: (q: string) =>
    api.get<{ query: string; groups: Group[] }>(`/api/search?q=${encodeURIComponent(q)}`),
  stats: () => api.get<Stats>('/api/stats'),
  files: () => api.get<LibFile[]>('/api/files'),
  fileDetail: (id: number) => api.get<FileDetail>(`/api/files/${id}`),
  folders: () => api.get<Folder[]>('/api/folders'),
  addFolder: (path: string) => api.post<Folder>('/api/folders', { path }),
  removeFolder: (id: number) => api.delete<{ ok: boolean }>(`/api/folders/${id}`),
  rescan: () => api.post<{ folders: number }>('/api/rescan'),
  retry: (id: number) => api.post<{ ok: boolean }>(`/api/files/${id}/retry`),
  reveal: (id: number) => api.post<{ ok: boolean }>(`/api/files/${id}/reveal`),
  peaks: (id: number) => api.get<{ peaks: number[]; duration: number }>(`/api/media/${id}/peaks`),
}

export function mediaUrl(id: number): string {
  return apiUrl(`/api/media/${id}`)
}

// Seconds -> "m:ss" (or "h:mm:ss" past an hour); used for timecodes and durations.
export function formatTime(t: number | null | undefined): string {
  if (t == null || !isFinite(t)) return '--:--'
  const s = Math.max(0, t)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
    : `${m}:${String(sec).padStart(2, '0')}`
}

export function formatDuration(t: number | null | undefined): string {
  if (t == null) return '—'
  return formatTime(t)
}
