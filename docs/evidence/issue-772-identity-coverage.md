# Issue #772: tag-proposal API boundary protection

Baseline main: `eb1ef51fa121329cebc90fcf4acbada464608b83`. One low risk chunk of #772, which stays open; no 90 percent claim.

The first-ranked production module is `src/fine_art_archive/api/main.py`. Its tagger endpoint accepted empty dictionaries as work lists and empty lists as gate objects; other valid JSON shapes raised uncaught attribute errors. The seven new shape cases failed on original source (7 failed / 9 passed). A seven-line guard now returns HTTP 500 with a controlled invalid-structure detail before using those values. Existing valid response fields and null/empty defaults are preserved.

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
