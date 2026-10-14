# Manifest ID drift proof — issue #790

`GET /healthz` compares the real manifest's work IDs with sidecar directory names.
Equal counts with different IDs are unhealthy. `manifest_missing` names directories
absent from the manifest; `manifest_extra` names manifest IDs absent from the tree.
Sorted lists contain at most 50 IDs and their `_count` fields retain full totals.
Unreadable trees report null comparisons. Numeric `manifest_drift`, the existing
empty-manifest fresh-checkout allowance, and non-gating decision-file reports remain.
This detects ID membership, not changes to titles or other sidecar fields.

## Validation

- `python -m pytest tests/test_healthz_manifest_drift.py tests/test_companion_app_api.py tests/test_build_manifest.py -q -o addopts=`: **97 passed, zero skipped** (`focused.log`, `focused.xml`).
- `python -m pytest -q`: **2236 passed, 12 skipped, 88.88% coverage** (`full-suite.log`, `full-suite.xml`). Existing opt-in live audits, external acquisition workspace, sample-master and calibration fixtures account for skips; the existing Starlette/httpx deprecation warning remains. The result exceeds the hosted 81% coverage floor.
- Ruff on source/tests/replays, repository Black (350 Python files), focused mypy on the changed API module, and `git diff --check` pass.
- Tests and subprocesses use the existing locked dev environment; `uv.lock` is identical to the environment's originating worktree. Reproduce in a fresh tree with `uv run --locked --extra dev` before each Python command.

All new endpoint regressions use real temporary CSV and directory files and the
production FastAPI endpoint/manifest loader. No ID-list, filesystem-reader or
manifest-loader stubs. The builder test runs the real `scripts/build_manifest.py`
with explicit temporary inputs and output, then reads the same endpoint to exercise
the real loader cache. Tests cover equal-count replacement, missing/extra direction,
ordering and bounds with 73 mismatches, unknown trees and non-directory files; prior
fresh-checkout and empty-populated-tree regressions still pass.

## Falsifiability

Run `python docs/evidence/manifest-id-drift/mutation.py` from the repository root.

1. Final tests on immutable original API source `30e1006a9c35e9b7e628ad53b8e62deb2a404212`: **3 failed** because equal-count mismatches incorrectly report healthy (`original-red.*`).
2. Remove only the membership condition from the corrected production health predicate: **3 failed** (`count-only-red.*`).
3. Restore identical production bytes in `finally`: **3 passed** (`restored-green.*`).

The receipt binds source, mutated source, restored source and final tests by SHA256.
The full suite ran on those same production/test bytes. `manifest.json` also binds
all proof files and the final replay scripts. Only machine-local path and JUnit
hostname metadata are redacted; assertions, outcomes and tracebacks are retained.

## Real HTTP and producer smoke

Run `PYTHONPATH=src python docs/evidence/manifest-id-drift/smoke.py`.
`smoke.json` captures the actual HTTP 200 bodies: three rows and three directories
start with missing `work-b` / extra `retired`, `manifest_drift: 0` and `ok: false`;
the real builder exits 0 and the next HTTP response has empty differences and
`ok: true`. This uses only temporary synthetic data. No operational archive,
deployment, hardware fidelity or provider acceptance is claimed. Hosted CI and
post-merge comparison remain pending.
