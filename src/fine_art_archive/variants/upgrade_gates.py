"""The crop test, for anything proposing to replace a master.

`scripts/promote_variant_upgrade.py` already refuses a candidate whose work
Q-ID differs from its target's, and one offered to several works at once. Those
answer "is this the same WORK?". They do not answer "is the file I am about to
overwrite doing a job this candidate cannot do", and in this archive that is a
separate question with its own answer.

`display/crops.py` opens with the rule: "nothing may be called a duplicate until
`classify_pair` has been run on it." Replacing a master IS a redundancy claim —
the old file is superseded and stops being what the app serves — so the rule
binds here, and this is the sixth place in the archive that has had to be taught
it separately.

The case it catches, measured 2026-09-02. `e2ed232-las-meninas-velazquez` holds
a master of 16875x30000: aspect 0.5625, which is exactly 9:16 — a portrait crop
cut for a frame, carrying `files.variants[]` links. The 266.9 MB candidate is
the uncropped painting at 0.8688. Both are real, both are wanted, and neither is
a duplicate of the other. Identity checks pass it (same painting); only the crop
test refuses it.

This lives in the library rather than in the executor because the detector that
PRODUCES candidates should never queue one the executor would refuse, and the
detector is a workspace script that imports this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..display.crops import ASPECT_TOLERANCE, classify_pair, display_aspect_of

__all__ = ["CropGate", "crop_gate", "master_facts"]


@dataclass(frozen=True)
class CropGate:
    """Whether the held master may be superseded by this candidate."""

    ok: bool
    reason: str = ""
    #: True when an operator looking at both images may proceed anyway. False
    #: means positive evidence the held file serves a purpose of its own.
    overridable: bool = False
    #: Whether the test had anything to measure. An `ok` with `measured=False`
    #: is "this gate has no evidence either way", NOT "checked, and it is fine".
    #: Callers must render those differently — a pass on ignorance that reads
    #: like a pass on evidence is how a silent gate gets built.
    measured: bool = True


def _positive_int(value: Any) -> int | None:
    """A usable pixel count, or None for anything that is not one.

    Sidecars are written by several tools and one of them is a workspace script
    this repo does not own, so `dimensions_px` arrives as whatever they put
    there. `[None, 100]` and `[nan, 100]` both raise inside `int()`, and this
    runs on the path to a REFUSAL — a malformed candidate sidecar aborting the
    whole evaluation instead of being refused is the opposite of what a safety
    gate is for. Zero and negatives are rejected too: they parse fine and then
    produce an aspect of 0.0 or -0.05, which is worse than no aspect at all
    because the crop test would reason from it.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN / infinities
        return None
    number = int(value)
    return number if number > 0 else None


def master_facts(meta: dict[str, Any]) -> tuple[float | None, int | None, tuple[int, int] | None]:
    """(aspect, size_bytes, pixels) for a sidecar's master, as far as it records them.

    Anything unusable comes back None. Never raises: see `_positive_int`.
    """
    block = (meta.get("files") or {}).get("master") or {}
    px = block.get("dimensions_px")
    pixels = None
    if isinstance(px, (list, tuple)) and len(px) == 2:
        width, height = _positive_int(px[0]), _positive_int(px[1])
        if width is not None and height is not None:
            pixels = (width, height)
    aspect = pixels[0] / pixels[1] if pixels else None
    size = block.get("size_bytes")
    return (
        aspect,
        (int(size) if isinstance(size, int) and not isinstance(size, bool) else None),
        pixels,
    )


def crop_gate(held: dict[str, Any], candidate: dict[str, Any]) -> CropGate:
    """Run the archive's crop test over a proposed master replacement.

    Two traps live in the plumbing, both hit on the way in:

    * Branch on the verdict STRING, never on `CropVerdict.protected` —
      `needs_review` also sets that flag as a fail-safe, so testing it reports
      every unverifiable pair as positive evidence of harm.
    * `redundant` is reserved for two renditions at IDENTICAL pixel dimensions,
      one image at two JPEG qualities. A real upgrade has MORE pixels, so it can
      never earn that verdict, and demanding it would refuse every legitimate
      promotion forever — a gate whose only clear path its own subject cannot
      take. `needs_review` is therefore cleared here on positive evidence of
      what an upgrade actually is: same framing, more pixels, and a held file
      that is not itself cut to a display aspect.
    """
    a_aspect, a_bytes, a_px = master_facts(held)
    b_aspect, b_bytes, b_px = master_facts(candidate)
    held_links = bool((held.get("files") or {}).get("variants"))
    cand_links = bool((candidate.get("files") or {}).get("variants"))

    # This gate is additive safety on top of an identity check that already
    # requires both work Q-IDs present and equal. Its job is to refuse on
    # POSITIVE evidence of a crop relationship, so with no aspect on either side
    # and no variant links it has nothing to say — and says so, rather than
    # refusing on ignorance or passing as though it had checked.
    if a_aspect is None and b_aspect is None and not (held_links or cand_links):
        return CropGate(True, "crop test had no dimensions to compare", measured=False)

    verdict = classify_pair(
        a_aspect,
        a_bytes,
        a_px,
        b_aspect,
        b_bytes,
        b_px,
        a_has_variant_links=held_links,
        b_has_variant_links=cand_links,
    )
    reason = verdict.reasons[0] if verdict.reasons else "no reason recorded"

    if verdict.verdict == "protected":
        return CropGate(False, f"crop test says PROTECTED: {reason}", overridable=False)
    if verdict.safe_to_dedupe:
        return CropGate(True)

    same_framing = bool(
        a_aspect
        and b_aspect
        and abs(a_aspect - b_aspect) / max(a_aspect, b_aspect) <= ASPECT_TOLERANCE
    )
    bigger = bool(a_px and b_px and (b_px[0] * b_px[1]) > (a_px[0] * a_px[1]))
    if same_framing and bigger and display_aspect_of(a_aspect) is None:
        return CropGate(True)
    return CropGate(False, f"crop test could not verify redundancy: {reason}", overridable=True)
