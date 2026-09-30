"""Slow, obviously-correct reference implementation of pipeline steps 3-5.

Written with plain Python/numpy loops and no vectorisation tricks, directly from the spec, so
it can be used to verify the optimised code in ``app.dsp`` produces *identical* peaks, hashes
and match results. Step 2 (the spectrogram) is shared: the reference consumes the same S.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from app.config import DSP, MATCH, DSPConfig, MatchConfig


def ref_find_peaks(S: np.ndarray, cfg: DSPConfig = DSP) -> list[tuple[int, int]]:
    """Return a list of (t, f) peaks, sorted by (t, f)."""
    lo, hi = cfg.F_MIN_BIN, cfg.F_MAX_BIN
    n_frames = S.shape[1]
    # band edges: log-spaced over [lo, hi+1)
    raw = [round(v) for v in np.geomspace(lo, hi + 1, cfg.N_BANDS + 1)]
    raw[0], raw[-1] = lo, hi + 1
    edges = sorted(set(int(v) for v in raw))
    bands = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

    def band_of(f: int) -> tuple[int, int]:
        for a, z in bands:
            if a <= f < z:
                return a, z
        raise AssertionError("bin outside bands")

    peaks: list[tuple[int, int]] = []
    for t in range(n_frames):
        band_mean = {}
        for a, z in bands:
            band_mean[(a, z)] = float(np.mean(S[a:z, t]))
        frame_peaks = []
        for f in range(lo, hi + 1):
            v = S[f, t]
            # neighbourhood restricted to the [lo, hi] x [0, n_frames) region
            f0, f1 = max(lo, f - cfg.PEAK_NBHD_FREQ), min(hi, f + cfg.PEAK_NBHD_FREQ)
            t0, t1 = max(0, t - cfg.PEAK_NBHD_TIME), min(n_frames - 1, t + cfg.PEAK_NBHD_TIME)
            if v != np.max(S[f0 : f1 + 1, t0 : t1 + 1]):
                continue
            if not v > band_mean[band_of(f)] + cfg.BAND_THRESH_DB:
                continue
            frame_peaks.append((v, f))
        frame_peaks.sort(key=lambda p: (-p[0], p[1]))
        for _, f in sorted(frame_peaks[: cfg.MAX_PEAKS_PER_FRAME], key=lambda p: p[1]):
            peaks.append((t, f))
    return peaks


def ref_make_hashes(peaks: list[tuple[int, int]], cfg: DSPConfig = DSP) -> list[tuple[int, int]]:
    """Return a list of (hash, t1) in anchor-major order."""
    out = []
    for i, (t1, f1) in enumerate(peaks):
        taken = 0
        for j in range(i + 1, len(peaks)):
            t2, f2 = peaks[j]
            dt = t2 - t1
            if dt > cfg.MAX_DT:
                break
            if dt < cfg.MIN_DT or abs(f2 - f1) > cfg.MAX_DF:
                continue
            assert 0 <= f1 < 2048 and 0 <= f2 < 2048 and 0 <= dt < 1024
            out.append(((f1 << 21) | (f2 << 10) | dt, t1))
            taken += 1
            if taken == cfg.FAN_OUT:
                break
    return out


def ref_match(
    query: list[tuple[int, int]],
    db: dict[int, list[tuple[int, int]]],
    cfg: MatchConfig = MATCH,
) -> dict:
    """Reference matcher.

    Args:
        query: list of (hash, t_query).
        db: song_id -> list of (hash, t_db).
    """
    table: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for song, entries in db.items():
        for h, t in entries:
            table[h].add((song, t))
    qpairs = sorted(set(query))
    # per song: list of (delta, qpair_index)
    hits: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for qi, (h, tq) in enumerate(qpairs):
        for song, tdb in table.get(h, ()):
            hits[song].append((tdb - tq, qi))
    if not hits:
        return {"matched": False, "song_id": None, "score": 0, "delta": 0, "second": 0}
    ranked = sorted(hits, key=lambda s: (-len(hits[s]), s))[: cfg.SEARCH_DEPTH]
    scores = []
    for song in ranked:
        hist: dict[int, int] = defaultdict(int)
        for d, _ in hits[song]:
            hist[d] += 1
        best_count = max(hist.values())
        peak = min(d for d, c in hist.items() if c == best_count)
        in_window = {qi for d, qi in hits[song] if abs(d - peak) <= cfg.WINDOW}
        scores.append((len(in_window), song, peak))
    scores.sort(key=lambda x: (-x[0], x[1]))
    best_score, best_song, best_delta = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0
    ratio = best_score / max(second, 1)
    matched = best_score >= cfg.MIN_SCORE and ratio >= cfg.MIN_RATIO
    conf = 0.0
    if matched:
        conf = (1 - math.exp(-best_score / cfg.SCORE_SCALE)) * (1 - 1 / max(ratio, 1.0))
    return {
        "matched": matched,
        "song_id": best_song if matched else None,
        "score": best_score,
        "delta": best_delta,
        "second": second,
        "confidence": conf,
    }
