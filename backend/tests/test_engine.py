"""Engine persistence: SQLite load, index snapshot round-trip and invalidation."""

from __future__ import annotations

import numpy as np

from app.db import Database
from app.engine import Engine
from tests.synth import SR, make_song


def _engine(tmp_path) -> Engine:
    return Engine(Database(tmp_path / "lib.sqlite3"))


def test_snapshot_roundtrip_matches_sqlite_load(tmp_path):
    e = _engine(tmp_path)
    for sid in (1, 2, 3):
        e.index_signal(make_song(seed=sid, duration=15.0), {"title": f"S{sid}", "artist": "T", "source": "seed"})
    info = e.load_index()  # first load: from SQLite, writes the snapshot
    assert info["source"] == "sqlite" and e.snapshot_path.is_file()
    ref = e.index.export()

    e2 = _engine(tmp_path)
    info2 = e2.load_index()
    assert info2["source"] == "snapshot" and info2["songs"] == 3
    for a, b in zip(ref, e2.index.export()):
        assert np.array_equal(a, b)
    r = e2.identify(make_song(seed=2, duration=15.0)[3 * SR: 9 * SR])
    assert r.matched and e2.db.get_song(r.song_id)["title"] == "S2"


def test_snapshot_invalidated_when_library_changes(tmp_path):
    e = _engine(tmp_path)
    e.index_signal(make_song(seed=1, duration=10.0), {"title": "S1", "artist": "T", "source": "seed"})
    e.load_index()
    # another process adds a song directly to the DB: the old snapshot must not be used
    other = _engine(tmp_path)
    other.index_signal(make_song(seed=2, duration=10.0), {"title": "S2", "artist": "T", "source": "seed"})
    e3 = _engine(tmp_path)
    info = e3.load_index()
    assert info["source"] == "sqlite" and info["songs"] == 2


def test_dirty_index_saved_and_corrupt_snapshot_ignored(tmp_path):
    e = _engine(tmp_path)
    e.load_index()
    e.index_signal(make_song(seed=5, duration=10.0), {"title": "S5", "artist": "T", "source": "seed"})
    assert e.save_snapshot_if_dirty() is not None
    assert e.save_snapshot_if_dirty() is None  # clean now
    assert _engine(tmp_path).load_index()["source"] == "snapshot"
    e.snapshot_path.write_bytes(b"not a zip file")
    info = _engine(tmp_path).load_index()
    assert info["source"] == "sqlite" and info["songs"] == 1


def test_audio_paths_are_relative_and_legacy_paths_resolve(tmp_path):
    import soundfile as sf

    from app.engine import resolve_audio_path

    data = tmp_path / "data"
    (data / "previews").mkdir(parents=True)
    wav = data / "previews" / "1.wav"
    sf.write(wav, make_song(seed=8, duration=6.0), SR)
    e = Engine(Database(data / "lib.sqlite3"))
    sid, _ = e.index_file(wav, {"title": "S8", "artist": "T", "source": "seed"})
    assert e.db.get_song(sid)["audio_path"] == "previews/1.wav"
    # a legacy absolute path from another machine resolves by its suffix under the data dir
    assert resolve_audio_path(data, "/Users/someone/proj/data/previews/1.wav") == data / "previews" / "1.wav"
    e.db.set_audio_path(sid, str(wav))  # legacy absolute row
    assert e.migrate_audio_paths() == 1 and e.db.get_song(sid)["audio_path"] == "previews/1.wav"
    assert resolve_audio_path(data, "/nowhere/x.wav") is None
