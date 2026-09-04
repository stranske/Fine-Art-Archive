"""Canonical Wikidata P31 (instance-of) artwork-class allowlist.

Acquisition and known-works SPARQL queries must share one verified set.
Hand-typed Q-ID tables have previously admitted non-artwork entities
(see Fine-Art-Archive#411 / the CURATED_ALIASES incident in #373).

Every member must be ``Q838948`` (work of art) itself or a subclass of it
via Wikidata ``P279*``.  Hermetic tests cover the offline regression shape;
``audit_allowed_p31_against_wikidata`` is the opt-in live check.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

# Root of the artwork class hierarchy on Wikidata.
WORK_OF_ART_QID = "Q838948"

# Verified artwork-class QIDs for acquisition / known-works SPARQL VALUES.
# Labels confirmed against live Wikidata during the 2026-08-03 audit (#411).
# Intentionally excludes prior junk entries Q11086742 / Q1167694 / Q57276.
ALLOWED_P31: frozenset[str] = frozenset(
    {
        "Q3305213",  # painting
        "Q4502142",  # visual artwork
        "Q15727816",  # painting series
        "Q860861",  # sculpture
        "Q15711026",  # altarpiece
        "Q11060274",  # print
        "Q18761202",  # watercolor painting
        WORK_OF_ART_QID,  # work of art
        "Q179700",  # statue
        "Q93184",  # drawing
    }
)

# ---------------------------------------------------------------------------
# Group classes: artwork classes that denote a SET, not a single object.
#
# `ALLOWED_P31` answers "is this an artwork class?". That is the wrong question
# at the point where a Q-ID is written into `stable_identifiers.wikidata_q`,
# which must denote ONE work and be unique across the archive. A painting
# series is unambiguously an artwork class and unambiguously not a single work,
# so it passed a gate that was never asking the right thing — which is how 132
# work Q-IDs were historically shared across sidecars. Current migrations must
# classify the entity from Wikidata evidence rather than infer "series" from a
# collision count alone.
#
# Note `Q15727816` (painting series) is a member of ALLOWED_P31 above. That is
# correct and deliberate: a series IS an artwork class, and known-works queries
# should still find it. It simply must not be recorded as a single work's
# identity — it belongs in `stable_identifiers.part_of_q` instead.
GROUP_P31: frozenset[str] = frozenset(
    {
        "Q15727816",  # painting series
        "Q15709879",  # artwork series ("thematic group of an artist's works")
        "Q19960510",  # series of prints ("works of art produced using a print technique")
        "Q18573970",  # artwork series
        "Q17489659",  # group of works of art
    }
)

# What may be written to `stable_identifiers.wikidata_q`.
SINGLE_WORK_P31: frozenset[str] = ALLOWED_P31 - GROUP_P31

# Entity QIDs adjudicated by the versioned shared-QID report as series/group
# identities. This small fail-closed registry lets ordinary sidecar validation
# reject known bad writes without making validation depend on the network.
KNOWN_SERIES_QIDS: frozenset[str] = frozenset(
    {
        "Q2667782",  # Rubens' Descent from the Cross triptych
    }
)


def is_group_class(qid: str) -> bool:
    """True when `qid` denotes a SET of works rather than one work."""
    return qid in GROUP_P31


def is_single_work_class(qid: str) -> bool:
    """True when `qid` may serve as a single work's stable identifier.

    Deliberately NOT `qid in ALLOWED_P31 and not is_group_class(qid)` written
    inline at each call site — the two questions have drifted apart before, and
    a named predicate is what stops a future caller from asking the looser one
    by accident.
    """
    return qid in SINGLE_WORK_P31


# Historical junk that must never re-enter the allowlist.
FORBIDDEN_P31: frozenset[str] = frozenset(
    {
        "Q11086742",  # anime television program
        "Q1167694",  # Raboy (surname)
        "Q57276",  # Michael D. Higgins (person)
    }
)

USER_AGENT = "FineArtArchive/0.3 (tim@stranskemo.com)"


def allowed_p31_sparql_values() -> str:
    """Render ``ALLOWED_P31`` as a SPARQL ``VALUES ?cls { ... }`` body."""
    parts = " ".join(f"wd:{qid}" for qid in sorted(ALLOWED_P31, key=_qid_sort_key))
    return f"VALUES ?cls {{ {parts} }}"


def _qid_sort_key(qid: str) -> tuple[int, str]:
    digits = qid[1:] if qid.startswith("Q") and qid[1:].isdigit() else qid
    return (int(digits) if isinstance(digits, str) and digits.isdigit() else 0, qid)


def _p279_parents(entity: object) -> list[str]:
    """Extract direct P279 (subclass of) target QIDs from a wbgetentities entity."""
    if not isinstance(entity, dict) or "missing" in entity:
        return []
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return []
    parents: list[str] = []
    for statement in claims.get("P279") or []:
        if not isinstance(statement, dict):
            continue
        snak = statement.get("mainsnak")
        if not isinstance(snak, dict) or snak.get("snaktype") != "value":
            continue
        value = (snak.get("datavalue") or {}).get("value")
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            parents.append(value["id"])
    return parents


def _claim_qids(entity: object, property_id: str) -> list[str]:
    """Extract entity-valued claim targets for ``property_id``."""
    if not isinstance(entity, dict) or "missing" in entity:
        return []
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return []
    qids: list[str] = []
    for statement in claims.get(property_id) or []:
        if not isinstance(statement, dict):
            continue
        snak = statement.get("mainsnak")
        if not isinstance(snak, dict) or snak.get("snaktype") != "value":
            continue
        value = (snak.get("datavalue") or {}).get("value")
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            qids.append(value["id"])
    return qids


def _reachable_roots(
    qid: str, roots: frozenset[str], parent_map: dict[str, list[str]]
) -> frozenset[str]:
    """Return roots reached from ``qid`` through zero or more P279 edges."""
    matched: set[str] = set()
    seen: set[str] = set()
    stack = [qid]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if current in roots:
            matched.add(current)
        stack.extend(parent_map.get(current, []))
    return frozenset(matched)


def series_qid_evidence(qid: str, entities: dict[str, object]) -> dict[str, object]:
    """Classify an entity QID from P31/P279 evidence supplied by the caller.

    ``entities`` is a hermetic ``wbgetentities``-shaped mapping containing the
    candidate, its P31 classes, and any P279 ancestors needed for the decision.
    The function never performs network I/O.
    """
    p31 = _claim_qids(entities.get(qid), "P31")
    parent_map = {entity_qid: _p279_parents(entity) for entity_qid, entity in entities.items()}
    matched: set[str] = set()
    for class_qid in p31:
        matched.update(_reachable_roots(class_qid, GROUP_P31, parent_map))
    return {
        "qid": qid,
        "is_series": bool(matched),
        "p31": sorted(set(p31), key=_qid_sort_key),
        "matched_group_classes": sorted(matched, key=_qid_sort_key),
    }


def is_series_qid(qid: str, entities: dict[str, object]) -> bool:
    """True when the entity's P31/P279 evidence reaches a group class."""
    return bool(series_qid_evidence(qid, entities)["is_series"])


def is_subclass_of_work_of_art(qid: str, parent_map: dict[str, list[str]]) -> bool:
    """Return True when ``qid`` is work-of-art or reaches it via ``parent_map`` P279 edges."""
    if qid == WORK_OF_ART_QID:
        return True
    seen: set[str] = set()
    stack = [qid]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for parent in parent_map.get(current, []):
            if parent == WORK_OF_ART_QID:
                return True
            stack.append(parent)
    return False


def allowed_p31_non_artwork_mismatches(
    entities: dict[str, object],
) -> list[str]:
    """Return allowlist members that are not subclasses of work of art.

    ``entities`` is a ``wbgetentities`` ``entities`` object (or a hermetic
    stand-in).  Parent links are read from each entity's P279 claims; missing
    entities are reported as mismatches.
    """
    parent_map: dict[str, list[str]] = {
        qid: _p279_parents(entity) for qid, entity in entities.items()
    }
    mismatches: list[str] = []
    for qid in sorted(ALLOWED_P31, key=_qid_sort_key):
        entity = entities.get(qid)
        if not isinstance(entity, dict) or "missing" in entity:
            mismatches.append(f"{qid}: Wikidata returned no entity for allowlist member")
            continue
        if not is_subclass_of_work_of_art(qid, parent_map):
            parents = parent_map.get(qid) or []
            evidence = ", ".join(parents) if parents else "no P279 parents"
            mismatches.append(
                f"{qid}: not a subclass of {WORK_OF_ART_QID} (work of art); P279 → {evidence}"
            )
    return mismatches


def audit_allowed_p31_against_wikidata(*, timeout: int = 20) -> list[str]:
    """Fetch allowlist QIDs once and return non-artwork mismatches.

    Opt-in only: regular CI must stay hermetic (set ``RUN_WIKIDATA_AUDIT=1``).
    """
    qids = "|".join(sorted(ALLOWED_P31, key=_qid_sort_key))
    query = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "format": "json",
            "props": "claims|labels",
            "languages": "en",
            "ids": qids,
        }
    )
    request = urllib.request.Request(
        f"https://www.wikidata.org/w/api.php?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict) or not isinstance(payload.get("entities"), dict):
        raise ValueError("Wikidata wbgetentities response did not include an entities object")
    return allowed_p31_non_artwork_mismatches(payload["entities"])
