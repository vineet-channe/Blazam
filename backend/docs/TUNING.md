# Tuning log

Rules: parameters marked `[tuned by eval]` in `app/config.py` change **only** on evidence from
`scripts/eval.py`. Every run's full JSON (config, every query record, threshold sweep) is saved
under `docs/eval_results/` (committed: song ids and scores only, no audio). The library is the real Deezer
library in `data/` (30 s previews). 15% of songs are held out and never indexed; their clips
serve as "unindexed song" negatives. Within a round every configuration sees the *same* clips
(same `--seed`), so within-round comparisons are paired.

**Noise caveat.** With 40–60 clips per cell, one clip moves a cell by 1.7–2.5 points.
Rounds 1 and 2 used different seeds, and the same configuration (band 10, fan 10) scored 85%
vs 68% on "5 s @ −10 dB" across them. So only same-round comparisons are meaningful, and I
only adopt changes that are consistent across several cells. Latency in rounds 1–2 was polluted
by a concurrent `docker build` and seeding, so it is not used for decisions there.

"Required" = the spec's conditions (clean, 20/10/5/0 dB white noise, gain ×0.3/×2.0, MP3
64 kbit/s). "Stress" = extra conditions used only to discriminate between configs (−5/−10 dB
white noise, a held-out song mixed in at 0 dB, MP3 32 kbit/s).

## T0: baseline (sourced starting values)

`PEAK_NBHD_FREQ=10, BAND_THRESH_DB=6, FAN_OUT=10, MAX_DT=32, MAX_DF=248, MIN_SCORE=5 (audfprint threshcount), MIN_RATIO=1.5`

300-song library (255 indexed / 45 held out), 40 clips per (duration, condition), seed 2026
(`20260929-154650-t0-baseline.json`):

| metric | value |
|---|---|
| required-condition top-1 | 99.8% (only miss: one 5 s clip at 0 dB) |
| stress top-1 | 97.5% (5 s @ −10 dB: 82.5%) |
| wrong accepts | 0 |
| **FPR (unindexed songs)** | **5.8%** (max negative score 8) |
| hashes / song | 12 822 |

The low audfprint threshold (5) is the problem: chance alignments with an unindexed song
reach 8. Held until the DSP parameters are settled (T5).

## T1: peak-neighbourhood frequency half-width (seed 2026, paired with T0)

Our bins are 4× narrower in Hz than Dejavu's, so "Dejavu-equivalent in Hz" would be ~40 bins.

| PEAK_NBHD_FREQ | hashes/song | 5 s @ −10 dB | 10 s @ −10 dB | 5 s mix 0 dB | stress top-1 |
|---|---|---|---|---|---|
| 5 | 17 606 | 82% | 100% | 100% | 97.8% |
| **10 (T0)** | 12 822 | 82% | 98% | 100% | 97.5% |
| 20 | 7 887 | 65% | 98% | 98% | 95.0% |
| 40 | 3 178 | 55% | 85% | 90% | 88.1% |

**Decision: keep 10.** Wider neighbourhoods remove too many peaks, and robustness drops
monotonically. 5 is no better than 10 but costs +37% storage.

## T2: fan-out (seed 2026, paired with T0)

| FAN_OUT | hashes/song | 5 s @ −10 dB | 10 s @ −10 dB | stress top-1 | max negative score |
|---|---|---|---|---|---|
| 5 | 6 678 | 48% | 95% | 92.8% | 7 |
| **10 (T0)** | 12 822 | 82% | 98% | 97.5% | 8 |
| 15 | 17 747 | 92% | 100% | 99.1% | 9 |

This matches Wang §2.2's trade-off: more pairs per anchor means more surviving hashes under
noise, at a linear storage cost and slightly higher chance scores. **Candidate: 15**, retested
in T4 with T3's lower hash count.

## T3: per-band threshold margin (seed 2026, paired with T0)

| BAND_THRESH_DB | hashes/song | 5 s @ −10 dB | 10 s @ −10 dB | stress top-1 |
|---|---|---|---|---|
| 3 | 13 293 | 85% | 98% | 97.8% |
| **6 (T0)** | 12 822 | 82% | 98% | 97.5% |
| 10 | 10 457 | 85% | 100% | 98.1% |

**Adopted in session 2: 10** (see "DSP changes adopted"). It gives −18% hashes with robustness no worse in any cell, because it drops
weak peaks that would not survive noise anyway.

## T4: combinations (seed 7, 60 clips/cell, 90 unindexed negatives/duration)

| config (all with BAND_THRESH_DB=10) | hashes/song | 5 s @ −10 dB | 10 s @ −10 dB | stress top-1 | max neg. score |
|---|---|---|---|---|---|
| FAN_OUT 10, MAX_DT 32 | 10 523 | 68% | 93% | 95.0% | 9 |
| FAN_OUT 15, MAX_DT 32 | 14 086 | 77% | 95% | 96.5% | 10 |
| **FAN_OUT 15, MAX_DT 48** | 15 886 | 80% | 98% | 97.3% | 10 |
| FAN_OUT 15, MAX_DT 32, MAX_DF 124 | 8 334 | 68% | 92% | 94.8% | 10 |

All four configs scored 100% top-1 on the required conditions with 0 wrong accepts.
**Adopted in session 2: FAN_OUT=15, MAX_DT=48 (MAX_DF stays 248).** It gains in both hard cells in a paired
comparison. The storage cost is +24% over T0 (15.9k vs 12.8k hashes per 30 s preview).

## DSP changes adopted (session 2, 2026-09-30)

Recommended at the end of session 1 and applied at the start of session 2:

| parameter | T0 | final | evidence |
|---|---|---|---|
| BAND_THRESH_DB | 6.0 | **10.0** | T3, T4 |
| FAN_OUT | 10 | **15** | T2, T4 |
| MAX_DT | 32 | **48** | T4 |
| PEAK_NBHD_FREQ | 10 | 10 (no change) | T1 |
| MAX_DF | 248 | 248 (no change) | T4 |

New `fp_version` = `8523f7fd9559`. `python -m app.index --reindex` re-fingerprinted the 363
songs on the old version (0 missing audio). It took 9 min, dominated by SQLite delete+insert
into the indexed `hashes` table. The other 102 songs were already on this version. Library
after reindex: 465 songs, 7 403 123 hashes, 370 MB SQLite file. Tests after the change:
73 passed.

## T5: acceptance thresholds (APPLIED; thresholds don't affect stored hashes)

Data: every negative query (unindexed songs, white noise, silence) from runs with the
**current** DSP config, i.e. T0 (255-song index, 142 negatives) and an earlier smoke run on the
first 100 seeded songs (85 indexed, 72 negatives). Per Wang §2.3.1, the threshold comes from
the score distribution of incorrect matches.

Chance-score histogram over the 142 T0 negatives: 0:2, 2:2, 3:47, 4:34, 5:36, 6:17, 7:3, 8:1.
Maximum 8 in both runs (214 negatives). The lowest *correct* required-condition score was 7
(one 5 s clip at 0 dB); the 1st percentile was 32.

From the T0 records (threshold sweep, same queries):

| MIN_SCORE | MIN_RATIO | required top-1 | stress top-1 | FPR (all negatives) |
|---|---|---|---|---|
| 5 (before) | 1.5 | 99.8% | 97.5% | **4.93%** (unindexed only: 5.8%) |
| 10 | 1.5 | 99.8% | 92.8% | 0.00% |
| **12 (after)** | **1.5** | **99.8%** | **90.9%** | **0.00%** |
| 12 | 2.0 | 99.8% | 90.9% | 0.00% |
| 15 | 2.0 | 99.7% | 88.1% | 0.00% |
| 20 | 2.0 | 99.4% | 82.2% | 0.00% |

**Decision: MIN_SCORE 5 → 12. MIN_RATIO stays 1.5.** 12 is 1.5× the observed chance maximum.
That margin covers the maximum growing with library size (more songs, more chances) and the
pending FAN_OUT=15 config, whose chance maximum was 10 in T4. The sweep doesn't support
changing MIN_RATIO: at MIN_SCORE ≥ 10, ratios 1.0–2.0 give identical accuracy and FPR on this
data, and 3.0 only loses stress accuracy (92.8% → 92.5% at MIN_SCORE 10). *(Corrected in
session 2: session 1 said "no ratio value" changes anything, which overstated it for 3.0.)* The
cost is 6.6 points of stress-condition top-1 (very noisy clips). Those clips now fall through
to AudD instead of being answered by Tier 1, which is the intended own/external split.
Required-condition accuracy is unchanged.

Caveat: 0.00% FPR on 214 negatives bounds the true rate at roughly ≤1.4% (95% upper bound,
rule of three), not zero. A larger negative set is part of the pending work.

## T6: final DSP config, thresholds re-derived (session 2)

465-song library (395 indexed / 70 held out), 60 clips per (duration, condition), 200
unindexed-song negatives per duration + 66 white-noise + 2 silence, seed 99
(`20260930-092703-t6-final.json`), run at MIN_SCORE=12.

**Label artifact found.** Six "unindexed" negatives scored 538–1050. All six were clips of
*Cyndi Lauper – Girls Just Wanna Have Fun* (ISRC USSM18300231, held out), matched to *Girls
Just Want to Have Fun* (ISRC USSM18300548, indexed): two Deezer entries whose audio the
matcher shows is identical, since scores that high are impossible by chance. The engine was
right and the ground-truth label was wrong, the situation Wang §3.3 describes for re-releases
and samples. These six queries are excluded from the chance-score statistics below and counted
separately. Fixing this properly means de-duplicating the library by audio (future work in the
README).

Chance scores over the **462 true negatives**: 0:2, 1:3, 2:15, 3:120, 4:59, 5:91, 6:102, 7:31,
8:22, 9:9, 10:5, 11:3. **Max 11**, p99 10. It is higher than T0's 8, as T4 predicted:
FAN_OUT=15 gives more hashes per query, hence more chance collisions, and the index is larger.

| MIN_SCORE (MIN_RATIO 1.5) | FP / 462 true negatives | required top-1 | stress top-1 |
|---|---|---|---|
| 8 | 13 | 100.0% | 96.5% |
| 10 | 4 | 100.0% | 95.0% |
| 12 (T5 value) | 0 | 100.0% | 93.8% |
| **15 (final)** | **0** | **100.0%** | **91.0%** |
| 20 | 0 | 100.0% | 86.7% |

**Decision: MIN_SCORE 12 → 15; MIN_RATIO stays 1.5.**
* 12 now sits just 1 above the observed chance maximum. The tail roughly halves per score step
  (22 → 9 → 5 → 3 for scores 8 → 11). Extrapolating, ≥12 would pass ≈0.3% of unknown clips and
  ≥15 ≈0.04%. That matches the 0.1% target Wang §2.3.1 gives as an example. This is an
  extrapolation, not a measurement: 0/462 only bounds the measured FPR at ≤0.65% (rule of three).
* Required-condition accuracy is unaffected: the lowest correct score on a required condition
  was 22.
* Cost: stress top-1 93.8% → 91.0%. Those clips route to AudD (Tier 2).
* Ratio: in the T6 sweep, ratios 1.0/1.25/1.5 are identical at MIN_SCORE 12 and 15, while 2.0
  and 3.0 lower required top-1 to 99.8% and 99.5%. 1.5 stays.

### Final numbers (T6 records re-scored at MIN_SCORE=15, MIN_RATIO=1.5)

| clip | condition | top-1 (n=60) | wrong accept | median score |
|---|---|---|---|---|
| 5 s | clean / 20 / 10 / 5 / 0 dB | 100 / 100 / 100 / 100 / 100% | 0 | 954 / 705 / 346 / 234 / 126 |
| 5 s | gain ×0.3 / ×2.0 / MP3 64k | 100 / 100 / 100% | 0 | 1083 / 691 / 956 |
| 10 s | clean / 20 / 10 / 5 / 0 dB | 100 / 100 / 100 / 100 / 100% | 0 | 2508 / 1691 / 830 / 508 / 258 |
| 10 s | gain ×0.3 / ×2.0 / MP3 64k | 100 / 100 / 100% | 0 | 2868 / 1713 / 2191 |
| stress (both lengths, 480 clips) | −5 / −10 dB, mix 0 dB, MP3 32k | 91.0% overall | 0 | — |

Offsets were within ±1.5 frames of the true start in ≥98% of accepted clips in every cell.
Fingerprint + match latency on 395 songs: p50 30.8 ms, p95 42.7 ms.
