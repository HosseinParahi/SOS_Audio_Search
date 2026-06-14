#!/bin/zsh
# Build the frontend if needed, then serve app + API on http://localhost:8000
set -e
cd "$(dirname "$0")"

if [ ! -d frontend/dist ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist 2>/dev/null | head -1)" ]; then
  echo "Building frontend..."
  (cd frontend && npm install --silent && npm run build)
fi

cd backend
exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
