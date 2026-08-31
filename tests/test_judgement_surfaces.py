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
