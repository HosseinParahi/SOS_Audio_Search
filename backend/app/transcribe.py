"""mlx-whisper transcription. Model loads once, lazily, inside the worker thread."""
import logging

from .config import WHISPER_MODEL

log = logging.getLogger(__name__)
_warmed = False


def transcribe(path: str) -> list[dict]:
    """Return [{start, end, text}] segments. mlx-whisper runs ffmpeg itself,
    so any container (wav/mp3/mov/...) works directly, downmixed to mono 16k."""
    global _warmed
    import mlx_whisper

    if not _warmed:
        log.info("Loading Whisper model %s (first run downloads ~1.6GB)", WHISPER_MODEL)
        _warmed = True

    result = mlx_whisper.transcribe(
        path,
        path_or_hf_repo=WHISPER_MODEL,
        language="en",
        condition_on_previous_text=False,
        verbose=None,
    )
    segments = []
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        segments.append({
            "start": round(float(seg["start"]), 3),
            "end": round(float(seg["end"]), 3),
            "text": text,
        })
    return segments
