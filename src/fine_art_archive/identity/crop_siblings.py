"""Complementary crops of one work: the fourth way a work Q-ID lands on two sidecars.

A work Q-ID on more than one sidecar has been treated as wrong in one of three
ways -- a genuine duplicate holding, a series Q-ID stamped on each member, or a
subject Q-ID mistaken for a work Q-ID. Those three want opposite remedies, which
is why the weekly review has kept presenting the collision list as a decision.

There is a fourth way, and it is not wrong at all. A work too wide or too tall
for any panel is kept as SEVERAL complementary crops -- Tintoretto's *Miracle of
the Loaves and Fishes* (Met 13.75) is 154.9 x 407.7 cm, aspect 2.63, so a left
crop and a right crop together show what one crop cannot. Both crops depict that
painting, so both *correctly* carry its Q-ID. Counting them as defects gives the
collision metric a floor it can never reach: on 2026-09-01 the archive reported
``qids_on_multiple: 2`` and both were complementary-crop pairs, so the number was
2 with a drainable count of 0 -- a gate whose only clear path is blocked by the
thing it measures.

**This module is the drain.** It states the fourth case once, in the canonical
library, so that every analysis reads it from the data instead of re-deriving a
three-way taxonomy that has no bucket for the commonest case in this archive.

Two halves, deliberately separate:

``crop_sibling_groups``
    Pure. Reads what is already recorded -- ``files.variants[]`` entries with
    ``role="partial-crop"`` -- and returns the groups. No image I/O, so the
    corpus audit can call it on 3,500 sidecars without touching a pixel.

``measure_lateral_overlap``
    The detector, for sidecars where nothing is recorded yet. Locates one image
    inside the other and returns the offset and correlation.

The split matters. :class:`~fine_art_archive.identity.variants.VariantLinks`
declines to resolve mutually-linked pairs because "whoever wrote the entry does
not settle which file is the crop, and guessing would strip the Q-ID from the
authoritative capture". That is right, and the answer is not to guess but to
MEASURE, then write the measurement down so nothing has to guess again. The
2026-08-09 pass that wrote the Tintoretto links recorded the two sides
backwards -- it worked from aspect and file size and never opened the files --
and the error survived because no later check ever compared its claim to the
pixels.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from fine_art_archive.display.crops import SAME_CONTENT_MIN_CORRELATION
from fine_art_archive.identity.variant_identity import work_qid_of

__all__ = [
    "COMPLEMENTARY_MAX_NCC",
    "CropSiblingGroup",
    "LateralOverlap",
    "OVERLAP_MIN_NCC",
    "PARTIAL_CROP_ROLE",
    "crop_sibling_groups",
    "crop_sibling_work_ids",
    "measure_lateral_overlap",
]

#: The ``files.variants[].role`` that records this relationship. The schema
#: already defines it -- "one of SEVERAL complementary crops of a work too wide
#: or tall for any single panel ... none is redundant with the others".
PARTIAL_CROP_ROLE = "partial-crop"

#: Aligned correlation at or below this, combined with a strong offset match,
#: means the two files show DIFFERENT parts of one image.
COMPLEMENTARY_MAX_NCC = 0.90

#: How good the offset match must be before two files are called two parts of
#: one image. Calibrated 2026-09-01 against both known pairs and 11 randomly
#: drawn unrelated pairs from the archive:
#:
#:     known complementary   0.926 (Tintoretto), 0.992 (Van Gogh)
#:     unrelated works       max 0.559, mean 0.292 (n=11)
#:
#: 0.80 clears the highest unrelated pair by 0.24 and sits 0.13 below the
#: weaker true pair. Anything derived from the same-content threshold instead
#: of measured separation would have rejected the Tintoretto pair, which is how
#: the first draft of this constant was wrong.
OVERLAP_MIN_NCC = 0.80


@dataclass(frozen=True)
class LateralOverlap:
    """Where one rendition sits inside another, measured from the pixels.

    **This measurement can CONFIRM a relationship and can never refute one.**
    There is deliberately no "different work" verdict and none may be added --
    see :meth:`verdict`. A low correlation on this corpus is the EXPECTED
    result for a legitimate crop, for two reasons that co-occur constantly:

    * Display crops carry non-linear tonal edits, not just a rectangle. A
      parent plus the right rectangle reproduces one at only ~17.5 dB, so
      greyscale correlation collapses on a true match.
    * Museum plates routinely include the picture FRAME. The Met's own plate of
      *The Miracle of the Loaves and Fishes* reads aspect 2.26 against a canvas
      catalogued at 2.63, which breaks both the scale assumption here and any
      aspect sanity check applied around it.

    Measured 2026-09-01, the near-miss this warning exists for: the archive's
    two crops of that painting scored 0.229 and 0.327 against the Met plate --
    inside the unrelated-pairs range (max 0.559, n=11) -- and that was written
    up as "different painting, the work Q-ID is wrong". They are the same
    painting, left half and right half, and the CLIP dedup gate had it right at
    cos 0.9347. Acting on the number would have cleared a CORRECT
    ``stable_identifiers.wikidata_q``, which CLAUDE.md permits only "when
    evidence shows it is wrong".
    """

    #: Correlation of the two images with no shift applied. Low for
    #: complementary crops, near 1.0 for a re-encode.
    aligned_ncc: float
    #: Best correlation found at any lateral shift.
    best_ncc: float
    #: Shift, as a fraction of width, at which ``best_ncc`` occurs. Positive
    #: means the second image's content lies to the RIGHT of the first's.
    shift_fraction: float
    #: "a-left" | "b-left" | None when the evidence does not order them.
    ordering: str | None

    @property
    def complementary(self) -> bool:
        """True when these are POSITIVELY shown to be parts of one image.

        False means "not shown", never "shown not to be" -- read
        :meth:`verdict` rather than negating this.
        """
        return (
            self.best_ncc >= OVERLAP_MIN_NCC
            and self.aligned_ncc <= COMPLEMENTARY_MAX_NCC
            and abs(self.shift_fraction) >= 0.05
        )

    @property
    def same_content(self) -> bool:
        """True when the two files are POSITIVELY shown to share one framing.

        False means "not shown", never "shown not to be". See :meth:`verdict`.
        """
        return self.aligned_ncc >= SAME_CONTENT_MIN_CORRELATION

    @property
    def verdict(self) -> str:
        """``"same-content"`` | ``"complementary"`` | ``"inconclusive"``.

        The point of this property is the third value and the absence of a
        fourth. Two booleans invite ``if not overlap.complementary:`` read as a
        finding; a named ``inconclusive`` cannot be read that way. Callers must
        branch on this rather than negate a boolean, and must treat
        ``inconclusive`` as "no information", never as evidence of difference.
        """
        if self.same_content:
            return "same-content"
        if self.complementary:
            return "complementary"
        return "inconclusive"

    @property
    def disproves_shared_identity(self) -> bool:
        """Always False. Present so the question has a written answer.

        Something will eventually want to ask this measurement whether two
        files are different works. It cannot answer: it has no negative
        verdict, by design. Refuting a shared identity needs a method that
        survives tonal edits and framing -- CLIP/DINOv2, the holder's own
        catalogue record, or a person looking at the two images.
        """
        return False


@dataclass(frozen=True)
class CropSiblingGroup:
    """Sidecars that together cover one work, each showing a different part."""

    work_qid: str
    work_ids: tuple[str, ...]
    #: work_id -> recorded ``crop_position``, where one is recorded.
    positions: Mapping[str, str | None]

    @property
    def complete(self) -> bool:
        """True when every member is linked and carries a position."""
        return all(self.positions.get(w) for w in self.work_ids)


def _partial_crop_targets(meta: Mapping[str, Any]) -> dict[str, str | None]:
    """work_ids this sidecar declares to be complementary crops, with positions.

    ``rel_path`` is relative to ``<archive_root>/Art/``, so an in-archive
    holding reads ``works/<work_id>/<file>``; anything else names no sidecar.
    ``crop_position`` describes the VARIANT, per the schema, not the owner.
    """
    files = meta.get("files")
    if not isinstance(files, Mapping):
        return {}
    variants = files.get("variants")
    if not isinstance(variants, list):
        return {}
    out: dict[str, str | None] = {}
    for entry in variants:
        if not isinstance(entry, Mapping) or entry.get("role") != PARTIAL_CROP_ROLE:
            continue
        text = str(entry.get("rel_path") or "")
        if not text.startswith("works/"):
            continue
        parts = text.split("/")
        if len(parts) > 2 and parts[1]:
            out[parts[1]] = entry.get("crop_position")
    return out


def crop_sibling_groups(metas: Iterable[Mapping[str, Any]]) -> list[CropSiblingGroup]:
    """Groups of sidecars that share a work Q-ID *because* each shows part of it.

    A group is recognised only when the members declare each other with
    ``role="partial-crop"``. A one-sided declaration is not enough: the whole
    point is that the relationship is recorded rather than inferred, and a
    single entry cannot distinguish "these two are complementary" from a stray
    link. That keeps this from ever quietly excusing a real duplicate.
    """
    materialized = [m for m in metas if isinstance(m, Mapping)]
    by_qid: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for meta in materialized:
        qid = work_qid_of(meta)
        if qid:
            by_qid[qid].append(meta)

    groups: list[CropSiblingGroup] = []
    for qid, members in sorted(by_qid.items()):
        if len(members) < 2:
            continue
        ids = {str(m.get("work_id") or "") for m in members} - {""}
        if len(ids) != len(members):
            continue
        declared = {str(m.get("work_id")): _partial_crop_targets(m) for m in members}

        # Every declared in-group link must be reciprocated. A complete graph
        # is unnecessary (a three-crop work may be a chain), but a directed
        # cycle cannot prove that any pair is mutually complementary.
        reciprocal: dict[str, set[str]] = {}
        for owner, targets in declared.items():
            in_group = {target for target in targets if target in ids and target != owner}
            if not in_group:
                reciprocal = {}
                break
            reciprocal[owner] = {target for target in in_group if owner in declared.get(target, {})}
            if reciprocal[owner] != in_group:
                reciprocal = {}
                break
        if not reciprocal or set(reciprocal) != ids:
            continue
        connected = {next(iter(ids))}
        pending = list(connected)
        while pending:
            member = pending.pop()
            for target in reciprocal[member] - connected:
                connected.add(target)
                pending.append(target)
        if connected != ids:
            continue

        positions: dict[str, str | None] = {}
        for targets in declared.values():
            for work_id, pos in targets.items():
                if work_id in ids and pos and not positions.get(work_id):
                    positions[work_id] = pos
        groups.append(
            CropSiblingGroup(
                work_qid=qid,
                work_ids=tuple(sorted(ids)),
                positions={w: positions.get(w) for w in sorted(ids)},
            )
        )
    return groups


def crop_sibling_work_ids(metas: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """Every work_id belonging to a recognised complementary-crop group."""
    return frozenset(w for g in crop_sibling_groups(metas) for w in g.work_ids)


def measure_lateral_overlap(
    path_a: Any,
    path_b: Any,
    *,
    height: int = 700,
    strip_fraction: float = 0.30,
) -> LateralOverlap:
    """Locate one rendition inside the other and report the offset.

    Greyscale, height-normalised, correlation-based -- it answers "is this the
    same framing or a different part of the same picture", which is all the
    crop-sibling question needs. It is not a similarity score for identity.

    Raises ``ImportError`` when Pillow/NumPy are absent, rather than returning a
    verdict: "could not measure" must never be readable as "measured, and they
    differ".
    """
    import numpy as np  # noqa: PLC0415 - optional at import time by design
    from PIL import Image  # noqa: PLC0415

    if (
        not isinstance(strip_fraction, (int, float))
        or not np.isfinite(strip_fraction)
        or not 0 < strip_fraction <= 1
    ):
        raise ValueError("strip_fraction must be a finite value in (0, 1]")

    def load(path: Any) -> Any:
        with Image.open(path) as im:
            grey = im.convert("L")
            width, tall = grey.size
            scaled = grey.resize((max(1, int(width * height / tall)), height))
            return np.asarray(scaled, dtype=np.float32)

    def norm(block: Any) -> Any:
        return (block - block.mean()) / (block.std() + 1e-6)

    a, b = load(path_a), load(path_b)
    width = min(a.shape[1], b.shape[1])
    aligned = float((norm(a[:, :width]) * norm(b[:, :width])).mean())

    strip = min(width, max(1, int(width * strip_fraction)))
    span = width - strip

    def locate(needle: Any, haystack: Any) -> tuple[float, int]:
        seed = norm(needle)
        best = (-1.0, 0)
        for x in range(0, haystack.shape[1] - strip + 1, 2):
            score = float((seed * norm(haystack[:, x : x + strip])).mean())
            if score > best[0]:
                best = (score, x)
        return best

    a_right_in_b, x_ar = locate(a[:, -strip:], b)
    b_left_in_a, x_bl = locate(b[:, :strip], a)
    a_left_in_b, x_al = locate(a[:, :strip], b)

    best_ncc = max(a_right_in_b, b_left_in_a, a_left_in_b)
    ordering: str | None = None
    shift = 0.0
    if span > 0 and min(a_right_in_b, b_left_in_a) > a_left_in_b:
        # B's left edge was found at column x_bl of A, so B's content starts
        # that far into A: the two overlap with A on the left.
        ordering = "a-left"
        shift = x_bl / a.shape[1]
    elif span > 0 and a_left_in_b > min(a_right_in_b, b_left_in_a):
        # A's left edge was found at column x_al of B: B starts first.
        ordering = "b-left"
        shift = -(x_al / b.shape[1])

    return LateralOverlap(
        aligned_ncc=aligned,
        best_ncc=best_ncc,
        shift_fraction=shift,
        ordering=ordering,
    )
