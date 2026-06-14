"""FastAPI application: all HTTP routes + the static frontend mount.

This is the only network-facing module. It stays thin: each route opens a short-lived
SQLite connection (closed in `finally`), and anything CPU/GPU-heavy (search, transcode,
peaks) is pushed to a thread pool so the async event loop never blocks. The background
ingest pipeline lives in `pipeline.py`; routes here just enqueue work and read results.
"""
import asyncio
import json
import logging
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, peaks, search
from .media import playable_path, range_stream
from .pipeline import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

# The built frontend (only exists after `npm run build`); mounted at the end if present.
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once at startup: ensure schema exists, then boot the ingest worker + requeue
    # anything left mid-process from a previous run.
    db.init_db()
    await pipeline.start()
    yield


app = FastAPI(title="Audio Search", lifespan=lifespan)

# The native macOS shell renders the UI from a different origin (tauri://localhost, or the
# Vite dev server) than the backend's 127.0.0.1:<port>, so the browser enforces CORS on the
# UI's fetch/EventSource/peaks calls. The server only ever binds to loopback, so allowing any
# origin here is safe and keeps the same-origin webapp working unchanged.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class FolderIn(BaseModel):
    path: str


# -- folders ----------------------------------------------------------------
# Add/list/remove the root folders the user wants indexed. Adding a folder (or rescanning)
# kicks off a background scan; the response returns immediately while work continues.
@app.post("/api/folders")
async def add_folder(body: FolderIn):
    p = Path(body.path).expanduser()
    if not p.is_dir():
        raise HTTPException(400, f"Not a directory: {p}")
    con = db.connect()
    try:
        existing = con.execute("SELECT id FROM folders WHERE path=?", (str(p),)).fetchone()
        if existing:
            fid = existing["id"]
        else:
            fid = con.execute("INSERT INTO folders (path) VALUES (?)", (str(p),)).lastrowid
            con.commit()
    finally:
        con.close()
    asyncio.create_task(pipeline.scan_folder(fid, str(p)))
    return {"id": fid, "path": str(p)}


@app.get("/api/folders")
async def list_folders():
    con = db.connect()
    try:
        rows = con.execute(
            """SELECT fo.id, fo.path, fo.added_at, COUNT(f.id) AS file_count
               FROM folders fo LEFT JOIN files f ON f.folder_id = fo.id
               GROUP BY fo.id ORDER BY fo.id"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


@app.delete("/api/folders/{folder_id}")
async def remove_folder(folder_id: int):
    # Drops the folder and its index rows only — the user's files on disk are untouched.
    con = db.connect()
    try:
        for f in con.execute("SELECT id FROM files WHERE folder_id=?", (folder_id,)):
            db.delete_file_index(con, f["id"])
        con.execute("DELETE FROM files WHERE folder_id=?", (folder_id,))
        con.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        con.commit()
    finally:
        con.close()
    return {"ok": True}


@app.post("/api/rescan")
async def rescan():
    con = db.connect()
    try:
        folders = con.execute("SELECT id, path FROM folders").fetchall()
    finally:
        con.close()
    for f in folders:
        asyncio.create_task(pipeline.scan_folder(f["id"], f["path"]))
    return {"folders": len(folders)}


# -- files -------------------------------------------------------------------
# Library listing, aggregate stats (drives the dashboard + progress dot), per-file
# transcript detail, retry of a failed file, and "reveal in Finder".
@app.get("/api/files")
async def list_files():
    con = db.connect()
    try:
        rows = con.execute(
            """SELECT id, filename, path, duration, format, codec, channels, has_video,
                      source_kind, ixml_scene, ixml_take, take_group_id, status, error, size
               FROM files ORDER BY filename"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


@app.get("/api/stats")
async def stats():
    con = db.connect()
    try:
        by_status = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) n FROM files GROUP BY status")}
        totals = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(duration),0) dur FROM files").fetchone()
        return {"by_status": by_status, "total_files": totals["n"],
                "total_duration": totals["dur"], "queue": pipeline.queue.qsize(),
                "scanning": pipeline.scanning}
    finally:
        con.close()


@app.get("/api/files/{file_id}")
async def file_detail(file_id: int):
    con = db.connect()
    try:
        row = con.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        segments = con.execute(
            "SELECT start, end, text FROM segments WHERE file_id=? ORDER BY start",
            (file_id,)).fetchall()
        return dict(row) | {"segments": [dict(s) for s in segments]}
    finally:
        con.close()


@app.post("/api/files/{file_id}/retry")
async def retry_file(file_id: int):
    con = db.connect()
    try:
        if not con.execute("SELECT 1 FROM files WHERE id=?", (file_id,)).fetchone():
            raise HTTPException(404)
        con.execute("UPDATE files SET status='pending', error=NULL WHERE id=?", (file_id,))
        con.commit()
    finally:
        con.close()
    pipeline.queue.put_nowait(file_id)
    return {"ok": True}


@app.post("/api/files/{file_id}/reveal")
async def reveal_file(file_id: int):
    con = db.connect()
    try:
        row = con.execute("SELECT path FROM files WHERE id=?", (file_id,)).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(404)
    # macOS `open -R` selects the file in Finder so the user can drag it into their NLE.
    subprocess.run(["open", "-R", row["path"]], check=False)
    return {"ok": True}


# -- search -------------------------------------------------------------------
@app.get("/api/search")
async def search_endpoint(q: str = ""):
    q = q.strip()
    if not q:
        return {"query": q, "groups": []}

    # search.search() runs FTS + a vector KNN + embedding the query — all blocking,
    # so run it off the event loop in a worker thread.
    def run():
        con = db.connect()
        try:
            return search.search(con, q)
        finally:
            con.close()

    groups = await asyncio.get_running_loop().run_in_executor(None, run)
    return {"query": q, "groups": groups}


# -- media ---------------------------------------------------------------------
# Audio streaming (with HTTP range support) + waveform peaks. playable_path() may run a
# blocking ffmpeg transcode, and peaks decode the whole file, so both go to a thread pool.
def _file_row(file_id: int):
    con = db.connect()
    try:
        row = con.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(404)
    return row


@app.get("/api/media/{file_id}")
async def stream_media(file_id: int, request: Request):
    row = _file_row(file_id)
    path, mime = await asyncio.get_running_loop().run_in_executor(
        None, playable_path, row)
    return range_stream(request, path, mime)


@app.get("/api/media/{file_id}/peaks")
async def media_peaks(file_id: int):
    row = _file_row(file_id)
    return await asyncio.get_running_loop().run_in_executor(
        None, peaks.get_peaks, file_id, Path(row["path"]), row["duration"])


# -- events (SSE) ----------------------------------------------------------------
# Server-Sent Events stream: the frontend subscribes once and receives live pipeline
# updates (file status changes, scan start/done) so the Library UI updates without polling.
@app.get("/api/events")
async def events(request: Request):
    q = pipeline.subscribe()

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'hello'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Block up to 15s for an event; on timeout send a comment line to keep
                    # the connection (and any proxies) alive.
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            pipeline.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# Serve the built SPA at the root (must be mounted last so it doesn't shadow /api routes).
# Absent in dev — there Vite serves the UI on :5173 and proxies /api here.
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
