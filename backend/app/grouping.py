"""Take grouping: same take captured by boom/lav/camera => one group.

Signals, strongest first:
1. BWF iXML scene+take match.
2. Whole-transcript embedding similarity + duration proximity.

A file's group id is the id of the earliest-grouped member (or its own id).
"""
import sqlite3

import numpy as np

from .config import GROUP_DURATION_TOLERANCE, GROUP_MAX_COSINE_DIST
from .embeddings import embed_passages


def assign_group(con: sqlite3.Connection, file_id: int) -> int:
    row = con.execute(
        "SELECT id, duration, transcript, ixml_scene, ixml_take FROM files WHERE id=?",
        (file_id,),
    ).fetchone()

    transcript = (row["transcript"] or "").strip()
    vec = embed_passages([transcript[:2000]])[0].astype(np.float32) if transcript else None

    group_id = (_match_by_ixml(con, row)
                or _match_by_transcript(con, row, vec)
                or file_id)
    con.execute("UPDATE files SET take_group_id=? WHERE id=?", (group_id, file_id))

    if vec is not None:
        con.execute("DELETE FROM vec_files WHERE file_id=?", (file_id,))
        con.execute(
            "INSERT INTO vec_files(file_id, embedding) VALUES (?, ?)",
            (file_id, vec.tobytes()),
        )
    con.commit()
    return group_id


def _match_by_ixml(con: sqlite3.Connection, row: sqlite3.Row) -> int | None:
    if not (row["ixml_scene"] and row["ixml_take"]):
        return None
    hit = con.execute(
        """SELECT take_group_id FROM files
           WHERE ixml_scene=? AND ixml_take=? AND id!=? AND take_group_id IS NOT NULL
           LIMIT 1""",
        (row["ixml_scene"], row["ixml_take"], row["id"]),
    ).fetchone()
    return hit["take_group_id"] if hit else None


def _match_by_transcript(con: sqlite3.Connection, row: sqlite3.Row,
                         vec: np.ndarray | None) -> int | None:
    if vec is None or len((row["transcript"] or "").strip()) < 40 or not row["duration"]:
        return None  # too little speech to trust similarity
    hits = con.execute(
        "SELECT file_id, distance FROM vec_files WHERE embedding MATCH ? AND k = 8",
        (vec.tobytes(),),
    ).fetchall()
    for hit in hits:
        if hit["file_id"] == row["id"] or hit["distance"] > GROUP_MAX_COSINE_DIST:
            continue
        other = con.execute(
            "SELECT duration, take_group_id FROM files WHERE id=?", (hit["file_id"],)
        ).fetchone()
        if not other or not other["take_group_id"] or not other["duration"]:
            continue
        longer = max(row["duration"], other["duration"])
        if abs(row["duration"] - other["duration"]) / longer <= GROUP_DURATION_TOLERANCE:
            return other["take_group_id"]
    return None
