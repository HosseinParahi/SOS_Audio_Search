import asyncio
import json
import logging
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, peaks, search
from .media import playable_path, range_stream
from .pipeline import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    await pipeline.start()
    yield


app = FastAPI(title="Audio Search", lifespan=lifespan)


class FolderIn(BaseModel):
    path: str


# -- folders ----------------------------------------------------------------
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
    subprocess.run(["open", "-R", row["path"]], check=False)
    return {"ok": True}


# -- search -------------------------------------------------------------------
@app.get("/api/search")
async def search_endpoint(q: str = ""):
    q = q.strip()
    if not q:
        return {"query": q, "groups": []}

    def run():
        con = db.connect()
        try:
            return search.search(con, q)
        finally:
            con.close()

    groups = await asyncio.get_running_loop().run_in_executor(None, run)
    return {"query": q, "groups": groups}


# -- media ---------------------------------------------------------------------
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
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            pipeline.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
