"""Deterministic synthetic 'songs' for tests (no copyrighted audio in the repo).

Each song is a seeded random melody of harmonic notes over a bass line with percussive noise
bursts. Variants (transposition, different note order) produce *similar* but distinct songs.
"""

from __future__ import annotations

import numpy as np

SR = 11025


def _note(freq: float, dur: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    n = int(dur * sr)
    t = np.arange(n) / sr
    env = np.minimum(1.0, t / 0.01) * np.exp(-3.0 * t / max(dur, 1e-3))
    sig = np.zeros(n)
    for k, amp in enumerate((1.0, 0.5, 0.3, 0.15), start=1):
        if freq * k < sr / 2:
            sig += amp * np.sin(2 * np.pi * freq * k * t + rng.uniform(0, 2 * np.pi))
    return env * sig


def make_song(
    seed: int,
    duration: float = 30.0,
    sr: int = SR,
    transpose: float = 0.0,
    melody_seed: int | None = None,
) -> np.ndarray:
    """Generate a mono float32 song.

    Args:
        seed: controls rhythm, timbre phases and percussion.
        duration: seconds.
        transpose: semitones added to every pitch (for 'similar song' variants).
        melody_seed: seed for the pitch sequence (defaults to ``seed``); sharing the rhythm
            seed but changing this gives a song with identical rhythm and different notes.
    """
    rng = np.random.default_rng(seed)
    mrng = np.random.default_rng(seed if melody_seed is None else melody_seed + 10_000)
    out = np.zeros(int(duration * sr) + sr)
    pos = 0.0
    scale = np.array([0, 2, 4, 5, 7, 9, 11])
    while pos < duration:
        dur = float(rng.choice([0.125, 0.25, 0.25, 0.5]))
        midi = 60 + scale[mrng.integers(0, 7)] + 12 * mrng.integers(-1, 2) + transpose
        freq = 440.0 * 2 ** ((midi - 69) / 12)
        seg = _note(freq, dur * 1.5, sr, rng)
        i = int(pos * sr)
        out[i : i + seg.size] += 0.4 * seg[: out.size - i]
        if rng.random() < 0.5:  # bass
            b = _note(freq / 4, dur, sr, rng)
            out[i : i + b.size] += 0.3 * b[: out.size - i]
        if rng.random() < 0.3:  # percussive burst
            m = int(0.03 * sr)
            out[i : i + m] += 0.2 * rng.standard_normal(m) * np.exp(-np.arange(m) / (0.008 * sr))
        pos += dur
    out = out[: int(duration * sr)]
    out /= np.max(np.abs(out)) + 1e-9
    return (0.8 * out).astype(np.float32)


def add_noise(x: np.ndarray, snr_db: float, seed: int = 0) -> np.ndarray:
    """Add white Gaussian noise at the given signal-to-noise ratio (power, dB)."""
    rng = np.random.default_rng(seed)
    p_sig = float(np.mean(x.astype(np.float64) ** 2))
    noise = rng.standard_normal(x.size)
    noise *= np.sqrt(p_sig / (10 ** (snr_db / 10)) / np.mean(noise**2))
    return (x + noise).astype(np.float32)
