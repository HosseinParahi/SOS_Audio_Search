import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Writable derived-data root. Defaults to backend/data for the webapp; the native
# macOS app (read-only .app bundle) overrides this to Application Support via the
# AUDIO_SEARCH_DATA env var so the DB + caches land somewhere writable.
DATA_DIR = Path(os.environ.get("AUDIO_SEARCH_DATA") or (BACKEND_DIR / "data"))
CACHE_DIR = DATA_DIR / "cache"
PROXY_DIR = CACHE_DIR / "proxy"
PEAKS_DIR = CACHE_DIR / "peaks"
DB_PATH = DATA_DIR / "library.db"

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
# bge v1.5 models expect this prefix on queries (not passages)
EMBED_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# segment windows for embedding
WINDOW_MAX_SECONDS = 30.0
WINDOW_GAP_BREAK = 2.0

# take grouping
GROUP_MAX_COSINE_DIST = 0.18
GROUP_DURATION_TOLERANCE = 0.35  # fraction of longer duration

AUDIO_EXTS = {".wav", ".bwf", ".mp3", ".m4a", ".aac", ".aif", ".aiff",
              ".flac", ".ogg", ".oga", ".opus", ".caf", ".wma"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".mxf", ".avi", ".mkv", ".mts", ".m2ts"}

for d in (DATA_DIR, PROXY_DIR, PEAKS_DIR):
    d.mkdir(parents=True, exist_ok=True)
