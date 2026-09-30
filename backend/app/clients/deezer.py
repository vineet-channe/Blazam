"""Deezer public API (no key) + iTunes Search as a secondary source.

Observed behaviour (recorded fixtures in tests/fixtures/api/):
* Errors come back as HTTP 200 with ``{"error": {"type", "message", "code"}}``; code 800 means
  "no data" (not found) and code 4 is the quota error, which we retry with backoff.
* ``preview`` URLs are signed (``hdnea=exp=...``) and expire ~15 minutes after issue, so
  responses containing them are cached for 10 minutes only and previews are downloaded promptly.
* Chart items have no ``isrc``/``release_date``; ``/track/{id}`` has both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.clients.base import BaseClient, Retryable, UpstreamError

DEEZER_QUOTA_CODE = 4
DEEZER_NOT_FOUND_CODE = 800


def normalize_deezer_track(t: dict[str, Any]) -> dict[str, Any]:
    """Map a Deezer track object to Blazam's song metadata shape."""
    album = t.get("album") or {}
    artist = t.get("artist") or {}
    release = t.get("release_date") or album.get("release_date")
    year = int(release[:4]) if isinstance(release, str) and release[:4].isdigit() else None
    return {
        "deezer_id": t.get("id"),
        "title": t.get("title") or t.get("title_short") or "Unknown",
        "artist": artist.get("name") or "Unknown",
        "album": album.get("title"),
        "year": year,
        "cover_url": album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium"),
        "preview_url": t.get("preview") or None,
        "duration_s": float(t["duration"]) if t.get("duration") else None,
        "isrc": t.get("isrc"),
    }


class DeezerClient(BaseClient):
    name = "deezer"
    base_url = "https://api.deezer.com"
    min_interval_s = 0.12  # conservative (~8 req/s); Deezer's exact quota is not publicly documented
    cache_ttl_s = 600  # responses embed preview URLs that expire ~15 min after issue

    def check(self, resp: httpx.Response) -> Any:
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict) and "error" in body:
            err = body["error"] or {}
            code = err.get("code")
            if code == DEEZER_QUOTA_CODE:
                raise Retryable(f"deezer quota exceeded: {err.get('message')}", retry_after=5.0)
            if code == DEEZER_NOT_FOUND_CODE:
                return None
            raise UpstreamError(f"deezer error {code}: {err.get('message')}")
        return body

    async def _paged(self, path: str, limit: int, params: dict | None = None) -> list[dict]:
        out: list[dict] = []
        index = 0
        while len(out) < limit:
            page = min(100, limit - len(out))
            body = await self.request("GET", path, params={**(params or {}), "index": index, "limit": page})
            if not body:
                break
            data = body.get("data") or []
            out.extend(data)
            index += len(data)
            # observed: /chart/0/tracks omits "next" and reports total == page size even though
            # index-based paging works, so a full page also means "try the next one"
            more = bool(body.get("next")) or len(data) >= page
            if not data or not more:
                break
        return out[:limit]

    async def chart(self, limit: int = 100, genre_id: int = 0) -> list[dict]:
        return [normalize_deezer_track(t) for t in await self._paged(f"/chart/{genre_id}/tracks", limit)]

    async def search(self, q: str, limit: int = 25) -> list[dict]:
        return [normalize_deezer_track(t) for t in await self._paged("/search", limit, {"q": q})]

    async def playlist_tracks(self, playlist_id: int | str, limit: int = 100) -> list[dict]:
        return [normalize_deezer_track(t) for t in await self._paged(f"/playlist/{playlist_id}/tracks", limit)]

    async def artist_top(self, artist_id: int | str, limit: int = 25) -> list[dict]:
        return [normalize_deezer_track(t) for t in await self._paged(f"/artist/{artist_id}/top", limit)]

    async def track(self, track_id: int | str, fresh: bool = False) -> dict | None:
        body = await self.request("GET", f"/track/{track_id}", use_cache=not fresh)
        return normalize_deezer_track(body) if body else None

    async def download(self, url: str, dest: Path, max_bytes: int = 20 * 1024 * 1024) -> Path:
        """Download a (preview) MP3 to ``dest`` with retries. Raises UpstreamError on failure."""
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                async with self._client.stream("GET", url, follow_redirects=True) as r:
                    if r.status_code in (403, 410):
                        raise UpstreamError(f"preview URL rejected ({r.status_code}); likely expired")
                    r.raise_for_status()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    size = 0
                    with tmp.open("wb") as fh:
                        async for chunk in r.aiter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                raise UpstreamError("download too large")
                            fh.write(chunk)
                    tmp.replace(dest)
                    return dest
            except UpstreamError:
                raise
            except (httpx.HTTPError,) as e:
                last = e
                if attempt < self.retries:
                    await self._sleep(self.backoff_base_s * (2**attempt))
        raise UpstreamError(f"download failed: {last}")


class ITunesClient(BaseClient):
    """iTunes Search API (secondary metadata/preview source). Documented limit ~20 calls/min."""

    name = "itunes"
    base_url = "https://itunes.apple.com"
    min_interval_s = 3.0

    async def search(self, term: str, limit: int = 5, country: str = "US") -> list[dict]:
        body = await self.request(
            "GET", "/search", params={"term": term, "media": "music", "entity": "song", "limit": limit, "country": country}
        )
        out = []
        for r in (body or {}).get("results", []):
            rd = r.get("releaseDate") or ""
            out.append({
                "itunes_id": r.get("trackId"),
                "title": r.get("trackName"),
                "artist": r.get("artistName"),
                "album": r.get("collectionName"),
                "year": int(rd[:4]) if rd[:4].isdigit() else None,
                "cover_url": r.get("artworkUrl100"),
                "preview_url": r.get("previewUrl"),
                "duration_s": (r["trackTimeMillis"] / 1000.0) if r.get("trackTimeMillis") else None,
            })
        return out
