"""Single source of truth for every tunable parameter.

Every DSP / matching constant carries a provenance comment:

* ``[Wang03 §x]``  - Wang 2003, "An Industrial-Strength Audio Search Algorithm".
* ``[Dejavu]``     - worldveil/dejavu ``dejavu/config/settings.py`` (master).
* ``[audfprint]``  - dpwe/audfprint ``audfprint_analyze.py`` / ``audfprint_match.py`` (master).
* ``[spec]``       - fixed by the Blazam product spec (not from a paper).
* ``[tuned by eval]`` - my own choice, set with ``scripts/eval.py`` and logged in docs/TUNING.md.

A value tagged ``[tuned by eval]`` is NOT sourced from the literature, even when its
starting point was derived from one. See docs/ALGORITHM.md for the full mapping.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# --------------------------------------------------------------------------------------
# DSP / fingerprint parameters (shared by indexing and querying: one code path)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DSPConfig:
    # Sample rate after resampling. [audfprint] Analyzer.target_sr = 11025.
    SAMPLE_RATE: int = 11025
    # FFT size. [Dejavu] DEFAULT_WINDOW_SIZE = 4096. At 11025 Hz -> 2.69 Hz/bin, 371 ms window.
    N_FFT: int = 4096
    # Hop size. [spec] HOP=512 -> 46.4 ms/frame. (Same frame period as Dejavu:
    # 4096*(1-0.5)=2048 samples @ 44100 Hz = 46.4 ms.)
    HOP: int = 512
    # Window. [Dejavu] mlab.window_hanning == numpy.hanning (symmetric Hann).
    WINDOW: str = "hann_symmetric"
    # Added to |X|^2 before log10. [spec] "10*log10(mag^2+eps)". Value is numerical only.
    EPS: float = 1e-10
    # Relative dB floor: values below (frame-global max - DB_FLOOR_REL) are clamped.
    # [audfprint] clamps magnitude at max/1e6 (= -120 dB in power); we use the same 120 dB range.
    DB_FLOOR_REL: float = 120.0

    # --- peak picking (Wang03 §2.1) ---
    # Neighbourhood half-widths for scipy.ndimage.maximum_filter (footprint = rectangle
    # (2*F+1) x (2*T+1)).  [Dejavu] PEAK_NEIGHBORHOOD_SIZE=10 with CONNECTIVITY_MASK=2 gives a
    # 21x21 square; at our 4x finer frequency resolution that is 4x narrower in Hz, so the
    # frequency half-width is [tuned by eval] (see TUNING.md); time half-width starts from Dejavu.
    PEAK_NBHD_FREQ: int = 10  # [tuned by eval] kept at Dejavu's 10; 20/40 lost robustness (TUNING.md T1)
    PEAK_NBHD_TIME: int = 10  # [Dejavu] PEAK_NEIGHBORHOOD_SIZE = 10
    # Number of log-spaced frequency bands for the per-band amplitude threshold. [spec] "about 6".
    N_BANDS: int = 6
    # A peak must exceed its band's per-frame mean (in dB) by this margin. [tuned by eval]
    # 6 -> 10: -18% hashes, equal or better robustness (docs/TUNING.md T3/T4).
    BAND_THRESH_DB: float = 10.0
    # Maximum peaks kept per frame. [audfprint] Analyzer.maxpksperframe = 5.
    MAX_PEAKS_PER_FRAME: int = 5
    # Frequency range (bins) used for peaks.  Upper bound: 2047 = largest 11-bit value
    # (hash field limit [spec]); bin 2048 is Nyquist, which audfprint also discards. [audfprint]
    # Lower bound [tuned by eval]: skips DC / sub-bass rumble.
    F_MIN_BIN: int = 12   # [tuned by eval] ~32 Hz
    F_MAX_BIN: int = 2047  # [spec] 11-bit field limit

    # --- hashing (Wang03 §2.2) ---
    # Fan-out. [tuned by eval] 10 -> 15 (docs/TUNING.md T2/T4). Starting point: [Wang03 §2.2]
    # example F=10. (15 is also Dejavu's original DEFAULT_FAN_VALUE; audfprint uses 3.)
    FAN_OUT: int = 15
    # Minimum dt (frames). [audfprint] Analyzer.mindt = 2.
    MIN_DT: int = 2
    # Maximum dt (frames). [tuned by eval]; starting point: audfprint targetdt=63 frames of
    # 23.2 ms = 1.46 s, which is ~32 frames at our 46.4 ms hop. Must fit DT_BITS.
    # 32 -> 48 (docs/TUNING.md T4).
    MAX_DT: int = 48
    # Max |f2 - f1| (bins). [tuned by eval]; starting point: audfprint targetdf=31 bins at
    # 21.5 Hz/bin ~= 667 Hz, which is ~248 bins at our 2.69 Hz/bin.
    MAX_DF: int = 248  # halving to 124 was worse (TUNING.md T4)
    # Bit layout of the uint32 hash. [spec] f1:11 | f2:11 | dt:10 (Wang03 §2.2 packs "into a
    # 32-bit unsigned integer" with ~10 bits per component).
    F_BITS: int = 11
    DT_BITS: int = 10


# --------------------------------------------------------------------------------------
# Matching / routing (Wang03 §2.3, §2.3.1)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MatchConfig:
    # Histogram bin tolerance: score counts peak bin +/- this many bins. [spec] "peak bin plus its
    # two neighbors"; identical to [audfprint] Matcher.window = 1.
    WINDOW: int = 1
    # Absolute minimum score. [tuned by eval] 5 -> 12 (docs/TUNING.md T5) -> 15 (T6): with the
    # final DSP config the chance-score maximum is 11 over 462 true negatives (p99 10); the tail
    # halves per step, so 15 targets ~0.1% FPR (Wang03 §2.3.1 example) with no loss on the
    # required conditions (lowest correct score there: 22).
    MIN_SCORE: int = 15
    # Best / second-best score ratio needed to accept. [tuned by eval] kept at 1.5: at
    # MIN_SCORE >= 10 ratios 1.0-1.5 give identical accuracy and FPR, while 2.0/3.0 only lose
    # accuracy (T5, T6); 1.5 keeps a guard against near-ties at no measured cost.
    MIN_RATIO: float = 1.5
    # Confidence curve scale: conf = (1 - exp(-score/SCORE_SCALE)) * (1 - 1/ratio). [tuned by eval]
    SCORE_SCALE: float = 30.0
    # Do not scan more than this many candidate songs (ranked by raw hits). [audfprint]
    # Matcher.search_depth = 100.
    SEARCH_DEPTH: int = 100


# --------------------------------------------------------------------------------------
# Runtime / service settings (environment-driven)
# --------------------------------------------------------------------------------------
def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("BLAZAM_DATA_DIR", BASE_DIR / "data")))
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("BLAZAM_DB_PATH", BASE_DIR / "data" / "blazam.sqlite3"))
    )
    audd_token: str = field(default_factory=lambda: os.getenv("AUDD_API_TOKEN", ""))
    acoustid_key: str = field(default_factory=lambda: os.getenv("ACOUSTID_API_KEY", ""))
    mock_external: bool = field(default_factory=lambda: _bool("MOCK_EXTERNAL", False))
    auto_learn: bool = field(default_factory=lambda: _bool("AUTO_LEARN", True))
    lyrics_enabled: bool = field(default_factory=lambda: _bool("FEATURE_LYRICS", True))
    acoustid_enabled: bool = field(default_factory=lambda: _bool("FEATURE_ACOUSTID", False))
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "BLAZAM_USER_AGENT", "Blazam/0.1.0 ( https://github.com/blazam/blazam )"
        )
    )
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()
        )
    )
    # optional regex for origins that change per deploy, e.g. Vercel preview URLs
    cors_origin_regex: str | None = field(default_factory=lambda: os.getenv("CORS_ORIGIN_REGEX") or None)
    http_timeout_s: float = 10.0
    http_retries: int = 3
    # Deezer preview URLs are signed and expire ~15 min after issue (observed; see README).
    download_concurrency: int = 4
    max_upload_bytes: int = 25 * 1024 * 1024
    # Max audio we fingerprint from a recognition query (seconds). [tuned by eval]
    max_query_seconds: float = 20.0


DSP = DSPConfig()
MATCH = MatchConfig()
SETTINGS = Settings()


def validate(dsp: DSPConfig = DSP) -> None:
    """Assert that the configured parameters fit the hash bit layout."""
    assert dsp.F_BITS * 2 + dsp.DT_BITS == 32, "hash must pack into exactly 32 bits"
    assert 0 <= dsp.F_MIN_BIN < dsp.F_MAX_BIN < (1 << dsp.F_BITS), "freq range must fit F_BITS"
    assert dsp.F_MAX_BIN <= dsp.N_FFT // 2, "freq range beyond Nyquist"
    assert 0 <= dsp.MIN_DT <= dsp.MAX_DT < (1 << dsp.DT_BITS), "dt range must fit DT_BITS"


validate()
