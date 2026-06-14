# Audio Search

Local webapp that turns a messy pile of production audio into a searchable database.
Point it at folders of WAV/BWF/MP3/M4A/MOV/MP4 files — it transcribes everything with
Whisper (runs locally on Apple Silicon, nothing leaves your machine), indexes the
transcripts for hybrid semantic + exact search, and groups duplicate takes recorded by
boom / lav / camera. Search a line of dialogue, play the match from its exact
timestamp, then reveal the original file in Finder to drag into your NLE.

Files are indexed **in place** — never moved, copied, or renamed.

## Requirements

- macOS on Apple Silicon (Whisper runs via MLX)
- `ffmpeg` on PATH (`brew install ffmpeg`)
- [`uv`](https://docs.astral.sh/uv/) (`brew install uv`)
- Node 20+ (only to build/dev the frontend)

First run downloads models automatically: Whisper large-v3-turbo (~1.6 GB) and the
bge-small embedding model (~130 MB).

## Run it

```bash
./start.sh
```

Then open <http://localhost:8000>, go to **Library**, paste a folder path, and watch it
index. Search lives on the first tab.

`start.sh` builds the frontend once (if needed) and starts the backend, which serves
the built UI on port 8000.

## Development

```bash
# backend (port 8000)
cd backend && uv run uvicorn app.main:app --reload

# frontend with hot reload (port 5173, proxies /api to 8000)
cd frontend && npm install && npm run dev
```

## How it works

- **Backend** ([backend/app](backend/app)): FastAPI + single SQLite database
  (FTS5 for exact text, [sqlite-vec](https://github.com/asg017/sqlite-vec) for
  embeddings). Pipeline per file: ffprobe → mlx-whisper transcription → bge-small
  embeddings over ~30 s windows → take grouping (BWF iXML scene/take when present,
  transcript-similarity otherwise). Progress streams to the UI over SSE.
- **Search** ([backend/app/search.py](backend/app/search.py)): BM25 + vector KNN fused
  with reciprocal rank fusion, collapsed to one card per take group.
- **Playback**: originals stream with HTTP range support; browser-unfriendly sources
  (camera MOVs, polyphonic WAVs) get a one-time m4a proxy in
  `backend/data/cache/`. Waveforms come from precomputed peaks.
- **Frontend** ([frontend/src](frontend/src)): React + Tailwind + lucide-react +
  wavesurfer.js, dark theme.

## Notes

- Re-adding or rescanning a folder only processes new/changed files (content hash).
- Exact-duplicate files (same content, different location) are marked `duplicate`
  and skipped.
- The index lives in `backend/data/` — delete that directory to start fresh.
