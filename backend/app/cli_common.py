"""Helpers shared by the command-line entry points (run without the HTTP server)."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable

from app.engine import Engine
from app.jobs import Job, JobManager
from app.services import Clients, Services


def build_services(load: bool = True) -> Services:
    engine = Engine()
    if load:
        engine.load_index()
    return Services(engine, Clients.create(cache=engine.db))


def print_progress(job: Job) -> None:
    pct = (100.0 * job.done / job.total) if job.total else 0.0
    title = (job.current_title or "")[:60]
    sys.stderr.write(f"\r[{job.done:>4}/{job.total:<4}] {pct:5.1f}%  errors={len(job.errors):<3} {title:<60}")
    sys.stderr.flush()


async def run_job_to_completion(svc: Services, start: Callable[[], Job], drain_enrichment: bool) -> Job:
    """Start a job, render progress on stderr, optionally wait for the enrichment queue."""
    svc.start_workers()
    job = start()
    while job.status not in ("done", "failed"):
        print_progress(job)
        await asyncio.sleep(0.25)
    print_progress(job)
    sys.stderr.write("\n")
    if drain_enrichment:
        pending = svc.enrich_pending
        if pending:
            sys.stderr.write(f"enriching metadata for {pending} songs (MusicBrainz is limited to 1 req/s)...\n")
        await svc.drain_enrichment()
    return job


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def run(coro: Awaitable) -> None:
    asyncio.run(coro)  # type: ignore[arg-type]
