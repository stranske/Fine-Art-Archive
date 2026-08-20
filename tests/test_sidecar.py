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


def test_series_qid_rejected_as_single_work_identity():
    meta = dict(MINIMAL_VALID)
    meta["stable_identifiers"] = {"wikidata_q": "Q2667782"}

    with pytest.raises(jsonschema.ValidationError, match="part_of_q"):
        sidecar.validate(meta)


def test_series_qid_accepted_as_part_of_identity():
    meta = dict(MINIMAL_VALID)
    meta["stable_identifiers"] = {"part_of_q": "Q2667782"}

    sidecar.validate(meta)


def test_series_position_requires_part_of_q():
    meta = dict(MINIMAL_VALID)
    meta["series"] = {"position": 1, "source": "catalogue raisonne"}

    with pytest.raises(jsonschema.ValidationError, match="requires stable_identifiers.part_of_q"):
        sidecar.validate(meta)


@pytest.mark.parametrize("position", [True, 0, -1, "first"])
def test_series_position_rejects_non_positive_or_free_form_values(position):
    meta = dict(MINIMAL_VALID)
    meta["stable_identifiers"] = {"part_of_q": "Q2667782"}
    meta["series"] = {"position": position}

    with pytest.raises(jsonschema.ValidationError):
        sidecar.validate(meta)


def test_series_position_accepts_explicit_positive_integer():
    meta = dict(MINIMAL_VALID)
    meta["stable_identifiers"] = {"part_of_q": "Q2667782"}
    meta["series"] = {"position": 4, "position_label": "Plate IV", "source": "catalog"}

    sidecar.validate(meta)


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


def test_category_enum_accepts_site_anchored_media():
    """The site-anchored media are valid category values."""
    for cat in (
        "architecture",
        "stained_glass",
        "mosaic",
        "monument",
        "architectural_sculpture",
        "painting",
        "photograph",
    ):
        meta = dict(MINIMAL_VALID)
        meta["category"] = cat
        assert sidecar.is_valid(meta), cat


def test_category_enum_rejects_unknown_value():
    meta = dict(MINIMAL_VALID)
    meta["category"] = "stained-glass-typo"
    assert not sidecar.is_valid(meta)


def test_category_null_or_omitted_still_valid():
    """category is optional; null and absence both validate (backward compat)."""
    assert sidecar.is_valid(MINIMAL_VALID)  # omitted
    meta = dict(MINIMAL_VALID)
    meta["category"] = None
    assert sidecar.is_valid(meta)


def test_site_block_valid():
    """A site-anchored work: anonymous attribution + populated site block."""
    meta = dict(MINIMAL_VALID)
    meta["category"] = "stained_glass"
    meta["artist"] = {
        "name": "Anonymous",
        "relation": "anonymous",
        "attribution_anchor": "Q4233718",
    }
    meta["site"] = {
        "name": "Chartres Cathedral",
        "wikidata_q": "Q188527",
        "element": "South rose window",
        "commons_category": "Category:Rose windows of Chartres Cathedral",
        "coordinates": "48.4475,1.4878",
        "depicts_q": ["Q188527"],
    }
    assert sidecar.is_valid(meta)


def test_site_block_rejects_bad_qid_and_extra_keys():
    meta = dict(MINIMAL_VALID)
    meta["site"] = {"name": "X", "wikidata_q": "188527"}  # missing Q prefix
    assert not sidecar.is_valid(meta)
    meta["site"] = {"name": "X", "unknown_site_key": "y"}  # additionalProperties false
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
        # no attribution_anchor: the relation enum + reference wikidata_q carry the
        # kind for person relations; the anchor is only used for anonymous works.
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


# ---------------------------------------------------------------------------
# source_image: the pre-archive parent an archived master was made from.
# ---------------------------------------------------------------------------

SOURCE_IMAGE = {
    "path": "Pictures/Personal Photos/Originals/by-year/2019/"
    "The_Nobleman_with_his_Hand_on_his_Chest__89466F18__original.jpeg",
    "content_hash": "a" * 64,
    "original_filename": "The Nobleman with his Hand on his Chest, El Greco.jpeg",
    "method": "byte-identical",
    "confidence": "certain",
    "linked_at": "2026-08-18T12:00:00Z",
}


def _with_source(**overrides):
    meta = json.loads(json.dumps(MINIMAL_VALID))
    meta["source_image"] = {**SOURCE_IMAGE, **overrides}
    return meta


def test_source_image_accepted():
    assert sidecar.is_valid(_with_source())


def test_source_image_null_accepted():
    meta = json.loads(json.dumps(MINIMAL_VALID))
    meta["source_image"] = None
    assert sidecar.is_valid(meta)


def test_source_image_absent_accepted():
    """Additive field: the 3,421 sidecars written before it stay valid."""
    assert "source_image" not in MINIMAL_VALID
    assert sidecar.is_valid(MINIMAL_VALID)


@pytest.mark.parametrize("missing", ["path", "method", "confidence"])
def test_source_image_requires_provenance_of_the_link(missing):
    """A parent pointer with no stated method or confidence is the failure this
    field exists to prevent: a 2026-08 pass marked 1,811 works linked, 1,425 of
    them from an embedding threshold that independent evidence corroborated 5.9%
    of the time, and nothing recorded which were which."""
    meta = _with_source()
    del meta["source_image"][missing]
    assert not sidecar.is_valid(meta)


@pytest.mark.parametrize(
    "field,value",
    [
        ("method", "vibes"),
        ("confidence", "pretty-sure"),
        ("content_hash", "not-hex"),
        ("sha256", "abc"),
    ],
)
def test_source_image_rejects_out_of_vocabulary_values(field, value):
    assert not sidecar.is_valid(_with_source(**{field: value}))


def test_source_image_rejects_unknown_keys():
    """additionalProperties is false, so a writer inventing `parent` fails loudly
    rather than having the value silently ignored by every reader."""
    assert not sidecar.is_valid(_with_source(parent="somewhere"))


def test_source_image_verification_block():
    meta = _with_source(
        method="crop-located",
        confidence="verified",
        verification={
            "test": "ncc-crop-location",
            "score": 0.9312,
            "checked_at": "2026-08-18T12:00:00Z",
        },
        crop_region="120,80,1600,900",
    )
    assert sidecar.is_valid(meta)


def test_source_image_is_not_derived_from():
    """The two model different things and must not be conflated: derived_from
    points at another work IN the archive and forces a null work Q-ID, while
    source_image points outside the archive and leaves identity untouched."""
    meta = _with_source()
    meta["stable_identifiers"] = {"wikidata_q": "Q78663009"}
    assert sidecar.is_valid(meta), "source_image must not trigger the derived_from invariant"


# ---------------------------------------------------------------------------
# files.variant_of — the in-archive inverse of files.variants[].
# ---------------------------------------------------------------------------


def test_variant_of_accepted():
    meta = json.loads(json.dumps(MINIMAL_VALID))
    meta["files"]["variant_of"] = {
        "work_id": "ea60c7c-claude-monet-saintlazare",
        "role": "landscape-crop",
        "direction_evidence": "holding sits on a display aspect and the owner does not",
    }
    assert sidecar.is_valid(meta)


@pytest.mark.parametrize("missing", ["work_id", "role"])
def test_variant_of_requires_work_id_and_role(missing):
    meta = json.loads(json.dumps(MINIMAL_VALID))
    variant_of = {
        "work_id": "ea60c7c-claude-monet-saintlazare",
        "role": "landscape-crop",
    }
    del variant_of[missing]
    meta["files"]["variant_of"] = variant_of
    assert not sidecar.is_valid(meta)


def test_field_provenance_decided_by_and_list_prior_value():
    """An owner decision is provenance too. `prior_value` accepts a list because
    the value being superseded is sometimes a variants[] array."""
    meta = json.loads(json.dumps(MINIMAL_VALID))
    meta["field_provenance"] = {
        "files.variants": {
            "status": "available",
            "source": "apply_owner_decisions",
            "decided_by": "Tim, in chat, 2026-08-18",
            "prior_value": ["works/c10bacd-harry-s-truman-kempton/master.jpeg"],
        }
    }
    assert sidecar.is_valid(meta)


def test_field_provenance_prior_value_list_items_must_be_strings():
    meta = json.loads(json.dumps(MINIMAL_VALID))
    meta["field_provenance"] = {
        "files.variants": {
            "status": "available",
            "prior_value": [{"rel_path": "x"}],
        }
    }
    assert not sidecar.is_valid(meta)


def test_source_image_certain_requires_byte_identical_method():
    assert not sidecar.is_valid(_with_source(method="embedding", confidence="certain"))


def test_source_image_verified_requires_verification_block():
    assert not sidecar.is_valid(
        _with_source(method="crop-located", confidence="verified", verification=None)
    )


def test_source_image_verification_requires_test():
    assert not sidecar.is_valid(
        _with_source(
            method="crop-located",
            confidence="verified",
            verification={},
        )
    )


def test_source_image_rejects_malformed_crop_region():
    assert not sidecar.is_valid(_with_source(crop_region="not-coordinates"))


def test_variant_of_rejects_unknown_role():
    meta = json.loads(json.dumps(MINIMAL_VALID))
    meta["files"]["variant_of"] = {
        "work_id": "ea60c7c-claude-monet-saintlazare",
        "role": "not-a-real-role",
    }
    assert not sidecar.is_valid(meta)


# ---------------------------------------------------------------------------
# Structural guard on the schema document itself.
# ---------------------------------------------------------------------------


def test_schema_has_no_duplicate_keys():
    """json.load keeps the LAST of two same-level keys and discards the first
    without error. `derived_from` was declared twice: a 2026-08-11 commit added
    a rendition model with a `display-crop` kind above the existing definition,
    and every parser silently dropped it, so the commit's schema change never
    took effect while its text sat in the file describing current behaviour.
    Nothing in JSON or jsonschema catches this; only reading the raw pairs does."""
    seen: list[str] = []

    def collect(pairs):
        keys = [k for k, _ in pairs]
        seen.extend(k for k in set(keys) if keys.count(k) > 1)
        return dict(pairs)

    raw = sidecar.SCHEMA_PATH.read_text(encoding="utf-8")
    json.loads(raw, object_pairs_hook=collect)
    assert seen == [], f"duplicate keys silently override earlier ones: {sorted(set(seen))}"


# --------------------------------------------------------------------------------------
# Undeclared-field regression guard.
#
# `additionalProperties: false` means an undeclared field is not merely unvalidated, it is
# REJECTED -- and by this repo's idiom an undeclared field is also an unread field, because
# the contract tells every reader it does not exist. Three lineage fields have now shipped
# undeclared, each populated by an archive-side pass and read by nothing:
#
#     derived_from        27 sidecars
#     files.variant_of    96 sidecars
#     source_image       898 sidecars
#
# CI cannot detect a NEW occurrence: the corpus lives outside the repo (under
# Dropbox/Pictures/Art/works) and no runner can see it -- use
# Metadata/tools/check_sidecar_drift.py against the live corpus for that. What CI can do is
# stop the reverse: a schema edit that silently drops one of these and re-orphans the data.
# --------------------------------------------------------------------------------------

LINEAGE_FIELDS_IN_USE = [
    (("source_image",), 898, "the pre-archive parent a master was cut from"),
    (("source_image", "crop_region"), 46, "where the master sits inside that parent"),
    (("files", "variant_of"), 96, "this holding is a rendition of another archived work"),
    (("derived_from",), 27, "this work is a section of another archived work"),
]


def _declared(path):
    """Walk `properties` down a dotted path; return the subschema or None."""
    node = sidecar.SCHEMA if hasattr(sidecar, "SCHEMA") else json.loads(
        sidecar.SCHEMA_PATH.read_text()
    )
    for key in path:
        props = node.get("properties")
        if not isinstance(props, dict) or key not in props:
            return None
        node = props[key]
    return node


@pytest.mark.parametrize("path,populated,why", LINEAGE_FIELDS_IN_USE)
def test_lineage_field_stays_declared(path, populated, why):
    """Dropping one of these re-orphans data that is already written."""
    assert _declared(path) is not None, (
        f"{'.'.join(path)} is no longer declared in meta.schema.json, but ~{populated} "
        f"sidecars already carry it ({why}). additionalProperties:false makes those "
        f"sidecars invalid and the field unreadable. Re-declare it, or migrate the corpus "
        f"first and update this test in the same change."
    )


def test_lineage_fields_are_reachable_through_closed_objects():
    """A declared child is useless if an ancestor forbids the branch it hangs from."""
    for path, populated, _why in LINEAGE_FIELDS_IN_USE:
        for depth in range(1, len(path) + 1):
            assert _declared(path[:depth]) is not None, (
                f"{'.'.join(path)} is unreachable: {'.'.join(path[:depth])} is undeclared "
                f"while ~{populated} sidecars depend on the full path."
            )
