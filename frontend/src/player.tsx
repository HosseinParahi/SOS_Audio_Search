import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import WaveSurfer from 'wavesurfer.js'
import {
  FastForward,
  Pause,
  Play,
  Rewind,
  Volume2,
  VolumeX,
} from 'lucide-react'
import { api, formatTime, mediaUrl } from './api'
import { SourceChip } from './ui'

// Global audio player. A single WaveSurfer instance lives in the persistent footer bar;
// any component calls usePlayer().play(track) to load + play a file from a timestamp.
// Exposed through React context so there's exactly one player for the whole app.

export interface Track {
  fileId: number
  filename: string
  sourceKind?: string
  startAt?: number // seconds to start from (e.g. a search match's timestamp)
}

interface PlayerApi {
  play: (t: Track) => void
  toggle: () => void
  track: Track | null
  playing: boolean
}

const Ctx = createContext<PlayerApi | null>(null)

export function usePlayer(): PlayerApi {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('usePlayer outside PlayerProvider')
  return ctx
}

const RATES = [1, 1.25, 1.5, 2, 0.75]

export function PlayerProvider({ children }: { children: ReactNode }) {
  const [track, setTrack] = useState<Track | null>(null)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [rate, setRate] = useState(1)
  const [loading, setLoading] = useState(false)

  // Refs hold values the WaveSurfer event callbacks need to read *without* re-subscribing.
  // The 'ready' handler is created once; reading volume/rate/seek from refs keeps it
  // current without tearing down and rebuilding the player on every state change.
  const containerRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WaveSurfer | null>(null)
  const loadedId = useRef<number | null>(null)   // which file is currently loaded
  const pendingSeek = useRef<number | null>(null) // seek to apply once 'ready' fires
  const volumeRef = useRef(1)
  const rateRef = useRef(1)

  // Create the WaveSurfer instance once, wire its events to React state, destroy on unmount.
  useEffect(() => {
    if (!containerRef.current) return
    const ws = WaveSurfer.create({
      container: containerRef.current,
      height: 44,
      waveColor: '#3a3d46',
      progressColor: '#ffa733',
      cursorColor: '#e9e7e2',
      cursorWidth: 1,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: false,
    })
    ws.on('play', () => setPlaying(true))
    ws.on('pause', () => setPlaying(false))
    ws.on('finish', () => setPlaying(false))
    ws.on('timeupdate', (t) => setTime(t))
    ws.on('ready', (dur) => {
      // Track is decoded: restore volume/rate, jump to the requested start, and play.
      setDuration(dur)
      setLoading(false)
      ws.setVolume(volumeRef.current)
      ws.setPlaybackRate(rateRef.current, true)
      if (pendingSeek.current != null) {
        ws.setTime(pendingSeek.current)
        pendingSeek.current = null
      }
      ws.play()
    })
    wsRef.current = ws
    return () => {
      ws.destroy()
      wsRef.current = null
      loadedId.current = null
    }
  }, [])

  const play = useCallback((t: Track) => {
    const ws = wsRef.current
    if (!ws) return
    setTrack(t)
    // Same file already loaded: just seek + resume, skip the reload.
    if (loadedId.current === t.fileId) {
      if (t.startAt != null) ws.setTime(t.startAt)
      ws.play()
      return
    }
    loadedId.current = t.fileId
    pendingSeek.current = t.startAt ?? null // applied in the 'ready' handler above
    setLoading(true)
    setTime(0)
    setDuration(0)
    ;(async () => {
      try {
        // Render instantly from precomputed peaks; audio still streams via /api/media.
        const pk = await api.peaks(t.fileId)
        await ws.load(mediaUrl(t.fileId), [pk.peaks], pk.duration)
      } catch {
        try {
          await ws.load(mediaUrl(t.fileId)) // peaks unavailable: let browser decode
        } catch {
          /* aborted by a newer load */
        }
      }
    })()
  }, [])

  const toggle = useCallback(() => {
    wsRef.current?.playPause()
  }, [])

  // Jump forward/back by `delta` seconds, clamped to [0, duration].
  const skip = (delta: number) => {
    const ws = wsRef.current
    if (!ws) return
    ws.setTime(Math.max(0, Math.min(ws.getDuration(), ws.getCurrentTime() + delta)))
  }

  const changeVolume = (v: number) => {
    setVolume(v)
    setMuted(false)
    volumeRef.current = v
    wsRef.current?.setVolume(v)
  }

  const toggleMute = () => {
    const next = !muted
    setMuted(next)
    wsRef.current?.setVolume(next ? 0 : volumeRef.current)
  }

  // Step through the preset playback speeds on each click.
  const cycleRate = () => {
    const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length]
    setRate(next)
    rateRef.current = next
    wsRef.current?.setPlaybackRate(next, true)
  }

  return (
    <Ctx.Provider value={{ play, toggle, track, playing }}>
      {children}
      <footer className="fixed bottom-0 left-0 right-0 z-40 border-t border-line bg-panel/95 backdrop-blur">
        <div className="flex items-center gap-4 px-4 py-2.5">
          {/* now playing */}
          <div className="flex w-56 shrink-0 items-center gap-2.5 overflow-hidden">
            {track ? (
              <>
                <SourceChip kind={track.sourceKind ?? 'unknown'} iconOnly />
                <div className="min-w-0">
                  <div className="tc truncate text-[12px] text-fg" title={track.filename}>
                    {track.filename}
                  </div>
                  <div className="text-[10px] uppercase tracking-[0.14em] text-faint">
                    {loading ? 'loading…' : playing ? 'playing' : 'paused'}
                  </div>
                </div>
              </>
            ) : (
              <div className="text-[12px] text-faint">Nothing playing</div>
            )}
          </div>

          {/* transport */}
          <button
            onClick={() => skip(-10)}
            disabled={!track}
            title="Back 10s"
            className="rounded-md p-2 text-dim transition hover:bg-raise hover:text-fg disabled:opacity-30"
          >
            <Rewind size={16} />
          </button>
          <button
            onClick={toggle}
            disabled={!track}
            title={playing ? 'Pause' : 'Play'}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-amber text-ink shadow-[0_0_18px_rgba(255,167,51,0.35)] transition hover:bg-amber-soft disabled:bg-line2 disabled:text-faint disabled:shadow-none"
          >
            {playing ? <Pause size={17} fill="currentColor" /> : <Play size={17} fill="currentColor" className="ml-0.5" />}
          </button>
          <button
            onClick={() => skip(10)}
            disabled={!track}
            title="Forward 10s"
            className="rounded-md p-2 text-dim transition hover:bg-raise hover:text-fg disabled:opacity-30"
          >
            <FastForward size={16} />
          </button>

          {/* waveform */}
          <span className="tc w-12 text-right text-[11px] text-dim">{formatTime(time)}</span>
          <div ref={containerRef} className="h-11 min-w-0 flex-1 cursor-pointer" />
          <span className="tc w-12 text-[11px] text-faint">{formatTime(duration)}</span>

          {/* rate + volume */}
          <button
            onClick={cycleRate}
            disabled={!track}
            title="Playback speed"
            className="tc w-12 rounded-md border border-line px-1.5 py-1 text-[11px] text-dim transition hover:border-line2 hover:text-fg disabled:opacity-30"
          >
            {rate.toFixed(2).replace(/0$/, '')}×
          </button>
          <div className="flex w-32 shrink-0 items-center gap-2">
            <button
              onClick={toggleMute}
              className="text-dim transition hover:text-fg"
              title={muted ? 'Unmute' : 'Mute'}
            >
              {muted || volume === 0 ? <VolumeX size={16} /> : <Volume2 size={16} />}
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={muted ? 0 : volume}
              onChange={(e) => changeVolume(Number(e.target.value))}
              className="w-full"
            />
          </div>
        </div>
      </footer>
    </Ctx.Provider>
  )
}
