"""Two guards on the work-QID resolver, both found by the 2026-08-09 archive audit.

1. DERIVED ITEMS HAVE NO IDENTITY OF THEIR OWN.
   The schema invariant is `derived_from set => stable_identifiers.wikidata_q is
   null`, and `audit_checks.derived_identity` reports any violation as BROKEN.
   The resolver had no concept of derived items at all (`grep derived_from`
   returned nothing), so it stamped a work Q-ID onto detail/capture sidecars.
   That is worse than one wrong field: it OSCILLATES. The resolver sets the
   Q-ID, the invariant repair clears it, the next run sets it again —
   `8d8f6ab-the-birth-of-venus-botticelli` flipped five times in 70 minutes,
   with three different actors taking turns in operations.log.

2. A MIRROR THAT CANNOT BE WRITTEN MUST NOT BE SILENT.
   `_write_existing_mirrors` returns [] when `art_works_root` is None, and that
   root defaults to `_env_path("FAA_ART_WORKS_ROOT")`. With the variable unset
   the run wrote staging only, reported success, and left the canonical archive
   stale. Measured: 49 of 926 identity operations wrote a mirror without the
   variable, against 760 of 761 with it — and by the time anyone looked, 142
   works had two sidecars that disagreed about which painting they were.
   Staging-only is a legitimate mode; being staging-only by ACCIDENT is not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.resolve_work_qids import _eligible, _is_derived, backfill, main


class FakeJson:
    def __init__(self, hits: list[str]) -> None:
        self._hits = hits

    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return {"search": [{"id": q} for q in self._hits]}


class FakeSparql:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def query(self, sparql: str) -> dict[str, Any]:
        return {"results": {"bindings": self._rows}}


def _write(tmp: Path, meta: dict[str, Any]) -> Path:
    p = tmp / meta["work_id"] / "meta.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta), encoding="utf-8")
    return p


class TestDerivedItemsAreSkipped:
    def test_is_derived_detects_detail_and_capture(self) -> None:
        assert _is_derived({"derived_from": {"work_id": "parent", "kind": "capture"}})
        assert _is_derived({"derived_from": {"work_id": "parent", "kind": "detail"}})
        assert not _is_derived({})
        assert not _is_derived({"derived_from": None})

    def test_derived_item_is_never_eligible(self) -> None:
        """Even with nothing resolved and no retirement ledger, it is skipped."""
        meta = {
            "work_id": "8d8f6ab-x",
            "title": "The birth of Venus",
            "artist": {"name": "Botticelli"},
            "derived_from": {"work_id": "c496d47-x", "kind": "capture"},
        }
        assert _eligible(meta) is False

    def test_backfill_leaves_a_derived_sidecar_untouched(self, tmp_path: Path) -> None:
        """The regression itself: a resolvable derived item must gain no Q-ID."""
        _write(tmp_path, {
            "work_id": "8d8f6ab-x",
            "title": "The birth of Venus",
            "artist": {"name": "Botticelli", "wikidata_q": "Q5669"},
            "derived_from": {"work_id": "c496d47-x", "kind": "capture"},
        })
        # A search that WOULD have matched, so the skip is what stops it.
        stats, outcomes = backfill(
            tmp_path, sparql=FakeSparql(), json_client=FakeJson(["Q151047"]),
            apply=True, retire=True)

        after = json.loads((tmp_path / "8d8f6ab-x" / "meta.json").read_text())
        assert (after.get("stable_identifiers") or {}).get("wikidata_q") is None
        assert "field_provenance" not in after, "a derived item is not 'retired' either"
        assert stats.attempted == 0
        assert outcomes["skipped:derived-item"] == 1

    def test_a_normal_work_is_still_processed(self, tmp_path: Path) -> None:
        """The guard must not swallow ordinary works."""
        _write(tmp_path, {"work_id": "1111111-x", "artist": {"name": "Unknown"},
                          "title": "Obscure"})
        stats, outcomes = backfill(
            tmp_path, sparql=FakeSparql(), json_client=FakeJson([]),
            apply=True, retire=True)
        assert stats.attempted == 1
        assert outcomes["skipped:derived-item"] == 0


class TestApplyRefusesToMirrorSilently:
    def test_apply_without_a_root_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FAA_ART_WORKS_ROOT", raising=False)
        with pytest.raises(SystemExit) as e:
            main(["--apply", "--staging-dir", str(tmp_path)])
        assert e.value.code != 0

    def test_no_mirror_makes_staging_only_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Staging-only stays available — it just has to be asked for."""
        monkeypatch.delenv("FAA_ART_WORKS_ROOT", raising=False)
        _write(tmp_path, {"work_id": "1111111-x", "artist": {"name": "Unknown"},
                          "title": "Obscure"})
        assert main(["--apply", "--no-mirror", "--staging-dir", str(tmp_path)]) == 0

    def test_dry_run_needs_no_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing is written, so nothing can go stale."""
        monkeypatch.delenv("FAA_ART_WORKS_ROOT", raising=False)
        assert main(["--staging-dir", str(tmp_path)]) == 0

    def test_explicit_root_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FAA_ART_WORKS_ROOT", raising=False)
        staging = tmp_path / "staging"
        staging.mkdir()
        assert main(["--apply", "--staging-dir", str(staging),
                     "--art-works-root", str(tmp_path / "works")]) == 0
