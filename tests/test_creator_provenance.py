"""Tests for creator-provenance classification + the artist-search ledger."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.resolve_creators import _apply_outcome, _eligible  # noqa: E402

from fine_art_archive.enrichment.creator_provenance import (  # noqa: E402
    ARTIST_SEARCH_PLAN_VERSION,
    REF_IMAGE_NAME_RECOVERED,
    REF_IMAGE_PENDING,
    REF_SEARCH,
    REF_UNATTRIBUTABLE,
    classify,
)


def _claim(qid: str) -> dict[str, Any]:
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}}


class FakeClient:
    """Resolves only the names in ``known`` (cleaned-name -> (qid, label)) to
    real painters; every other search returns no hit."""

    def __init__(self, known: dict[str, tuple[str, str]]) -> None:
        self.known = known
        self.by_qid = dict(known.values())

    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        if params is None:  # fetch_identity -> Special:EntityData
            qid = url.rsplit("/", 1)[-1].removesuffix(".json")
            label = self.by_qid.get(qid)
            return (
                {"entities": {qid: {"labels": {"en": {"value": label}}, "claims": {}}}}
                if label
                else None
            )
        if params.get("action") == "wbsearchentities":
            hit = self.known.get(params.get("search", ""))
            return {"search": ([{"id": hit[0]}] if hit else [])}
        if params.get("action") == "wbgetentities":
            entities: dict[str, Any] = {}
            for qid in params.get("ids", "").split("|"):
                label = self.by_qid.get(qid)
                if label:
                    entities[qid] = {
                        "claims": {"P31": [_claim("Q5")], "P106": [_claim("Q1028181")]},
                        "labels": {"en": {"value": label}},
                        "aliases": {},
                    }
            return {"entities": entities}
        return None


def _meta(name: str = "", title: str = "", relation: str = "") -> dict[str, Any]:
    return {"work_id": "w1", "title": title, "artist": {"name": name, "relation": relation}}


def test_resolved_clean_name() -> None:
    client = FakeClient({"Zeno Fictus": ("Q900", "Zeno Fictus")})
    out = classify(_meta(name="Zeno Fictus", title="A Landscape"), client=client)
    assert out.kind == "resolved" and out.qid == "Q900"


def test_resolved_via_conservative_typo_repair() -> None:
    # "Zeno Ficttus" (tripled t) is not found; the collapse-tripled variant is.
    client = FakeClient({"Zeno Fictus": ("Q900", "Zeno Fictus")})
    out = classify(_meta(name="Zeno Ficttus", title="A Landscape"), client=client)
    assert out.kind == "resolved" and out.qid == "Q900"
    assert "via" in (out.method or "")


def test_resolved_via_token_reorder() -> None:
    client = FakeClient({"Fictus Zeno": ("Q901", "Fictus Zeno")})
    out = classify(_meta(name="Zeno Fictus", title="A Landscape"), client=client)
    assert out.kind == "resolved" and out.qid == "Q901"


def test_typo_repair_rejected_when_label_drifts() -> None:
    # The variant resolves, but to a completely different name -> must NOT accept.
    client = FakeClient({"Zeno Fictus": ("Q902", "Pablo Picasso")})
    out = classify(_meta(name="Zeno Ficttus", title="A Landscape"), client=client)
    assert out.kind != "resolved"


def test_anonymous_explicit_marker() -> None:
    out = classify(_meta(name="Unknown (Early Christian)", title="Mosaic"), client=FakeClient({}))
    assert out.kind == "anonymous"


def test_anonymous_relation() -> None:
    out = classify(_meta(name="Some Studio", relation="anonymous"), client=FakeClient({}))
    assert out.kind == "anonymous"


def test_anonymous_period_culture_fragment() -> None:
    out = classify(
        _meta(name="1279–1213 B.C.", title="Queen Nefertari being led by Isis"),
        client=FakeClient({}),
    )
    assert out.kind == "anonymous"


def test_half_swap_date_name_with_artist_title_is_unattributable() -> None:
    # name is a date fragment but the TITLE names a real artist -> corrupt, NOT anonymous.
    client = FakeClient({"Anthonie van Borssom": ("Q950", "Anthonie van Borssom")})
    out = classify(_meta(name="1629:1630 - 1677)", title="Anthonie van Borssom"), client=client)
    assert out.kind == "unattributable"


def test_searched_real_name_unresolved() -> None:
    out = classify(_meta(name="Leonard Kateete", title="Subaa"), client=FakeClient({}))
    assert out.kind == "searched"


def test_unattributable_junk_fragment() -> None:
    out = classify(_meta(name="_El_Jem", title="Anfiteatro"), client=FakeClient({}))
    assert out.kind == "unattributable"


def test_bare_year_is_unattributable_not_anonymous() -> None:
    # A lost modern year is corruption, NOT evidence of cultural anonymity.
    out = classify(_meta(name="1440-43", title="Door of the Apostles"), client=FakeClient({}))
    assert out.kind == "unattributable"


def test_era_keyword_is_anonymous() -> None:
    out = classify(
        _meta(name="early 8th century (Tang dynasty)", title="Tomb Guardian"),
        client=FakeClient({}),
    )
    assert out.kind == "anonymous"


def test_empty_name_is_unattributable() -> None:
    out = classify(_meta(name="", title="Untitled"), client=FakeClient({}))
    assert out.kind == "unattributable"


# --- ledger eligibility ---------------------------------------------------


def test_eligible_when_never_classified() -> None:
    assert _eligible(_meta(name="Someone New")) is True


def test_old_generic_label_is_reclassified() -> None:
    # An old not_available with no ledger source_ref is not authoritative here.
    meta = _meta(name="Unknown (Early Christian)")
    meta["field_provenance"] = {
        "artist_qid": {"status": "not_available", "source_ref": "", "note": "Checked sources"}
    }
    assert _eligible(meta) is True


def test_ineligible_when_has_creator_qid() -> None:
    meta = _meta(name="Zeno")
    meta["artist"]["wikidata_q"] = "Q900"
    assert _eligible(meta) is False


def test_anonymous_is_terminal_version_independent() -> None:
    meta = _meta(name="Unknown")
    _apply_outcome(meta, classify(meta, client=FakeClient({})))
    assert meta["field_provenance"]["artist_qid"]["status"] == "not_available"
    assert _eligible(meta) is False  # never re-opened by a plan bump


def test_searched_reopens_only_when_plan_rises() -> None:
    meta = _meta(name="Leonard Kateete", title="Subaa")
    _apply_outcome(meta, classify(meta, client=FakeClient({})))
    entry = meta["field_provenance"]["artist_qid"]
    assert entry["source_ref"] == f"{REF_SEARCH}{ARTIST_SEARCH_PLAN_VERSION}"
    assert _eligible(meta) is False  # same version -> terminal
    # simulate an older retirement -> re-opens
    entry["source_ref"] = f"{REF_SEARCH}{ARTIST_SEARCH_PLAN_VERSION - 1}"
    assert _eligible(meta) is True


def test_null_name_is_image_search_pending_not_final() -> None:
    # A null/empty name (debris stripped) must NOT be a final verdict: it goes to
    # the non-terminal image-search-pending state until image search has run.
    meta = _meta(name="")
    bucket = _apply_outcome(meta, classify(meta, client=FakeClient({})))
    assert bucket == "image-search-pending"
    assert meta["field_provenance"]["artist_qid"]["source_ref"] == REF_IMAGE_PENDING
    assert _eligible(meta) is False  # text is exhausted; the image process owns it now


def test_lens_recovered_names_are_terminal_not_image_search_pending() -> None:
    """A repeated image search cannot improve a name Lens already recovered."""
    for name in ("Hunto", "Shiva and Dayal"):
        meta = _meta(name=name)
        meta["field_provenance"] = {
            "artist_qid": {"status": "not_available", "source_ref": "faa:google-lens/text"}
        }

        bucket = _apply_outcome(meta, classify(meta, client=FakeClient({})))

        entry = meta["field_provenance"]["artist_qid"]
        assert bucket == "image-search-name-recovered"
        assert entry["source_ref"] == REF_IMAGE_NAME_RECOVERED
        assert entry["source_ref"] != REF_IMAGE_PENDING
        assert _eligible(meta) is False


def test_legacy_unattributable_reopens_for_migration() -> None:
    meta = _meta(name="_junk_fragment")
    meta["field_provenance"] = {
        "artist_qid": {"status": "not_available", "source_ref": REF_UNATTRIBUTABLE}
    }
    assert _eligible(meta) is True  # reopened so a re-run migrates it to image-pending


def test_resolved_apply_sets_creator_qid() -> None:
    client = FakeClient({"Zeno Fictus": ("Q900", "Zeno Fictus")})
    meta = _meta(name="Zeno Fictus", title="A Landscape")
    _apply_outcome(meta, classify(meta, client=client))
    assert meta["artist"]["wikidata_q"] == "Q900"
    assert _eligible(meta) is False  # now has a creator
