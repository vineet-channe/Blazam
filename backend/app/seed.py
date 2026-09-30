"""Seed the library from Deezer.

    python -m app.seed --source deezer --chart --limit 300
    python -m app.seed --source deezer --query "daft punk" --limit 20
    python -m app.seed --source deezer --playlist 248297032 --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.cli_common import build_services, run_job_to_completion, setup_logging


async def main_async(args: argparse.Namespace) -> int:
    svc = build_services()
    try:
        job = await run_job_to_completion(
            svc,
            lambda: svc.start_deezer_import(query=args.query, chart=args.chart, playlist_id=args.playlist,
                                            artist_id=args.artist, limit=args.limit),
            drain_enrichment=not args.no_enrich,
        )
        print(json.dumps({"status": job.status, **job.result, "errors": job.errors[:20],
                          "library_songs": svc.engine.index.n_songs, "library_hashes": svc.engine.index.n_hashes},
                         indent=2))
        return 0 if job.status == "done" else 1
    finally:
        await svc.stop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.seed", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["deezer"], default="deezer")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--chart", action="store_true", help="Deezer global chart (/chart/0/tracks)")
    g.add_argument("--query", help="Deezer search query")
    g.add_argument("--playlist", help="Deezer playlist id")
    g.add_argument("--artist", help="Deezer artist id (top tracks)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--no-enrich", action="store_true", help="skip MusicBrainz/CAA/LRCLIB enrichment")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    setup_logging(args.verbose)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
