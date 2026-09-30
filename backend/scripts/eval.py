"""Evaluation + tuning harness (the ONLY tool used to change tuned parameters; see docs/TUNING.md).

    python scripts/eval.py                                   # current config, default protocol
    python scripts/eval.py --set PEAK_NBHD_FREQ=20 --set FAN_OUT=5 --tag nbhd20
    python scripts/eval.py --library-size 500 --latency-only

Protocol
--------
* Library: songs in data/blazam.sqlite3 that have an audio file (Deezer 30 s previews).
  A deterministic ``--holdout`` fraction is NOT indexed; clips from those songs are negatives
  ("unindexed song"), alongside white noise and digital silence.
* Positives: random 5 s and 10 s clips (random start) of indexed songs under conditions
  clean, white noise at 20/10/5/0 dB SNR, gain x0.3 / x2.0 (x2.0 is clipped to [-1, 1], as a
  real file would be), and an MP3 round trip at 64 kbit/s (ffmpeg libmp3lame).
* Metrics: top-1 accuracy (accepted AND correct), wrong-accept rate, false-positive rate on
  negatives, and per-query latency (fingerprint + match; decode excluded) with
  p50/p95, all with the given thresholds. A threshold sweep over (MIN_SCORE, MIN_RATIO) is
  also reported.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DSP, MATCH, DSPConfig, MatchConfig  # noqa: E402
from app.db import Database  # noqa: E402
from app.dsp.audio import load_audio  # noqa: E402
from app.dsp.fingerprint import fingerprint_signal  # noqa: E402
from app.dsp.index import HashIndex  # noqa: E402
from app.engine import resolve_audio_path  # noqa: E402
from app.dsp.matcher import match  # noqa: E402

SR = DSP.SAMPLE_RATE
# required by the spec
CONDITIONS = ["clean", "snr20", "snr10", "snr5", "snr0", "gain0.3", "gain2.0", "mp3_64k"]
# extra stress conditions used to discriminate between parameter sets during tuning:
# harsher white noise, music-over-music interference from a held-out song at 0 dB, low-rate MP3
STRESS = ["snr-5", "snr-10", "mix0", "mp3_32k"]
INTERFERERS: list[np.ndarray] = []


def parse_overrides(items: list[str]) -> tuple[DSPConfig, MatchConfig]:
    dsp_kw, match_kw = {}, {}
    dsp_fields = {f.name: f.type for f in dataclasses.fields(DSPConfig)}
    match_fields = {f.name: f.type for f in dataclasses.fields(MatchConfig)}
    for it in items:
        k, v = it.split("=", 1)
        if k in dsp_fields:
            dsp_kw[k] = type(getattr(DSP, k))(v)
        elif k in match_fields:
            match_kw[k] = type(getattr(MATCH, k))(v)
        else:
            raise SystemExit(f"unknown parameter {k}")
    return dataclasses.replace(DSP, **dsp_kw), dataclasses.replace(MATCH, **match_kw)


def _decode(path: str) -> np.ndarray:
    return load_audio(path)


def _fp(args: tuple[np.ndarray, DSPConfig]):
    x, cfg = args
    fp = fingerprint_signal(x, cfg)
    return fp.hashes, fp.offsets


def add_noise(x: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    p = float(np.mean(x.astype(np.float64) ** 2)) + 1e-12
    n = rng.standard_normal(x.size)
    n *= np.sqrt(p / 10 ** (snr_db / 10) / np.mean(n**2))
    return (x + n).astype(np.float32)


def mix_with(x: np.ndarray, other: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    start = int(rng.integers(0, max(1, other.size - x.size)))
    o = other[start : start + x.size].astype(np.float64)
    if o.size < x.size:
        o = np.pad(o, (0, x.size - o.size))
    p_x, p_o = float(np.mean(x.astype(np.float64) ** 2)) + 1e-12, float(np.mean(o**2)) + 1e-12
    return (x + o * np.sqrt(p_x / p_o / 10 ** (snr_db / 10))).astype(np.float32)


def mp3_roundtrip(x: np.ndarray, kbps: int = 64) -> np.ndarray:
    import soundfile as sf

    with tempfile.TemporaryDirectory() as td:
        w, m = Path(td) / "c.wav", Path(td) / "c.mp3"
        sf.write(w, x, SR, subtype="FLOAT")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(w), "-c:a", "libmp3lame",
                        "-b:a", f"{kbps}k", str(m)], check=True)
        return load_audio(m)


def degrade(x: np.ndarray, cond: str, rng: np.random.Generator) -> np.ndarray:
    if cond == "clean":
        return x
    if cond.startswith("snr"):
        return add_noise(x, float(cond[3:]), rng)
    if cond.startswith("gain"):
        return np.clip(x * float(cond[4:]), -1.0, 1.0).astype(np.float32)
    if cond.startswith("mp3_"):
        return mp3_roundtrip(x, int(cond[4:-1]))
    if cond.startswith("mix"):
        return mix_with(x, INTERFERERS[int(rng.integers(0, len(INTERFERERS)))], float(cond[3:]), rng)
    raise ValueError(cond)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "blazam.sqlite3"))
    ap.add_argument("--set", action="append", default=[], help="override a config parameter, e.g. FAN_OUT=5")
    ap.add_argument("--clips", type=int, default=60, help="positive clips per (duration, condition)")
    ap.add_argument("--negatives", type=int, default=60, help="unindexed-song negative clips per duration")
    ap.add_argument("--holdout", type=float, default=0.15)
    ap.add_argument("--library-size", type=int, default=0, help="limit number of songs considered (0 = all)")
    ap.add_argument("--durations", default="5,10")
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--stress", action="store_true", help="also run the extra stress conditions")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--tag", default="")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", default=str(ROOT / "docs" / "eval_results"))
    args = ap.parse_args()

    dsp, mcfg = parse_overrides(args.set)
    rng = np.random.default_rng(args.seed)
    root = Path(args.db).resolve().parent
    songs = []
    for s in Database(args.db).all_songs():
        p = resolve_audio_path(root, s.get("audio_path"))
        if p is not None and p.is_file():
            songs.append({**s, "audio_path": str(p)})
    songs.sort(key=lambda s: s["id"])
    if args.library_size:
        songs = songs[: args.library_size]
    if len(songs) < 10:
        raise SystemExit("need at least 10 songs with audio; run `python -m app.seed --chart --limit 300` first")
    perm = np.random.default_rng(args.seed).permutation(len(songs))
    n_hold = int(round(len(songs) * args.holdout))
    held = [songs[i] for i in perm[:n_hold]]
    indexed = [songs[i] for i in perm[n_hold:]]

    t0 = time.perf_counter()
    with ProcessPoolExecutor(args.workers) as ex:
        signals = dict(zip([s["id"] for s in songs], ex.map(_decode, [s["audio_path"] for s in songs], chunksize=4)))
        t_dec = time.perf_counter() - t0
        fps = list(ex.map(_fp, [(signals[s["id"]], dsp) for s in indexed], chunksize=4))
    idx = HashIndex()
    for s, (h, t) in zip(indexed, fps):
        idx.add_song(s["id"], h, t)
    idx.compact()
    t_idx = time.perf_counter() - t0 - t_dec
    print(f"library: {len(indexed)} indexed + {len(held)} held out; {idx.n_hashes} hashes "
          f"({idx.n_hashes / max(1, len(indexed)):.0f}/song); decode {t_dec:.1f}s, fingerprint+index {t_idx:.1f}s",
          flush=True)

    durations = [float(d) for d in args.durations.split(",")]
    conditions = args.conditions.split(",") + (STRESS if args.stress else [])
    INTERFERERS.extend(signals[s["id"]] for s in held)
    records = []  # dict per query

    def run_query(x: np.ndarray, truth: int | None, kind: str, cond: str, dur: float) -> None:
        q0 = time.perf_counter()
        y = degrade(x, cond, rng)
        q1 = time.perf_counter()
        r = match(fingerprint_signal(y, dsp), idx, mcfg)
        q2 = time.perf_counter()
        lat = q2 - q1  # fingerprint + match (decode/degradation excluded; see README for end-to-end)
        best = r.candidates[0].song_id if r.candidates else None
        records.append({"kind": kind, "cond": cond, "dur": dur, "truth": truth, "best": best, "score": r.score,
                        "second": r.second_score, "ratio": r.ratio, "matched": r.matched,
                        "offset": r.offset_seconds, "latency_ms": lat * 1000})

    def clip_of(sig: np.ndarray, dur: float) -> tuple[np.ndarray, float]:
        n = int(dur * SR)
        start = int(rng.integers(0, max(1, sig.size - n)))
        return sig[start : start + n], start / SR

    for dur in durations:
        for cond in conditions:
            for _ in range(args.clips):
                s = indexed[int(rng.integers(0, len(indexed)))]
                x, start = clip_of(signals[s["id"]], dur)
                run_query(x, s["id"], "pos", cond, dur)
                records[-1]["start"] = start
        for i in range(args.negatives):
            if held:
                s = held[i % len(held)]
                run_query(clip_of(signals[s["id"]], dur)[0], None, "neg_unindexed", "clean", dur)
        for i in range(max(5, args.negatives // 6)):
            run_query((np.random.default_rng(i).standard_normal(int(dur * SR)) * 0.3).astype(np.float32),
                      None, "neg_noise", "clean", dur)
        run_query(np.zeros(int(dur * SR), np.float32), None, "neg_silence", "clean", dur)
        print(f"  finished {dur:.0f}s clips ({len(records)} queries so far)", flush=True)

    report = summarize(records, mcfg, durations, conditions)
    report.update({
        "tag": args.tag, "overrides": args.set, "dsp": dataclasses.asdict(dsp), "match": dataclasses.asdict(mcfg),
        "library": {"indexed": len(indexed), "held_out": len(held), "hashes": idx.n_hashes},
        "timing": {"decode_s": round(t_dec, 1), "index_s": round(t_idx, 1)},
        "sweep": sweep(records),
    })
    print_report(report)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}{'-' + args.tag if args.tag else ''}.json"
    (out / name).write_text(json.dumps({**report, "records": records}, indent=1))
    print(f"\nsaved {out / name}")
    return 0


def _acc(recs: list[dict]) -> float:
    return float(np.mean([r["matched"] and r["best"] == r["truth"] for r in recs])) if recs else float("nan")


def summarize(records: list[dict], mcfg: MatchConfig, durations: list[float], conditions: list[str]) -> dict:
    pos_all = [r for r in records if r["kind"] == "pos"]
    pos = [r for r in pos_all if r["cond"] in CONDITIONS]
    stress = [r for r in pos_all if r["cond"] not in CONDITIONS]
    neg = [r for r in records if r["kind"] != "pos"]
    table = []
    for dur in durations:
        for cond in conditions:
            rs = [r for r in pos_all if r["dur"] == dur and r["cond"] == cond]
            ok = [r for r in rs if r["matched"] and r["best"] == r["truth"]]
            off_ok = [abs(r["offset"] - r["start"]) <= 1.5 * DSP.HOP / SR for r in ok]
            table.append({
                "dur": dur, "cond": cond, "n": len(rs), "top1": _acc(rs),
                "wrong_accept": float(np.mean([r["matched"] and r["best"] != r["truth"] for r in rs])) if rs else 0.0,
                "median_score": float(np.median([r["score"] for r in rs])) if rs else 0.0,
                "offset_ok": float(np.mean(off_ok)) if off_ok else float("nan"),
                "lat_p50_ms": float(np.percentile([r["latency_ms"] for r in rs], 50)) if rs else 0.0,
            })
    neg_table = []
    for kind in ("neg_unindexed", "neg_noise", "neg_silence"):
        rs = [r for r in neg if r["kind"] == kind]
        if rs:
            neg_table.append({"kind": kind, "n": len(rs), "fpr": float(np.mean([r["matched"] for r in rs])),
                              "max_score": int(max(r["score"] for r in rs)),
                              "p99_score": float(np.percentile([r["score"] for r in rs], 99))})
    lat = [r["latency_ms"] for r in records]
    return {
        "thresholds": {"MIN_SCORE": mcfg.MIN_SCORE, "MIN_RATIO": mcfg.MIN_RATIO},
        "overall": {
            "top1": _acc(pos),
            "wrong_accept": float(np.mean([r["matched"] and r["best"] != r["truth"] for r in pos])),
            "fpr": float(np.mean([r["matched"] for r in neg])) if neg else 0.0,
            "latency_p50_ms": float(np.percentile(lat, 50)), "latency_p95_ms": float(np.percentile(lat, 95)),
            "latency_max_ms": float(np.max(lat)),
            "stress_top1": _acc(stress) if stress else None,
        },
        "by_condition": table,
        "negatives": neg_table,
    }


def sweep(records: list[dict]) -> list[dict]:
    """Accuracy / FPR for a grid of thresholds (scores and ratios are threshold-independent)."""
    pos = [r for r in records if r["kind"] == "pos" and r["cond"] in CONDITIONS]
    stress = [r for r in records if r["kind"] == "pos" and r["cond"] not in CONDITIONS]
    neg = [r for r in records if r["kind"] != "pos"]
    rows = []
    for ms in (5, 8, 10, 12, 15, 20, 25, 30):
        for mr in (1.0, 1.25, 1.5, 2.0, 3.0):
            acc = np.mean([r["score"] >= ms and r["ratio"] >= mr and r["best"] == r["truth"] for r in pos])
            wa = np.mean([r["score"] >= ms and r["ratio"] >= mr and r["best"] != r["truth"] for r in pos])
            fpr = np.mean([r["score"] >= ms and r["ratio"] >= mr for r in neg]) if neg else 0.0
            st = np.mean([r["score"] >= ms and r["ratio"] >= mr and r["best"] == r["truth"] for r in stress]) \
                if stress else float("nan")
            rows.append({"MIN_SCORE": ms, "MIN_RATIO": mr, "top1": float(acc), "wrong_accept": float(wa),
                         "fpr": float(fpr), "stress_top1": float(st)})
    return rows


def print_report(rep: dict) -> None:
    o = rep["overall"]
    print(f"\n== {rep.get('tag') or 'eval'}  thresholds MIN_SCORE={rep['thresholds']['MIN_SCORE']} "
          f"MIN_RATIO={rep['thresholds']['MIN_RATIO']}")
    print(f"overall top-1 {o['top1']:.1%} | wrong-accept {o['wrong_accept']:.2%} | FPR {o['fpr']:.2%} | "
          f"latency p50 {o['latency_p50_ms']:.1f} ms p95 {o['latency_p95_ms']:.1f} ms max {o['latency_max_ms']:.1f} ms"
          + (f" | stress top-1 {o['stress_top1']:.1%}" if o.get("stress_top1") is not None else ""))
    print("\n| clip | condition | n | top-1 | wrong accept | median score | offset ok | p50 ms |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rep["by_condition"]:
        print(f"| {r['dur']:.0f}s | {r['cond']} | {r['n']} | {r['top1']:.1%} | {r['wrong_accept']:.1%} | "
              f"{r['median_score']:.0f} | {r['offset_ok']:.0%} | {r['lat_p50_ms']:.1f} |")
    print("\n| negative set | n | false positives | max score | p99 score |")
    print("|---|---|---|---|---|")
    for r in rep["negatives"]:
        print(f"| {r['kind']} | {r['n']} | {r['fpr']:.1%} | {r['max_score']} | {r['p99_score']:.1f} |")
    best = [s for s in rep.get("sweep", []) if s["fpr"] == 0.0 and s["wrong_accept"] == 0.0]
    if best:
        b = max(best, key=lambda s: (s["top1"], -s["MIN_SCORE"], -s["MIN_RATIO"]))
        print(f"\nbest zero-FP thresholds in sweep: MIN_SCORE={b['MIN_SCORE']} MIN_RATIO={b['MIN_RATIO']} "
              f"-> top-1 {b['top1']:.1%}")


if __name__ == "__main__":
    sys.exit(main())
