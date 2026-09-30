"""Step 5: searching and scoring (Wang03 §2.3).

For each database song, the matched time pairs (t_db, t_query) are reduced to
``delta = t_db - t_query`` and histogrammed in 1-frame bins. The peak bin is located (ties ->
smallest delta), and the score is the number of *distinct* query (hash, t_query) pairs whose
delta lies within +/- WINDOW bins of the peak (= peak bin plus its two neighbours for WINDOW=1;
de-duplication as in audfprint ``Matcher._unique_match_hashes``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from app.config import DSP, MATCH, MatchConfig
from app.dsp.fingerprint import Fingerprint
from app.dsp.index import HashIndex


@dataclass(frozen=True)
class Candidate:
    song_id: int
    score: int
    delta: int  # frames
    raw_hits: int


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    song_id: int | None
    score: int
    second_score: int
    ratio: float
    confidence: float
    offset_frames: int
    offset_seconds: float
    n_query_hashes: int
    candidates: list[Candidate] = field(default_factory=list)


def confidence(score: int, ratio: float, cfg: MatchConfig = MATCH) -> float:
    """Map (score, ratio) to [0, 1]; non-decreasing in both arguments.

    ``conf = (1 - exp(-score / SCORE_SCALE)) * (1 - 1 / max(ratio, 1))``

    The first factor saturates as more aligned hashes agree; the second is 0 when the best and
    second-best songs tie and approaches 1 as the winner dominates.
    """
    if score <= 0:
        return 0.0
    r = max(float(ratio), 1.0)
    c = (1.0 - math.exp(-score / cfg.SCORE_SCALE)) * (1.0 - 1.0 / r)
    return float(min(max(c, 0.0), 1.0))


def unique_query_pairs(fp: Fingerprint) -> tuple[np.ndarray, np.ndarray]:
    """Distinct (hash, t_query) pairs of a query, sorted by (hash, t)."""
    key = np.unique((fp.hashes.astype(np.uint64) << np.uint64(32)) | fp.offsets.astype(np.uint32).astype(np.uint64))
    return (key >> np.uint64(32)).astype(np.uint32), (key & np.uint64(0xFFFFFFFF)).astype(np.int64)


def collect_hits(fp: Fingerprint, index: HashIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (song_id, delta, query_pair_id) for every database hit of the query."""
    qh, qt = unique_query_pairs(fp)
    qi, sid, tdb = index.lookup(qh)
    delta = tdb.astype(np.int64) - qt[qi]
    return sid.astype(np.int64), delta, qi.astype(np.int64)


def score_song(delta: np.ndarray, qpair: np.ndarray, window: int) -> tuple[int, int]:
    """Histogram-peak score for one song's hits. Returns (score, peak_delta)."""
    dmin = int(delta.min())
    hist = np.bincount(delta - dmin)
    peak = int(np.argmax(hist)) + dmin  # argmax returns first max -> smallest delta on ties
    in_win = np.abs(delta - peak) <= window
    return int(np.unique(qpair[in_win]).size), peak


def match(fp: Fingerprint, index: HashIndex, cfg: MatchConfig = MATCH) -> MatchResult:
    """Identify the query fingerprint against the index."""
    n_q = int(unique_query_pairs(fp)[0].size)
    sid, delta, qpair = collect_hits(fp, index)
    if sid.size == 0:
        return MatchResult(False, None, 0, 0, 0.0, 0.0, 0, 0.0, n_q, [])

    songs, raw = np.unique(sid, return_counts=True)
    # candidates by raw hit count desc, then song id asc; at most SEARCH_DEPTH
    order = np.lexsort((songs, -raw))[: cfg.SEARCH_DEPTH]
    cand_ids = songs[order]

    srt = np.lexsort((qpair, delta, sid))
    sid_s, delta_s, q_s = sid[srt], delta[srt], qpair[srt]
    starts = np.searchsorted(sid_s, cand_ids, side="left")
    ends = np.searchsorted(sid_s, cand_ids, side="right")

    cands: list[Candidate] = []
    for song, a, b, r in zip(cand_ids, starts, ends, raw[order]):
        score, peak = score_song(delta_s[a:b], q_s[a:b], cfg.WINDOW)
        cands.append(Candidate(int(song), score, peak, int(r)))
    cands.sort(key=lambda c: (-c.score, c.song_id))

    best = cands[0]
    second = cands[1].score if len(cands) > 1 else 0
    ratio = best.score / max(second, 1)
    matched = best.score >= cfg.MIN_SCORE and ratio >= cfg.MIN_RATIO
    return MatchResult(
        matched=matched,
        song_id=best.song_id if matched else None,
        score=best.score,
        second_score=second,
        ratio=float(ratio),
        confidence=confidence(best.score, ratio, cfg) if matched else 0.0,
        offset_frames=best.delta,
        offset_seconds=best.delta * DSP.HOP / DSP.SAMPLE_RATE,
        n_query_hashes=n_q,
        candidates=cands[:5],
    )


def delta_histogram(fp: Fingerprint, index: HashIndex, song_id: int) -> tuple[np.ndarray, np.ndarray]:
    """(delta_values, counts) of the offset histogram for one song - used for plots/debugging."""
    sid, delta, _ = collect_hits(fp, index)
    d = delta[sid == song_id]
    if d.size == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    vals, counts = np.unique(d, return_counts=True)
    return vals, counts
