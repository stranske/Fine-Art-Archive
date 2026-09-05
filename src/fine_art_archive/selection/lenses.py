"""Five lenses with separate budget shares, instead of one ranker.

The selection rule used to be `(transfer_deferrals, -sitelinks)` — which is to
say the archive was ranked on name recognition alone. That is right for
Versailles and wrong for the museum in Nukus, and no single score holds both:
the requirements genuinely conflict.

So each lens ranks the same pool by its own criterion and gets its own share of
the batch. Each is allowed to be wrong in its own way, and no one failure mode
can capture the whole archive.

  canon         work-level notability — the obvious greats
  atypicality   rare-for-this-painter — a Rembrandt landscape is 3.6% of him
  standing      the museum's own renown, for collections nobody catalogued
  series        canonical sets, where the 30th print is not filler
  regional      an explicit allocation, because a global ranker spends it all
                on Europe: the data is denser there, which is a fact about
                digitisation budgets rather than about the art

Two rules run through all of it.

**A lens with no feature data is UNAVAILABLE, never a lens that scored zero.**
An unavailable lens forfeits its share to the others and says so in the report.
Silently scoring 0 would let a broken feature pipeline masquerade as "nothing
matched", which is the failure this codebase keeps re-learning.

**The saturation cap holds a share, it does not ban a subject.** Madonnas are
11.2% of the archive and 18.3% of the candidate pool; the cap keeps acquisition
near the former instead of drifting to the latter. It reports what it held back
AND how much headroom remains, so "nothing selected" can never be mistaken for
"nothing eligible".
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: Budget shares per lens. They need not sum to 1.0 — the allocator normalises
#: over whichever lenses are actually available on the day.
LENS_SHARES: dict[str, float] = {
    "canon": 0.35,
    "atypicality": 0.20,
    "series": 0.15,
    "regional": 0.20,
    "standing": 0.10,
}


@dataclass(frozen=True)
class Lens:
    """One way of ranking candidates.

    `score` returns None when this candidate has no feature data for this lens.
    A lens whose every candidate returns None is unavailable — which is a
    different statement from "this lens ranked nothing highly".
    """

    name: str
    describe: str
    score: Callable[[Mapping[str, Any]], float | None]

    def rank(self, pool: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        scored = [(self.score(c), c) for c in pool]
        usable = [(s, c) for s, c in scored if s is not None]
        usable.sort(key=lambda sc: (-sc[0], str(sc[1].get("qid", ""))))
        return [c for _, c in usable]


@dataclass
class LensReport:
    name: str
    available: bool
    #: Why it could not run. Empty when available.
    reason: str
    #: Slots this lens was allocated, and what it actually contributed.
    allotted: int = 0
    chosen: list[str] = field(default_factory=list)
    #: How many candidates this lens could score at all.
    scorable: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "reason": self.reason,
            "allotted": self.allotted,
            "chosen": list(self.chosen),
            "scorable": self.scorable,
        }


@dataclass
class SaturationReport:
    """What the iconography cap held back, and what headroom is left.

    `held` alone reads as a working filter forever. `held` beside `headroom` is
    what distinguishes "the cap is doing its job" from "the cap is stuck shut".
    """

    bucket_shares: dict[str, float]
    held: dict[str, int]
    headroom: dict[str, int]

    def summary(self) -> dict[str, Any]:
        return {
            "bucket_shares": dict(self.bucket_shares),
            "held": dict(self.held),
            "headroom": dict(self.headroom),
            "total_held": sum(self.held.values()),
            "total_headroom": sum(self.headroom.values()),
        }


# --------------------------------------------------------------------------
# The lenses
# --------------------------------------------------------------------------
def _f(cand: Mapping[str, Any], key: str) -> Any:
    """Read a precomputed feature, or None when it was never computed."""
    return (cand.get("lens_features") or {}).get(key)


def _finite_float(value: Any) -> float | None:
    """Coerce a numeric feature without letting malformed values rank a work."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _finite_whole(value: Any) -> int | None:
    """Return a finite whole-number count, or mark the feature unavailable."""
    number = _finite_float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _nonnegative_count(value: Any) -> int | None:
    """Return a non-negative whole count, or mark the feature unavailable."""
    count = _finite_whole(value)
    return count if count is not None and count >= 0 else None


def _canon(cand: Mapping[str, Any]) -> float | None:
    return _nonnegative_count(cand.get("sitelinks"))


def _atypicality(cand: Mapping[str, Any]) -> float | None:
    """How rare this work's genre is within its own painter's output.

    Rembrandt painted 27 landscapes out of 754 works, so a Rembrandt landscape
    scores 1 - 0.036 = 0.964. This is deliberately independent of fame: it
    finds the Oslo `Landscape with a Horseman`, which has zero sitelinks.
    """
    share = _f(cand, "genre_share_in_oeuvre")
    share = _finite_float(share)
    if share is None:
        return None
    # Guard against a malformed share; a share of 0 would otherwise score 1.0
    # and let a genre the artist never painted outrank everything.
    if not 0 < share <= 1:
        return None
    return 1.0 - share


def _series(cand: Mapping[str, Any]) -> float | None:
    """Prefer works that complete a set the archive already part-holds."""
    size = _finite_whole(_f(cand, "series_size"))
    held = _finite_whole(_f(cand, "series_held"))
    if size is None or held is None or size <= 1 or held <= 0:
        return None
    # Most valuable when the archive holds some but not all of the series.
    fraction = held / size
    if fraction >= 1.0:
        return None
    return fraction


def _regional(cand: Mapping[str, Any]) -> float | None:
    """Under-representation of this work's country in the archive."""
    share = _finite_float(_f(cand, "country_share_in_archive"))
    if share is None or not 0 <= share <= 1:
        return None
    return 1.0 - share


#: Curated works rank above every uncurated one. The gap is wider than any
#: plausible sitelink count so the two bands cannot interleave.
_CURATED_BAND = 10_000.0


def _standing(cand: Mapping[str, Any]) -> float | None:
    """Institutional judgement — about the WORK first, the building second.

    This lens began as "how renowned is the holding museum", which has an
    obvious failure: the White House carries 142 sitelinks, more than any
    actual museum in the candidate pool, so it won every slot this lens had
    (measured 2026-08-30, 2 of 7 places in one batch) on the strength of being
    a famous building rather than a serious collection.

    A holder choosing to publish a work on Google Arts & Culture is a judgement
    about that work, made by the people who own it — which is what this lens
    was always reaching for. 24.8% of screened candidates carry the marker, so
    it discriminates rather than admitting everything. Renown still breaks ties
    inside each band, and still ranks works with no marker at all, so an
    institution GA&C has never partnered with is not silently excluded.
    """
    curated = _f(cand, "gac_curated")
    raw_sitelinks = _f(cand, "holder_sitelinks")
    sl = _nonnegative_count(raw_sitelinks)
    if raw_sitelinks is not None and sl is None:
        return None
    if curated:
        return _CURATED_BAND + (sl or 0)
    return sl


LENSES: tuple[Lens, ...] = (
    Lens("canon", "work-level notability", _canon),
    Lens("atypicality", "rare for this painter", _atypicality),
    Lens("series", "completes a set already part-held", _series),
    Lens("regional", "under-represented country", _regional),
    Lens("standing", "the holder chose to publish this work", _standing),
)


# --------------------------------------------------------------------------
# Saturation cap
# --------------------------------------------------------------------------
def apply_saturation_cap(
    pool: Sequence[Mapping[str, Any]],
    *,
    batch_cap: int,
    archive_shares: Mapping[str, float],
    bucket_of: Callable[[Mapping[str, Any]], str],
    tolerance: float = 1.0,
) -> tuple[list[Mapping[str, Any]], SaturationReport]:
    """Hold each subject bucket near its existing share of the archive.

    NOT a ban. A bucket at 11% of the archive keeps earning ~11% of each batch;
    what it stops is the candidate pool's 18% drifting into the archive. A
    bucket with no recorded archive share is uncapped rather than blocked —
    an unknown share must not silently forbid a subject.
    """
    allowed: dict[str, int] = {}
    for bucket, share in archive_shares.items():
        # At least one slot for any bucket the archive holds at all: a cap that
        # rounds a real subject down to zero is a ban wearing a cap's clothes.
        allowed[bucket] = max(1, int(round(batch_cap * float(share) * tolerance)))

    taken: dict[str, int] = {}
    held: dict[str, int] = {}
    kept: list[Mapping[str, Any]] = []
    for cand in pool:
        bucket = bucket_of(cand)
        limit = allowed.get(bucket)
        if limit is None:
            kept.append(cand)
            continue
        if taken.get(bucket, 0) >= limit:
            held[bucket] = held.get(bucket, 0) + 1
            continue
        taken[bucket] = taken.get(bucket, 0) + 1
        kept.append(cand)

    headroom = {b: max(0, allowed[b] - taken.get(b, 0)) for b in allowed}
    return kept, SaturationReport(bucket_shares=dict(archive_shares), held=held, headroom=headroom)


# --------------------------------------------------------------------------
# Allocation
# --------------------------------------------------------------------------
def _allocation_weights(available: Sequence[str], shares: Mapping[str, float]) -> dict[str, float]:
    """Use positive finite shares, with defaults for invalid or missing values.

    Named lenses fall back to their declared share; custom lenses use 1.0.
    Scale before summing so even large finite shares cannot overflow the total.
    """
    weights: dict[str, float] = {}
    for name in available:
        weight = _finite_float(shares.get(name))
        if weight is None or weight <= 0.0:
            weight = LENS_SHARES.get(name, 1.0)
        weights[name] = weight
    scale = max(weights.values())
    return {name: weight / scale for name, weight in weights.items()}


def allocate(
    batch_cap: int, available: Sequence[str], shares: Mapping[str, float]
) -> dict[str, int]:
    """Split `batch_cap` slots across the available lenses, largest-remainder.

    Shares are renormalised over the AVAILABLE lenses only, so an unavailable
    lens hands its budget to the others rather than shrinking the batch. Every
    available lens gets at least one slot when the cap allows — a lens that
    never gets a slot is indistinguishable from one that is switched off.
    """
    if batch_cap <= 0 or not available:
        return {}
    weights = _allocation_weights(available, shares)
    total = sum(weights.values())

    exact = {n: batch_cap * (w / total) for n, w in weights.items()}
    out = {n: int(v) for n, v in exact.items()}

    if batch_cap >= len(available):
        for n in available:
            out[n] = max(1, out[n])
        while sum(out.values()) > batch_cap:
            # Trim the most over-served lens relative to its exact entitlement.
            over = max(
                (name for name in available if out[name] > 1),
                key=lambda name: out[name] - exact[name],
                default=None,
            )
            if over is None:
                break
            out[over] -= 1

    remainder = batch_cap - sum(out.values())
    if remainder > 0:
        order = sorted(available, key=lambda n: (-(exact[n] - int(exact[n])), n))
        for i in range(remainder):
            out[order[i % len(order)]] += 1
    return out


def allocate_monthly(
    batch_cap: int,
    available: Sequence[str],
    shares: Mapping[str, float],
    *,
    monthly_cap: int,
    spent: Mapping[str, int],
) -> tuple[dict[str, int], dict[str, str]]:
    """Allocate today's slots against the MONTH's entitlement, not the day's.

    `allocate()` splits each batch by share, which sounds equivalent and is not.
    The batch cap exists only to keep growth steady; the budget that the shares
    are meant to divide is monthly. At a batch of 7 across 5 lenses the
    "everyone gets at least one" floor swamps the shares completely — measured
    2026-08-30, a declared 35/20/15/20/10 came out as 29/14/14/14/29, handing
    the weakest lens three times its intended weight. The shares only landed
    exactly at a batch of 20.

    Allocating monthly fixes that without removing the floor: a lens that is
    ahead of its monthly pace simply yields today and catches up later, and
    over a month the shares land wherever the batch size happens to sit.

    Returns (allocation, notes). A lens present in `notes` got fewer slots than
    its share implies, WITH THE REASON — a lens at zero must always be
    distinguishable from a lens that silently stopped working.
    """
    if batch_cap <= 0 or not available:
        return {}, {}

    weights = _allocation_weights(available, shares)
    total = sum(weights.values())

    entitlement = {n: monthly_cap * (w / total) for n, w in weights.items()}
    left = {n: entitlement[n] - float(spent.get(n, 0)) for n in available}

    notes: dict[str, str] = {}
    hungry = [n for n in available if left[n] > 0]
    for n in available:
        if left[n] <= 0:
            notes[n] = (
                f"at its monthly share already ({spent.get(n, 0)} of "
                f"{entitlement[n]:.0f}) — yielding this batch"
            )

    # Everyone is ahead of pace (or the month is over-spent). Fall back to the
    # per-batch split so the tick still fills its batch rather than stalling on
    # an accounting artefact.
    if not hungry:
        notes["_all"] = "every lens is at or past its monthly share; splitting by share"
        return allocate(batch_cap, available, shares), notes

    need = sum(left[n] for n in hungry)
    exact = {n: batch_cap * left[n] / need for n in hungry}
    out: dict[str, int] = dict.fromkeys(available, 0)
    for n in hungry:
        out[n] = int(exact[n])

    remainder = batch_cap - sum(out.values())
    if remainder > 0:
        order = sorted(hungry, key=lambda n: (-(exact[n] - int(exact[n])), n))
        for i in range(remainder):
            out[order[i % len(order)]] += 1
    return out, notes


def select(
    pool: Sequence[Mapping[str, Any]],
    *,
    batch_cap: int,
    shares: Mapping[str, float] | None = None,
    lenses: Iterable[Lens] = LENSES,
    id_of: Callable[[Mapping[str, Any]], str] = lambda c: str(c.get("qid", "")),
    monthly_cap: int | None = None,
    spent: Mapping[str, int] | None = None,
) -> tuple[list[Mapping[str, Any]], list[LensReport]]:
    """Pick up to `batch_cap` candidates, drawing from each available lens.

    Round-robins across lenses so that a lens late in the ordering still gets
    its picks when several lenses want the same candidate.

    Pass `monthly_cap` and `spent` to divide the MONTH's budget by share rather
    than each batch, which is the only way the shares actually bind at a small
    batch size — see `allocate_monthly`. Without them the per-batch split is
    used, which is correct but coarse.
    """
    shares = shares or LENS_SHARES
    lenses = list(lenses)

    ranked: dict[str, list[Mapping[str, Any]]] = {}
    reports: dict[str, LensReport] = {}
    for lens in lenses:
        order = lens.rank(pool)
        ranked[lens.name] = order
        reports[lens.name] = LensReport(
            name=lens.name,
            available=bool(order),
            reason="" if order else "no candidate carries this lens's feature data",
            scorable=len(order),
        )

    available = [ln.name for ln in lenses if reports[ln.name].available]
    if monthly_cap:
        allotment, notes = allocate_monthly(
            batch_cap, available, shares, monthly_cap=monthly_cap, spent=spent or {}
        )
        # A lens allotted zero because it is ahead of its monthly pace must say
        # so. Otherwise it is indistinguishable from a lens that broke, which
        # is the one confusion this module exists to prevent.
        for name, why in notes.items():
            if name in reports:
                reports[name].reason = why
    else:
        allotment = allocate(batch_cap, available, shares)
    for name, n in allotment.items():
        reports[name].allotted = n

    chosen: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    cursor = dict.fromkeys(available, 0)
    remaining = dict(allotment)

    # Round-robin rather than draining one lens at a time: taking canon's full
    # share first lets it consume candidates the regional lens was counting on.
    while len(chosen) < batch_cap and any(remaining.get(n, 0) > 0 for n in available):
        progressed = False
        for name in available:
            if remaining.get(name, 0) <= 0 or len(chosen) >= batch_cap:
                continue
            order = ranked[name]
            while cursor[name] < len(order):
                cand = order[cursor[name]]
                cursor[name] += 1
                cid = id_of(cand)
                if cid in seen:
                    continue
                seen.add(cid)
                chosen.append(cand)
                reports[name].chosen.append(cid)
                remaining[name] -= 1
                progressed = True
                break
            else:
                # This lens is exhausted; release its unused slots.
                remaining[name] = 0
        if not progressed:
            break

    # A lens can exhaust its unique candidates after its original allocation.
    # Reassign those unused slots to another lens with an unseen candidate so
    # the batch cap remains a cap, not an accidental shortage.
    while len(chosen) < batch_cap:
        progressed = False
        for name in available:
            order = ranked[name]
            while cursor[name] < len(order):
                cand = order[cursor[name]]
                cursor[name] += 1
                cid = id_of(cand)
                if cid in seen:
                    continue
                seen.add(cid)
                chosen.append(cand)
                reports[name].chosen.append(cid)
                progressed = True
                break
            if len(chosen) >= batch_cap:
                break
        if not progressed:
            break

    return chosen, [reports[ln.name] for ln in lenses]
