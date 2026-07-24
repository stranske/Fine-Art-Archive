"""Tests for collect/host_registry.py loader and lookup helpers."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from fine_art_archive.collect import host_registry as hr


@pytest.fixture(autouse=True)
def _clear_yaml_cache() -> Generator[None]:
    hr._load_yaml.cache_clear()
    yield
    hr._load_yaml.cache_clear()


FULL_HOST_YAML = """\
schema_version: "1.0"
hosts:
  full_museum:
    name: Full Museum
    aliases:
      - Museum, Full
    wikidata_q: Q999001
    ror: abc123
    homepage: https://example.org/
    rights_default: public-domain
    primary_acquisition:
      adapter: test_adapter
      notes: |
        Multi-line note
        second line
    discovery:
      api_base: "https://api.example.org/objects/{accession}"
      accession_property: P350
      accession_lookup_url: "https://example.org/{accession}"
      iiif_pattern: "https://iiif.example/{id}/full/max/0/default.jpg"
      field_map:
        medium:
          - materials
          - technique
      quirks:
        - quirk one
    fallback_chain:
      - wikimedia_commons
      - google_arts_culture
    known_issues:
      - date: "2026-05-17"
        description: Something broke
        workaround: Use og:image
    last_verified: "2026-05-17"
    verification_test_work_q: Q123456
    source_tier: 2

  minimal_host:
    name: Minimal Host
"""

MINIMAL_HOSTS_YAML = """\
schema_version: "1.0"
hosts:
  bare:
    wikidata_q: Q888002
"""


def _write_registry(tmp_path: Path, content: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "host_registry.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_registry_coerces_full_entry(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, FULL_HOST_YAML)
    registry = hr.load_registry(path)

    assert set(registry) == {"full_museum", "minimal_host"}
    entry = registry["full_museum"]
    assert entry.host_id == "full_museum"
    assert entry.name == "Full Museum"
    assert entry.wikidata_q == "Q999001"
    assert entry.ror == "abc123"
    assert entry.homepage == "https://example.org/"
    assert entry.rights_default == "public-domain"
    assert entry.primary_adapter == "test_adapter"
    assert "Multi-line note" in entry.primary_notes
    assert entry.aliases == ["Museum, Full"]
    assert entry.api_base == "https://api.example.org/objects/{accession}"
    assert entry.accession_property == "P350"
    assert entry.accession_lookup_url == "https://example.org/{accession}"
    assert entry.iiif_pattern == "https://iiif.example/{id}/full/max/0/default.jpg"
    assert entry.field_map == {"medium": ["materials", "technique"]}
    assert entry.quirks == ["quirk one"]
    assert entry.fallback_chain == ["wikimedia_commons", "google_arts_culture"]
    assert entry.known_issues == [
        {
            "date": "2026-05-17",
            "description": "Something broke",
            "workaround": "Use og:image",
        }
    ]
    assert entry.last_verified == "2026-05-17"
    assert entry.verification_test_work_q == "Q123456"
    assert entry.source_tier == 2
    assert entry.raw["name"] == "Full Museum"


def test_load_registry_applies_defaults_for_missing_optional_sections(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, MINIMAL_HOSTS_YAML)
    entry = hr.load_registry(path)["bare"]

    assert entry.host_id == "bare"
    assert entry.name == "bare"
    assert entry.wikidata_q == "Q888002"
    assert entry.ror is None
    assert entry.homepage is None
    assert entry.rights_default is None
    assert entry.primary_adapter is None
    assert entry.primary_notes == ""
    assert entry.aliases == []
    assert entry.api_base is None
    assert entry.accession_property is None
    assert entry.accession_lookup_url is None
    assert entry.iiif_pattern is None
    assert entry.field_map == {}
    assert entry.quirks == []
    assert entry.fallback_chain == []
    assert entry.known_issues == []
    assert entry.last_verified is None
    assert entry.verification_test_work_q is None
    assert entry.source_tier == 4


def test_load_registry_empty_hosts_section(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, 'schema_version: "1.0"\n')
    assert hr.load_registry(path) == {}


def test_load_registry_does_not_leak_cached_yaml_between_paths(tmp_path: Path) -> None:
    path_a = _write_registry(tmp_path / "a", MINIMAL_HOSTS_YAML)
    path_b = _write_registry(
        tmp_path / "b",
        'schema_version: "1.0"\nhosts:\n  other:\n    name: Other\n',
    )

    assert set(hr.load_registry(path_a)) == {"bare"}
    assert set(hr.load_registry(path_b)) == {"other"}
    assert set(hr.load_registry(path_a)) == {"bare"}


def test_find_by_wikidata_q(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = hr.load_registry(_write_registry(tmp_path, FULL_HOST_YAML))
    monkeypatch.setattr(hr, "load_registry", lambda path=None: registry)

    found = hr.find_by_wikidata_q("Q999001")
    assert found is not None
    assert found.host_id == "full_museum"

    assert hr.find_by_wikidata_q("Q000000") is None


def test_find_by_holder_uses_qid_ror_then_normalized_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = hr.load_registry(_write_registry(tmp_path, FULL_HOST_YAML))
    monkeypatch.setattr(hr, "load_registry", lambda path=None: registry)

    qid_match = hr.find_by_holder(wikidata_q="Q999001")
    ror_match = hr.find_by_holder(ror="ABC123")
    name_match = hr.find_by_holder(name="museum full")
    assert qid_match is not None and qid_match.host_id == "full_museum"
    assert ror_match is not None and ror_match.host_id == "full_museum"
    assert name_match is not None and name_match.host_id == "full_museum"
    assert hr.find_by_holder(name="Missing Museum") is None


def test_production_registry_loads_and_validates_expanded_hosts() -> None:
    registry = hr.load_registry()

    assert {
        "national_gallery_of_art_us",
        "harvard_art_museums",
        "j_paul_getty_museum",
        "smithsonian_institution",
        "walters_art_museum",
        "victoria_and_albert",
        "cooper_hewitt",
        "national_gallery_london",
        "museum_of_modern_art",
        "tate",
        "van_gogh_museum",
        "mauritshuis",
        "museo_del_prado",
        "national_gallery_prague",
        "lacma",
        "alte_nationalgalerie",
        "staedel_museum",
        "musee_d_orsay",
        "kunsthistorisches_museum",
    } <= registry.keys()
    assert registry["victoria_and_albert"].api_base == (
        "https://api.vam.ac.uk/v2/museumobject/{accession}"
    )
    assert registry["victoria_and_albert"].accession_property == "P3929"
    assert registry["harvard_art_museums"].iiif_pattern == (
        "https://iiif.harvardartmuseums.org/manifests/object/{accession}"
    )


@pytest.mark.parametrize(
    "content",
    [
        'schema_version: "2.0"\nhosts: {}\n',
        "- not-an-object\n",
        'schema_version: "1.0"\nhosts:\n  Bad-ID:\n    name: Bad\n',
        ('schema_version: "1.0"\nhosts:\n  bad:\n    name: Bad\n' "    wikidata_q: not-a-qid\n"),
        (
            'schema_version: "1.0"\nhosts:\n  bad:\n    name: Bad\n'
            "    discovery:\n      accession_property: accession\n"
        ),
    ],
)
def test_invalid_registry_fails_loudly(tmp_path: Path, content: str) -> None:
    path = _write_registry(tmp_path, content)

    with pytest.raises(hr.RegistryError):
        hr.load_registry(path)


def test_primary_adapter_for(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = hr.load_registry(_write_registry(tmp_path, FULL_HOST_YAML))
    monkeypatch.setattr(hr, "load_registry", lambda path=None: registry)

    assert hr.primary_adapter_for("Q999001") == "test_adapter"
    assert hr.primary_adapter_for("Q000000") is None


def test_fallback_chain_for(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = hr.load_registry(_write_registry(tmp_path, FULL_HOST_YAML))
    monkeypatch.setattr(hr, "load_registry", lambda path=None: registry)

    assert hr.fallback_chain_for("Q999001") == [
        "wikimedia_commons",
        "google_arts_culture",
    ]
    assert hr.fallback_chain_for("Q000000") == []
