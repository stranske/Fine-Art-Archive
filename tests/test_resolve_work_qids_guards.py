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

import jsonschema
import pytest
from scripts.resolve_work_qids import (
    SEARCH_PLAN_VERSION,
    _adjudicated,
    _eligible,
    _is_derived,
    backfill,
    main,
)

from fine_art_archive import sidecar
from tests.test_work_qid_search import FakeJson as SearchJson
from tests.test_work_qid_search import FakeSparqlDetails, _detail_row
from tests.test_work_qid_search import _write as search_write


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


def _valid(work_id: str, **extra: Any) -> dict[str, Any]:
    """A sidecar that PASSES schemas/meta.schema.json.

    The resolver validates before writing and skips anything invalid
    (`skipped-invalid-sidecar`), so a fixture missing required fields never
    reaches the write-and-mirror path — and a test asserting "no mirror was
    written" over one passes for the wrong reason, whether or not the code is
    correct. Any test about writing must start from a valid sidecar.
    """
    meta: dict[str, Any] = {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": "Unknown"},
        "title": "Obscure",
        "files": {"master": {"filename": "master.jpeg", "sha256": "0" * 64,
                             "size_bytes": 1,
                             "ingested_at": "2026-01-01T00:00:00+00:00"}},
        "history": [{"actor": "test", "op": "created",
                     "ts": "2026-01-01T00:00:00+00:00"}],
    }
    meta.update(extra)
    return meta


class TestDerivedItemsAreSkipped:
    def test_derived_item_requires_an_explicit_null_work_qid(self) -> None:
        derived = _valid(
            "8d8f6ab-x",
            derived_from={"work_id": "c496d47-x", "kind": "capture"},
        )
        assert sidecar.is_valid(derived) is False

        derived["stable_identifiers"] = {}
        assert sidecar.is_valid(derived) is False

        derived["stable_identifiers"] = {"wikidata_q": "Q151047"}
        assert sidecar.is_valid(derived) is False

        derived["stable_identifiers"] = {"wikidata_q": None}
        assert sidecar.is_valid(derived) is True

    @pytest.mark.parametrize("explicit_null", [False, True], ids=["absent", "null"])
    def test_non_derived_items_may_keep_a_work_qid(self, explicit_null: bool) -> None:
        meta = _valid(
            "8d8f6ab-x",
            stable_identifiers={"wikidata_q": "Q151047"},
        )
        if explicit_null:
            meta["derived_from"] = None
        assert sidecar.is_valid(meta) is True

    @pytest.mark.parametrize(
        "stable_identifiers",
        [None, {}, {"wikidata_q": "Q151047"}],
        ids=["missing", "empty", "non-null-qid"],
    )
    def test_sidecar_write_rejects_invalid_derived_identity(
        self, tmp_path: Path, stable_identifiers: dict[str, str] | None
    ) -> None:
        meta = _valid(
            "8d8f6ab-x",
            derived_from={"work_id": "c496d47-x", "kind": "capture"},
        )
        if stable_identifiers is not None:
            meta["stable_identifiers"] = stable_identifiers

        path = tmp_path / "invalid-derived.json"
        with pytest.raises(jsonschema.ValidationError):
            sidecar.write(path, meta)
        assert path.exists() is False

    def test_sidecar_write_accepts_valid_derived_identity(self, tmp_path: Path) -> None:
        meta = _valid(
            "8d8f6ab-x",
            derived_from={"work_id": "c496d47-x", "kind": "capture"},
            stable_identifiers={"wikidata_q": None},
        )
        path = tmp_path / "valid-derived.json"
        sidecar.write(path, meta)
        assert sidecar.load(path) == meta

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


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch):
    """Stop main() from constructing the real network clients.

    `main` builds `SparqlClient()` and `JsonClient(timeout=15.0)` itself, so a
    test that feeds it real work data would query Wikidata — non-deterministic,
    and rude. Every other test in this suite injects fakes through `backfill`;
    the main()-level tests need them patched at the module instead.
    """
    import scripts.resolve_work_qids as mod
    monkeypatch.setattr(mod, "SparqlClient", lambda *a, **k: FakeSparql())
    monkeypatch.setattr(mod, "JsonClient", lambda *a, **k: FakeJson([]))


class TestApplyRefusesToMirrorSilently:
    def test_apply_without_a_root_is_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FAA_ART_WORKS_ROOT", raising=False)
        with pytest.raises(SystemExit) as e:
            main(["--apply", "--staging-dir", str(tmp_path)])
        assert e.value.code != 0

    def test_no_mirror_makes_staging_only_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline
    ) -> None:
        """Staging-only stays available — it just has to be asked for."""
        monkeypatch.delenv("FAA_ART_WORKS_ROOT", raising=False)
        staging = tmp_path / "staging"
        _write(staging, {"work_id": "1111111-x", "artist": {"name": "Unknown"},
                         "title": "Obscure"})
        assert main(["--apply", "--no-mirror", "--staging-dir", str(staging)]) == 0

    def test_no_mirror_suppresses_writes_to_a_configured_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline
    ) -> None:
        """The flag must suppress mirroring, not merely silence the guard.

        Bypassing only the missing-root error would leave `--no-mirror` writing
        the very mirrors its help text promises to skip whenever
        FAA_ART_WORKS_ROOT happens to be set — the same class of silent
        mismatch between claim and behaviour this PR exists to remove.
        """
        staging = tmp_path / "staging"
        works = tmp_path / "works"
        _write(staging, _valid("1111111-x"))
        mirror = works / "1111111-x" / "meta.json"
        mirror.parent.mkdir(parents=True)
        sentinel = _valid("1111111-x", title="UNTOUCHED")
        mirror.write_text(json.dumps(sentinel), encoding="utf-8")
        monkeypatch.setenv("FAA_ART_WORKS_ROOT", str(works))

        assert main(["--apply", "--retire", "--no-mirror",
                     "--staging-dir", str(staging)]) == 0

        # The staging copy MUST have been retired, proving the run reached the
        # write path; only then does an untouched mirror mean anything.
        staged = json.loads((staging / "1111111-x" / "meta.json").read_text())
        assert "work_qid" in (staged.get("field_provenance") or {})
        assert json.loads(mirror.read_text()) == sentinel

    def test_dry_run_needs_no_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline
    ) -> None:
        """Nothing is written, so nothing can go stale."""
        monkeypatch.delenv("FAA_ART_WORKS_ROOT", raising=False)
        assert main(["--staging-dir", str(tmp_path)]) == 0

    def test_explicit_root_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline
    ) -> None:
        monkeypatch.delenv("FAA_ART_WORKS_ROOT", raising=False)
        staging = tmp_path / "staging"
        staging.mkdir()
        assert main(["--apply", "--staging-dir", str(staging),
                     "--art-works-root", str(tmp_path / "works")]) == 0


class TestVariantHoldingsAreSkipped:
    """3. A HOLDING OF A WORK IS NOT A WORK.

    The same rule as guard 1, one field over. The schema states the invariant
    over `derived_from` and enforces it in its own `allOf`; it cannot enforce it
    over `files.variants[]`, because that entry lives in the OWNER's sidecar and
    says nothing inside the holding's. So nothing stopped this resolver from
    filling in a crop, and it kept restoring the identity the crop repair had
    just cleared — a dry run on 2026-08-11 proposed Q185372, Q1091086 and
    Q151047 back onto the Girl with a Pearl Earring, Third of May and Birth of
    Venus crops minutes after they were cleared. The match was not wrong; a crop
    of a work IS that work. What was missing was the statement that the crop's
    sidecar is a second holding rather than a second painting.
    """

    QID = "Q185372"

    def _clients(self) -> tuple[SearchJson, FakeSparqlDetails]:
        """A search that WOULD resolve either sidecar, so the skip is what stops it."""
        return SearchJson([self.QID]), FakeSparqlDetails(
            [_detail_row(self.QID, "Girl with a Pearl Earring", artwork=True,
                         creators=[], inception="1665")]
        )

    def _sidecar(self, work_id: str, *, variants: list[str] = ()) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "work_id": work_id,
            "artist": {"name": "Johannes Vermeer"},
            "title": "Girl with a Pearl Earring",
            "year": "1665",
        }
        if variants:
            meta["files"] = {
                "master": {"filename": "m.jpeg", "sha256": "a" * 64, "size_bytes": 1,
                           "ingested_at": "2026-05-16T21:30:00Z"},
                "variants": [{"rel_path": f"works/{v}/m.jpeg", "role": "landscape-crop"}
                             for v in variants],
            }
        return meta

    def test_the_holding_gains_no_q_id_and_the_owner_takes_it(self, tmp_path: Path) -> None:
        """The regression itself: the crop must stay QID-less, the owner resolve."""
        search_write(tmp_path, self._sidecar("aaaaaaa-crop"))
        search_write(tmp_path, self._sidecar("bbbbbbb-master", variants=["aaaaaaa-crop"]))
        json_c, sparql = self._clients()

        stats, outcomes = backfill(
            tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=True)

        crop = json.loads((tmp_path / "aaaaaaa-crop" / "meta.json").read_text())
        owner = json.loads((tmp_path / "bbbbbbb-master" / "meta.json").read_text())
        assert (crop.get("stable_identifiers") or {}).get("wikidata_q") is None
        assert "field_provenance" not in crop, "a holding is not 'retired' either"
        assert owner["stable_identifiers"]["wikidata_q"] == self.QID
        assert outcomes["skipped:variant-holding"] == 1
        assert stats.attempted == 1 and stats.resolved == 1

    def test_neither_side_of_a_mutual_pair_is_resolved(self, tmp_path: Path) -> None:
        """Whoever wrote the entry does not settle which file is the crop."""
        search_write(tmp_path, self._sidecar("aaaaaaa-crop", variants=["bbbbbbb-master"]))
        search_write(tmp_path, self._sidecar("bbbbbbb-master", variants=["aaaaaaa-crop"]))
        json_c, sparql = self._clients()

        stats, outcomes = backfill(
            tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=True)

        for work_id in ("aaaaaaa-crop", "bbbbbbb-master"):
            meta = json.loads((tmp_path / work_id / "meta.json").read_text())
            assert (meta.get("stable_identifiers") or {}).get("wikidata_q") is None
        assert outcomes["skipped:variant-link-ambiguous"] == 2
        assert stats.attempted == 0

    def test_a_work_whose_variant_lives_outside_works_is_untouched(self, tmp_path: Path) -> None:
        """A file beside the master is not another sidecar, so nothing is held."""
        meta = self._sidecar("bbbbbbb-master")
        meta["files"] = {
            "master": {"filename": "m.jpeg", "sha256": "a" * 64, "size_bytes": 1,
                       "ingested_at": "2026-05-16T21:30:00Z"},
            "variants": [{"rel_path": "renders/eink/bbbbbbb-master.png", "role": "eink-render"}],
        }
        search_write(tmp_path, meta)
        json_c, sparql = self._clients()

        stats, outcomes = backfill(
            tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=True)

        assert stats.resolved == 1
        assert not [key for key in outcomes if key.startswith("skipped:variant")]


class TestAPlanBumpDoesNotOverturnDecisions:
    """4. A DECISION IS NOT RE-LITIGATED BY A SEARCH.

    `_retired_plan_version` reads a retirement whose `source_ref` carries no
    plan version as version 0, so raising SEARCH_PLAN_VERSION re-opens it. That
    is right for a work the search gave up on and wrong for a work some pass
    DECIDED about. The archive holds 101 of the latter — 72 `faa:identity-anchor`
    and 29 `duplicate-adjudication`, the second group cleared on evidence that
    item dimensions and the P18 image put the work on another sidecar. Searching
    them again proposes the same Q-ID straight back, so without this guard the
    v5 bump would silently overturn every one of them.
    """

    def _retired(self, source: str, source_ref: str) -> dict[str, Any]:
        meta = _valid("aaaaaaa-x", artist={"name": "Cezanne", "wikidata_q": "Q35548"})
        meta["field_provenance"] = {
            "work_qid": {
                "status": "not_available",
                "source": source,
                "source_ref": source_ref,
                "recorded_at": "2026-08-01T00:00:00+00:00",
            }
        }
        return meta

    def test_a_decision_without_a_plan_version_is_not_re_opened(self) -> None:
        for source in ("faa:identity-anchor", "duplicate-adjudication"):
            meta = self._retired(source, source)
            assert _adjudicated(meta) == source
            assert _eligible(meta) is False, f"{source} must not be re-searched"

    def test_a_search_retirement_at_an_older_plan_is_re_opened(self) -> None:
        meta = self._retired("wikidata", "faa:work-qid-search/v4")
        assert _adjudicated(meta) is None
        assert _eligible(meta) is True

    def test_a_search_retirement_at_the_current_plan_is_left_alone(self) -> None:
        meta = self._retired("wikidata", f"faa:work-qid-search/v{SEARCH_PLAN_VERSION}")
        assert _eligible(meta) is False

    def test_backfill_leaves_an_adjudicated_sidecar_untouched(self, tmp_path: Path) -> None:
        _write(tmp_path, self._retired("faa:identity-anchor", "faa:identity-anchor"))
        before = json.loads((tmp_path / "aaaaaaa-x" / "meta.json").read_text())

        stats, _ = backfill(
            tmp_path, sparql=FakeSparql(), json_client=FakeJson(["Q17277950"]),
            apply=True, retire=True)

        assert json.loads((tmp_path / "aaaaaaa-x" / "meta.json").read_text()) == before
        assert stats.attempted == 0
