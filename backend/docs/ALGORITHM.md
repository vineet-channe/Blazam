# Blazam landmark fingerprinting: step-by-step mapping to the sources

Sources (read in full before any DSP code was written, 2026-09-29):

* **[Wang03]** A. Wang, *An Industrial-Strength Audio Search Algorithm*, ISMIR 2003.
  https://www.ee.columbia.edu/~dpwe/papers/Wang03-shazam.pdf
* **[Dejavu]** worldveil/dejavu @ master: `dejavu/config/settings.py`, `dejavu/logic/fingerprint.py`.
* **[audfprint]** dpwe/audfprint @ master: `audfprint_analyze.py`, `audfprint_match.py`, `hash_table.py`.

Every numeric parameter lives in `app/config.py`, which tags each one with its source or with
`[tuned by eval]`. Tuned values are justified only by `scripts/eval.py` runs logged in
`docs/TUNING.md`. **Indexing and querying run exactly the same code** (`fingerprint_signal`),
as Wang03 §2 requires ("Both 'database' and 'sample' audio files are subjected to the same
analysis").

| # | Step | Blazam code | Wang03 | Reference code |
|---|------|-------------|--------|----------------|
| 1 | Decode → mono float32 → 11 025 Hz | `app/dsp/audio.py` `load_audio` | §3.1 used 8 kHz mono (not prescriptive) | audfprint `Analyzer.target_sr = 11025`, `audio_read(..., channels=1)` |
| 2 | STFT, Hann, N_FFT 4096, hop 512, `10·log10(|X|²+eps)`, dB floor | `fingerprint.spectrogram_db` | §2.1 "spectrogram" (no parameters given) | Dejavu `DEFAULT_WINDOW_SIZE=4096`, `mlab.window_hanning`, `10*log10`; audfprint floors at `max/1e6` |
| 3 | Peaks = local max of neighbourhood ∧ above per-band threshold; ≤K per frame; restricted band | `fingerprint.find_peaks` | §2.1 "candidate peak if it has a higher energy content than all its neighbors in a region centered around the point… chosen according to a density criterion… according to amplitude" | Dejavu `maximum_filter(arr2D, footprint=iterate_structure(generate_binary_structure(2, 2), 10))`; audfprint `maxpksperframe = 5` |
| 4 | Pair anchor with ≤FAN_OUT later peaks in the target zone; hash = f1‖f2‖dt in uint32; store (hash, song, t1) | `fingerprint.make_hashes`, `pack_hash` | §2.2, Fig. 1C/1D "Hash:time = [f1:f2:Δt]:t1"; "packed into a 32-bit unsigned integer"; fan-out F=10 | audfprint `peaks2landmarks` (`mindt`, `targetdt`, `targetdf`, `maxpairsperpeak`); Dejavu `generate_hashes` (`fan_value`, `MIN/MAX_HASH_TIME_DELTA`, `PEAK_SORT`) |
| 5 | Look up hashes; per song histogram of δt = t_db − t_query; score = peak bin ± 1; accept on MIN_SCORE and ratio | `app/dsp/matcher.py` `match` | §2.3 "calculate a histogram of these δtk values and scan for a peak… The score of the match is the number of matching points in the histogram peak"; §2.3.1 threshold from the score distribution of incorrect tracks | audfprint `Matcher.window = 1`, `threshcount = 5`, `search_depth = 100`, `_unique_match_hashes` (distinct query hashes in the window) |

## Step details and deviations

**1. Decode.** WAV/FLAC/OGG are read with libsndfile. Everything else (webm/opus from the
browser, mp4/m4a, mp3) goes through `ffmpeg` to a native-rate float WAV. Down-mix (channel mean)
and resampling (`scipy.signal.resample_poly`, exact rational ratio, e.g. 147/640 for 48 kHz)
are then done in numpy for every format.

**2. Spectrogram.** Frames start at sample 0, with no centre padding. Signals shorter than one
window are zero-padded to one frame. Window = `numpy.hanning(4096)`, the symmetric Hann that
Dejavu's `mlab.window_hanning` uses. Power = |X|², log = `10·log10(power + 1e-10)`, then a
*relative* floor at (max − 120 dB), audfprint's 1e6 magnitude range. Resolution: 2.69 Hz/bin
and 46.4 ms/frame; the frame period equals Dejavu's (2048 samples at 44.1 kHz).

**3. Peaks.** `maximum_filter(size=(2·PEAK_NBHD_FREQ+1, 2·PEAK_NBHD_TIME+1), mode="constant",
cval=-inf)` over the restricted band [F_MIN_BIN, F_MAX_BIN]. A rectangle is what Dejavu's
`iterate_structure(generate_binary_structure(2, 2), n)` produces: I verified it yields an
all-True 21×21 array for n=10. `mode="constant", cval=-inf` makes the edge behaviour exactly
reproducible by the loop reference.

The per-band amplitude threshold is a spec requirement, not from the paper. There are
N_BANDS=6 log-spaced bands, and a bin must exceed the mean dB of its band *in the same frame*
by BAND_THRESH_DB. It is frame-local on purpose: a database song and a query see the same
threshold for the same audio, and it is exactly gain-invariant because a gain shifts every dB
value by a constant. This plays the role of Wang's "density criterion" and replaces Dejavu's
absolute `DEFAULT_AMP_MIN = 10` dB, which is not gain-invariant.

Finally, at most MAX_PEAKS_PER_FRAME = 5 peaks per frame are kept (audfprint), by amplitude with
ties to the lower frequency. The upper bin is 2047 so f fits 11 bits; Nyquist (bin 2048) is
discarded, as audfprint does.

**4. Hashes.** Peaks are sorted by (t, f) (Dejavu `PEAK_SORT=True`). For each anchor, later
peaks are visited in that order and the first FAN_OUT satisfying `MIN_DT ≤ t2−t1 ≤ MAX_DT` and
`|f2−f1| ≤ MAX_DF` are paired, like audfprint's `maxpairsperpeak` loop. The layout is
`hash = f1<<21 | f2<<10 | dt`, with asserts on all three ranges. Wang packs "[f1:f2:Δt]" into
32 bits. audfprint stores Δf instead of f2 because its f1 has only 8 bits; with 11-bit f2 we
store f2 directly, as the spec asks. (hash, song_id, t1) rows go into SQLite (INTEGER is
64-bit, so a uint32 needs no sign handling) and into a sorted in-memory numpy index
(Wang: "structs are sorted according to hash token value").

**5. Matching.** Query (hash, t_query) pairs are de-duplicated. Every hit gives
`delta = t_db − t_query`. Candidate songs are ranked by raw hit count (audfprint ranks by count
÷ song length; we use raw counts, which doesn't matter for equal-length 30 s previews) and at
most SEARCH_DEPTH=100 are scored. Per song, the 1-frame histogram peak is found (ties → the
smallest δ), and the score is the number of *distinct* query (hash, t_query) pairs whose δ lies
in [peak−1, peak+1]. That's the peak bin plus its two neighbours, and equals audfprint
`window=1` with `_unique_match_hashes`. `offset_seconds = delta·512/11025`.

Acceptance:

* `score ≥ MIN_SCORE` (Wang §2.3.1), and
* `best / max(second_best, 1) ≥ MIN_RATIO` (my addition, for the own-vs-external routing
  decision).

Both thresholds are `[tuned by eval]` (docs/TUNING.md), set from the distribution of scores of
incorrect / unindexed matches, as §2.3.1 prescribes.

**Confidence** is `conf = (1 − exp(−score / SCORE_SCALE)) · (1 − 1 / ratio)`, reported only for
accepted matches. It is non-decreasing in both score and ratio (checked by
`test_confidence_monotonic`) and lies in [0, 1): it is 0 when two songs tie and approaches 1 for
a dominant, well-supported match. It is a monotone *ranking* signal, **not a calibrated
probability**.

## Verification

* `tests/reference_impl.py` re-implements steps 3–5 with plain Python loops straight from the
  text above. `test_optimized_peaks_and_hashes_equal_reference` (5 signal types, including
  silence and a sub-window clip) and `test_optimized_match_equals_reference` assert identical
  peaks, identical ordered hash lists, and identical match decisions, scores, offsets and
  confidences.
* Figures: `docs/spectrogram_peaks.png` (Wang Fig. 1A/B), `docs/target_zone.png` (Fig. 1C),
  `docs/offset_histogram.png` (Figs. 2B/3B), from `scripts/make_plots.py` on synthetic audio.
