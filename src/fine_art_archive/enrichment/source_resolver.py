"""Tiered authoritative-source resolution for incomplete work metadata.

The resolver keeps network access behind small, injectable providers.  A
provider distinguishes a successful lookup with no value from a failed or
inapplicable lookup so transient outages are not recorded as confirmed
absence.
"""

from __future__ import annotations

import html
import importlib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import IntEnum
from typing import Any, Protocol

from fine_art_archive import provenance
from fine_art_archive.collect import host_registry
from fine_art_archive.identity.artist_resolver import fold_name, resolve_artist
from fine_art_archive.identity.getty import resolve_getty_ids
from fine_art_archive.iiif import IIIF_CONTEXT

FIELDS = frozenset({"year", "medium", "category", "dimensions_original", "artist_qid"})
NETWORK_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    socket.timeout,
    OSError,
)

_THROTTLE_SECONDS = 0.2
_MAX_RETRIES = 4
_last_request_monotonic = 0.0


def _throttle() -> None:
    """Space out remote requests so shared APIs (Wikidata) don't rate-limit us."""
    global _last_request_monotonic
    wait = _THROTTLE_SECONDS - (time.monotonic() - _last_request_monotonic)
    if wait > 0:
        time.sleep(wait)
    _last_request_monotonic = time.monotonic()


def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after), 30.0)
    return min(2.0**attempt, 30.0)


QID_RE = re.compile(r"^Q[1-9][0-9]*$")
QID_IN_TEXT_RE = re.compile(r"(?:wikidata\.org/(?:wiki/)?|^)(Q[1-9][0-9]*)\b")
ULAN_RE = re.compile(r"(?:ulan/)?([0-9]{3,})/?$")
YEAR_RE = re.compile(r"(?<!\d)([12][0-9]{3})(?!\d)")
NUMBER_RE = r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)"


class Tier(IntEnum):
    """Source precedence; lower numbers are more authoritative."""

    MUSEUM = 1
    GENERAL = 2
    FILENAME = 3


@dataclass(frozen=True)
class Candidate:
    """One value supplied by a source."""

    value: Any
    source_id: str
    source_ref: str | None
    tier: Tier
    note: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    """Result from one provider.

    ``checked`` is false for an inapplicable source or a failed request.  It is
    true when the source answered, even when ``candidate`` is absent.
    """

    checked: bool
    source_id: str
    candidate: Candidate | None = None


@dataclass(frozen=True)
class Resolution:
    """Final research outcome used by the completion pass."""

    value: Any
    source_id: str | None
    source_ref: str | None
    status: str
    tier: Tier | None
    note: str | None = None

    def as_tuple(self) -> tuple[Any, str | None, str | None]:
        """Return the issue-specified ``(value, source_id, source_ref)`` form."""
        return self.value, self.source_id, self.source_ref


class SourceProvider(Protocol):
    """Injectable tier provider."""

    def resolve(self, sidecar: dict[str, Any], field: str) -> ProviderResult: ...


class JsonClient:
    """Small timeout-bounded JSON transport shared by remote providers."""

    def __init__(self, *, timeout: float = 15) -> None:
        self.timeout = timeout

    def get(self, url: str, *, params: Mapping[str, str] | None = None) -> dict[str, Any] | None:
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Fine-Art-Archive/0.1 (https://github.com/stranske/Fine-Art-Archive)",
            },
        )
        for attempt in range(_MAX_RETRIES):
            _throttle()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read())
                return payload if isinstance(payload, dict) else None
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 503) and attempt < _MAX_RETRIES - 1:
                    time.sleep(_retry_delay(exc, attempt))
                    continue
                return None
            except NETWORK_ERRORS:
                return None
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
        return None


class ArtistQidResolver:
    """Resolve a museum/manifest artist identity, using ULAN as a bridge."""

    def __init__(
        self,
        *,
        wikidata: WikidataProvider | None = None,
        timeout: float = 15,
    ) -> None:
        self.timeout = timeout
        self.wikidata = wikidata

    def resolve(
        self,
        raw: Mapping[str, Any],
        normalized: Mapping[str, Any],
        sidecar: Mapping[str, Any],
    ) -> tuple[str | None, str | None]:
        direct = _artist_qid_from_values(raw, normalized)
        if direct is not None:
            return direct, "museum record artist link supplied a Wikidata QID"

        name = _museum_artist_name(raw, normalized) or _artist_name(sidecar)
        if name:
            local = resolve_artist(name, allow_wikidata=False)
            if local.q is not None and local.confidence >= 0.85:
                return local.q, f"artist alias match ({local.method})"

        ulan = _artist_ulan_from_values(raw, normalized)
        if ulan is None and name:
            try:
                ids = resolve_getty_ids(
                    name=name,
                    vocabulary="ulan",
                    timeout=max(1, round(self.timeout)),
                )
            except NETWORK_ERRORS:
                ids = None
            if ids is not None:
                ulan = _clean_ulan(ids.ulan)

        if self.wikidata is None or name is None:
            return None, None
        qid, method = self.wikidata.find_artist(name, ulan=ulan)
        if qid is None:
            return None, None
        bridge = f" via Getty ULAN {ulan}" if ulan is not None else ""
        return qid, f"{method}{bridge}"


class MuseumProvider:
    """Tier A: fetch the holder's configured museum API by accession."""

    def __init__(
        self,
        *,
        client: JsonClient | None = None,
        artist_resolver: ArtistQidResolver | None = None,
    ) -> None:
        self.client = client or JsonClient()
        self.artist_resolver = artist_resolver or ArtistQidResolver(timeout=self.client.timeout)
        self._accession_cache: dict[tuple[str, str], str | None] = {}

    def resolve(self, sidecar: dict[str, Any], field: str) -> ProviderResult:
        entry = _holder_registry_entry(sidecar)
        if entry is None:
            return ProviderResult(False, "museum")
        source_id = entry.primary_adapter or f"museum:{entry.host_id}"
        accession = self._configured_accession(sidecar, entry) or _museum_accession(sidecar)
        if accession is None:
            return ProviderResult(False, source_id)
        route = _museum_route(entry, accession)
        if route is None:
            return ProviderResult(False, source_id)
        api_url, source_ref, normalizer = route
        payload = self.client.get(api_url)
        if payload is None:
            return ProviderResult(False, source_id)
        try:
            normalized_value = normalizer(payload)
        except (KeyError, TypeError, ValueError):
            normalized_value = {}
        normalized = normalized_value if isinstance(normalized_value, dict) else {}
        candidate = _candidate_from_metadata(
            field,
            payload,
            normalized,
            source_id=source_id,
            source_ref=source_ref,
            tier=Tier.MUSEUM,
            artist_resolver=self.artist_resolver,
            sidecar=sidecar,
        )
        return ProviderResult(True, source_id, candidate)

    def _configured_accession(
        self, sidecar: Mapping[str, Any], entry: host_registry.HostEntry
    ) -> str | None:
        """Read a host-specific Wikidata identifier when the registry declares one."""
        property_id = entry.accession_property
        work_qid = _work_qid(sidecar)
        if property_id is None or property_id == "P217" or work_qid is None:
            return None
        cache_key = (work_qid, property_id)
        if cache_key in self._accession_cache:
            return self._accession_cache[cache_key]
        payload = self.client.get(
            WikidataProvider.API_URL,
            params={
                "action": "wbgetentities",
                "format": "json",
                "ids": work_qid,
                "languages": "en",
                "props": "claims",
            },
        )
        accession = None
        if payload is not None:
            entities = payload.get("entities")
            entity = entities.get(work_qid) if isinstance(entities, Mapping) else None
            if isinstance(entity, Mapping):
                accession = _first_text(*_claim_values(entity, property_id))
        self._accession_cache[cache_key] = accession
        return accession


class WikidataProvider:
    """Tier B Wikidata claims and artist identity lookups."""

    API_URL = "https://www.wikidata.org/w/api.php"

    def __init__(self, *, client: JsonClient | None = None) -> None:
        self.client = client or JsonClient()

    def resolve(self, sidecar: dict[str, Any], field: str) -> ProviderResult:
        qid = _work_qid(sidecar)
        if qid is None:
            return ProviderResult(False, "wikidata")
        entity = self._entity(qid)
        if entity is None:
            return ProviderResult(False, "wikidata")
        value = self._field_from_entity(entity, field)
        candidate = (
            Candidate(
                value,
                "wikidata",
                f"https://www.wikidata.org/wiki/{qid}",
                Tier.GENERAL,
            )
            if value is not None
            else None
        )
        return ProviderResult(True, "wikidata", candidate)

    def find_artist(self, name: str, *, ulan: str | None) -> tuple[str | None, str | None]:
        """Find a human artist, preferring an exact Getty ULAN claim."""
        search = self.client.get(
            self.API_URL,
            params={
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "limit": "10",
                "search": name,
                "type": "item",
            },
        )
        if search is None:
            return None, None
        hits = search.get("search")
        if not isinstance(hits, list):
            return None, None
        qids = [
            qid
            for hit in hits
            if isinstance(hit, dict) and (qid := _clean_qid(hit.get("id"))) is not None
        ]
        if not qids:
            return None, None
        entities = self._entities(qids)
        if entities is None:
            return None, None

        if ulan is not None:
            for qid in qids:
                entity = entities.get(qid)
                if isinstance(entity, dict) and ulan in {
                    _clean_ulan(value)
                    for value in _claim_values(entity, "P245")
                    if _clean_ulan(value) is not None
                }:
                    return qid, "Wikidata P245 match"

        folded_name = fold_name(name)
        best: tuple[float, str] | None = None
        for qid in qids:
            entity = entities.get(qid)
            if not isinstance(entity, dict) or "Q5" not in _qid_claims(entity, "P31"):
                continue
            for candidate_name in _entity_names(entity):
                score = SequenceMatcher(None, folded_name, fold_name(candidate_name)).ratio()
                if best is None or score > best[0]:
                    best = score, qid
        if best is not None and best[0] >= 0.88:
            return best[1], f"Wikidata alias/fuzzy match ({best[0]:.2f})"
        return None, None

    def _field_from_entity(self, entity: Mapping[str, Any], field: str) -> Any:
        if field == "year":
            return _year_from_claims(entity)
        if field == "artist_qid":
            return _first(_qid_claims(entity, "P170"))
        if field == "dimensions_original":
            return _dimensions_from_claims(entity)
        if field == "medium":
            return self._labels_for_claims(entity, "P186")
        if field == "category":
            labels = self._labels_for_claims(entity, "P136")
            return _category_from_text(labels)
        return None

    def _labels_for_claims(self, entity: Mapping[str, Any], property_id: str) -> str | None:
        qids = _qid_claims(entity, property_id)
        if not qids:
            strings = [
                value.strip()
                for value in _claim_values(entity, property_id)
                if isinstance(value, str) and value.strip()
            ]
            return ", ".join(strings) if strings else None
        entities = self._entities(qids)
        if entities is None:
            return None
        labels = [
            label
            for qid in qids
            if isinstance((item := entities.get(qid)), dict)
            and (label := _english_label(item)) is not None
        ]
        return ", ".join(dict.fromkeys(labels)) if labels else None

    def _entity(self, qid: str) -> dict[str, Any] | None:
        entities = self._entities([qid])
        if entities is None:
            return None
        entity = entities.get(qid)
        return entity if isinstance(entity, dict) and "missing" not in entity else None

    def _entities(self, qids: Sequence[str]) -> dict[str, Any] | None:
        payload = self.client.get(
            self.API_URL,
            params={
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(qids),
                "languages": "en",
                "props": "claims|labels|aliases",
            },
        )
        if payload is None:
            return None
        entities = payload.get("entities")
        return entities if isinstance(entities, dict) else None


class IiifProvider:
    """Tier B IIIF Presentation metadata reader."""

    def __init__(
        self,
        *,
        client: JsonClient | None = None,
        artist_resolver: ArtistQidResolver | None = None,
    ) -> None:
        self.client = client or JsonClient()
        self.artist_resolver = artist_resolver or ArtistQidResolver(timeout=self.client.timeout)

    def resolve(self, sidecar: dict[str, Any], field: str) -> ProviderResult:
        manifest_url = _iiif_manifest_url(sidecar)
        if manifest_url is None:
            return ProviderResult(False, "iiif")
        manifest = self.client.get(manifest_url)
        if manifest is None:
            return ProviderResult(False, "iiif")
        metadata = _iiif_metadata(manifest)
        candidate = _candidate_from_metadata(
            field,
            manifest,
            metadata,
            source_id="iiif",
            source_ref=manifest_url,
            tier=Tier.GENERAL,
            artist_resolver=self.artist_resolver,
            sidecar=sidecar,
        )
        return ProviderResult(True, "iiif", candidate)


class EuropeanaProvider:
    """Tier B Europeana search, enabled when an API key is configured."""

    API_URL = "https://api.europeana.eu/record/v2/search.json"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: JsonClient | None = None,
        artist_resolver: ArtistQidResolver | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("EUROPEANA_API_KEY")
        self.client = client or JsonClient()
        self.artist_resolver = artist_resolver or ArtistQidResolver(timeout=self.client.timeout)

    def resolve(self, sidecar: dict[str, Any], field: str) -> ProviderResult:
        title = _clean_text(sidecar.get("title"))
        if not self.api_key or title is None:
            return ProviderResult(False, "europeana")
        payload = self.client.get(
            self.API_URL,
            params={
                "wskey": self.api_key,
                "query": " ".join(filter(None, (title, _artist_name(sidecar)))),
                "rows": "5",
                "profile": "rich",
            },
        )
        if payload is None:
            return ProviderResult(False, "europeana")
        items = payload.get("items")
        record = (
            items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        )
        source_ref = _clean_text(record.get("guid") or record.get("link"))
        candidate = _candidate_from_metadata(
            field,
            record,
            _europeana_metadata(record),
            source_id="europeana",
            source_ref=source_ref,
            tier=Tier.GENERAL,
            artist_resolver=self.artist_resolver,
            sidecar=sidecar,
        )
        return ProviderResult(True, "europeana", candidate)


class CommonsSdcProvider:
    """Tier B Wikimedia Commons Structured Data (MediaInfo) claims."""

    API_URL = "https://commons.wikimedia.org/w/api.php"

    def __init__(
        self,
        *,
        client: JsonClient | None = None,
        wikidata: WikidataProvider | None = None,
    ) -> None:
        self.client = client or JsonClient()
        self.wikidata = wikidata or WikidataProvider(client=self.client)

    def resolve(self, sidecar: dict[str, Any], field: str) -> ProviderResult:
        filename = _commons_file(sidecar)
        if filename is None:
            return ProviderResult(False, "wikimedia_commons_sdc")
        title = filename if filename.lower().startswith("file:") else f"File:{filename}"
        payload = self.client.get(
            self.API_URL,
            params={
                "action": "wbgetentities",
                "format": "json",
                "sites": "commonswiki",
                "titles": title,
                "languages": "en",
                "props": "claims|labels",
            },
        )
        if payload is None:
            return ProviderResult(False, "wikimedia_commons_sdc")
        entities = payload.get("entities")
        entity = (
            next((item for item in entities.values() if isinstance(item, dict)), None)
            if isinstance(entities, dict)
            else None
        )
        value = self.wikidata._field_from_entity(entity, field) if entity is not None else None
        candidate = (
            Candidate(
                value,
                "wikimedia_commons_sdc",
                f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                Tier.GENERAL,
            )
            if value is not None
            else None
        )
        return ProviderResult(True, "wikimedia_commons_sdc", candidate)


class SourceResolver:
    """Resolve fields in strict Tier A -> Tier B -> Tier C order."""

    def __init__(
        self,
        *,
        museum: SourceProvider | None = None,
        wikidata: SourceProvider | None = None,
        iiif: SourceProvider | None = None,
        europeana: SourceProvider | None = None,
        commons: SourceProvider | None = None,
        timeout: float = 15,
    ) -> None:
        client = JsonClient(timeout=timeout)
        wikidata_provider = WikidataProvider(client=client)
        identity = ArtistQidResolver(wikidata=wikidata_provider, timeout=timeout)
        self.tier_a = (museum or MuseumProvider(client=client, artist_resolver=identity),)
        self.tier_b = (
            wikidata or wikidata_provider,
            iiif or IiifProvider(client=client, artist_resolver=identity),
            europeana or EuropeanaProvider(client=client, artist_resolver=identity),
            commons or CommonsSdcProvider(client=client, wikidata=wikidata_provider),
        )

    def resolve(self, sidecar: dict[str, Any], field: str) -> tuple[Any, str | None, str | None]:
        """Return the issue-specified tuple for ``field``."""
        return self.research(sidecar, field).as_tuple()

    def research(self, sidecar: dict[str, Any], field: str) -> Resolution:
        """Return a provenance-aware resolution without mutating ``sidecar``."""
        if field not in FIELDS:
            raise ValueError(f"unsupported metadata field: {field}")
        current_entry = provenance.get(sidecar, field)
        current_status = current_entry.get("status") if current_entry else None
        existing = get_field_value(sidecar, field)
        if current_status == "available":
            return Resolution(
                existing,
                _optional_text(current_entry.get("source")) if current_entry else None,
                _optional_text(current_entry.get("source_ref")) if current_entry else None,
                "available",
                None,
                _optional_text(current_entry.get("note")) if current_entry else None,
            )

        checked_sources: list[str] = []
        for provider in (*self.tier_a, *self.tier_b):
            try:
                result = provider.resolve(sidecar, field)
            except NETWORK_ERRORS:
                continue
            if result.checked:
                checked_sources.append(result.source_id)
            if result.candidate is not None:
                return _authoritative_resolution(existing, result.candidate)

        if existing is not None:
            source = (
                _optional_text(current_entry.get("source")) if current_entry is not None else None
            ) or "filename_parse"
            source_ref = (
                _optional_text(current_entry.get("source_ref"))
                if current_entry is not None
                else None
            )
            return Resolution(
                existing,
                source,
                source_ref,
                "unverified",
                Tier.FILENAME,
                _optional_text(current_entry.get("note")) if current_entry else None,
            )

        if checked_sources:
            checked = ", ".join(dict.fromkeys(checked_sources))
            return Resolution(
                None,
                "source_resolver",
                None,
                "not_available",
                None,
                f"Checked applicable sources without finding the field: {checked}.",
            )
        return Resolution(None, None, None, "not_researched", None)


def resolve_field(
    sidecar: dict[str, Any],
    field: str,
    *,
    resolver: SourceResolver | None = None,
) -> tuple[Any, str | None, str | None]:
    """Convenience wrapper returning ``(value, source_id, source_ref)``."""
    return (resolver or SourceResolver()).resolve(sidecar, field)


def apply_resolution(
    sidecar: dict[str, Any],
    field: str,
    resolution: Resolution,
    *,
    checked_at: str | None = None,
) -> bool:
    """Apply ``resolution`` and provenance, returning whether data changed."""
    if field not in FIELDS:
        raise ValueError(f"unsupported metadata field: {field}")
    if resolution.status == "not_researched":
        return False

    before_value = get_field_value(sidecar, field)
    before_provenance = provenance.get(sidecar, field)
    if resolution.status in {"available", "conflicting", "not_available"}:
        set_field_value(sidecar, field, resolution.value)
    if (
        resolution.status == "unverified"
        and _values_equal(field, before_value, resolution.value)
        and before_provenance is not None
        and before_provenance.get("status") == "unverified"
        and before_provenance.get("source") == resolution.source_id
        and before_provenance.get("source_ref") == resolution.source_ref
        and before_provenance.get("note") == resolution.note
    ):
        return False
    provenance.set(
        sidecar,
        field,
        resolution.status,
        resolution.source_id,
        source_ref=resolution.source_ref,
        checked_at=checked_at,
        note=resolution.note,
    )
    return not _values_equal(field, before_value, get_field_value(sidecar, field)) or (
        provenance.get(sidecar, field) != before_provenance
    )


def get_field_value(sidecar: Mapping[str, Any], field: str) -> Any:
    """Read a resolver field, including nested ``artist.wikidata_q``."""
    if field == "artist_qid":
        artist = sidecar.get("artist")
        return artist.get("wikidata_q") if isinstance(artist, Mapping) else None
    return sidecar.get(field)


def set_field_value(sidecar: dict[str, Any], field: str, value: Any) -> None:
    """Write a resolver field, including nested ``artist.wikidata_q``."""
    if field == "artist_qid":
        artist = sidecar.get("artist")
        if not isinstance(artist, dict):
            raise ValueError("artist must be an object")
        artist["wikidata_q"] = value
        return
    sidecar[field] = value


def parse_dimensions(value: Any) -> dict[str, float | str | None] | None:
    """Parse common museum dimension strings into centimetres."""
    if isinstance(value, Mapping):
        h = _number(value.get("h_cm") or value.get("height"))
        w = _number(value.get("w_cm") or value.get("width"))
        if h is None and w is None:
            raw_value = value.get("raw")
            return parse_dimensions(raw_value)
        parsed: dict[str, float | str | None] = {"h_cm": h, "w_cm": w}
        raw = _clean_text(value.get("raw"))
        if raw is not None:
            parsed["raw"] = raw
        return parsed
    text = _clean_text(value)
    if text is None:
        return None
    lowered = html.unescape(re.sub(r"<[^>]+>", " ", text)).lower()
    unit_factor = _unit_factor(lowered)

    height_match = re.search(
        rf"(?:height|h)\s*[:=]?\s*({NUMBER_RE})\s*(mm|cm|m|in(?:ches?)?|″|\")?",
        lowered,
    )
    width_match = re.search(
        rf"(?:width|w)\s*[:=]?\s*({NUMBER_RE})\s*(mm|cm|m|in(?:ches?)?|″|\")?",
        lowered,
    )
    if height_match or width_match:
        h = _measurement_match(height_match, unit_factor)
        w = _measurement_match(width_match, unit_factor)
    else:
        pair = re.search(
            rf"({NUMBER_RE})\s*(?:mm|cm|m|in(?:ches?)?|″|\")?\s*"
            rf"(?:[x×])\s*({NUMBER_RE})\s*(mm|cm|m|in(?:ches?)?|″|\")?",
            lowered,
        )
        if pair is None:
            return None
        factor = _unit_factor(pair.group(3) or lowered)
        h = _number(pair.group(1))
        w = _number(pair.group(2))
        h = h * factor if h is not None else None
        w = w * factor if w is not None else None
    if h is None and w is None:
        return None
    return {
        "h_cm": _round_optional_dimension(h),
        "w_cm": _round_optional_dimension(w),
        "raw": text,
    }


def _authoritative_resolution(existing: Any, candidate: Candidate) -> Resolution:
    if existing is not None and not _values_equal(
        _field_for_value(candidate.value), existing, candidate.value
    ):
        loser = json.dumps(existing, ensure_ascii=False, sort_keys=True)
        note = f"Higher-tier source replaced lower-tier existing value {loser}."
        if candidate.note:
            note = f"{note} {candidate.note}"
        return Resolution(
            candidate.value,
            candidate.source_id,
            candidate.source_ref,
            "conflicting",
            candidate.tier,
            note,
        )
    return Resolution(
        candidate.value,
        candidate.source_id,
        candidate.source_ref,
        "available",
        candidate.tier,
        candidate.note,
    )


def _field_for_value(value: Any) -> str:
    return "dimensions_original" if isinstance(value, Mapping) else "scalar"


def _values_equal(field: str, left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is right
    if field == "dimensions_original" or (isinstance(left, Mapping) and isinstance(right, Mapping)):
        left_dimensions = parse_dimensions(left)
        right_dimensions = parse_dimensions(right)
        if left_dimensions is None or right_dimensions is None:
            return left == right
        return all(
            _numbers_close(left_dimensions.get(key), right_dimensions.get(key))
            for key in ("h_cm", "w_cm")
        )
    return str(left).strip().casefold() == str(right).strip().casefold()


def _numbers_close(left: Any, right: Any) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return left_number is right_number
    return abs(left_number - right_number) <= 0.01


def _candidate_from_metadata(
    field: str,
    raw: Mapping[str, Any],
    normalized: Mapping[str, Any],
    *,
    source_id: str,
    source_ref: str | None,
    tier: Tier,
    artist_resolver: ArtistQidResolver,
    sidecar: Mapping[str, Any],
) -> Candidate | None:
    note = None
    value: Any
    if field == "year":
        value = _year_from_metadata(raw, normalized)
    elif field == "medium":
        value = _first_text(
            normalized.get("medium"),
            raw.get("medium"),
            raw.get("dcFormat"),
            raw.get("materials"),
            raw.get("technique"),
        )
    elif field == "category":
        value = _category_from_text(
            _first_text(
                normalized.get("category"),
                raw.get("classification_title"),
                raw.get("classification"),
                raw.get("objectName"),
                raw.get("type"),
                raw.get("dcType"),
                normalized.get("medium"),
            )
        )
    elif field == "dimensions_original":
        value = parse_dimensions(
            normalized.get("dimensions_original")
            or normalized.get("dimensions_raw")
            or raw.get("dimensions")
            or raw.get("measurements")
            or raw.get("dimensions_original")
        )
    elif field == "artist_qid":
        value, note = artist_resolver.resolve(raw, normalized, sidecar)
    else:
        value = None
    if value is None:
        return None
    return Candidate(value, source_id, source_ref, tier, note)


def _year_from_metadata(raw: Mapping[str, Any], normalized: Mapping[str, Any]) -> str | None:
    value = _first_text(
        normalized.get("year"),
        normalized.get("year_min"),
        raw.get("date_display"),
        raw.get("objectDate"),
        raw.get("creation_date"),
        raw.get("dcDate"),
        raw.get("date"),
    )
    if value is None:
        return None
    match = YEAR_RE.search(value)
    return match.group(1) if match else value


MetadataNormalizer = Callable[[dict[str, Any]], dict[str, Any]]


def _museum_route(
    entry: host_registry.HostEntry, accession: str
) -> tuple[str, str, MetadataNormalizer] | None:
    """Resolve an adapter, declarative JSON API, or IIIF manifest route."""
    adapter = entry.primary_adapter
    if adapter is not None and re.fullmatch(r"[a-z][a-z0-9_]*", adapter):
        try:
            module = importlib.import_module(f"fine_art_archive.collect.sources.{adapter}")
        except ImportError:
            module = None
        normalizer = getattr(module, "normalize_metadata", None)
        if module is not None and callable(normalizer):
            # Existing adapters expose a one-argument stable-handle dataclass
            # with metadata_api_url/web_url properties.
            for candidate_type in vars(module).values():
                if (
                    not isinstance(candidate_type, type)
                    or candidate_type.__module__ != module.__name__
                ):
                    continue
                try:
                    handle = candidate_type(accession)
                except (TypeError, ValueError):
                    continue
                api_url = _absolute_http_url(getattr(handle, "metadata_api_url", None))
                if api_url is None:
                    continue
                source_ref = (
                    _absolute_http_url(getattr(handle, "web_url", None))
                    or entry.homepage
                    or api_url
                )
                return api_url, source_ref, normalizer

    if entry.api_base is not None:
        api_url = _declarative_url(entry.api_base, accession)
        if api_url is not None:
            return (
                api_url,
                api_url,
                lambda payload: _declarative_metadata(payload, entry.field_map),
            )

    if entry.iiif_pattern is not None:
        manifest_url = _declarative_url(entry.iiif_pattern, accession, append=False)
        if manifest_url is not None:
            return manifest_url, manifest_url, _iiif_metadata
    return None


def _declarative_url(pattern: str, accession: str, *, append: bool = True) -> str | None:
    encoded_accession = urllib.parse.quote(accession, safe="")
    try:
        if "{accession}" in pattern:
            candidate = pattern.format(accession=encoded_accession)
        elif append:
            candidate = f"{pattern.rstrip('/')}/{encoded_accession}"
        else:
            return None
    except (KeyError, ValueError):
        return None
    return _absolute_http_url(candidate)


def _declarative_metadata(
    payload: Mapping[str, Any], field_map: Mapping[str, Sequence[str]]
) -> dict[str, Any]:
    """Project common museum JSON shapes without institution-specific code."""
    aliases: dict[str, tuple[str, ...]] = {
        "year": (
            "date_display",
            "objectDate",
            "creation_date",
            "productionDates",
            "_primaryDate",
            "dated",
            "date",
            "year",
        ),
        "medium": (
            "materialsAndTechniques",
            "medium_display",
            "medium",
            "materials",
            "technique",
            "techniques",
        ),
        "category": (
            "classification_title",
            "classification",
            "objectType",
            "objectName",
            "type",
        ),
        "dimensions_raw": (
            "dimensions_display",
            "dimensions",
            "measurements",
            "physicalDescription",
        ),
        "artist_name": (
            "artistDisplayName",
            "artist_display",
            "_primaryMaker",
            "principalOrFirstMaker",
            "creator",
            "creators",
            "maker",
        ),
    }
    normalized: dict[str, Any] = {}
    for field_name, defaults in aliases.items():
        configured = field_map.get(field_name)
        value = _declarative_text(payload, configured or defaults)
        if value is not None:
            normalized[field_name] = value
    return normalized


def _declarative_text(payload: Mapping[str, Any], aliases: Sequence[str]) -> str | None:
    values = _walk_values(payload)
    for alias in aliases:
        folded_alias = fold_name(alias)
        for key, value in values:
            folded_key = fold_name(key)
            if (
                folded_key == folded_alias
                or folded_key.endswith(f" {folded_alias}")
                or f" {folded_alias} " in f" {folded_key} "
            ):
                text = _clean_text(value)
                if text is not None:
                    return text
    return None


def _holder_registry_entry(sidecar: Mapping[str, Any]) -> host_registry.HostEntry | None:
    holder = sidecar.get("holder")
    qid = _clean_qid(holder.get("wikidata_q")) if isinstance(holder, Mapping) else None
    name = _clean_text(holder.get("name")) if isinstance(holder, Mapping) else None
    ror = _clean_text(holder.get("ror")) if isinstance(holder, Mapping) else None
    try:
        direct = host_registry.find_by_holder(name=name, wikidata_q=qid, ror=ror)
        if direct is not None:
            return direct
        entry = provenance.get(dict(sidecar), "holder")
        note = entry.get("note") if entry is not None else None
        if isinstance(note, str):
            match = re.search(r"(?:^|\s)host_registry_key=([a-z0-9_]+)", note)
            if match:
                return host_registry.load_registry().get(match.group(1))
    except (OSError, RuntimeError):
        return None
    return None


def _museum_accession(sidecar: Mapping[str, Any]) -> str | None:
    holder = sidecar.get("holder")
    holder_accession = holder.get("accession") if isinstance(holder, Mapping) else None
    stable = sidecar.get("stable_identifiers")
    stable_accession = stable.get("museum_accession") if isinstance(stable, Mapping) else None
    return _clean_text(holder_accession) or _clean_text(stable_accession)


def _work_qid(sidecar: Mapping[str, Any]) -> str | None:
    stable = sidecar.get("stable_identifiers")
    stable_qid = stable.get("wikidata_q") if isinstance(stable, Mapping) else None
    return _clean_qid(stable_qid) or _clean_qid(sidecar.get("work_qid"))


def _iiif_manifest_url(sidecar: Mapping[str, Any]) -> str | None:
    stable = sidecar.get("stable_identifiers")
    if not isinstance(stable, Mapping):
        return None
    return _absolute_http_url(stable.get("iiif_manifest_url"))


def _commons_file(sidecar: Mapping[str, Any]) -> str | None:
    stable = sidecar.get("stable_identifiers")
    return _clean_text(stable.get("commons_file")) if isinstance(stable, Mapping) else None


def _iiif_metadata(manifest: Mapping[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    items = manifest.get("metadata")
    if not isinstance(items, list):
        return output
    for item in items:
        if not isinstance(item, Mapping):
            continue
        label = _language_value(item.get("label"))
        value = _language_value(item.get("value"))
        if label and value:
            output[_iiif_key(label)] = value
    context = manifest.get("@context")
    if context == IIIF_CONTEXT:
        output.setdefault("iiif_version", "3")
    return output


def _iiif_key(label: str) -> str:
    folded = fold_name(label)
    aliases = {
        "date": "year",
        "creation date": "year",
        "object date": "year",
        "material": "medium",
        "materials": "medium",
        "technique": "medium",
        "classification": "category",
        "type": "category",
        "measurements": "dimensions_raw",
        "dimensions": "dimensions_raw",
        "creator": "artist_name",
        "maker": "artist_name",
        "artist": "artist_name",
    }
    return aliases.get(folded, folded.replace(" ", "_"))


def _language_value(value: Any) -> str | None:
    if isinstance(value, str):
        return _clean_text(html.unescape(re.sub(r"<[^>]+>", " ", value)))
    if isinstance(value, Mapping):
        for key in ("en", "none", "@value", "value"):
            if key in value and (text := _language_value(value[key])) is not None:
                return text
        for nested in value.values():
            if (text := _language_value(nested)) is not None:
                return text
    if isinstance(value, list):
        texts = [text for item in value if (text := _language_value(item)) is not None]
        return ", ".join(texts) if texts else None
    return None


def _europeana_metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "year": _first_text(record.get("year"), record.get("dcDate")),
        "medium": _first_text(record.get("dcFormat"), record.get("edmConceptLabel")),
        "category": _first_text(record.get("dcType"), record.get("type")),
        "dimensions_raw": _first_text(record.get("dimensions"), record.get("dctermsExtent")),
        "artist_name": _first_text(record.get("dcCreator"), record.get("edmAgentLabel")),
    }


def _claim_values(entity: Mapping[str, Any], property_id: str) -> list[Any]:
    claims = entity.get("claims")
    statements = claims.get(property_id) if isinstance(claims, Mapping) else None
    if not isinstance(statements, list):
        return []
    values: list[Any] = []
    for statement in statements:
        if not isinstance(statement, Mapping) or statement.get("rank") == "deprecated":
            continue
        mainsnak = statement.get("mainsnak")
        datavalue = mainsnak.get("datavalue") if isinstance(mainsnak, Mapping) else None
        if isinstance(datavalue, Mapping) and "value" in datavalue:
            values.append(datavalue["value"])
    return values


def _qid_claims(entity: Mapping[str, Any], property_id: str) -> list[str]:
    return [
        qid
        for value in _claim_values(entity, property_id)
        if isinstance(value, Mapping) and (qid := _clean_qid(value.get("id"))) is not None
    ]


def _year_from_claims(entity: Mapping[str, Any]) -> str | None:
    for value in _claim_values(entity, "P571"):
        time = value.get("time") if isinstance(value, Mapping) else value
        if isinstance(time, str) and (match := re.search(r"[+-]([0-9]{4,})", time)):
            return match.group(1)
    return None


def _dimensions_from_claims(entity: Mapping[str, Any]) -> dict[str, float] | None:
    height = _quantity_cm(_first(_claim_values(entity, "P2048")))
    width = _quantity_cm(_first(_claim_values(entity, "P2049")))
    if height is None and width is None:
        return None
    result: dict[str, float] = {}
    if height is not None:
        result["h_cm"] = _round_dimension(height)
    if width is not None:
        result["w_cm"] = _round_dimension(width)
    return result


def _quantity_cm(value: Any) -> float | None:
    if not isinstance(value, Mapping):
        return None
    amount = _number(value.get("amount"))
    if amount is None:
        return None
    unit = str(value.get("unit") or "")
    unit_qid = unit.rstrip("/").rsplit("/", 1)[-1]
    factors = {
        "1": 1.0,
        "Q174728": 1.0,  # centimetre
        "Q11573": 100.0,  # metre
        "Q828224": 0.1,  # millimetre
        "Q218593": 2.54,  # inch
    }
    factor = factors.get(unit_qid)
    return amount * factor if factor is not None else None


def _english_label(entity: Mapping[str, Any]) -> str | None:
    labels = entity.get("labels")
    label = labels.get("en") if isinstance(labels, Mapping) else None
    return _clean_text(label.get("value")) if isinstance(label, Mapping) else None


def _entity_names(entity: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    if (label := _english_label(entity)) is not None:
        names.append(label)
    aliases = entity.get("aliases")
    english_aliases = aliases.get("en") if isinstance(aliases, Mapping) else None
    if isinstance(english_aliases, list):
        names.extend(
            text
            for alias in english_aliases
            if isinstance(alias, Mapping) and (text := _clean_text(alias.get("value"))) is not None
        )
    return names


def _artist_qid_from_values(raw: Mapping[str, Any], normalized: Mapping[str, Any]) -> str | None:
    for key, value in _walk_values(raw, normalized):
        folded_key = fold_name(key)
        if not any(token in folded_key for token in ("artist", "creator", "maker")):
            continue
        if (qid := _clean_qid(value)) is not None:
            return qid
        if isinstance(value, str) and (match := QID_IN_TEXT_RE.search(value.strip())):
            return match.group(1)
    return None


def _artist_ulan_from_values(raw: Mapping[str, Any], normalized: Mapping[str, Any]) -> str | None:
    for key, value in _walk_values(raw, normalized):
        folded_key = fold_name(key)
        if "ulan" not in folded_key and not (
            any(token in folded_key for token in ("artist", "creator", "maker"))
            and isinstance(value, str)
            and "vocab.getty.edu/ulan/" in value
        ):
            continue
        if (ulan := _clean_ulan(value)) is not None:
            return ulan
    return None


def _walk_values(*values: Mapping[str, Any]) -> list[tuple[str, Any]]:
    output: list[tuple[str, Any]] = []

    def visit(key: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                visit(f"{key} {nested_key}", nested_value)
        elif isinstance(value, list):
            for nested_value in value:
                visit(key, nested_value)
        else:
            output.append((key, value))

    for mapping in values:
        for key, value in mapping.items():
            visit(str(key), value)
    return output


def _museum_artist_name(raw: Mapping[str, Any], normalized: Mapping[str, Any]) -> str | None:
    direct = _first_text(
        normalized.get("artist_name"),
        normalized.get("artist"),
        raw.get("artistDisplayName"),
        raw.get("artist_title"),
        raw.get("artist_display"),
        raw.get("principalOrFirstMaker"),
        raw.get("dcCreator"),
    )
    if direct is not None:
        return direct
    creators = raw.get("creators")
    if isinstance(creators, list) and creators and isinstance(creators[0], Mapping):
        return _first_text(
            creators[0].get("description"),
            creators[0].get("name"),
        )
    return None


def _artist_name(sidecar: Mapping[str, Any]) -> str | None:
    artist = sidecar.get("artist")
    return _clean_text(artist.get("name")) if isinstance(artist, Mapping) else None


def _category_from_text(value: Any) -> str | None:
    text = _first_text(value)
    if text is None:
        return None
    folded = fold_name(text)
    mappings = (
        ("stained glass", "stained_glass"),
        ("illuminated manuscript", "illuminated_manuscript"),
        ("architectural sculpture", "architectural_sculpture"),
        ("other", "other"),
        ("photograph", "photograph"),
        ("photography", "photograph"),
        ("painting", "painting"),
        ("drawing", "drawing"),
        ("print", "print"),
        ("etching", "print"),
        ("lithograph", "print"),
        ("sculpture", "sculpture"),
        ("fresco", "fresco"),
        ("mural", "mural"),
        ("tapestry", "tapestry"),
        ("altarpiece", "altarpiece"),
        ("icon", "icon"),
        ("architecture", "architecture"),
        ("mosaic", "mosaic"),
        ("monument", "monument"),
    )
    for token, category in mappings:
        if token in folded:
            return category
    return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, list):
            texts = [text for item in value if (text := _clean_text(item)) is not None]
            if texts:
                return ", ".join(texts)
        elif (text := _clean_text(value)) is not None:
            return text
    return None


def _clean_text(value: Any) -> str | None:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    return None


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _clean_qid(value: Any) -> str | None:
    if isinstance(value, str):
        candidate = value.strip().rstrip("/").rsplit("/", 1)[-1]
        return candidate if QID_RE.fullmatch(candidate) else None
    return None


def _clean_ulan(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = ULAN_RE.search(value.strip())
    return match.group(1) if match else None


def _absolute_http_url(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    parsed = urllib.parse.urlparse(text)
    return text if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _first(values: Sequence[Any]) -> Any:
    return values[0] if values else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ".").lstrip("+"))
        except ValueError:
            return None
    return None


def _unit_factor(value: str) -> float:
    folded = value.strip().lower()
    if re.search(r"(?:^|\s)mm(?:\s|$)", folded):
        return 0.1
    if re.search(r"(?:^|\s)(?:in|inch|inches)(?:\s|$)|[″\"]", folded):
        return 2.54
    if re.search(r"(?:^|\s)m(?:\s|$)", folded):
        return 100.0
    return 1.0


def _measurement_match(match: re.Match[str] | None, fallback: float) -> float | None:
    if match is None:
        return None
    number = _number(match.group(1))
    if number is None:
        return None
    unit = match.group(2) if match.lastindex and match.lastindex >= 2 else None
    return number * (_unit_factor(unit) if unit else fallback)


def _round_dimension(value: float | None) -> float:
    if value is None:
        raise ValueError("cannot round an absent dimension")
    return round(value, 4)


def _round_optional_dimension(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None
