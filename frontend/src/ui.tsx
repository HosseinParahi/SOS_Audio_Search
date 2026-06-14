import { useEffect, useState, type ReactNode } from 'react'
import {
  AudioLines,
  Check,
  Copy,
  FolderSearch,
  Loader2,
  Mic,
  Radio,
  Video,
  X,
} from 'lucide-react'
import { api, formatTime, type FileDetail } from './api'
import { usePlayer } from './player'

// Shared presentational pieces used across both views: source chips (boom/lav/camera),
// pipeline status badges, safe search-snippet highlighting, copy/reveal buttons, and the
// transcript drawer.

// -- source chips -------------------------------------------------------------
const SOURCE_META: Record<string, { icon: typeof Mic; label: string; cls: string }> = {
  boom: { icon: Mic, label: 'Boom', cls: 'text-amber border-amber/40 bg-amber/10' },
  lav: { icon: Radio, label: 'Lav', cls: 'text-cyan border-cyan/40 bg-cyan/10' },
  camera: { icon: Video, label: 'Cam', cls: 'text-green border-green/40 bg-green/10' },
  recorder: { icon: AudioLines, label: 'Rec', cls: 'text-fg border-line2 bg-raise' },
  unknown: { icon: AudioLines, label: 'Audio', cls: 'text-dim border-line bg-panel2' },
}

export function SourceChip({ kind, iconOnly = false }: { kind: string; iconOnly?: boolean }) {
  const meta = SOURCE_META[kind] ?? SOURCE_META.unknown
  const Icon = meta.icon
  return (
    <span
      title={meta.label}
      className={`inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${meta.cls}`}
    >
      <Icon size={11} />
      {!iconOnly && meta.label}
    </span>
  )
}

// -- pipeline status badges -----------------------------------------------------
const STATUS_META: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  pending: { label: 'queued', cls: 'text-dim bg-panel2 border-line' },
  transcribing: { label: 'transcribing', cls: 'text-amber bg-amber/10 border-amber/40', pulse: true },
  embedding: { label: 'embedding', cls: 'text-cyan bg-cyan/10 border-cyan/40', pulse: true },
  done: { label: 'indexed', cls: 'text-green bg-green/10 border-green/40' },
  error: { label: 'error', cls: 'text-red bg-red/10 border-red/40' },
  duplicate: { label: 'duplicate', cls: 'text-faint bg-panel2 border-line' },
}

export function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.pending
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] ${meta.cls}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full bg-current ${meta.pulse ? 'pulse-dot' : ''}`} />
      {meta.label}
    </span>
  )
}

/**
 * Render a search snippet with matched terms highlighted. The backend marks hits with
 * \x01…\x02 sentinel chars (see search._fts_search) instead of HTML, so we can build real
 * <mark> elements here — transcript text is never injected as HTML, avoiding any XSS risk.
 */
export function Highlight({ snippet }: { snippet: string }) {
  const parts = snippet.split(/([\x01\x02])/)
  const out: ReactNode[] = []
  let inMark = false
  for (const part of parts) {
    if (part === '\x01') inMark = true
    else if (part === '\x02') inMark = false
    else if (part) out.push(inMark ? <mark key={out.length}>{part}</mark> : part)
  }
  return <>{out}</>
}

export function KindTag({ kind }: { kind: 'exact' | 'semantic' }) {
  return kind === 'exact' ? (
    <span className="rounded bg-amber/15 px-1.5 py-px text-[9px] font-semibold uppercase tracking-[0.12em] text-amber">
      exact
    </span>
  ) : (
    <span className="rounded bg-cyan/15 px-1.5 py-px text-[9px] font-semibold uppercase tracking-[0.12em] text-cyan">
      semantic
    </span>
  )
}

// -- shared action buttons -------------------------------------------------------
export function CopyPathButton({ path }: { path: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      title="Copy file path"
      onClick={() => {
        navigator.clipboard.writeText(path)
        setCopied(true)
        setTimeout(() => setCopied(false), 1200)
      }}
      className="rounded-md p-1.5 text-dim transition hover:bg-raise hover:text-fg"
    >
      {copied ? <Check size={14} className="text-green" /> : <Copy size={14} />}
    </button>
  )
}

export function RevealButton({ fileId }: { fileId: number }) {
  return (
    <button
      title="Reveal in Finder"
      onClick={() => api.reveal(fileId)}
      className="rounded-md p-1.5 text-dim transition hover:bg-raise hover:text-fg"
    >
      <FolderSearch size={14} />
    </button>
  )
}

// -- transcript drawer -------------------------------------------------------------
export function TranscriptDrawer({ fileId, onClose }: { fileId: number; onClose: () => void }) {
  const [detail, setDetail] = useState<FileDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { play } = usePlayer()

  useEffect(() => {
    setDetail(null)
    setError(null)
    api.fileDetail(fileId).then(setDetail).catch((e) => setError(String(e)))
  }, [fileId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink/60 backdrop-blur-[2px]" onClick={onClose} />
      <aside className="fixed bottom-0 right-0 top-0 z-50 flex w-[480px] max-w-[90vw] flex-col border-l border-line bg-panel shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <div className="font-display text-[15px] font-semibold leading-tight">
              {detail?.filename ?? '…'}
            </div>
            {detail && (
              <div className="tc mt-1 truncate text-[11px] text-faint" title={detail.path}>
                {detail.path}
              </div>
            )}
            {detail && (
              <div className="mt-2 flex items-center gap-2">
                <SourceChip kind={detail.source_kind} />
                <span className="tc text-[11px] text-dim">{formatTime(detail.duration)}</span>
                {detail.ixml_scene && (
                  <span className="tc text-[11px] text-dim">
                    S:{detail.ixml_scene} T:{detail.ixml_take}
                  </span>
                )}
                <RevealButton fileId={detail.id} />
                <CopyPathButton path={detail.path} />
              </div>
            )}
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 text-dim hover:bg-raise hover:text-fg">
            <X size={16} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-2 py-3 pb-24">
          {!detail && !error && (
            <div className="flex items-center gap-2 px-4 py-8 text-dim">
              <Loader2 size={15} className="animate-spin" /> Loading transcript…
            </div>
          )}
          {error && <div className="px-4 py-8 text-[13px] text-red">{error}</div>}
          {detail?.segments.length === 0 && (
            <div className="px-4 py-8 text-[13px] text-faint">No speech detected.</div>
          )}
          {detail?.segments.map((s, i) => (
            <button
              key={i}
              onClick={() =>
                play({
                  fileId: detail.id,
                  filename: detail.filename,
                  sourceKind: detail.source_kind,
                  startAt: s.start,
                })
              }
              className="group flex w-full items-start gap-3 rounded-md px-3 py-2 text-left transition hover:bg-panel2"
            >
              <span className="tc mt-px shrink-0 text-[11px] text-faint group-hover:text-amber">
                {formatTime(s.start)}
              </span>
              <span className="text-[13.5px] leading-relaxed text-fg/90">{s.text}</span>
            </button>
          ))}
        </div>
      </aside>
    </>
  )
}
