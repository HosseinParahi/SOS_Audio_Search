"""Original-file range streaming + on-demand m4a proxy for non-web-safe sources."""
import subprocess
import threading
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from .config import PROXY_DIR

CHUNK = 256 * 1024
WEB_SAFE_CODECS = {"mp3", "aac", "flac", "vorbis", "opus"}
_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()

MIME = {".wav": "audio/wav", ".bwf": "audio/wav", ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac",
        ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
        ".aif": "audio/aiff", ".aiff": "audio/aiff"}


def is_web_safe(row) -> bool:
    if row["has_video"]:
        return False  # stream extracted audio proxy, not the whole video
    if (row["codec"] or "").startswith("pcm_s16") or (row["codec"] or "").startswith("pcm_s24"):
        return (row["channels"] or 0) <= 2 and Path(row["path"]).suffix.lower() in (".wav", ".bwf")
    return (row["codec"] or "") in WEB_SAFE_CODECS and (row["channels"] or 0) <= 2


def playable_path(row) -> tuple[Path, str]:
    """Return (path, mime) — original when browser-safe, cached m4a proxy otherwise."""
    src = Path(row["path"])
    if is_web_safe(row):
        return src, MIME.get(src.suffix.lower(), "application/octet-stream")

    proxy = PROXY_DIR / f"{row['id']}.m4a"
    if not proxy.exists():
        with _locks_guard:
            lock = _locks.setdefault(row["id"], threading.Lock())
        with lock:
            if not proxy.exists():
                _transcode(src, proxy)
    return proxy, "audio/mp4"


def _transcode(src: Path, dst: Path) -> None:
    tmp = dst.with_suffix(".tmp.m4a")
    out = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn",
         "-ac", "2", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(tmp)],
        capture_output=True, timeout=1800,
    )
    if out.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(500, f"transcode failed: {out.stderr.decode(errors='ignore')[:300]}")
    tmp.rename(dst)


def range_stream(request: Request, path: Path, mime: str) -> StreamingResponse:
    if not path.exists():
        raise HTTPException(404, "media file missing on disk")
    size = path.stat().st_size
    start, end = 0, size - 1
    range_header = request.headers.get("range")
    status = 200
    if range_header:
        try:
            unit, _, rng = range_header.partition("=")
            lo, _, hi = rng.partition("-")
            if unit.strip() != "bytes":
                raise ValueError
            start = int(lo) if lo else max(0, size - int(hi))
            end = min(int(hi), size - 1) if lo and hi else end
            if start > end or start >= size:
                raise ValueError
            status = 206
        except ValueError:
            raise HTTPException(416, "invalid range")

    def reader():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "no-cache",
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(reader(), status_code=status, media_type=mime, headers=headers)
