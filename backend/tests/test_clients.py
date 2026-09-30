"""API client tests against recorded fixtures (requirement 7i). No live network calls:
every request goes through ``httpx.MockTransport``; unexpected requests fail the test."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.clients.base import UpstreamError
from app.clients.deezer import DeezerClient, ITunesClient
from app.clients.metadata import CoverArtClient, LrclibClient, MusicBrainzClient
from app.clients.recognizers import AcoustIdClient, AuddAuthError, AuddClient, MockAuddClient
from app.db import Database

FIX = Path(__file__).parent / "fixtures" / "api"


def body(name: str) -> bytes:
    return (FIX / f"{name}.body").read_bytes()


class Recorder:
    """Route table for MockTransport + a log of requests seen."""

    def __init__(self, routes):
        self.routes = routes  # list of (predicate, response-or-callable)
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        for pred, resp in self.routes:
            if pred(request):
                return resp(request) if callable(resp) else resp
        raise AssertionError(f"unexpected request {request.method} {request.url}")


def seq(*responses):
    """Return responses in order (last one repeats)."""
    it = list(responses)

    def f(_req):
        return it.pop(0) if len(it) > 1 else it[0]

    return f


def json_resp(status: int, raw: bytes, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, content=raw, headers={"content-type": "application/json", **(headers or {})})


async def no_sleep(_s: float) -> None:
    no_sleep.calls.append(_s)


no_sleep.calls = []


def make(cls, rec: Recorder, **kw):
    return cls(transport=httpx.MockTransport(rec), sleep=no_sleep, **kw)


# ------------------------------------------------------------------------------ Deezer
async def test_deezer_chart_normalizes_fixture():
    rec = Recorder([(lambda r: r.url.path == "/chart/0/tracks", json_resp(200, body("deezer_chart")))])
    d = make(DeezerClient, rec)
    tracks = await d.chart(limit=3)
    assert len(tracks) == 3
    t = tracks[0]
    assert t["deezer_id"] and t["title"] and t["artist"] and t["preview_url"].startswith("https://")
    assert t["isrc"] is None  # observed: chart items carry no ISRC
    assert rec.calls[0].url.params["limit"] == "3"


async def test_deezer_track_has_isrc_and_year():
    rec = Recorder([(lambda r: r.url.path == "/track/67238735", json_resp(200, body("deezer_track")))])
    t = await make(DeezerClient, rec).track(67238735)
    assert t["isrc"] == "USQX91300108" and t["year"] == 2013 and t["artist"] == "Daft Punk"
    assert t["cover_url"].endswith("1000x1000-000000-80-0-0.jpg")


async def test_deezer_not_found_is_none_even_with_http_200():
    rec = Recorder([(lambda r: True, json_resp(200, body("deezer_track_notfound")))])
    assert await make(DeezerClient, rec).track(1) is None


async def test_deezer_quota_error_retries_then_succeeds():
    rec = Recorder([(lambda r: True, seq(json_resp(200, body("synthetic_deezer_quota")),
                                         json_resp(200, body("deezer_track"))))])
    no_sleep.calls.clear()
    t = await make(DeezerClient, rec).track(67238735)
    assert t["deezer_id"] == 67238735 and len(rec.calls) == 2
    assert 5.0 in no_sleep.calls  # quota backoff


async def test_deezer_quota_exhausted_degrades():
    rec = Recorder([(lambda r: True, json_resp(200, body("synthetic_deezer_quota")))])
    d = make(DeezerClient, rec, retries=2)
    with pytest.raises(UpstreamError):
        await d.track(5)
    assert len(rec.calls) == 3
    assert await d.safe(d.track(5)) is None


async def test_deezer_search_playlist_artist_fixtures():
    rec = Recorder([
        (lambda r: r.url.path == "/search", json_resp(200, body("deezer_search"))),
        (lambda r: r.url.path.startswith("/playlist/"), json_resp(200, body("deezer_playlist_tracks"))),
        (lambda r: r.url.path.startswith("/artist/"), json_resp(200, body("deezer_artist_top"))),
    ])
    d = make(DeezerClient, rec)
    assert (await d.search("daft punk get lucky", limit=2))[0]["isrc"]
    assert len(await d.playlist_tracks(3155776842, limit=2)) == 2
    assert len(await d.artist_top(27, limit=2)) == 2


async def test_deezer_pagination_follows_next():
    page = json.loads(body("deezer_search"))
    last = {**page, "next": None}
    rec = Recorder([(lambda r: True, seq(json_resp(200, json.dumps(page).encode()),
                                         json_resp(200, json.dumps(last).encode())))])
    got = await make(DeezerClient, rec).search("x", limit=4)
    assert len(got) == 4 and rec.calls[1].url.params["index"] == "2"


async def test_network_failure_retries_with_exponential_backoff():
    def boom(req):
        raise httpx.ConnectError("down", request=req)

    rec = Recorder([(lambda r: True, boom)])
    no_sleep.calls.clear()
    d = make(DeezerClient, rec, retries=3, backoff_base_s=0.5)
    d.min_interval_s = 0
    with pytest.raises(UpstreamError):
        await d.chart(limit=1)
    assert no_sleep.calls == [0.5, 1.0, 2.0]


async def test_on_disk_cache_prevents_second_call(tmp_path):
    db = Database(tmp_path / "c.sqlite3")
    rec = Recorder([(lambda r: True, json_resp(200, body("deezer_track")))])
    d = make(DeezerClient, rec, cache=db)
    await d.track(67238735)
    await d.track(67238735)
    assert len(rec.calls) == 1
    # a new client instance (e.g. after restart) still hits the on-disk cache
    d2 = make(DeezerClient, rec, cache=Database(tmp_path / "c.sqlite3"))
    await d2.track(67238735)
    assert len(rec.calls) == 1


async def test_itunes_search_fixture():
    rec = Recorder([(lambda r: r.url.path == "/search", json_resp(200, body("itunes_search")))])
    res = await make(ITunesClient, rec).search("daft punk get lucky", limit=2)
    assert res and res[0]["artist"] and res[0]["preview_url"]


# ------------------------------------------------------------------------------ MusicBrainz
async def test_musicbrainz_isrc_and_user_agent():
    rec = Recorder([(lambda r: r.url.path.endswith("/isrc/USQX91300108"), json_resp(200, body("musicbrainz_isrc")))])
    mb = make(MusicBrainzClient, rec, user_agent="Blazam/0.1.0 ( test@example.org )")
    r = await mb.by_isrc("USQX91300108")
    assert r["mbid"] and r["year"] == 2013 and "Daft Punk" in r["artist"]
    assert rec.calls[0].headers["user-agent"] == "Blazam/0.1.0 ( test@example.org )"


async def test_musicbrainz_throttle_one_request_per_second():
    rec = Recorder([(lambda r: True, json_resp(200, body("musicbrainz_isrc")))])
    no_sleep.calls.clear()
    mb = make(MusicBrainzClient, rec)
    MusicBrainzClient._global_last = 0.0
    await mb.request("GET", "/isrc/A", use_cache=False)
    await mb.request("GET", "/isrc/B", use_cache=False)
    assert no_sleep.calls and 0.9 < no_sleep.calls[-1] <= 1.05


async def test_musicbrainz_503_then_success():
    rec = Recorder([(lambda r: True, seq(json_resp(503, body("synthetic_musicbrainz_503")),
                                         json_resp(200, body("musicbrainz_isrc"))))])
    r = await make(MusicBrainzClient, rec).by_isrc("USQX91300108")
    assert r and len(rec.calls) == 2


async def test_musicbrainz_not_found_and_release_groups():
    rec = Recorder([
        (lambda r: "/isrc/" in r.url.path, json_resp(404, body("musicbrainz_isrc_notfound"))),
        (lambda r: "/recording/" in r.url.path, json_resp(200, body("musicbrainz_recording_lookup"))),
        (lambda r: r.url.path.endswith("/recording"), json_resp(200, body("musicbrainz_recording_search"))),
    ])
    mb = make(MusicBrainzClient, rec)
    assert await mb.by_isrc("ZZZZ00000000") is None
    rgs = await mb.release_groups("833f00e1-781f-4edd-90e4-e52712618862")
    assert rgs and all(len(x) == 36 for x in rgs)
    assert (await mb.search_recording("Get Lucky", "Daft Punk"))["mbid"]


# ------------------------------------------------------------------------------ Cover Art Archive
async def test_coverart_redirect_means_exists_and_404_html_means_none():
    rec = Recorder([
        (lambda r: "aa997ea0" in r.url.path, httpx.Response(307, headers={"location": "https://archive.org/x.jpg"})),
        (lambda r: True, httpx.Response(404, content=body("caa_notfound"), headers={"content-type": "text/html"})),
    ])
    caa = make(CoverArtClient, rec)
    assert await caa.front_url("aa997ea0-2936-40bd-884d-3af8a0e064dc") == (
        "https://coverartarchive.org/release-group/aa997ea0-2936-40bd-884d-3af8a0e064dc/front-500")
    assert await caa.front_url("00000000-0000-0000-0000-000000000000") is None


# ------------------------------------------------------------------------------ LRCLIB
async def test_lrclib_get_and_404():
    rec = Recorder([
        (lambda r: r.url.params.get("artist_name") == "Daft Punk", json_resp(200, body("lrclib_get"))),
        (lambda r: True, json_resp(404, body("lrclib_get_notfound"))),
    ])
    lr = make(LrclibClient, rec)
    got = await lr.get("Get Lucky", "Daft Punk", "Random Access Memories", 369.2)
    assert got["plain"] and rec.calls[0].url.params["duration"] == "369"
    assert await lr.get("nonexistent", "zzz") is None


async def test_lrclib_429_honours_retry_after():
    rec = Recorder([(lambda r: True, seq(json_resp(429, body("synthetic_lrclib_429"), {"Retry-After": "3"}),
                                         json_resp(200, body("lrclib_get"))))])
    no_sleep.calls.clear()
    got = await make(LrclibClient, rec).get("Get Lucky", "Daft Punk")
    assert got and 3.0 in no_sleep.calls


# ------------------------------------------------------------------------------ AudD
async def test_audd_success_fixture_normalized():
    rec = Recorder([(lambda r: r.method == "POST", json_resp(200, body("audd_success")))])
    song = await make(AuddClient, rec, api_token="tok").recognize(b"\x00" * 100, "clip.mp3")
    assert song["title"].startswith("Get Lucky") and song["artist"] == "Daft Punk"
    assert song["deezer_id"] and song["preview_url"] and song["isrc"]
    sent = rec.calls[0].content
    assert b'name="api_token"' in sent and b'name="file"' in sent and b"deezer" in sent


async def test_audd_no_result_is_none():
    rec = Recorder([(lambda r: True, json_resp(200, body("audd_no_token")))])
    assert await make(AuddClient, rec).recognize(b"x", "a.wav") is None


@pytest.mark.parametrize("fixture", ["audd_bad_token", "synthetic_audd_901"])
async def test_audd_auth_errors_raise_and_degrade(fixture):
    rec = Recorder([(lambda r: True, json_resp(200, body(fixture)))])
    a = make(AuddClient, rec, api_token="bad")
    with pytest.raises(AuddAuthError):
        await a.recognize(b"x", "a.wav")
    assert await a.safe(a.recognize(b"x", "a.wav")) is None
    assert len(rec.calls) == 2  # auth errors are not retried


async def test_audd_rejects_oversized_clip_without_calling():
    rec = Recorder([])
    with pytest.raises(UpstreamError):
        await make(AuddClient, rec).recognize(b"x" * (10 * 1024 * 1024 + 1))
    assert rec.calls == []


async def test_mock_audd_uses_fixture_and_silence_is_none():
    import numpy as np

    m = MockAuddClient()
    assert (await m.recognize(b"x", signal=np.ones(100, np.float32) * 0.1))["artist"] == "Daft Punk"
    assert await m.recognize(b"x", signal=np.zeros(100, np.float32)) is None


# ------------------------------------------------------------------------------ AcoustID
async def test_acoustid_invalid_key_fixture():
    rec = Recorder([(lambda r: True, json_resp(400, body("acoustid_bad_key")))])
    a = make(AcoustIdClient, rec, api_key="invalidkey")
    with pytest.raises(UpstreamError, match="invalid API key"):
        await a.lookup(6, "AQAAAA")


async def test_acoustid_without_key_does_not_call():
    rec = Recorder([])
    with pytest.raises(UpstreamError):
        await make(AcoustIdClient, rec).lookup(6, "AQAAAA")
    assert rec.calls == []


async def test_deezer_chart_pagination_without_next_or_total():
    """Regression: observed /chart/0/tracks pages have no 'next' and total == page size."""
    one = json.loads(body("deezer_chart"))["data"][0]

    def page(req):
        idx, lim = int(req.url.params["index"]), int(req.url.params["limit"])
        n = max(0, min(lim, 250 - idx))
        data = [{**one, "id": idx + i + 1} for i in range(n)]
        return json_resp(200, json.dumps({"data": data, "total": n}).encode())

    rec = Recorder([(lambda r: True, page)])
    got = await make(DeezerClient, rec).chart(limit=300)
    assert len(got) == 250 and len({t["deezer_id"] for t in got}) == 250
