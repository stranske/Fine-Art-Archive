"""Store recovery must preserve healthy neighbors and uncertainty about unreadable files."""

import json

import pytest

from fine_art_archive.api import store


@pytest.fixture
def facts_cache(tmp_path, monkeypatch):
    path = tmp_path / "facts.json"
    monkeypatch.setattr(store, "MASTER_FACTS_CACHE", path)
    monkeypatch.setattr(store, "_MASTER_FACTS", {})
    monkeypatch.setattr(store, "_MASTER_FACTS_LOADED", False)
    monkeypatch.setattr(store, "_MASTER_FACTS_DIRTY", False)
    return path


@pytest.mark.parametrize("raw", [[], {"entries": []}, {"entries": None}])
def test_invalid_facts_cache_shape_is_recoverable(facts_cache, raw):
    facts_cache.write_text(json.dumps(raw))
    store._load_master_facts()
    assert store._MASTER_FACTS == {}
    assert store._MASTER_FACTS_LOADED is True


def test_invalid_and_unchecked_facts_do_not_discard_healthy_neighbor(facts_cache):
    facts_cache.write_text(
        json.dumps(
            {
                "entries": {
                    "bad-key": [[10, 20], 1.0, "ok"],
                    "bad-number\u0000no-mtime\u00002": [[10, 20], 1.0, "ok"],
                    "bad-pixels\u00001\u00002": [[10], 1.0, "ok"],
                    "unchecked\u00001\u00002": [None, 1.0, "unchecked"],
                    "healthy\u00003\u00004": [[30, 40], 2.0, "ok"],
                }
            }
        )
    )
    store._load_master_facts()
    assert store._MASTER_FACTS == {("healthy", 3, 4): ((30, 40), 2.0, "ok")}


def test_failed_cache_flush_preserves_existing_file(facts_cache, monkeypatch):
    facts_cache.write_text("previous cache")
    monkeypatch.setattr(store, "_MASTER_FACTS_DIRTY", True)
    original_replace = type(facts_cache).replace

    def refuse_replace(self, target):
        if target == facts_cache:
            raise PermissionError("cache temporarily read-only")
        return original_replace(self, target)

    monkeypatch.setattr(type(facts_cache), "replace", refuse_replace)
    store.flush_master_facts()
    assert facts_cache.read_text() == "previous cache"


def test_full_facts_cache_evicts_old_entries_and_keeps_current_master(
    facts_cache, tmp_path, monkeypatch
):
    master = tmp_path / "master.png"
    master.write_bytes(b"image placeholder")
    monkeypatch.setattr(store, "_MASTER_FACTS_MAX", 1)
    store._MASTER_FACTS.update(
        {("old-a", 1, 2): (None, 0.1, "ok"), ("old-b", 1, 2): (None, 0.1, "ok")}
    )
    monkeypatch.setattr(store, "_image_pixels", lambda _path: (30, 40))
    monkeypatch.setattr(store, "_master_health", lambda _path: "ok")
    assert store._master_facts(master) == ((30, 40), 0.0, "ok", False)
    assert len(store._MASTER_FACTS) == 1
    assert next(iter(store._MASTER_FACTS))[0] == str(master)


def test_unreadable_image_has_unknown_dimensions(tmp_path):
    corrupt = tmp_path / "master.jpg"
    corrupt.write_bytes(b"not an image")
    assert store._image_pixels(corrupt) is None


def test_invalid_work_id_has_unchecked_health():
    assert store.master_health("../outside") == "unchecked"


def test_symlinked_work_cannot_escape_archive(tmp_path):
    archive = tmp_path / "works"
    archive.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (archive / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="work_id path escapes archive root"):
        store.contained_work_path(archive, "linked", "meta.json")


def test_unreadable_dossier_sidecar_does_not_hide_healthy_work(tmp_path, monkeypatch):
    for name in ("blocked", "healthy"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "meta.json").write_text('{"dossier": {"viewer_summary": "A work"}}')
    monkeypatch.setattr(store, "WORKS", tmp_path)
    monkeypatch.setattr(store, "_dossier_cache", {"sig": None, "ids": frozenset()})
    original_read = type(tmp_path).read_text

    def read(self, *args, **kwargs):
        if self == tmp_path / "blocked" / "meta.json":
            raise PermissionError("temporarily unreadable")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "read_text", read)
    assert store.work_ids_with_dossier() == frozenset({"healthy"})


def test_corrupt_sidecar_does_not_hide_acquisitions_or_artist_identities(
    tmp_path, monkeypatch, facts_cache
):
    for name, text in [
        ("broken", "not json"),
        (
            "healthy",
            json.dumps(
                {
                    "title": "A work",
                    "artist": {"name": "Painter", "wikidata_q": "Q123"},
                    "history": [{"ts": "2026-10-01", "actor": "automation"}],
                }
            ),
        ),
    ]:
        directory = tmp_path / name
        directory.mkdir()
        (directory / "meta.json").write_text(text)
    monkeypatch.setattr(store, "WORKS", tmp_path)
    monkeypatch.setattr(store, "_artist_qid_cache", {"sig": None, "qids": frozenset()})
    monkeypatch.setattr(store, "_acq_cache", {"sig": None, "rows": []})
    assert store.known_artist_qids() == frozenset({"Q123"})
    rows = store.acquisitions_since_epoch("2026-09-01")
    assert [row["work_id"] for row in rows] == ["healthy"]
    assert rows[0]["file_health"] == "unchecked"
