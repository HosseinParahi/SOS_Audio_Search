import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Clock,
  FilesIcon,
  FolderPlus,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import {
  api,
  formatDuration,
  formatTime,
  type Folder,
  type LibFile,
  type PipelineEvent,
  type Stats,
} from '../api'
import { usePlayer } from '../player'
import { CopyPathButton, RevealButton, SourceChip, StatusBadge, TranscriptDrawer } from '../ui'

// Library page: add/remove folders, see indexing stats, and a live file table. Status
// updates arrive over Server-Sent Events so badges change in real time without polling.

export default function LibraryView() {
  const [folders, setFolders] = useState<Folder[]>([])
  const [files, setFiles] = useState<LibFile[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [newPath, setNewPath] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [drawerFile, setDrawerFile] = useState<number | null>(null)
  const { play } = usePlayer()
  // Ids we've already rendered — lets the SSE handler tell a status change (patch in place)
  // from a newly discovered file (needs a full refresh to appear in the table).
  const knownIds = useRef<Set<number>>(new Set())

  // Full reload of folders + files + stats (on mount, after add/remove, and on scan events).
  const refresh = useCallback(async () => {
    const [fo, fi, st] = await Promise.all([api.folders(), api.files(), api.stats()])
    setFolders(fo)
    setFiles(fi)
    setStats(st)
    knownIds.current = new Set(fi.map((f) => f.id))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Subscribe to live pipeline events. Known file -> patch its row in place (cheap);
  // unknown file or a scan event -> full refresh. Connection closes on unmount.
  useEffect(() => {
    const es = new EventSource('/api/events')
    es.onmessage = (msg) => {
      const ev: PipelineEvent = JSON.parse(msg.data)
      if (ev.type === 'file' && ev.id != null) {
        if (!knownIds.current.has(ev.id)) {
          refresh()
          return
        }
        setFiles((prev) =>
          prev.map((f) =>
            f.id === ev.id ? { ...f, status: ev.status ?? f.status, error: ev.error ?? null } : f,
          ),
        )
        api.stats().then(setStats).catch(() => {}) // keep the counters in sync
      } else if (ev.type === 'scan') {
        refresh()
      }
    }
    return () => es.close()
  }, [refresh])

  const addFolder = async () => {
    if (!newPath.trim()) return
    setAdding(true)
    setAddError(null)
    try {
      await api.addFolder(newPath.trim())
      setNewPath('')
      await refresh()
    } catch (e) {
      setAddError(e instanceof Error ? e.message : String(e))
    } finally {
      setAdding(false)
    }
  }

  const removeFolder = async (id: number) => {
    await api.removeFolder(id)
    refresh()
  }

  const indexedHours = files
    .filter((f) => f.status === 'done')
    .reduce((acc, f) => acc + (f.duration ?? 0), 0)

  return (
    <div className="mx-auto w-full max-w-5xl px-6 pb-32 pt-10">
      <h1 className="font-display text-[26px] font-bold tracking-tight">Library</h1>
      <p className="mt-1 text-[13px] text-dim">
        Folders are indexed in place — nothing is moved or copied.
      </p>

      {/* stats strip */}
      <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          icon={<FilesIcon size={15} />}
          label="Files"
          value={String(stats?.total_files ?? files.length)}
        />
        <StatCard
          icon={<Clock size={15} />}
          label="Indexed audio"
          value={formatDuration(indexedHours)}
        />
        <StatCard
          icon={
            (stats?.queue ?? 0) > 0 ? (
              <Loader2 size={15} className="animate-spin text-amber" />
            ) : (
              <RefreshCw size={15} />
            )
          }
          label="Queue"
          value={String(stats?.queue ?? 0)}
          accent={(stats?.queue ?? 0) > 0}
        />
        <StatCard
          icon={<TriangleAlert size={15} />}
          label="Errors"
          value={String(stats?.by_status?.error ?? 0)}
          danger={(stats?.by_status?.error ?? 0) > 0}
        />
      </div>

      {/* folders */}
      <section className="mt-8">
        <div className="flex items-center gap-2">
          <input
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addFolder()}
            placeholder="/path/to/your/audio/folder"
            className="tc flex-1 rounded-lg border border-line bg-panel2 px-3.5 py-2.5 text-[13px] text-fg outline-none transition placeholder:text-faint focus:border-amber/50"
          />
          <button
            onClick={addFolder}
            disabled={adding || !newPath.trim()}
            className="flex items-center gap-2 rounded-lg bg-amber px-4 py-2.5 text-[13px] font-semibold text-ink transition hover:bg-amber-soft disabled:opacity-40"
          >
            {adding ? <Loader2 size={15} className="animate-spin" /> : <FolderPlus size={15} />}
            Add folder
          </button>
          <button
            onClick={() => api.rescan()}
            title="Rescan all folders for new files"
            className="flex items-center gap-2 rounded-lg border border-line px-3.5 py-2.5 text-[13px] text-dim transition hover:border-line2 hover:text-fg"
          >
            <RefreshCw size={14} />
            Rescan
          </button>
        </div>
        {addError && <div className="mt-2 text-[12px] text-red">{addError}</div>}

        {folders.length > 0 && (
          <div className="mt-3 space-y-1.5">
            {folders.map((f) => (
              <div
                key={f.id}
                className="group flex items-center gap-3 rounded-lg border border-line/60 bg-panel px-3.5 py-2"
              >
                <span className="tc min-w-0 flex-1 truncate text-[12.5px] text-fg/90">
                  {f.path}
                </span>
                <span className="tc text-[11px] text-faint">{f.file_count} files</span>
                <button
                  onClick={() => removeFolder(f.id)}
                  title="Remove folder and its index (files on disk untouched)"
                  className="rounded-md p-1.5 text-faint opacity-0 transition hover:bg-raise hover:text-red group-hover:opacity-100"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* file table */}
      <section className="mt-8">
        {files.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line px-6 py-14 text-center">
            <FolderPlus size={26} className="mx-auto mb-3 text-faint" />
            <p className="text-[14px] text-dim">Add a folder above to start indexing.</p>
            <p className="mt-1 text-[12px] text-faint">
              WAV, BWF, MP3, M4A and video files are all fair game.
            </p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-line">
            <table className="w-full table-fixed text-left text-[13px]">
              <thead>
                <tr className="border-b border-line bg-panel2/70 text-[10px] uppercase tracking-[0.14em] text-faint">
                  <th className="w-12 px-3 py-2.5" />
                  <th className="px-2 py-2.5 font-medium">File</th>
                  <th className="w-24 px-2 py-2.5 font-medium">Source</th>
                  <th className="w-20 px-2 py-2.5 font-medium">Length</th>
                  <th className="w-36 px-2 py-2.5 font-medium">Status</th>
                  <th className="w-28 px-2 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {files.map((f) => (
                  <tr
                    key={f.id}
                    className="group border-b border-line/40 bg-panel transition last:border-0 hover:bg-panel2/60"
                  >
                    <td className="px-3 py-2">
                      <button
                        onClick={() =>
                          play({ fileId: f.id, filename: f.filename, sourceKind: f.source_kind })
                        }
                        disabled={f.status !== 'done' && f.status !== 'duplicate'}
                        title="Play"
                        className="grid h-7 w-7 place-items-center rounded-full border border-line2 text-fg transition hover:border-amber hover:bg-amber hover:text-ink disabled:opacity-20"
                      >
                        <Play size={11} fill="currentColor" className="ml-px" />
                      </button>
                    </td>
                    <td className="max-w-0 px-2 py-2">
                      <button
                        onClick={() => f.status === 'done' && setDrawerFile(f.id)}
                        className={`tc block w-full truncate text-left text-[12.5px] ${
                          f.status === 'done' ? 'text-fg hover:text-amber' : 'text-dim'
                        }`}
                        title={f.path}
                      >
                        {f.filename}
                      </button>
                      {f.error && (
                        <div className="truncate text-[11px] text-red/80" title={f.error}>
                          {f.error}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-2">
                      <SourceChip kind={f.source_kind} />
                    </td>
                    <td className="tc px-2 py-2 text-[12px] text-dim">
                      {formatTime(f.duration)}
                    </td>
                    <td className="px-2 py-2">
                      <StatusBadge status={f.status} />
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-center justify-end gap-0.5 opacity-0 transition group-hover:opacity-100">
                        {f.status === 'error' && (
                          <button
                            title="Retry"
                            onClick={() => api.retry(f.id)}
                            className="rounded-md p-1.5 text-dim transition hover:bg-raise hover:text-amber"
                          >
                            <RotateCcw size={14} />
                          </button>
                        )}
                        <RevealButton fileId={f.id} />
                        <CopyPathButton path={f.path} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {drawerFile != null && (
        <TranscriptDrawer fileId={drawerFile} onClose={() => setDrawerFile(null)} />
      )}
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
  accent = false,
  danger = false,
}: {
  icon: React.ReactNode
  label: string
  value: string
  accent?: boolean
  danger?: boolean
}) {
  return (
    <div
      className={`rounded-xl border bg-panel px-4 py-3 ${
        danger ? 'border-red/40' : accent ? 'border-amber/40' : 'border-line'
      }`}
    >
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-faint">
        {icon}
        {label}
      </div>
      <div
        className={`tc mt-1.5 text-[22px] font-semibold leading-none ${
          danger ? 'text-red' : accent ? 'text-amber' : 'text-fg'
        }`}
      >
        {value}
      </div>
    </div>
  )
}
