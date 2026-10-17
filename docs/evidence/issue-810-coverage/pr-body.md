The master-facts loader now treats JSON caches whose `entries` field is a list or null as a cache miss. Previously those shapes raised `AttributeError` and could break acquisition review. Two new regressions reproduced the failure before the four-line guard was added.

The PR adds 65 offline cases for API delivery, review gates, store recovery, museum artist resolution, and discovery. The final production diff is limited to the cache-shape guard. Targets follow `issue-799-coverage/review-gap-ranking.csv`: `api/main.py`, then `api/store.py`, then `enrichment/source_resolver.py`; the ranking's repair-history proxy is not asserted to be a verified escaped-defect count.

- [x] Use whole-suite coverage as the baseline and disclose differences from CI. The supplied CI baseline is **89.64%**; the fresh starting-head whole-suite baseline is **89.9790326%** (2335 passed, 12 skipped, four environment failures). The rounded table says 90%, but the unrounded measurement is below the stop threshold. CI's counts remain authoritative for Gate acceptance.
- [x] Run the repository's Black and Ruff checks before committing. Both whole-tree Black commands pass for 367 files; whole-tree Ruff and `git diff --check` pass.
- [x] Verify each added test with an executed break-and-revert run. All 55 cases added in this round, plus all ten inherited API/discovery cases, individually fail under mutation (exit 1) and pass after restoration (exit 0). See [the receipt index](mutation-summary.md) and [exact mutations and outputs](mutation-proofs.json.gz).
- [x] Confirm the final full-suite coverage improvement: **89.9790% → 90.9801%**, with **135 fewer missing target units**.
- [ ] Verify fresh-head pytest and the ~120-unit reduction in Gate coverage. GitHub access is unavailable; local evidence does not replace this required check.

The starting local run fails four tests in `test_workspace_conflict_guard.py` because `/home/runner/.cache/fine-art-archive` is read-only. No tests were disabled to hide those failures. The temporary external polling harness used by prior coverage rounds is needed here too: it bounds selector waits because sandboxed socketpair writes cannot wake the event loop. It changes no repository code or tests. Black uses one worker because sandboxed multiprocessing sockets are unavailable.

GitHub API access is unavailable in this environment (`gh pr view` reports a connection failure). Updating the live PR body and verifying fresh Gate results require a connected run; this file is the prepared PR description.


Whole-suite target measurements (statements + branches missing):

| Ranked target | Published CI reference | Local before | Local after | Local reduction | Final cover |
|---|---:|---:|---:|---:|---:|
| `api/main.py` | 69 + 42 = 111 | 63 + 35 = 98 | 3 + 10 = 13 | 85 | 99.29% |
| `api/store.py` | 20 + 6 = 26 | 20 + 6 = 26 | 0 + 1 = 1 | 25 | 99.82% |
| `enrichment/source_resolver.py` | 95 + 88 = 183 | 95 + 88 = 183 | 81 + 77 = 158 | 25 | 85.99% |

The published reference is the repository's whole-CI ranking in `docs/evidence/issue-799-coverage/review-gap-ranking.csv`; it remains the CI comparison basis. The final local targets have 148 fewer missing units than that published reference, while the matched local runs establish 135. A fresh Gate run must confirm the CI delta. The earlier head already contains the API/discovery tests, so the fresh baseline includes those tests rather than crediting them again. The cache fix adds three statements and two branches, all covered; those new units are not counted as formerly uncovered units.

Final full suite: **2390 passed, 12 skipped, four unchanged read-only-home failures** in 159.63 seconds. New-test targeted run: **55 passed**. No other failures were introduced. Baseline and final runs both use `pytest tests/ -o addopts= --cov=src -q -m 'not slow'` with distinct coverage data/report paths. Exact commands, module summaries, environment limitations, and source hashes are in [validation.json](validation.json); full reports and outputs are compressed beside it.

All **65** PR-added cases were run individually against a temporary production mutation and again after restoring the exact source bytes: **65 failed broken / 65 passed restored**. This includes the ten API/discovery cases from the starting head. Every mutation and both complete pytest outputs are retained in [mutation-proofs.json.gz](mutation-proofs.json.gz), indexed in [mutation-summary.md](mutation-summary.md). The two failing cache-shape regressions before the fix are separately retained in [cache-bug-before-fix.txt.gz](cache-bug-before-fix.txt.gz).

The remaining API lines are the Pydantic v1 compatibility fallbacks and the zero-attempt retry fallback; this chunk does not synthesize unsupported runtime conditions to cover them. Remaining resolver paths are outside the bounded ~120-unit chunk. No target is claimed fully covered.

- [x] Pick targets in repository ranking order, rather than by file size.
- [x] Fix real bugs found by tests with a minimal production diff; the only fix is the malformed cache `entries` guard described above.
- [x] Keep the work to one logical API/enrichment coverage chunk, without refactors.

Required checks executed locally:

```bash
black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
black --check --line-length 100 --exclude '(\.venv|\.workflows-lib|node_modules)' .
ruff check --output-format github --extend-exclude .workflows-lib .
git diff --check
```

Both Black checks pass for all 367 Python files. Ruff and whitespace checks pass. Black formatting was also applied to all changed Python files before these checks.


Commit handoff is blocked by the execution environment: staging the scoped files fails with `Unable to create .git/index.lock: Read-only file system`. No commit or push was created. The existing branch is `codex/issue-810-api-discovery-coverage`, still at `e2ea975175e5eb16abc963db1abad3f670e9918f`. The source change, three new test files, and evidence are ready for a runner with writable Git metadata. The live PR state, ready-for-review flag, and fresh CI results remain unverified because GitHub API access fails.
