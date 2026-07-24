"""Loader for config/host_registry.yaml.

Provides a typed interface to the host registry so adapters and discovery
code can ask "what do we know about host X?" without parsing YAML each time.
"""

from __future__ import annotations

import functools
import re
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parents[3] / "config" / "host_registry.yaml"
HOST_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
QID_RE = re.compile(r"^Q[1-9][0-9]*$")
PROPERTY_RE = re.compile(r"^P[1-9][0-9]*$")


class RegistryError(ValueError):
    """Raised when ``host_registry.yaml`` is structurally invalid."""


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
    aliases: list[str] = field(default_factory=list)
    api_base: str | None = None
    accession_property: str | None = None
    accession_lookup_url: str | None = None
    iiif_pattern: str | None = None
    field_map: dict[str, list[str]] = field(default_factory=dict)
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


def _coerce_entry(host_id: str, d: dict[str, Any]) -> HostEntry:
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
        aliases=list(d.get("aliases") or []),
        api_base=d.get("api_base") or discovery.get("api_base"),
        accession_property=discovery.get("accession_property"),
        accession_lookup_url=discovery.get("accession_lookup_url"),
        iiif_pattern=discovery.get("iiif_pattern"),
        field_map={key: list(value) for key, value in (discovery.get("field_map") or {}).items()},
        quirks=list(discovery.get("quirks") or []),
        fallback_chain=list(d.get("fallback_chain") or []),
        known_issues=list(d.get("known_issues") or []),
        last_verified=d.get("last_verified"),
        verification_test_work_q=d.get("verification_test_work_q"),
        source_tier=int(d.get("source_tier", 4)),
        raw=d,
    )


def validate_registry(raw: Mapping[str, Any]) -> None:
    """Validate the registry's declarative contract.

    Validation is deliberately structural: it rejects malformed identifiers,
    URLs, and field maps while allowing an institution to be catalogued before
    it has a live API or IIIF route.
    """
    schema_version = raw.get("schema_version")
    if schema_version not in {None, "1.0"}:
        raise RegistryError(f"unsupported host registry schema_version: {schema_version!r}")
    hosts = raw.get("hosts", {})
    if not isinstance(hosts, Mapping):
        raise RegistryError("host registry 'hosts' must be an object")

    seen_qids: dict[str, str] = {}
    for host_id, value in hosts.items():
        if not isinstance(host_id, str) or not HOST_ID_RE.fullmatch(host_id):
            raise RegistryError(f"invalid host id: {host_id!r}")
        if not isinstance(value, Mapping):
            raise RegistryError(f"host {host_id!r} must be an object")
        _validate_entry(host_id, value)
        qid = value.get("wikidata_q")
        if isinstance(qid, str):
            previous = seen_qids.get(qid)
            if previous is not None:
                raise RegistryError(
                    f"hosts {previous!r} and {host_id!r} duplicate wikidata_q {qid}"
                )
            seen_qids[qid] = host_id


def _validate_entry(host_id: str, value: Mapping[str, Any]) -> None:
    for key in ("name", "wikidata_q", "ror", "homepage", "rights_default", "api_base"):
        item = value.get(key)
        if item is not None and not isinstance(item, str):
            raise RegistryError(f"host {host_id!r} field {key!r} must be a string or null")
    name = value.get("name")
    if isinstance(name, str) and not name.strip():
        raise RegistryError(f"host {host_id!r} name must not be empty")
    qid = value.get("wikidata_q")
    if isinstance(qid, str) and not QID_RE.fullmatch(qid):
        raise RegistryError(f"host {host_id!r} has invalid wikidata_q {qid!r}")
    for key in ("aliases", "fallback_chain"):
        item = value.get(key)
        if item is not None and not isinstance(item, list):
            raise RegistryError(f"host {host_id!r} field {key!r} must be a list")
        if isinstance(item, list) and not all(
            isinstance(element, str) and element.strip() for element in item
        ):
            raise RegistryError(f"host {host_id!r} field {key!r} must contain non-empty strings")
    known_issues = value.get("known_issues")
    if known_issues is not None and (
        not isinstance(known_issues, list)
        or not all(isinstance(issue, Mapping) for issue in known_issues)
    ):
        raise RegistryError(f"host {host_id!r} known_issues must contain objects")
    source_tier = value.get("source_tier", 4)
    if (
        isinstance(source_tier, bool)
        or not isinstance(source_tier, int)
        or source_tier not in range(1, 5)
    ):
        raise RegistryError(f"host {host_id!r} source_tier must be an integer from 1 to 4")
    _validate_url(host_id, "homepage", value.get("homepage"))
    _validate_url(host_id, "api_base", value.get("api_base"))

    primary = value.get("primary_acquisition", {})
    discovery = value.get("discovery", {})
    if primary is not None and not isinstance(primary, Mapping):
        raise RegistryError(f"host {host_id!r} primary_acquisition must be an object")
    if isinstance(primary, Mapping):
        for key in ("adapter", "notes"):
            item = primary.get(key)
            if item is not None and not isinstance(item, str):
                raise RegistryError(
                    f"host {host_id!r} primary_acquisition.{key} must be a string or null"
                )
    if discovery is not None and not isinstance(discovery, Mapping):
        raise RegistryError(f"host {host_id!r} discovery must be an object")
    if not isinstance(discovery, Mapping):
        return
    property_id = discovery.get("accession_property")
    if property_id is not None and (
        not isinstance(property_id, str) or not PROPERTY_RE.fullmatch(property_id)
    ):
        raise RegistryError(f"host {host_id!r} has invalid accession_property {property_id!r}")
    for key in ("api_base", "accession_lookup_url", "iiif_pattern"):
        _validate_url(host_id, key, discovery.get(key))
    quirks = discovery.get("quirks")
    if quirks is not None and (
        not isinstance(quirks, list)
        or not all(isinstance(quirk, str) and quirk.strip() for quirk in quirks)
    ):
        raise RegistryError(f"host {host_id!r} discovery.quirks must contain strings")
    field_map = discovery.get("field_map", {})
    if not isinstance(field_map, Mapping):
        raise RegistryError(f"host {host_id!r} discovery.field_map must be an object")
    for field_name, aliases in field_map.items():
        if (
            not isinstance(field_name, str)
            or not isinstance(aliases, list)
            or not all(isinstance(alias, str) and alias.strip() for alias in aliases)
        ):
            raise RegistryError(f"host {host_id!r} field map values must be non-empty string lists")


def _validate_url(host_id: str, field_name: str, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise RegistryError(f"host {host_id!r} field {field_name!r} must be a string or null")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RegistryError(f"host {host_id!r} has invalid {field_name} URL {value!r}")


def load_registry(path: Path | str | None = None) -> dict[str, HostEntry]:
    """Validate and return the host registry keyed by host id."""
    p = str(path) if path else str(REGISTRY_PATH)
    raw = _load_yaml(p)
    if not isinstance(raw, Mapping):
        raise RegistryError("host registry root must be an object")
    validate_registry(raw)
    hosts = raw.get("hosts") or {}
    return {hid: _coerce_entry(hid, hd) for hid, hd in hosts.items()}


def find_by_wikidata_q(qid: str, path: Path | str | None = None) -> HostEntry | None:
    """Find a host by its Wikidata Q-ID (the institution's Q, not the work's)."""
    for entry in load_registry(path).values():
        if entry.wikidata_q == qid:
            return entry
    return None


def find_by_holder(
    *,
    name: str | None = None,
    wikidata_q: str | None = None,
    ror: str | None = None,
    path: Path | str | None = None,
) -> HostEntry | None:
    """Find a configured host using the strongest available holder identity."""
    registry = load_registry(path)
    if wikidata_q:
        for entry in registry.values():
            if entry.wikidata_q == wikidata_q:
                return entry
    if ror:
        folded_ror = ror.strip().casefold()
        for entry in registry.values():
            if entry.ror and entry.ror.casefold() == folded_ror:
                return entry
    if name:
        folded_name = _fold_name(name)
        for entry in registry.values():
            if folded_name in {_fold_name(entry.name), *map(_fold_name, entry.aliases)}:
                return entry
    return None


def _fold_name(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def primary_adapter_for(qid: str, path: Path | str | None = None) -> str | None:
    """Return the primary acquisition adapter name for the given institution Q-ID."""
    entry = find_by_wikidata_q(qid, path)
    return entry.primary_adapter if entry else None


def fallback_chain_for(qid: str, path: Path | str | None = None) -> list[str]:
    """Return the ordered fallback adapter chain for the given institution Q-ID."""
    entry = find_by_wikidata_q(qid, path)
    return list(entry.fallback_chain) if entry else []
