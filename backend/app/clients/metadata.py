"""MusicBrainz (1 req/s, descriptive User-Agent), Cover Art Archive, and LRCLIB clients.

Observed behaviour (see tests/fixtures/api/ and README "doc vs reality"):
* MusicBrainz ``/isrc/{isrc}`` ignores ``inc=releases`` - recordings come back with
  ``first-release-date`` but without releases; releases need ``/recording/{mbid}?inc=releases``.
* MusicBrainz throttling returns HTTP 503 (documented); we retry with backoff.
* Cover Art Archive ``/release-group/{mbid}/front-500`` answers 307 (redirect to archive.org) or
  404 with an *HTML* body; ``/release/{mbid}`` JSON is also served via a 307 redirect.
* LRCLIB 404 body uses ``statusCode`` (docs show ``code``); 429 carries ``Retry-After``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.clients.base import BaseClient


def _year(date: str | None) -> int | None:
    return int(date[:4]) if isinstance(date, str) and date[:4].isdigit() else None


def _artist_credit(ac: list[dict] | None) -> str | None:
    if not ac:
        return None
    return "".join(f"{a.get('name', '')}{a.get('joinphrase', '')}" for a in ac).strip() or None


class MusicBrainzClient(BaseClient):
    name = "musicbrainz"
    base_url = "https://musicbrainz.org/ws/2"
    min_interval_s = 1.05  # documented: ~1 request/second per IP
    cache_ttl_s = 7 * 24 * 3600
    # one throttle shared by *all* instances in the process (the limit is per IP)
    _global_locks: dict[int, asyncio.Lock] = {}
    _global_last = 0.0

    async def _throttle(self) -> None:
        loop_id = id(asyncio.get_running_loop())
        lock = MusicBrainzClient._global_locks.setdefault(loop_id, asyncio.Lock())
        async with lock:
            wait = MusicBrainzClient._global_last + self.min_interval_s - time.monotonic()
            if wait > 0:
                await self._sleep(wait)
            MusicBrainzClient._global_last = time.monotonic()

    def check(self, resp: httpx.Response) -> Any:
        if resp.status_code in (400, 404):
            return None
        resp.raise_for_status()
        return resp.json()

    async def by_isrc(self, isrc: str) -> dict | None:
        """Best recording for an ISRC: {mbid, title, artist, year}."""
        body = await self.request("GET", f"/isrc/{isrc}", params={"fmt": "json"})
        recs = (body or {}).get("recordings") or []
        if not recs:
            return None
        recs = sorted(recs, key=lambda r: (r.get("first-release-date") or "9999", r.get("id")))
        r = recs[0]
        return {"mbid": r["id"], "title": r.get("title"), "artist": _artist_credit(r.get("artist-credit")),
                "year": _year(r.get("first-release-date"))}

    async def search_recording(self, title: str, artist: str) -> dict | None:
        q = f'recording:"{title}" AND artist:"{artist}"'
        body = await self.request("GET", "/recording", params={"query": q, "limit": 5, "fmt": "json"})
        recs = [r for r in (body or {}).get("recordings", []) if int(r.get("score", 0)) >= 90]
        if not recs:
            return None
        r = recs[0]
        return {"mbid": r["id"], "title": r.get("title"), "artist": _artist_credit(r.get("artist-credit")),
                "year": _year(r.get("first-release-date"))}

    async def release_groups(self, recording_mbid: str) -> list[str]:
        """Release-group MBIDs for a recording, official + earliest first."""
        body = await self.request(
            "GET", f"/recording/{recording_mbid}", params={"inc": "releases+release-groups", "fmt": "json"}
        )
        rels = (body or {}).get("releases") or []
        rels = sorted(rels, key=lambda r: (r.get("status") != "Official", r.get("date") or "9999"))
        seen: list[str] = []
        for r in rels:
            rg = (r.get("release-group") or {}).get("id")
            if rg and rg not in seen:
                seen.append(rg)
        return seen


class CoverArtClient(BaseClient):
    name = "coverart"
    base_url = "https://coverartarchive.org"
    cache_ttl_s = 7 * 24 * 3600

    def check(self, resp: httpx.Response) -> Any:
        if resp.status_code in (200, 307, 302):
            return {"exists": True}
        if resp.status_code in (400, 404):
            return {"exists": False}
        resp.raise_for_status()
        return {"exists": False}

    async def front_url(self, release_group_mbid: str, size: int = 500) -> str | None:
        """Stable CAA URL of a release group's front cover, or None if there is none."""
        path = f"/release-group/{release_group_mbid}/front-{size}"
        res = await self.request("HEAD", path)
        return f"{self.base_url}{path}" if res and res.get("exists") else None


class LrclibClient(BaseClient):
    name = "lrclib"
    base_url = "https://lrclib.net"
    min_interval_s = 0.25  # docs: sequential requests with a 200-500 ms delay
    cache_ttl_s = 7 * 24 * 3600

    async def get(self, title: str, artist: str, album: str | None = None, duration_s: float | None = None) -> dict | None:
        params: dict[str, Any] = {"track_name": title, "artist_name": artist}
        if album:
            params["album_name"] = album
        if duration_s and 1 <= duration_s <= 3600:
            params["duration"] = int(round(duration_s))
        body = await self.request("GET", "/api/get", params=params)
        if not body:
            return None
        return {"plain": body.get("plainLyrics"), "synced": body.get("syncedLyrics"),
                "instrumental": bool(body.get("instrumental"))}
