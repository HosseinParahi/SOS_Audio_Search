"""Background ingest pipeline: scan -> transcribe -> embed -> group.

Threading model (why it's shaped this way):
  - A single GPU worker thread runs all Whisper + embedding work. The model can't be
    shared across threads safely and the GPU is the bottleneck anyway, so serializing
    keeps things simple and predictable.
  - Folder scans (mostly disk + ffprobe) run on the default thread pool — they shouldn't
    wait behind transcription.
  - Files to process flow through one asyncio.Queue of file ids.
  - Progress is broadcast to connected SSE clients via per-subscriber asyncio.Queues.
    Worker-thread code publishes via `publish_threadsafe` (hops back onto the loop).

The pipeline is resumable: status lives in the DB, processing clears prior derived data
first, so a crash/restart just re-queues whatever wasn't 'done'.
"""
import asyncio
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import db
from .embeddings import embed_passages, merge_windows
from .grouping import assign_group
from .scanner import find_media, guess_source_kind, parse_ixml, probe, quick_hash
from .transcribe import transcribe

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.subscribers: set[asyncio.Queue] = set()
        self.gpu = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gpu")
        self.loop: asyncio.AbstractEventLoop | None = None
        self._runner: asyncio.Task | None = None
        self.scanning = False

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self._requeue_unfinished()
        self._runner = asyncio.create_task(self._run())

    async def _requeue_unfinished(self) -> None:
        # On startup, anything caught mid-flight last run (transcribing/embedding) is
        # reset to 'pending' and re-queued. 'done'/'error'/'duplicate' are left alone.
        con = db.connect()
        try:
            con.execute(
                "UPDATE files SET status='pending' "
                "WHERE status NOT IN ('done','error','duplicate','pending')"
            )
            con.commit()
            ids = [r["id"] for r in con.execute(
                "SELECT id FROM files WHERE status='pending' ORDER BY id")]
        finally:
            con.close()
        for fid in ids:
            self.queue.put_nowait(fid)

    async def _run(self) -> None:
        # The forever loop: pull the next file id and process it on the GPU thread. One at
        # a time by design. A failure is logged but never kills the loop.
        assert self.loop
        while True:
            fid = await self.queue.get()
            try:
                await self.loop.run_in_executor(self.gpu, self._process, fid)
            except Exception:
                log.exception("pipeline failed on file %s", fid)

    # -- events ------------------------------------------------------------
    # Pub/sub for SSE: each connected client gets its own bounded queue. A slow/dead
    # client whose queue fills up is simply dropped rather than blocking the publisher.
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def publish(self, event: dict) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self.subscribers.discard(q)

    def publish_threadsafe(self, event: dict) -> None:
        # Called from the GPU worker thread; hops the event onto the loop thread to publish.
        if self.loop:
            self.loop.call_soon_threadsafe(self.publish, event)

    # -- scanning ----------------------------------------------------------
    # Walk a folder, register new/changed media files, and queue them for processing.
    async def scan_folder(self, folder_id: int, path: str) -> None:
        assert self.loop
        self.scanning = True
        self.publish({"type": "scan", "state": "started", "folder": path})
        try:
            new_ids = await self.loop.run_in_executor(None, self._scan, folder_id, path)
            for fid in new_ids:
                self.queue.put_nowait(fid)
            self.publish({"type": "scan", "state": "done", "folder": path,
                          "new_files": len(new_ids)})
        finally:
            self.scanning = False

    def _scan(self, folder_id: int, root: str) -> list[int]:
        con = db.connect()
        new_ids: list[int] = []
        try:
            for p in find_media(Path(root)):
                fid = self._ingest_path(con, folder_id, p)
                if fid is not None:
                    new_ids.append(fid)
        finally:
            con.close()
        return new_ids

    def _ingest_path(self, con: sqlite3.Connection, folder_id: int, p: Path) -> int | None:
        """Register one file. Returns its id if it needs processing, else None.

        Idempotent: a known unchanged path is skipped; a changed one (different content
        hash) is reset for reindex; a brand-new file is inserted (marked 'duplicate' if its
        content already exists elsewhere)."""
        existing = con.execute("SELECT id, hash, status FROM files WHERE path=?",
                               (str(p),)).fetchone()
        file_hash = quick_hash(p)
        if existing:
            if existing["hash"] == file_hash:
                # Same path, same content — only (re)queue if still pending.
                return existing["id"] if existing["status"] == "pending" else None
            db.delete_file_index(con, existing["id"])  # file content changed: reindex
            con.execute("UPDATE files SET hash=?, status='pending', error=NULL WHERE id=?",
                        (file_hash, existing["id"]))
            con.commit()
            return existing["id"]

        info = probe(p)
        if info is None:
            return None  # not real media (ffprobe couldn't read an audio stream)
        # Same content already indexed under another path -> mark as duplicate, don't redo.
        dup = con.execute(
            "SELECT id FROM files WHERE hash=? AND status!='duplicate'", (file_hash,)
        ).fetchone()
        status = "duplicate" if dup else "pending"
        scene, take = parse_ixml(p) if p.suffix.lower() in (".wav", ".bwf") else (None, None)
        cur = con.execute(
            """INSERT INTO files (folder_id, path, filename, hash, size, duration, format,
                                  codec, channels, sample_rate, has_video, source_kind,
                                  ixml_scene, ixml_take, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (folder_id, str(p), p.name, file_hash, p.stat().st_size, info["duration"],
             info["format"], info["codec"], info["channels"], info["sample_rate"],
             info["has_video"], guess_source_kind(p, bool(info["has_video"])),
             scene, take, status),
        )
        con.commit()
        fid = cur.lastrowid
        self.publish_threadsafe({"type": "file", "id": fid, "status": status,
                                 "filename": p.name})
        return fid if status == "pending" else None

    # -- per-file processing (runs on GPU thread) ---------------------------
    def _process(self, fid: int) -> None:
        """Transcribe -> store segments -> embed windows -> assign take group.

        Status transitions (each broadcast over SSE): pending -> transcribing ->
        embedding -> done, or -> error. Everything for this file commits together; on any
        exception we roll back the partial work and mark the file 'error' (retryable)."""
        con = db.connect()
        try:
            row = con.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
            if row is None or row["status"] in ("done", "duplicate"):
                return  # already handled (e.g. queued twice)
            if not Path(row["path"]).exists():
                self._set_status(con, fid, "error", error="file missing on disk")
                return

            try:
                # 1) Whisper transcription -> timestamped segments.
                self._set_status(con, fid, "transcribing")
                segments = transcribe(row["path"])

                # 2) Persist segments (also fills FTS via trigger). Clear any old data
                #    first so reprocessing is clean.
                self._set_status(con, fid, "embedding")
                db.delete_file_index(con, fid)
                transcript = " ".join(s["text"] for s in segments)
                con.executemany(
                    "INSERT INTO segments (file_id, start, end, text) VALUES (?,?,?,?)",
                    [(fid, s["start"], s["end"], s["text"]) for s in segments],
                )
                # 3) Merge into ~30s windows, embed them, store text + vector side by side.
                windows = merge_windows(segments)
                if windows:
                    vecs = embed_passages([w["text"] for w in windows])
                    for w, v in zip(windows, vecs):
                        cur = con.execute(
                            "INSERT INTO windows (file_id, start, end, text) VALUES (?,?,?,?)",
                            (fid, w["start"], w["end"], w["text"]),
                        )
                        con.execute(
                            "INSERT INTO vec_windows (window_id, embedding) VALUES (?,?)",
                            (cur.lastrowid, v.astype(np.float32).tobytes()),
                        )
                con.execute("UPDATE files SET transcript=? WHERE id=?", (transcript, fid))
                con.commit()

                # 4) Cluster with any matching take already in the DB (boom/lav/camera).
                assign_group(con, fid)
                self._set_status(con, fid, "done")
            except Exception as e:
                log.exception("processing failed for %s", row["path"])
                con.rollback()
                self._set_status(con, fid, "error", error=str(e)[:500])
        finally:
            con.close()

    def _set_status(self, con: sqlite3.Connection, fid: int, status: str,
                    error: str | None = None) -> None:
        con.execute("UPDATE files SET status=?, error=? WHERE id=?", (status, error, fid))
        con.commit()
        row = con.execute("SELECT filename FROM files WHERE id=?", (fid,)).fetchone()
        self.publish_threadsafe({"type": "file", "id": fid, "status": status,
                                 "error": error, "filename": row["filename"] if row else ""})


pipeline = Pipeline()
