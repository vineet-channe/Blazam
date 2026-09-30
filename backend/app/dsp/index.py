"""In-memory inverted index of (hash -> song_id, t_db), backed by sorted numpy arrays.

Wang03 §2.2: "the 64-bit structs are sorted according to hash token value". We keep a large
sorted *base* segment plus a few small sorted *pending* segments (new songs); lookups binary-
search every segment, and :meth:`HashIndex.compact` merges pending segments into the base.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np


@dataclass
class _Segment:
    hashes: np.ndarray  # uint32 sorted
    song_ids: np.ndarray  # int32
    offsets: np.ndarray  # int32

    @staticmethod
    def build(hashes: np.ndarray, song_ids: np.ndarray, offsets: np.ndarray) -> "_Segment":
        # stable sort on (hash, song, t) so layout is deterministic
        order = np.lexsort((offsets, song_ids, hashes))
        return _Segment(
            np.ascontiguousarray(hashes[order], dtype=np.uint32),
            np.ascontiguousarray(song_ids[order], dtype=np.int32),
            np.ascontiguousarray(offsets[order], dtype=np.int32),
        )

    def __len__(self) -> int:
        return int(self.hashes.size)


def _empty() -> _Segment:
    return _Segment(np.zeros(0, np.uint32), np.zeros(0, np.int32), np.zeros(0, np.int32))


class HashIndex:
    """Thread-safe hash -> (song_id, t_db) lookup table."""

    MAX_PENDING = 16

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._base = _empty()
        self._pending: list[_Segment] = []
        self._removed: set[int] = set()
        self._hash_counts: dict[int, int] = {}

    # ------------------------------------------------------------------ mutation
    def load(self, hashes: np.ndarray, song_ids: np.ndarray, offsets: np.ndarray) -> None:
        """Replace the index contents with the given arrays."""
        seg = _Segment.build(np.asarray(hashes), np.asarray(song_ids), np.asarray(offsets))
        counts = np.bincount(seg.song_ids) if len(seg) else np.zeros(0, np.int64)
        with self._lock:
            self._base = seg
            self._pending = []
            self._removed = set()
            self._hash_counts = {int(i): int(c) for i, c in enumerate(counts) if c}

    def load_sorted(self, hashes: np.ndarray, song_ids: np.ndarray, offsets: np.ndarray) -> None:
        """Replace contents with arrays already in (hash, song, t) order (e.g. from a snapshot)."""
        h = np.ascontiguousarray(hashes, dtype=np.uint32)
        if h.size > 1 and not bool(np.all(h[1:] >= h[:-1])):
            raise ValueError("snapshot hashes are not sorted")
        seg = _Segment(h, np.ascontiguousarray(song_ids, dtype=np.int32), np.ascontiguousarray(offsets, dtype=np.int32))
        counts = np.bincount(seg.song_ids) if len(seg) else np.zeros(0, np.int64)
        with self._lock:
            self._base = seg
            self._pending = []
            self._removed = set()
            self._hash_counts = {int(i): int(c) for i, c in enumerate(counts) if c}

    def export(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compact and return the sorted (hashes, song_ids, offsets) arrays."""
        with self._lock:
            self._compact_locked()
            return self._base.hashes, self._base.song_ids, self._base.offsets

    def add_song(self, song_id: int, hashes: np.ndarray, offsets: np.ndarray) -> None:
        """Add one song's (hash, t1) pairs. Duplicate (hash, t1) pairs are dropped."""
        hashes = np.asarray(hashes, dtype=np.uint32)
        offsets = np.asarray(offsets, dtype=np.int32)
        key = np.unique((hashes.astype(np.uint64) << np.uint64(32)) | offsets.astype(np.uint32).astype(np.uint64))
        h = (key >> np.uint64(32)).astype(np.uint32)
        t = (key & np.uint64(0xFFFFFFFF)).astype(np.uint32).astype(np.int32)
        seg = _Segment.build(h, np.full(h.size, song_id, np.int32), t)
        with self._lock:
            self._removed.discard(song_id)
            self._pending.append(seg)
            self._hash_counts[song_id] = int(h.size)
            if len(self._pending) > self.MAX_PENDING:
                self._compact_locked()

    def remove_song(self, song_id: int) -> None:
        with self._lock:
            self._removed.add(song_id)
            self._hash_counts.pop(song_id, None)

    def compact(self) -> None:
        with self._lock:
            self._compact_locked()

    def _compact_locked(self) -> None:
        segs = [self._base, *self._pending]
        h = np.concatenate([s.hashes for s in segs])
        s_ = np.concatenate([s.song_ids for s in segs])
        t = np.concatenate([s.offsets for s in segs])
        if self._removed:
            keep = ~np.isin(s_, np.fromiter(self._removed, dtype=np.int32))
            h, s_, t = h[keep], s_[keep], t[keep]
            self._removed = set()
        self._base = _Segment.build(h, s_, t)
        self._pending = []

    # ------------------------------------------------------------------ queries
    @property
    def n_hashes(self) -> int:
        with self._lock:
            return sum(self._hash_counts.values())

    @property
    def n_songs(self) -> int:
        with self._lock:
            return len(self._hash_counts)

    def song_ids(self) -> list[int]:
        with self._lock:
            return sorted(self._hash_counts)

    def lookup(self, q_hashes: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Find all database entries whose hash equals any query hash.

        Args:
            q_hashes: uint32 array of query hashes (any order, duplicates allowed).

        Returns:
            (q_index, song_id, t_db): for each hit, the index into ``q_hashes`` it came from,
            and the database song and anchor time.
        """
        q = np.asarray(q_hashes, dtype=np.uint32)
        with self._lock:
            segs = [self._base, *self._pending]
            removed = np.fromiter(self._removed, dtype=np.int32) if self._removed else None
        out_q, out_s, out_t = [], [], []
        for seg in segs:
            if not len(seg) or not q.size:
                continue
            left = np.searchsorted(seg.hashes, q, side="left")
            right = np.searchsorted(seg.hashes, q, side="right")
            counts = right - left
            total = int(counts.sum())
            if total == 0:
                continue
            q_idx = np.repeat(np.arange(q.size), counts)
            # position of each hit inside its [left, right) run
            run_start = np.repeat(np.cumsum(counts) - counts, counts)
            db_idx = np.repeat(left, counts) + (np.arange(total) - run_start)
            out_q.append(q_idx)
            out_s.append(seg.song_ids[db_idx])
            out_t.append(seg.offsets[db_idx])
        if not out_q:
            z = np.zeros(0, np.int64)
            return z, z.astype(np.int32), z.astype(np.int32)
        qi, si, ti = np.concatenate(out_q), np.concatenate(out_s), np.concatenate(out_t)
        if removed is not None and removed.size:
            keep = ~np.isin(si, removed)
            qi, si, ti = qi[keep], si[keep], ti[keep]
        return qi, si, ti
