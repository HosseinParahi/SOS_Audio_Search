"""Folder walking, ffprobe validation, BWF iXML parsing, source-kind heuristics."""
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

from .config import AUDIO_EXTS, VIDEO_EXTS

# NB: \b doesn't fire between letters and underscores (both \w), and production
# filenames are underscore-heavy (LAV_TX1_...), so use explicit separators instead.
_SEP = r"(?:^|[^a-z0-9])"
_END = r"(?:[^a-z0-9]|$)"
SOURCE_PATTERNS = [
    ("boom", re.compile(rf"boom|mkh|{_SEP}416{_END}|shotgun", re.I)),
    ("lav", re.compile(rf"{_SEP}lav|lavalier|lapel|{_SEP}tx\d|wireless|bodymic|cos11|{_SEP}dpa{_END}", re.I)),
    ("camera", re.compile(rf"{_SEP}cam{_END}|camera|scratch|{_SEP}(?:a7|fx3|fx6){_END}|komodo|alexa|{_SEP}c\d{{4}}{_END}", re.I)),
    ("recorder", re.compile(rf"recorder|{_SEP}zoom|mixpre|{_SEP}f[86]{_END}|sound.?devices|tascam|h4n|{_SEP}h6{_END}", re.I)),
]


def probe(path: Path) -> dict | None:
    """ffprobe a file; return parsed info or None if not usable media."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        info = json.loads(out.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None

    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        return None
    video = next(
        (s for s in info.get("streams", [])
         if s.get("codec_type") == "video"
         and s.get("disposition", {}).get("attached_pic", 0) == 0
         and s.get("codec_name") not in ("mjpeg", "png", "bmp")),
        None,
    )
    fmt = info.get("format", {})
    duration = float(fmt.get("duration") or audio.get("duration") or 0)
    return {
        "duration": duration,
        "format": (fmt.get("format_name") or "").split(",")[0],
        "codec": audio.get("codec_name"),
        "channels": int(audio.get("channels") or 0),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "has_video": 1 if video else 0,
    }


def quick_hash(path: Path) -> str:
    """blake2b of size + first/last 1MB — fast identity for dedupe."""
    h = hashlib.blake2b(digest_size=16)
    size = path.stat().st_size
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1024 * 1024))
        if size > 2 * 1024 * 1024:
            f.seek(-1024 * 1024, 2)
            h.update(f.read(1024 * 1024))
    return h.hexdigest()


def guess_source_kind(path: Path, has_video: bool) -> str:
    text = str(path)
    for kind, pat in SOURCE_PATTERNS:
        if pat.search(text):
            return kind
    if has_video:
        return "camera"
    return "unknown"


def parse_ixml(path: Path) -> tuple[str | None, str | None]:
    """Best-effort scene/take from a BWF/WAV iXML chunk."""
    try:
        with open(path, "rb") as f:
            riff = f.read(12)
            if len(riff) < 12 or riff[:4] not in (b"RIFF", b"RF64") or riff[8:12] != b"WAVE":
                return None, None
            while True:
                header = f.read(8)
                if len(header) < 8:
                    return None, None
                cid, csize = header[:4], struct.unpack("<I", header[4:])[0]
                if cid == b"iXML":
                    xml = f.read(min(csize, 1024 * 1024)).decode("utf-8", "ignore")
                    scene = re.search(r"<SCENE>([^<]*)</SCENE>", xml)
                    take = re.search(r"<TAKE>([^<]*)</TAKE>", xml)
                    return (scene.group(1).strip() if scene else None,
                            take.group(1).strip() if take else None)
                if cid == b"data" and csize == 0xFFFFFFFF:  # RF64 streamed size
                    return None, None
                f.seek(csize + (csize & 1), 1)
    except OSError:
        return None, None


def find_media(root: Path) -> list[Path]:
    exts = AUDIO_EXTS | VIDEO_EXTS
    found = []
    for p in sorted(root.rglob("*")):
        if p.name.startswith(".") or any(part.startswith(".") for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in exts:
            found.append(p)
    return found
