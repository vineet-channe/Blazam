"""Step 1 of the pipeline: decode any supported container to mono float32 @ DSP.SAMPLE_RATE.

Decoding strategy (deterministic per input format):

* WAV / FLAC / OGG / AIFF are read directly with ``soundfile`` (libsndfile).
* Everything else (webm/opus, mp4/m4a/aac, mp3, ...) is decoded by ``ffmpeg`` to a temporary
  32-bit float WAV at the *native* sample rate and channel count, then read with ``soundfile``.

Channel down-mix (mean) and resampling (``scipy.signal.resample_poly``) always happen here in
numpy, so indexing and querying share exactly one code path after the container decoder.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from app.config import DSP

SOUNDFILE_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif"}
SUPPORTED_EXTS = SOUNDFILE_EXTS | {".mp3", ".webm", ".opus", ".mp4", ".m4a", ".aac", ".mka", ".mkv", ".oga"}


class AudioDecodeError(RuntimeError):
    """Raised when an input cannot be decoded to audio."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffmpeg_to_wav(src: Path, dst: Path) -> None:
    if not ffmpeg_available():
        raise AudioDecodeError("ffmpeg is not installed; cannot decode this format")
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-map", "0:a:0", "-vn", "-c:a", "pcm_f32le", "-f", "wav", str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise AudioDecodeError(f"ffmpeg failed: {msg[-1] if msg else 'unknown error'}")


def read_native(path: str | Path) -> tuple[np.ndarray, int]:
    """Decode a file to a float32 array of shape (n_samples, n_channels) at its native rate."""
    path = Path(path)
    if path.suffix.lower() in SOUNDFILE_EXTS:
        try:
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return data, int(sr)
        except Exception:  # noqa: BLE001 - fall through to ffmpeg (e.g. odd WAV subtypes)
            pass
    with tempfile.TemporaryDirectory(prefix="blazam_dec_") as td:
        tmp = Path(td) / "decoded.wav"
        _ffmpeg_to_wav(path, tmp)
        try:
            data, sr = sf.read(str(tmp), dtype="float32", always_2d=True)
        except Exception as e:  # noqa: BLE001
            raise AudioDecodeError(f"could not read decoded audio: {e}") from e
    return data, int(sr)


def to_mono_resampled(data: np.ndarray, sr: int, target_sr: int = DSP.SAMPLE_RATE) -> np.ndarray:
    """Down-mix (channel mean) and resample to ``target_sr`` with a polyphase filter.

    Args:
        data: array (n_samples,) or (n_samples, n_channels).
        sr: input sample rate in Hz.
        target_sr: output sample rate in Hz.

    Returns:
        1-D float32 array at ``target_sr``.
    """
    x = np.asarray(data, dtype=np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    if sr != target_sr:
        g = math.gcd(int(sr), int(target_sr))
        x = resample_poly(x, target_sr // g, sr // g)
    return np.ascontiguousarray(x, dtype=np.float32)


def load_audio(path: str | Path, max_seconds: float | None = None) -> np.ndarray:
    """Full step 1: decode ``path`` -> mono float32 @ DSP.SAMPLE_RATE.

    Args:
        path: audio file path (any supported container).
        max_seconds: optionally truncate the *decoded* signal to this many seconds.
    """
    data, sr = read_native(path)
    if data.size == 0:
        raise AudioDecodeError("decoded audio is empty")
    if max_seconds is not None:
        data = data[: int(max_seconds * sr)]
    return to_mono_resampled(data, sr)


def load_audio_bytes(blob: bytes, filename: str = "upload", max_seconds: float | None = None) -> np.ndarray:
    """Decode an in-memory upload. The original extension (if any) selects the decoder."""
    suffix = Path(filename).suffix.lower() or ".bin"
    with tempfile.TemporaryDirectory(prefix="blazam_up_") as td:
        p = Path(td) / f"in{suffix}"
        p.write_bytes(blob)
        return load_audio(p, max_seconds=max_seconds)
