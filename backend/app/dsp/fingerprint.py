"""Steps 2-4 of the pipeline: spectrogram -> constellation peaks -> combinatorial hashes.

All functions are pure and deterministic; the same function is used for indexing and for
querying (Wang03 §2: "Both 'database' and 'sample' audio files are subjected to the same
analysis"). Parameters come exclusively from ``app.config.DSP``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import maximum_filter

from app.config import DSP, DSPConfig

_F_SHIFT_1 = DSP.F_BITS + DSP.DT_BITS  # f1 occupies the top 11 bits
_F_SHIFT_2 = DSP.DT_BITS  # f2 the next 11
_F_MASK = (1 << DSP.F_BITS) - 1
_DT_MASK = (1 << DSP.DT_BITS) - 1


@dataclass(frozen=True)
class Fingerprint:
    """Result of fingerprinting one signal."""

    hashes: np.ndarray  # uint32, shape (n,)
    offsets: np.ndarray  # int32 anchor time t1 in frames, shape (n,)
    peaks: np.ndarray  # int32, shape (m, 2) columns [t, f], sorted by (t, f)
    n_frames: int

    @property
    def duration_s(self) -> float:
        return self.n_frames * DSP.HOP / DSP.SAMPLE_RATE


# ----------------------------------------------------------------------------- step 2
def _window(cfg: DSPConfig) -> np.ndarray:
    if cfg.WINDOW != "hann_symmetric":
        raise ValueError(f"unsupported window {cfg.WINDOW}")
    return np.hanning(cfg.N_FFT)  # [Dejavu] mlab.window_hanning == np.hanning


def spectrogram_db(x: np.ndarray, cfg: DSPConfig = DSP) -> np.ndarray:
    """Log-power STFT, shape (N_FFT//2 + 1, n_frames), float64.

    Frames start at sample 0 and advance by HOP with no centre padding; signals shorter than
    one window are zero-padded to exactly one frame. Power is ``|X|^2``; the log is
    ``10*log10(|X|^2 + EPS)``, then clamped to ``max - DB_FLOOR_REL``.

    Args:
        x: mono signal at ``cfg.SAMPLE_RATE``.
        cfg: DSP configuration.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < cfg.N_FFT:
        x = np.pad(x, (0, cfg.N_FFT - x.size))
    n_frames = 1 + (x.size - cfg.N_FFT) // cfg.HOP
    win = _window(cfg)
    frames = np.lib.stride_tricks.sliding_window_view(x, cfg.N_FFT)[:: cfg.HOP][:n_frames]
    out = np.empty((cfg.N_FFT // 2 + 1, n_frames), dtype=np.float64)
    chunk = 512  # bound peak memory for long songs
    for s in range(0, n_frames, chunk):
        spec = np.fft.rfft(frames[s : s + chunk] * win, axis=1)
        power = spec.real**2 + spec.imag**2
        out[:, s : s + chunk] = (10.0 * np.log10(power + cfg.EPS)).T
    floor = out.max() - cfg.DB_FLOOR_REL
    np.maximum(out, floor, out=out)
    return out


# ----------------------------------------------------------------------------- step 3
def band_edges(cfg: DSPConfig = DSP) -> np.ndarray:
    """Log-spaced band edges (absolute bin indices) over [F_MIN_BIN, F_MAX_BIN + 1).

    Returns an int array ``e`` of length ``n+1``; band ``b`` covers bins ``e[b] .. e[b+1]-1``.
    """
    edges = np.round(np.geomspace(cfg.F_MIN_BIN, cfg.F_MAX_BIN + 1, cfg.N_BANDS + 1)).astype(np.int64)
    edges[0], edges[-1] = cfg.F_MIN_BIN, cfg.F_MAX_BIN + 1
    return np.unique(edges)


def find_peaks(S: np.ndarray, cfg: DSPConfig = DSP) -> np.ndarray:
    """Constellation map (Wang03 §2.1).

    A bin (t, f) with ``F_MIN_BIN <= f <= F_MAX_BIN`` is a peak iff
      1. it equals the maximum of the rectangular neighbourhood of half-size
         (PEAK_NBHD_FREQ, PEAK_NBHD_TIME) (``scipy.ndimage.maximum_filter``; cells outside the
         restricted spectrogram are treated as -inf), and
      2. it exceeds the mean dB of its log-spaced band *in the same frame* by BAND_THRESH_DB.
    Then per frame only the MAX_PEAKS_PER_FRAME highest-amplitude peaks are kept (ties broken
    by lower frequency).

    Args:
        S: log-power spectrogram from :func:`spectrogram_db`, shape (n_freq, n_frames).

    Returns:
        int32 array (m, 2) with columns [t, f] (absolute bin index), sorted by (t, f).
    """
    lo, hi = cfg.F_MIN_BIN, cfg.F_MAX_BIN
    sub = S[lo : hi + 1, :]
    if sub.size == 0:
        return np.zeros((0, 2), dtype=np.int32)
    size = (2 * cfg.PEAK_NBHD_FREQ + 1, 2 * cfg.PEAK_NBHD_TIME + 1)
    local_max = maximum_filter(sub, size=size, mode="constant", cval=-np.inf) == sub

    thresh = np.empty_like(sub)
    edges = band_edges(cfg) - lo
    for b in range(len(edges) - 1):
        a, z = edges[b], edges[b + 1]
        thresh[a:z, :] = sub[a:z, :].mean(axis=0, keepdims=True) + cfg.BAND_THRESH_DB
    cand = local_max & (sub > thresh)

    f_idx, t_idx = np.nonzero(cand)
    if f_idx.size == 0:
        return np.zeros((0, 2), dtype=np.int32)
    amp = sub[f_idx, t_idx]
    # order: t asc, amplitude desc, f asc  (np.lexsort: last key is primary)
    order = np.lexsort((f_idx, -amp, t_idx))
    f_idx, t_idx = f_idx[order], t_idx[order]
    # rank within each frame
    starts = np.r_[0, np.flatnonzero(np.diff(t_idx)) + 1]
    group_start = np.repeat(starts, np.diff(np.r_[starts, t_idx.size]))
    keep = (np.arange(t_idx.size) - group_start) < cfg.MAX_PEAKS_PER_FRAME
    t_k, f_k = t_idx[keep], f_idx[keep] + lo
    order = np.lexsort((f_k, t_k))
    return np.stack([t_k[order], f_k[order]], axis=1).astype(np.int32)


# ----------------------------------------------------------------------------- step 4
def pack_hash(f1: np.ndarray | int, f2: np.ndarray | int, dt: np.ndarray | int) -> np.ndarray:
    """Pack (f1, f2, dt) into uint32: f1 (11 bits) | f2 (11 bits) | dt (10 bits)."""
    f1 = np.asarray(f1, dtype=np.int64)
    f2 = np.asarray(f2, dtype=np.int64)
    dt = np.asarray(dt, dtype=np.int64)
    assert np.all((f1 >= 0) & (f1 <= _F_MASK)), "f1 out of 11-bit range"
    assert np.all((f2 >= 0) & (f2 <= _F_MASK)), "f2 out of 11-bit range"
    assert np.all((dt >= 0) & (dt <= _DT_MASK)), "dt out of 10-bit range"
    return ((f1 << _F_SHIFT_1) | (f2 << _F_SHIFT_2) | dt).astype(np.uint32)


def unpack_hash(h: np.ndarray | int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inverse of :func:`pack_hash`."""
    h = np.asarray(h, dtype=np.int64)
    return (h >> _F_SHIFT_1) & _F_MASK, (h >> _F_SHIFT_2) & _F_MASK, h & _DT_MASK


def make_hashes(peaks: np.ndarray, cfg: DSPConfig = DSP) -> tuple[np.ndarray, np.ndarray]:
    """Combinatorial hashing (Wang03 §2.2).

    Peaks are in (t, f) order. Each anchor i is paired with the first FAN_OUT later peaks j
    (in that order) with ``MIN_DT <= t_j - t_i <= MAX_DT`` and ``|f_j - f_i| <= MAX_DF``.

    Returns:
        (hashes uint32, t1 int32) - one entry per pair, anchor-major order.
    """
    n = len(peaks)
    if n == 0:
        return np.zeros(0, np.uint32), np.zeros(0, np.int32)
    t = peaks[:, 0].astype(np.int64)
    f = peaks[:, 1].astype(np.int64)
    lo = np.searchsorted(t, t + cfg.MIN_DT, side="left")
    hi = np.searchsorted(t, t + cfg.MAX_DT, side="right")
    width = int((hi - lo).max(initial=0))
    taken = np.zeros(n, dtype=np.int64)
    anchors, targets, ranks = [], [], []
    for k in range(width):
        j = lo + k
        valid = j < hi
        jj = np.where(valid, j, 0)
        valid &= np.abs(f[jj] - f) <= cfg.MAX_DF
        valid &= taken < cfg.FAN_OUT
        idx = np.flatnonzero(valid)
        if idx.size:
            anchors.append(idx)
            targets.append(jj[idx])
            ranks.append(np.full(idx.size, k))
            taken[idx] += 1
    if not anchors:
        return np.zeros(0, np.uint32), np.zeros(0, np.int32)
    a = np.concatenate(anchors)
    b = np.concatenate(targets)
    order = np.lexsort((np.concatenate(ranks), a))  # anchor-major, then pairing order
    a, b = a[order], b[order]
    hashes = pack_hash(f[a], f[b], t[b] - t[a])
    return hashes, t[a].astype(np.int32)


def fingerprint_signal(x: np.ndarray, cfg: DSPConfig = DSP) -> Fingerprint:
    """Full steps 2-4 for a mono signal already at ``cfg.SAMPLE_RATE``."""
    S = spectrogram_db(x, cfg)
    peaks = find_peaks(S, cfg)
    hashes, offsets = make_hashes(peaks, cfg)
    return Fingerprint(hashes=hashes, offsets=offsets, peaks=peaks, n_frames=S.shape[1])
