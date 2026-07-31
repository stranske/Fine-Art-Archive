"""Tests for category inference + the backfill CLI."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.backfill_categories import backfill

from fine_art_archive import sidecar
from fine_art_archive.enrichment import category_infer as ci

BASE: dict[str, Any] = {
    "work_id": "9999999-example",
    "schema_version": "1.0",
    "artist": {"name": "Example"},
    "title": "Example",
    "year": "1889",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "9999999" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


class FakeJsonClient:
    """Returns Special:EntityData-shaped payloads keyed by work QID -> P31 list."""

    def __init__(self, p31_by_qid: dict[str, list[str]]) -> None:
        self._p31 = p31_by_qid

    def get(self, url: str, *, params: Any = None) -> dict[str, Any] | None:
        qid = url.rsplit("/", 1)[-1].removesuffix(".json")
        if qid not in self._p31:
            return None
        claims = [
            {"mainsnak": {"datavalue": {"value": {"id": target, "entity-type": "item"}}}}
            for target in self._p31[qid]
        ]
        return {"entities": {qid: {"claims": {"P31": claims}}}}


# --- P31 mapping -----------------------------------------------------------
def test_p31_allowlisted_maps() -> None:
    assert ci.infer_from_p31(["Q3305213"]) == ("painting", "Wikidata P31 Q3305213 -> painting.")
    assert ci.infer_from_p31(["Q860861"])[0] == "sculpture"
    assert ci.infer_from_p31(["Q1473346"])[0] == "stained_glass"


def test_p31_unknown_class_ignored() -> None:
    # mis-resolved QID (country / scholarly article / person) -> no guess
    assert ci.infer_from_p31(["Q6256"]) is None
    assert ci.infer_from_p31(["Q13442814", "Q5"]) is None
    assert ci.infer_from_p31([]) is None


def test_p31_precedence_specific_over_generic() -> None:
    # The Last Supper: fresco painting + wall painting -> fresco (more specific)
    assert ci.infer_from_p31(["Q99516640", "Q134194"])[0] == "fresco"
    assert ci.infer_from_p31(["Q3305213", "Q133067"])[0] == "mosaic"


# --- medium technique (tier 1) ---------------------------------------------
def test_medium_technique_keywords() -> None:
    assert ci.infer_from_medium_technique("Apse mosaic")[0] == "mosaic"
    assert ci.infer_from_medium_technique("Stained glass")[0] == "stained_glass"
    assert ci.infer_from_medium_technique("bronze, gold")[0] == "sculpture"
    assert ci.infer_from_medium_technique("engraving on laid paper")[0] == "print"


def test_medium_technique_word_boundary_and_junk() -> None:
    assert ci.infer_from_medium_technique("_Guadalajara; _2017-01-04; _DD_41") is None
    assert ci.infer_from_medium_technique("") is None
    assert ci.infer_from_medium_technique(None) is None
    # ambiguous building stone must NOT be read as sculpture
    assert ci.infer_from_medium_technique("limestone") is None


def test_medium_technique_second_wave() -> None:
    # fresco typo + plural that \b-anchored "fresco" would miss
    assert ci.infer_from_medium_technique("fresc")[0] == "fresco"
    assert ci.infer_from_medium_technique("frescoes, Scrovegni Chapel")[0] == "fresco"
    # bare "Print" and photogravure -> print
    assert ci.infer_from_medium_technique("Print")[0] == "print"
    assert ci.infer_from_medium_technique("Photogravure")[0] == "print"
    # photographic transparency -> photograph
    assert ci.infer_from_medium_technique("Time Life color transparency")[0] == "photograph"


# --- medium material (tier 3) ----------------------------------------------
def test_medium_material_paint_and_draw() -> None:
    assert ci.infer_from_medium_material("oil paint, canvas")[0] == "painting"
    assert ci.infer_from_medium_material("tempera, gesso")[0] == "painting"
    assert ci.infer_from_medium_material("Ink and color on paper")[0] == "drawing"
    assert ci.infer_from_medium_material("sancai earthenware")[0] == "other"
    assert ci.infer_from_medium_material("gold and silver leaf") is None
    assert ci.infer_from_medium_material(None) is None


def test_medium_material_colorant_and_ceramic_and_typo() -> None:
    # East-Asian "<colorant> on <support>" -> painting (scrolls, thangkas)
    assert ci.infer_from_medium_material("Color on silk")[0] == "painting"
    assert ci.infer_from_medium_material("Pigment and gold on cotton")[0] == "painting"
    assert ci.infer_from_medium_material("Egg temper on cardboard")[0] == "painting"
    assert ci.infer_from_medium_material("fired clay")[0] == "other"
    assert ci.infer_from_medium_material("ceramic; found in Tlahuac")[0] == "other"
    # medium_vocab still wins: watercolour/ink stay drawing, not colorant-painting
    assert ci.infer_from_medium_material("watercolour on paper")[0] == "drawing"
    assert ci.infer_from_medium_material("ink and colour on paper")[0] == "drawing"


# --- title (tier 4) --------------------------------------------------------
def test_title_object_nouns_only() -> None:
    assert ci.infer_from_title("The Isenheim Altarpiece")[0] == "altarpiece"
    # building names are deliberately excluded (a titled "Cathedral" is often a painting)
    assert ci.infer_from_title("Rouen Cathedral, West Facade") is None
    assert ci.infer_from_title(None) is None


# --- orchestration ordering ------------------------------------------------
def test_infer_technique_beats_p31() -> None:
    # medium says mosaic; a mis-resolved QID says painting -> mosaic wins
    meta = {"medium": "Apse mosaic", "title": "Christ enthroned"}
    result = ci.infer_category(meta, p31_qids=["Q3305213"])
    assert result is not None and result.category == "mosaic" and result.source == "medium"


def test_infer_p31_beats_material() -> None:
    # ink-on-paper would be a drawing, but P31 explicitly types it a print
    meta = {"medium": "ink on paper", "title": "Adam and Eve"}
    result = ci.infer_category(meta, p31_qids=["Q11060274"])
    assert result is not None and result.category == "print" and result.source == "wikidata"


def test_infer_material_then_title_then_none() -> None:
    assert ci.infer_category({"medium": "oil paint, canvas"}).category == "painting"
    assert ci.infer_category({"medium": None, "title": "An Altarpiece"}).category == "altarpiece"
    assert ci.infer_category({"medium": None, "title": "Untitled"}) is None


# --- P31 fetch -------------------------------------------------------------
def test_fetch_p31_qids() -> None:
    client = FakeJsonClient({"Q28539395": ["Q3305213"]})
    assert ci.fetch_p31_qids("Q28539395", client=client) == ["Q3305213"]
    assert ci.fetch_p31_qids("Q404", client=client) == []  # unknown -> None payload
    assert ci.fetch_p31_qids("", client=client) == []


# --- enum guard ------------------------------------------------------------
def test_emitted_categories_are_valid_enum_members() -> None:
    schema = sidecar.load_schema()
    allowed = set(schema["properties"]["category"]["enum"])
    emitted = set(ci.P31_CATEGORY.values())
    emitted.update(cat for cat, _ in ci._TECHNIQUE_KEYWORDS)
    emitted.update(cat for cat, _ in ci._TITLE_KEYWORDS)
    emitted.update({"painting", "drawing", "other"})  # material tier outputs
    assert emitted <= allowed, emitted - allowed


# --- backfill CLI ----------------------------------------------------------
def _write(tmp_path: Path, **overrides: Any) -> Path:
    meta = deepcopy(BASE)
    meta.update(overrides)
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    return path


def test_backfill_apply_writes_category_and_provenance(tmp_path: Path) -> None:
    path = _write(tmp_path, category=None, medium="oil paint, canvas")
    stats, by_cat = backfill(path.parents[1], client=FakeJsonClient({}), apply=True)
    assert stats.resolved == 1 and stats.updated_works == 1
    result = sidecar.load_validated(path)
    assert result["category"] == "painting"
    assert result["field_provenance"]["category"]["status"] == "available"
    assert result["field_provenance"]["category"]["source"] == "medium"
    assert by_cat["painting"] == 1


def test_backfill_uses_p31(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        category=None,
        medium=None,
        stable_identifiers={"wikidata_q": "Q860861"},
    )
    client = FakeJsonClient({"Q860861": ["Q860861"]})
    backfill(path.parents[1], client=client, apply=True)
    result = sidecar.load_validated(path)
    assert result["category"] == "sculpture"
    assert result["field_provenance"]["category"]["source"] == "wikidata"


def test_backfill_dry_run_does_not_write(tmp_path: Path) -> None:
    path = _write(tmp_path, category=None, medium="oil paint, canvas")
    stats, _ = backfill(path.parents[1], client=FakeJsonClient({}), apply=False)
    assert stats.resolved == 1 and stats.updated_works == 0
    assert sidecar.load(path).get("category") is None  # unchanged on disk


def test_backfill_skips_already_categorized(tmp_path: Path) -> None:
    path = _write(tmp_path, category="painting", medium="oil paint, canvas")
    stats, _ = backfill(path.parents[1], client=FakeJsonClient({}), apply=True)
    assert stats.attempted == 0


def test_backfill_leaves_unresolvable_uncategorized(tmp_path: Path) -> None:
    path = _write(tmp_path, category=None, medium="_junk_caption_2017", title="Untitled")
    stats, by_cat = backfill(path.parents[1], client=FakeJsonClient({}), apply=True)
    assert stats.attempted == 1 and stats.resolved == 0
    assert by_cat["(unresolved)"] == 1
    assert sidecar.load(path).get("category") is None
