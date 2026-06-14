# Contributing to Audio Search

Thanks for your interest in improving Audio Search! This guide covers how to set up, build,
verify, and submit changes. For the full architecture map and module-by-module breakdown, see
**[AGENTS.md](AGENTS.md)** — it's the technical source of truth for how this repo is built and
run. This file is the human-facing front door; it points at AGENTS.md rather than duplicating it.

## Project scope & hard constraints

Audio Search indexes piles of unorganized production audio in place, transcribes it locally, and
gives you hybrid (semantic + exact) search over the transcripts. Before you start, know the
non-negotiables — changes that break these won't be merged without first replacing the underlying
backend:

- **macOS on Apple Silicon only.** Transcription uses [`mlx-whisper`](https://github.com/ml-explore/mlx-examples),
  which needs an Apple-Silicon GPU. No Intel/Windows/Linux without swapping the transcription backend.
- **Python is pinned to 3.12** via `uv` (newer Pythons break the ML wheels). Always run the backend
  through `uv run …`, never bare `python`.
- **`ffmpeg` must be on PATH** (probing, extraction, transcode proxies, waveform peaks).
- **Index in place.** Never move, copy, rename, or write to the user's audio files — the app only
  reads them. Derived data lives under `backend/data/` (or Application Support for the native app).

## Setup

```bash
brew install ffmpeg uv node      # system tools
cd backend && uv sync            # backend env (uv creates .venv, Python 3.12)
cd ../frontend && npm install    # frontend deps
```

## Run (development)

```bash
# Webapp — two terminals:
cd backend  && uv run uvicorn app.main:app --reload   # API + UI on :8000
cd frontend && npm run dev                             # UI hot reload on :5173 (proxies /api → 8000)

# Native macOS app (Tauri) — needs Rust (https://rustup.rs) + dylibbundler:
cd src-tauri && cargo run        # dev: uses the `uv run` backend, no bundling
```

The first index run downloads the AI models once (~1.6 GB Whisper + ~130 MB embedder); needs
internet that one time only.

## Coding conventions

Match the style of the surrounding code (naming, comment density, idioms). The key project rules
(full list in [AGENTS.md](AGENTS.md#conventions)):

- **`ffmpeg`/`ffprobe` via list-args only** (`subprocess.run([...])`) — never shell strings; user
  paths contain spaces and unicode.
- **No raw HTML into React.** FTS highlights come back wrapped in marker chars and render through
  the `Highlight` component — don't switch to `dangerouslySetInnerHTML`.
- **One SQLite connection per request/worker**, closed in `finally`. WAL mode is on.
- **The pipeline is resumable & idempotent** — don't add steps that can't be safely re-run.
- Keep the webapp and native app working from one codebase: frontend API calls go through
  `apiUrl()` ([frontend/src/api.ts](frontend/src/api.ts)), which is a no-op in the webapp.

## Verify before you open a PR

Run the same checks the maintainers do:

```bash
cd frontend && npx tsc -b && npm run build          # frontend type-check + build
cd backend  && uv run python -c "import app.main"    # backend imports cleanly
./start.sh && curl -s localhost:8000/api/stats       # smoke-test a running server
```

For native-app changes, additionally build it (see [AGENTS.md](AGENTS.md#macos-desktop-app-tauri)):

```bash
src-tauri/scripts/build-pyenv.sh && src-tauri/scripts/bundle-ffmpeg.sh
./frontend/node_modules/.bin/tauri build --bundles app dmg
```

## Commits & pull requests

- **Conventional Commits** for messages: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:` … with a
  concise imperative subject. Explain the *why* in the body when it isn't obvious.
- **Keep PRs small and focused** — one logical change per PR. Describe what changed and why, and
  link any related issue (`Closes #123`).
- **Run the verification commands above** and mention the results in the PR.
- Don't commit generated artifacts: `node_modules/`, `backend/.venv/`, `frontend/dist/`,
  `src-tauri/target/`, the bundled `src-tauri/resources/` contents, `*.log`, `.DS_Store`.

## Reporting bugs & requesting features

Open a GitHub issue. For bugs, include your macOS version + chip (e.g. M2 Pro), how you ran it
(webapp or `.app`), steps to reproduce, and any backend log output. For features, describe the
post-production workflow you're trying to support.

## Be respectful

Be kind and constructive in issues, PRs, and reviews. Assume good intent; critique code, not people.
