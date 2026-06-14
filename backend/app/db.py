import sqlite3

import sqlite_vec

from .config import DB_PATH, EMBED_DIM

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    added_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    hash TEXT,
    size INTEGER,
    duration REAL,
    format TEXT,
    codec TEXT,
    channels INTEGER,
    sample_rate INTEGER,
    has_video INTEGER DEFAULT 0,
    source_kind TEXT DEFAULT 'unknown',
    ixml_scene TEXT,
    ixml_take TEXT,
    take_group_id INTEGER,
    status TEXT DEFAULT 'pending',
    error TEXT,
    transcript TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_group ON files(take_group_id);
CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    start REAL NOT NULL,
    end REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_file ON segments(file_id);

CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text, content='segments', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

CREATE TABLE IF NOT EXISTS windows (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    start REAL NOT NULL,
    end REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_windows_file ON windows(file_id);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_windows USING vec0(
    window_id INTEGER PRIMARY KEY,
    embedding float[{EMBED_DIM}] distance_metric=cosine
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_files USING vec0(
    file_id INTEGER PRIMARY KEY,
    embedding float[{EMBED_DIM}] distance_metric=cosine
);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    return con


def init_db() -> None:
    con = connect()
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()


def delete_file_index(con: sqlite3.Connection, file_id: int) -> None:
    """Remove derived data for a file (segments/windows/vectors), keep the file row."""
    con.execute(
        "DELETE FROM vec_windows WHERE window_id IN (SELECT id FROM windows WHERE file_id=?)",
        (file_id,),
    )
    con.execute("DELETE FROM vec_files WHERE file_id=?", (file_id,))
    con.execute("DELETE FROM windows WHERE file_id=?", (file_id,))
    con.execute("DELETE FROM segments WHERE file_id=?", (file_id,))
