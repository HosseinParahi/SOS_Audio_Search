"""Hybrid search: FTS5 BM25 + sqlite-vec KNN -> reciprocal rank fusion -> take groups.

Two independent retrievers run over the same transcripts:
  - exact/keyword via FTS5 (catches precise lines the user remembers verbatim);
  - semantic via vector KNN over ~30s windows (catches paraphrases / "what it was about").
Their ranked lists are merged with Reciprocal Rank Fusion (RRF) — a score that depends
only on *rank position*, so the two incomparable scales (BM25 vs cosine distance) combine
cleanly. Files are then collapsed into take groups so duplicate takes show as one result.
"""
import re
import sqlite3

import numpy as np

from .embeddings import embed_query

RRF_K = 60          # RRF damping constant; larger = flatter contribution from top ranks
CANDIDATES = 60     # how many hits to pull from each retriever before fusing
MAX_MATCHES_PER_FILE = 3  # snippet rows shown per file in the result card


def _fts_query(q: str) -> str:
    """Quote tokens so user text can't break FTS5 syntax."""
    tokens = re.findall(r"\w+", q)
    return " ".join(f'"{t}"' for t in tokens)


def search(con: sqlite3.Connection, q: str, limit: int = 20) -> list[dict]:
    fts_hits = _fts_search(con, q)
    vec_hits = _vec_search(con, q)

    # Fuse both lists with RRF, accumulating per *file*. A hit at rank r contributes
    # 1/(RRF_K + r); a file appearing in both lists naturally scores higher. While doing
    # so, keep each file's best matching regions for the snippet display.
    scores: dict[int, float] = {}
    matches: dict[int, list[dict]] = {}
    for rank, hit in enumerate(fts_hits):
        scores[hit["file_id"]] = scores.get(hit["file_id"], 0) + 1 / (RRF_K + rank + 1)
        matches.setdefault(hit["file_id"], []).append(hit)
    for rank, hit in enumerate(vec_hits):
        scores[hit["file_id"]] = scores.get(hit["file_id"], 0) + 1 / (RRF_K + rank + 1)
        bucket = matches.setdefault(hit["file_id"], [])
        # skip a semantic hit that covers the same moment an exact hit already does
        if not any(_overlaps(hit, m) for m in bucket):
            bucket.append(hit)

    if not scores:
        return []

    ranked_files = sorted(scores, key=lambda f: scores[f], reverse=True)
    file_rows = _fetch_files(con, ranked_files)

    # Collapse files into take groups (boom/lav/camera of one take -> one card). The group
    # inherits the score of its best-ranked member, so group order follows file order.
    groups: dict[int, dict] = {}
    for fid in ranked_files:
        row = file_rows.get(fid)
        if row is None:
            continue
        gid = row["take_group_id"] or fid
        entry = groups.setdefault(gid, {"group_id": gid, "score": scores[fid], "files": []})
        entry["files"].append(_file_payload(row, matches.get(fid, [])))

    ordered = sorted(groups.values(), key=lambda g: g["score"], reverse=True)[:limit]
    # Fill in the take's other recordings that didn't match the query on their own.
    for group in ordered:
        _attach_siblings(con, group, file_rows)
    return ordered


def _fts_search(con: sqlite3.Connection, q: str) -> list[dict]:
    """Keyword search ranked by BM25. highlight() wraps matched terms in char(1)/char(2)
    sentinel bytes — the frontend turns those into <mark> safely, no HTML is sent."""
    match = _fts_query(q)
    if not match:
        return []
    rows = con.execute(
        """SELECT s.file_id, s.start, s.end,
                  highlight(segments_fts, 0, char(1), char(2)) AS snippet,
                  s.text
           FROM segments_fts
           JOIN segments s ON s.id = segments_fts.rowid
           WHERE segments_fts MATCH ?
           ORDER BY bm25(segments_fts)
           LIMIT ?""",
        (match, CANDIDATES),
    ).fetchall()
    return [dict(r) | {"kind": "exact"} for r in rows]


def _vec_search(con: sqlite3.Connection, q: str) -> list[dict]:
    """Semantic search: embed the query, then KNN over the per-window embeddings."""
    vec = embed_query(q).astype(np.float32)
    rows = con.execute(
        """SELECT window_id, distance FROM vec_windows
           WHERE embedding MATCH ? AND k = ?""",
        (vec.tobytes(), CANDIDATES),
    ).fetchall()
    hits = []
    for r in rows:
        w = con.execute(
            "SELECT file_id, start, end, text FROM windows WHERE id=?", (r["window_id"],)
        ).fetchone()
        if w:
            hits.append(dict(w) | {"snippet": w["text"], "kind": "semantic",
                                   "distance": r["distance"]})
    return hits


def _overlaps(a: dict, b: dict) -> bool:
    """True if two [start,end] time spans intersect (used to dedupe match snippets)."""
    return a["start"] < b["end"] and b["start"] < a["end"]


def _fetch_files(con: sqlite3.Connection, ids: list[int]) -> dict[int, sqlite3.Row]:
    """Batch-load file rows by id into a dict (one query instead of N)."""
    qmarks = ",".join("?" * len(ids))
    rows = con.execute(f"SELECT * FROM files WHERE id IN ({qmarks})", ids).fetchall()
    return {r["id"]: r for r in rows}


def _file_payload(row: sqlite3.Row, hits: list[dict]) -> dict:
    hits = sorted(hits, key=lambda h: 0 if h["kind"] == "exact" else 1)[:MAX_MATCHES_PER_FILE]
    return {
        "id": row["id"],
        "filename": row["filename"],
        "path": row["path"],
        "duration": row["duration"],
        "source_kind": row["source_kind"],
        "format": row["format"],
        "has_video": bool(row["has_video"]),
        "ixml_scene": row["ixml_scene"],
        "ixml_take": row["ixml_take"],
        "matches": [
            {"start": h["start"], "end": h["end"], "snippet": h["snippet"], "kind": h["kind"]}
            for h in hits
        ],
    }


def _attach_siblings(con: sqlite3.Connection, group: dict,
                     already: dict[int, sqlite3.Row]) -> None:
    """Other recordings of the same take that didn't match the query themselves."""
    have = {f["id"] for f in group["files"]}
    rows = con.execute(
        "SELECT * FROM files WHERE take_group_id=? AND status='done'", (group["group_id"],)
    ).fetchall()
    for row in rows:
        if row["id"] not in have:
            group["files"].append(_file_payload(row, []))
