"""A work QID denotes one work — enforced at the point of assignment.

Every pass that writes ``stable_identifiers.wikidata_q`` searches one sidecar at
a time and, before this module existed, never asked whether the identifier it
was about to write was already spoken for. Two passes did exactly that on
2026-08-09: ``backfill_work_qids_by_creator`` bound Q24046967 to three separate
*Field with Poppies* sidecars, and ``resolve_work_qids`` bound Q17277950 — the
Wikidata **group of paintings** for Cezanne's *Card Players* — to two members 15
minutes apart inside a single run.

Replaying the archive's own ``operations.log`` through :class:`WorkQidClaims`,
60 historical writes would have been declined, 58 of them from the by-creator
backfill. A guard living in one script would therefore have caught 2 of 60,
which is why this is a shared invariant and not a local patch.

Declining is deliberately the conservative move. Writing a QID that another
work already holds asserts the two sidecars are the same work — a claim these
passes have no evidence for and no means of testing, since
``same_work_registration`` can only ever CONFIRM sameness, never refute it. The
refusal leaves the work unresolved and names the incumbent, so the pair can be
adjudicated by a pass that does have evidence (dedup, or series -> ``part_of_q``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = ["WorkQidClaims", "work_qid_of"]


def work_qid_of(meta: dict[str, Any]) -> str | None:
    """``stable_identifiers.wikidata_q`` if set to a non-empty string."""
    stable = meta.get("stable_identifiers")
    if isinstance(stable, dict):
        qid = stable.get("wikidata_q")
        if isinstance(qid, str) and qid:
            return qid
    return None


class WorkQidClaims:
    """Who currently holds each work QID, updated as a run assigns more.

    Seeded from every sidecar rather than only the eligible ones: an incumbent
    holder is by definition ineligible for backfill (it already has a QID), so a
    scan limited to the work queue would see no collision at all.
    """

    def __init__(
        self,
        holders: dict[str, str] | None = None,
        *,
        same_object: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._holders: dict[str, str] = dict(holders or {})
        self._same_object = same_object

    @classmethod
    def from_sidecars(
        cls,
        paths: list[Path],
        *,
        load: Callable[[Path], dict[str, Any]],
        same_object: Callable[[str, str], bool] | None = None,
    ) -> WorkQidClaims:
        holders: dict[str, str] = {}
        for path in paths:
            try:
                meta = load(path)
            except Exception:
                # Unreadable sidecars are counted and reported by the archive
                # audit; a parse failure here must not disable the guard.
                continue
            qid = work_qid_of(meta)
            if qid:
                holders.setdefault(qid, str(meta.get("work_id") or path.parent.name))
        return cls(holders, same_object=same_object)

    def holder(self, qid: str | None) -> str | None:
        """The work_id already holding ``qid``, or None if unclaimed."""
        return self._holders.get(qid) if qid else None

    def collides(self, qid: str | None, work_id: str) -> str | None:
        """The *other* work holding ``qid``, or None when the write is safe.

        Two work_ids sharing a QID is not automatically wrong. The archive keeps
        a master and its 16:9 / 9:16 display crops as separate works, and those
        renditions genuinely *are* the same Wikidata work -- 69 of the 79
        contested QIDs in this archive are that case, not a real clash. When a
        ``same_object`` predicate is supplied (see
        :func:`fine_art_archive.identity.variants.same_object`) a shared QID
        between renditions of one work is allowed through.

        Without that predicate the behaviour is unchanged: any other holder is a
        collision. The guard is only ever relaxed by evidence of derivation, so
        two unrelated works still cannot take the same identifier.
        """
        holder = self.holder(qid)
        if holder is None or holder == work_id:
            return None
        if self._same_object is not None and self._same_object(holder, work_id):
            return None
        return holder

    def claim(self, qid: str, work_id: str) -> None:
        self._holders[qid] = work_id

    def __len__(self) -> int:
        return len(self._holders)


def collision_note(qid: str, holder: str, *, plan: str) -> str:
    """Provenance note for a refused assignment, naming the incumbent."""
    return (
        f"Declined {qid}: collision — already held by {holder}. Either these are "
        "one work held twice (dedup), or the QID denotes a series/version group "
        f"rather than this work ({plan})."
    )
