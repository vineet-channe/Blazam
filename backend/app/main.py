"""FastAPI application: HTTP contract consumed by the Blazam frontend."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import __version__
from app.config import SETTINGS
from app.dsp.audio import ffmpeg_available
from app.engine import Engine, resolve_audio_path
from app.services import Clients, Services, public_song

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# explicit types: Python's guesses (audio/mp4a-latm, video/webm, audio/x-flac) confuse browsers
AUDIO_MEDIA_TYPES = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac",
    ".wav": "audio/wav", ".flac": "audio/flac", ".ogg": "audio/ogg", ".oga": "audio/ogg",
    ".opus": "audio/ogg", ".webm": "audio/webm", ".aiff": "audio/aiff", ".aif": "audio/aiff",
}


def with_local_preview(request: Request, song: dict[str, Any] | None) -> dict[str, Any] | None:
    """Point a library song's preview_url at our own audio endpoint.

    Deezer preview URLs are signed and expire ~15 min after issue, so a stored one is useless
    later; the audio we indexed is on disk and never expires. External songs that are not in
    the library yet (``id`` is null) keep the fresh URL AudD/Deezer just returned.
    """
    if song and song.get("id") is not None:
        s = request.app.state.svc
        row = s.db.get_song(song["id"])
        path = resolve_audio_path(s.engine.data_root, row.get("audio_path")) if row else None
        if path is not None and path.is_file():
            song = {**song, "preview_url": str(request.url_for("song_preview", song_id=song["id"]))}
    return song


class ImportRequest(BaseModel):
    source: Literal["deezer"] = "deezer"
    query: str | None = None
    chart: bool = False
    playlist_id: str | None = None
    artist_id: str | None = None
    limit: int = Field(50, ge=1, le=1000)


def create_app(services_factory: Any = None) -> FastAPI:
    """Build the app. ``services_factory`` (async, returns Services) lets tests inject fakes."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if services_factory is not None:
            svc = await services_factory()
        else:
            engine = Engine()
            engine.load_index()
            svc = Services(engine, Clients.create(cache=engine.db))
        svc.start_workers()
        app.state.svc = svc
        yield
        await svc.stop()

    app = FastAPI(title="Blazam", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(SETTINGS.cors_origins),
        allow_origin_regex=SETTINGS.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def svc(request: Request) -> Services:
        return request.app.state.svc

    @app.post("/api/recognize")
    async def recognize(request: Request, audio: UploadFile = File(...)) -> dict[str, Any]:
        blob = await audio.read()
        if not blob:
            raise HTTPException(400, "empty audio upload")
        if len(blob) > SETTINGS.max_upload_bytes:
            raise HTTPException(413, "audio too large")
        try:
            resp = await svc(request).recognize(blob, audio.filename or "clip.webm")
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        resp["song"] = with_local_preview(request, resp.get("song"))
        return resp

    @app.get("/api/library")
    async def library(request: Request, q: str = "", page: int = Query(1, ge=1),
                      page_size: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
        rows, total = svc(request).db.list_songs(q=q, page=page, page_size=page_size)
        items = []
        for r in rows:
            s = with_local_preview(request, public_song(r, include_lyrics=False))
            s.update(source=r["source"], n_hashes=r["n_hashes"], has_lyrics=bool(r.get("lyrics")))
            items.append(s)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    @app.get("/api/songs/{song_id}/preview", name="song_preview")
    async def song_preview(request: Request, song_id: int) -> FileResponse:
        """The indexed audio of a library song (supports HTTP Range for seeking)."""
        s = svc(request)
        song = s.db.get_song(song_id)
        if not song:
            raise HTTPException(404, "song not found")
        path = resolve_audio_path(s.engine.data_root, song.get("audio_path"))
        if path is None or not path.is_file():
            raise HTTPException(404, "audio file not available for this song")
        media = AUDIO_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
        return FileResponse(path, media_type=media, headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/api/library/import")
    async def library_import(request: Request, body: ImportRequest) -> dict[str, str]:
        if not (body.query or body.chart or body.playlist_id or body.artist_id):
            raise HTTPException(422, "one of query, chart, playlist_id or artist_id is required")
        job = svc(request).start_deezer_import(query=body.query, chart=body.chart, playlist_id=body.playlist_id,
                                               artist_id=body.artist_id, limit=body.limit)
        return {"job_id": job.id}

    @app.post("/api/library/upload")
    async def library_upload(request: Request, files: list[UploadFile] = File(...)) -> dict[str, str]:
        payload = []
        for f in files:
            blob = await f.read()
            if len(blob) > SETTINGS.max_upload_bytes * 4:
                raise HTTPException(413, f"{f.filename}: file too large")
            payload.append((f.filename or "upload", blob))
        job = svc(request).start_upload(payload)
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    async def job_status(request: Request, job_id: str) -> dict[str, Any]:
        job = svc(request).jobs.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return job.public()

    @app.get("/api/jobs/{job_id}/stream")
    async def job_stream(request: Request, job_id: str) -> StreamingResponse:
        s = svc(request)
        if not s.jobs.get(job_id):
            raise HTTPException(404, "job not found")
        return StreamingResponse(
            s.jobs.stream(job_id), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/history")
    async def history(request: Request, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
        items = svc(request).db.list_history(limit)
        for it in items:
            it["song"] = with_local_preview(request, it.get("song"))
        return {"items": items}

    @app.get("/api/stats")
    async def stats(request: Request) -> dict[str, Any]:
        return svc(request).db.stats()

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        s = svc(request)
        return {
            "status": "ok",
            "version": __version__,
            "index_loaded": s.engine.loaded,
            "songs_indexed": s.engine.index.n_songs,
            "hashes_indexed": s.engine.index.n_hashes,
            "stale_songs": s.engine.stale_songs,
            "fp_version": s.engine.version,
            "ffmpeg": ffmpeg_available(),
            "external_recognizer": "mock" if s.settings.mock_external else (
                "audd" if s.settings.audd_token else "audd-anonymous"),
            "auto_learn": s.settings.auto_learn,
            "lyrics": s.settings.lyrics_enabled,
        }

    return app


app = create_app()
