"""`manifest.csv` must exist, and must carry what the operator UI reads off it.

The Companion App browses works through the manifest and through nothing else,
so a work missing from it is served and rendered but unreachable. Until
2026-09-01 nothing in this repository wrote the file: `/healthz` had reported
manifest drift correctly since 2026-08-05 while the only thing that could clear
it had no producer, and the drift reached all 3499 works on disk.

The regression these tests guard is therefore twofold: that the generator
produces a row per work with the columns its consumers actually read, and that
one unreadable sidecar costs its own row rather than the whole index.
"""

from __future__ import annotations

import csv
import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts import build_manifest  # noqa: E402
from scripts.build_manifest import COLUMNS, build, main  # noqa: E402

from fine_art_archive.api import store  # noqa: E402


def _sidecar(**overrides: object) -> dict:
    meta = {
        "work_id": "0000001-a-work",
        "schema_version": "1.0.0",
        "title": "A Work",
        "artist": {"name": "An Artist"},
        "files": {"master": {"filename": "master.jpg"}},
        "history": [],
    }
    meta.update(overrides)
    return meta


@pytest.fixture
def works(tmp_path: Path) -> Path:
    """Three readable works and one sidecar that is not JSON.

    Deliberately out of alphabetical creation order, so a generator that
    happened to emit directory order rather than sorting would still pass the
    row-count assertions and fail the ordering one.
    """
    root = tmp_path / "works"
    root.mkdir()

    def put(work_id: str, meta: dict) -> None:
        directory = root / work_id
        directory.mkdir()
        (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    put(
        "b2b2b22-christ-crowned-with-thorns-perugino",
        _sidecar(
            work_id="b2b2b22-christ-crowned-with-thorns-perugino",
            title="Christ Crowned with Thorns",
            artist={
                "name": "Pietro Perugino",
                "wikidata_q": "Q5827",
                "canonical": {"wikidata_q": "Q5827", "display_name": "Pietro Perugino"},
            },
            year="1505",
            medium="oil on panel",
            files={
                "master": {"filename": "master.jpg"},
                "variants": [{"role": "landscape-crop"}, {"role": "portrait-crop"}],
            },
        ),
    )
    put(
        "a1a1a11-winter-landscape-leytens",
        _sidecar(
            work_id="a1a1a11-winter-landscape-leytens",
            title="Winter Landscape",
            # Raw spelling and canonical spelling differ, and the canonical
            # Q-ID is the one the store's screener trusts.
            artist={
                "name": "Gysbrechts Leytens",
                "wikidata_q": "Q999999",
                "canonical": {"wikidata_q": "Q1390417", "display_name": "Gijsbrecht Leytens"},
            },
            year=None,
            medium="Oil on canvas",
        ),
    )
    put(
        "c3c3c33-untitled-anonymous",
        _sidecar(
            work_id="c3c3c33-untitled-anonymous",
            title="Untitled",
            # A debris-repair pass has stripped an unusable name. The schema
            # allows it, and the work still has to be reachable.
            artist={"name": None},
        ),
    )

    corrupt = root / "d4d4d44-truncated-sidecar"
    corrupt.mkdir()
    (corrupt / "meta.json").write_text('{"work_id": "d4d4d44-trunc', encoding="utf-8")
    return root


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the real archive's manifest and ratings log out of these tests."""
    monkeypatch.setattr(store, "RATINGS_LOG", tmp_path / "ratings_log.jsonl")
    store.invalidate_manifest_cache()
    store.invalidate_ratings_cache()
    yield
    store.invalidate_manifest_cache()
    store.invalidate_ratings_cache()


def _read(manifest: Path) -> list[dict[str, str]]:
    with open(manifest, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_columns_are_the_ones_consumers_read(works: Path, tmp_path: Path) -> None:
    """Every column has a live reader; `list_works()` ships all of them.

    work_id -> `store.get_manifest_row()` and the ratings join;
    title, artist_name -> `store._matches_query()`, `store.list_artists()`;
    artist_wikidata_q, year, medium -> `main._manifest_placeholder_work()`
    and the browse table; n_variants -> the Variants column.
    """
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0

    with open(manifest, encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == list(COLUMNS)
    assert header == [
        "work_id",
        "title",
        "artist_name",
        "artist_wikidata_q",
        "year",
        "medium",
        "n_variants",
    ]


def test_one_row_per_readable_work_sorted_by_work_id(works: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0

    rows = _read(manifest)
    assert [row["work_id"] for row in rows] == [
        "a1a1a11-winter-landscape-leytens",
        "b2b2b22-christ-crowned-with-thorns-perugino",
        "c3c3c33-untitled-anonymous",
    ]


def test_artist_name_is_the_raw_display_string(works: Path, tmp_path: Path) -> None:
    """`artist_name` carries `artist.name`, not the `artist` mapping.

    `artist` is an object in the sidecar; the manifest is flat. Writing the
    mapping would put `{'name': 'Pietro Perugino', ...}` in the cell, which
    `store._matches_query()` would then substring-search and
    `store.list_artists()` would group on, giving every work its own artist.
    The RAW spelling is required, not the canonical one: the resolver runs at
    read time, and `list_artists()` counts distinct raw spellings to report how
    many folded together.
    """
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0

    by_id = {row["work_id"]: row for row in _read(manifest)}
    assert by_id["b2b2b22-christ-crowned-with-thorns-perugino"]["artist_name"] == "Pietro Perugino"
    assert by_id["a1a1a11-winter-landscape-leytens"]["artist_name"] == "Gysbrechts Leytens"
    # Nullable by schema, and rendered as an empty cell rather than "None".
    assert by_id["c3c3c33-untitled-anonymous"]["artist_name"] == ""


def test_row_values_come_from_the_sidecar(works: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0

    by_id = {row["work_id"]: row for row in _read(manifest)}
    perugino = by_id["b2b2b22-christ-crowned-with-thorns-perugino"]
    assert perugino["title"] == "Christ Crowned with Thorns"
    assert perugino["year"] == "1505"
    assert perugino["medium"] == "oil on panel"
    assert perugino["n_variants"] == "2"

    leytens = by_id["a1a1a11-winter-landscape-leytens"]
    # Canonical Q-ID wins over the raw one, matching `store.known_artist_qids()`.
    assert leytens["artist_wikidata_q"] == "Q1390417"
    assert leytens["year"] == ""
    assert leytens["n_variants"] == "0"


def test_unreadable_sidecar_is_skipped_and_named_not_fatal(
    works: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One corrupt sidecar costs its own row, never the whole index."""
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0

    captured = capsys.readouterr()
    assert "d4d4d44-truncated-sidecar" in captured.err
    assert "1 skipped" in captured.out

    rows = _read(manifest)
    assert len(rows) == 3, "the readable works must still be navigable"
    assert "d4d4d44-truncated-sidecar" not in {row["work_id"] for row in rows}

    result = build(works)
    assert [skip.work_id for skip in result.skipped] == ["d4d4d44-truncated-sidecar"]


def test_a_clean_run_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """ "0 skipped" must be reachable, not just the failure wording.

    A report that can only ever say "n skipped" for n > 0 goes quiet at the
    exact moment it is healthy, which reads as a broken check.
    """
    works = tmp_path / "works"
    (works / "e5e5e55-a-work").mkdir(parents=True)
    (works / "e5e5e55-a-work" / "meta.json").write_text(
        json.dumps(_sidecar(work_id="e5e5e55-a-work")), encoding="utf-8"
    )

    assert main(["--works-root", str(works), "--out", str(tmp_path / "manifest.csv")]) == 0
    assert "1 works, 0 skipped" in capsys.readouterr().out


def test_rerun_reproduces_the_file_byte_for_byte(works: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0
    first = manifest.read_bytes()
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0
    assert manifest.read_bytes() == first


def test_check_reports_staleness_without_writing(works: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest), "--check"]) == 1
    assert not manifest.exists(), "--check must not write"

    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0
    assert main(["--works-root", str(works), "--out", str(manifest), "--check"]) == 0

    # A promotion the manifest has not caught up with is stale, not current.
    new_work = works / "f6f6f66-a-later-promotion"
    new_work.mkdir()
    (new_work / "meta.json").write_text(
        json.dumps(_sidecar(work_id="f6f6f66-a-later-promotion")), encoding="utf-8"
    )
    assert main(["--works-root", str(works), "--out", str(manifest), "--check"]) == 1


def test_unreadable_works_root_does_not_truncate_the_manifest(works: Path, tmp_path: Path) -> None:
    """ "Cannot read the tree" is not "the tree is empty".

    Treating it as empty would replace a good index with a header row and take
    the whole archive out of the UI -- the outage this generator exists to end.
    """
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0
    good = manifest.read_bytes()

    assert main(["--works-root", str(tmp_path / "gone"), "--out", str(manifest)]) == 2
    assert manifest.read_bytes() == good


def test_unlistable_works_root_exits_rather_than_crashing(
    works: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root that exists but cannot be LISTED is still "cannot measure".

    `is_dir()` is true and `os.scandir()` then raises -- a permission denial, or
    a cloud-sync mount that has evicted the tree, which is the likely shape on
    this archive's volume. main() caught only NotADirectoryError, so this exact
    case produced a traceback instead of the exit 2 the docstring promises, and
    a caller reading the exit code could not tell it apart from a crash.
    """
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0
    good = manifest.read_bytes()

    def deny(_path: object) -> object:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(build_manifest.os, "scandir", deny)
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 2
    assert manifest.read_bytes() == good, "an unlistable root must not rewrite the manifest"


def test_generated_manifest_drives_the_real_consumers(
    works: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_store: None
) -> None:
    """The end the manifest exists for: the store can navigate to every work.

    Asserted against `store`, not against the column list, so the test fails if
    the generator and its consumers ever disagree about a column name.
    """
    manifest = tmp_path / "manifest.csv"
    assert main(["--works-root", str(works), "--out", str(manifest)]) == 0
    monkeypatch.setattr(store, "MANIFEST_CSV", manifest)
    store.invalidate_manifest_cache()

    listing = store.list_works(limit=50)
    assert listing["total"] == 3

    row = store.get_manifest_row("b2b2b22-christ-crowned-with-thorns-perugino")
    assert row is not None
    assert row["title"] == "Christ Crowned with Thorns"

    # Search reaches both the title and the raw artist spelling.
    assert store.list_works(q="crowned")["total"] == 1
    assert store.list_works(q="Gysbrechts")["total"] == 1

    # The two named artists group separately, one work each; the stripped name
    # contributes no artist at all.
    artists = store.list_artists(limit=10)
    assert sorted(entry["n_works"] for entry in artists) == [1, 1]


# --------------------------------------------------------------------------
# Every launch path must run the producer
# --------------------------------------------------------------------------
def test_every_documented_launch_path_rebuilds_the_index_before_serving() -> None:
    """A producer nothing calls is the same as no producer.

    Promotion into `Art/works/` happens outside this repo, so the manifest can
    only ever go stale between launches — which is why
    `scripts/run_companion_app.sh` rebuilds before it serves. `.claude/launch.json`
    called uvicorn directly and did not, so every launch through that path
    served whatever index had last been written by hand. Measured 2026-09-02:
    five works acquired since the previous rebuild, `/healthz` reporting
    `ok: false`, and those five unreachable in the UI — the exact condition
    #639 existed to end, reintroduced by the launcher rather than by the code.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    sh = (root / "scripts" / "run_companion_app.sh").read_text(encoding="utf-8")
    assert "build_manifest.py" in sh, "the shell runner no longer rebuilds the index"

    launch = root / ".claude" / "launch.json"
    if not launch.exists():  # pragma: no cover - optional local file
        return
    cfg = json.loads(launch.read_text(encoding="utf-8"))
    for entry in cfg.get("configurations", []):
        command = " ".join(
            [str(entry.get("runtimeExecutable", ""))]
            + [str(a) for a in entry.get("runtimeArgs", [])]
        )
        if "fine_art_archive.api.main:app" not in command:
            continue
        assert "build_manifest" in command, (
            f"launch configuration {entry.get('name')!r} serves the app without "
            "rebuilding manifest.csv, so it will show a stale archive"
        )
