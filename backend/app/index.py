"""Index local audio files (recursively) into the library.

    python -m app.index ./songs_dir
    python -m app.index --reindex          # re-fingerprint after DSP parameters changed
    python -m app.index --enrich-missing   # re-run metadata enrichment for songs lacking year/MBID
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.cli_common import build_services, run_job_to_completion, setup_logging
from app.dsp.audio import SUPPORTED_EXTS


async def main_async(args: argparse.Namespace) -> int:
    svc = build_services(load=not (args.reindex or args.enrich_missing))
    try:
        if args.enrich_missing:
            todo = [s["id"] for s in svc.db.all_songs() if s.get("year") is None or s.get("mbid") is None]
            before = _coverage(svc)
            svc.start_workers()
            for sid in todo:
                svc.schedule_enrich(sid)
            sys.stderr.write(f"enriching {len(todo)} songs (MusicBrainz: 1 req/s; cached answers are reused)...\n")
            while svc.enrich_pending:
                sys.stderr.write(f"\r  remaining: {svc.enrich_pending:<5}")
                await asyncio.sleep(1)
            await svc.drain_enrichment()
            sys.stderr.write("\n")
            print(json.dumps({"songs_considered": len(todo), "before": before, "after": _coverage(svc)}, indent=2))
            return 0
        if args.reindex:
            moved = svc.engine.migrate_audio_paths()
            if moved:
                sys.stderr.write(f"stored {moved} audio paths relative to the data dir\n")
            res = await asyncio.to_thread(
                svc.engine.reindex_all, lambda n, t: sys.stderr.write(f"\rreindexed {n}: {t[:60]:<60}")
            )
            sys.stderr.write("\n")
            print(json.dumps(res, indent=2))
            return 0
        root = Path(args.path)
        if not root.exists():
            print(f"error: {root} does not exist", file=sys.stderr)
            return 2
        paths = sorted(p for p in ([root] if root.is_file() else root.rglob("*"))
                       if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)
        if not paths:
            print(f"no audio files ({', '.join(sorted(SUPPORTED_EXTS))}) under {root}", file=sys.stderr)
            return 1

        async def run(job, jm):
            await svc._index_paths(job, jm, paths, source="upload")

        job = await run_job_to_completion(svc, lambda: svc.jobs.start("index_dir", run, total=len(paths)),
                                          drain_enrichment=args.enrich)
        print(json.dumps({"status": job.status, **job.result, "errors": job.errors[:20],
                          "library_songs": svc.engine.index.n_songs}, indent=2))
        return 0 if job.status == "done" else 1
    finally:
        await svc.stop()


def _coverage(svc) -> dict[str, int]:
    songs = svc.db.all_songs()
    return {"songs": len(songs), "with_year": sum(s["year"] is not None for s in songs),
            "with_mbid": sum(s["mbid"] is not None for s in songs),
            "with_lyrics": sum(s["lyrics"] is not None for s in songs)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.index", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", nargs="?", help="file or directory of audio files")
    p.add_argument("--reindex", action="store_true")
    p.add_argument("--enrich-missing", action="store_true", help="re-enrich songs missing year or MBID")
    p.add_argument("--enrich", action="store_true", help="also look up MusicBrainz/CAA/LRCLIB metadata")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if not (args.reindex or args.enrich_missing) and not args.path:
        p.error("path is required unless --reindex or --enrich-missing")
    setup_logging(args.verbose)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
