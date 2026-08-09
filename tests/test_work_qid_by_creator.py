"""Tests for SPARQL by-creator work-QID resolution + backfill CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.backfill_work_qids_by_creator import backfill

from fine_art_archive.enrichment import holder_by_creator as hbc
from fine_art_archive.enrichment import work_qid_by_creator as wqc

# Reuse the holder test's binding + fake-client shape.
from tests.test_holder_by_creator import BASE, FakeSparql, _binding


def _work(
    qid: str, label: str, *, inception: str | None = None, aliases: tuple[str, ...] = ()
) -> hbc.CreatorWork:
    return hbc.CreatorWork(
        work_qid=qid,
        label=label,
        collection_qid=None,
        collection_label=None,
        ror=None,
        url=None,
        accession=None,
        inception=inception,
        aliases=aliases,
    )


def _uncat_sidecar(
    work_id: str, title: str, *, artist_qid: str | None = "Q296", year: str | None = "1889"
) -> dict[str, Any]:
    meta = json.loads(json.dumps(BASE))
    meta["work_id"] = work_id
    meta["title"] = title
    meta["artist"] = {"name": "Example"}
    if artist_qid:
        meta["artist"]["wikidata_q"] = artist_qid
    if year is None:
        meta.pop("year", None)
    else:
        meta["year"] = year
    return meta


def _write(tmp_path: Path, meta: dict[str, Any]) -> Path:
    path = tmp_path / meta["work_id"] / "meta.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


# --- match_work_entity (the extracted, holder-independent core) ---------------


def test_entity_match_returns_work_without_requiring_holder() -> None:
    # A confident title match whose work has NO collection/location: match_work
    # rejects it as "no-collection", but match_work_entity still identifies it.
    works = hbc.works_by_creator(
        "Q296",
        client=FakeSparql(
            [
                _binding("Q1", "The Starry Night", inception="1889"),  # no coll, no loc
                _binding("Q2", "Irises", inception="1889"),
            ]
        ),
    )
    assert hbc.match_work("The Starry Night", 1889, works)[1] == "no-collection"
    best, score, reason = hbc.match_work_entity("The Starry Night", 1889, works)
    assert reason == "match"
    assert best is not None and best.work_qid == "Q1"
    assert score >= 0.93


def test_entity_match_preserves_guards() -> None:
    works = hbc.works_by_creator(
        "Q296",
        client=FakeSparql(
            [
                # same-title-different-work: two works both score 1.0 -> ambiguous
                _binding("Q1", "Saint Jerome", inception="1605"),
                _binding("Q2", "Saint Jerome", inception="1607"),
            ]
        ),
    )
    assert hbc.match_work_entity("Saint Jerome", None, works)[2] == "ambiguous"

    # Same work held in several collections -> several identical-score rows for
    # one work_qid. Those are the same answer, not a competitor: still a match.
    dup = hbc.works_by_creator(
        "Q297",
        client=FakeSparql(
            [
                _binding("Q1", "Old Woman Cooking Eggs", coll="Q100", inception="1618"),
                _binding("Q1", "Old Woman Cooking Eggs", coll="Q200", inception="1618"),
            ]
        ),
    )
    best, _score, reason = hbc.match_work_entity("Old Woman Cooking Eggs", None, dup)
    assert reason == "match"
    assert best is not None and best.work_qid == "Q1"
    assert hbc.match_work_entity("Completely Different", None, works)[2] == "below-threshold"
    # year disagreement beyond tolerance
    yr = hbc.works_by_creator(
        "Q296", client=FakeSparql([_binding("Q1", "Irises", inception="1600")])
    )
    assert hbc.match_work_entity("Irises", 1889, yr)[2] == "year-mismatch"


# --- Tier B: alias + normalized-title matching --------------------------------


def test_matches_on_leading_article_difference() -> None:
    works = [_work("Q1", "The Burial of Saint Lucy", inception="1608"), _work("Q2", "Irises")]
    best, score, reason = hbc.match_work_entity("Burial of Saint Lucy", None, works)
    assert reason == "match" and best.work_qid == "Q1" and score >= 0.99


def test_matches_on_alias_when_primary_label_differs() -> None:
    # museum title lives in the altLabels, not the primary label
    works = [
        _work("Q1", "Woman with a Parasol", aliases=("Madame Monet and Her Son",), inception="1875")
    ]
    best, _s, reason = hbc.match_work_entity("Madame Monet and Her Son", None, works)
    assert reason == "match" and best.work_qid == "Q1"


def test_distinct_variant_titles_do_not_merge() -> None:
    # 'Vase with Gladioli' must NOT swallow 'Vase with Gladioli and Chinese Asters'
    works = [
        _work("Q1", "Vase with Gladioli", inception="1886"),
        _work("Q2", "Vase with Gladioli and Chinese Asters", inception="1886"),
    ]
    best, _s, reason = hbc.match_work_entity("Vase with Gladioli", None, works)
    assert reason == "match" and best.work_qid == "Q1"  # exact wins, variant scores lower


# --- Tier B: year as the discriminator among same-title works ------------------

# years spaced >1 apart so a single year uniquely selects within the tight window
_SELF_PORTRAITS = [
    _work("Q1", "Self-Portrait", inception="1887-01-01T00:00:00Z"),
    _work("Q2", "Self-Portrait", inception="1889-01-01T00:00:00Z"),
    _work("Q3", "Self-Portrait", inception="1892-01-01T00:00:00Z"),
]


def test_holder_disambiguates_same_title_cluster() -> None:
    # two same-title works in different collections; the sidecar's holder picks one
    works = [
        _work("Q1", "Saint Jerome", inception="1605"),
        _work("Q2", "Saint Jerome", inception="1607"),
    ]
    works[0] = hbc.CreatorWork(
        work_qid="Q1",
        label="Saint Jerome",
        collection_qid="Q_BORGHESE",
        collection_label=None,
        ror=None,
        url=None,
        accession=None,
        inception="1605",
    )
    works[1] = hbc.CreatorWork(
        work_qid="Q2",
        label="Saint Jerome",
        collection_qid="Q_VALLETTA",
        collection_label=None,
        ror=None,
        url=None,
        accession=None,
        inception="1607",
    )
    # no year -> would be ambiguous; holder resolves it
    assert hbc.match_work_entity("Saint Jerome", None, works)[2] == "ambiguous"
    best, _s, reason = hbc.match_work_entity("Saint Jerome", None, works, holder_qid="Q_VALLETTA")
    assert reason == "match" and best.work_qid == "Q2"
    # a holder matching NEITHER (or both) still declines
    assert (
        hbc.match_work_entity("Saint Jerome", None, works, holder_qid="Q_OTHER")[2] == "ambiguous"
    )


def test_year_in_title_disambiguates_same_title_works() -> None:
    best, _s, reason = hbc.match_work_entity("Self-Portrait (1889)", None, _SELF_PORTRAITS)
    assert reason == "match" and best.work_qid == "Q2"


def test_sidecar_year_disambiguates_when_title_has_no_year() -> None:
    best, _s, reason = hbc.match_work_entity("Self-Portrait", 1887, _SELF_PORTRAITS)
    assert reason == "match" and best.work_qid == "Q1"


def test_same_title_without_any_year_is_ambiguous() -> None:
    _best, _s, reason = hbc.match_work_entity("Self-Portrait", None, _SELF_PORTRAITS)
    assert reason == "ambiguous"


def test_year_discriminator_requires_uniqueness() -> None:
    # two self-portraits within the tight window of the target year -> still ambiguous
    close = [
        _work("Q1", "Self-Portrait", inception="1888"),
        _work("Q2", "Self-Portrait", inception="1889"),
    ]
    _best, _s, reason = hbc.match_work_entity("Self-Portrait (1888)", None, close)
    assert reason == "ambiguous"  # 1888 within +/-1 of both 1888 and 1889


def test_year_discriminator_is_tight_not_lenient() -> None:
    # a lone self-portrait 5 years off: single-candidate path uses lenient +/-6 -> matches
    lone = [_work("Q1", "Self-Portrait", inception="1892")]
    _b, _s, reason = hbc.match_work_entity("Self-Portrait (1887)", None, lone)
    assert reason == "match"
    # but as a DISCRIMINATOR among a cluster, +/-6 is too loose -> the 5-year-off
    # candidate is not a survivor, so a 2-member cluster resolves to the exact one
    cluster = [
        _work("Q1", "Self-Portrait", inception="1892"),
        _work("Q2", "Self-Portrait", inception="1887"),
    ]
    best, _s, reason = hbc.match_work_entity("Self-Portrait (1887)", None, cluster)
    assert reason == "match" and best.work_qid == "Q2"


# --- resolve_work_qid ---------------------------------------------------------


class _DimsSparql:
    """FakeSparql that also answers the P2048/P2049 dimensions query."""

    def __init__(
        self, bindings: list[dict[str, Any]], dims: dict[str, tuple[float, float]]
    ) -> None:
        self._payload = {"results": {"bindings": bindings}}
        self._dims = dims

    def query(self, sparql: str) -> dict[str, Any]:
        if "P2048" in sparql:
            rows = []
            for qid, (h, w) in self._dims.items():
                cm = "http://www.wikidata.org/entity/Q174728"
                rows.append(
                    {
                        "w": {"value": f"http://www.wikidata.org/entity/{qid}"},
                        "h": {"value": str(h)},
                        "hu": {"value": cm},
                        "wd": {"value": str(w)},
                        "wu": {"value": cm},
                    }
                )
            return {"results": {"bindings": rows}}
        return self._payload


def test_dimensions_disambiguate_same_title_cluster() -> None:
    # two same-title works, no year/holder to split them; sidecar dims pick one
    client = _DimsSparql(
        [
            _binding("Q1", "Saint Jerome"),
            _binding("Q2", "Saint Jerome"),
        ],
        dims={"Q1": (100.0, 80.0), "Q2": (50.0, 40.0)},
    )
    # without dims -> ambiguous
    assert wqc.resolve_work_qid("Saint Jerome", None, "Q296", client=client)[1] == "ambiguous"
    # sidecar 50x40 uniquely matches Q2
    match, reason = wqc.resolve_work_qid(
        "Saint Jerome", None, "Q296", client=client, dimensions=(50.0, 40.0)
    )
    assert reason == "match" and match.work_qid == "Q2"
    # dims matching neither -> still ambiguous
    assert (
        wqc.resolve_work_qid("Saint Jerome", None, "Q296", client=client, dimensions=(200.0, 5.0))[
            1
        ]
        == "ambiguous"
    )


class _MediumSparql:
    """FakeSparql that also answers the P31 medium-label query."""

    def __init__(self, bindings: list[dict[str, Any]], media: dict[str, str]) -> None:
        self._payload = {"results": {"bindings": bindings}}
        self._media = media

    def query(self, sparql: str) -> dict[str, Any]:
        if "typeLabel" in sparql:
            rows = [
                {"w": {"value": f"http://www.wikidata.org/entity/{q}"}, "typeLabel": {"value": lbl}}
                for q, lbl in self._media.items()
            ]
            return {"results": {"bindings": rows}}
        return self._payload


def test_medium_disambiguates_print_from_painting() -> None:
    # Benton's "Aaron" exists as both a painting (PAFA) and a lithograph (NGA).
    client = _MediumSparql(
        [_binding("Q1", "Aaron"), _binding("Q2", "Aaron")],
        media={"Q1": "painting", "Q2": "lithograph"},
    )
    # no discriminator -> ambiguous
    assert wqc.resolve_work_qid("Aaron", None, "Q471764", client=client)[1] == "ambiguous"
    # sidecar is a print -> the lithograph
    match, reason = wqc.resolve_work_qid("Aaron", None, "Q471764", client=client, category="print")
    assert reason == "match" and match.work_qid == "Q2"
    # sidecar is a painting -> the painting
    match, reason = wqc.resolve_work_qid(
        "Aaron", None, "Q471764", client=client, category="painting"
    )
    assert reason == "match" and match.work_qid == "Q1"
    # a medium neither candidate has -> still ambiguous
    assert (
        wqc.resolve_work_qid("Aaron", None, "Q471764", client=client, category="sculpture")[1]
        == "ambiguous"
    )


def test_resolve_work_qid_match() -> None:
    client = FakeSparql(
        [
            _binding("Q1", "The Starry Night", inception="1889"),
            _binding("Q2", "Irises", inception="1889"),
        ]
    )
    match, reason = wqc.resolve_work_qid("The Starry Night", 1889, "Q296", client=client)
    assert reason == "match"
    assert match is not None and match.work_qid == "Q1"


def test_resolve_work_qid_no_creator() -> None:
    match, reason = wqc.resolve_work_qid("x", None, "", client=FakeSparql([]))
    assert match is None and reason == "no-creator"


def test_wrong_creator_declines_rather_than_mismatches() -> None:
    # creator's works never title-match -> no write (self-defending guard)
    client = FakeSparql([_binding("Q9", "Some Unrelated Work", inception="1700")])
    match, reason = wqc.resolve_work_qid("The Starry Night", 1889, "Q999", client=client)
    assert match is None and reason == "below-threshold"


# --- backfill CLI -------------------------------------------------------------


def test_backfill_writes_qid_and_provenance(tmp_path: Path) -> None:
    path = _write(tmp_path, _uncat_sidecar("1111111-starry-night", "The Starry Night"))
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, reasons = backfill(tmp_path, client=client, apply=True)

    assert stats.attempted == 1 and stats.resolved == 1
    written = json.loads(path.read_text())
    assert written["stable_identifiers"]["wikidata_q"] == "Q1"
    entry = written["field_provenance"]["work_qid"]
    assert entry["status"] == "available" and entry["source"] == "wikidata"
    assert entry["source_ref"] == "https://www.wikidata.org/wiki/Q1"


def test_dry_run_reports_without_writing(tmp_path: Path) -> None:
    path = _write(tmp_path, _uncat_sidecar("1111111-starry-night", "The Starry Night"))
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, _ = backfill(tmp_path, client=client, apply=False)

    assert len(stats.matches) == 1 and stats.resolved == 0
    assert "stable_identifiers" not in json.loads(path.read_text())


def test_skips_categorized_and_already_qided(tmp_path: Path) -> None:
    # categorized -> ineligible
    cat = _uncat_sidecar("2222222-categorized", "The Starry Night")
    cat["category"] = "painting"
    _write(tmp_path, cat)
    # already has a work QID -> ineligible
    qided = _uncat_sidecar("3333330-already-qided", "The Starry Night")
    qided["stable_identifiers"] = {"wikidata_q": "Q1"}
    _write(tmp_path, qided)
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, _ = backfill(tmp_path, client=client, apply=True)

    assert stats.attempted == 0 and stats.resolved == 0


def test_include_categorized_resolves_categorized_qidless_works(tmp_path: Path) -> None:
    # a categorized work with a creator but no work QID: skipped by default,
    # resolved with include_categorized (so holder/IIIF can use the work QID).
    cat = _uncat_sidecar("2222222-categorized", "The Starry Night")
    cat["category"] = "painting"
    _write(tmp_path, cat)
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    default_stats, _ = backfill(tmp_path, client=client, apply=False)
    assert default_stats.attempted == 0  # skipped by default

    inc_stats, _ = backfill(tmp_path, client=client, apply=True, include_categorized=True)
    assert inc_stats.attempted == 1 and inc_stats.resolved == 1
    assert (
        json.loads((tmp_path / "2222222-categorized" / "meta.json").read_text())[
            "stable_identifiers"
        ]["wikidata_q"]
        == "Q1"
    )


def test_include_categorized_still_skips_already_qided(tmp_path: Path) -> None:
    qided = _uncat_sidecar("3333330-already-qided", "The Starry Night")
    qided["category"] = "painting"
    qided["stable_identifiers"] = {"wikidata_q": "Q99"}
    _write(tmp_path, qided)
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, _ = backfill(tmp_path, client=client, apply=True, include_categorized=True)
    assert stats.attempted == 0  # a work that already has a QID is never re-touched


def test_preexisting_invalid_sidecar_is_skipped_not_fatal(tmp_path: Path) -> None:
    # a sidecar already schema-invalid for an unrelated reason (out-of-tree key)
    # must be skipped, not abort the whole pass.
    bad = _uncat_sidecar("1111111-bad", "The Starry Night")
    bad["stable_identifiers"] = {"not_a_schema_key": "x"}  # out-of-schema -> invalid
    _write(tmp_path, bad)
    good = _uncat_sidecar("2222222-good", "The Starry Night")
    _write(tmp_path, good)
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, reasons = backfill(tmp_path, client=client, apply=True)

    # the good one resolves; the invalid one is skipped, not fatal
    assert stats.resolved == 1
    assert reasons["skipped-invalid-sidecar"] == 1
    assert (
        "wikidata_q"
        not in json.loads((tmp_path / "1111111-bad" / "meta.json").read_text())[
            "stable_identifiers"
        ]
    )


def test_no_creator_qid_is_reported_not_guessed(tmp_path: Path) -> None:
    _write(tmp_path, _uncat_sidecar("4444444-no-artist", "The Starry Night", artist_qid=None))
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, reasons = backfill(tmp_path, client=client, apply=True)

    assert stats.attempted == 0 and stats.resolved == 0
    assert stats.needs_artist == 1
    assert reasons["no-creator-qid"] == 1


def test_mirror_and_log(tmp_path: Path) -> None:
    _write(tmp_path, _uncat_sidecar("1111111-starry-night", "The Starry Night"))
    art_root = tmp_path / "art"
    mirror = art_root / "1111111-starry-night" / "meta.json"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(
        json.dumps(_uncat_sidecar("1111111-starry-night", "The Starry Night")), encoding="utf-8"
    )
    log = tmp_path / "operations.log"
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, _ = backfill(
        tmp_path, client=client, art_works_root=art_root, operations_log=log, apply=True
    )

    assert stats.mirrored == 1
    assert json.loads(mirror.read_text())["stable_identifiers"]["wikidata_q"] == "Q1"
    logged = json.loads(log.read_text().strip())
    assert logged["op"] == "work_qid_by_creator_backfill"
    assert logged["matched_work_qid"] == "Q1"
