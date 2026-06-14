# Audio Search

![platform: macOS Apple Silicon](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-black)
![license: MIT](https://img.shields.io/badge/license-MIT-blue)

Turn a messy pile of production audio into a searchable database. Point it at folders of
WAV/BWF/MP3/M4A/MOV/MP4 files — it transcribes everything with Whisper (runs **locally** on Apple
Silicon, nothing leaves your machine), indexes the transcripts for hybrid semantic + exact search,
and groups duplicate takes recorded by boom / lav / camera. Search a line of dialogue, play the
match from its exact timestamp, then reveal the original file in Finder to drag into your NLE.

Files are indexed **in place** — never moved, copied, or renamed.

### What you'll be able to do

1. Add folders of audio/video — they get transcribed in the background.
2. Search by exact line ("best coffee in town") **or** by meaning ("someone talking about hiking").
3. See every take grouped together (boom + lav + camera = one result), play any source from the
   matched moment, and jump to the original file in Finder.

> **Hard requirement: macOS on Apple Silicon (M1/M2/M3/M4).**
> Transcription uses [`mlx-whisper`](https://github.com/ml-explore/mlx-examples), which only runs on
> Apple-Silicon GPUs. It will **not** work on Intel Macs, Windows, or Linux.

---

## Two ways to run

### Option A — Download the Mac app (easiest, no setup)

1. Grab the latest **`AudioSearch-…-arm64.dmg`** from the
   [**Releases**](https://github.com/HosseinParahi/SOS_Audio_Search/releases) page.
2. Open the `.dmg` and drag **Audio Search** to Applications.
3. **First launch:** the app is not code-signed yet, so macOS Gatekeeper will block it. Either
   **right-click the app → Open** (then confirm once), or run:
   ```bash
   xattr -dr com.apple.quarantine "/Applications/Audio Search.app"
   ```
4. Add a folder with the native **Choose Folder…** picker and start searching.

Everything is bundled inside the app — no terminal, Python, or Homebrew needed. The **first** time
you index, it downloads the AI models once (~1.7 GB) into `~/Library/Application Support/`; needs
internet that one time only, fully offline after.

> The `.app` is ~1 GB because the Python + ML stack (Whisper/MLX, embeddings) ships inside it.
> Apple-Silicon only.

### Option B — Run the webapp locally (from source)

Best if you want to develop, tweak, or prefer running in your browser. Full guide below.

---

## Webapp setup

### 1. Prerequisites

Install the system tools. If you don't have Homebrew yet:

```bash
# Xcode command-line tools (git, compilers) — skip if already installed
xcode-select --install

# Homebrew (the macOS package manager) — skip if you already have `brew`
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install the three things this project needs:

```bash
brew install ffmpeg uv node
```

| Tool | Why it's needed |
|------|-----------------|
| **ffmpeg** | Decodes/extracts audio from any format (incl. video files) |
| **uv** | Python package manager — creates the backend environment and pins Python 3.12 automatically |
| **node** | Builds the web frontend (v20+) |

No need to install Python yourself — `uv` downloads the correct version (3.12).

### 2. Get the code

```bash
git clone git@github.com:HosseinParahi/SOS_Audio_Search.git
cd SOS_Audio_Search
```

### 3. Run it

```bash
chmod +x start.sh   # only needed the first time
./start.sh
```

`start.sh` builds the web UI (first time only) and starts the server.

> **First run is slow.** It downloads the AI models the first time you actually index audio:
> Whisper large-v3-turbo (~1.6 GB) and the bge-small embedding model (~130 MB). This happens once —
> later runs are fast. You need an internet connection for this first download only; everything
> after that is fully offline.

When you see the server start, open **<http://localhost:8000>**.

### 4. First use

1. Click the **Library** tab (book icon, left rail).
2. Paste a folder path that contains your audio (e.g. `/Users/you/Shoots/Day1`) and click
   **Add folder**.
3. Watch the status badges: `queued → transcribing → embedding → indexed`. You can keep using the
   app while it works; progress updates live.
4. Switch to the **Search** tab and type a line someone said, or describe what was discussed.
5. Click ▶ on any result to play it from the matched moment. Use the folder icon to **reveal the
   original file in Finder**, or the copy icon to copy its path.

### 5. Manual run (if `start.sh` fails)

Run the backend and frontend yourself in two terminals.

```bash
# Terminal 1 — backend API + UI on http://localhost:8000
cd backend
uv run uvicorn app.main:app --reload
```

```bash
# Terminal 2 — frontend with hot reload on http://localhost:5173
# (proxies /api calls to the backend on 8000; use this for UI development)
cd frontend
npm install
npm run dev
```

For a one-off production build of the UI without the script:

```bash
cd frontend && npm install && npm run build
# then run the backend as above — it serves frontend/dist automatically
```

### 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Port 8000 is already in use` | Something else is on 8000. Stop it, or find it: `lsof -ti :8000` then `kill <pid>`. |
| `ffmpeg: command not found` | `brew install ffmpeg`, then reopen the terminal. |
| First index hangs for minutes | It's downloading the Whisper model (~1.6 GB). Watch the backend logs; it only happens once. Needs internet. |
| `ModuleNotFoundError` / wrong Python | Always start the backend with `uv run …` (not bare `python`). `uv` pins Python 3.12; the system Python may be too new for the ML wheels. |
| Search returns nothing | Files may still be indexing — check the Library tab. Search only matches files showing `indexed`. |
| Want a clean slate | Stop the server and delete `backend/data/` (the index + caches). Re-add your folders. |
| The Mac app won't open ("damaged"/"unidentified developer") | It's unsigned — right-click → Open, or `xattr -dr com.apple.quarantine "/Applications/Audio Search.app"`. |

---

## How it works

- **Backend** ([backend/app](backend/app)): FastAPI + a single SQLite database (FTS5 for exact text,
  [sqlite-vec](https://github.com/asg017/sqlite-vec) for embeddings). Pipeline per file: ffprobe →
  mlx-whisper transcription → bge-small embeddings over ~30 s windows → take grouping (BWF iXML
  scene/take when present, transcript-similarity otherwise). Progress streams to the UI over SSE.
- **Search** ([backend/app/search.py](backend/app/search.py)): BM25 + vector KNN fused with
  reciprocal rank fusion, collapsed to one card per take group.
- **Playback**: originals stream with HTTP range support; browser-unfriendly sources (camera MOVs,
  polyphonic WAVs) get a one-time m4a proxy. Waveforms come from precomputed peaks.
- **Frontend** ([frontend/src](frontend/src)): React + Tailwind + lucide-react + wavesurfer.js, dark theme.
- **Native app** ([src-tauri](src-tauri)): a Tauri 2 shell renders the same React UI in a native
  window and runs the same Python backend as a bundled child process — one codebase, two ways to ship.

See [AGENTS.md](AGENTS.md) for a contributor/AI-agent oriented map of the codebase.

## Contributing

Contributions welcome! Read **[CONTRIBUTING.md](CONTRIBUTING.md)** for setup, conventions, the
verification checklist, and how to build the native app. The technical deep-dive lives in
[AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE) © 2026 Hossein Parahi.

## Notes

- Re-adding or rescanning a folder only processes new/changed files (content hash).
- Exact-duplicate files (same content, different location) are marked `duplicate` and skipped.
- The webapp index lives in `backend/data/`; the native app keeps its index + model cache in
  `~/Library/Application Support/com.audiosearch.desktop/`.
