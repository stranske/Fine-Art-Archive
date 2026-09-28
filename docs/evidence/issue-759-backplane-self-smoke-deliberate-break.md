# Issue #759 backplane self-smoke deliberate-break evidence

This transcript closes the evidence gap identified in issue #759 for the
acceptance criterion from issue #738 and merged PR #756. The production and
test implementation were not changed.

## Environment

- Base: `origin/main` at `9adffadee0e8f50e49418aa7aa30322b8748e348`
- Python environment: the repository lock resolved by `uv run --frozen`
- Named gate:

  ```console
  uv run --frozen pytest tests/test_validate_run_contract_self_smoke.py -q -o addopts=
  ```

The pre-existing canonical checkout environment was not used because its
`attrs`/`attr` installation raised `ImportError: cannot import name 'NOTHING'
from 'attr'`. The locked environment above is the reproducible repository
environment and passed before the deliberate break.

## Baseline PASS

```console
$ uv run --frozen pytest tests/test_validate_run_contract_self_smoke.py -q -o addopts=
.                                                                        [100%]
1 passed in 0.54s
```

## Deliberate break: remove `valid_run.json`

The fixture was moved to a non-JSON holding name so it was absent from the
self-smoke fixture set without altering its contents:

```console
$ mv tests/fixtures/backplane/valid_run.json \
    tests/fixtures/backplane/valid_run.json.deliberate-break
$ uv run --frozen pytest tests/test_validate_run_contract_self_smoke.py -q -o addopts=
F                                                                        [100%]
=================================== FAILURES ===================================
____________________ test_validate_run_contract_self_smoke _____________________

>       assert observed == EXPECTED_FIXTURES, output
E       AssertionError: PASS schema loads + valid Draft202012: artifact-manifest-v1.schema.json
E         PASS schema loads + valid Draft202012: capability-bundle-v1.schema.json
E         PASS schema loads + valid Draft202012: document-mirror-v1.schema.json
E         PASS schema loads + valid Draft202012: evidence-object-v1.schema.json
E         PASS schema loads + valid Draft202012: mosaic-core-v1.schema.json
E         PASS schema loads + valid Draft202012: output-substrate-v1.schema.json
E         PASS schema loads + valid Draft202012: run-contract-v1.schema.json
E         PASS schema loads + valid Draft202012: tracked-variable-v1.schema.json
E         PASS fixture missing_cost.json: expected reject, got reject
E         PASS fixture unsafe_rows_inline.json: expected reject, got reject
E         PASS fixture unsafe_prompt_inline.json: expected reject, got reject
E         PASS fixture artifact_not_in_manifest.json: expected reject, got reject
E         PASS fixture bad_identity_ref.json: expected reject, got reject
E
E       assert {'artifact_no..._inline.json'} == {'artifact_no...lid_run.json'}
E
E         Extra items in the right set:
E         'valid_run.json'

tests/test_validate_run_contract_self_smoke.py:45: AssertionError
=========================== short test summary info ============================
FAILED tests/test_validate_run_contract_self_smoke.py::test_validate_run_contract_self_smoke
1 failed in 0.57s
```

The command exited `1`. The failure is the intended gate: schema-only and
negative-fixture success cannot hide the missing positive fixture.

## Exact restoration PASS

```console
$ mv tests/fixtures/backplane/valid_run.json.deliberate-break \
    tests/fixtures/backplane/valid_run.json
$ uv run --frozen pytest tests/test_validate_run_contract_self_smoke.py -q -o addopts=
.                                                                        [100%]
1 passed in 0.50s
```

Cleanup proof immediately after restoration:

```console
$ git status -sb
## codex/issue-759-backplane-deliberate-break...origin/main
```

The deliberate break left no source or fixture change behind.
