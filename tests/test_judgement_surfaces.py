"""Every screen that asks for a judgement must carry what the judgement needs.

Written after the fifth round of "you fixed one screen, the others still show
68 px icons". Each check below is a defect that actually shipped, on a screen
that had already been declared fixed:

  * a gate whose "Open" led to a flat table because only three gates were
    listed in the routing map
  * 103 broken thumbnails, because a list of ARCHIVE work ids asked the
    WIKIDATA candidate proxy for its pictures
  * a truncated download shown as a broken-image icon, indistinguishable from
    a bad picture
  * "approve the artist" offered on a queue decided one work at a time

The point is that these are checked for ALL surfaces at once, not for whichever
one was last complained about.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

from fine_art_archive.api import store

UI = Path(__file__).resolve().parents[1] / "src/fine_art_archive/ui/index.html"


@pytest.fixture(scope="module")
def page() -> str:
    return UI.read_text(encoding="utf-8")


def _all_gate_names() -> set[str]:
    from fine_art_archive.api import main

    return {g.name for g in main._all_gates()}


def _gate_view_names(page: str) -> set[str]:
    block = re.search(r"const GATE_VIEW = \{(.*?)\};", page, re.S)
    assert block, "GATE_VIEW map not found"
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.M))


def test_every_gate_routes_to_a_view_built_for_its_judgement(page: str) -> None:
    """A gate with no card view sends you to a flat table of thumbnails.

    That table cannot answer "is this image good enough" or "is this the
    painting I already hold", which is what these gates are asking.
    """
    missing = _all_gate_names() - _gate_view_names(page)
    assert not missing, f"gates with no judgement view: {sorted(missing)}"


def test_the_routing_map_is_defined_exactly_once(page: str) -> None:
    """Two copies is how the gate table came to offer "Approve artist" on a
    queue the gate list had already learned was decided work by work."""
    assert page.count("const GATE_VIEW = {") == 1


def test_every_gate_declares_what_its_ids_refer_to() -> None:
    """The viewer must never guess which image endpoint serves an item.

    Guessing is how the unreviewed-acquisitions list asked the Wikidata
    candidate proxy for all 103 of its pictures and got 103 broken images.
    """
    from fine_art_archive.api import main

    for gate in main._all_gates():
        assert gate.item_kind in {"candidate", "held_work"}, gate.name
        for item in gate.items:
            looks_like_qid = bool(re.fullmatch(r"Q\d+", str(item.get("id", ""))))
            if gate.item_kind == "candidate":
                assert looks_like_qid, f"{gate.name}: {item.get('id')!r} is not a Q-ID"
            else:
                assert not looks_like_qid, f"{gate.name}: {item.get('id')!r} looks like a Q-ID"


def test_a_gate_declares_its_item_kind_even_when_it_is_empty() -> None:
    """Otherwise a gate tells you a different story on a quiet day."""
    from fine_art_archive.api import main

    gate = main._variant_upgrade_gate()
    assert gate.item_kind == "held_work"


# --------------------------------------------------------------------------
# Master health: "not looked at" is not "fine"
# --------------------------------------------------------------------------
def _jpeg_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (32, 24), (120, 60, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def test_a_complete_jpeg_is_ok(tmp_path: Path) -> None:
    p = tmp_path / "master.jpeg"
    p.write_bytes(_jpeg_bytes())
    assert store._master_health(p) == "ok"


def test_a_truncated_jpeg_is_reported_as_truncated(tmp_path: Path) -> None:
    """Three acquired masters in this archive are truncated. Their headers
    still report full dimensions, so every list showed them as normal."""
    p = tmp_path / "master.jpeg"
    complete = _jpeg_bytes()
    assert len(complete) > 200, "fixture too small to truncate meaningfully"
    p.write_bytes(complete[: len(complete) // 2])
    assert store._master_health(p) == "truncated"


def test_a_jpeg_missing_only_its_end_marker_is_not_called_truncated(tmp_path: Path) -> None:
    """The check that made this test necessary.

    Rousseau's *The Dream* has no end-of-image marker and decodes perfectly. A
    marker-only check would have told the owner a working picture was broken —
    the same false alarm, in the opposite direction, as a silent failure.
    """
    # Faithful reproduction: the scan data is COMPLETE, the end marker just
    # is not the last thing in the file. Chopping bytes off instead would
    # destroy real scan data and test something else entirely.
    p = tmp_path / "master.jpeg"
    p.write_bytes(_jpeg_bytes() + b"\x00\x00\x00")
    assert store._master_health(p) == "ok"


def test_an_unreadable_file_is_unchecked_not_ok(tmp_path: Path) -> None:
    assert store._master_health(tmp_path / "nope.jpeg") == "unchecked"


# --------------------------------------------------------------------------
# The acquisition card's evidence
# --------------------------------------------------------------------------
def test_acquisition_evidence_carries_where_the_bytes_came_from(tmp_path: Path) -> None:
    """A title and a name cannot show that a work titled "...near Argenteuil"
    was filled from a file named "...near Giverny"."""
    (tmp_path / "master.jpeg").write_bytes(_jpeg_bytes())
    meta = {
        "holder": {"name": "Musée d'Orsay"},
        "acquisition_provenance": {
            "source": "wikimedia-commons",
            "commons_filename": "Poppy Field in a Hollow near Giverny.jpg",
            "image_url": "https://example.invalid/file.jpg",
        },
        "rights": {"status": "public-domain"},
        "stable_identifiers": {"wikidata_q": "Q3231771"},
    }
    ev = store._acquisition_evidence(meta, tmp_path)
    assert ev["source_filename"] == "Poppy Field in a Hollow near Giverny.jpg"
    assert ev["holder_name"] == "Musée d'Orsay"
    assert ev["source_url"] == "https://example.invalid/file.jpg"
    assert ev["rights_status"] == "public-domain"
    assert ev["pixels_measured"] is True
    assert ev["file_health"] == "ok"


def test_a_work_with_no_master_reports_unmeasured_not_zero(tmp_path: Path) -> None:
    ev = store._acquisition_evidence({}, tmp_path)
    assert ev["pixels_measured"] is False
    assert ev["megapixels"] is None
    assert ev["file_health"] == "unchecked"


def test_acquisition_evidence_survives_master_removal_during_stat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    master = tmp_path / "master.jpeg"
    master.write_bytes(_jpeg_bytes())
    original_stat = Path.stat

    def disappearing_stat(path: Path, *args, **kwargs):
        if path == master:
            raise OSError("master removed")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(store, "_find_master", lambda _work_dir: master)
    monkeypatch.setattr(store, "_image_pixels", lambda _path: None)
    monkeypatch.setattr(Path, "stat", disappearing_stat)
    ev = store._acquisition_evidence({}, tmp_path)
    assert ev["master_mb"] is None
    assert ev["file_health"] == "unchecked"


# --------------------------------------------------------------------------
# What the card must actually put on the page
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "card,needle",
    [
        # every judgement card offers a full-size view
        ("renderWorkReview", "Open larger"),
        ("renderAcquisition", "full size"),
        ("renderUpgrade", "full size"),
        ("renderApproval", "open larger"),
        # and says what the decision does not do
        ("renderWorkReview", "not the artist"),
        ("renderAcquisition", "does not accept"),
        ("renderUpgrade", "nothing is overwritten"),
        ("renderApproval", "does not acquire anything now"),
    ],
)
def test_each_card_shows_the_picture_and_states_its_scope(
    page: str, card: str, needle: str
) -> None:
    start = page.index(f"function {card}(")
    body = page[start : start + 9000]
    assert needle in body, f"{card} is missing {needle!r}"


def test_no_judgement_card_nests_an_anchor_inside_an_anchor(page: str) -> None:
    """decisionThumb already returns an <a>. Wrapping it in a jump link closes
    the outer anchor, so the click opened the raw JPEG instead of the card."""
    for card in ("renderWorkReview", "renderAcquisition", "renderUpgrade", "renderApproval"):
        start = page.index(f"function {card}(")
        body = page[start : start + 9000]
        nested = re.search(r"<a\b[^>]*>(?:(?!</a>).)*?decisionThumb\(", body, re.S)
        assert not nested, f"{card} nests decisionThumb inside an anchor"


def test_review_cards_guard_all_external_evidence_links(page: str) -> None:
    """Escaping an href preserves a javascript: scheme; safeHref rejects it."""
    review = page[
        page.index("function renderWorkReview(") : page.index("function renderAcquisition(")
    ]
    acquisition_start = page.index("function acqEvidence(")
    acquisition = page[acquisition_start : page.index("function renderAcquisition(")]
    assert "safeHref(w.image_url)" in review
    assert "safeHref(w.rights_evidence_url)" in acquisition
    assert "safeHref(w.source_url)" in acquisition


def test_work_review_derives_artist_siblings_once_in_the_browser(page: str) -> None:
    """One API row per work avoids a quadratic review-queue response."""
    start = page.index("async function loadWorkReview(")
    body = page[start : start + 2500]
    assert "const worksByArtist = new Map()" in body
    assert "work.artist_works = works.filter" in body


# --------------------------------------------------------------------------
# Rating the autonomous acquisitions
# --------------------------------------------------------------------------
def test_the_acquisitions_rating_queue_is_computed_not_frozen(monkeypatch) -> None:
    """A stored list of work ids is correct until the tick acquires one more.

    A rating queue that silently stops including new arrivals is the same
    failure as a review surface that silently omits works: it reads as "you
    have seen everything" when the truth is "we stopped looking".
    """
    from fine_art_archive.api import main

    rows = [
        {"work_id": "a-one", "acquired_at": "2026-08-10T00:00:00+00:00"},
        {"work_id": "b-two", "acquired_at": "2026-08-11T00:00:00+00:00"},
    ]
    monkeypatch.setattr(main.store, "acquisitions_since_epoch", lambda *a, **k: rows)
    monkeypatch.setattr(main.store, "count_ratings_for", lambda wid: 0)
    first = main._dynamic_queue("autonomous-acquisitions")
    assert first is not None
    assert set(first["work_ids"]) == {"a-one", "b-two"}

    rows.append({"work_id": "c-new", "acquired_at": "2026-08-12T00:00:00+00:00"})
    second = main._dynamic_queue("autonomous-acquisitions")
    assert "c-new" in second["work_ids"], "a newly acquired work must appear without a rebuild"


def test_unrated_acquisitions_come_first(monkeypatch) -> None:
    """The queue exists to be rated; an already-rated work is the one entry
    with nothing to do on it."""
    from fine_art_archive.api import main

    rows = [
        {"work_id": "rated-old", "acquired_at": "2026-08-20T00:00:00+00:00"},
        {"work_id": "unrated-older", "acquired_at": "2026-08-10T00:00:00+00:00"},
        {"work_id": "unrated-newest", "acquired_at": "2026-08-30T00:00:00+00:00"},
    ]
    monkeypatch.setattr(main.store, "acquisitions_since_epoch", lambda *a, **k: rows)
    monkeypatch.setattr(main.store, "count_ratings_for", lambda wid: 3 if wid == "rated-old" else 0)
    got = main._dynamic_queue("autonomous-acquisitions")["work_ids"]
    assert got == ["unrated-newest", "unrated-older", "rated-old"], got


def test_an_unknown_queue_name_is_still_a_404(monkeypatch) -> None:
    """The dynamic lookup must not swallow a genuine typo."""
    from fine_art_archive.api import main

    assert main._dynamic_queue("no-such-queue") is None


def test_the_queue_listing_carries_an_addressable_key() -> None:
    """The picker sends the key back. A computed queue's readable label is not
    its key, and sending the label would 404."""
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main

    body = TestClient(main.app).get("/queues").json()
    dynamic = [q for q in body["queues"] if q.get("key") == "autonomous-acquisitions"]
    assert dynamic, "the acquisitions rating queue is not offered"
    assert dynamic[0]["name"] != dynamic[0]["key"], "this queue has a label distinct from its key"
    assert all(q.get("key") for q in body["queues"]), "every queue must be addressable"


def test_the_ui_sends_the_key_not_the_label(page: str) -> None:
    assert "opt.value = q.key || q.name;" in page


def test_the_rating_view_says_when_the_file_will_not_open(page: str) -> None:
    """Otherwise it asks for a judgement on a broken-image icon."""
    assert 'data._file_health === "truncated"' in page
    assert "Do not rate this one down" in page


# --------------------------------------------------------------------------
# The page's script must actually parse
# --------------------------------------------------------------------------
def test_the_inline_script_is_syntactically_valid(page: str) -> None:
    """A single unbalanced brace silently disables EVERY control on the page.

    This is not hypothetical. Merging main into the review work spliced a block
    between `slCount`'s opening brace and its closing one; the whole 146 KB
    script then failed to evaluate, so no card, no gate and no rating control
    existed at all — and every test in this file still passed, because they all
    read the HTML as text. The browser reported one line:

        Uncaught SyntaxError: Unexpected end of input

    Grepping for a string proves the string is present, not that the code runs.
    """
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:  # pragma: no cover - depends on the host
        pytest.skip("node not available to parse the inline script")

    blocks = re.findall(r"<script[^>]*>(.*?)</script>", page, re.S)
    assert blocks, "no inline script found — the page is served from this file"
    for i, block in enumerate(sorted(blocks, key=len, reverse=True)):
        if len(block.strip()) < 200:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(block)
            path = Path(fh.name)
        try:
            result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        finally:
            path.unlink(missing_ok=True)
        assert result.returncode == 0, f"script block {i} does not parse:\n{result.stderr}"


# --------------------------------------------------------------------------
# The variant gate must not count work nobody can do
# --------------------------------------------------------------------------
def _variant_csv(tmp_path, rows):
    import csv as _c

    p = tmp_path / "variant_upgrade_candidates.csv"
    cols = [
        "existing_wid",
        "title",
        "artist",
        "existing_master_mb",
        "candidate_master_mb",
        "ratio",
        "candidate_path",
        "candidate_meta",
        "candidate_quarantined",
        "candidate_canonical_q",
    ]
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = _c.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return p


def test_a_candidate_whose_file_is_gone_is_not_counted_as_pending(monkeypatch, tmp_path) -> None:
    """The latch this fixes.

    The detector writes against a staging tree the app does not control, and a
    quarantine purge deletes candidates on its TTL — five of six rows went
    missing inside a day. Such a row cannot be accepted, so the gate could not
    go down by doing the thing it asks for, and the only mechanism that clears
    it (re-running the detector) was invoked by nothing. A gate blocking on
    work nobody can do, with an uncalled drain, stays shut until someone
    notices.
    """
    from fine_art_archive.api import main

    present = tmp_path / "here.jpg"
    present.write_bytes(b"x")
    csv_path = _variant_csv(
        tmp_path,
        [
            {"existing_wid": "aaaaaaa-live-work", "title": "Live", "candidate_path": str(present)},
            {
                "existing_wid": "bbbbbbb-gone-work",
                "title": "Gone",
                "candidate_path": str(tmp_path / "deleted.jpg"),
            },
        ],
    )
    monkeypatch.setattr(main, "VARIANT_UPGRADE_CSV", csv_path)
    monkeypatch.setattr(main, "VARIANT_UPGRADE_DECISIONS", tmp_path / "decisions.jsonl")
    monkeypatch.setattr(main, "VARIANT_CANDIDATE_ROOTS", (tmp_path,))
    main._image_dims.cache_clear()

    gate = main._variant_upgrade_gate()
    assert gate.blocking == 1, "only the row whose file exists is a decision"
    assert gate.drainable == 1
    assert [i["id"] for i in gate.items] == ["aaaaaaa-live-work"]
    # And the stale one is REPORTED, with the command that clears it.
    assert "1 row(s)" in gate.note
    assert "detect_variant_upgrades" in gate.note


def test_the_variant_gate_names_a_drain_that_something_actually_invokes() -> None:
    """A drain that exists but is never called leaves the gate shut anyway.

    The quarantine purge is what deletes these candidates, so it is what must
    refresh the list. Before this it deleted the files and walked away.
    """
    import os
    from pathlib import Path

    workspace = os.environ.get("FAA_ACQUISITION_WORKSPACE")
    if not workspace:  # pragma: no cover - external workspace is opt-in in CI
        pytest.skip("set FAA_ACQUISITION_WORKSPACE to check the external purge contract")
    purge = Path(workspace) / "scripts" / "purge_expired_quarantines.py"
    assert purge.is_file(), "FAA_ACQUISITION_WORKSPACE must name the acquisition workspace"
    text = purge.read_text(encoding="utf-8")
    assert "detect_variant_upgrades" in text, (
        "the quarantine purge deletes variant candidates without refreshing the "
        "list that names them, so the review gate keeps showing deleted files"
    )


def test_the_upgrade_card_holds_stale_rows_out_of_the_queue(page: str) -> None:
    assert "candidate_present" in page
    assert "no longer on disk" in page


def test_a_gigapixel_master_is_not_reported_as_damaged(tmp_path) -> None:
    """Pillow's decompression-bomb ceiling is a false alarm on this corpus.

    These are museum scans we fetched ourselves, and several are hundreds of
    megapixels. `_master_health` decodes every master and treats any exception
    as truncation, so `DecompressionBombError` — a refusal on SIZE, not a
    finding about the bytes — was reported as a damaged file.

    It happened to a real work: Leonardo's *Virgin and Child with Saint Anne*,
    13295x17828 (237 MP), decodes cleanly and is byte-identical to a fresh
    download of its source. The review card told the owner it was truncated and
    not to judge it.

    Simulated here by lowering the ceiling rather than allocating 237 MP.
    """
    from io import BytesIO

    from PIL import Image

    src = tmp_path / "master.jpeg"
    buf = BytesIO()
    Image.new("RGB", (400, 400), (10, 20, 30)).save(buf, format="JPEG")
    src.write_bytes(buf.getvalue())

    original = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = 100  # any real image now trips the ceiling
        assert store._master_health(src) == "ok", (
            "a size refusal is not evidence about the bytes and must not be "
            "reported as truncation"
        )
    finally:
        Image.MAX_IMAGE_PIXELS = original


def test_master_health_restores_pillow_pixel_ceiling(tmp_path) -> None:
    """_master_health lifts the bomb ceiling only for its own decode."""
    from io import BytesIO

    from PIL import Image

    src = tmp_path / "master.jpeg"
    buf = BytesIO()
    Image.new("RGB", (20, 20), (1, 2, 3)).save(buf, format="JPEG")
    src.write_bytes(buf.getvalue())

    sentinel = 12345
    original = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = sentinel
    try:
        assert store._master_health(src) == "ok"
        assert sentinel == Image.MAX_IMAGE_PIXELS
    finally:
        Image.MAX_IMAGE_PIXELS = original


def test_master_facts_are_not_recomputed_when_only_a_sidecar_changes(tmp_path) -> None:
    """The acquisition list is invalidated by ANY sidecar write, which the
    growth tick does constantly. Re-opening every acquired master each time
    cost 28 seconds on a Dropbox-synced volume, on the page whose whole purpose
    is to be glanced at."""
    from io import BytesIO

    from PIL import Image

    src = tmp_path / "master.jpeg"
    buf = BytesIO()
    Image.new("RGB", (64, 64), (1, 2, 3)).save(buf, format="JPEG")
    src.write_bytes(buf.getvalue())

    store._MASTER_FACTS.clear()
    first = store._master_facts(src)
    assert len(store._MASTER_FACTS) == 1
    calls = []
    original = store._master_health
    store._master_health = lambda p: calls.append(p) or "ok"  # type: ignore[assignment]
    try:
        again = store._master_facts(src)
    finally:
        store._master_health = original  # type: ignore[assignment]
    assert again == first
    assert calls == [], "an unchanged master must not be re-examined"

    # A master that genuinely changes IS re-examined.
    buf2 = BytesIO()
    Image.new("RGB", (80, 80), (9, 9, 9)).save(buf2, format="JPEG")
    src.write_bytes(buf2.getvalue())
    assert store._master_facts(src)[0] == (80, 80)
