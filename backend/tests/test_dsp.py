"""DSP / matching correctness tests (requirements 7a-7h + reference equivalence)."""

from __future__ import annotations

import numpy as np
import pytest

from app.config import DSP, MATCH
from app.dsp.fingerprint import (
    fingerprint_signal,
    find_peaks,
    make_hashes,
    pack_hash,
    spectrogram_db,
    unpack_hash,
)
from app.dsp.index import HashIndex
from app.dsp.matcher import confidence, match
from tests.reference_impl import ref_find_peaks, ref_make_hashes, ref_match
from tests.synth import SR, add_noise, make_song

FRAME_S = DSP.HOP / DSP.SAMPLE_RATE

SONG_SPECS = {
    1: dict(seed=1),
    2: dict(seed=2),
    3: dict(seed=3),
    4: dict(seed=4),
    5: dict(seed=1, transpose=1.0),  # similar: song 1 up one semitone
    6: dict(seed=1, melody_seed=77),  # similar: song 1's rhythm/timbre, different notes
}


@pytest.fixture(scope="module")
def library() -> tuple[HashIndex, dict[int, np.ndarray]]:
    songs = {sid: make_song(duration=30.0, **spec) for sid, spec in SONG_SPECS.items()}
    idx = HashIndex()
    for sid, x in songs.items():
        fp = fingerprint_signal(x)
        idx.add_song(sid, fp.hashes, fp.offsets)
    idx.compact()
    return idx, songs


def _clip(x: np.ndarray, start_s: float, dur_s: float) -> np.ndarray:
    a = int(round(start_s * SR))
    return x[a : a + int(dur_s * SR)]


# --------------------------------------------------------------------------- 7a
def test_exact_slice_correct_song_and_offset(library):
    idx, songs = library
    start = 7.3
    r = match(fingerprint_signal(_clip(songs[3], start, 5.0)), idx)
    assert r.matched and r.song_id == 3
    assert abs(r.offset_seconds - start) <= FRAME_S, (r.offset_seconds, start)


# --------------------------------------------------------------------------- 7b
def test_twenty_random_offsets(library):
    idx, songs = library
    rng = np.random.default_rng(1234)
    for _ in range(20):
        sid = int(rng.choice(list(songs)))
        start = float(rng.uniform(0.0, 24.0))
        r = match(fingerprint_signal(_clip(songs[sid], start, 5.0)), idx)
        assert r.matched and r.song_id == sid, (sid, start, r)
        assert abs(r.offset_seconds - start) <= FRAME_S, (sid, start, r.offset_seconds)


# --------------------------------------------------------------------------- 7c
@pytest.mark.parametrize("gain", [0.3, 2.0])
def test_volume_invariance(library, gain):
    idx, songs = library
    clip = _clip(songs[2], 11.0, 5.0)
    base = match(fingerprint_signal(clip), idx)
    scaled = match(fingerprint_signal(clip * gain), idx)
    assert scaled.matched and scaled.song_id == base.song_id == 2
    assert scaled.offset_frames == base.offset_frames
    assert abs(scaled.score - base.score) <= max(2, 0.02 * base.score)


# --------------------------------------------------------------------------- 7d
def test_noise_degrades_gracefully(library, capsys):
    idx, songs = library
    levels = [20, 10, 5, 0]
    rng = np.random.default_rng(7)
    trials = [(int(rng.choice([1, 2, 3, 4])), float(rng.uniform(0, 24))) for _ in range(10)]
    report = {}
    for snr in levels:
        scores, correct = [], 0
        for k, (sid, start) in enumerate(trials):
            noisy = add_noise(_clip(songs[sid], start, 5.0), snr, seed=k)
            r = match(fingerprint_signal(noisy), idx)
            scores.append(r.score)
            correct += int(r.matched and r.song_id == sid)
        report[snr] = (float(np.median(scores)), correct / len(trials))
    with capsys.disabled():
        print("\n[7d] SNR dB | median score | top-1 accuracy (10 x 5 s clips)")
        for snr in levels:
            print(f"      {snr:>5} | {report[snr][0]:>12.1f} | {report[snr][1]:.0%}")
    med = [report[s][0] for s in levels]
    assert all(a >= b for a, b in zip(med, med[1:])), "median score must not increase as SNR drops"
    assert report[20][1] == 1.0 and report[10][1] >= 0.9


# --------------------------------------------------------------------------- 7e
@pytest.mark.parametrize("kind", ["white_noise", "silence", "unindexed_song"])
def test_negative_controls(library, kind):
    idx, _ = library
    n = int(5.0 * SR)
    if kind == "white_noise":
        x = np.random.default_rng(3).standard_normal(n).astype(np.float32) * 0.3
    elif kind == "silence":
        x = np.zeros(n, np.float32)
    else:
        x = _clip(make_song(seed=99, duration=30.0), 10.0, 5.0)
    r = match(fingerprint_signal(x), idx)
    assert r.score < MATCH.MIN_SCORE, r
    assert not r.matched


# --------------------------------------------------------------------------- 7f
@pytest.mark.parametrize("sid", [1, 5, 6])
def test_similar_songs_not_confused(library, sid):
    idx, songs = library
    for start in (3.0, 14.5):
        r = match(fingerprint_signal(_clip(songs[sid], start, 5.0)), idx)
        assert r.matched and r.song_id == sid, (sid, start, r.candidates)


# --------------------------------------------------------------------------- 7g
def test_same_input_identical_hashes():
    x = make_song(seed=11, duration=10.0)
    a, b = fingerprint_signal(x), fingerprint_signal(x.copy())
    assert np.array_equal(a.hashes, b.hashes) and np.array_equal(a.offsets, b.offsets)
    assert np.array_equal(a.peaks, b.peaks)


def test_same_file_identical_hashes(tmp_path):
    import soundfile as sf

    from app.dsp.audio import load_audio

    p = tmp_path / "s.wav"
    sf.write(p, make_song(seed=12, duration=8.0), SR, subtype="FLOAT")
    a, b = fingerprint_signal(load_audio(p)), fingerprint_signal(load_audio(p))
    assert np.array_equal(a.hashes, b.hashes) and np.array_equal(a.offsets, b.offsets)


# --------------------------------------------------------------------------- 7h
@pytest.mark.parametrize(
    "f1,f2,dt",
    [(0, 0, 0), (2047, 2047, 1023), (2047, 0, 0), (0, 2047, 0), (0, 0, 1023), (1024, 1023, 512), (1, 2, 3)],
)
def test_hash_pack_roundtrip(f1, f2, dt):
    h = pack_hash(f1, f2, dt)
    assert h.dtype == np.uint32
    assert tuple(int(v) for v in unpack_hash(h)) == (f1, f2, dt)


def test_hash_boundaries_are_distinct_and_max():
    assert int(pack_hash(2047, 2047, 1023)) == 0xFFFFFFFF
    assert int(pack_hash(0, 0, 0)) == 0


@pytest.mark.parametrize("f1,f2,dt", [(2048, 0, 0), (0, 2048, 0), (0, 0, 1024), (-1, 0, 0), (0, 0, -1)])
def test_hash_pack_rejects_out_of_range(f1, f2, dt):
    with pytest.raises(AssertionError):
        pack_hash(f1, f2, dt)


# --------------------------------------------------------- reference equivalence (7, ref impl)
@pytest.mark.parametrize(
    "signal",
    ["song", "noisy_song", "white_noise", "silence", "short"],
)
def test_optimized_peaks_and_hashes_equal_reference(signal):
    rng = np.random.default_rng(5)
    if signal == "song":
        x = make_song(seed=21, duration=4.0)
    elif signal == "noisy_song":
        x = add_noise(make_song(seed=22, duration=4.0), 5.0, seed=1)
    elif signal == "white_noise":
        x = rng.standard_normal(int(3 * SR)).astype(np.float32)
    elif signal == "silence":
        x = np.zeros(int(2 * SR), np.float32)
    else:
        x = make_song(seed=23, duration=0.2)  # shorter than one FFT window
    S = spectrogram_db(x)
    peaks = find_peaks(S)
    ref_peaks = ref_find_peaks(S)
    assert [tuple(map(int, p)) for p in peaks] == ref_peaks
    h, t = make_hashes(peaks)
    assert list(zip(h.tolist(), t.tolist())) == ref_make_hashes(ref_peaks)


def test_optimized_match_equals_reference():
    songs = {sid: make_song(seed=sid, duration=8.0) for sid in (31, 32, 33)}
    songs[34] = make_song(seed=31, duration=8.0, transpose=1.0)
    db, idx = {}, HashIndex()
    for sid, x in songs.items():
        fp = fingerprint_signal(x)
        db[sid] = list(zip(fp.hashes.tolist(), fp.offsets.tolist()))
        idx.add_song(sid, fp.hashes, fp.offsets)
    queries = [
        _clip(songs[32], 2.1, 4.0),
        _clip(songs[34], 1.0, 4.0),
        add_noise(_clip(songs[31], 3.3, 4.0), 3.0, seed=2),
        np.random.default_rng(0).standard_normal(4 * SR).astype(np.float32),
    ]
    for q in queries:
        fp = fingerprint_signal(q)
        got = match(fp, idx)
        ref = ref_match(list(zip(fp.hashes.tolist(), fp.offsets.tolist())), db)
        assert got.matched == ref["matched"]
        assert got.song_id == ref["song_id"]
        assert got.score == ref["score"] and got.second_score == ref["second"]
        if ref["score"]:
            assert got.offset_frames == ref["delta"]
        if got.matched:
            assert got.confidence == pytest.approx(ref["confidence"])


# --------------------------------------------------------------------------- misc
def test_confidence_monotonic():
    grid = [(s, r) for s in range(0, 200, 7) for r in (1.0, 1.2, 1.5, 2, 3, 10)]
    for s, r in grid:
        c = confidence(s, r)
        assert 0.0 <= c <= 1.0
        assert confidence(s + 1, r) >= c and confidence(s, r * 1.1) >= c


def test_index_remove_and_compact(library):
    _, songs = library
    idx = HashIndex()
    for sid in (1, 2):
        fp = fingerprint_signal(songs[sid])
        idx.add_song(sid, fp.hashes, fp.offsets)
    idx.remove_song(1)
    r = match(fingerprint_signal(_clip(songs[1], 5.0, 5.0)), idx)
    assert r.song_id != 1
    idx.compact()
    assert idx.song_ids() == [2]


# --------------------------------------------------------------------------- decoding (spec §2)
@pytest.mark.parametrize(
    "ext,codec",
    [("wav", None), ("flac", None), ("mp3", "libmp3lame"), ("webm", "libopus"), ("m4a", "aac"), ("mp4", "aac")],
)
def test_every_supported_container_decodes_and_matches(library, tmp_path, ext, codec):
    import subprocess

    import soundfile as sf

    from app.dsp.audio import load_audio

    idx, songs = library
    src = tmp_path / "src.wav"
    sf.write(src, _clip(songs[4], 6.0, 7.0), SR, subtype="FLOAT")
    dst = tmp_path / f"clip.{ext}"
    if codec is None:
        sf.write(dst, _clip(songs[4], 6.0, 7.0), SR, subtype="PCM_16")
    else:
        # encode at 48 kHz stereo like a browser/phone would, to exercise down-mix + resampling
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-ar", "48000", "-ac", "2",
                        "-c:a", codec, str(dst)], check=True)
    x = load_audio(dst)
    assert x.dtype == np.float32 and x.ndim == 1
    assert abs(x.size / DSP.SAMPLE_RATE - 7.0) < 0.1  # codec padding stays small
    r = match(fingerprint_signal(x), idx)
    assert r.matched and r.song_id == 4
    assert abs(r.offset_seconds - 6.0) <= 2 * FRAME_S  # lossy codecs add a few ms of encoder delay
