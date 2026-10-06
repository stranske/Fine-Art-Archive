# Issue #772: tag-proposal API boundary protection

Baseline main: `eb1ef51fa121329cebc90fcf4acbada464608b83`. One low risk chunk of #772, which stays open; no 90 percent claim.

The first-ranked production module is `src/fine_art_archive/api/main.py`. Its tagger endpoint accepted empty dictionaries as work lists and empty lists as gate objects; other valid JSON shapes raised uncaught attribute errors. The seven new shape cases failed on original source (7 failed / 9 passed). The initial seven-line guard returned HTTP 500 with a controlled invalid-structure detail before using those values, but preserved null/empty defaults. The acceptance follow-up below closes the remaining null-field gap.

## Ranking

Repair-history is a proxy, not a verified escaped-defect count: search the latest 500 main commit subjects for fix/bug/correct/repair/guard/regression, count touched production paths, then order by that count, churn count, and uncovered line mass. Full baseline coverage supplies uncovered mass. No coverage exclusions, floors, marker selections or refactors changed.

| File | Repair-history proxy | Churn | Missing lines |
|---|---:|---:|---:|
| `src/fine_art_archive/api/main.py` | 22 | 47 | 190 |
| `src/fine_art_archive/api/store.py` | 6 | 19 | 21 |
| `src/fine_art_archive/enrichment/source_resolver.py` | 5 | 9 | 95 |
| `src/fine_art_archive/api/gates.py` | 5 | 8 | 63 |
| `src/fine_art_archive/identity/variants.py` | 5 | 7 | 7 |
| `src/fine_art_archive/known_works/artwork_classes.py` | 4 | 4 | 18 |

## Executed gates

Same baseline and candidate command: `.venv/bin/python -m pytest -q -n 4 --cov=src --cov-report=json:<evidence-path> --cov-report=term`. Both run all default tests from a linked checkout with an isolated Python3.12 environment, not the operator archive. No model, external image service, production archive mutation or tagger subprocess was run by the new HTTP tests; the subprocess boundary returns controlled responses.

| Metric | Baseline | Candidate |
|---|---:|---:|
| covered_lines | 9189 | 9213 |
| num_statements | 10164 | 10166 |
| covered_branches | 2882 | 2888 |
| num_branches | 3582 | 3584 |
| missing_lines | 975 | 953 |
| missing_branches | 700 | 696 |
| percent_covered | 87.81463698530482 | 88.00727272727272 |
| api/main.py covered_lines | 1225 | 1249 |
| api/main.py missing_lines | 190 | 168 |
| api/main.py covered_branches | 304 | 310 |
| api/main.py missing_branches | 84 | 80 |
| api/main.py percent_covered | 84.80310593455353 | 86.27559490868843 |

Baseline: **2083 passed,12 skipped**. Candidate: **2099 passed,12 skipped**. Adjacent endpoint/security/subject-state gate: **141 passed**. Black whole checkout339files, touched Ruff, touched-source mypy, and git diff check passed. Coverage is combined line+branch, matching the repo configuration; baseline statement-only coverage90.41percent is not the combined metric. CI and external tagger runtime remain receiving-lane checks.

## Actual mutation proof

Each listed test function (all parameterized cases included) was run against its targeted real mutation and returned exit1 with the named failing node. Source was restored byte for byte after every mutation. Final new-module gate returned exit0 with16passed. Full console evidence is in [issue-772-tag-proposal-mutations.txt](issue-772-tag-proposal-mutations.txt).

| Mutation | Named test in tests/test_api_tag_proposals.py | RED exit |
|---|---|---:|
| work-id | `test_invalid_work_id_never_launches_tagger` | 1 |
| missing-script | `test_missing_script_reports_unavailable_without_launch` | 1 |
| timeout | `test_timeout_is_a_gateway_timeout` | 1 |
| process-failure | `test_failed_process_reports_only_last_four_error_lines` | 1 |
| final-json | `test_missing_final_json_reports_controlled_error` | 1 |
| json-shape | `test_invalid_json_shape_reports_controlled_error` | 1 |
| success-fields | `test_valid_result_preserves_proposals_and_launch_contract` | 1 |
| empty-defaults | `test_empty_result_uses_explicit_defaults` | 1 |

Restored source SHA256: `55730a0d3151fb87bbe316aa8ba4ca307f73f043397676119fd8236a302f6abc`.

An initial proof attempt was incomplete because same-size, same-second source edits reused timestamp-valid Python bytecode. The corrected harness disables bytecode writes and removes only this source module derived cache before each execution; all eight mutation groups then failed and the restored gate passed. The incomplete attempt is retained in local run evidence and is not counted as proof.

## Acceptance follow-up

- [x] **Bug Fixes**
  - [x] Tag proposals return a controlled HTTP 500 for invalid JSON structures: the response must be an object, any present `works` must be a list of objects, and any present `gate` must be an object.

The initial guard accepted explicit `works: null` and `gate: null`. Field-presence checks now reject both while allowing omitted fields, empty work lists and empty gate objects. Expanded HTTP regressions also cover boolean/numeric envelopes and fields, string gates, and an invalid later work row. Against the initial guard, the expanded module returned **2 failed, 27 passed**: both null cases incorrectly returned HTTP 200. After the fix, the module and adjacent endpoint/security/subject-state gate returned **154 passed**, including all **29 tag-proposal cases**. No broader coverage target is claimed by this follow-up.

Verification used Python 3.14.8 with `pytest tests/test_api_tag_proposals.py tests/test_companion_app_api.py tests/test_companion_app_security.py tests/test_subject_action_state.py -m "not slow" --no-cov -q`. The sandbox denies socketpair sends, preventing asyncio thread wakeups; a temporary verification-only selector polling shim let the unchanged HTTP tests execute. It was kept outside the repository and did not change application behavior or assertions.

Whole-repository Black check passed for **339 files** (line length 100, the required exclusions, one worker and the same polling shim). Touched-file Ruff, source-module mypy and `git diff --check` passed. GitHub API access was unavailable, so remote checklist updates and PR-state verification remain for the receiving lane.

## Keepalive verification, 2026-10-06

This round's baseline is `3cfc764d12a722dd2a7da8ff2bb821cf36599273` on
`codex/issue-772-identity-coverage`. The earlier main comparison above is historical;
the following comparison measures the source and tests available in this runner.

### Current gap ranking

The repair-history proxy is explicitly **not an escaped-production-defect count**.
The input is the latest 500 commit subjects reachable from the baseline, ending at
`d718d40c575b44443208a24938c6977d076e3931`:
`git log -500 --format='%H%x09%s' 3cfc764d12a722dd2a7da8ff2bb821cf36599273`.
For each commit, `git diff-tree --no-commit-id --name-only -r <sha>` supplies touched
paths. Count each Python production path once per commit for churn, and once for
the repair proxy when the subject matches the case-insensitive expression
`\b(?:fix|bug|correct|repair|guard|regression)`. Keep modules with missing lines or
branches from the full baseline coverage JSON, then sort by descending proxy,
churn, and missing lines, using ascending path for ties. Missing branches are
reported separately. The [complete ranking](issue-772-current-gap-ranking.csv)
contains all **65** modules with measured gaps.

| Rank | File under `src/fine_art_archive/` | Repair-history proxy | Churn | Missing lines | Missing branches |
|---|---|---:|---:|---:|---:|
| 1 | `api/main.py` | 22 | 49 | 168 | 80 |
| 2 | `api/store.py` | 6 | 19 | 20 | 6 |
| 3 | `enrichment/source_resolver.py` | 5 | 9 | 95 | 88 |
| 4 | `api/gates.py` | 5 | 8 | 66 | 45 |
| 5 | `identity/variants.py` | 5 | 7 | 7 | 7 |
| 6 | `known_works/artwork_classes.py` | 4 | 4 | 18 | 14 |

The first-ranked module remains the selected scope. Its `propose_tags` symbol
already measured 100% line and branch coverage, but launching a missing,
non-executable, or otherwise unavailable configured Python process still raised
an uncaught `OSError`. This is a behavioral gap that the aggregate metric cannot
represent. The three new HTTP cases reproduced it on the baseline source:
`python -m pytest tests/test_api_tag_proposals.py::test_launch_failure_reports_tagger_unavailable -m "not slow" --no-cov -q`
returned **exit 1, 3 failed** (`missing-executable`, `permission-denied`, `os-error`).
The two-line fix catches launch `OSError` and returns HTTP 503 with
`{"detail": "tagger could not be started"}`. The tests also require exactly one
launch attempt. The existing timeout case continues to require HTTP 504.

### Identical-scope full-suite comparison

Both executions ran the exact requested command:

```bash
PYTHONPATH=/tmp/issue-772-verification:src PYTEST_ADDOPTS="-m 'not slow'" \
  python -m pytest -q --cov=src --cov-report=json:coverage.json
```

Python **3.14.7**, pytest **9.1.1**, pytest-cov **7.1.0** and the repository's
unchanged combined line+branch coverage configuration were used for both.
`PYTEST_ADDOPTS` applies the required `not slow` selection identically; it
deselected no tests. No coverage exclusions or full-suite coverage floor changed.
The baseline JSON was saved before the candidate overwrote `coverage.json`.

The sandbox denies wakeup socket sends, so the unassisted baseline stalled at
the first HTTP test and was interrupted (exit 130); it is not a completed
measurement. Both completed measurements used the same external
`/tmp/issue-772-verification/sitecustomize.py`: wrap
`selectors.DefaultSelector.select` to call the original selector with
`0.01 if timeout is None else min(timeout, 0.01)`. This permits asyncio to observe
queued callbacks without changing repository source, assertions, or test mocks.

| Metric | Baseline | Candidate |
|---|---:|---:|
| collected | 2124 | 2127 |
| passed | 2108 | 2111 |
| failed | 4 | 4 |
| skipped | 12 | 12 |
| warnings | 1 | 1 |
| exit status | 1 | 1 |
| covered_lines | 9207 | 9209 |
| num_statements | 10166 | 10168 |
| covered_branches | 2880 | 2880 |
| num_branches | 3584 | 3584 |
| missing_lines | 959 | 959 |
| missing_branches | 704 | 704 |
| percent_covered | 87.90545454545455 | 87.90721349621873 |
| api/main.py covered_lines | 1249 | 1251 |
| api/main.py missing_lines | 168 | 168 |
| api/main.py covered_branches | 310 | 310 |
| api/main.py missing_branches | 80 | 80 |
| api/main.py percent_covered | 86.27559490868843 | 86.29076838032061 |
| propose_tags percent_covered | 100 | 100 |

The exact failed-node sets match. All four existing failures are in
`tests/test_workspace_conflict_guard.py`, each raising
`OSError: [Errno 30] Read-only file system: '/home/runner/.cache/fine-art-archive'`:

- `test_automation_lock_path_is_not_on_dropbox_tree`
- `test_automation_lock_path_rejects_configured_dropbox_directory`
- `test_resolve_automation_lock_path_redirects_synced_candidate`
- `test_sidecar_file_lock_redirects_lock_when_sidecar_is_on_dropbox`

These environmental failures remain visible; no existing test was skipped or
disabled to make the comparison pass. There are **no new failures**. A fully
green suite still needs a runner with a writable host-local lock directory.

### Repeated actual source mutation proof

The **32 cases listed in the mutation table below**, including the earlier
expanded-shape and three launch cases, were exercised against real source edits.
The six `test_nested_array_fields_reject_non_arrays` cases added in the closer
source repair have separate actual mutation/restoration receipts in
`issue-772-nested-array-controls.txt` and `.json` (see the final section).
The historical table below covers 32 cases; those receipts cover the remaining six.
Every row ran the following command with its named function node, first mutated
and then restored, using the same polling shim:

```bash
PYTHONPATH=/tmp/issue-772-verification:src PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest tests/test_api_tag_proposals.py::<function> -m "not slow" --no-cov -q
```

| Actual source mutation | Function | Mutated result | Restored result |
|---|---|---|---|
| Replace work-id validation call with `pass` | `test_invalid_work_id_never_launches_tagger` | 1 failed, exit 1 | 1 passed, exit 0 |
| Make missing-script condition false | `test_missing_script_reports_unavailable_without_launch` | 1 failed, exit 1 | 1 passed, exit 0 |
| Change timeout HTTP 504 to 500 | `test_timeout_is_a_gateway_timeout` | 1 failed, exit 1 | 1 passed, exit 0 |
| Remove the new `except OSError` handler | `test_launch_failure_reports_tagger_unavailable` | 3 failed, exit 1 | 3 passed, exit 0 |
| Change failed-process HTTP 500 to 502 | `test_failed_process_reports_only_last_four_error_lines` | 1 failed, exit 1 | 1 passed, exit 0 |
| Change missing-JSON HTTP 500 to 502 | `test_missing_final_json_reports_controlled_error` | 3 failed, exit 1 | 3 passed, exit 0 |
| Remove the complete JSON shape guard | `test_invalid_json_shape_reports_controlled_error` | 17 failed, exit 1 | 17 passed, exit 0 |
| Replace selected work with an empty object | `test_valid_result_preserves_proposals_and_launch_contract` | 1 failed, exit 1 | 1 passed, exit 0 |
| Change default `written` from false to true | `test_empty_result_uses_explicit_defaults` | 4 failed, exit 1 | 4 passed, exit 0 |

The harness retained original bytes and restored them in `finally` after each
mutation. Byte equality was asserted before every restored execution. Only
`api/__pycache__/main.*.pyc` was removed before executions to prevent stale
bytecode. Every restoration had SHA256
`1eadae1e35bb42d6fc6b7ddf3439ebc7c595d38975c725a88257325b03e8eb91`.
[Captured console results](issue-772-tag-proposal-followup-mutations.txt) include
the exact commands, individual failing parameter nodes, counts, statuses, and
restoration hashes.

### Validation and task status

The focused module produced **32 passed**. An initial focused coverage invocation
also inherited the configured `--cov=src`, producing exit 1 despite all tests
passing because the full-src 25% floor was not met by this tiny selection. The
corrected targeted coverage gate removed only the default command arguments,
kept the 25% floor, and covered the specific module:

```bash
PYTHONPATH=/tmp/issue-772-verification:src python -m pytest \
  tests/test_api_tag_proposals.py tests/test_companion_app_api.py \
  tests/test_companion_app_security.py tests/test_subject_action_state.py \
  -o addopts='' -m "not slow" --cov=fine_art_archive.api.main --cov-report=term-missing -q
```

Result: **157 passed, exit 0**, `src/fine_art_archive/api/main.py` **54%** in the
targeted table (**54.06%** combined as printed), with `propose_tags` **100%** in
the final full-suite JSON. No 90% claim is made for this targeted selection.

Black formatted both touched Python files at line length 100. The required
whole-repository command
`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
passed for **339 files**, with `BLACK_NUM_WORKERS=1` and the polling shim because
the sandbox also denies multiprocessing socket binds. Touched-file
`ruff check src/fine_art_archive/api/main.py tests/test_api_tag_proposals.py`,
`mypy src/fine_art_archive/api/main.py`, and `git diff --check` passed.

- [x] Run the current full-src coverage baseline and rank gaps by the named repair-history proxy, churn, then uncovered mass.
- [x] Add focused tests for selected production symbols and minimally fix the reproduced launch defect.
- [x] Deliberately break every tag-proposal case, run its named test, restore exact source bytes, and capture proof here.
- [x] Complete identical-scope baseline/candidate coverage with no new failures, recording exact counts, percentages, ranking, and existing failures.
- [x] Verify each new case fails for its actual source mutation and passes after byte-identical restoration, recording nodes, commands, and exits.
- [x] Apply the conditional 90% criterion: the measured baseline is below 90%, so retain this bounded PR and the broader #772 initiative.

Remote checklist updates and PR readiness could not be checked:
`gh pr view 774 --repo stranske/Fine-Art-Archive --json number,state,isDraft,body`
failed to connect to `api.github.com` (exit 1). This round did not change remote
PR state or close the broader issue.

The primary checkout's `.git` is read-only: staging failed to create
`.git/index.lock`. The five changed files are committed using an isolated local
repository at `/tmp/issue-772-commit-repo`, with the baseline tree as parent and
the primary working files as input. The receiving lane can apply the exported
`/tmp/issue-772-keepalive.patch` to its writable checkout. No commit or push to
the primary checkout or remote is claimed.


2026-10-06 current-head check: `python3.12 -m pytest tests/test_api_tag_proposals.py -q --no-cov` passed all38 tests. The first focused run also passed38 tests but exited1 because this single module reached5.98percent against the package-wide25percent coverage floor. This focused check disables aggregate coverage only for the narrow run; no package-wide coverage PASS is claimed. Prior full-suite host cache limitations remain documented above.


## Exact merged-source nested-array mutation proof (2026-10-06)

The earlier 32-case mutation table is historical. The six additional nested-array
cases now have actual source-mutation proof in
[the full command transcript](issue-772-nested-array-controls.txt) and
[the per-case receipt](issue-772-nested-array-controls.json). This supplies the
previously missing six-case mutation proof.

On main `fb47e2f3e0700fc55ec99f2b4a008692da95fb84`, removing only the production
`proposals` and `gate.tags_enabled` list guards makes all six named cases fail
with HTTP 200 where controlled HTTP 500 is required. Every assertion stays
unchanged. Byte-identical restoration gives six passes; the full tag-proposal
module gives 38 passes. No production or test changes are retained.

| Named parameter case | Production guards removed | Restored |
| --- | --- | --- |
| `invalid-proposals` | FAIL, exit 1 | PASS, exit 0 |
| `invalid-tags_enabled` | FAIL, exit 1 | PASS, exit 0 |
| `invalid1-proposals` | FAIL, exit 1 | PASS, exit 0 |
| `invalid1-tags_enabled` | FAIL, exit 1 | PASS, exit 0 |
| `None-proposals` | FAIL, exit 1 | PASS, exit 0 |
| `None-tags_enabled` | FAIL, exit 1 | PASS, exit 0 |

Production source before and after restoration has SHA256
`d201269355b26f47b20b08a7020de9c277d6ada569e64e93e874a9d0006f93d3`.

Coverage measurements elsewhere in this document are separate historical
baseline/candidate pairs from different environments: the original local
2083→2099/12-skip run and the later sandbox run with four unchanged workspace
conflict failures and its stated `not slow` selection. Their percentages must
be compared within each identical-scope pair, not mixed across environments.
This follow-up changes documentation only and claims no new package coverage
measurement or package-wide PASS. The broader 90% initiative remains open;
current-head hosted checks, review and comparison disposition remain required.
