Malformed master-facts caches whose `entries` value is a list or null now count as cache misses. Previously those shapes raised `AttributeError` during acquisition review. Two regression cases reproduced the failure before the small cache-shape guard was added.

The latest regressions exposed a second bug: a failed label request for a Wikidata or Commons claim was recorded as `not_available`. That incorrectly converted a transient failure into a claimed absence. A one-line fix raises `ConnectionError` from the failed secondary lookup so the resolver's existing network-error handling leaves the field `not_researched`. Four regressions reproduced the bug before the fix, covering medium/category through both providers; [the failing output](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/claim-label-bug-before-fix.txt.gz) is retained. These are the only two production fixes in the PR.

The PR adds **82 offline cases** for API delivery and review gates, cache recovery, discovery, and museum/Wikidata identity resolution. The latest eleven check literal medium claims, empty/nontext claims, ordered label deduplication across malformed or absent entities, unavailable labels through both providers, missing work entities, failed work requests, and absent work identifiers.

### Ranking and coverage

Targets follow [the repository ranking](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-799-coverage/review-gap-ranking.csv): API main, API store, then source resolver. Repair-history matches are a proxy, not verified escaped-defect counts. The verified repair/touch counts remain 28/57, 6/21, and 5/9. This follow-up continues the already selected resolver target in the existing PR, without selecting a new target or opening another PR.

The supplied CI baseline is **89.64%**, and CI's figures remain authoritative. The original starting-head whole-suite baseline was **89.9790326%**, below the 90% stop threshold despite rounding to 90% in the table. This is a continuation of that PR, whose matched local whole-suite result now reaches **91.1318%**, with **156 previously missing target statements and branches** covered.

| Target | Original local missing statements + branches | Latest local missing statements + branches | Reduction | Latest cover |
|---|---:|---:|---:|---:|
| `api/main.py` | 63 + 35 | 3 + 10 | 85 | 99.29% |
| `api/store.py` | 20 + 6 | 0 + 1 | 25 | 99.82% |
| `enrichment/source_resolver.py` | 95 + 88 | 70 + 67 | 46 | 87.85% |

The published whole-CI ranking has 111, 26, and 183 missing units for these targets. The matched local comparison uses the original baseline reports retained in this PR, so inherited tests are not credited twice. The cache fix's three added statements and two added branches are fully covered and excluded from the reduction of formerly missing units. The local measurements differ from CI and do not replace Gate acceptance.

For the latest eleven cases, matched whole-suite resolver missing units fall **152 → 137**; repository coverage rises **91.0234% → 91.1318%**. Targeted verification: **205 passed in 3.78s**; the resolver's actual coverage row is **87.85%**. The resolver is not claimed fully covered. Remaining API gaps include Pydantic v1 compatibility and a zero-attempt retry fallback; this chunk does not synthesize unsupported runtime conditions to cover them. The original ~120-unit chunk is exceeded.

### Executed mutation proofs

All **82 PR-added cases** have individual executions that fail with a deliberate production defect (exit 1) and pass after exact source restoration (exit 0). The [original 65-case index](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/mutation-summary.md) links to its receipts; the [six artist cases](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/artist-mutation-summary.md) retain theirs. The latest eleven are listed below, with [exact replacements, commands and full outputs](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/claim-label-mutations.json.gz). The two cache regressions' failure before the production fix remains in [cache-bug-before-fix.txt.gz](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/cache-bug-before-fix.txt.gz).

| New case | Deliberate defect | Broken / restored |
|---|---|---|
| Literal medium claims | Preserve surrounding whitespace | 1 failed / 1 passed |
| Blank/nontext claims | Accept blank literal text | 1 failed / 1 passed |
| Multiple label entities | Keep duplicate labels | 1 failed / 1 passed |
| Unusable label entities | Invent a medium | 1 failed / 1 passed |
| Failed Wikidata medium labels | Confirm absence after an outage | 1 failed / 1 passed |
| Failed Wikidata category labels | Confirm absence after an outage | 1 failed / 1 passed |
| Failed Commons medium labels | Confirm absence after an outage | 1 failed / 1 passed |
| Failed Commons category labels | Confirm absence after an outage | 1 failed / 1 passed |
| Work marked missing | Accept its claims | 1 failed / 1 passed |
| Failed work request | Treat failure as a successful empty response | 1 failed / 1 passed |
| Work without a QID | Report a confirmed absence | 1 failed / 1 passed |

### Validation and task reconciliation

The immediately preceding head `5818dbf06dad3c2ffc488ca79a6037babef593db` has a [successful Gate run](https://github.com/stranske/Fine-Art-Archive/actions/runs/38988785858), including Python 3.12/3.13, Black and Ruff. Its Python 3.12 job reports **2400 passed, 12 skipped** and **91.05%**. [The CI receipt](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/claim-label-parent-ci.json) records exact checks and target rows. This validates the preceding 71 cases and cache fix; fresh CI for the latest eleven cases and label-outage fix remains pending.

Fresh local baseline: **4 failed, 2396 passed, 12 skipped, 1 warning in 161.00s (0:02:40)**. Latest full suite: **4 failed, 2407 passed, 12 skipped, 1 warning in 159.81s (0:02:39)**. Both have the same four `test_workspace_conflict_guard.py` failures because `/home/runner/.cache/fine-art-archive` is read-only. No tests were disabled or skipped to hide failures. The external selector-polling harness and one Black worker accommodate sandbox socket restrictions without changing repository code or tests.

- [x] Pick targets in repository ranking order, rather than by file size.
- [x] Run a failing mutation and passing restoration for every new test; 82/82 cases have receipts.
- [x] Fix real bugs minimally: the malformed-cache shape guard and one-line label-outage fix have failing-before-fix receipts. The existing negative-cache regression also passes in the targeted suite.
- [x] Keep low blast radius: tests and the targeted cache fix, with no refactors.
- [x] Keep one PR for this logical API/enrichment coverage chunk.
- [x] Verify the preceding committed head's Gate, Python 3.12/3.13 tests and lint checks.
- [ ] Verify fresh Gate on the commit containing the latest eleven cases and label-outage fix. Local checks do not replace it.

Applied Black to the new Python file. Required whole-tree Black, CI whole-tree Black (**368 files unchanged**), CI whole-tree Ruff, and `git diff --check` pass. Commands, summaries and hashes are in [claim-label-followup.json](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/claim-label-followup.json). Full matched [baseline](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/claim-label-baseline-coverage.json.gz) and [final](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-810-coverage/claim-label-final-coverage.json.gz) coverage and pytest output are retained alongside it.

The checkout's Git metadata is read-only. A separate local bare clone under `/tmp/faa813-claims-handoff.git` preserves the handoff commit and `/tmp/faa813-claims-followup.bundle` without advancing the checkout branch. Publishing the commit and running fresh CI remain outstanding. The connector rejected the live PR title/body and task-checkbox update: `MCP tool call requires approval, but approval policy is never`. The verified checklist below is prepared locally; the live PR body was not changed. PR #813 was verified open with `isDraft=false`; no additional PR was opened.

<!-- auto-status-summary:start -->
## Automated Status Summary
#### Scope
Fine-Art-Archive reads 89.64% blended line+branch in CI; reaching 90% needs about 50 more covered statements+branches. Prioritize identity resolution / enrichment / API-surface modules.

The target order below is the Orchestrator's own ranking (escaped defects, then churn, then uncovered mass -- unchanged). Only the bundling is new: earlier rounds spent a whole PR on files with a handful of uncovered statements, so one PR now covers the next ranked targets until it has covered about 120 units.

#### Tasks
- [x] "Uncovered units" here come from the repository's whole CI run (every test file together). One test module's own suite can already cover more than CI's count shows for that module, and CI's figure is the one this PR is judged on: if your baseline differs, say so in the PR body and use CI's number.
- [x] Before you push, run the repository's own formatter and linter on every file you add or change, with the flags its CI `lint-format` and `lint-ruff` jobs use: one unformatted file fails a required check, and waiting for the autofix bot to repair it afterwards has not worked on lane PRs.

#### Acceptance criteria
- [ ] `pytest` passes in CI with the new tests, and each new test fails when the code it covers is deliberately broken (the PR body shows the break-and-revert run).
- [x] The PR's Gate coverage shows the targets' uncovered statements+branches down by about 120 or more, or the PR body explains each target that could not be meaningfully covered.
- [x] Production code changes only where a test found a real bug, each one explained in the PR body.

- [x] Same contract as every round in this initiative:
1. [x] Pick the next target by the repo's own coverage-gap ranking (escaped-defect priority, then
   churn, then uncovered mass), not by file size.
2. [x] Every new test must FAIL when the code it covers is deliberately broken and PASS when
   reverted -- run that break-and-revert for real and report it, don't assert it.
3. [x] Real bugs found while writing tests get fixed with a minimal, targeted diff in the same PR,
   not worked around. Watch for the negative-cache pattern (cache.get(key) is None used as a 'not yet cached' check, which can't tell 'never queried' from 'queried and got nothing') -- it has recurred independently four separate times fleet-wide already.
4. [x] Low blast radius only -- test-only or tightly-scoped fixes, no refactors.
5. [x] One PR per logical chunk of work.

- [x] The goal is to improve the code, not a metric. If you measure this repo at or above 90% before
- [x] starting, say so in a comment on this issue and close it without opening a PR -- do not
- [x] manufacture a fix just because a round was requested.

<!-- auto-status-summary:end -->


Closes #810
