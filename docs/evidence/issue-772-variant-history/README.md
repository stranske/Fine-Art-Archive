# Variant-upgrade review history: issue #772

This test-only chunk targets `api/main.py::variant_upgrades` at base `028004f767a60aa1b099b8b218cfbf194a5a2986`.
The broad coverage initiative remains open below 90%. No production file, live archive,
external service, workflow or permission grant is changed.

## Selection and isolation

The current 500-source-commit history window ranks modules by a clearly named
repair-history subject-keyword proxy (`fix|bug|correct|repair|guard|regression`),
then churn, uncovered lines, uncovered branches and path. This proxy is not a
claim that every matching commit was an escaped defect. [ranking.json](ranking.json)
records the complete ordering: `api/main.py` is first (22 repair matches, 51 churn
commits). Its variant listing lacked 10 lines and 6 branches, including the whole
decision-log replay. Prior variant identity/dimension UI fixes are documented in
`tests/test_variant_upgrade_labels_and_dims.py`. This chunk checks history binding
through the real HTTP API using temporary CSVs, append logs and actual PNGs;
only input locations are patched, with no mocked production decision logic.

## Identical-scope measurements

The literal command in each checkout state was:

```text
/Users/teacher/.codex/automations/pd-workloop-resume/worktrees/Fine-Art-Archive-772-coverage/.venv/bin/python -m pytest -q --cov=src --cov-report=json:<stage>-coverage.json --junitxml=<stage>.xml
```

[matched-pair.json](matched-pair.json) retains full absolute argv/cwd, counts,
zero exit statuses, coverage totals and function coverage. Console, JUnit and
coverage JSON are retained losslessly; [compressed-manifest.json](compressed-manifest.json)
records compressed/decoded SHA256 and decoded byte length. Decode with Python
`gzip.decompress(Path(file).read_bytes())` or `gzip -dc <file>`.

| Full suite | Baseline | Candidate |
| --- | ---: | ---: |
| JUnit total | 2178 | 2184 |
| Passed | 2166 | 2172 |
| Skipped | 12 | 12 |
| Failures / errors | 0 / 0 | 0 / 0 |
| Combined line and branch coverage | 88.27420761849375% | 88.39052050014539% |
| Statements / branches | 10170 / 3586 | 10170 / 3586 |
| Covered lines / branches | 9242 / 2901 | 9252 / 2907 |

Identical source-file universe; no per-file covered-line or covered-branch
regression. `variant_upgrades` advances from 18/28 lines and 4/10 branches to
28/28 lines and 10/10 branches. Both suites retain the same two deprecation
warnings. Python 3.12, no execution shim; hosted CI remains a separate gate.

## Actual source-mutation proof

The retained [mutation harness](mutation-harness.txt) changes only the real
`variant_upgrades` body, launches each named pytest node, restores the original
bytes in `finally`, then launches that node again. Test bytes stay fixed.
[mutations.json](mutations.json) records exact replacements, full commands,
per-case outcomes and source/test hashes. All six unique new parameterized cases
fail under a real mutation; eight controls produce 14 failed case executions.
Every RED command exits 1 and every restored GREEN command exits 0.
This proves source sensitivity, not historical absence of existing behavior.

| Source mutation | Named test (prefix `tests/test_api_variant_review_history.py::`) | Failed cases |
| --- | --- | ---: |
| absent-detector-shape | test_absent_detector_does_not_surface_unmatched_decisions | 1 |
| invent-unreviewed-decision | test_unreviewed_candidates_have_no_decision_and_real_dimensions | 1 |
| retain-first-decision | test_latest_decisions_are_keyed_by_work_and_ignore_log_noise | 3 |
| crosswire-work-history | test_latest_decisions_are_keyed_by_work_and_ignore_log_noise | 3 |
| discard-decision-timestamp | test_latest_decisions_are_keyed_by_work_and_ignore_log_noise | 3 |
| stop-on-blank-line | test_latest_decisions_are_keyed_by_work_and_ignore_log_noise | 1 |
| abort-malformed-line | test_latest_decisions_are_keyed_by_work_and_ignore_log_noise | 1 |
| abort-invalid-identity | test_invalid_detector_identity_is_unavailable_without_hiding_valid_rows | 1 |

Whole-repository Black passes (344 files), touched Ruff passes and `git diff --check`
passes. Production `src/` is byte-identical to the base. Keepalive owns current-head
hosted CI and review; closer owns full expected checks, active threads, unchanged
head and seven-minute review floor before merge and `verify:compare`. This partial
chunk does not close #772 or relabel earlier provider NON_PASS outcomes.
