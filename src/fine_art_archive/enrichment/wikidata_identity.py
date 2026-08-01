"""Fetch canonical person identity (display name + lifespan) from Wikidata.

Given an artist's Wikidata QID, returns the English label and a ``birth–death``
lifespan string suitable for the sidecar's ``artist.canonical`` block. Kept small
and side-effect-free apart from the injected ``client`` so it is easy to test.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Protocol

_YEAR = re.compile(r"^[+-](\d{1,4})-")


class _Client(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> dict[str, Any] | None: ...


def _claim_year(entity: Mapping[str, Any], prop: str) -> str | None:
    for statement in (entity.get("claims") or {}).get(prop, []):
        datavalue = (statement.get("mainsnak") or {}).get("datavalue")
        if isinstance(datavalue, dict):
            value = datavalue.get("value")
            if isinstance(value, dict):
                match = _YEAR.match(str(value.get("time", "")))
                if match:
                    return str(int(match.group(1)))
    return None


def fetch_identity(qid: str, *, client: _Client) -> tuple[str | None, str | None]:
    """Return ``(display_name, lifespan)`` for ``qid`` from Wikidata.

    ``display_name`` is the English label; ``lifespan`` is ``"birth–death"``
    (en-dash) when both P569/P570 years are present, or a one-sided ``"birth–"`` /
    ``"–death"`` when only one is. Both are ``None`` on any network/shape failure.
    """
    if not qid:
        return None, None
    payload = client.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    if not isinstance(payload, dict):
        return None, None
    entity = (payload.get("entities") or {}).get(qid)
    if not isinstance(entity, dict):
        return None, None
    display_name = (entity.get("labels") or {}).get("en", {}).get("value")
    birth = _claim_year(entity, "P569")
    death = _claim_year(entity, "P570")
    lifespan = f"{birth or ''}–{death or ''}" if (birth or death) else None
    return display_name, lifespan
