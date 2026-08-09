"""Latent preference from head-to-head comparisons — and the first real negatives.

Near-term item N-C7. It exists because of a specific gap: `rocchio.build` splits
liked from disliked at the rater's median, and on this corpus the median fit is
exactly 9.0, so **17 of 78 works tie there and are discarded**. Ties are not
evidence either way. Asking "is this good?" cannot separate them; asking "which
of these two?" can, because a forced choice has no neutral option.

Ten minutes of pairwise comparison is worth more here than another hundred
absolute ratings, which is why the audit sequenced this AFTER N-C6 rather than
instead of it.

**The property this must not lose.** Bradley-Terry scores are only comparable
within a CONNECTED component of the comparison graph. If Tim compares A-B and
C-D but never links the two pairs, there is no evidence relating A to C, and any
ranking that puts them on one scale is inventing it. `fit` reports components
and refuses to pretend otherwise — see `BradleyTerryResult.comparable`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

#: Iterations of the MM update. Convergence is fast for the small graphs this
#: sees (tens of items); the cap exists so a pathological input terminates.
MAX_ITERATIONS = 500

#: Stop when no strength moves by more than this in an iteration.
TOLERANCE = 1e-9

#: Half-games added to BOTH sides of every pair that was actually compared.
#: Without it a perfect record puts the maximum-likelihood strength at infinity
#: (undefeated) or zero (winless) and the fit never converges — not an edge case
#: but the normal outcome of a complete round-robin, which is exactly what a
#: ten-minute session over 17 works produces.
PRIOR_STRENGTH = 0.5


@dataclass(frozen=True)
class BradleyTerryResult:
    """Latent strengths, plus an honest account of what they rest on."""

    #: work_id -> latent strength. Higher is preferred. Only comparable WITHIN
    #: a component (see `components`).
    strengths: dict[str, float]
    #: Groups of works connected by at least one chain of comparisons.
    components: list[set[str]]
    comparisons: int
    iterations: int
    converged: bool
    notes: list[str] = field(default_factory=list)

    @property
    def comparable(self) -> bool:
        """True only when every rated work sits in ONE component.

        A ranking across disconnected components is fabricated: nothing in the
        data relates one group to the other.
        """
        return len(self.components) <= 1

    def ranked(self) -> list[tuple[str, float]]:
        return sorted(self.strengths.items(), key=lambda kv: -kv[1])

    def negatives(self, fraction: float = 0.5) -> list[str]:
        """The lower `fraction` of the ranking — genuine dislikes.

        This is the point of the whole exercise: absolute ratings on this corpus
        produce almost no negatives, and Rocchio needs a negative centroid.
        """
        r = self.ranked()
        cut = int(len(r) * fraction)
        return [w for w, _ in r[cut:]]


def _components(pairs: list[tuple[str, str]]) -> list[set[str]]:
    """Connected components of the comparison graph, via union-find."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in pairs:
        union(a, b)
    groups: dict[str, set[str]] = defaultdict(set)
    for node in parent:
        groups[find(node)].add(node)
    return sorted(groups.values(), key=len, reverse=True)


def fit(comparisons: list[tuple[str, str]]) -> BradleyTerryResult:
    """Fit Bradley-Terry strengths from (winner, loser) pairs.

    Uses the standard MM (minorisation-maximisation) update, which needs no
    optimiser and no gradient:

        p_i  <-  W_i / sum_j  n_ij / (p_i + p_j)

    with a symmetric prior on wins and comparisons so that an item which lost
    everything gets a small strength rather than zero, and one that won
    everything stays finite. On a ten-minute session both cases are likely.
    """
    notes: list[str] = []
    if not comparisons:
        return BradleyTerryResult({}, [], 0, 0, True, ["no comparisons recorded"])

    items = sorted({w for pair in comparisons for w in pair})
    wins: dict[str, float] = dict.fromkeys(items, 0.0)
    n: dict[tuple[str, str], float] = defaultdict(float)
    for winner, loser in comparisons:
        if winner == loser:
            notes.append(f"ignored a self-comparison for {winner}")
            continue
        wins[winner] += 1.0
        key = (winner, loser) if winner < loser else (loser, winner)
        n[key] += 1.0

    # Symmetric prior, applied PER COMPARED PAIR: pretend each pair also played
    # 2*PRIOR_STRENGTH games split evenly. Only pairs actually shown together
    # get one, so the prior never invents a relationship.
    #
    # It must be added to BOTH sides of the same pair. An earlier version added
    # the win prior once per ITEM but the count prior once per PAIR, so with 16
    # opponents each the denominator received 16x more prior than the numerator
    # and every strength was crushed toward zero. That only showed up on a real
    # round-robin: 136 comparisons over 17 works, where the undefeated work sat
    # at 10.9 and the winless one at 0.000, and the fit never converged.
    for (a, b) in list(n):
        n[(a, b)] += 2 * PRIOR_STRENGTH
        wins[a] += PRIOR_STRENGTH
        wins[b] += PRIOR_STRENGTH

    p: dict[str, float] = dict.fromkeys(items, 1.0)
    iterations = 0
    converged = False
    for step in range(1, MAX_ITERATIONS + 1):
        iterations = step
        new: dict[str, float] = {}
        for i in items:
            denom = 0.0
            for (a, b), count in n.items():
                if i not in (a, b):
                    continue
                j = b if a == i else a
                denom += count / (p[i] + p[j])
            new[i] = wins[i] / denom if denom > 0 else p[i]
        total = sum(new.values()) or 1.0
        new = {k: v * len(items) / total for k, v in new.items()}
        delta = max(abs(new[k] - p[k]) for k in items)
        p = new
        if delta < TOLERANCE:
            converged = True
            break
    if not converged:
        notes.append(f"did not converge within {MAX_ITERATIONS} iterations")

    comps = _components([(a, b) for a, b in comparisons if a != b])
    if len(comps) > 1:
        notes.append(
            f"the comparison graph has {len(comps)} disconnected components — "
            "strengths are comparable WITHIN a component only, because nothing "
            "in the data relates one group to another"
        )
    return BradleyTerryResult(p, comps, len(comparisons), iterations, converged, notes)


def next_pair(
    candidates: list[str],
    comparisons: list[tuple[str, str]],
    strengths: dict[str, float] | None = None,
) -> tuple[str, str] | None:
    """Choose the most informative pair to ask about next.

    Two rules, in order:

    1. **Connect the graph first.** A comparison that joins two components buys
       more than any comparison inside one, because without it no ranking
       spanning them is defensible at all.
    2. Then ask about the pair whose outcome is least predictable — closest in
       current strength. Comparing an obvious favourite against an obvious
       also-ran spends a question to learn nothing.

    Returns None when every pair has been asked.
    """
    if len(candidates) < 2:
        return None
    asked = {(a, b) if a < b else (b, a) for a, b in comparisons}

    comps = _components([(a, b) for a, b in comparisons if a != b])
    seen = {w for c in comps for w in c}
    unseen = [c for c in candidates if c not in seen]
    if unseen and seen:
        # Rule 1: attach an unseen work to the existing graph.
        return (unseen[0], sorted(seen)[0])
    if len(comps) > 1:
        return (sorted(comps[0])[0], sorted(comps[1])[0])

    best: tuple[float, tuple[str, str]] | None = None
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            key = (a, b) if a < b else (b, a)
            if key in asked:
                continue
            gap = abs(strengths.get(a, 1.0) - strengths.get(b, 1.0)) if strengths else 0.0
            if best is None or gap < best[0]:
                best = (gap, (a, b))
    return best[1] if best else None


def minimum_comparisons(n_items: int) -> int:
    """A floor, not a target: n-1 links are needed merely to connect n items.

    Reported so a session that stops early is visibly under-powered rather than
    quietly producing a ranking nobody should use. Roughly n*log2(n) gives
    usable strengths; below n-1 the graph cannot even be connected.
    """
    return max(0, n_items - 1)


def recommended_comparisons(n_items: int) -> int:
    """About n*log2(n) — enough for strengths to mean something."""
    if n_items < 2:
        return 0
    return int(round(n_items * math.log2(n_items)))
