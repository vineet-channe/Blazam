# Blazam backend: status (2026-09-30, end of session 2)

**All items pending after session 1 are done.** The requirements checklist in
[`README.md`](../README.md#requirements-checklist) shows 67 PASS, 3 PARTIAL, 0 FAIL, with
evidence for each. Final `.venv/bin/pytest`: **87 passed, 0 failed.**

## Session 2 summary

| item | result |
|---|---|
| Adopt tuned DSP params (`BAND_THRESH_DB=10`, `FAN_OUT=15`, `MAX_DT=48`) | applied; `fp_version 8523f7fd9559`; 363 songs reindexed (9 min), 0 missing audio |
| Thresholds for the final config (T6) | MIN_SCORE 12 → **15**, MIN_RATIO 1.5 kept. Chance max 11 over 462 true negatives, 0 FP, required conditions 100% (`docs/TUNING.md` T6) |
| Label artifact found in eval | two Deezer entries for *Girls Just Want(a) to Have Fun* hold the same audio. Excluded from the chance statistics and documented; audio de-duplication listed as future work |
| 500-song latency | fingerprint+match p50 31 ms / max 155 ms at 500 songs; end-to-end `/api/recognize` (20 real webm uploads) p50 165 ms / max 409 ms at 545 songs |
| Startup | index snapshot added: 22 s (SQLite scan) → 0.18 s |
| CLIs run for real | `app.index` (nested dir, 3 formats, re-run skips) and `app.match` (hit, unknown, bad file) |
| Gaps closed | m4a/mp4 decode test (6 containers); iTunes wired in as preview fallback (40 of 43 preview-less tracks recovered); enrichment fills the year from Deezer `/track`; compose env passthrough fixed; audio paths stored relative to the data dir (host ↔ container) |
| Docker | `docker compose build` + `up` against the real library: health, webm recognition, CORS, env passthrough, 585/585 paths resolved in-container |
| README | architecture (Mermaid), API, algorithm, eval, tuning, APIs + limits, doc-vs-reality, future work, checklist |

## Library on disk

`data/blazam.sqlite3`: **585 songs**, 9 191 889 hashes, one fingerprint version (no stale
songs). All 585 have a year, 485 have MBIDs and 484 have lyrics. 40 songs use iTunes previews
(`*.itunes.m4a`). Index snapshot: `data/blazam.index.npz`, rebuilt automatically when the DB
changes.

## After session 2 (frontend-readiness fixes)

* **Previews no longer expire.** `GET /api/songs/{id}/preview` serves the indexed audio
  (supports Range). `preview_url` in recognize/library/history responses points to it for
  library songs, replacing stored Deezer links that expire ~15 min after issue.
* **Years filled.** `python -m app.index --enrich-missing` gave all 585 songs a year (was 488).
  MBIDs stay at 485: the other 100 aren't findable on MusicBrainz.
* Known leftover: a history entry for an *external* match recorded before its auto-learn
  finished keeps the Deezer URL from that moment, which expires ~15 min later.

## Remaining (all PARTIAL in the checklist, none blocking)

1. **Tier-2 enrichment in the immediate response.** MusicBrainz/CAA/lyrics arrive only after
   auto-learn. The option is a small time budget (e.g. 300 ms) for MB/CAA before responding.
2. **Postgres.** The schema uses portable types but has never been executed on Postgres.
3. **AcoustID comparison view.** The client and tests exist; there's no endpoint, and `fpcalc`
   isn't installed.

Worth doing next (see README → Future improvements): audio-level library de-duplication, faster
bulk (re)indexing, and recorded room noise in the eval.

## Commands

```bash
cd /Users/vineetchanne/Desktop/Projects/Blazam/backend
.venv/bin/pytest                                         # 87 passed
.venv/bin/uvicorn app.main:app --port 8000               # or: docker compose up --build
.venv/bin/python -m app.match clip.wav
.venv/bin/python scripts/eval.py --stress                # re-run the evaluation
```
