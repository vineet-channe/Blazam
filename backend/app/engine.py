"""Tier-1 engine: owns the SQLite database and the in-memory hash index."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.config import DSP, SETTINGS
from app.db import Database
from app.dsp.audio import load_audio
from app.dsp.fingerprint import Fingerprint, fingerprint_signal
from app.dsp.index import HashIndex
from app.dsp.matcher import MatchResult, match

log = logging.getLogger("blazam.engine")


def fp_version() -> str:
    """Identifier of the fingerprint parameter set; stored hashes are only valid for it."""
    raw = json.dumps(dataclasses.asdict(DSP), sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def resolve_audio_path(root: Path, stored: str | None) -> Path | None:
    """Locate a song's audio file.

    New rows store paths relative to the data dir (the DB's folder), so a library can move
    between machines/containers. Legacy absolute paths are tried as-is, then by their longest
    suffix that exists under ``root`` (e.g. a host path inside the Docker volume).
    """
    if not stored:
        return None
    p = Path(stored)
    if not p.is_absolute():
        return root / p
    if p.is_file():
        return p
    for i in range(1, len(p.parts)):
        cand = root.joinpath(*p.parts[i:])
        if cand.is_file():
            return cand
    return None


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Engine:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database(SETTINGS.db_path)
        self.index = HashIndex()
        self.version = fp_version()
        self._write_lock = threading.Lock()
        self.loaded = False
        self.stale_songs = 0
        self._dirty = False  # index changed since the last snapshot

    @property
    def data_root(self) -> Path:
        return Path(self.db.path).resolve().parent if self.db.path != ":memory:" else Path.cwd()

    def _store_path(self, path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.data_root))
        except ValueError:
            return str(Path(path).resolve())

    def migrate_audio_paths(self) -> int:
        """Rewrite legacy absolute audio paths that live under the data dir as relative ones."""
        n = 0
        for song in self.db.all_songs():
            stored = song.get("audio_path")
            if stored and Path(stored).is_absolute():
                found = resolve_audio_path(self.data_root, stored)
                if found is not None:
                    rel = self._store_path(found)
                    if not Path(rel).is_absolute():
                        self.db.set_audio_path(song["id"], rel)
                        n += 1
        return n

    # ------------------------------------------------------------------ snapshot
    @property
    def snapshot_path(self) -> Path | None:
        if self.db.path == ":memory:":
            return None
        return Path(self.db.path).with_suffix(".index.npz")

    def _snapshot_key(self) -> str:
        """Identifies the exact DB state a snapshot was built from (songs + fingerprint version)."""
        h = hashlib.sha1(self.version.encode())
        for r in self.db._q("SELECT id, n_hashes, fp_version FROM songs ORDER BY id"):
            h.update(f"{r[0]}:{r[1]}:{r[2]};".encode())
        return h.hexdigest()

    def save_snapshot(self) -> Path | None:
        """Persist the in-memory index (sorted arrays) so the next start skips the SQLite scan."""
        path = self.snapshot_path
        if path is None or not self.loaded:
            return None
        with self._write_lock:
            H, S, T = self.index.export()
            key = self._snapshot_key()
        tmp = path.with_suffix(".tmp.npz")
        np.savez(tmp, hashes=H, song_ids=S, offsets=T, key=np.array(key))
        tmp.replace(path)
        self._dirty = False
        return path

    def _try_load_snapshot(self) -> bool:
        path = self.snapshot_path
        if path is None or not path.is_file():
            return False
        try:
            with np.load(path) as z:
                if str(z["key"]) != self._snapshot_key():
                    return False
                self.index.load_sorted(z["hashes"], z["song_ids"], z["offsets"])
            return True
        except (OSError, KeyError, ValueError) as e:
            log.warning("ignoring unreadable index snapshot %s: %s", path, e)
            return False

    def load_index(self) -> dict[str, Any]:
        """Load the hash index: from a matching snapshot if present, otherwise from SQLite.

        Songs with another fp_version are skipped (they need ``python -m app.index --reindex``).
        """
        t0 = time.perf_counter()
        versions = self.db.song_fp_versions()
        self.stale_songs = sum(n for v, n in versions.items() if v != self.version)
        if self._try_load_snapshot():
            self.loaded = True
            self._dirty = False
            info = {"songs": self.index.n_songs, "hashes": self.index.n_hashes,
                    "seconds": round(time.perf_counter() - t0, 2), "stale_songs": self.stale_songs,
                    "source": "snapshot"}
            log.info("index loaded: %s", info)
            return info
        H, S, T = self.db.load_all_hashes()
        if self.stale_songs:
            stale_ids = [s["id"] for s in self.db.all_songs() if s["fp_version"] != self.version]
            keep = ~np.isin(S, np.asarray(stale_ids, dtype=np.int32))
            H, S, T = H[keep], S[keep], T[keep]
            log.warning("%d songs were fingerprinted with other parameters; run `python -m app.index --reindex`",
                        self.stale_songs)
        self.index.load(H, S, T)
        self.loaded = True
        self._dirty = False
        info = {"songs": self.index.n_songs, "hashes": int(H.size), "seconds": round(time.perf_counter() - t0, 2),
                "stale_songs": self.stale_songs, "source": "sqlite"}
        log.info("index loaded: %s", info)
        if not self.stale_songs:
            self.save_snapshot()
        return info

    # ------------------------------------------------------------------ indexing
    def index_signal(self, x: np.ndarray, meta: dict[str, Any], sha1: str | None = None) -> tuple[int, Fingerprint]:
        """Fingerprint a mono signal and persist + index it. Returns (song_id, fingerprint)."""
        fp = fingerprint_signal(x)
        if fp.hashes.size == 0:
            raise ValueError("no fingerprint hashes (silent or too short?)")
        meta = {**meta, "file_sha1": sha1}
        if not meta.get("duration_s"):
            meta["duration_s"] = round(x.size / DSP.SAMPLE_RATE, 2)
        with self._write_lock:
            song_id = self.db.insert_song_with_hashes(meta, fp.hashes, fp.offsets, self.version)
            self.index.add_song(song_id, fp.hashes, fp.offsets)
            self._dirty = True
        return song_id, fp

    def index_file(self, path: Path, meta: dict[str, Any]) -> tuple[int, bool]:
        """Index an audio file. Returns (song_id, created); skips files already indexed."""
        sha1 = file_sha1(path)
        existing = self.db.find_song(sha1=sha1)
        if existing is None and meta.get("deezer_id") is not None:
            existing = self.db.find_song(deezer_id=meta["deezer_id"])
        if existing:
            return int(existing["id"]), False
        x = load_audio(path)
        fp = fingerprint_signal(x)
        if fp.hashes.size == 0:
            raise ValueError("no fingerprint hashes (silent or too short?)")
        meta = {**meta, "audio_path": self._store_path(path), "file_sha1": sha1}
        if not meta.get("duration_s"):
            meta["duration_s"] = round(x.size / DSP.SAMPLE_RATE, 2)
        with self._write_lock:  # re-check under the lock: concurrent imports may race on the same file
            existing = self.db.find_song(sha1=sha1)
            if existing is None and meta.get("deezer_id") is not None:
                existing = self.db.find_song(deezer_id=meta["deezer_id"])
            if existing:
                return int(existing["id"]), False
            song_id = self.db.insert_song_with_hashes(meta, fp.hashes, fp.offsets, self.version)
            self.index.add_song(song_id, fp.hashes, fp.offsets)
            self._dirty = True
        return song_id, True

    def reindex_all(self, progress: Any = None) -> dict[str, int]:
        """Re-fingerprint every stored song whose fp_version differs (needs its audio file)."""
        done = missing = 0
        for s in self.db.all_songs():
            if s["fp_version"] == self.version:
                continue
            p = resolve_audio_path(self.data_root, s["audio_path"])
            if p is None or not p.is_file():
                missing += 1
                continue
            fp = fingerprint_signal(load_audio(p))
            self.db.replace_hashes(s["id"], fp.hashes, fp.offsets, self.version)
            done += 1
            if progress:
                progress(done, s["title"])
        self.load_index()
        return {"reindexed": done, "missing_audio": missing}

    def delete_song(self, song_id: int) -> None:
        with self._write_lock:
            self.db.delete_song(song_id)
            self.index.remove_song(song_id)
            self._dirty = True

    # ------------------------------------------------------------------ matching
    def save_snapshot_if_dirty(self) -> Path | None:
        return self.save_snapshot() if self._dirty and not self.stale_songs else None

    def identify(self, x: np.ndarray) -> MatchResult:
        return match(fingerprint_signal(x), self.index)
