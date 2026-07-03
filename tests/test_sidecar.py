"""Unit tests for fine_art_archive.sidecar (schema validation + helpers)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive import sidecar  # noqa: E402

# A minimal valid sidecar covering all required fields.
MINIMAL_VALID = {
    "work_id": "4f3a2b8-after-the-bullfight-cassatt",
    "schema_version": "1.0",
    "artist": {"name": "Mary Cassatt"},
    "title": "After the Bullfight",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "4f3a2b8" + ("0" * 57),  # 64 hex chars
            "size_bytes": 12378451,
            "ingested_at": "2026-05-16T21:30:00Z",
        },
    },
    "history": [
        {"ts": "2026-05-16T21:30:00Z", "actor": "claude", "op": "ingested"},
    ],
}


def test_minimal_valid():
    assert sidecar.is_valid(MINIMAL_VALID)


def test_full_valid():
    """A maximally-populated valid sidecar."""
    meta = dict(MINIMAL_VALID)
    meta["artist"] = {
        "name": "Mary Cassatt",
        "given": "Mary",
        "family": "Cassatt",
        "lifespan": "1844-1926",
        "nationality": "American",
        "wikidata_q": "Q173223",
        "ulan": "500030502",
    }
    meta["year"] = "1873"
    meta["year_min"] = 1873
    meta["year_max"] = 1873
    meta["medium"] = "Oil on canvas"
    meta["dimensions_original"] = {"h_cm": 82.5, "w_cm": 64.0, "raw": "82.5 × 64 cm"}
    meta["holder"] = {
        "name": "Art Institute of Chicago",
        "wikidata_q": "Q239303",
        "ror": "00w99rt55",
        "accession": "1969.332",
        "url": "https://www.artic.edu/artworks/61446",
    }
    meta["rights"] = {
        "status": "public-domain",
        "evidence_url": "https://www.artic.edu/artworks/61446",
        "evidence_wacz": "resources/wacz/artic-61446-2026-05-16.wacz",
    }
    meta["description_short"] = (
        "After the Bullfight; Mary Cassatt; 1873; Oil on canvas; 82.5 × 64 cm"
    )
    meta["stable_identifiers"] = {
        "wikidata_q": "Q98549878",
        "museum_accession": "1969.332",
    }
    meta["display_hints"] = {
        "orientation_natural": "portrait",
        "orientation_allowed": ["portrait"],
        "inkposter_tela_28_5": {
            "dither": "riemersma",
            "saturation_boost": 1.30,
            "contrast_boost": 1.15,
        },
    }
    meta["tags"] = ["impressionism", "portrait"]
    assert sidecar.is_valid(meta)


def test_invalid_missing_required_field():
    meta = {k: v for k, v in MINIMAL_VALID.items() if k != "title"}
    assert not sidecar.is_valid(meta)


def test_is_valid_raises_when_schema_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(sidecar, "SCHEMA_PATH", tmp_path / "missing.schema.json")

    with pytest.raises(sidecar.SchemaNotFound):
        sidecar.is_valid(MINIMAL_VALID)


def test_is_valid_raises_when_jsonschema_is_unavailable():
    with mock.patch.dict(sys.modules, {"jsonschema": None}), pytest.raises(ModuleNotFoundError):
        sidecar.is_valid(MINIMAL_VALID)


def test_is_valid_raises_for_corrupt_schema_json(monkeypatch, tmp_path):
    corrupt_schema = tmp_path / "meta.schema.json"
    corrupt_schema.write_text("{bad\n", encoding="utf-8")
    monkeypatch.setattr(sidecar, "SCHEMA_PATH", corrupt_schema)

    with pytest.raises(json.JSONDecodeError):
        sidecar.is_valid(MINIMAL_VALID)


def test_is_valid_raises_for_invalid_schema_document(monkeypatch, tmp_path):
    broken_schema = tmp_path / "meta.schema.json"
    broken_schema.write_text('{"type": 1}\n', encoding="utf-8")
    monkeypatch.setattr(sidecar, "SCHEMA_PATH", broken_schema)

    with pytest.raises(jsonschema.SchemaError):
        sidecar.is_valid(MINIMAL_VALID)


def test_invalid_work_id_pattern():
    meta = dict(MINIMAL_VALID)
    meta["work_id"] = "ZZZ-bad-pattern"  # uppercase Z disallowed
    assert not sidecar.is_valid(meta)


def test_invalid_sha256_length():
    meta = {**MINIMAL_VALID, "files": {**MINIMAL_VALID["files"]}}
    meta["files"]["master"] = {**MINIMAL_VALID["files"]["master"], "sha256": "abc"}
    assert not sidecar.is_valid(meta)


def test_invalid_wikidata_q_pattern():
    meta = {**MINIMAL_VALID, "artist": {"name": "X", "wikidata_q": "not-a-Q-id"}}
    assert not sidecar.is_valid(meta)


def test_invalid_rights_status_enum():
    meta = dict(MINIMAL_VALID)
    meta["rights"] = {"status": "maybe?"}
    assert not sidecar.is_valid(meta)


def test_history_empty_rejected():
    meta = dict(MINIMAL_VALID)
    meta["history"] = []
    assert not sidecar.is_valid(meta)


def test_history_event_missing_op():
    meta = dict(MINIMAL_VALID)
    meta["history"] = [{"ts": "2026-05-16T21:30:00Z", "actor": "claude"}]
    assert not sidecar.is_valid(meta)


def test_additional_top_level_property_rejected():
    meta = dict(MINIMAL_VALID)
    meta["unknown_field"] = "x"
    assert not sidecar.is_valid(meta)


def test_display_hints_open_additionalProperties():  # noqa: N802  -- mirrors JSON Schema keyword
    """display_hints accepts arbitrary per-device keys — that's the point."""
    meta = dict(MINIMAL_VALID)
    meta["display_hints"] = {
        "orientation_natural": "portrait",
        "orientation_allowed": ["portrait"],
        "vendor_x_42_2027": {
            "dither": "blue_noise",
            "saturation_boost": 1.35,
            "panel_size_px": [3200, 4800],
            "matte_color": "#f5f0e8",
        },
    }
    assert sidecar.is_valid(meta)


def test_files_variants_accepted():
    """files.variants holds same-work entries prepared for other surfaces.

    Phase 3 migration populates this from variant_groups.csv. Each entry
    references a sibling file by rel_path with a role tag indicating what
    display surface it's prepared for.
    """
    meta = {**MINIMAL_VALID, "files": {**MINIMAL_VALID["files"]}}
    meta["files"]["variants"] = [
        {
            "rel_path": "Landscape TV/The birth of Venus; Sandro Botticelli; ...jpeg",
            "role": "tv-master",
            "size_bytes": 507_300_000,
            "sha256": "a" * 64,
            "dimensions_px": [9987, 7755],
            "source_cluster_id": "cluster-0042",
        },
        {
            "rel_path": "Portrait Framed/The birth of Venus; ...jpeg",
            "role": "meural-framed",
        },
    ]
    assert sidecar.is_valid(meta)


def test_files_variants_rejects_bad_role():
    meta = {**MINIMAL_VALID, "files": {**MINIMAL_VALID["files"]}}
    meta["files"]["variants"] = [
        {"rel_path": "x.jpeg", "role": "not-a-real-role"},
    ]
    assert not sidecar.is_valid(meta)


def test_files_variants_requires_rel_path():
    meta = {**MINIMAL_VALID, "files": {**MINIMAL_VALID["files"]}}
    meta["files"]["variants"] = [{"role": "tv-master"}]  # missing rel_path
    assert not sidecar.is_valid(meta)


# --- Attribution relation (workshop/circle/after/anonymous) ----------------


def test_artist_workshop_of_uses_reference_qid():
    """Workshop-of works anchor on the reference artist's Q-ID."""
    meta = dict(MINIMAL_VALID)
    meta["artist"] = {
        "name": "Workshop of Rembrandt",
        "wikidata_q": "Q5598",  # Rembrandt himself, the reference artist
        "relation": "workshop",
        "attribution_confidence": "scholarly_consensus",
        "attribution_anchor": "Q23807",  # "workshop" entity on Wikidata
    }
    assert sidecar.is_valid(meta), sidecar.validate(meta)


def test_artist_after_caravaggio():
    meta = dict(MINIMAL_VALID)
    meta["artist"] = {
        "name": "After Caravaggio",
        "wikidata_q": "Q42207",
        "relation": "after",
        "attribution_confidence": "attributed",
    }
    assert sidecar.is_valid(meta)


def test_artist_anonymous_no_personal_qid():
    """True 'Unknown artist' — wikidata_q is null, anchor is anonymous."""
    meta = dict(MINIMAL_VALID)
    meta["artist"] = {
        "name": "Unknown artist",
        "wikidata_q": None,
        "relation": "anonymous",
        "attribution_anchor": "Q4233718",  # anonymous (Wikidata)
        "attribution_confidence": "scholarly_consensus",
    }
    assert sidecar.is_valid(meta)


def test_artist_relation_rejects_bad_enum():
    meta = dict(MINIMAL_VALID)
    meta["artist"] = {"name": "X", "relation": "made-up-relation"}
    assert not sidecar.is_valid(meta)


def test_artist_default_relation_omitted_is_valid():
    """Existing sidecars without a relation field still validate (default='self')."""
    meta = dict(MINIMAL_VALID)
    meta["artist"] = {"name": "Mary Cassatt", "wikidata_q": "Q436859"}
    assert sidecar.is_valid(meta)


def test_artist_attribution_anchor_pattern_enforced():
    meta = dict(MINIMAL_VALID)
    meta["artist"] = {"name": "Anon", "attribution_anchor": "not-a-q-id"}
    assert not sidecar.is_valid(meta)


# -- slugify and work_id derivation ------------------------------------------


def test_slugify_basic():
    assert (
        sidecar.slugify("After the Bullfight", artist_surname="Cassatt")
        == "after-the-bullfight-cassatt"
    )


def test_slugify_punctuation_stripped():
    # Default max_words=6 truncates after "as"; the test point is that the
    # "(Philip II?)" punctuation is stripped, not that every word survives.
    out = sidecar.slugify("Portrait of a Spanish Prince as Hunter (Philip II?)")
    assert out == "portrait-of-a-spanish-prince-as"
    # With max_words=7, "hunter" is preserved but "philip" is excluded.
    out2 = sidecar.slugify("Portrait of a Spanish Prince as Hunter (Philip II?)", max_words=7)
    assert out2 == "portrait-of-a-spanish-prince-as-hunter"
    # Punctuation never appears in the output regardless of cap.
    assert "(" not in out2 and ")" not in out2 and "?" not in out2


def test_slugify_max_words():
    s = sidecar.slugify("A B C D E F G H I", max_words=3)
    assert s == "a-b-c"


def test_slugify_empty_falls_back():
    assert sidecar.slugify("???") == "untitled"


def test_derive_work_id():
    sha = "4f3a2b8" + ("0" * 57)
    wid = sidecar.derive_work_id(sha, "after-the-bullfight-cassatt")
    assert wid == "4f3a2b8-after-the-bullfight-cassatt"


def test_derive_work_id_rejects_short_hash():
    with pytest.raises(ValueError):
        sidecar.derive_work_id("abc", "title")
