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
    p.write_bytes(_jpeg_bytes()[:-400])
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
def test_each_card_shows_the_picture_and_states_its_scope(page: str, card: str, needle: str) -> None:
    start = page.index(f"function {card}(")
    body = page[start : start + 9000]
    assert needle in body, f"{card} is missing {needle!r}"


def test_no_judgement_card_nests_an_anchor_inside_an_anchor(page: str) -> None:
    """decisionThumb already returns an <a>. Wrapping it in a jump link closes
    the outer anchor, so the click opened the raw JPEG instead of the card."""
    for card in ("renderWorkReview", "renderAcquisition", "renderUpgrade", "renderApproval"):
        start = page.index(f"function {card}(")
        body = page[start : start + 9000]
        assert "<a" not in body or "plainThumb" in body or "decisionThumb" not in body, card


def test_review_cards_guard_all_external_evidence_links(page: str) -> None:
    """Escaping an href preserves a javascript: scheme; safeHref rejects it."""
    review = page[page.index("function renderWorkReview(") : page.index("function renderAcquisition(")]
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
    monkeypatch.setattr(
        main.store, "count_ratings_for", lambda wid: 3 if wid == "rated-old" else 0
    )
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
    import tempfile

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
            path = fh.name
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, f"script block {i} does not parse:\n{result.stderr}"
