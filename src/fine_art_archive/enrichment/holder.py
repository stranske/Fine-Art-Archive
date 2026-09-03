"""Complete holding-institution metadata from a Wikidata work entity.

Host-registry matches are recorded in ``field_provenance.holder.note`` as
``host_registry_key=<key>``. The schema does not currently expose a dedicated
host-key field, and the research-ledger note is the existing schema-valid place
for this enrichment routing detail.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from fine_art_archive import provenance
from fine_art_archive.collect import host_registry

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
NETWORK_ERRORS = (
    urllib.error.URLError,
    http.client.HTTPException,
    TimeoutError,
    socket.timeout,
    OSError,
)
QID_RE = re.compile(r"^Q[1-9][0-9]*$")
ROR_RE = re.compile(r"^0[a-z0-9]{6}[0-9]{2}$", re.IGNORECASE)

# Wikidata P31 (instance-of) classes that mark a candidate as a work of art
# rather than a building/place/museum. Used to gate bare title matches so a
# search for "Rouen Cathedral" cannot return the cathedral building. Not
# exhaustive; a candidate with a P170 creator is also accepted as an artwork.
_ARTWORK_P31 = frozenset(
    {
        "Q3305213",  # painting
        "Q838948",  # work of art
        "Q93184",  # drawing
        "Q11060274",  # print
        "Q18761202",  # watercolor painting
        "Q56676432",  # panel painting
        "Q15709879",  # triptych
        "Q3374376",  # diptych
        "Q22669139",  # fresco
        "Q860861",  # sculpture
        "Q179700",  # statue
        "Q133067",  # tapestry
        "Q1278452",  # engraving
        "Q11835431",  # etching
        "Q4502142",  # visual artwork
        "Q106857709",  # oil painting
        "Q2247624",  # painting series
    }
)

# Wikidata asks for a descriptive User-Agent and rate-limits anonymous bursts.
USER_AGENT = "Fine-Art-Archive/0.1 (https://github.com/stranske/Fine-Art-Archive)"
_THROTTLE_SECONDS = 0.2
_MAX_RETRIES = 4
_last_request_monotonic = 0.0


def _throttle() -> None:
    """Space out Wikidata requests so a bulk pass does not get rate-limited."""
    global _last_request_monotonic
    wait = _THROTTLE_SECONDS - (time.monotonic() - _last_request_monotonic)
    if wait > 0:
        time.sleep(wait)
    _last_request_monotonic = time.monotonic()


def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    """Backoff for a retryable response: honour Retry-After, else exponential."""
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after), 30.0)
    return min(2.0**attempt, 30.0)


@dataclass(frozen=True)
class HolderLookup:
    """Wikidata fields used by the holder-completion pass."""

    work_qid: str
    collection_qid: str | None
    collection_name: str | None
    ror: str | None
    url: str | None
    accession: str | None
    iiif_manifest_url: str | None


class HolderClient(Protocol):
    """Injectable interface used by :func:`complete_holder`."""

    def find_work_qid(
        self, title: str, artist: str, *, creator_qid: str | None = None
    ) -> str | None: ...

    def lookup_holder(self, work_qid: str) -> HolderLookup | None: ...


class WikidataClient:
    """Small timeout-bounded client for the Wikidata Action API."""

    def __init__(self, *, timeout: float = 15) -> None:
        self.timeout = timeout

    def find_work_qid(
        self, title: str, artist: str, *, creator_qid: str | None = None
    ) -> str | None:
        """Best-effort work lookup, verifying P170 when a creator QID is known."""
        title = title.strip()
        artist = artist.strip()
        # Search title-only first (broadest recall) then the combined phrase, so
        # a work indexed only under its title is still found and then verified by
        # creator. Dedupe queries and preserve candidate order.
        queries = [q for q in (title, f"{title} {artist}".strip()) if q]
        seen: dict[str, str] = {}
        candidate_qids: list[str] = []
        for query in dict.fromkeys(queries):
            payload = self._request_json(
                {
                    "action": "wbsearchentities",
                    "format": "json",
                    "language": "en",
                    "limit": "10",
                    "search": query,
                    "type": "item",
                }
            )
            for qid in _search_qids(payload):
                if qid not in seen:
                    seen[qid] = query
                    candidate_qids.append(qid)
        if not candidate_qids:
            return None

        # Gate every candidate: accept only an entity that is actually the
        # artwork. Without this a bare title search returns e.g. the cathedral
        # *building* for "Rouen Cathedral" or the *museum* for "The Louvre",
        # whose year/holder/medium then poison the sidecar.
        entities = self._get_entities(candidate_qids, props="claims")
        if entities is None:
            return None
        for qid in candidate_qids:
            entity = entities.get(qid)
            if not isinstance(entity, dict):
                continue
            creators = _qid_claims(entity, "P170")
            if creator_qid is not None:
                # Known creator: require it to match this candidate.
                if creator_qid in creators:
                    return qid
                continue
            # Creator unknown: accept only a plausible artwork — one with a
            # creator (P170) or an artwork instance-of (P31). Rejects buildings,
            # museums, places and other non-artwork top hits.
            if creators or (set(_qid_claims(entity, "P31")) & _ARTWORK_P31):
                return qid
        return None

    def lookup_holder(self, work_qid: str) -> HolderLookup | None:
        """Fetch P195, P217 and P6108 plus details for the P195 collection."""
        if not _clean_qid(work_qid):
            return None
        work = self._get_entity(work_qid, props="claims")
        if work is None:
            return None

        collection_qid = _first_qid_claim(work, "P195")
        accession = _first_string_claim(work, "P217")
        iiif_manifest_url = _first_string_claim(work, "P6108")
        collection_name = ror = url = None
        if collection_qid is not None:
            collection = self._get_entity(collection_qid, props="claims|labels")
            if collection is not None:
                collection_name = _english_label(collection)
                ror = _entity_ror(collection)
                url = _first_string_claim(collection, "P856")

        return HolderLookup(
            work_qid=work_qid,
            collection_qid=collection_qid,
            collection_name=collection_name,
            ror=ror,
            url=url,
            accession=accession,
            iiif_manifest_url=iiif_manifest_url,
        )

    def _get_entity(self, qid: str, *, props: str) -> dict[str, Any] | None:
        entities = self._get_entities([qid], props=props)
        if entities is None:
            return None
        entity = entities.get(qid)
        return entity if isinstance(entity, dict) and "missing" not in entity else None

    def _get_entities(self, qids: list[str], *, props: str) -> dict[str, dict[str, Any]] | None:
        payload = self._request_json(
            {
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(qids),
                "languages": "en",
                "props": props,
            }
        )
        if payload is None:
            return None
        entities = payload.get("entities")
        return entities if isinstance(entities, dict) else None

    def _request_json(self, params: dict[str, str]) -> dict[str, Any] | None:
        url = f"{WIKIDATA_API}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        for attempt in range(_MAX_RETRIES):
            _throttle()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read())
                return payload if isinstance(payload, dict) else None
            except urllib.error.HTTPError as exc:
                # Retry transient rate-limit / unavailable responses with backoff;
                # anything else is a hard failure that the caller skips.
                if exc.code in (429, 503) and attempt < _MAX_RETRIES - 1:
                    time.sleep(_retry_delay(exc, attempt))
                    continue
                return None
            except NETWORK_ERRORS:
                # No retry: preserves timeout-bounded semantics for the caller.
                return None
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
        return None


def complete_holder(
    sidecar: dict[str, Any], *, client: HolderClient | None = None
) -> dict[str, Any]:
    """Populate holder fields when the sidecar is eligible for holder research.

    Network failure is a skip: the sidecar is returned unchanged and is not
    falsely marked ``not_available``.
    """
    if not provenance.needs_research(sidecar, "holder"):
        return sidecar
    status = _holder_status(sidecar)
    if status == "conflicting":
        return sidecar
    if _has_nonempty_holder(sidecar) and status not in {"not_researched", "unverified"}:
        return sidecar

    active_client = client if client is not None else WikidataClient()
    work_qid = _work_qid(sidecar)
    try:
        if work_qid is None:
            work_qid = active_client.find_work_qid(
                str(sidecar.get("title") or ""),
                _artist_name(sidecar),
                creator_qid=_creator_qid(sidecar),
            )
        if work_qid is None:
            return sidecar
        lookup = active_client.lookup_holder(work_qid)
    except NETWORK_ERRORS:
        return sidecar
    if lookup is None:
        return sidecar

    stable = _stable_identifiers(sidecar)
    stable["wikidata_q"] = lookup.work_qid
    _set_if_present(stable, "museum_accession", lookup.accession)
    _set_if_present(stable, "iiif_manifest_url", lookup.iiif_manifest_url)

    source_ref = f"https://www.wikidata.org/wiki/{lookup.work_qid}"
    if lookup.collection_qid is None:
        sidecar["holder"] = None
        provenance.set(
            sidecar,
            "holder",
            "not_available",
            "wikidata",
            source_ref=source_ref,
            note="Wikidata work entity has no P195 collection claim.",
        )
        return sidecar

    registry_entry = _registry_entry(lookup.collection_qid)
    holder_ror = lookup.ror or (registry_entry.ror if registry_entry else None)
    holder_url = lookup.url or (registry_entry.homepage if registry_entry else None)
    holder_name = lookup.collection_name or (registry_entry.name if registry_entry else None)
    sidecar["holder"] = {
        "name": holder_name,
        "wikidata_q": lookup.collection_qid,
        "ror": holder_ror,
        "url": holder_url,
        "accession": lookup.accession,
    }
    _set_if_present(stable, "museum_institution_ror", holder_ror)
    provenance.set(
        sidecar,
        "holder",
        "available",
        "wikidata",
        source_ref=source_ref,
        note=(
            f"host_registry_key={registry_entry.host_id}" if registry_entry is not None else None
        ),
    )
    return sidecar


def _search_qids(payload: dict[str, Any] | None) -> list[str]:
    if payload is None:
        return []
    results = payload.get("search")
    if not isinstance(results, list):
        return []
    qids: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        qid = _clean_qid(result.get("id"))
        if qid is not None:
            qids.append(qid)
    return qids


def _claim_values(entity: dict[str, Any], property_id: str) -> list[Any]:
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return []
    statements = claims.get(property_id)
    if not isinstance(statements, list):
        return []

    values: list[Any] = []
    for statement in statements:
        if not isinstance(statement, dict) or statement.get("rank") == "deprecated":
            continue
        mainsnak = statement.get("mainsnak")
        if not isinstance(mainsnak, dict):
            continue
        datavalue = mainsnak.get("datavalue")
        if isinstance(datavalue, dict) and "value" in datavalue:
            values.append(datavalue["value"])
    return values


def _qid_claims(entity: dict[str, Any], property_id: str) -> list[str]:
    qids: list[str] = []
    for value in _claim_values(entity, property_id):
        if not isinstance(value, dict):
            continue
        qid = _clean_qid(value.get("id"))
        if qid is not None:
            qids.append(qid)
    return qids


def _first_qid_claim(entity: dict[str, Any], property_id: str) -> str | None:
    qids = _qid_claims(entity, property_id)
    return qids[0] if qids else None


def _first_string_claim(entity: dict[str, Any], property_id: str) -> str | None:
    for value in _claim_values(entity, property_id):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _english_label(entity: dict[str, Any]) -> str | None:
    labels = entity.get("labels")
    if not isinstance(labels, dict):
        return None
    label = labels.get("en")
    if not isinstance(label, dict):
        return None
    value = label.get("value")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _entity_ror(entity: dict[str, Any]) -> str | None:
    # P6782 is the current Wikidata ROR property. P3500 (Ringgold) and P8250
    # (Rhode Island National Register) are retained as guarded legacy inputs
    # from the issue specification; their normal values cannot pass ROR_RE.
    for property_id in ("P6782", "P3500", "P8250"):
        ror = _normalise_ror(_first_string_claim(entity, property_id))
        if ror is not None:
            return ror
    return None


def _normalise_ror(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip().rstrip("/").rsplit("/", 1)[-1]
    return candidate.lower() if ROR_RE.fullmatch(candidate) else None


def _clean_qid(value: Any) -> str | None:
    return value if isinstance(value, str) and QID_RE.fullmatch(value) else None


def _holder_status(sidecar: dict[str, Any]) -> str | None:
    entry = provenance.get(sidecar, "holder")
    status = entry.get("status") if entry is not None else None
    return status if isinstance(status, str) else None


def _has_nonempty_holder(sidecar: dict[str, Any]) -> bool:
    holder = sidecar.get("holder")
    return isinstance(holder, dict) and any(value not in {None, ""} for value in holder.values())


def _work_qid(sidecar: dict[str, Any]) -> str | None:
    stable = sidecar.get("stable_identifiers")
    stable_qid = stable.get("wikidata_q") if isinstance(stable, dict) else None
    for candidate in (sidecar.get("work_qid"), stable_qid, sidecar.get("wikidata_q")):
        qid = _clean_qid(candidate)
        if qid is not None:
            return qid
    return None


def _creator_qid(sidecar: dict[str, Any]) -> str | None:
    artist = sidecar.get("artist")
    artist_qid = canonical_qid = None
    if isinstance(artist, dict):
        artist_qid = artist.get("wikidata_q")
        canonical = artist.get("canonical")
        if isinstance(canonical, dict):
            canonical_qid = canonical.get("wikidata_q")
    for candidate in (sidecar.get("creator_qid"), artist_qid, canonical_qid):
        qid = _clean_qid(candidate)
        if qid is not None:
            return qid
    return None


def _artist_name(sidecar: dict[str, Any]) -> str:
    artist = sidecar.get("artist")
    if isinstance(artist, dict):
        value = artist.get("name")
        return value if isinstance(value, str) else ""
    value = sidecar.get("artist_name")
    return value if isinstance(value, str) else ""


def _stable_identifiers(sidecar: dict[str, Any]) -> dict[str, Any]:
    stable = sidecar.get("stable_identifiers")
    if isinstance(stable, dict):
        return stable
    stable = {}
    sidecar["stable_identifiers"] = stable
    return stable


def _set_if_present(target: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None:
        target[key] = value


def _registry_entry(collection_qid: str) -> host_registry.HostEntry | None:
    try:
        return host_registry.find_by_wikidata_q(collection_qid)
    except (OSError, RuntimeError):
        return None
