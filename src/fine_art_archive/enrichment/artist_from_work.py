"""Adopt a work's Wikidata creator (P170) as the sidecar artist.

A large batch of works carry a resolved work QID (``stable_identifiers.
wikidata_q``) but a wrong or placeholder ``artist.name`` -- a mis-parsed caption
token: a date ("1602"), a place ("_El_Jem"), a period label ("British School,
16th century"). The work entity itself records the real creator via P170, which
is authoritative, so this reads it back as ground truth.

Guards (precision over recall -- ``artist.wikidata_q`` is load-bearing):

  * only when the sidecar has NO valid ``artist.wikidata_q`` (a resolved artist
    is never overwritten);
  * only when the work's P170 is a single, concrete creator QID -- ``somevalue``
    (Wikidata's explicit "anonymous") and absent P170 both yield no creator, so
    genuinely-anonymous works and mis-resolved work QIDs (whose entity is a
    place/person with no P170) are declined, not guessed at;
  * skipped when the sidecar ``artist.name`` already names that creator (folded
    containment) -- nothing to fix.

The raw ``artist.name`` placeholder is replaced (it was never a real source
attribution, so preserving it would just perpetuate the parse error); the
original is retained verbatim in the provenance note, so the change is lossless.
Network access is injected (a ``.get(url) -> dict | None`` client) so the mapper
stays offline-testable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fine_art_archive.enrichment.wikidata_identity import fetch_identity
from fine_art_archive.identity.artist_resolver import fold_name


class _Client(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class CreatorAdoption:
    creator_qid: str
    display_name: str
    lifespan: str | None


def creator_qid_of(work_qid: str, *, client: _Client) -> tuple[str | None, str]:
    """Return ``(creator_qid, reason)`` for a work's single P170 creator.

    ``reason`` is ``"creator"`` / ``"anonymous"`` (P170 somevalue) /
    ``"no-p170"`` / ``"multiple"`` / ``"fetch-failed"``.
    """
    if not work_qid:
        return None, "no-work-qid"
    payload = client.get(f"https://www.wikidata.org/wiki/Special:EntityData/{work_qid}.json")
    if not isinstance(payload, dict):
        return None, "fetch-failed"
    entity = (payload.get("entities") or {}).get(work_qid)
    if not isinstance(entity, dict):
        return None, "fetch-failed"
    statements = (entity.get("claims") or {}).get("P170", [])
    qids: list[str] = []
    saw_anonymous = False
    for statement in statements:
        snak = statement.get("mainsnak") or {}
        if snak.get("snaktype") == "somevalue":
            saw_anonymous = True
            continue
        value = snak.get("datavalue")
        if isinstance(value, dict) and isinstance(value.get("value"), dict):
            qid = value["value"].get("id")
            if isinstance(qid, str) and qid:
                qids.append(qid)
    distinct = list(dict.fromkeys(qids))
    if len(distinct) == 1:
        return distinct[0], "creator"
    if len(distinct) > 1:
        return None, "multiple"
    return None, ("anonymous" if saw_anonymous else "no-p170")


def _current_artist_qid(meta: Mapping[str, Any]) -> str | None:
    artist = meta.get("artist")
    if not isinstance(artist, Mapping):
        return None
    qid = artist.get("wikidata_q")
    if isinstance(qid, str) and qid:
        return qid
    canonical = artist.get("canonical")
    if isinstance(canonical, Mapping):
        cq = canonical.get("wikidata_q")
        return cq if isinstance(cq, str) and cq else None
    return None


def _work_qid(meta: Mapping[str, Any]) -> str | None:
    stable = meta.get("stable_identifiers")
    if isinstance(stable, Mapping):
        qid = stable.get("wikidata_q")
        return qid if isinstance(qid, str) and qid else None
    return None


def resolve_adoption(
    meta: Mapping[str, Any], *, client: _Client
) -> tuple[CreatorAdoption | None, str]:
    """Return ``(CreatorAdoption, "adopt")`` or ``(None, reason)`` for one sidecar."""
    if _current_artist_qid(meta) is not None:
        return None, "artist-already-resolved"
    work_qid = _work_qid(meta)
    if work_qid is None:
        return None, "no-work-qid"
    creator_qid, reason = creator_qid_of(work_qid, client=client)
    if creator_qid is None:
        return None, reason
    display_name, lifespan = fetch_identity(creator_qid, client=client)
    if not display_name:
        return None, "identity-fetch-failed"
    artist = meta.get("artist")
    current_name = artist.get("name") if isinstance(artist, Mapping) else None
    # Already names this creator (any spelling variant) -> nothing to fix.
    if (
        isinstance(current_name, str)
        and current_name.strip()
        and fold_name(display_name) in fold_name(current_name)
    ):
        return None, "already-named"
    return CreatorAdoption(creator_qid, display_name, lifespan), "adopt"
