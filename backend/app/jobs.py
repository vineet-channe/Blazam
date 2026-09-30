"""Background jobs with progress reporting (polling + Server-Sent Events)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("blazam.jobs")


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | failed
    done: int = 0
    total: int = 0
    current_title: str | None = None
    errors: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d["job_id"] = d.pop("id")
        return d


JobFn = Callable[["Job", "JobManager"], Awaitable[None]]


class JobManager:
    MAX_ERRORS = 200

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._tasks: set[asyncio.Task] = set()

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def start(self, kind: str, fn: JobFn, total: int = 0) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, total=total)
        self.jobs[job.id] = job
        task = asyncio.create_task(self._run(job, fn))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: Job, fn: JobFn) -> None:
        job.status = "running"
        self.notify(job)
        try:
            await fn(job, self)
            job.status = "done"
        except Exception as e:  # noqa: BLE001 - job failures are reported, not raised
            log.exception("job %s failed", job.id)
            job.status = "failed"
            self.error(job, f"fatal: {e}")
        finally:
            job.current_title = None
            job.finished_at = time.time()
            self.notify(job)

    # ------------------------------------------------------------------ progress
    def progress(self, job: Job, *, done: int | None = None, total: int | None = None,
                 current_title: str | None = None) -> None:
        if done is not None:
            job.done = done
        if total is not None:
            job.total = total
        if current_title is not None:
            job.current_title = current_title
        self.notify(job)

    def error(self, job: Job, msg: str) -> None:
        if len(job.errors) < self.MAX_ERRORS:
            job.errors.append(msg)
        self.notify(job)

    def notify(self, job: Job) -> None:
        for q in list(self._subs.get(job.id, ())):
            q.put_nowait(job.public())

    async def stream(self, job_id: str, heartbeat_s: float = 15.0):
        """Async generator of SSE frames until the job finishes."""
        job = self.jobs[job_id]
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(job_id, set()).add(q)
        try:
            import json

            yield f"event: progress\ndata: {json.dumps(job.public())}\n\n"
            while job.status not in ("done", "failed"):
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=heartbeat_s)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
            yield f"event: end\ndata: {json.dumps(job.public())}\n\n"
        finally:
            self._subs.get(job_id, set()).discard(q)

    async def wait(self, job_id: str, timeout: float | None = None) -> Job:
        job = self.jobs[job_id]
        t0 = time.monotonic()
        while job.status not in ("done", "failed"):
            if timeout is not None and time.monotonic() - t0 > timeout:
                raise TimeoutError(job_id)
            await asyncio.sleep(0.05)
        return job
