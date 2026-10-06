# Issue #772: DeepZoom cache and HTTP boundary regressions

This bounded continuation follows the independent acceptance of PR #775. Source issue #772 remains open: combined line-and-branch coverage is below 90%. No production defect was reproduced, so this chunk changes tests and evidence only. All ZIPs, sidecars, proxy paths and returned handles belong to temporary fixtures; the tests do not use the operator archive or external image services.

Baseline main: `2b21719b5551742dcb7001a814c4964981413e04`.
Production `src/fine_art_archive/api/main.py` SHA256 before and after every deliberate mutation: `d201269355b26f47b20b08a7020de9c277d6ada569e64e93e874a9d0006f93d3`.
Test file SHA256: `c2ad6ad67d81af158f7be596e74f663c7f6a964a572bf9a3485152ca036f893f`.

## Selection and behavior

The [complete gap ranking](ranking.json) uses the latest 500 commits reachable from baseline, retained verbatim in `history.txt.gz`. Command: `git log -500 --format='COMMIT %H %s' --name-only HEAD`. Count each production path once per commit; subjects matching case-insensitive `\b(fix|bug|correct|repair|guard|regression)\w*` supply a **repair-history proxy, not a verified escaped-defect count**. Restrict to measured production gaps, then sort by descending repair proxy, churn, uncovered lines, with path as the final tie breaker.

| Production module | Repair proxy | Churn | Baseline missing lines |
|---|---:|---:|---:|
| api/main.py | 21 | 48 | 157 |
| api/store.py | 6 | 19 | 21 |
| enrichment/source_resolver.py | 5 | 9 | 95 |
| api/gates.py | 5 | 8 | 63 |
| identity/variants.py | 5 | 7 | 7 |

The first-ranked API module has a compact DeepZoom boundary suitable for a low risk chunk. Nineteen cases cover unchanged-handle reuse, case normalization, nanosecond replacement, disappearance/reappearance without negative caching, corrupt/unreadable ZIP fallback, unavailable work directories, cache eviction, absent sidecars/layers, and invalid HTTP requests rejected before archive/network I/O. Fixture cleanup closes returned handles even after replacement/eviction.

## Full baseline and candidate gates

Both executed the default full suite, same source file universe, interpreter and coverage settings:

```sh
python -m pytest -q --cov=src --cov-report=json:<coverage-path> --junitxml=<junit-path>
```

Exact interpreter, commands, cwd, environment, exit status and elapsed time are retained in `baseline-process.json` and `candidate-process.json`. Python 3.12.2 / pytest 9.1.1 reused an existing isolated environment, while this checkout's `src` supplied production imports. No floors, exclusions, markers, source, or test selection changed between runs; both exited 0. Full logs, JUnit and coverage JSON are losslessly compressed beside this report; use `gzip -dc <file>.gz` to inspect. [compressed-manifest.json](compressed-manifest.json) records decoded byte counts and SHA256 hashes.

| Metric | Baseline | Candidate |
|---|---:|---:|
| Passed / skipped | 2127 / 12 | 2146 / 12 |
| Warnings | 2 | 2 |
| Covered lines / statements | 9226 / 10168 | 9233 / 10168 |
| Covered branches / branches | 2894 / 3584 | 2897 / 3584 |
| Missing lines / branches | 942 / 690 | 935 / 687 |
| Combined coverage | 88.1326352530541% | 88.20535194880745% |
| API main combined coverage | 87.23051409618574% | 87.78330569375345% |

Only `api/main.py` gained coverage; no measured production file regressed. Statement-only coverage is 90.8044846577498%, which is **not** the combined initiative metric. [comparison.json](comparison.json) retains all per-file summaries and the selected function summaries. The focused module passed all 19 cases; whole-checkout Black (341 files), touched-file Ruff, and `git diff --check` passed.

## Actual break / restore proof

Each group changed the real production condition, ran the named tests, restored original source bytes, and reran those tests with unchanged test bytes. All RED executions failed assertions or raised the expected semantic failure, with no collection errors. Twelve mutations cover all 19 unique cases (20 failing case executions, because the reuse case proves two independent controls). Every restored GREEN execution exited 0. The final full candidate suite ran after restoration.

| Real mutation | Named node in tests/test_deepzoom_archive_cache.py | Cases | RED / GREEN exit |
|---|---|---:|---:|
| `reuse` | `test_unchanged_container_reuses_handle_across_layer_case` | 1 | 1 / 0 |
| `layer-case` | `test_unchanged_container_reuses_handle_across_layer_case` | 1 | 1 / 0 |
| `replacement` | `test_replaced_container_reopens_and_serves_new_bytes` | 1 | 1 / 0 |
| `disappearance` | `test_missing_container_clears_stale_cache_and_can_reappear` | 1 | 1 / 0 |
| `corrupt` | `test_corrupt_container_allows_fallback_and_later_repair` | 1 | 1 / 0 |
| `unreadable` | `test_unreadable_container_allows_fallback_without_cache_entry` | 1 | 1 / 0 |
| `directory-error` | `test_unavailable_work_directory_allows_container_fallback` | 2 | 1 / 0 |
| `eviction` | `test_container_cache_evicts_old_entries_and_keeps_new_handle` | 1 | 1 / 0 |
| `manifest-missing` | `test_missing_sidecar_returns_not_found[deepzoom]` | 1 | 1 / 0 |
| `tile-missing` | `test_missing_sidecar_returns_not_found[dz/VIS/12/3_4.jpg]` | 1 | 1 / 0 |
| `absent-layer` | `test_absent_layer_returns_not_found` | 3 | 1 / 0 |
| `invalid-tile` | `test_invalid_tile_request_is_rejected_before_archive_or_network` | 6 | 1 / 0 |

[mutations.json](mutations.json) records exact replacements, commands, every parameterized case result, exit codes, and restoration hashes. Each referenced console log and JUnit file is retained with `.gz` appended. [mutation-harness.txt](mutation-harness.txt) is the actual executed harness: it disables bytecode writes and removes only this module's derived bytecode before mutation execution to prevent same-second stale imports. No mutation remains in production source.

## Receiving lane

Keepalive owns head-attached CI and any review findings for this chunk; the reviewed-repo closer owns exact-head checks, full active-thread review, the seven-minute review floor, merge, and `verify:compare`. After independent acceptance of this chunk, the opener may select the next ranked gap under #772. This report claims local validation and a measured incremental gain, not initiative completion or deployed/live archive acceptance.
