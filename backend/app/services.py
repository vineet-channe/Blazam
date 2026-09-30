"""Orchestration: recognition routing (Tier 1 -> Tier 2 -> no_match), library import, uploads,
auto-learn and asynchronous metadata enrichment."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.clients.base import Cache, UpstreamError
from app.clients.deezer import DeezerClient, ITunesClient
from app.clients.metadata import CoverArtClient, LrclibClient, MusicBrainzClient
from app.clients.recognizers import AuddClient, MockAuddClient
from app.config import SETTINGS, Settings
from app.dsp.audio import SUPPORTED_EXTS, AudioDecodeError, load_audio_bytes
from app.dsp.matcher import MatchResult
from app.engine import Engine
from app.jobs import Job, JobManager

log = logging.getLogger("blazam.services")

PUBLIC_SONG_FIELDS = ("id", "title", "artist", "album", "year", "cover_url", "deezer_id", "mbid", "preview_url")


def public_song(s: dict[str, Any] | None, include_lyrics: bool = True) -> dict[str, Any] | None:
    if not s:
        return None
    out = {k: s.get(k) for k in PUBLIC_SONG_FIELDS}
    if include_lyrics and s.get("lyrics"):
        try:
            out["lyrics"] = json.loads(s["lyrics"])
        except (TypeError, json.JSONDecodeError):
            out["lyrics"] = {"plain": s["lyrics"], "synced": None}
    return out


def ffprobe_tags(path: Path) -> dict[str, str]:
    """Read title/artist/album/date tags with ffprobe (best effort)."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
            capture_output=True, timeout=20,
        )
        tags = json.loads(proc.stdout or b"{}").get("format", {}).get("tags", {})
        return {k.lower(): v for k, v in tags.items()}
    except Exception:  # noqa: BLE001
        return {}


def _norm(text: str | None) -> str:
    """Lower-case, drop (...)/[...] parts and ' - Remastered'-style suffixes, keep alphanumerics."""
    t = re.sub(r"[\(\[].*?[\)\]]", " ", (text or "").casefold())
    t = t.split(" - ")[0]
    return re.sub(r"[^0-9a-z]+", "", t)


def same_recording(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Conservative title/artist equality used before trusting a secondary source's audio."""
    ta, tb, aa, ab = _norm(a.get("title")), _norm(b.get("title")), _norm(a.get("artist")), _norm(b.get("artist"))
    if not (ta and tb and aa and ab) or ta != tb:
        return False
    return aa == ab or aa.startswith(ab) or ab.startswith(aa)


def meta_from_file(path: Path) -> dict[str, Any]:
    tags = ffprobe_tags(path)
    stem = path.stem
    artist, title = (stem.split(" - ", 1) + [""])[:2] if " - " in stem else ("Unknown", stem)
    date = tags.get("date") or tags.get("year") or ""
    return {
        "title": tags.get("title") or title or stem,
        "artist": tags.get("artist") or artist,
        "album": tags.get("album"),
        "year": int(date[:4]) if date[:4].isdigit() else None,
    }


@dataclass
class Clients:
    deezer: DeezerClient
    itunes: ITunesClient
    musicbrainz: MusicBrainzClient
    coverart: CoverArtClient
    lrclib: LrclibClient
    audd: AuddClient | MockAuddClient

    @classmethod
    def create(cls, cache: Cache, settings: Settings = SETTINGS, **kw: Any) -> "Clients":
        audd = MockAuddClient() if settings.mock_external else AuddClient(settings.audd_token, cache=cache, **kw)
        return cls(
            deezer=DeezerClient(cache=cache, **kw),
            itunes=ITunesClient(cache=cache, **kw),
            musicbrainz=MusicBrainzClient(cache=cache, **kw),
            coverart=CoverArtClient(cache=cache, **kw),
            lrclib=LrclibClient(cache=cache, **kw),
            audd=audd,
        )

    async def aclose(self) -> None:
        for c in (self.deezer, self.itunes, self.musicbrainz, self.coverart, self.lrclib, self.audd):
            await c.aclose()


class Services:
    """Application service container (one per process)."""

    def __init__(self, engine: Engine, clients: Clients, settings: Settings = SETTINGS) -> None:
        self.engine = engine
        self.db = engine.db
        self.clients = clients
        self.settings = settings
        self.jobs = JobManager()
        self.preview_dir = settings.data_dir / "previews"
        self.upload_dir = settings.data_dir / "uploads"
        self._enrich_q: asyncio.Queue[int] = asyncio.Queue()
        self._enrich_task: asyncio.Task | None = None
        self._learning: set[int] = set()
        self._fp_sem = asyncio.Semaphore(2)  # bounded CPU work for background indexing

    # ------------------------------------------------------------------ lifecycle
    def start_workers(self) -> None:
        if self._enrich_task is None:
            self._enrich_task = asyncio.create_task(self._enrich_worker())

    async def stop(self) -> None:
        if self._enrich_task:
            self._enrich_task.cancel()
            try:
                await self._enrich_task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(self.engine.save_snapshot_if_dirty)
        await self.clients.aclose()

    # ------------------------------------------------------------------ enrichment
    def schedule_enrich(self, song_id: int) -> None:
        self._enrich_q.put_nowait(song_id)

    async def _enrich_worker(self) -> None:
        while True:
            song_id = await self._enrich_q.get()
            try:
                await self.enrich(song_id)
            except Exception:  # noqa: BLE001 - enrichment must never crash the worker
                log.exception("enrichment failed for song %s", song_id)
            finally:
                self._enrich_q.task_done()

    @property
    def enrich_pending(self) -> int:
        return self._enrich_q.qsize()

    async def drain_enrichment(self) -> None:
        """Wait until every scheduled enrichment has finished."""
        await self._enrich_q.join()

    async def enrich(self, song_id: int) -> dict[str, Any] | None:
        """Fill in mbid / year / cover (CAA -> Deezer fallback) / lyrics. Every step degrades."""
        s = self.db.get_song(song_id)
        if not s:
            return None
        c = self.clients
        upd: dict[str, Any] = {}
        isrc = s.get("isrc")
        if (not isrc or not s.get("year")) and s.get("deezer_id"):
            # search/chart items can lack isrc or release_date; /track/{id} has both
            t = await c.deezer.safe(c.deezer.track(s["deezer_id"]))
            if t:
                isrc = isrc or t.get("isrc")
                upd.update(isrc=isrc, year=s.get("year") or t.get("year"))
        rec = None
        if isrc:
            rec = await c.musicbrainz.safe(c.musicbrainz.by_isrc(isrc))
        if not rec:
            rec = await c.musicbrainz.safe(c.musicbrainz.search_recording(s["title"], s["artist"]))
        if rec:
            upd["mbid"] = rec["mbid"]
            if rec.get("year"):
                upd["year"] = rec["year"]
            rgs = await c.musicbrainz.safe(c.musicbrainz.release_groups(rec["mbid"]), default=[])
            for rg in rgs[:3]:
                url = await c.coverart.safe(c.coverart.front_url(rg))
                if url:
                    upd["cover_url"] = url
                    break
        if self.settings.lyrics_enabled:
            ly = await c.lrclib.safe(c.lrclib.get(s["title"], s["artist"], s.get("album"), s.get("duration_s")))
            if ly and (ly.get("plain") or ly.get("synced")):
                upd["lyrics"] = json.dumps({"plain": ly.get("plain"), "synced": ly.get("synced")})
        self.db.update_song(song_id, **upd)
        return self.db.get_song(song_id)

    # ------------------------------------------------------------------ indexing helpers
    async def _itunes_preview(self, meta: dict[str, Any]) -> dict[str, Any] | None:
        """Secondary source: an iTunes preview for the *same* recording (strict artist/title match)."""
        hits = await self.clients.itunes.safe(
            self.clients.itunes.search(f"{meta.get('artist', '')} {meta.get('title', '')}", limit=10), default=[])
        for h in hits:
            if h.get("preview_url") and same_recording(h, meta):
                return h
        return None

    async def _index_deezer_track(self, meta: dict[str, Any], source: str) -> tuple[int, bool]:
        """Download a Deezer preview (refreshing an expired URL once; falling back to an iTunes
        preview of the same recording when Deezer has none) and index it."""
        existing = self.db.find_song(deezer_id=meta["deezer_id"]) if meta.get("deezer_id") else None
        if existing:
            return int(existing["id"]), False
        dest = self.preview_dir / f"{meta['deezer_id']}.mp3"
        itunes_dest = self.preview_dir / f"{meta['deezer_id']}.itunes.m4a"
        if itunes_dest.is_file():
            dest = itunes_dest
        elif not dest.is_file():
            url = meta.get("preview_url")
            try:
                if not url:
                    raise UpstreamError("no preview url")
                await self.clients.deezer.download(url, dest)
            except UpstreamError:
                fresh = await self.clients.deezer.track(meta["deezer_id"], fresh=True)
                if fresh and fresh.get("preview_url"):
                    meta = {**meta, **{k: v for k, v in fresh.items() if v}}
                    await self.clients.deezer.download(fresh["preview_url"], dest)
                else:
                    alt = await self._itunes_preview(meta)
                    if not alt:
                        raise UpstreamError("no preview on Deezer or iTunes")
                    await self.clients.deezer.download(alt["preview_url"], itunes_dest)
                    dest = itunes_dest
                    meta = {**meta, "preview_url": alt["preview_url"],
                            "cover_url": meta.get("cover_url") or alt.get("cover_url")}
        async with self._fp_sem:
            song_id, created = await asyncio.to_thread(
                self.engine.index_file, dest, {**meta, "source": source, "preview_url": meta.get("preview_url")}
            )
        if created:
            self.schedule_enrich(song_id)
        return song_id, created

    # ------------------------------------------------------------------ jobs
    def start_deezer_import(self, *, query: str | None = None, chart: bool = False,
                            playlist_id: str | int | None = None, artist_id: str | int | None = None,
                            limit: int = 50) -> Job:
        async def run(job: Job, jm: JobManager) -> None:
            d = self.clients.deezer
            if playlist_id is not None:
                tracks = await d.playlist_tracks(playlist_id, limit)
            elif artist_id is not None:
                tracks = await d.artist_top(artist_id, limit)
            elif query:
                tracks = await d.search(query, limit)
            else:
                tracks = await d.chart(limit)
            await self._import_tracks(job, jm, tracks, source="seed")

        return self.jobs.start("deezer_import", run)

    async def _import_tracks(self, job: Job, jm: JobManager, tracks: list[dict], source: str) -> None:
        tracks = [t for t in tracks if t.get("deezer_id")]
        jm.progress(job, total=len(tracks), done=0)
        sem = asyncio.Semaphore(self.settings.download_concurrency)
        counter = {"done": 0, "created": 0, "skipped": 0}

        async def one(t: dict) -> None:
            async with sem:
                label = f"{t.get('artist')} - {t.get('title')}"
                try:
                    _, created = await self._index_deezer_track(t, source)
                    counter["created" if created else "skipped"] += 1
                except (UpstreamError, AudioDecodeError, ValueError) as e:
                    jm.error(job, f"{label}: {e}")
                except Exception as e:  # noqa: BLE001 - isolate unexpected per-track failures
                    log.exception("import failed for %s", label)
                    jm.error(job, f"{label}: unexpected error: {e}")
                finally:
                    counter["done"] += 1
                    jm.progress(job, done=counter["done"], current_title=label)

        await asyncio.gather(*(one(t) for t in tracks))
        self.engine.index.compact()
        job.result = {"indexed": counter["created"], "skipped_existing": counter["skipped"], "failed": len(job.errors)}

    def start_upload(self, files: list[tuple[str, bytes]]) -> Job:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        batch_dir = self.upload_dir / f"{int(time.time() * 1000)}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        for i, (name, blob) in enumerate(files):
            safe = Path(name).name or f"upload_{i}"
            p = batch_dir / safe
            if p.exists():
                p = batch_dir / f"{i}_{safe}"
            p.write_bytes(blob)
            saved.append(p)

        async def run(job: Job, jm: JobManager) -> None:
            await self._index_paths(job, jm, saved, source="upload")

        return self.jobs.start("upload", run, total=len(saved))

    async def _index_paths(self, job: Job, jm: JobManager, paths: list[Path], source: str) -> None:
        jm.progress(job, total=len(paths), done=0)
        created_n = 0
        for i, p in enumerate(paths):
            meta = meta_from_file(p)
            jm.progress(job, current_title=f"{meta['artist']} - {meta['title']}")
            if p.suffix.lower() not in SUPPORTED_EXTS:
                jm.error(job, f"{p.name}: unsupported extension")
            else:
                try:
                    async with self._fp_sem:
                        song_id, created = await asyncio.to_thread(self.engine.index_file, p, {**meta, "source": source})
                    created_n += int(created)
                    if created:
                        self.schedule_enrich(song_id)
                except (AudioDecodeError, ValueError) as e:
                    jm.error(job, f"{p.name}: {e}")
            jm.progress(job, done=i + 1)
        self.engine.index.compact()
        job.result = {"indexed": created_n, "failed": len(job.errors)}

    # ------------------------------------------------------------------ auto-learn
    def schedule_learn(self, song: dict[str, Any]) -> bool:
        """Queue background indexing of an externally recognised song. Returns True if queued."""
        did = song.get("deezer_id")
        if not (self.settings.auto_learn and did) or did in self._learning:
            return False
        if self.db.find_song(deezer_id=did):
            return False
        self._learning.add(did)

        async def run(job: Job, jm: JobManager) -> None:
            try:
                jm.progress(job, total=1, current_title=f"{song.get('artist')} - {song.get('title')}")
                meta = {k: song.get(k) for k in ("deezer_id", "title", "artist", "album", "year", "cover_url",
                                                  "preview_url", "isrc", "mbid", "duration_s")}
                song_id, _ = await self._index_deezer_track(meta, source="learned")
                job.result = {"song_id": song_id}
                jm.progress(job, done=1)
            finally:
                self._learning.discard(did)

        self.jobs.start("auto_learn", run, total=1)
        return True

    # ------------------------------------------------------------------ recognition
    async def recognize(self, blob: bytes, filename: str = "clip.webm") -> dict[str, Any]:
        """Tier 1 (own engine) -> Tier 2 (AudD) -> no_match. Records history."""
        t0 = time.perf_counter()
        try:
            x = await asyncio.to_thread(load_audio_bytes, blob, filename, self.settings.max_query_seconds)
        except AudioDecodeError as e:
            raise ValueError(f"could not decode audio: {e}") from e
        r: MatchResult = await asyncio.to_thread(self.engine.identify, x)
        resp: dict[str, Any] = {
            "status": "no_match", "source": None, "confidence": 0.0, "score": r.score,
            "offset_seconds": None, "latency_ms": 0.0, "song": None, "learned": False,
        }
        song_id: int | None = None
        if r.matched and r.song_id is not None:
            song = self.db.get_song(r.song_id)
            song_id = r.song_id
            resp.update(status="match", source="own", confidence=round(r.confidence, 4),
                        offset_seconds=round(r.offset_seconds, 3), song=public_song(song))
        else:
            ext = await self._external(blob, filename, x)
            if ext:
                lib = self.db.find_song(deezer_id=ext["deezer_id"]) if ext.get("deezer_id") else None
                if lib:
                    song_id = int(lib["id"])
                    song_pub = public_song(lib)
                    learned = False
                else:
                    song_pub = {k: ext.get(k) for k in PUBLIC_SONG_FIELDS}
                    song_pub["id"] = None
                    learned = self.schedule_learn(ext)
                resp.update(status="match", source="external", confidence=None, song=song_pub, learned=learned,
                            offset_seconds=_timecode_seconds(ext.get("timecode")))
        resp["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        self.db.add_history({**resp, "song_id": song_id})
        return resp

    async def _external(self, blob: bytes, filename: str, x: np.ndarray) -> dict[str, Any] | None:
        audd = self.clients.audd
        try:
            if isinstance(audd, MockAuddClient):
                return await audd.recognize(blob, filename, signal=x)
            return await asyncio.wait_for(audd.recognize(blob, filename), timeout=self.settings.http_timeout_s * 2)
        except (UpstreamError, asyncio.TimeoutError) as e:
            log.warning("external recognizer unavailable: %s", e)
            return None


def _timecode_seconds(tc: str | None) -> float | None:
    if not tc:
        return None
    try:
        parts = [float(p) for p in tc.split(":")]
    except ValueError:
        return None
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec

