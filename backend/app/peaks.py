"""Waveform peaks for the player: decoded once via ffmpeg, cached as JSON."""
import json
import subprocess
from pathlib import Path

import numpy as np

from .config import PEAKS_DIR

NUM_PEAKS = 1600
DECODE_RATE = 8000


def get_peaks(file_id: int, src: Path, duration: float) -> dict:
    cache = PEAKS_DIR / f"{file_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src),
         "-f", "s16le", "-ac", "1", "-ar", str(DECODE_RATE), "-"],
        capture_output=True, timeout=600,
    )
    if out.returncode != 0 or not out.stdout:
        raise RuntimeError(f"ffmpeg decode failed: {out.stderr.decode(errors='ignore')[:300]}")

    samples = np.frombuffer(out.stdout, dtype=np.int16)
    n = max(1, len(samples) // NUM_PEAKS)
    trimmed = samples[: n * NUM_PEAKS] if len(samples) >= NUM_PEAKS else samples
    buckets = np.abs(trimmed.astype(np.float32)).reshape(-1, n) if len(samples) >= NUM_PEAKS \
        else np.abs(trimmed.astype(np.float32)).reshape(-1, 1)
    peaks = buckets.max(axis=1)
    top = float(peaks.max()) or 1.0
    data = {"peaks": [round(float(p) / top, 3) for p in peaks], "duration": duration}
    cache.write_text(json.dumps(data))
    return data
