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

## Current-checkout queue-detail regression protection (2026-10-06)

This is a new, bounded test change on baseline
`100b0e539c69c609dba9d318283b5eec40f77469`, branch
`codex/issue-772-nested-array-mutation-evidence`. All preceding comparisons are
historical and are not inputs to this round's percentages. The baseline was
completed before adding `tests/test_api_queue_details.py`.

### Measured selection

The repair-history proxy counts touched Python production paths once per commit
when the subject matches case-insensitive `\b(?:fix|bug|correct|repair|guard|regression)`.
It is not a verified escaped-defect count. Churn counts all touches in the same
500-commit window. Inputs are
`git log -500 --format='%H%x09%s' 100b0e539c69c609dba9d318283b5eec40f77469`
and `git diff-tree --no-commit-id --name-only -r <sha>` for each commit; the
oldest commit is `d718d40c575b44443208a24938c6977d076e3931`. Retain modules
with missing lines or branches in the new baseline JSON, then sort descending
by repair proxy, churn, missing lines, and ascending path for ties. Missing
branches are reported separately. The [full ranking](issue-772-queue-gap-ranking.csv)
contains all 65 modules with measured gaps.

| Rank | File under `src/fine_art_archive/` | Repair-history proxy | Churn | Missing lines | Missing branches |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | `api/main.py` | 21 | 48 | 168 | 80 |
| 2 | `api/store.py` | 6 | 19 | 20 | 6 |
| 3 | `enrichment/source_resolver.py` | 5 | 9 | 95 | 88 |
| 4 | `api/gates.py` | 5 | 8 | 66 | 45 |
| 5 | `identity/variants.py` | 5 | 7 | 7 | 7 |
| 6 | `known_works/artwork_classes.py` | 4 | 4 | 18 | 14 |

Within the first-ranked module, `get_queue` had only 5/16 lines and 2/8 branches
covered (29.166666666666668% combined). Its eleven missing lines are
`1221, 1223, 1225, 1226, 1227, 1228, 1229, 1233, 1234, 1249, 1250`.
Repair-history context includes `df35046` (Handle corrupt queue JSON consistently,
#228) and `fba402b` (surface autonomous acquisitions, #495). Existing tests
protected corrupt queue files and dynamic ordering but did not exercise valid
queue-detail HTTP responses. This choice protects behavior, rather than adding
tests merely to raise the aggregate metric.

The six new cases use temporary queue files, sidecars and a real ratings log.
Only the acquisition inventory is stubbed for the dynamic queue case. They
require file order, omission of missing works, sidecar metadata,
legacy and two-axis latest-rating badges, counts for the specific work,
dynamic-queue precedence over a stale same-named file, new arrivals on the next
request, empty defaults, and a controlled missing-queue response. All six pass
on the baseline production source; no defect was reproduced, so no production
fix is retained.

### Identical-scope measurement

Both completed full-suite measurements used:

```bash
PYTHONPATH=/tmp/issue-772-verification:src PYTEST_ADDOPTS="-m 'not slow'" \
  python -m pytest -q --cov=src --cov-report=json:coverage.json
```

Python 3.14.7, pytest 9.1.1, pytest-cov 7.1.0 and coverage.py 7.16.2 were
identical. The existing combined line-and-branch configuration, exclusions and
25% floor were unchanged. The required `not slow` selection deselected no tests.
An unassisted initial run stalled at the first HTTP test and was interrupted
(exit 130); it is not counted as a measurement. Both completed runs used the
same external polling shim, shown in full below:

```python
import selectors

_original_select = selectors.DefaultSelector.select


def _poll_select(self, timeout=None):
    return _original_select(self, 0.01 if timeout is None else min(timeout, 0.01))


selectors.DefaultSelector.select = _poll_select
```

This lets asyncio observe queued callbacks when sandbox wakeup socket writes
are denied. The shim is outside the repository and changes no assertions or
application code. Full output is retained in the
[baseline transcript](issue-772-queue-baseline.txt) and
[candidate transcript](issue-772-queue-candidate.txt); exact coverage summaries
and selected-symbol line/branch details are in the
[measurement receipt](issue-772-queue-coverage-summary.json). The complete JSON
artifacts are also saved at `/tmp/issue-772-queue-{baseline,candidate}-coverage.json`.
The tracked historical `coverage.json` was restored after saving those artifacts.
Transcript files trim trailing whitespace and prefix pytest separator lines
with `| ` so Git does not mistake test output for conflict markers. Original
console captures are retained as `/tmp/issue-772-queue-*-raw.txt`.

| Metric | Baseline | Candidate |
| --- | ---: | ---: |
| collected | 2133 | 2139 |
| passed | 2117 | 2123 |
| failed | 4 | 4 |
| skipped | 12 | 12 |
| warnings | 1 | 1 |
| exit status | 1 | 1 |
| covered_lines | 9209 | 9220 |
| num_statements | 10168 | 10168 |
| covered_branches | 2880 | 2886 |
| num_branches | 3584 | 3584 |
| missing_lines | 959 | 948 |
| missing_branches | 704 | 698 |
| percent_covered | 87.90721349621873 | 88.03083187899942 |
| api/main.py covered_lines | 1251 | 1262 |
| api/main.py missing_lines | 168 | 157 |
| api/main.py covered_branches | 310 | 316 |
| api/main.py missing_branches | 80 | 74 |
| api/main.py percent_covered | 86.29076838032061 | 87.23051409618574 |
| get_queue covered lines / statements | 5/16 | 16/16 |
| get_queue covered branches / branches | 2/8 | 8/8 |
| get_queue percent_covered | 29.166666666666668 | 100 |

The failed-node sets were compared and are identical. Each existing failure is
an `OSError: [Errno 30] Read-only file system: '/home/runner/.cache/fine-art-archive'`:

- `tests/test_workspace_conflict_guard.py::test_automation_lock_path_is_not_on_dropbox_tree`
- `tests/test_workspace_conflict_guard.py::test_automation_lock_path_rejects_configured_dropbox_directory`
- `tests/test_workspace_conflict_guard.py::test_resolve_automation_lock_path_redirects_synced_candidate`
- `tests/test_workspace_conflict_guard.py::test_sidecar_file_lock_redirects_lock_when_sidecar_is_on_dropbox`

There are no new failures. This is not a package-wide green claim; the receiving
runner still needs a writable host-local lock directory. Statement-only baseline
coverage is 90.5684500393391%, but the repository's combined baseline metric is
87.90721349621873%, below 90%. Retain this bounded PR and the broader #772
initiative; do not claim completion of the broader 90% goal.

### Actual source-mutation controls

All 17 controls change only the real `get_queue` function. Tests and assertions
remain byte-identical throughout. Every control runs its named node against the
mutation (exit 1 with an assertion failure), restores exact source bytes in a
`finally` block, asserts byte equality, and reruns the same node (exit 0).
Only derived `api/__pycache__/main.*.pyc` files are removed before runs to avoid
timestamp-valid stale bytecode. The [full control transcript](issue-772-queue-controls.txt)
records exact replacements, commands, failing nodes, counts, exit statuses and
restoration hashes; the [per-control receipts](issue-772-queue-controls.json)
record the same nodes and statuses in machine-readable form.

Every execution uses the named node under `tests/test_api_queue_details.py`:

```bash
PYTHONPATH=/tmp/issue-772-verification:src PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest tests/test_api_queue_details.py::<node> -m "not slow" --no-cov -q
```

| Deliberate source break | Named node | RED / restored GREEN |
| --- | --- | --- |
| Sort work IDs instead of preserving file order | `test_file_queue_preserves_work_order_and_skips_missing` | 1 failed / 1 passed |
| Stop at the first missing work | `test_file_queue_preserves_work_order_and_skips_missing` | 1 failed / 1 passed |
| Blank title, artist name, artist QID, or year (four separate controls) | `test_file_queue_preserves_work_order_and_skips_missing` | each 1 failed / 1 passed |
| Force variant count to zero | `test_file_queue_preserves_work_order_and_skips_missing` | 1 failed / 1 passed |
| Drop latest legacy rating | `test_queue_badges_use_latest_event_and_count_all_ratings[legacy]` | 1 failed / 1 passed |
| Drop latest quality or fit (two separate controls) | `test_queue_badges_use_latest_event_and_count_all_ratings[two-axis]` | each 1 failed / 1 passed |
| Force work rating count to zero | `test_queue_badges_use_latest_event_and_count_all_ratings` | 2 failed / 2 passed |
| Bypass dynamic queue lookup | `test_dynamic_queue_uses_current_acquisitions_instead_of_same_named_file` | 1 failed / 1 passed |
| Lose filename name fallback or empty description fallback (two separate controls) | `test_empty_queue_uses_filename_and_default_description` | each 1 failed / 1 passed |
| Count requested IDs instead of readable works | `test_file_queue_preserves_work_order_and_skips_missing` | 1 failed / 1 passed |
| Use the display name as the addressable key | `test_file_queue_preserves_work_order_and_skips_missing` | 1 failed / 1 passed |
| Return HTTP 422 for an unknown queue | `test_unknown_queue_returns_not_found` | 1 failed / 1 passed |

Source before and after every restoration has SHA256
`d201269355b26f47b20b08a7020de9c277d6ada569e64e93e874a9d0006f93d3`.
The final production source was also compared byte for byte with baseline HEAD.

### Validation and verified checklist

The focused six-case gate passed. Targeted measured verification, with the
unchanged 25% floor and explicit module scope, used:

```bash
PYTHONPATH=/tmp/issue-772-verification:src python -m pytest \
  tests/test_api_queue_details.py tests/test_companion_app_api.py \
  tests/test_judgement_surfaces.py -o addopts='' -m "not slow" \
  --cov=fine_art_archive.api.main --cov-report=term-missing \
  --cov-report=json:/tmp/issue-772-queue-targeted-coverage.json -q
```

Result: **107 passed, 1 skipped, exit 0**. The coverage table reports
`src/fine_art_archive/api/main.py` at **50%** (49.53012714206744% combined);
`get_queue` measures **100%** lines and branches in both targeted and full runs.
This targeted selection makes no whole-module 90% claim. The one skip is the
existing external acquisition-workspace purge-contract check (the workspace is
not configured in this runner). Relevant-file Black at line length 100,
the required whole-repository
`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
(340 files, `BLACK_NUM_WORKERS=1` and the polling shim), touched-file Ruff and
`git diff --check` passed. [Validation output](issue-772-queue-validation.txt)
retains the targeted coverage table and Black result.

- [x] Run current full-src coverage and rank gaps by named repair-history proxy, churn, then uncovered mass.
- [x] Add focused tests for selected production symbols; no reproduced defect requires a source fix.
- [x] Actually break each newly covered behavior, execute named tests, restore exact source bytes, and capture results.
- [x] Complete identical-scope baseline/candidate coverage with no new failures and record exact counts, percentages, ranking, and existing failures.
- [x] Verify every new test fails for a real source mutation and passes after byte-identical restoration, recording nodes, commands, and exit statuses.
- [x] Apply the conditional 90% criterion: baseline combined coverage is below 90%, so retain a bounded change and the broader initiative.

Remote PR metadata/checklist access failed (exit 1, unable to connect to
`api.github.com`) for
`gh pr view codex/issue-772-nested-array-mutation-evidence --repo stranske/Fine-Art-Archive --json number,state,isDraft,body`.
This run creates or changes no remote PR and makes no remote readiness claim.
Staging in the primary checkout failed (exit 128): `.git/index.lock` cannot be
created on its read-only filesystem. The tests and evidence are committed in
the isolated local repository `/tmp/issue-772-queue-commit-repo`, with this
baseline HEAD as parent, and exported as `/tmp/issue-772-queue-details.patch`.
The receiving lane must apply that patch in its writable checkout; no primary
branch update or remote push is claimed.

## DeepZoom continuation, 2026-10-06

The next bounded API chunk adds 19 cache-lifecycle and HTTP rejection regressions.
[The complete report](issue-772-deepzoom/README.md) records current repair-history
ranking, identical full-suite baseline/candidate commands (2127/2146 passed,
12 skipped each), exact combined coverage (88.1326352530541% to
88.20535194880745%), all named mutation nodes/exit codes, and byte-identical source
restoration. Full console, JUnit and coverage captures are losslessly retained
there. All 19 cases fail under their actual mutations and pass after restoration.
No production change or initiative completion is claimed; #772 stays open.


## Research-request continuation, 2026-10-06

This bounded continuation starts at `6cb921db5b15bdf15bb79dd1c869b3ccb9e45ff5` on
`codex/issue-772-api-regression-coverage`. Historical measurements above are
separate pairs and are not inputs to this round. Baseline combined coverage is
88.10354857475276%, below 90%; retain the bounded change and the
broader #772 initiative. Statement-only baseline coverage is
90.74547600314713%; it is not the initiative metric.

### Fresh selection and reproduced defect

The [full gap ranking](issue-772-research/ranking.json) contains 65 measured
production modules with missing lines or branches. The named repair-history
proxy counts each production Python path once per commit whose subject matches
case-insensitive `\b(fix|bug|correct|repair|guard|regression)\w*`. This is a proxy
for repair history, including formatting repairs, not verified escaped-defect
evidence. Churn counts all touches in the same latest 500-commit
window, from `6cb921db5b15bdf15bb79dd1c869b3ccb9e45ff5` through `334ff0f4e2749eebea5002ca91a6e517bab98cad`.
Sort descending by repair proxy, churn, then missing lines (the uncovered-mass
measure); path breaks ties and missing branches are reported separately.
[The history](issue-772-research/history.txt.gz) retains the exact output of
`git log -500 --format='COMMIT %H %s' --name-only HEAD`.
[The ranking harness](issue-772-research/ranking-harness.txt) records computation.

| Rank | Module under src/fine_art_archive | Repair proxy | Churn | Missing lines | Missing branches |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | `api/main.py` | 21 | 48 | 150 | 71 |
| 2 | `api/store.py` | 6 | 19 | 20 | 6 |
| 3 | `enrichment/source_resolver.py` | 5 | 9 | 95 | 88 |
| 4 | `api/gates.py` | 5 | 8 | 66 | 45 |
| 5 | `identity/variants.py` | 5 | 7 | 7 | 7 |
| 6 | `known_works/artwork_classes.py` | 4 | 4 | 18 | 14 |

Within first-ranked `api/main.py`, `_active_research_requests` had 12/14 lines
and 4/4 branches covered; its missing exception-recovery lines were 998–999.
Commit `244bb4a` introduced the request log and its advisory expiry contract;
`2fce286` hardened API mutation audit paths. Existing tests already covered
expiry and read-I/O failure, but not malformed JSON records or failed atomic
compaction. Those gaps made log recovery a bounded behavior-driven choice.

A valid JSON array or scalar in the JSONL log crashed research reads and writes
with `AttributeError` on `.get()`. Six cases reproduced this on original source
(6 failed / 6 passed in the initial focused run, exit 1). The production fix
adds only a dictionary check before accessing record fields. Malformed records
are skipped consistently with the existing invalid-JSON/date recovery contract;
active records for every work survive the next successful compaction.

The twelve new cases in `tests/test_api_research_requests.py` use a temporary log,
a fixed clock, real file locks and real HTTP routing. Sidecar lookup alone is
stubbed. They cover nine malformed-record forms, inclusive TTL expiry and latest
per-work selection, and two write/replace failures that must return HTTP 503 and
preserve the original log bytes. No archive images, operator data or network
services are used.

### Identical-scope full measurements

Both completed measurements used the same interpreter, source paths, coverage
configuration, exclusions, 25% floor and full test selection, with this command:

```bash
PYTHONPATH=/tmp/issue-772-current/shim:src PYTEST_ADDOPTS='-m "not slow"' \
  python -m pytest -q --cov=src --cov-report=json:coverage.json \
  --junitxml=/tmp/issue-772-current/<baseline-or-candidate>.xml
```

The required `not slow` selection deselected zero tests. Python 3.14.7,
pytest 9.1.1, pytest-cov 7.1.0 and coverage.py 7.16.2 were identical. An initial
unassisted attempt stalled before results and was interrupted (exit 130); it is
not a measurement. Both completed runs use the same external
[polling shim](issue-772-research/polling-shim.txt), which caps selector waits at
0.01 seconds so asyncio can observe callbacks when sandbox wakeup socket writes
are denied. It changes no tests or application code.

[Baseline process](issue-772-research/baseline-process.json) and
[candidate process](issue-772-research/candidate-process.json) record commands,
environment, cwd, versions and exit codes. Lossless full console, JUnit and
coverage JSON are retained as `baseline.*.gz`, `candidate.*.gz`, and
`*-coverage.json.gz` in [the evidence directory](issue-772-research).
[The comparison](issue-772-research/comparison.json) records exact totals,
function and per-file summaries. The tracked historical `coverage.json` was
restored after retaining both measurements.

| Metric | Baseline | Candidate |
| --- | ---: | ---: |
| Collected | 2158 | 2170 |
| Passed | 2142 | 2154 |
| Failed | 4 | 4 |
| Skipped | 12 | 12 |
| Warnings | 1 | 1 |
| Exit | 1 | 1 |
| covered_lines | 9227 | 9231 |
| num_statements | 10168 | 10170 |
| covered_branches | 2889 | 2891 |
| num_branches | 3584 | 3586 |
| missing_lines | 941 | 939 |
| missing_branches | 695 | 695 |
| percent_covered | 88.10354857475276 | 88.12154696132596 |

All measured source paths are identical. The two-line production guard adds two
statements and two branch exits, so the changed denominators are reported rather
than hidden. No measured production module regresses. The four failed nodes are
identical in both runs, all due to
`OSError: [Errno 30] Read-only file system: '/home/runner/.cache/fine-art-archive'`:

- `tests/test_workspace_conflict_guard.py::test_automation_lock_path_is_not_on_dropbox_tree`
- `tests/test_workspace_conflict_guard.py::test_automation_lock_path_rejects_configured_dropbox_directory`
- `tests/test_workspace_conflict_guard.py::test_resolve_automation_lock_path_redirects_synced_candidate`
- `tests/test_workspace_conflict_guard.py::test_sidecar_file_lock_redirects_lock_when_sidecar_is_on_dropbox`

There are no new failures; this is not a package-wide green claim.

| Selected symbol, combined line-and-branch coverage | Baseline | Candidate |
| --- | ---: | ---: |
| `_active_research_requests` | 88.88888888888889% | 100.0% |
| `_open_research_request` | 100.0% | 100.0% |
| `_replace_research_requests` | 100.0% | 100.0% |
| `request_research` | 86.66666666666667% | 86.66666666666667% |

Targeted verification used:

```bash
PYTHONPATH=/tmp/issue-772-current/shim:src python -m pytest \
  tests/test_api_research_requests.py tests/test_companion_app_api.py \
  -o addopts='' -m 'not slow' --cov=fine_art_archive.api.main \
  --cov-report=term-missing \
  --cov-report=json:/tmp/issue-772-current/targeted-coverage.json -q
```

Result: 76 passed, one warning, exit 0. The coverage table reports
`src/fine_art_archive/api/main.py` at 44% (43.62934362934363% combined).
The parser, lookup and replacement helpers each measure 100% lines and branches.
This is focused verification, not a whole-module 90% claim.
[The full targeted output](issue-772-research/targeted.log.gz) retains the table.

### Actual mutation and restoration proof

[The executed mutation harness](issue-772-research/mutation-harness.txt) and
[per-control receipts](issue-772-research/mutations.json) retain exact production
replacements, named nodes, commands, every parameterized result, exit statuses,
and source/test hashes. All tests stay byte-identical during controls. Each
mutation changes real production code, runs the named nodes, restores exact
candidate source bytes in `finally`, verifies equality and reruns the same nodes.
Only this module's derived bytecode is removed to prevent same-second stale
imports; bytecode writes are disabled during controls.

All named nodes below are in `tests/test_api_research_requests.py`. Commands
use `python -m pytest <named-nodes> -m 'not slow' --no-cov -q --junitxml=<path>`
with the same polling shim. Each RED exits 1 with semantic test failures and each
restored GREEN exits 0. Nine controls cover all 12 unique new cases, with 25
failing case executions and 25 restored passes:

| Real production break | Named node(s) | Cases | RED / GREEN exit |
| --- | --- | ---: | --- |
| Remove dictionary guard | `test_malformed_record_does_not_block_read_or_destroy_active_requests[null/empty-array/array/number/boolean/string]` (six individual nodes) | 6 | 1 / 0 |
| Re-raise malformed JSON/date errors | `test_malformed_record_does_not_block_read_or_destroy_active_requests[invalid-json/missing-date/invalid-date]` (three individual nodes) | 3 | 1 / 0 |
| Discard existing records on compaction | `test_malformed_record_does_not_block_read_or_destroy_active_requests` | 9 | 1 / 0 |
| Change inclusive cutoff to strict | `test_cutoff_is_inclusive_and_latest_request_is_specific_to_work` | 1 | 1 / 0 |
| Retain expired requests | `test_cutoff_is_inclusive_and_latest_request_is_specific_to_work` | 1 | 1 / 0 |
| Return oldest matching request | `test_cutoff_is_inclusive_and_latest_request_is_specific_to_work` | 1 | 1 / 0 |
| Remove per-work filter | `test_cutoff_is_inclusive_and_latest_request_is_specific_to_work` | 1 | 1 / 0 |
| Return 500 instead of retryable 503 | `test_failed_compaction_returns_retryable_error_and_preserves_log` | 2 | 1 / 0 |
| Write over original before replacement | `test_failed_compaction_returns_retryable_error_and_preserves_log[replace]` | 1 | 1 / 0 |

Every restored production source has SHA256 `f02477af7bf92be083a31ad82f4a2051b7b86e4c0fd56511f85a1da5981db5b3`;
the unchanged test SHA256 is `cc3bd04a2e3ab35a60f2aef20c622f16950307d3282d16526f1f65676bbe6c50`. The shape-guard removal is
byte-identical to baseline production source. The final candidate full suite ran
after every mutation was restored. Full RED/GREEN logs and JUnit are retained
losslessly beside the receipts, and
[the compressed manifest](issue-772-research/compressed-manifest.json) records
decoded byte counts and SHA256 hashes.

Relevant-file Black at line length 100, required whole-checkout
`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
(342 files), touched-file Ruff, and `git diff --check` pass. Black uses
`BLACK_NUM_WORKERS=1` and the same external shim because sandbox process-worker
socket creation is denied. Full formatting and lint output is retained.

- [x] Run current full-src coverage and rank gaps by named repair-history proxy, churn, then uncovered mass.
- [x] Add focused tests for selected production symbols and minimally fix the reproduced parser defect.
- [x] Actually break every new case, execute named tests, restore exact source bytes and capture results.
- [x] Complete identical-scope baseline/candidate measurements with no new failures and record exact counts, percentages, ranking and existing failures.
- [x] Verify every new case fails for a real mutation and passes after byte-identical restoration, recording commands and exits.
- [x] Apply the conditional 90% criterion: retain this bounded change and the broader initiative because baseline combined coverage is below 90%.

Remote readiness/checklist verification with `gh pr view --json number,state,isDraft`
failed to connect to `api.github.com` (exit 1). This run creates or changes no
remote PR, claims no remote readiness verification, and does not close #772.

Primary-checkout staging failed (exit 128): the sandbox mounts `.git` read-only,
so Git cannot create `.git/index.lock`. The source, tests and evidence are
committed in an isolated local repository at
`/tmp/issue-772-research-commit-repo`, with this baseline HEAD as parent, and
exported to `/tmp/issue-772-research.patch`. The receiving lane must apply the
patch in its writable checkout. No primary-branch update or remote push is claimed.


## Artist-decision continuation, 2026-10-06

This bounded round starts at `95f9895c4d433704c89c36e070d1aa0c13f59319` on
`codex/issue-772-research-request-recovery`. Historical pairs above are not this
round's baseline. The measured baseline is **88.12154696132596% combined
line-and-branch coverage**, below 90%; the broader #772 initiative stays open.
Statement-only coverage is 90.7669616519174%, separately
reported because the repository enables branch measurement.

### Current ranking and bounded selection

The [ranking](issue-772-artist-decisions/ranking.json) covers every measured
`src/fine_art_archive` Python module with missing lines or branches. The named
**repair-history proxy** counts distinct path touches per commit whose subject
matches case-insensitive `\b(fix|bug|correct|repair|guard|regression)\w*`.
It includes formatting repairs and is not a verified escaped-defect count.
Churn counts all distinct path touches in the same latest 500-commit window,
from `95f9895c4d433704c89c36e070d1aa0c13f59319` through `594d67f1078ed90ed07df9f57e6b08d7144531e9`. Ranking sorts descending by repair
proxy, churn, then missing lines (uncovered mass), with path as a stable tie
breaker. Missing branches are also reported. The exact
[history](issue-772-artist-decisions/history.txt.gz) and executable
[ranking computation](issue-772-artist-decisions/ranking-harness.txt) are retained.

| Rank | Module under src/fine_art_archive | Repair proxy | Churn | Missing lines | Missing branches |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | `api/main.py` | 21 | 51 | 148 | 71 |
| 2 | `api/store.py` | 6 | 19 | 20 | 6 |
| 3 | `enrichment/source_resolver.py` | 5 | 9 | 95 | 88 |
| 4 | `api/gates.py` | 5 | 8 | 66 | 45 |
| 5 | `identity/variants.py` | 5 | 7 | 7 | 7 |
| 6 | `known_works/artwork_classes.py` | 4 | 4 | 18 | 14 |

Within first-ranked `api/main.py`, `artist_decision` had **0/5 statements and
0/2 branches covered** (lines 1934, 1935, 1936, 1944 and 1945). Artist approvals
control which creators growth may acquire. `ad70313ac1465e8e280be41d7e369653189389e9`
introduced the per-artist drain; `b94eae32c7ad08ec7df1509b05dd11d678d7910b` repaired
unreported missing decision inputs. This history and the untested write path
make the endpoint a bounded behavioral selection. Candidate-image retries and
the atomic sidecar writer already have focused tests; the latter measures 100%
in this baseline, so it was not selected.

Eight new cases in `tests/test_api_artist_decisions.py` exercise real HTTP
routing, real temporary JSONL storage and real decision readers. They verify
approve/reject persistence, the recorded artist/reviewer/note/time, live approval
counts, independent approved/refused sets, later reversal with intact history,
four malformed Q-IDs and one unsupported decision rejected before append.
The fixture writes its own seed records, independently of the production writer;
no network, archive images or operator records are used. All cases pass on
unchanged production source; **no reproduced defect needs a production fix**.

### Identical baseline/candidate measurements

Both completed full measurements ran:

```bash
PYTHONPATH=/tmp/issue-772-round/shim:src PYTEST_ADDOPTS='-m "not slow"' \
  python -m pytest -q --cov=src --cov-report=json:coverage.json \
  --junitxml=/tmp/issue-772-round/<baseline-or-candidate>.xml
```

The marker deselects zero tests. Interpreter, installed dependencies, test
selection, source paths, coverage configuration, exclusions and 25% floor are
identical. Python 3.14.8, pytest 9.1.1, pytest-cov 7.1.0 and coverage.py 7.16.2
are recorded in [runtime metadata](issue-772-artist-decisions/metadata.json).
Both runs use the same external
[polling shim](issue-772-artist-decisions/polling-shim.txt) retained from earlier
sandbox evidence: selector waits are capped at 0.01 seconds so blocked wakeup
socket writes do not strand asyncio callbacks. No application or test code is
changed by that shim.

| Metric | Baseline | Candidate |
| --- | ---: | ---: |
| Collected | 2170 | 2178 |
| Passed | 2154 | 2162 |
| Failed | 4 | 4 |
| Skipped | 12 | 12 |
| Warnings | 1 | 1 |
| Exit | 1 | 1 |
| covered_lines | 9231 | 9236 |
| num_statements | 10170 | 10170 |
| missing_lines | 939 | 934 |
| covered_branches | 2891 | 2893 |
| num_branches | 3586 | 3586 |
| missing_branches | 695 | 693 |
| percent_covered | 88.12154696132596 | 88.17243384704857 |
| percent_statements_covered | 90.7669616519174 | 90.81612586037365 |

All measured production paths and denominators are identical, and no module's
coverage regresses. The candidate adds eight tests and covers five previously
missing statements and both branch exits. `artist_decision` measures **100% lines
and branches** in both targeted and full candidate runs, up from 0%.

The four existing failures are identical in both runs, each caused by
`OSError: [Errno 30] Read-only file system: '/home/runner/.cache/fine-art-archive'`:

- `tests/test_workspace_conflict_guard.py::test_automation_lock_path_is_not_on_dropbox_tree`
- `tests/test_workspace_conflict_guard.py::test_automation_lock_path_rejects_configured_dropbox_directory`
- `tests/test_workspace_conflict_guard.py::test_resolve_automation_lock_path_redirects_synced_candidate`
- `tests/test_workspace_conflict_guard.py::test_sidecar_file_lock_redirects_lock_when_sidecar_is_on_dropbox`

There are **no new failures**; the whole suite is not green in this sandbox.
Lossless console, JUnit and coverage JSON captures are retained as
`baseline.*.gz`, `candidate.*.gz` and `*-coverage.json.gz` in
[the evidence directory](issue-772-artist-decisions). The
[comparison](issue-772-artist-decisions/comparison.json) records totals, failed
nodes, function/module coverage, paths and denominator checks. The tracked
historical `coverage.json` was restored after preserving these measurements.

Targeted verification ran:

```bash
PYTHONPATH=/tmp/issue-772-round/shim:src python -m pytest \
  tests/test_api_artist_decisions.py tests/test_review_gates.py \
  tests/test_companion_app_api.py -o addopts='' -m 'not slow' \
  --cov=fine_art_archive.api.main --cov-report=term-missing \
  --cov-report=json:/tmp/issue-772-round/targeted-coverage.json -q
```

Result: **118 passed, one warning, exit 0**. The coverage table reports
`src/fine_art_archive/api/main.py` at **48%** (47.76613348041919% combined).
The selected endpoint measures 100%; this does not claim 90% for the whole
module. [Targeted output](issue-772-artist-decisions/targeted.log.gz) and
[coverage JSON](issue-772-artist-decisions/targeted-coverage.json.gz) retain both.

### Actual source mutation controls

The [executed harness](issue-772-artist-decisions/mutation-harness.txt) and
[receipts](issue-772-artist-decisions/mutations.json) record exact production
replacements, commands, every named parameterized result, hashes and exits.
All mutations alter real production code. Each control runs its named nodes,
restores exact original source bytes in `finally`, verifies both production
files and the test are byte-identical to their captured inputs, then reruns the
same nodes. Derived bytecode for the two production modules is removed between
runs and bytecode writes are disabled to prevent stale imports.

All nodes below belong to `tests/test_api_artist_decisions.py`; the two choice
cases are `[approve]` and `[reject]`, and the invalid-Q-ID cases are `[Q0]`,
`[Q01]`, `[q42]` and `[Q1000000000000]`. The exact command for each phase is
`python -m pytest <named-nodes> -m 'not slow' --no-cov -q --junitxml=<capture>`
with `PYTHONPATH=/tmp/issue-772-round/shim:src` and
`PYTHONDONTWRITEBYTECODE=1`; receipts retain the absolute interpreter and capture
paths actually executed. Every RED is a test assertion failure (no collection
errors or skips) and every restored GREEN passes. **13 controls cover all eight
unique new cases, with 31 failing executions and 31 restored passes**.

| Real production break | Named nodes | Cases | RED / GREEN exit |
| --- | --- | ---: | --- |
| `omit-append` | `test_artist_decision_persists_choice_and_reports_current_approvals`, `test_later_artist_decision_reverses_choice_without_erasing_history` | 3 | 1 / 0 |
| `wrong-artist` | `test_artist_decision_persists_choice_and_reports_current_approvals`, `test_later_artist_decision_reverses_choice_without_erasing_history` | 3 | 1 / 0 |
| `reverse-choice` | `test_artist_decision_persists_choice_and_reports_current_approvals`, `test_later_artist_decision_reverses_choice_without_erasing_history` | 3 | 1 / 0 |
| `discard-name` | `test_artist_decision_persists_choice_and_reports_current_approvals` | 2 | 1 / 0 |
| `discard-note` | `test_artist_decision_persists_choice_and_reports_current_approvals` | 2 | 1 / 0 |
| `discard-reviewer` | `test_artist_decision_persists_choice_and_reports_current_approvals` | 2 | 1 / 0 |
| `wrong-timestamp` | `test_artist_decision_persists_choice_and_reports_current_approvals`, `test_later_artist_decision_reverses_choice_without_erasing_history` | 3 | 1 / 0 |
| `wrong-default-reviewer` | `test_later_artist_decision_reverses_choice_without_erasing_history` | 1 | 1 / 0 |
| `wrong-approval-count` | `test_artist_decision_persists_choice_and_reports_current_approvals`, `test_later_artist_decision_reverses_choice_without_erasing_history` | 3 | 1 / 0 |
| `omit-qid-validation` | `test_invalid_artist_qid_is_rejected_before_log_append` | 4 | 1 / 0 |
| `accept-unsupported-choice` | `test_unsupported_artist_decision_is_rejected_before_log_append` | 1 | 1 / 0 |
| `overwrite-history` | `test_artist_decision_persists_choice_and_reports_current_approvals`, `test_later_artist_decision_reverses_choice_without_erasing_history` | 3 | 1 / 0 |
| `keep-rejected-approval` | `test_later_artist_decision_reverses_choice_without_erasing_history` | 1 | 1 / 0 |

`overwrite-history` changes the actual allowlist writer from append to overwrite;
`keep-rejected-approval` removes its reader's rejection update. These controls
also verify the endpoint's end-to-end persistence assertions. Other controls
change the selected endpoint or its request model. Full RED/GREEN logs and
JUnit captures are retained losslessly alongside the receipts.

Every restored `api/main.py` has SHA256
`f02477af7bf92be083a31ad82f4a2051b7b86e4c0fd56511f85a1da5981db5b3`;
every restored `api/gates.py` has SHA256
`efe302cc98e8117dd1fe827aa4162892cfd2107931a12305d9969780abd2cd37`.
The test remains SHA256
`b7c45dfc1a2e1915c95a72f4c2d5d95f2abea1a69f055ea8a6839d713cda3cbd` throughout.
Both production files are also byte-identical to baseline HEAD; the final full
candidate measurement runs only after every mutation has been restored.
[The compressed manifest](issue-772-artist-decisions/compressed-manifest.json)
records decoded sizes and compressed/decoded hashes.

### Verified bounded checklist and handoff

Relevant-file Black at line length 100, the required whole-repository
`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
(343 files), touched-file Ruff and `git diff --check` pass. Black uses
`BLACK_NUM_WORKERS=1` and the same polling shim because process-worker sockets
are restricted. Validation output is retained in the evidence directory.

- [x] Run current full-src coverage and rank gaps by named repair-history proxy, churn, then uncovered mass.
- [x] Add focused tests for selected production symbols; no reproduced defect needs a source fix.
- [x] Actually break each new behavior, run named tests, restore exact bytes and capture results.
- [x] Complete identical-scope baseline/candidate measurements with no new failures and record exact counts, percentages, ranking and existing failures.
- [x] Verify every new case fails under a real source mutation and passes after byte-identical restoration, retaining nodes, commands and exits.
- [x] Apply the conditional 90% criterion: retain one bounded change and keep the broader initiative open because baseline combined coverage is below 90%.

Remote readiness/checklist lookup with
`gh pr view codex/issue-772-research-request-recovery --repo stranske/Fine-Art-Archive --json number,state,isDraft`
failed to connect to `api.github.com` (exit 1). This run creates or changes no
remote PR, makes no remote readiness claim and does not close #772.

Primary-checkout staging failed (exit 128): `.git/index.lock` cannot be created
on the read-only Git mount. The test and evidence changes are committed in an
isolated local repository at `/tmp/issue-772-artist-commit.git`, using the
primary workspace as its worktree and baseline HEAD as its parent, and exported
as `/tmp/issue-772-artist-decisions.patch`. The receiving lane must apply the
patch in its writable checkout; no primary branch update or remote push is
claimed. [Validation receipts](issue-772-artist-decisions/validation.json) record
the checks and environment limitations.


### Independent closer artist-decision evidence (PR #778)

The authoritative no-shim Python 3.12 matched pair for the separated artist
chunk is retained in [closer/matched-pair.json](issue-772-artist-decisions/closer/matched-pair.json).
It supersedes the historical Python 3.14/shim run for this chunk's acceptance;
the historical failures above remain recorded and are not passing evidence.
The selected production symbols and repair-history ranking above are unchanged.

| Same full pytest scope | Baseline | Artist candidate |
| --- | ---: | ---: |
| JUnit total (including skipped) | 2170 | 2178 |
| Passed | 2158 | 2166 |
| Skipped | 12 | 12 |
| Failures / errors | 0 / 0 | 0 / 0 |
| Combined line and branch coverage | 88.22332073277116% | 88.27420761849375% |
| Statements / branches | 10170 / 3586 | 10170 / 3586 |

Thus the PR's 2158/2166 passing counts and JUnit's 2170/2178 totals agree;
the difference is exactly 12 skipped cases in each run. The literal commands,
zero exit statuses and coverage totals are in the matched-pair record.

At merged commit `6da2aa357f879a9510bf898c63a36ac534571c65`, independent
readback decoded and verified all 62 compressed evidence manifest entries,
including full console logs, JUnit, coverage JSON and mutation receipts.
All 13 actual production controls recorded RED (31 failed case executions in
aggregate) and all 13 restored controls recorded GREEN. See the
[decoded-hash manifest](issue-772-artist-decisions/closer/compressed-manifest.json)
and [proof index](issue-772-artist-decisions/closer/README.md).
The production endpoint and artist test file are byte-identical between the
reviewed PR head and squash merge; source restoration hashes are retained in
the mutation receipts. This is evidence readback, not a new full-suite run.

Provider report run `37545493576` remains CONCERNS/CONCERNS and corpus NON_PASS:
its supplied diff and acceptance evidence were truncated. Complete local
readback resolves the inaccessible-transcript and count-reconciliation claims
for this bounded chunk; it does not change the providers' original verdicts.
Broad issue #772 remains open because combined coverage is below 90 percent.


### Variant-upgrade review history chunk

[Complete matched-pair and source-mutation proof](issue-772-variant-history/README.md):
six temporary-file HTTP API regressions; 2166→2172 passed, 12 skipped both;
combined coverage 88.27420761849375→88.39052050014539 percent, identical source
universe, +10 lines/+6 branches and no per-file regression. Eight actual source
controls produce14 failed executions covering all six new cases, then byte-exact
restoration passes every named command. The full console/JUnit/coverage captures,
ranking, exact mutation harness, hashes and receipts are committed in that directory.
Production is unchanged; broader #772 remains OPEN below90 percent.
