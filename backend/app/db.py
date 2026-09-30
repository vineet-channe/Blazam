"""SQLite persistence. The DDL sticks to portable types (INTEGER/BIGINT, TEXT, REAL) so it runs
unchanged on PostgreSQL apart from the auto-increment clause (see ``POSTGRES_NOTE``)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

POSTGRES_NOTE = "On Postgres replace 'INTEGER PRIMARY KEY AUTOINCREMENT' with 'BIGSERIAL PRIMARY KEY'."

SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    artist        TEXT NOT NULL,
    album         TEXT,
    year          INTEGER,
    cover_url     TEXT,
    deezer_id     BIGINT UNIQUE,
    isrc          TEXT,
    mbid          TEXT,
    preview_url   TEXT,
    duration_s    REAL,
    source        TEXT NOT NULL,          -- seed | upload | learned
    file_sha1     TEXT UNIQUE,
    fp_version    TEXT NOT NULL,
    n_hashes      INTEGER NOT NULL DEFAULT 0,
    lyrics        TEXT,
    audio_path    TEXT,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_songs_title ON songs(title);
CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist);

CREATE TABLE IF NOT EXISTS hashes (
    hash     BIGINT NOT NULL,             -- uint32 packed f1|f2|dt
    song_id  INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    t        INTEGER NOT NULL             -- anchor time in frames
);
CREATE INDEX IF NOT EXISTS idx_hashes_hash ON hashes(hash);
CREATE INDEX IF NOT EXISTS idx_hashes_song ON hashes(song_id);

CREATE TABLE IF NOT EXISTS history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      REAL NOT NULL,
    status          TEXT NOT NULL,        -- match | no_match
    source          TEXT,                 -- own | external | NULL
    song_id         INTEGER REFERENCES songs(id) ON DELETE SET NULL,
    confidence      REAL,
    score           INTEGER,
    offset_seconds  REAL,
    latency_ms      REAL,
    learned         INTEGER NOT NULL DEFAULT 0,
    song_json       TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at);

CREATE TABLE IF NOT EXISTS api_cache (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL
);
"""

SONG_FIELDS = (
    "id", "title", "artist", "album", "year", "cover_url", "deezer_id", "isrc", "mbid",
    "preview_url", "duration_s", "source", "n_hashes", "lyrics", "created_at",
)


class Database:
    """Thin thread-safe wrapper around one SQLite connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys=ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _q(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    # ------------------------------------------------------------------ songs
    def find_song(self, *, deezer_id: int | None = None, sha1: str | None = None) -> dict | None:
        if deezer_id is not None:
            rows = self._q("SELECT * FROM songs WHERE deezer_id = ?", (deezer_id,))
            if rows:
                return dict(rows[0])
        if sha1 is not None:
            rows = self._q("SELECT * FROM songs WHERE file_sha1 = ?", (sha1,))
            if rows:
                return dict(rows[0])
        return None

    def get_song(self, song_id: int) -> dict | None:
        rows = self._q("SELECT * FROM songs WHERE id = ?", (song_id,))
        return dict(rows[0]) if rows else None

    def insert_song_with_hashes(
        self,
        meta: dict[str, Any],
        hashes: np.ndarray,
        offsets: np.ndarray,
        fp_version: str,
        batch: int = 20_000,
    ) -> int:
        """Insert a song row and its (hash, t) pairs atomically. Returns the new song id.

        Duplicate (hash, t) pairs are removed first so the table holds a set per song.
        """
        key = np.unique((hashes.astype(np.uint64) << np.uint64(32)) | offsets.astype(np.uint32).astype(np.uint64))
        h = (key >> np.uint64(32)).astype(np.int64)
        t = (key & np.uint64(0xFFFFFFFF)).astype(np.int64)
        cols = ("title", "artist", "album", "year", "cover_url", "deezer_id", "isrc", "mbid",
                "preview_url", "duration_s", "source", "file_sha1", "lyrics", "audio_path")
        vals = [meta.get(c) for c in cols]
        with self.tx() as c:
            cur = c.execute(
                f"INSERT INTO songs ({', '.join(cols)}, fp_version, n_hashes, created_at) "
                f"VALUES ({', '.join('?' * len(cols))}, ?, ?, ?)",
                (*vals, fp_version, int(h.size), time.time()),
            )
            song_id = int(cur.lastrowid)
            for s in range(0, h.size, batch):
                c.executemany(
                    "INSERT INTO hashes (hash, song_id, t) VALUES (?, ?, ?)",
                    zip(h[s : s + batch].tolist(), [song_id] * min(batch, h.size - s), t[s : s + batch].tolist()),
                )
        return song_id

    def replace_hashes(self, song_id: int, hashes: np.ndarray, offsets: np.ndarray, fp_version: str) -> int:
        """Re-fingerprint support: swap a song's hashes for a new set (e.g. after tuning)."""
        key = np.unique((hashes.astype(np.uint64) << np.uint64(32)) | offsets.astype(np.uint32).astype(np.uint64))
        h = (key >> np.uint64(32)).astype(np.int64).tolist()
        t = (key & np.uint64(0xFFFFFFFF)).astype(np.int64).tolist()
        with self.tx() as c:
            c.execute("DELETE FROM hashes WHERE song_id = ?", (song_id,))
            c.executemany("INSERT INTO hashes (hash, song_id, t) VALUES (?, ?, ?)", zip(h, [song_id] * len(h), t))
            c.execute("UPDATE songs SET fp_version = ?, n_hashes = ? WHERE id = ?", (fp_version, len(h), song_id))
        return len(h)

    def set_audio_path(self, song_id: int, path: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE songs SET audio_path = ? WHERE id = ?", (path, song_id))

    def all_songs(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM songs ORDER BY id")]

    def update_song(self, song_id: int, **fields: Any) -> None:
        allowed = {"title", "artist", "album", "year", "cover_url", "isrc", "mbid", "preview_url", "lyrics", "duration_s"}
        items = [(k, v) for k, v in fields.items() if k in allowed and v is not None]
        if not items:
            return
        with self._lock:
            self._conn.execute(
                f"UPDATE songs SET {', '.join(f'{k} = ?' for k, _ in items)} WHERE id = ?",
                (*[v for _, v in items], song_id),
            )

    def delete_song(self, song_id: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM hashes WHERE song_id = ?", (song_id,))
            c.execute("DELETE FROM songs WHERE id = ?", (song_id,))

    def list_songs(self, q: str = "", page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
        page, page_size = max(1, page), max(1, min(page_size, 200))
        where, params = "", []
        if q:
            where = "WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?"
            like = f"%{q}%"
            params = [like, like, like]
        total = int(self._q(f"SELECT COUNT(*) FROM songs {where}", params)[0][0])
        rows = self._q(
            f"SELECT {', '.join(SONG_FIELDS)} FROM songs {where} ORDER BY id LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        )
        return [dict(r) for r in rows], total

    def song_fp_versions(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self._q("SELECT fp_version, COUNT(*) FROM songs GROUP BY fp_version")}

    def load_all_hashes(self, chunk: int = 200_000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Stream the full hashes table into numpy arrays (hash uint32, song_id int32, t int32)."""
        with self._lock:
            n = int(self._conn.execute("SELECT COUNT(*) FROM hashes").fetchone()[0])
            H = np.empty(n, np.uint32)
            S = np.empty(n, np.int32)
            T = np.empty(n, np.int32)
            cur = self._conn.execute("SELECT hash, song_id, t FROM hashes")
            i = 0
            while True:
                rows = cur.fetchmany(chunk)
                if not rows:
                    break
                a = np.array(rows, dtype=np.int64)
                H[i : i + len(a)], S[i : i + len(a)], T[i : i + len(a)] = a[:, 0], a[:, 1], a[:, 2]
                i += len(a)
        return H[:i], S[:i], T[:i]

    # ------------------------------------------------------------------ history / stats
    def add_history(self, rec: dict[str, Any]) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO history (created_at, status, source, song_id, confidence, score, offset_seconds,"
                " latency_ms, learned, song_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(), rec["status"], rec.get("source"), rec.get("song_id"), rec.get("confidence"),
                    rec.get("score"), rec.get("offset_seconds"), rec.get("latency_ms"),
                    int(bool(rec.get("learned"))), json.dumps(rec.get("song")) if rec.get("song") else None,
                ),
            )
            return int(cur.lastrowid)

    def list_history(self, limit: int = 50) -> list[dict]:
        rows = self._q("SELECT * FROM history ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),))
        out = []
        for r in rows:
            d = dict(r)
            d["learned"] = bool(d["learned"])
            d["song"] = json.loads(d.pop("song_json")) if d.get("song_json") else None
            out.append(d)
        return out

    def stats(self) -> dict[str, Any]:
        songs = int(self._q("SELECT COUNT(*) FROM songs")[0][0])
        hashes = int(self._q("SELECT COALESCE(SUM(n_hashes), 0) FROM songs")[0][0])
        counts = {(r[0], r[1]): r[2] for r in self._q("SELECT status, source, COUNT(*) FROM history GROUP BY status, source")}
        lat = {r[0]: r[1] for r in self._q("SELECT source, AVG(latency_ms) FROM history WHERE status='match' GROUP BY source")}
        return {
            "total_songs": songs,
            "total_hashes": hashes,
            "own_count": counts.get(("match", "own"), 0),
            "external_count": counts.get(("match", "external"), 0),
            "no_match_count": sum(v for (st, _), v in counts.items() if st == "no_match"),
            "avg_latency_own_ms": round(lat["own"], 1) if lat.get("own") is not None else None,
            "avg_latency_external_ms": round(lat["external"], 1) if lat.get("external") is not None else None,
        }

    # ------------------------------------------------------------------ api cache
    def cache_get(self, key: str) -> Any | None:
        rows = self._q("SELECT value, expires_at FROM api_cache WHERE key = ?", (key,))
        if not rows:
            return None
        if rows[0]["expires_at"] is not None and rows[0]["expires_at"] < time.time():
            return None
        return json.loads(rows[0]["value"])

    def cache_set(self, key: str, value: Any, ttl_s: float | None) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO api_cache (key, value, created_at, expires_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, created_at=excluded.created_at, "
                "expires_at=excluded.expires_at",
                (key, json.dumps(value), now, now + ttl_s if ttl_s else None),
            )
