import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AudioLines,
  ChevronDown,
  ChevronRight,
  FileText,
  Layers,
  Loader2,
  Play,
  Search,
} from 'lucide-react'
import { api, formatTime, type FileHit, type Group } from '../api'
import { usePlayer } from '../player'
import { CopyPathButton, Highlight, KindTag, RevealButton, SourceChip, TranscriptDrawer } from '../ui'

// Search page: a debounced live search box and a list of take-group cards. Each card is
// one take; its primary (best-matching) recording is shown, with sibling sources
// (boom/lav/camera) collapsed behind a toggle.

export default function SearchView() {
  const [q, setQ] = useState('')
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [drawerFile, setDrawerFile] = useState<number | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const seq = useRef(0)

  const runSearch = useCallback(async (query: string) => {
    // `seq` guards against out-of-order responses: only the latest request applies its
    // result (a slow earlier query can't overwrite a newer one).
    const mine = ++seq.current
    if (!query.trim()) {
      setGroups(null)
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await api.search(query)
      if (seq.current === mine) setGroups(res.groups)
    } catch (e) {
      if (seq.current === mine) setError(String(e))
    } finally {
      if (seq.current === mine) setLoading(false)
    }
  }, [])

  // Debounce: search 350ms after the user stops typing, so we don't fire on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => runSearch(q), 350)
    return () => clearTimeout(t)
  }, [q, runSearch])

  useEffect(() => inputRef.current?.focus(), [])

  const idle = groups === null && !loading

  return (
    <div className={`mx-auto w-full max-w-4xl px-6 ${idle ? 'pt-[18vh]' : 'pt-10'} pb-32 transition-all`}>
      {idle && (
        <div className="rise mb-8 text-center">
          <AudioLines size={34} className="mx-auto mb-5 text-amber" />
          <h1 className="font-display text-[42px] font-bold leading-none tracking-tight">
            Find the take.
          </h1>
          <p className="mt-3 text-[14px] text-dim">
            Search everything anyone said, across every mic and every card.
          </p>
        </div>
      )}

      <div className="sticky top-4 z-30">
        <div className="flex items-center gap-3 rounded-xl border border-line bg-panel2/95 px-4 shadow-[0_8px_30px_rgba(0,0,0,0.4)] backdrop-blur transition focus-within:border-amber/50">
          {loading ? (
            <Loader2 size={18} className="shrink-0 animate-spin text-amber" />
          ) : (
            <Search size={18} className="shrink-0 text-dim" />
          )}
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="a line of dialogue, or what it was about…"
            className="tc w-full bg-transparent py-3.5 text-[15px] text-fg outline-none placeholder:text-faint"
          />
          {q && (
            <button
              onClick={() => setQ('')}
              className="text-[11px] uppercase tracking-wider text-faint hover:text-fg"
            >
              clear
            </button>
          )}
        </div>
        {idle && (
          <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
            {['coffee', 'morning sunshine', 'talks about adventure'].map((hint) => (
              <button
                key={hint}
                onClick={() => setQ(hint)}
                className="rounded-full border border-line px-3 py-1 text-[12px] text-dim transition hover:border-amber/40 hover:text-amber"
              >
                {hint}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="mt-6 rounded-lg border border-red/30 bg-red/10 px-4 py-3 text-[13px] text-red">
          {error}
        </div>
      )}

      {groups && groups.length === 0 && !loading && (
        <div className="mt-16 text-center text-dim">
          <Search size={28} className="mx-auto mb-3 opacity-40" />
          <p className="text-[14px]">No matches for “{q}”.</p>
          <p className="mt-1 text-[12px] text-faint">
            Try fewer words, or describe the topic instead of the exact line.
          </p>
        </div>
      )}

      {groups && groups.length > 0 && (
        <div className="mt-6 space-y-4">
          <div className="tc text-[11px] uppercase tracking-[0.14em] text-faint">
            {groups.length} take{groups.length === 1 ? '' : 's'}
          </div>
          {groups.map((g, i) => (
            <GroupCard
              key={g.group_id}
              group={g}
              delay={i * 45}
              onTranscript={(id) => setDrawerFile(id)}
            />
          ))}
        </div>
      )}

      {drawerFile != null && (
        <TranscriptDrawer fileId={drawerFile} onClose={() => setDrawerFile(null)} />
      )}
    </div>
  )
}

// One take = one card. `delay` staggers the entrance animation down the list.
function GroupCard({
  group,
  delay,
  onTranscript,
}: {
  group: Group
  delay: number
  onTranscript: (id: number) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const primary = group.files[0]      // best-matching recording, shown by default
  const siblings = group.files.slice(1) // other mics/cards of the same take

  return (
    <article
      className="rise overflow-hidden rounded-xl border border-line bg-panel"
      style={{ animationDelay: `${delay}ms` }}
    >
      <header className="flex items-center gap-3 border-b border-line/70 bg-panel2/60 px-4 py-2">
        <Layers size={13} className="text-amber" />
        <span className="tc text-[11px] font-medium uppercase tracking-[0.16em] text-dim">
          {primary.ixml_scene
            ? `Scene ${primary.ixml_scene} · Take ${primary.ixml_take}`
            : `Take group ${group.group_id}`}
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {group.files.map((f) => (
            <SourceChip key={f.id} kind={f.source_kind} iconOnly />
          ))}
        </div>
      </header>

      <FileRow file={primary} onTranscript={onTranscript} primary />

      {siblings.length > 0 && (
        <div className="border-t border-line/70">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex w-full items-center gap-1.5 px-4 py-2 text-[11px] uppercase tracking-[0.12em] text-faint transition hover:text-dim"
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {siblings.length} more source{siblings.length === 1 ? '' : 's'} of this take
          </button>
          {expanded &&
            siblings.map((f) => <FileRow key={f.id} file={f} onTranscript={onTranscript} />)}
        </div>
      )}
    </article>
  )
}

// One recording within a take: play button, source chip, match snippets, and actions.
function FileRow({
  file,
  onTranscript,
  primary = false,
}: {
  file: FileHit
  onTranscript: (id: number) => void
  primary?: boolean
}) {
  const { play } = usePlayer()
  const startAt = file.matches[0]?.start // play from the first match by default

  return (
    <div className={`px-4 py-3 ${primary ? '' : 'border-t border-line/40 bg-panel2/40'}`}>
      <div className="flex items-center gap-2.5">
        <button
          onClick={() =>
            play({
              fileId: file.id,
              filename: file.filename,
              sourceKind: file.source_kind,
              startAt,
            })
          }
          title={startAt != null ? `Play from ${formatTime(startAt)}` : 'Play'}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-line2 text-fg transition hover:border-amber hover:bg-amber hover:text-ink"
        >
          <Play size={13} fill="currentColor" className="ml-px" />
        </button>
        <SourceChip kind={file.source_kind} />
        <span className="tc min-w-0 truncate text-[13px] text-fg" title={file.path}>
          {file.filename}
        </span>
        <span className="tc shrink-0 text-[11px] text-faint">{formatTime(file.duration)}</span>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <button
            title="View transcript"
            onClick={() => onTranscript(file.id)}
            className="rounded-md p-1.5 text-dim transition hover:bg-raise hover:text-fg"
          >
            <FileText size={14} />
          </button>
          <RevealButton fileId={file.id} />
          <CopyPathButton path={file.path} />
        </div>
      </div>

      {file.matches.length > 0 && (
        <div className="mt-2.5 space-y-1.5 pl-[42px]">
          {file.matches.map((m, i) => (
            <button
              key={i}
              onClick={() =>
                play({
                  fileId: file.id,
                  filename: file.filename,
                  sourceKind: file.source_kind,
                  startAt: m.start,
                })
              }
              className="group flex w-full items-baseline gap-2.5 rounded-md px-2 py-1.5 text-left transition hover:bg-panel2"
            >
              <span className="tc shrink-0 text-[11px] text-faint transition group-hover:text-amber">
                {formatTime(m.start)}
              </span>
              <KindTag kind={m.kind} />
              <span className="min-w-0 text-[13.5px] leading-relaxed text-fg/85">
                <Highlight snippet={m.snippet} />
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
