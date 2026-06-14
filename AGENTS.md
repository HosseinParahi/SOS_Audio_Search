# AGENTS.md — guide for AI agents & contributors

Read this before changing anything. It's the single source of truth for how this repo is
built, run, and verified. (`CLAUDE.md` just points here.)

## What this project is

**Audio Search** is a local-only webapp for film/ad post-production. A user has piles of
unorganized production audio (boom mics, lavalier mics, camera scratch audio, recorder
files) and can't find specific takes. This app indexes those folders **in place**,
transcribes every file with a local Whisper model, and provides hybrid (semantic + exact)
search over the transcripts. Matching takes are grouped (the same line captured by boom +
lav + camera shows as one result), playable from the matched timestamp, and revealable in
Finder so the user can drag the original into their editing timeline.

## Hard constraints (do not violate)

- **macOS on Apple Silicon only.** Transcription uses `mlx-whisper`, which requires an
  Apple-Silicon GPU. Don't suggest porting to Intel/Windows/Linux without replacing the
  transcription backend.
- **Python is pinned to 3.12** via `uv` — see [backend/pyproject.toml](backend/pyproject.toml)
  (`requires-python`). The system may ship a newer Python (3.13/3.14) whose wheels break
  the ML deps. Always run the backend through `uv run …`, never bare `python`.
- **`ffmpeg` must be on PATH.** Used for probing, audio extraction, transcode proxies, and
  waveform peaks.
- **Index in place.** Never move, copy, rename, or write to the user's audio files. The
  app only reads them. Derived data lives under `backend/data/` (gitignored).

## Setup

```bash
brew install ffmpeg uv node      # system tools
cd backend && uv sync            # backend env (uv creates .venv, Python 3.12)
cd ../frontend && npm install    # frontend deps
```

## Run

```bash
./start.sh        # production: builds frontend, serves UI + API on http://localhost:8000

# OR, for development (two terminals):
cd backend  && uv run uvicorn app.main:app --reload   # API + UI, port 8000
cd frontend && npm run dev                             # UI hot reload, port 5173 (proxies /api → 8000)
```

First indexing run downloads models (~1.6 GB Whisper + ~130 MB embedder), once.

## Architecture map

### Backend — `backend/app/` (FastAPI, single SQLite DB)

| File | Responsibility |
|------|----------------|
| [config.py](backend/app/config.py) | Paths, model names, tunables (window size, grouping thresholds, recognized extensions). |
| [db.py](backend/app/db.py) | SQLite schema + connection (loads sqlite-vec). Tables: `folders`, `files`, `segments` (+`segments_fts` FTS5), `windows` (+`vec_windows`), `vec_files`. |
| [scanner.py](backend/app/scanner.py) | Folder walk, `ffprobe` validation, content hashing (dedupe), BWF iXML scene/take parse, source-kind heuristic (boom/lav/camera/recorder from filename). |
| [transcribe.py](backend/app/transcribe.py) | `mlx-whisper` wrapper → timestamped segments. Model loads lazily, once. |
| [embeddings.py](backend/app/embeddings.py) | `bge-small-en-v1.5` via sentence-transformers; merges segments into ~30 s windows. |
| [grouping.py](backend/app/grouping.py) | Clusters near-duplicate takes (iXML scene/take, else transcript-embedding similarity + duration proximity). |
| [search.py](backend/app/search.py) | Hybrid search: FTS5 BM25 + sqlite-vec KNN → reciprocal rank fusion → collapse to take groups. |
| [media.py](backend/app/media.py) | HTTP range streaming of originals; one-time m4a transcode proxy for non-web-safe sources. |
| [peaks.py](backend/app/peaks.py) | Precomputed waveform peaks (cached JSON) for the player. |
| [pipeline.py](backend/app/pipeline.py) | Background ingest: scan → transcribe → embed → group. Single GPU worker thread; progress fans out to SSE subscribers. |
| [main.py](backend/app/main.py) | FastAPI app + all routes (folders, files, search, media, SSE events). Serves the built frontend. |

### Frontend — `frontend/src/` (React + TS + Tailwind v4 + lucide-react + wavesurfer.js)

| File | Responsibility |
|------|----------------|
| [api.ts](frontend/src/api.ts) | Typed API client + shared types + time formatting. |
| [player.tsx](frontend/src/player.tsx) | Persistent bottom audio player (wavesurfer waveform, transport, volume, speed) exposed via `usePlayer()` context. |
| [ui.tsx](frontend/src/ui.tsx) | Shared bits: source chips, status badges, `Highlight`, copy/reveal buttons, transcript drawer. |
| [views/SearchView.tsx](frontend/src/views/SearchView.tsx) | Debounced live search; take-group result cards. |
| [views/LibraryView.tsx](frontend/src/views/LibraryView.tsx) | Folder management + file table + live SSE indexing progress. |
| [App.tsx](frontend/src/App.tsx) | Shell: left icon rail, view switching, global stats poll. |

## Conventions

- **Pipeline is resumable & idempotent.** Per-file `status` drives processing; re-running
  reprocesses cleanly (`db.delete_file_index` clears derived rows first). Don't introduce
  steps that can't be safely re-run.
- **ffmpeg/ffprobe via list-args only** (`subprocess.run([...])`) — never shell strings.
  User paths contain spaces and unicode.
- **No raw HTML into React.** FTS highlights come back wrapped in `\x01`/`\x02` marker
  chars and are rendered by the `Highlight` component ([ui.tsx](frontend/src/ui.tsx)) — do
  not switch to `dangerouslySetInnerHTML`.
- **One SQLite connection per request/worker**, closed in `finally`. WAL mode is on.

## Verify a change

```bash
cd frontend && npx tsc -b && npm run build      # frontend type-check + build
cd backend  && uv run python -c "import app.main"  # backend imports cleanly
curl -s localhost:8000/api/stats                 # smoke test a running server
```

Reset all indexed state: stop the server, delete `backend/data/`.

## Gotchas

- First run downloads ~1.7 GB of models; needs internet that one time.
- `backend/data/` (DB + transcode/peak caches) is **gitignored** — it's regenerated.
- Never commit `node_modules/`, `backend/.venv/`, `frontend/dist/`, `*.log`, `.DS_Store`.
- Don't change ports casually: the frontend dev proxy and `start.sh` both assume API on 8000.
