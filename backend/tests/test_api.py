"""HTTP contract + threshold routing tests (requirement 7i).

A real Services stack is used (SQLite in a temp dir, real DSP, real job manager), with every
outbound HTTP call served by ``httpx.MockTransport`` from recorded fixtures.
"""

from __future__ import annotations

import dataclasses
import io
import json
import subprocess
import time
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app.config import MATCH, SETTINGS
from app.db import Database
from app.engine import Engine
from app.main import create_app
from app.services import Clients, Services
from tests.synth import SR, make_song

FIX = Path(__file__).parent / "fixtures" / "api"
NO_PREVIEW_ID = 424242  # a Deezer track whose preview is empty (43 real tracks behaved like this)
UNINDEXED_SEED = 404  # the synthetic "song" AudD will recognise and we will auto-learn
LEARN_DEEZER_ID = json.loads((FIX / "audd_success.body").read_text())["result"]["deezer"]["id"]


def wav_bytes(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, x, SR, format="WAV", subtype="FLOAT")
    return buf.getvalue()


def mp3_bytes(x: np.ndarray, tmp: Path) -> bytes:
    src, dst = tmp / "p.wav", tmp / "p.mp3"
    sf.write(src, x, SR, subtype="FLOAT")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-b:a", "128k", str(dst)], check=True)
    return dst.read_bytes()


class Upstream:
    """Fake internet. ``audd_mode``: 'hit' | 'none' | 'down'."""

    def __init__(self, preview_mp3: bytes) -> None:
        self.audd_mode = "hit"
        self.mb_down = False
        self.preview = preview_mp3
        self.calls: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(f"{req.method} {req.url.host}{req.url.path}")
        host = req.url.host
        if host == "api.audd.io":
            if self.audd_mode == "down":
                raise httpx.ConnectError("audd down", request=req)
            name = "audd_success" if self.audd_mode == "hit" else "audd_no_token"
            return httpx.Response(200, content=(FIX / f"{name}.body").read_bytes())
        if host == "cdnt-preview.dzcdn.net":
            return httpx.Response(200, content=self.preview, headers={"content-type": "audio/mpeg"})
        if host == "api.deezer.com" and req.url.path == f"/track/{NO_PREVIEW_ID}":
            t = json.loads((FIX / "deezer_track.body").read_text())
            return httpx.Response(200, content=json.dumps({**t, "id": NO_PREVIEW_ID, "preview": ""}).encode())
        if host == "api.deezer.com" and req.url.path.startswith("/track/"):
            return httpx.Response(200, content=(FIX / "deezer_track.body").read_bytes())
        if host == "itunes.apple.com" and req.url.path == "/search":
            return httpx.Response(200, content=(FIX / "itunes_search.body").read_bytes())
        if host == "audio-ssl.itunes.apple.com":
            return httpx.Response(200, content=self.preview, headers={"content-type": "audio/x-m4p"})
        if host == "api.deezer.com" and req.url.path.startswith("/chart/"):
            return httpx.Response(200, content=(FIX / "deezer_chart.body").read_bytes())
        if host == "musicbrainz.org" and self.mb_down:
            raise httpx.ConnectError("musicbrainz down", request=req)
        if host == "musicbrainz.org" and "/isrc/" in req.url.path:
            return httpx.Response(200, content=(FIX / "musicbrainz_isrc.body").read_bytes())
        if host == "musicbrainz.org" and "/recording/" in req.url.path:
            return httpx.Response(200, content=(FIX / "musicbrainz_recording_lookup.body").read_bytes())
        if host == "coverartarchive.org":
            return httpx.Response(307, headers={"location": "https://archive.org/x.jpg"})
        if host == "lrclib.net":
            return httpx.Response(200, content=(FIX / "lrclib_get.body").read_bytes())
        return httpx.Response(599, content=b"unexpected")


@pytest.fixture()
def env(tmp_path):
    songs = {sid: make_song(seed=sid, duration=30.0) for sid in (1, 2, 3)}
    unindexed = make_song(seed=UNINDEXED_SEED, duration=30.0)
    up = Upstream(mp3_bytes(unindexed, tmp_path))
    settings = dataclasses.replace(SETTINGS, data_dir=tmp_path, auto_learn=True, mock_external=False,
                                   lyrics_enabled=True)

    async def factory() -> Services:
        db = Database(tmp_path / "t.sqlite3")
        engine = Engine(db)
        for sid, x in songs.items():
            engine.index_signal(x, {"title": f"Synth {sid}", "artist": "Test", "source": "seed"})
        engine.load_index()
        clients = Clients.create(cache=db, settings=settings, transport=httpx.MockTransport(up),
                                 sleep=_fast_sleep)
        return Services(engine, clients, settings)

    with TestClient(create_app(factory)) as client:
        yield client, songs, unindexed, up


async def _fast_sleep(_s: float) -> None:
    return None


def recognize(client, x: np.ndarray, name: str = "clip.wav"):
    return client.post("/api/recognize", files={"audio": (name, wav_bytes(x), "audio/wav")})


def wait_job(client, job_id: str, timeout: float = 30.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise TimeoutError(job_id)


CONTRACT_KEYS = {"status", "source", "confidence", "score", "offset_seconds", "latency_ms", "song", "learned"}
SONG_KEYS = {"id", "title", "artist", "album", "year", "cover_url", "deezer_id", "mbid", "preview_url"}


def test_route_own_match(env):
    client, songs, _, up = env
    r = recognize(client, songs[2][int(9.0 * SR): int(15.0 * SR)])
    assert r.status_code == 200
    d = r.json()
    assert set(d) == CONTRACT_KEYS
    assert d["status"] == "match" and d["source"] == "own" and d["learned"] is False
    assert d["song"]["title"] == "Synth 2" and SONG_KEYS <= set(d["song"])
    assert d["score"] >= MATCH.MIN_SCORE and 0 < d["confidence"] <= 1
    assert abs(d["offset_seconds"] - 9.0) < 0.05
    assert not any("audd" in c for c in up.calls), "Tier 2 must not be called when Tier 1 matches"


def test_route_external_then_auto_learn_then_own(env):
    client, _, unindexed, up = env
    clip = unindexed[int(5.0 * SR): int(12.0 * SR)]
    d = recognize(client, clip).json()
    assert d["status"] == "match" and d["source"] == "external"
    assert d["song"]["deezer_id"] == LEARN_DEEZER_ID and d["song"]["id"] is None
    assert d["learned"] is True
    assert d["score"] < MATCH.MIN_SCORE or d["confidence"] is None
    # the learn job runs in the background: wait for it via the jobs API
    svc = client.app.state.svc
    job_ids = [j.id for j in svc.jobs.jobs.values() if j.kind == "auto_learn"]
    assert len(job_ids) == 1
    job = wait_job(client, job_ids[0])
    assert job["status"] == "done", job
    lib = client.get("/api/library", params={"q": "Get Lucky"}).json()
    assert lib["total"] == 1 and lib["items"][0]["source"] == "learned"
    # the same clip is now recognised by our own engine
    d2 = recognize(client, clip).json()
    assert d2["source"] == "own" and d2["song"]["deezer_id"] == LEARN_DEEZER_ID
    # and a repeated external hit for a known song does not learn twice
    assert svc.schedule_learn({"deezer_id": LEARN_DEEZER_ID}) is False


def test_route_no_match_when_external_has_no_result(env):
    client, _, _, up = env
    up.audd_mode = "none"
    x = np.random.default_rng(0).standard_normal(6 * SR).astype(np.float32) * 0.2
    d = recognize(client, x).json()
    assert d == {**d, "status": "no_match", "source": None, "song": None, "learned": False}
    assert d["score"] < MATCH.MIN_SCORE


def test_route_no_match_when_external_is_down(env):
    client, _, unindexed, up = env
    up.audd_mode = "down"
    d = recognize(client, unindexed[: 6 * SR]).json()
    assert d["status"] == "no_match" and d["source"] is None


def test_history_and_stats_track_routes(env):
    client, songs, unindexed, up = env
    recognize(client, songs[1][: 6 * SR])
    up.audd_mode = "none"
    recognize(client, np.zeros(6 * SR, np.float32))
    h = client.get("/api/history", params={"limit": 10}).json()["items"]
    assert [i["status"] for i in h] == ["no_match", "match"]
    s = client.get("/api/stats").json()
    assert set(s) == {"total_songs", "total_hashes", "own_count", "external_count", "no_match_count",
                      "avg_latency_own_ms", "avg_latency_external_ms"}
    assert s["own_count"] == 1 and s["no_match_count"] == 1 and s["total_songs"] == 3
    assert s["avg_latency_own_ms"] > 0


def test_bad_uploads(env):
    client, *_ = env
    assert client.post("/api/recognize", files={"audio": ("x.wav", b"", "audio/wav")}).status_code == 400
    assert client.post("/api/recognize", files={"audio": ("x.webm", b"not audio", "audio/webm")}).status_code == 422
    assert client.post("/api/recognize").status_code == 422


def test_recognize_webm_opus_upload(env, tmp_path):
    client, songs, *_ = env
    src, dst = tmp_path / "c.wav", tmp_path / "c.webm"
    sf.write(src, songs[3][int(3 * SR): int(10 * SR)], SR, subtype="FLOAT")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-c:a", "libopus", "-b:a", "64k",
                    str(dst)], check=True)
    r = client.post("/api/recognize", files={"audio": ("c.webm", dst.read_bytes(), "audio/webm")})
    d = r.json()
    assert d["source"] == "own" and d["song"]["title"] == "Synth 3", d


def test_upload_job_and_sse_stream(env, tmp_path):
    client, *_ = env
    x = make_song(seed=777, duration=12.0)
    r = client.post("/api/library/upload", files=[
        ("files", ("Test Artist - Uploaded Song.wav", wav_bytes(x), "audio/wav")),
        ("files", ("notes.txt", b"hello", "text/plain")),
    ])
    job_id = r.json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as s:
        events = [line for line in s.iter_lines() if line.startswith("event:")]
    assert events[-1] == "event: end"
    j = client.get(f"/api/jobs/{job_id}").json()
    assert set(j) >= {"status", "done", "total", "current_title", "errors"}
    assert j["status"] == "done" and j["done"] == 2 and j["total"] == 2 and len(j["errors"]) == 1
    lib = client.get("/api/library", params={"q": "Uploaded"}).json()
    assert lib["items"][0]["artist"] == "Test Artist" and lib["items"][0]["title"] == "Uploaded Song"
    d = recognize(client, x[2 * SR: 8 * SR]).json()
    assert d["source"] == "own" and d["song"]["title"] == "Uploaded Song"


def test_import_job_from_deezer_chart_fixture(env):
    client, *_ = env
    r = client.post("/api/library/import", json={"source": "deezer", "chart": True, "limit": 3})
    j = wait_job(client, r.json()["job_id"])
    assert j["status"] == "done" and j["total"] == 3 and j["done"] == 3
    assert client.post("/api/library/import", json={"source": "deezer", "limit": 3}).status_code == 422
    assert client.get("/api/jobs/doesnotexist").status_code == 404


def test_library_pagination_and_health(env):
    client, *_ = env
    p = client.get("/api/library", params={"page": 1, "page_size": 2}).json()
    assert p["total"] == 3 and len(p["items"]) == 2 and p["page_size"] == 2
    p2 = client.get("/api/library", params={"page": 2, "page_size": 2}).json()
    assert len(p2["items"]) == 1
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["index_loaded"] and h["songs_indexed"] == 3


def test_cors_allows_frontend_origin(env):
    client, *_ = env
    r = client.options("/api/health", headers={"Origin": "http://localhost:3000",
                                               "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_enrichment_fills_metadata_via_fixtures(env):
    client, *_ = env
    svc = client.app.state.svc
    sid = svc.db.list_songs()[0][0]["id"]
    svc.db.update_song(sid, title="Get Lucky", artist="Daft Punk", isrc="USQX91300108")
    song = client.portal.call(svc.enrich, sid)
    assert song["mbid"] == "833f00e1-781f-4edd-90e4-e52712618862" and song["year"] == 2013
    assert song["cover_url"].startswith("https://coverartarchive.org/release-group/")
    assert json.loads(song["lyrics"])["plain"]
    r = client.get("/api/library", params={"q": "Get Lucky"}).json()["items"][0]
    assert r["mbid"] and r["has_lyrics"] is True


def test_mock_external_mode_routes_without_network(tmp_path):
    """MOCK_EXTERNAL=1: Tier-2 answers from the recorded fixture; AudD is never contacted."""
    settings = dataclasses.replace(SETTINGS, data_dir=tmp_path, auto_learn=False, mock_external=True)
    seen: list[str] = []

    def no_network(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(599)

    async def factory() -> Services:
        db = Database(tmp_path / "m.sqlite3")
        engine = Engine(db)
        engine.index_signal(make_song(seed=1, duration=20.0), {"title": "Synth 1", "artist": "T", "source": "seed"})
        engine.load_index()
        return Services(engine, Clients.create(cache=db, settings=settings,
                                               transport=httpx.MockTransport(no_network)), settings)

    with TestClient(create_app(factory)) as client:
        d = recognize(client, make_song(seed=555, duration=8.0)).json()
        assert d["status"] == "match" and d["source"] == "external" and d["song"]["artist"] == "Daft Punk"
        assert d["learned"] is False  # auto-learn disabled in this test
        silent = recognize(client, np.zeros(5 * SR, np.float32)).json()
        assert silent["status"] == "no_match"
        assert client.get("/api/health").json()["external_recognizer"] == "mock"
    assert not any("audd" in u for u in seen)


def test_enrichment_degrades_when_musicbrainz_is_down(env):
    """MB unreachable: year still comes from Deezer /track, the Deezer cover is kept, nothing raises."""
    client, _, _, up = env
    up.mb_down = True
    svc = client.app.state.svc
    sid = svc.db.list_songs()[0][0]["id"]
    deezer_cover = "https://cdn-images.dzcdn.net/images/cover/x/1000x1000-000000-80-0-0.jpg"
    svc.db.update_song(sid, title="Get Lucky", artist="Daft Punk", isrc="USQX91300108", cover_url=deezer_cover)
    svc.db._conn.execute("UPDATE songs SET deezer_id = 67238735, year = NULL WHERE id = ?", (sid,))
    song = client.portal.call(svc.enrich, sid)
    assert song["year"] == 2013  # from the Deezer /track fixture (release_date 2013-05-20)
    assert song["mbid"] is None and song["cover_url"] == deezer_cover


def test_itunes_preview_fallback_when_deezer_has_none(env):
    client, _, unindexed, _ = env
    svc = client.app.state.svc
    svc.clients.itunes.min_interval_s = 0
    meta = {"deezer_id": NO_PREVIEW_ID, "title": "Get Lucky", "artist": "Daft Punk", "preview_url": None}
    song_id, created = client.portal.call(svc._index_deezer_track, meta, "seed")
    s = svc.db.get_song(song_id)
    assert created and s["audio_path"].endswith(".itunes.m4a")
    assert s["preview_url"].startswith("https://audio-ssl.itunes.apple.com/")
    d = recognize(client, unindexed[4 * SR: 11 * SR]).json()  # the fake iTunes preview's audio
    assert d["source"] == "own" and d["song"]["id"] == song_id


def test_itunes_fallback_refuses_a_different_recording(env):
    client, *_ = env
    svc = client.app.state.svc
    svc.clients.itunes.min_interval_s = 0
    from app.clients.base import UpstreamError

    meta = {"deezer_id": NO_PREVIEW_ID, "title": "Some Other Song", "artist": "Daft Punk", "preview_url": None}
    with pytest.raises(UpstreamError, match="no preview on Deezer or iTunes"):
        client.portal.call(svc._index_deezer_track, meta, "seed")
    assert svc.db.find_song(deezer_id=NO_PREVIEW_ID) is None


def test_preview_endpoint_serves_local_audio_and_urls_point_to_it(env, tmp_path):
    """Deezer preview URLs expire ~15 min after issue; library songs must use our own endpoint."""
    client, *_ = env
    x = make_song(seed=4242, duration=12.0)
    job = client.post("/api/library/upload",
                      files=[("files", ("Preview Artist - Preview Song.wav", wav_bytes(x), "audio/wav"))]).json()
    assert wait_job(client, job["job_id"])["status"] == "done"
    item = client.get("/api/library", params={"q": "Preview Song"}).json()["items"][0]
    url = f"/api/songs/{item['id']}/preview"
    assert item["preview_url"] == f"http://testserver{url}"

    r = client.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF" and len(r.content) > 100_000
    part = client.get(url, headers={"Range": "bytes=0-99"})  # browsers seek with Range requests
    assert part.status_code == 206 and len(part.content) == 100

    d = recognize(client, x[3 * SR: 9 * SR]).json()
    assert d["source"] == "own" and d["song"]["preview_url"] == f"http://testserver{url}"
    hist = client.get("/api/history", params={"limit": 1}).json()["items"][0]
    assert hist["song"]["preview_url"] == f"http://testserver{url}"

    assert client.get("/api/songs/999999/preview").status_code == 404
    # a song without an audio file keeps its stored URL instead of pointing at a 404
    synth = client.get("/api/library", params={"q": "Synth 1"}).json()["items"][0]
    assert synth["preview_url"] is None and client.get(f"/api/songs/{synth['id']}/preview").status_code == 404
