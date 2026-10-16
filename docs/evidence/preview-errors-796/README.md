# Source #796: preview error-contract acceptance

This repairs acceptance evidence for existing PR #797. Production source is unchanged. Four invalid-input/missing-master cases now also spy on the real renderer and assert that it was never called. The fifth case still injects only the renderer failure and checks the exact HTTP 500 diagnostic.

## Baseline and ranking correction

The original author log was recovered from the actual completed #796 writer. `original-ranking-recovery.json` preserves its commands and outputs. It ranked API/identity/enrichment module gaps using a saved coverage file and identified `eink_preview` as an uncovered public boundary. Its attempted fresh background baseline never ran (`nice(5) failed: operation not permitted`, empty log, no result). Accordingly, the PR's original 87.91% was a saved report, not a measured pre-work run.

The exact pre-PR base `4446c8f2cb7730614f9bf5e35e0ac385242facec` has now been reconstructed in a separate linked worktree, with the frozen `uv.lock` dev environment on CPython 3.12.2. Full baseline: **2277 passed, 12 skipped, 89.090646% combined line/branch coverage**, below the source's 90% stop condition. This is a retrospective measurement, not a claim that the original writer ran it. Full baseline XML/log and summary are included.

`base-ranking.json` records the current bounded comparison in the source's requested API/identity/enrichment scope. It sorts explicit same-surface escaped-defect evidence first, then 90-day commit count, then missing lines + branches; file size is unused. API `main.py` has the recent fit/ETag and monochrome delivery corrective lineage (#786/#788/#790), 45 recent commits, and 121 uncovered lines/branches. `eink_preview` itself has 8 missing lines and 2 missing branches at base (65.52% combined coverage), directly covering the new invalid-options/error cases. This supports retaining the existing narrow API chunk; it does not assert a new fleet-wide coverage ranking or authorize another coverage chunk.

## Individual causal controls

`faults.json`, per-control logs, and parsed JUnit preserve **seven assertion-RED / restored-GREEN controls**. Each control starts from the exact production bytes and restores them in a `finally` block. Source SHA-256 is recorded in every row. The restored source is byte-identical to the PR's production source; no mutant is committed.

| Fault | Expected failing cases | Restored |
| --- | ---: | --- |
| Invalid target silently falls back to valid panel | 1 | PASS |
| Invalid dither validation bypassed | 1 | PASS |
| Invalid fit silently falls back | 1 | PASS |
| Missing-master status changed 404 -> 410 | 1 | PASS |
| Renderer exception status changed 500 -> 400 | 1 | PASS |
| Actual render performed before invalid-option validation | 3 | PASS |
| Actual render performed before missing-master rejection | 1 | PASS |

The ordering mutants still return the expected status/detail; the new renderer assertions specifically catch their extra work. The JUnit audit confirms 9 assertion failures, zero collection/setup errors, and all restored cases passing. An initial selection trial selected zero nodes and an initial same-size rewrite reused Python bytecode; neither was accepted as proof. The final runner selects the actual pytest parameter IDs and removes only its owned generated `main.*.pyc` before each subprocess. The seven final controls above were rerun completely.

Reproduce after `uv sync --frozen --extra dev --python /opt/anaconda3/bin/python3` with `.venv/bin/python docs/evidence/preview-errors-796/run-faults.py`. Run it only in an isolated worktree with no concurrent tests/writer, because it temporarily mutates the production file.

## Full candidate validation

Frozen-lock full candidate suite: **2282 passed, 12 skipped**, 175.33 seconds. Combined coverage moves **89.090646% -> 89.162989%**; the production `eink_preview` function moves **65.52% -> 100%** (25/25 statements and 4/4 branches). The skipped set remains 12. Candidate JUnit, full XML/log, and the coverage JSON hash/totals/function summary are durable here. The full JSON is retained in the local worktree, not committed. Ruff and pinned Black pass for both changed Python files; `git diff --check` passes.

## Delivery boundary

Full candidate suite, exact-head hosted checks, seven-minute review floor, zero active review threads, guarded squash, actual `verify:compare`, and source disposition remain separate gates. Local causal proof does not assert hosted acceptance or provider PASS.
