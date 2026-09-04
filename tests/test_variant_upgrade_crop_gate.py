"""The crop test, for anything proposing to replace a master.

`promote_variant_upgrade.py` already refuses a candidate whose work Q-ID differs
from its target's, and one offered to several works at once. Those answer "is
this the same WORK?" — not "is the file I am about to overwrite doing a job this
candidate cannot do", which in this archive is a separate question.

The measured case, 2026-09-02: `e2ed232-las-meninas-velazquez` holds a master of
16875x30000 — aspect 0.5625, exactly 9:16, a portrait crop cut for a frame, with
`files.variants[]` links. The candidate is the uncropped painting at 0.8688.
Same painting, both wanted, neither a duplicate. Identity passes it; only the
crop test refuses it.
"""

from __future__ import annotations

from fine_art_archive.variants import crop_gate, master_facts


def meta(
    *, pixels: list[int] | None = None, size: int = 1_000_000, variants: list | None = None
) -> dict:
    block: dict = {"filename": "master.jpg", "size_bytes": size}
    if pixels:
        block["dimensions_px"] = pixels
    out: dict = {"files": {"master": block}}
    if variants is not None:
        out["files"]["variants"] = variants
    return out


def test_master_facts_reads_what_is_there() -> None:
    assert master_facts(meta(pixels=[1000, 500], size=42)) == (2.0, 42, (1000, 500))
    assert master_facts({}) == (None, None, None)


def test_a_nine_sixteen_held_master_is_protected() -> None:
    """The Las Meninas case, at its real dimensions."""
    gate = crop_gate(
        meta(pixels=[16875, 30000], size=19_478_716),
        meta(pixels=[26065, 30000], size=266_867_780),
    )
    assert not gate.ok and "PROTECTED" in gate.reason
    assert not gate.overridable, "a protected crop must not be promotable behind a flag"
    assert gate.measured


def test_existing_variant_links_protect_the_held_master() -> None:
    gate = crop_gate(
        meta(
            pixels=[1000, 1200], variants=[{"rel_path": "works/x/master.jpg", "role": "tv-master"}]
        ),
        meta(pixels=[4000, 4800]),
    )
    assert not gate.ok and not gate.overridable


def test_a_reframe_is_protected_however_many_pixels() -> None:
    gate = crop_gate(meta(pixels=[1000, 1200]), meta(pixels=[4800, 4000]))
    assert not gate.ok and not gate.overridable


def test_a_genuine_enlargement_passes() -> None:
    """Same framing, more pixels, not a display aspect — what an upgrade IS.

    `classify_pair` reserves "redundant" for two renditions at IDENTICAL pixel
    dimensions, so an upgrade can never earn that verdict. Demanding it would
    refuse every legitimate promotion forever.
    """
    gate = crop_gate(meta(pixels=[1000, 1200]), meta(pixels=[4000, 4800]))
    assert gate.ok and gate.measured


def test_a_smaller_candidate_is_not_an_enlargement() -> None:
    assert not crop_gate(meta(pixels=[4000, 4800]), meta(pixels=[1000, 1200])).ok


def test_no_dimensions_anywhere_is_reported_as_unmeasured() -> None:
    """ "Nothing to compare" must not be dressed up as "checked, and it is fine".

    This gate is additive safety on top of an identity check that already
    demands both work Q-IDs present and equal, so with no evidence it stands
    aside — but it says so, and `measured` is how a caller can tell the two
    apart. A pass on ignorance that reads like a pass on evidence is how a
    silent gate gets built.
    """
    gate = crop_gate(meta(), meta())
    assert gate.ok
    assert not gate.measured
    assert "no dimensions" in gate.reason


def test_variant_links_alone_are_enough_evidence_to_refuse() -> None:
    """Even with no dimensions on either side, a recorded crop link decides.

    This is what actually catches the real Las Meninas row, whose sidecars
    record no `dimensions_px` at all.
    """
    gate = crop_gate(
        meta(variants=[{"rel_path": "works/x/master.jpg", "role": "portrait-crop"}]), meta()
    )
    assert not gate.ok and gate.measured
    assert not gate.overridable


def test_one_sided_dimensions_still_get_a_verdict() -> None:
    gate = crop_gate(meta(pixels=[16875, 30000]), meta())
    assert gate.measured, "one side measurable is still evidence"
