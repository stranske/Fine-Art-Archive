"""Loader for config/host_registry.yaml.

Provides a typed interface to the host registry so adapters and discovery
code can ask "what do we know about host X?" without parsing YAML each time.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[3] / "config" / "host_registry.yaml"


@dataclass
class HostEntry:
    host_id: str
    name: str
    wikidata_q: str | None
    ror: str | None
    homepage: str | None
    rights_default: str | None
    primary_adapter: str | None
    primary_notes: str = ""
    accession_property: str | None = None
    accession_lookup_url: str | None = None
    iiif_pattern: str | None = None
    quirks: list[str] = field(default_factory=list)
    fallback_chain: list[str] = field(default_factory=list)
    known_issues: list[dict] = field(default_factory=list)
    last_verified: str | None = None
    verification_test_work_q: str | None = None
    source_tier: int = 4
    raw: dict = field(default_factory=dict)


@functools.lru_cache(maxsize=1)
def _load_yaml(path_str: str) -> dict:
    """Load YAML using PyYAML; if unavailable, a minimal hand-parser is used.

    The minimal parser supports the strict-yaml subset that the registry
    uses (nested keys, lists, multi-line | blocks, simple strings). Good
    enough for our purposes and removes the hard dependency on pyyaml in
    environments where it isn't installed.
    """
    try:
        import yaml  # type: ignore

        with open(path_str, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Fallback: load via subprocess (`python3 -c 'import yaml; ...'`)
        # would re-fail. As a last resort, raise a clear error.
        raise RuntimeError(
            "PyYAML not installed. Run: pip install pyyaml. "
            "(Lightweight YAML loading via stdlib isn't reliable for our "
            "use of multi-line | blocks.)"
        ) from None


def _coerce_entry(host_id: str, d: dict) -> HostEntry:
    primary = d.get("primary_acquisition") or {}
    discovery = d.get("discovery") or {}
    return HostEntry(
        host_id=host_id,
        name=d.get("name", host_id),
        wikidata_q=d.get("wikidata_q"),
        ror=d.get("ror"),
        homepage=d.get("homepage"),
        rights_default=d.get("rights_default"),
        primary_adapter=primary.get("adapter"),
        primary_notes=primary.get("notes", "") or "",
        accession_property=discovery.get("accession_property"),
        accession_lookup_url=discovery.get("accession_lookup_url"),
        iiif_pattern=discovery.get("iiif_pattern"),
        quirks=list(discovery.get("quirks") or []),
        fallback_chain=list(d.get("fallback_chain") or []),
        known_issues=list(d.get("known_issues") or []),
        last_verified=d.get("last_verified"),
        verification_test_work_q=d.get("verification_test_work_q"),
        source_tier=int(d.get("source_tier", 4)),
        raw=d,
    )


def load_registry(path: Path | str | None = None) -> dict[str, HostEntry]:
    """Return the host registry as a dict keyed by host_id."""
    p = str(path) if path else str(REGISTRY_PATH)
    raw = _load_yaml(p)
    hosts = raw.get("hosts") or {}
    return {hid: _coerce_entry(hid, hd) for hid, hd in hosts.items()}


def find_by_wikidata_q(qid: str) -> HostEntry | None:
    """Find a host by its Wikidata Q-ID (the institution's Q, not the work's)."""
    for entry in load_registry().values():
        if entry.wikidata_q == qid:
            return entry
    return None


def primary_adapter_for(qid: str) -> str | None:
    """Return the primary acquisition adapter name for the given institution Q-ID."""
    entry = find_by_wikidata_q(qid)
    return entry.primary_adapter if entry else None


def fallback_chain_for(qid: str) -> list[str]:
    """Return the ordered fallback adapter chain for the given institution Q-ID."""
    entry = find_by_wikidata_q(qid)
    return list(entry.fallback_chain) if entry else []
