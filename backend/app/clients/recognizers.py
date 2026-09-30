"""External recognizers: AudD (Tier 2 fallback) and AcoustID/Chromaprint (comparison only).

AudD observed behaviour (fixtures in tests/fixtures/api/audd_*):
* Every response is HTTP 200; errors are ``{"status": "error", "error": {"error_code",
  "error_message"}}`` (docs show ``error: {...}`` without naming the fields).
* Without ``api_token`` a small anonymous quota works; ``return=musicbrainz`` was ignored on the
  anonymous call (no ``musicbrainz`` key in the result), ``deezer`` was honoured.
* ``result`` is ``null`` when nothing matched. ``timecode`` is relative to the full track.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.clients.base import BaseClient, UpstreamError
from app.clients.deezer import normalize_deezer_track

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "api"

AUDD_AUTH_ERRORS = {900, 901}


class AuddAuthError(UpstreamError):
    """AudD refused the request (missing/invalid token or quota exhausted)."""


def normalize_audd_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map an AudD ``result`` object to Blazam's song metadata shape (plus ``deezer`` if present)."""
    if not result:
        return None
    rd = result.get("release_date") or ""
    song: dict[str, Any] = {
        "title": result.get("title") or "Unknown",
        "artist": result.get("artist") or "Unknown",
        "album": result.get("album"),
        "year": int(rd[:4]) if rd[:4].isdigit() else None,
        "cover_url": None,
        "deezer_id": None,
        "mbid": None,
        "preview_url": None,
        "isrc": None,
        "timecode": result.get("timecode"),
    }
    dz = result.get("deezer")
    if isinstance(dz, dict) and dz.get("id"):
        d = normalize_deezer_track(dz)
        for k in ("deezer_id", "cover_url", "preview_url", "isrc", "duration_s"):
            song[k] = d.get(k)
        song["album"] = song["album"] or d.get("album")
    mb = result.get("musicbrainz")
    if isinstance(mb, list) and mb and isinstance(mb[0], dict):
        song["mbid"] = mb[0].get("id")
    return song


class AuddClient(BaseClient):
    name = "audd"
    base_url = "https://api.audd.io"
    MAX_BYTES = 10 * 1024 * 1024  # documented limit of the standard endpoint

    def __init__(self, api_token: str = "", **kw: Any) -> None:
        super().__init__(**kw)
        self.api_token = api_token

    def check(self, resp: httpx.Response) -> Any:
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") == "error":
            err = body.get("error") or {}
            code = err.get("error_code")
            msg = err.get("error_message", "")
            if code in AUDD_AUTH_ERRORS:
                raise AuddAuthError(f"audd auth/quota error {code}: {msg}")
            if code in (300, 500, 700):  # too short / invalid audio / no file -> treat as no match
                return {"status": "success", "result": None, "note": f"audd error {code}"}
            raise UpstreamError(f"audd error {code}: {msg}")
        return body

    async def recognize(self, audio: bytes, filename: str = "clip.webm") -> dict | None:
        """Recognize a clip. Returns normalized song metadata or None (no match).

        Raises :class:`UpstreamError` / :class:`AuddAuthError` on failure (callers degrade).
        """
        if len(audio) > self.MAX_BYTES:
            raise UpstreamError("clip exceeds AudD 10 MB limit")
        data = {"return": "deezer,musicbrainz"}
        if self.api_token:
            data["api_token"] = self.api_token
        body = await self.request("POST", "/", data=data, files={"file": (filename, audio)}, use_cache=False)
        return normalize_audd_result((body or {}).get("result"))


class MockAuddClient:
    """MOCK_EXTERNAL=1: fakes the AudD path from the recorded success fixture (no network).

    Any clip with audible content "matches" the fixture's song; digital silence returns None.
    """

    name = "audd-mock"

    def __init__(self, fixture: Path | None = None) -> None:
        path = fixture or FIXTURE_DIR / "audd_success.body"
        self._result = json.loads(path.read_text())["result"]

    async def recognize(self, audio: bytes, filename: str = "clip.webm", signal: np.ndarray | None = None) -> dict | None:
        await asyncio.sleep(0.05)  # emulate a network round trip
        if signal is not None and float(np.sqrt(np.mean(signal.astype(np.float64) ** 2))) < 1e-4:
            return None
        return normalize_audd_result(self._result)

    async def aclose(self) -> None:
        return None


class AcoustIdClient(BaseClient):
    """Optional AcoustID lookup of a Chromaprint fingerprint (comparison view only).

    Needs the ``fpcalc`` binary (Chromaprint) and ``ACOUSTID_API_KEY``. Documented limit: 3 req/s.
    """

    name = "acoustid"
    base_url = "https://api.acoustid.org"
    min_interval_s = 0.34

    def __init__(self, api_key: str = "", **kw: Any) -> None:
        super().__init__(**kw)
        self.api_key = api_key

    @staticmethod
    def fpcalc_available() -> bool:
        return shutil.which("fpcalc") is not None

    def check(self, resp: httpx.Response) -> Any:
        body = resp.json()
        if body.get("status") == "error":
            err = body.get("error") or {}
            raise UpstreamError(f"acoustid error {err.get('code')}: {err.get('message')}")
        resp.raise_for_status()
        return body

    @staticmethod
    async def fingerprint(path: Path) -> tuple[int, str] | None:
        if not AcoustIdClient.fpcalc_available():
            return None
        proc = await asyncio.create_subprocess_exec(
            "fpcalc", "-json", str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        d = json.loads(out)
        return int(round(d["duration"])), d["fingerprint"]

    async def lookup(self, duration: int, fingerprint: str) -> list[dict]:
        if not self.api_key:
            raise UpstreamError("ACOUSTID_API_KEY not set")
        body = await self.request(
            "GET", "/v2/lookup",
            params={"client": self.api_key, "duration": duration, "fingerprint": fingerprint, "meta": "recordings"},
            use_cache=False,
        )
        out = []
        for r in (body or {}).get("results", []):
            recs = r.get("recordings") or [{}]
            rec = recs[0]
            artists = ", ".join(a.get("name", "") for a in rec.get("artists", []))
            out.append({"acoustid": r.get("id"), "score": r.get("score"), "mbid": rec.get("id"),
                        "title": rec.get("title"), "artist": artists or None})
        return out
