"""Identify a clip against the local library (Tier 1 only, fully offline).

    python -m app.match clip.wav
    python -m app.match clip.webm --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from app.config import DSP, MATCH
from app.dsp.audio import AudioDecodeError, load_audio
from app.dsp.fingerprint import fingerprint_signal
from app.dsp.matcher import match
from app.engine import Engine


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.match", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("clip")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if not Path(args.clip).is_file():
        print(f"error: {args.clip} is not a file", file=sys.stderr)
        return 2
    engine = Engine()
    info = engine.load_index()
    t0 = time.perf_counter()
    try:
        x = load_audio(args.clip)
    except AudioDecodeError as e:
        print(f"error: cannot decode {args.clip}: {e}", file=sys.stderr)
        return 2
    t1 = time.perf_counter()
    fp = fingerprint_signal(x)
    t2 = time.perf_counter()
    r = match(fp, engine.index)
    t3 = time.perf_counter()
    song = engine.db.get_song(r.song_id) if r.song_id else None
    cands = []
    for c in r.candidates:
        s = engine.db.get_song(c.song_id)
        cands.append({"song_id": c.song_id, "title": s["title"] if s else None, "artist": s["artist"] if s else None,
                      "score": c.score, "raw_hits": c.raw_hits, "offset_s": round(c.delta * DSP.HOP / DSP.SAMPLE_RATE, 2)})
    out = {
        "status": "match" if r.matched else "no_match",
        "song": {k: song[k] for k in ("id", "title", "artist", "album", "year")} if song else None,
        "score": r.score, "second_score": r.second_score, "ratio": round(r.ratio, 2),
        "confidence": round(r.confidence, 3), "offset_seconds": round(r.offset_seconds, 3),
        "thresholds": {"MIN_SCORE": MATCH.MIN_SCORE, "MIN_RATIO": MATCH.MIN_RATIO},
        "query_hashes": r.n_query_hashes,
        "timing_ms": {"decode": round(1000 * (t1 - t0), 1), "fingerprint": round(1000 * (t2 - t1), 1),
                      "match": round(1000 * (t3 - t2), 1)},
        "library": info, "candidates": cands,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        if song:
            print(f"MATCH  {song['artist']} - {song['title']}  (score {r.score}, ratio {r.ratio:.2f}, "
                  f"confidence {r.confidence:.2f}, offset {r.offset_seconds:.2f}s)")
        else:
            print(f"NO MATCH (best score {r.score}, ratio {r.ratio:.2f})")
        print(f"timing: decode {out['timing_ms']['decode']} ms, fingerprint {out['timing_ms']['fingerprint']} ms, "
              f"match {out['timing_ms']['match']} ms; library {info['songs']} songs / {info['hashes']} hashes")
        for c in cands:
            print(f"   {c['score']:>5}  {c['artist']} - {c['title']}  (raw {c['raw_hits']}, offset {c['offset_s']}s)")
    return 0 if r.matched else 3


if __name__ == "__main__":
    sys.exit(main())
