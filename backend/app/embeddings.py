"""Local sentence embeddings (bge-small-en-v1.5) + segment->window merging."""
import functools
import logging

import numpy as np

from .config import (EMBED_MODEL, EMBED_QUERY_PREFIX, WINDOW_GAP_BREAK,
                     WINDOW_MAX_SECONDS)

log = logging.getLogger(__name__)


@functools.cache
def _model():
    from sentence_transformers import SentenceTransformer
    log.info("Loading embedding model %s", EMBED_MODEL)
    return SentenceTransformer(EMBED_MODEL)


def embed_passages(texts: list[str]) -> np.ndarray:
    return _model().encode(texts, normalize_embeddings=True, show_progress_bar=False)


def embed_query(text: str) -> np.ndarray:
    return _model().encode([EMBED_QUERY_PREFIX + text],
                           normalize_embeddings=True, show_progress_bar=False)[0]


def merge_windows(segments: list[dict]) -> list[dict]:
    """Merge whisper segments into ~30s windows, breaking on long silences."""
    windows: list[dict] = []
    cur: dict | None = None
    for seg in segments:
        if cur is None:
            cur = dict(seg)
            continue
        too_long = seg["end"] - cur["start"] > WINDOW_MAX_SECONDS
        gap = seg["start"] - cur["end"] > WINDOW_GAP_BREAK
        if too_long or gap:
            windows.append(cur)
            cur = dict(seg)
        else:
            cur["end"] = seg["end"]
            cur["text"] = f"{cur['text']} {seg['text']}"
    if cur is not None:
        windows.append(cur)
    return windows
