import { useEffect, useState } from 'react'
import { AudioLines, LibraryBig, Search } from 'lucide-react'
import { api, type Stats } from './api'
import { PlayerProvider } from './player'
import LibraryView from './views/LibraryView'
import SearchView from './views/SearchView'

// App shell: a left icon rail switches between the two views; the player footer wraps
// everything (PlayerProvider) so it persists across view changes. A lightweight stats
// poll drives the "indexing" indicator on the rail.

type View = 'search' | 'library'

export default function App() {
  const [view, setView] = useState<View>('search')
  const [stats, setStats] = useState<Stats | null>(null)

  // Poll stats every 5s for the rail's busy indicator. `alive` guards against a state
  // update after unmount.
  useEffect(() => {
    let alive = true
    const tick = () => api.stats().then((s) => alive && setStats(s)).catch(() => {})
    tick()
    const t = setInterval(tick, 5000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  const busy = (stats?.queue ?? 0) > 0 || stats?.scanning

  return (
    <PlayerProvider>
      <div className="atmosphere grain flex h-full">
        {/* icon rail */}
        <nav className="z-30 flex w-14 shrink-0 flex-col items-center border-r border-line bg-panel/80 py-4 backdrop-blur">
          <AudioLines size={22} className="mb-6 text-amber" />
          <RailButton
            active={view === 'search'}
            onClick={() => setView('search')}
            title="Search"
          >
            <Search size={18} />
          </RailButton>
          <RailButton
            active={view === 'library'}
            onClick={() => setView('library')}
            title="Library"
          >
            <LibraryBig size={18} />
          </RailButton>
          <div className="mt-auto flex flex-col items-center gap-1.5 pb-20" title={
            busy ? `Indexing — ${stats?.queue ?? 0} in queue` : 'Index idle'
          }>
            <span
              className={`h-2 w-2 rounded-full ${
                busy ? 'pulse-dot bg-amber' : 'bg-green/70'
              }`}
            />
            {busy && (
              <span className="tc text-[10px] text-amber">{stats?.queue ?? 0}</span>
            )}
          </div>
        </nav>

        <main className="min-w-0 flex-1 overflow-y-auto">
          {view === 'search' ? <SearchView /> : <LibraryView />}
        </main>
      </div>
    </PlayerProvider>
  )
}

function RailButton({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean
  onClick: () => void
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`relative mb-1.5 grid h-10 w-10 place-items-center rounded-lg transition ${
        active ? 'bg-raise text-amber' : 'text-dim hover:bg-panel2 hover:text-fg'
      }`}
    >
      {active && (
        <span className="absolute -left-2 h-5 w-0.5 rounded-full bg-amber" />
      )}
      {children}
    </button>
  )
}
