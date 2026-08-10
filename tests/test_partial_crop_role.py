"""A work too wide for any panel needs SEVERAL crops, and none of them is waste.

Tintoretto's *The Miracle of the Loaves and Fishes* (Metropolitan Museum, inv.
13.75) is **154.9 x 407.7 cm** — aspect 2.63. No 16:9 panel can hold it: fitting
the whole width leaves the figures too small to read, so the sensible answer is
two complementary crops, one from each end, which between them show what one
crop cannot.

The existing `files.variants[].role` vocabulary could not express that. Every
value assumed ONE crop per master (`landscape-crop`, `portrait-crop`,
`meural-framed`) or an outright redundancy (`duplicate-copy`). With no way to
say "these two are complementary", the pair reads as a duplicate to every
analysis that looks at it — which is exactly how it surfaced: as a candidate for
deletion.

`partial-crop` plus `crop_position` says it directly. This will recur: it is a
property of the work's proportions against the panel's, not a one-off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fine_art_archive import sidecar

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[1] / "schemas" / "meta.schema.json").read_text(
        encoding="utf-8"
    )
)
VARIANT = SCHEMA["properties"]["files"]["properties"]["variants"]["items"]


def _meta(variants: list[dict]) -> dict:
    return {
        "work_id": "abc1234-the-miracle-of-the-loaves-tintoretto",
        "schema_version": "1.0",
        "artist": {"name": "Jacopo Tintoretto"},
        "title": "The Miracle of the Loaves and Fishes",
        "files": {
            "master": {
                "filename": "master.jpg",
                "sha256": "a" * 64,
                "size_bytes": 1234,
                "ingested_at": "2026-08-09T00:00:00+00:00",
            },
            "variants": variants,
        },
        "history": [{"ts": "2026-08-09T00:00:00+00:00", "actor": "test", "op": "test"}],
    }


def _variant(role: str, position: str | None = None) -> dict:
    v = {
        "filename": "master.jpeg",
        "rel_path": "works/xyz/master.jpeg",
        "role": role,
        "sha256": "b" * 64,
        "size_bytes": 999,
    }
    if position is not None:
        v["crop_position"] = position
    return v


class TestTheVocabularyCanExpressIt:
    def test_partial_crop_is_an_allowed_role(self) -> None:
        assert "partial-crop" in VARIANT["properties"]["role"]["enum"]

    def test_it_is_distinct_from_duplicate_copy(self) -> None:
        """The distinction that stops the pair being deleted as waste."""
        enum = VARIANT["properties"]["role"]["enum"]
        assert "duplicate-copy" in enum and "partial-crop" in enum

    def test_crop_position_exists_and_is_constrained(self) -> None:
        pos = VARIANT["properties"]["crop_position"]
        assert set(pos["enum"]) == {
            "left",
            "centre",
            "center",
            "right",
            "top",
            "middle",
            "bottom",
            None,
        }

    def test_the_role_description_explains_complementarity(self) -> None:
        """A future reader must not have to guess why two crops are both kept."""
        desc = VARIANT["properties"]["role"]["description"]
        assert "complementary" in desc
        assert "none is redundant" in desc


class TestItValidates:
    def test_two_complementary_crops_validate(self) -> None:
        meta = _meta([_variant("partial-crop", "left"), _variant("partial-crop", "right")])
        assert sidecar.is_valid(meta) is True

    def test_a_crop_position_is_optional(self) -> None:
        assert sidecar.is_valid(_meta([_variant("partial-crop")])) is True

    @pytest.mark.parametrize(
        "position",
        ["left", "centre", "center", "right", "top", "middle", "bottom"],
    )
    def test_every_supported_crop_position_validates(self, position: str) -> None:
        assert sidecar.is_valid(_meta([_variant("partial-crop", position)])) is True

    def test_an_invented_position_is_refused(self) -> None:
        assert sidecar.is_valid(_meta([_variant("partial-crop", "north-by-northwest")])) is False

    def test_an_invented_role_is_still_refused(self) -> None:
        """Adding one value must not open the enum up."""
        assert sidecar.is_valid(_meta([_variant("some-new-role")])) is False

    @pytest.mark.parametrize("role", ["landscape-crop", "portrait-crop", "duplicate-copy"])
    def test_the_existing_roles_are_untouched(self, role: str) -> None:
        assert sidecar.is_valid(_meta([_variant(role)])) is True
