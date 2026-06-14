#!/usr/bin/env bash
# Build src-tauri/resources/pyenv: a relocatable, standalone CPython 3.12 with every backend
# runtime dependency installed, plus src-tauri/resources/backend/app (the backend source).
# This is exactly what the bundled .app runs — the end user needs no uv, Python, or pip.
#
# Run from anywhere:  src-tauri/scripts/build-pyenv.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BACKEND="$REPO/backend"
RES="$REPO/src-tauri/resources"
PYENV="$RES/pyenv"
BACKEND_DEST="$RES/backend"

echo "==> ensuring a managed standalone CPython 3.12 exists"
uv python install 3.12

PYBIN="$(uv python find 3.12)"
# pwd -P resolves the un-versioned alias symlink (cpython-3.12-…) to the real versioned dir,
# so the copy below duplicates real files instead of re-creating a symlink.
SRC_ROOT="$(cd "$(dirname "$PYBIN")/.." && pwd -P)"   # .../cpython-3.12.x-macos-aarch64-none
echo "    source interpreter: $SRC_ROOT"

echo "==> copying the standalone interpreter into the bundle ($PYENV)"
rm -rf "$PYENV"
mkdir -p "$RES"
cp -R "$SRC_ROOT" "$PYENV"

PY="$PYENV/bin/python3.12"
echo "    bundled interpreter: $("$PY" --version)"

# uv stamps its managed builds as externally-managed; strip the marker on our private copy so
# we can install straight into its site-packages (the copy is no longer uv-managed).
find "$PYENV" -name 'EXTERNALLY-MANAGED' -delete 2>/dev/null || true

echo "==> exporting locked runtime requirements from backend/uv.lock"
REQS="$(mktemp)"
( cd "$BACKEND" && uv export --no-hashes --no-emit-project --no-dev -o "$REQS" )

echo "==> installing deps into the bundled interpreter (downloads torch/mlx — several GB)"
# Install straight into the standalone interpreter's site-packages (not a venv), so the whole
# tree is self-contained and relocatable.
uv pip install --python "$PY" --break-system-packages -r "$REQS"

echo "==> copying backend source (app package only)"
rm -rf "$BACKEND_DEST"
mkdir -p "$BACKEND_DEST"
cp -R "$BACKEND/app" "$BACKEND_DEST/app"

echo "==> slimming __pycache__ / *.pyc"
find "$PYENV" "$BACKEND_DEST" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$PYENV" -name '*.pyc' -delete 2>/dev/null || true

echo "==> smoke-testing the relocated interpreter can import the ML stack"
"$PY" - <<'PYEOF'
import importlib
for m in ("fastapi", "uvicorn", "numpy", "mlx_whisper", "sentence_transformers", "sqlite_vec"):
    importlib.import_module(m)
    print("  ok:", m)
print("all imports succeeded")
PYEOF

echo "==> done. sizes:"
du -sh "$PYENV" "$BACKEND_DEST"
