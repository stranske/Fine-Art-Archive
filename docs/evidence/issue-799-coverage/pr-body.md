## Summary
Verification now has regressions for hash thresholds, fallback image discrimination, normalized OpenCLIP output, invalid inputs, and selection of the strongest site reference. Acquisition tests cover missing configuration and optional staged metadata.

The existing production fix in this PR handles an imagehash/SciPy backend raising `ValueError` by using the documented local hash fallback. No additional production changes were needed while strengthening the tests.

## Measured coverage
| Target | Before: statements + branches missing | Before | After: statements + branches missing | After |
|---|---:|---:|---:|---:|
| `collect/verify.py` | 42 + 8 | 83.22% | 0 + 0 | 100% |
| `collect/acquisition_flow.py` | 5 + 7 | 92.73% | 0 + 0 | 100% |

This PR covers all **62** ranked target units. Repository blended line/branch coverage in the matched local runs rises **89.06% → 89.51%**. The baseline uses current production code with this PR's added `tests/test_coverage_round_799.py` excluded; the final run includes it. Both runs use `pytest --cov=src` and branch coverage. These fresh matched measurements replace the earlier repository-wide estimates.

## Validation
- Targeted coverage: **87 passed, 4 skipped in 5.21s**; both target rows show **100%**, with zero missing statements or branches.
- Baseline full suite: **4 failed, 2278 passed, 12 skipped, 1 warning in 158.43s (0:02:38)**.
- Final full suite: **4 failed, 2294 passed, 12 skipped, 1 warning in 160.51s (0:02:40)**.
- Both local full-suite runs have the same four failures in `tests/test_workspace_conflict_guard.py`: the sandbox makes `/home/runner/.cache/fine-art-archive` read-only. No tests were disabled or skipped to hide the failures.
- Before this follow-up, CI's Python [3.12](https://github.com/stranske/Fine-Art-Archive/actions/runs/38954235393/job/117153224143) and [3.13](https://github.com/stranske/Fine-Art-Archive/actions/runs/38954235393/job/117153224049) jobs passed on production head `9dfd595`. Fresh-head CI acceptance remains unchecked below.
- Whole-tree Black check passed for all 361 Python files; changed-file Ruff and `git diff --check` passed.

Targeted command:
```bash
pytest tests/test_verify.py tests/test_verify_embeddings.py tests/test_site_anchored.py tests/test_coverage_round_799.py tests/test_acquisition_flow.py tests/test_acquisition_routing.py tests/test_dedup_cascade.py tests/test_source_quality_wiring.py -m 'not slow' --cov-reset --cov=fine_art_archive.collect.verify --cov=fine_art_archive.collect.acquisition_flow --cov-report=term-missing --cov-report=json:/tmp/coverage-799-target-after.json --cov-report=xml:/tmp/coverage-799-target-after.xml
```

Formatting:
```bash
black --line-length 100 tests/test_coverage_round_799.py
black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check src/fine_art_archive/collect/verify.py tests/test_coverage_round_799.py
```

The local full-suite and Black runs used a temporary external selector-polling harness because sandboxed socketpair writes return EPERM and otherwise hang event-loop thread completion. Black also used one worker because forkserver sockets are unavailable. The harness changes no repository source or tests. Commands, exact coverage summaries, environment details, and file hashes are in [validation.json](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-799-coverage-verify-acquisition/docs/evidence/issue-799-coverage/validation.json).

## Executed break-and-revert proofs
Each of the 16 collected test cases was run separately against an actual, temporary production-source mutation; it failed. The source was restored before rerunning the same selected case; it passed. Restoration was protected by `finally`, and both production files match the starting head after the proofs. Every row below is an executed run, including each parameterized case.

| Test case in `tests/test_coverage_round_799.py` | Deliberate defect | Broken | Restored |
|---|---|---|---|
| `test_report_unverified_inputs_distinguish_skip_from_failure` | Report unverified-only checks as PASS | 1 failed in 0.26s (exit 1) | 1 passed in 0.22s (exit 0) |
| `test_perceptual_hash_falls_back_when_imagehash_backend_raises_value_error` | Remove ValueError fallback | 1 failed in 0.29s (exit 1) | 1 passed in 0.23s (exit 0) |
| `test_perceptual_hash_uses_working_imagehash_backend[phash-at-threshold]` | Reject pHash exactly at threshold | 1 failed in 0.69s (exit 1) | 1 passed in 0.22s (exit 0) |
| `test_perceptual_hash_uses_working_imagehash_backend[dhash-at-threshold]` | Reject dHash exactly at threshold | 1 failed in 0.28s (exit 1) | 1 passed in 0.25s (exit 0) |
| `test_perceptual_hash_uses_working_imagehash_backend[both-over-threshold]` | Accept when both hashes exceed threshold | 1 failed in 0.28s (exit 1) | 1 passed in 0.23s (exit 0) |
| `test_perceptual_hash_fallback_preserves_image_discrimination[same-work]` | Add a spurious bit difference to fallback hashes | 1 failed in 0.28s (exit 1) | 1 passed in 0.22s (exit 0) |
| `test_perceptual_hash_fallback_preserves_image_discrimination[different-work]` | Make fallback hashes identical for every image | 1 failed in 0.27s (exit 1) | 1 passed in 0.23s (exit 0) |
| `test_open_clip_backend_wraps_model_embedding` | Omit embedding normalization | 1 failed in 0.26s (exit 1) | 1 passed in 0.22s (exit 0) |
| `test_embedding_and_site_identity_reject_invalid_inputs` | Remove vector length validation | 1 failed in 0.27s (exit 1) | 1 passed in 0.23s (exit 0) |
| `test_place_similarity_handles_empty_unavailable_and_invalid_references` | Pass an empty reference set | 1 failed in 0.28s (exit 1) | 1 passed in 0.25s (exit 0) |
| `test_place_similarity_records_best_of_multiple_references[later-best]` | Keep the first reference even when a later match is better | 1 failed in 0.28s (exit 1) | 1 passed in 0.23s (exit 0) |
| `test_place_similarity_records_best_of_multiple_references[earlier-best]` | Overwrite the best reference with a worse later match | 1 failed in 0.28s (exit 1) | 1 passed in 0.23s (exit 0) |
| `test_place_similarity_records_best_of_multiple_references[tie-keeps-first]` | Overwrite the first reference on a tie | 1 failed in 0.28s (exit 1) | 1 passed in 0.23s (exit 0) |
| `test_verify_reports_unreadable_candidate_as_aspect_failure` | Skip instead of failing an unreadable aspect candidate | 1 failed in 0.27s (exit 1) | 1 passed in 0.22s (exit 0) |
| `test_acquisition_configuration_and_artist_name_failure_paths` | Raise the wrong error for missing routing configuration | 1 failed in 0.27s (exit 1) | 1 passed in 0.22s (exit 0) |
| `test_acquisition_flow_accepts_work_without_metadata` | Require the optional staged metadata file | 1 failed in 0.30s (exit 1) | 1 passed in 0.24s (exit 0) |

Full RED/GREEN output: [mutation-proofs.txt](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-799-coverage-verify-acquisition/docs/evidence/issue-799-coverage/mutation-proofs.txt). In particular, removing `ValueError` from the fallback handler reproduces the real backend bug and restoring it passes.

<!-- pr-preamble:start -->
<!-- meta:issue:799 -->
> **Source:** Issue #799

Closes #799

<!-- pr-preamble:end -->

<!-- auto-status-summary:start -->
## Automated Status Summary
#### Scope
Fine-Art-Archive reads 89.11% blended line+branch in CI; reaching 90% needs about 124 more covered statements+branches. Prioritize identity resolution / enrichment / API-surface modules.

The target order below is the Orchestrator's own ranking (escaped defects, then churn, then uncovered mass -- unchanged). Only the bundling is new: earlier rounds spent a whole PR on files with a handful of uncovered statements, so one PR now covers the next ranked targets until it has covered about 60 units.

#### Tasks
- [x] Cover `src/fine_art_archive/collect/verify.py` (50 uncovered statements+branches): write tests under `tests/` for its untested lines and branches.
- [x] Cover `src/fine_art_archive/collect/acquisition_flow.py` (12 uncovered statements+branches): write tests under `tests/` for its untested lines and branches.
- [x] For each new test, run the break-and-revert proof (break the code it covers, `pytest` fails; revert, `pytest` passes) and record both results in the PR body.
- [x] If a test exposes a real bug in a target above, fix it with the smallest diff and show `pytest tests/` green again.
- [x] Open ONE PR whose body states each target's coverage before and after (from `pytest --cov`) and has a closing line for THIS issue (`Closes #<this issue's number>`), so the round closes when the PR merges.

#### Acceptance criteria
- [ ] `pytest` passes in CI with the new tests, and each new test fails when the code it covers is deliberately broken (the PR body shows the break-and-revert run).
- [ ] The PR's Gate coverage shows the targets' uncovered statements+branches down by about 60 or more, or the PR body explains each target that could not be meaningfully covered.
- [x] Production code changes only where a test found a real bug, each one explained in the PR body.

- [x] Same contract as every round in this initiative:
1. [ ] Pick the next target by the repo's own coverage-gap ranking (escaped-defect priority, then
   churn, then uncovered mass), not by file size.
2. [ ] Every new test must FAIL when the code it covers is deliberately broken and PASS when
   reverted -- run that break-and-revert for real and report it, don't assert it.
3. [ ] Real bugs found while writing tests get fixed with a minimal, targeted diff in the same PR,
   not worked around. Watch for the negative-cache pattern (cache.get(key) is None used as a 'not yet cached' check, which can't tell 'never queried' from 'queried and got nothing') -- it has recurred independently four separate times fleet-wide already.
4. [ ] Low blast radius only -- test-only or tightly-scoped fixes, no refactors.
5. [ ] One PR per logical chunk of work.

- [x] The goal is to improve the code, not a metric. If you measure this repo at or above 90% before
- [x] starting, say so in a comment on this issue and close it without opening a PR -- do not
- [x] manufacture a fix just because a round was requested.

**Head SHA:** 9dfd5951fc036bb1a0680d539c3a05374cd08ad0
**Latest Runs:** ❔ in progress — Gate
**Required:** gate: ❔ in progress

| Workflow / Job | Result | Logs |
|----------------|--------|------|
| Backplane Conformance | ✅ success | [View run](https://github.com/stranske/Fine-Art-Archive/actions/runs/38951677814) |
| Cross-Repo Smoke | ⏭️ skipped | [View run](https://github.com/stranske/Fine-Art-Archive/actions/runs/38951677802) |
| Gate | ❔ in progress | [View run](https://github.com/stranske/Fine-Art-Archive/actions/runs/38951676708) |
| Health 45 Agents Guard | ✅ success | [View run](https://github.com/stranske/Fine-Art-Archive/actions/runs/38951675959) |
| PR 46 Dependency Repair Contract | ⏭️ skipped | Last completed result; current run in PR checks |
<!-- auto-status-summary:end -->

## Registry routing replacement
Supersedes #803 at unchanged implementation head `9dfd5951fc036bb1a0680d539c3a05374cd08ad0`. The original coverage-autopilot Codex agent completed with rc0 and released its target claim before this repair. This replacement uses the registry branch and matching Codex/auto/keepalive/autofix routing; no implementation change or new source issue is introduced. Preserve the original local coverage and break/revert receipts. Current lint-format failure and incomplete product CI remain real until the routed worker repairs or completes them; no check waiver or CodeRabbit approval is inferred.

Closes #799.


Closes #799

