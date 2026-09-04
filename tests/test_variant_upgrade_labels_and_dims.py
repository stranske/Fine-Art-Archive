"""Two ways the upgrade surface reported something other than what is on disk.

1. The gate read `artist_name` from the detector CSV. The detector emits
   `artist`. Nothing errored — every gate item simply carried a blank artist,
   while the same row rendered the name correctly in the upgrade table.
2. `_image_dims` was `lru_cache`d on the path alone. A promotion replaces
   `works/<wid>/master.*` in place, so the path survives the swap and the cache
   went on reporting the superseded pixel count — the number the table shows to
   justify the next swap.

Both are the same failure: a value that looks authoritative and is stale.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store


@pytest.fixture
def upgrade_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    works = tmp_path / "works"
    (works / "abc1234-a-work").mkdir(parents=True)
    # The gate excludes rows whose candidate is no longer on disk, so every
    # fixture row needs a real file or it is filtered before the labels matter.
    candidate = works / "abc1234-a-work" / "candidate.jpg"
    candidate.write_bytes(b"candidate")
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "VARIANT_CANDIDATE_ROOTS", (works,))
    monkeypatch.setattr(
        api_main, "VARIANT_UPGRADE_DECISIONS", tmp_path / "variant_upgrade_decisions.jsonl"
    )
    csv_path = tmp_path / "variant_upgrade_candidates.csv"
    monkeypatch.setattr(api_main, "VARIANT_UPGRADE_CSV", csv_path)
    return {"root": tmp_path, "works": works, "csv": csv_path, "candidate": candidate}


# --------------------------------------------------------------------------
# 1. The artist the detector actually emits.
# --------------------------------------------------------------------------
def _detector_row(candidate: Path, **extra: str) -> str:
    """A row shaped the way `Claude Project/scripts/detect_variant_upgrades.py`
    writes it — `artist`, never `artist_name`."""
    header = ["existing_wid", "title", "artist", "candidate_path", *extra]
    values = ["abc1234-a-work", "A Work", "Rembrandt van Rijn", str(candidate), *extra.values()]
    return ",".join(header) + "\n" + ",".join(values) + "\n"


def test_gate_item_carries_the_artist_the_csv_spells_artist(
    upgrade_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade_env["csv"].write_text(_detector_row(upgrade_env["candidate"]), encoding="utf-8")
    monkeypatch.setattr(api_store, "get_manifest_row", lambda _wid: None)
    monkeypatch.setattr(api_store, "get_work", lambda _wid: None)

    gate = api_main._variant_upgrade_gate()
    assert gate.blocking == 1
    item = gate.items[0]
    assert item["artist_name"] == "Rembrandt van Rijn", "gate must not render a blank artist"
    assert item["title"] == "A Work"


def test_archive_outranks_the_csv_for_both_labels(
    upgrade_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CSV is input this app does not write; the archive owns these fields."""
    upgrade_env["csv"].write_text(_detector_row(upgrade_env["candidate"]), encoding="utf-8")
    monkeypatch.setattr(
        api_store,
        "get_manifest_row",
        lambda _wid: {
            "work_id": "abc1234-a-work",
            "title": "The Night Watch",
            "artist_name": "Rembrandt Harmenszoon van Rijn",
            "artist_wikidata_q": "Q5598",
        },
    )

    item = api_main._variant_upgrade_gate().items[0]
    assert item["title"] == "The Night Watch"
    assert item["artist_name"] == "Rembrandt Harmenszoon van Rijn"


def test_artist_name_spelling_still_works(upgrade_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """A producer that emits `artist_name` must keep working — accept both."""
    upgrade_env["csv"].write_text(
        "existing_wid,title,artist_name,candidate_path\n"
        f"abc1234-a-work,A Work,Johannes Vermeer,{upgrade_env['candidate']}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api_store, "get_manifest_row", lambda _wid: None)
    monkeypatch.setattr(api_store, "get_work", lambda _wid: None)

    assert api_main._variant_upgrade_gate().items[0]["artist_name"] == "Johannes Vermeer"


def test_listing_publishes_both_spellings(upgrade_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """The UI reads `c.artist`, the gate reads `artist_name`. Serve both."""
    upgrade_env["csv"].write_text(_detector_row(upgrade_env["candidate"]), encoding="utf-8")
    monkeypatch.setattr(api_store, "get_manifest_row", lambda _wid: None)
    monkeypatch.setattr(api_store, "get_work", lambda _wid: None)

    with TestClient(api_main.app) as client:
        row = client.get("/variant_upgrades").json()["candidates"][0]
    assert row["artist"] == "Rembrandt van Rijn"
    assert row["artist_name"] == row["artist"]


def test_missing_artist_everywhere_is_empty_not_an_error(
    upgrade_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade_env["csv"].write_text(
        "existing_wid,title,candidate_path\n" f"abc1234-a-work,A Work,{upgrade_env['candidate']}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api_store, "get_manifest_row", lambda _wid: None)
    monkeypatch.setattr(api_store, "get_work", lambda _wid: None)

    assert api_main._variant_upgrade_gate().items[0]["artist_name"] == ""


def test_malformed_work_id_is_filtered_not_rendered(
    upgrade_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad id in untrusted input drops out; it must not 500 or render."""
    upgrade_env["csv"].write_text(
        "existing_wid,title,artist,candidate_path\n"
        f"../etc/passwd,Bad,Nobody,{upgrade_env['candidate']}\n",
        encoding="utf-8",
    )
    gate = api_main._variant_upgrade_gate()
    assert gate.blocking == 0, "a row whose work id cannot resolve is not a pending decision"
    assert gate.items == []


def test_stale_row_command_names_a_script_that_exists(
    upgrade_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate's stated drain must be runnable.

    It printed a bare `python3 scripts/detect_variant_upgrades.py`, but the
    detector is a WORKSPACE script — no such file in a checkout. A gate that
    names a drain nobody can run is the defect this whole area keeps repeating.
    """
    command = api_main.VARIANT_DETECT_COMMAND
    script = command.split(" ", 1)[1]
    assert Path(
        script
    ).is_absolute(), "a relative command runs in whatever directory the shell is in"
    assert Path(script).name == "detect_variant_upgrades.py"


# --------------------------------------------------------------------------
# 2. Dimensions must follow an in-place replacement.
# --------------------------------------------------------------------------
def test_image_dims_follows_an_in_place_replacement(tmp_path: Path) -> None:
    """The promotion case: same path, new pixels, and the cache must not lie."""
    master = tmp_path / "master.jpg"
    Image.new("RGB", (400, 300), "navy").save(master)
    assert api_main._image_dims(master) == "400x300"

    # Exactly what a promotion does — overwrite in place.
    Image.new("RGB", (4000, 3000), "navy").save(master)
    assert api_main._image_dims(master) == "4000x3000", (
        "dimensions came from a path-keyed cache; a promoted master reports its "
        "superseded size for the life of the process"
    )


def test_image_dims_same_second_size_change_is_seen(tmp_path: Path) -> None:
    """Size is in the key too: mtime alone need not separate two writes."""
    p = tmp_path / "m.jpg"
    Image.new("RGB", (64, 64), "red").save(p)
    first = api_main._image_dims(p)
    Image.new("RGB", (128, 96), "red").save(p)
    import os

    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # keep mtime; size differs
    assert first == "64x64"
    assert api_main._image_dims(p) == "128x96"


def test_image_dims_handles_missing_and_non_files(tmp_path: Path) -> None:
    assert api_main._image_dims(None) is None
    assert api_main._image_dims(tmp_path / "nope.jpg") is None
    assert api_main._image_dims(tmp_path) is None, "a directory is not an image"


def test_image_dims_non_image_bytes_are_none(tmp_path: Path) -> None:
    junk = tmp_path / "junk.jpg"
    junk.write_bytes(b"not an image")
    assert api_main._image_dims(junk) is None


def test_listing_reports_promoted_pixels(upgrade_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: the number the upgrade table shows tracks the file on disk."""
    work_dir = upgrade_env["works"] / "abc1234-a-work"
    master = work_dir / "master.jpg"
    Image.new("RGB", (400, 300), "navy").save(master)
    (work_dir / "meta.json").write_text(
        json.dumps({"work_id": "abc1234-a-work", "files": {"master": {"filename": "master.jpg"}}}),
        encoding="utf-8",
    )
    upgrade_env["csv"].write_text(_detector_row(upgrade_env["candidate"]), encoding="utf-8")
    monkeypatch.setattr(api_store, "get_manifest_row", lambda _wid: None)
    monkeypatch.setattr(api_store, "get_work", lambda _wid: None)

    with TestClient(api_main.app) as client:
        assert client.get("/variant_upgrades").json()["candidates"][0]["existing_px"] == "400x300"
        Image.new("RGB", (4000, 3000), "navy").save(master)
        assert client.get("/variant_upgrades").json()["candidates"][0]["existing_px"] == "4000x3000"


# --------------------------------------------------------------------------
# 3. The producer and the reader must be able to name the same file.
# --------------------------------------------------------------------------
def test_variant_upgrade_paths_take_an_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The detector is a workspace script and writes beside itself.

    `VARIANT_UPGRADE_CSV` defaulted to REPO_ROOT with no seam, so the producer
    wrote `Claude Project/variant_upgrade_candidates.csv` and the app read a repo
    path that has never existed. The screen rendered "no candidates" — the same
    thing it says when the detector genuinely found none.
    """
    import importlib

    csv_path = tmp_path / "elsewhere" / "variant_upgrade_candidates.csv"
    decisions = tmp_path / "elsewhere" / "decisions.jsonl"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("existing_wid,title,artist\nabc1234-a-work,A Work,An Artist\n")

    monkeypatch.setenv("FAA_VARIANT_UPGRADE_CSV", str(csv_path))
    monkeypatch.setenv("FAA_VARIANT_UPGRADE_DECISIONS", str(decisions))
    reloaded = importlib.reload(api_main)
    try:
        assert csv_path == reloaded.VARIANT_UPGRADE_CSV
        assert decisions == reloaded.VARIANT_UPGRADE_DECISIONS
    finally:
        monkeypatch.delenv("FAA_VARIANT_UPGRADE_CSV")
        monkeypatch.delenv("FAA_VARIANT_UPGRADE_DECISIONS")
        importlib.reload(api_main)


def test_variant_upgrade_paths_default_to_the_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """No override, no surprise: the documented defaults still hold."""
    import importlib

    monkeypatch.delenv("FAA_VARIANT_UPGRADE_CSV", raising=False)
    monkeypatch.delenv("FAA_VARIANT_UPGRADE_DECISIONS", raising=False)
    reloaded = importlib.reload(api_main)
    assert reloaded.VARIANT_UPGRADE_CSV.name == "variant_upgrade_candidates.csv"
    assert reloaded.VARIANT_UPGRADE_CSV.parent == reloaded.REPO_ROOT
    assert reloaded.VARIANT_UPGRADE_DECISIONS.parent == reloaded.REPO_ROOT / "data"


def test_launcher_documents_the_new_overrides() -> None:
    """A seam nobody can find is not a seam."""
    launcher = (Path(__file__).resolve().parents[1] / "scripts" / "run_companion_app.sh").read_text(
        encoding="utf-8"
    )
    assert "FAA_VARIANT_UPGRADE_CSV" in launcher
    assert "FAA_VARIANT_UPGRADE_DECISIONS" in launcher
