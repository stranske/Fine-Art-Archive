"""A preference vector from the ratings that exist, honestly.

Near-term item N-C6, owner decision D6. Rocchio because it is well-posed at
n=79: no training, no GPU, no hyperparameter search, and — the property that
matters most here — it degrades gracefully when one class is nearly empty.

**The ratings are heavily skewed positive.** Across 93 events on 79 works, fit
averages 8.2 on a 1-10 scale and quality 8.5. Tim rates what he chose to
acquire, so almost nothing is disliked. Classic Rocchio subtracts a
negative centroid; with three genuine negatives that centroid is noise
amplified by γ, and a model that confidently learns from three examples is
worse than one that admits it cannot.

Two consequences, both deliberate:

  * "Liked" and "disliked" are split at the rater's own **median**, not at a
    fixed threshold. An absolute cut at 5/10 would put 90% of the corpus on one
    side and learn nothing. Ties AT the median are dropped from both classes:
    on a 1-10 scale most scores tie there — this corpus's median fit is 9.0 —
    and an earlier version that swept ties into "disliked" counted every work
    rated 9/10 as a dislike while still reporting healthy support.
  * `negative_support` is reported alongside the vector, and
    `PreferenceVector.is_well_posed` is False when either side is too thin.
    A caller that ignores it gets a vector anyway — but the number is there to
    be checked, rather than the model silently pretending.

N-C7 (a Bradley-Terry micro-session) is what would mint real negatives. This
ships without it, and says so.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

#: Below this many works on either side of the median, the vector is reported
#: as not well-posed. Rocchio needs a handful of examples per class before a
#: centroid means anything; ten is the conventional floor and this corpus is
#: small enough that a lower one would be self-deception.
MIN_SUPPORT_PER_CLASS = 10

#: Rocchio weights. Beta over gamma because the positive class is both larger
#: and more trustworthy here — see the module docstring on the skew.
BETA = 1.0
GAMMA = 0.5


@dataclass(frozen=True)
class PreferenceVector:
    """Learned weights over features, plus what they rest on."""

    weights: dict[str, float]
    positive_support: int
    negative_support: int
    split_value: float
    axis: str
    feature_count: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_well_posed(self) -> bool:
        """False when a centroid rests on too few examples to mean anything."""
        return (
            self.positive_support >= MIN_SUPPORT_PER_CLASS
            and self.negative_support >= MIN_SUPPORT_PER_CLASS
        )

    def top(self, n: int = 10) -> list[tuple[str, float]]:
        return sorted(self.weights.items(), key=lambda kv: -kv[1])[:n]

    def bottom(self, n: int = 10) -> list[tuple[str, float]]:
        return sorted(self.weights.items(), key=lambda kv: kv[1])[:n]


def features_of(sidecar: dict) -> set[str]:
    """The feature set for one work.

    Content tags and artist only. Deliberately NOT category: 77 of the 79 rated
    works are `painting`, so it carries almost no information and would just add
    a constant to every vector.

    Rejected tags are excluded — a tag Tim rejected is evidence about the
    tagger, not about the work.
    """
    feats: set[str] = set()
    subject = sidecar.get("subject") or {}
    for tag in subject.get("content_tags") or []:
        if not isinstance(tag, dict):
            continue
        if tag.get("state") == "rejected":
            continue
        tag_id = tag.get("id")
        if tag_id:
            feats.add(f"tag:{tag_id}")
    artist = (sidecar.get("artist") or {}).get("name")
    if artist:
        feats.add(f"artist:{artist}")
    return feats


def _centroid(docs: list[set[str]], idf: dict[str, float]) -> dict[str, float]:
    """Mean IDF-weighted feature vector over a set of works."""
    if not docs:
        return {}
    total: Counter[str] = Counter()
    for d in docs:
        for f in d:
            total[f] += 1
    return {f: (c / len(docs)) * idf.get(f, 0.0) for f, c in total.items()}


def build(
    rated: list[tuple[dict, float]],
    *,
    axis: str = "fit",
) -> PreferenceVector:
    """Rocchio preference vector from (sidecar, score) pairs.

    `axis` names the score's meaning for the record — `fit` is the display
    question ("do I want this on the wall") and is the one D6 is about; quality
    is about the reproduction, not the choice.
    """
    scored = [(features_of(sc), s) for sc, s in rated if s is not None]
    notes: list[str] = []
    if not scored:
        return PreferenceVector({}, 0, 0, math.nan, axis, 0, ["no rated works supplied"])

    values = sorted(s for _, s in scored)
    mid = len(values) // 2
    split = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

    # Strictly above / strictly below, with ties at the median DROPPED.
    #
    # An earlier version used at-or-below for the negative class. On a 1-10
    # scale most scores tie at the median — the real corpus has median fit 9.0 —
    # so every work rated exactly 9/10 was swept into "disliked", inverting the
    # signal while still reporting healthy support on both sides. Dropping ties
    # costs examples and is honest about it; miscounting a 9 as a dislike is not
    # a smaller error for being invisible.
    pos = [f for f, s in scored if s > split]
    neg = [f for f, s in scored if s < split]
    ties = len(scored) - len(pos) - len(neg)
    if ties:
        notes.append(
            f"{ties} work(s) scored exactly at the median ({split}) and were excluded "
            "from both classes — a tie is not evidence either way"
        )
    if not pos or not neg:
        notes.append(f"all scores on one side of the median ({split}) — no contrast to learn from")

    n = len(scored)
    df: Counter[str] = Counter()
    for f, _ in scored:
        for feat in f:
            df[feat] += 1
    # Smoothed IDF: a feature on every work carries no preference information,
    # and without this the most common tag would dominate purely by frequency.
    idf = {f: math.log((n + 1) / (c + 1)) + 1.0 for f, c in df.items()}

    p_cent, n_cent = _centroid(pos, idf), _centroid(neg, idf)
    weights: dict[str, float] = {}
    for feat_name in set(p_cent) | set(n_cent):
        w = BETA * p_cent.get(feat_name, 0.0) - GAMMA * n_cent.get(feat_name, 0.0)
        if abs(w) > 1e-12:
            weights[feat_name] = w

    if len(neg) < MIN_SUPPORT_PER_CLASS:
        notes.append(
            f"only {len(neg)} work(s) below the median — the negative centroid "
            "is thin, so dislikes are weakly evidenced (N-C7 would mint real negatives)"
        )
    return PreferenceVector(weights, len(pos), len(neg), float(split), axis, len(idf), notes)


def score(sidecar: dict, vector: PreferenceVector) -> float:
    """Cosine-normalised affinity of one work to the preference vector.

    Normalised by the work's own feature count, so a heavily-tagged work does
    not outrank a sparsely-tagged one simply for having more tags.
    """
    feats = features_of(sidecar)
    if not feats or not vector.weights:
        return 0.0
    raw = sum(vector.weights.get(f, 0.0) for f in feats)
    return raw / math.sqrt(len(feats))
