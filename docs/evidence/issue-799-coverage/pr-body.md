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
Each of the original 16 collected test cases was run separately against an actual, temporary production-source mutation; it failed. The source was restored before rerunning the same selected case; it passed. Restoration was protected by `finally`, and both production files match the starting head after the proofs. Every row below is an executed run, including each parameterized case. The combined acquisition configuration test has since been replaced by the eight independent cases documented below; its original receipt is retained as history.

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

## Acquisition follow-up

The combined configuration/artist test has been split into independent missing-config, empty-config, unknown-host, empty-candidate, and parameterized artist-name cases. This prevents a failure in the first assertion from standing in as mutation evidence for all later checks. The artist cases also check that a non-string name falls back to a label and blank fields fall back to `display_name`. No additional production change was needed.

All eight cases below were individually run against the stated source mutation and again after restoring the original bytes. At that revision, together with the 15 retained test cases from the original proof table, all 23 cases had an executed break-and-revert proof. Detailed output is in [acquisition-mutation-proofs.txt](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-799-coverage-verify-acquisition/docs/evidence/issue-799-coverage/acquisition-mutation-proofs.txt).

| Test case | Deliberate defect | Broken | Restored |
|---|---|---|---|
| `test_acquisition_missing_quality_config` | Raise ValueError instead of FileNotFoundError | 1 failed in 0.16s (exit 1) | 1 passed in 0.55s (exit 0) |
| `test_acquisition_quality_config_without_sources` | Accept a configuration with no sources | 1 failed in 0.16s (exit 1) | 1 passed in 0.11s (exit 0) |
| `test_acquisition_unknown_host_has_no_source_chain` | Invent a source chain for an unknown host | 1 failed in 0.16s (exit 1) | 1 passed in 0.12s (exit 0) |
| `test_acquisition_select_source_rejects_empty_candidates` | Omit the empty candidate guard | 1 failed in 0.16s (exit 1) | 1 passed in 0.11s (exit 0) |
| `test_acquisition_candidate_artist_name[blank-name]` | Invent an artist name when all name fields are blank | 1 failed in 0.16s (exit 1) | 1 passed in 0.11s (exit 0) |
| `test_acquisition_candidate_artist_name[label-fallback]` | Ignore the artist label fallback | 1 failed in 0.16s (exit 1) | 1 passed in 0.12s (exit 0) |
| `test_acquisition_candidate_artist_name[display-name-fallback]` | Ignore the display_name fallback | 1 failed in 0.16s (exit 1) | 1 passed in 0.12s (exit 0) |
| `test_acquisition_candidate_artist_name[non-string-artist]` | Turn a non-string artist into a name | 1 failed in 0.15s (exit 1) | 1 passed in 0.11s (exit 0) |

Fresh targeted coverage: **94 passed, 4 skipped in 3.09s**. Both `acquisition_flow.py` (127 statements + 38 branches) and `verify.py` (238 statements + 60 branches) remain at **100%**, with zero missing units. The earlier PR baseline and 62-unit improvement above remain unchanged; this follow-up strengthens the evidence rather than claiming additional covered units.

Fresh full-suite baseline at `38d72e0`: **4 failed, 2294 passed, 12 skipped in 107.83s**; blended coverage **89.51%**, so the 90% stop condition does not apply. Final full-suite result: **4 failed, 2301 passed, 12 skipped in 104.57s**, with the same four read-only-home failures and unchanged **89.51%** blended coverage. Both runs use `pytest tests/ -o addopts= --cov=src --cov-report=term --cov-report=json:<separate report path> -q -m 'not slow'`. The same temporary selector-polling harness described above is needed in this sandbox. No tests are disabled to hide filesystem failures.

Before this follow-up, [Gate passed on `38d72e0`](https://github.com/stranske/Fine-Art-Archive/actions/runs/38956189223). Acceptance for the new commit's CI remains pending. Whole-tree Black (361 files), changed-file Ruff, and `git diff --check` pass. Commands, fresh coverage summaries, production-source hashes, and mutation results are in [acquisition-followup.json](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-799-coverage-verify-acquisition/docs/evidence/issue-799-coverage/acquisition-followup.json).

## Verification follow-up

Two combined verification tests have been replaced by nine independent cases. The vector cases separately check matching, unequal-length, and zero vectors; site identity separately checks category and identifiers; place similarity separately checks empty references, missing backend, unreadable references, and invalid reference vectors. Assertions also verify the diagnostic and result details. No production change was needed.

Each case below was run against an actual temporary mutation of `collect/verify.py`, failed, then passed after the original source bytes were restored. Together with the 21 retained cases documented above, all **30 current cases** have individual executed proofs. Full output: [verification-mutation-proofs.txt](verification-mutation-proofs.txt); commands and hashes: [verification-followup.json](verification-followup.json).

| Test case | Deliberate defect | Broken | Restored |
|---|---|---|---|
| `test_embedding_similarity_validates_vectors[matching]` | Reject matching embeddings | 1 failed in 0.20s (exit 1) | 1 passed in 0.53s (exit 0) |
| `test_embedding_similarity_validates_vectors[length-mismatch]` | Remove vector-length validation | 1 failed in 0.19s (exit 1) | 1 passed in 0.14s (exit 0) |
| `test_embedding_similarity_validates_vectors[zero-vector]` | Remove zero-vector validation | 1 failed in 0.19s (exit 1) | 1 passed in 0.14s (exit 0) |
| `test_site_identity_rejects_missing_anchors[wrong-category]` | Remove site-category guard | 1 failed in 0.17s (exit 1) | 1 passed in 0.13s (exit 0) |
| `test_site_identity_rejects_missing_anchors[missing-site-identifiers]` | Remove site-identifier guard | 1 failed in 0.17s (exit 1) | 1 passed in 0.13s (exit 0) |
| `test_place_similarity_rejects_empty_references` | Accept an empty reference set | 1 failed in 0.18s (exit 1) | 1 passed in 0.14s (exit 0) |
| `test_place_similarity_rejects_unavailable_backend` | Skip rather than fail an unavailable site backend | 1 failed in 0.18s (exit 1) | 1 passed in 0.13s (exit 0) |
| `test_place_similarity_rejects_unreadable_reference` | Accept an unreadable reference | 1 failed in 0.20s (exit 1) | 1 passed in 0.16s (exit 0) |
| `test_place_similarity_rejects_invalid_reference_vector` | Accept an invalid reference vector | 1 failed in 0.18s (exit 1) | 1 passed in 0.14s (exit 0) |

The starting full suite at `62b7bde` measured **89.51%** blended coverage, with **4 failed, 2301 passed, 12 skipped**. The same four read-only-home failures described above remain environmental blockers. The existing [Gate run for `62b7bde`](https://github.com/stranske/Fine-Art-Archive/actions/runs/38959783307) passed; CI for this follow-up is still pending.

Final targeted coverage: **101 passed, 4 skipped in 3.27s**, both target rows **100%** with zero missing statements or branches. Final full suite: **4 failed, 2308 passed, 12 skipped in 119.25s**, with exactly the same four read-only-home failures and unchanged **89.51%** blended coverage. No additional covered units are claimed for this follow-up. All 30 collected cases match executed RED/GREEN receipts. Whole-tree Black (361 files), changed-file Ruff, and `git diff --check` passed.

Prior iteration reconciliation: both coverage targets were verified complete, and their completed checkboxes and mutation proofs were recorded here. The GitHub connector confirmed PR #804 was open with draft=false, but its live body update required unavailable approval. Git staging was also blocked by the read-only `.git` directory. The automation subsequently committed that iteration as `d739ecc`.

## Acquisition assessment follow-up

Reviewed `9dfd595`, `38d72e0`, `62b7bde`, and `d739ecc` before continuing. A fresh starting targeted run on `d739ecc` passed **101 tests, 4 skipped**, with both targets at **100%**. The first unchecked coverage task in the live body is already implemented; this file's reconciled checkboxes remain the accurate local record. An attempt to update the live PR body was rejected: `MCP tool call requires approval, but approval policy is never`.

Four acquisition-level regression cases now exercise the existing backend bug fix through `assess_master`. Matching and different reference images are assessed when either pHash or dHash raises `ValueError`. The latter also checks recovery after pHash has already returned a misleading zero distance. Matching images must pass and different images must fail, with fallback distances, the blocking hash result, quality, and fitness preserved. No production changes were needed.

Each new case was individually run with a temporary production mutation, then with the exact original bytes restored:

| New case suffix | Deliberate defect | Broken | Restored |
|---|---|---|---|
| `same-work-phash` | Remove the ValueError fallback | 1 failed in 0.21s (exit 1) | 1 passed in 0.24s (exit 0) |
| `same-work-dhash` | Remove the ValueError fallback | 1 failed in 0.21s (exit 1) | 1 passed in 0.12s (exit 0) |
| `different-work-phash` | Discard the fallback average-hash distance | 1 failed in 0.16s (exit 1) | 1 passed in 0.13s (exit 0) |
| `different-work-dhash` | Discard the fallback average-hash distance | 1 failed in 0.22s (exit 1) | 1 passed in 0.13s (exit 0) |

All four are parameters of `test_acquisition_assessment_preserves_identity_when_hash_backend_breaks`. Together with the prior 30 cases, all **34 cases** have executed break-and-revert receipts. Commands and full output are in [acquisition-boundary-mutation-proofs.txt](acquisition-boundary-mutation-proofs.txt); hashes and coverage summaries are in [acquisition-boundary-followup.json](acquisition-boundary-followup.json).

Final targeted run: **105 passed, 4 skipped in 2.84s**. Both targets remain at **100%**, with zero missing statements or branches. The PR's 62-unit improvement is unchanged; these tests validate the existing production fix through its acquisition caller. Whole-tree Black (**361 files**), changed-file Ruff, and `git diff --check` passed.

Final full suite: **4 failed, 2312 passed, 12 skipped in 103.21s**, with exactly the same four read-only-home failures as the prior baseline. Blended coverage is **89.52%**. No tests were disabled or skipped to hide those failures, and the full-suite-green task remains unchecked. The run uses `PYTHONPATH=/tmp/faa804-harness COVERAGE_FILE=/tmp/faa804-boundary-full.coverage pytest tests/ -o addopts= -q -m 'not slow' --cov=src --cov-report=term --cov-report=json:/tmp/faa804-boundary-full.json`; the unchanged external selector-polling harness is recorded in `verification-followup.json`.

The starting head `d739ecc` has a successful [Gate run](https://github.com/stranske/Fine-Art-Archive/actions/runs/38961466698), including passing [Python 3.12](https://github.com/stranske/Fine-Art-Archive/actions/runs/38961466698/job/117177542253) and [Python 3.13](https://github.com/stranske/Fine-Art-Archive/actions/runs/38961466698/job/117177542269) unit-test jobs. These results validate the preceding iteration, not these four uncommitted cases. CI acceptance stays unchecked for the additions.

PR #804 was rechecked open with draft=false. Its live body update remains blocked by the approval policy. Staging these changes failed with `Unable to create '.git/index.lock': Read-only file system`; no commit or push was possible. The new tests, receipts, and reconciled body remain in the working tree for the automation handoff.

## Ranked review API follow-up

The next target is `api/main.py`, selected from the latest 500 reachable commits
at `4a68aea` using the repository's documented ranking: repair-history proxy,
then churn, then missing lines, with path as the tie-breaker. The proxy counts
commit subjects matching `\b(fix|bug|correct|repair|guard|regression)\w*`; it is
not a verified escaped-defect count. The target has 27 proxy repairs, 54 touches,
and 69 missing statements + 42 missing branches in the fresh baseline.
The [complete ranking](review-gap-ranking.csv) records every measured gap.
The previously selected verification and acquisition targets remain at 100%.

Ten new HTTP regression cases in `tests/test_api_review_contracts.py` cover
review gate summaries, item limits and ordering, unknown gates, early rejection
of zero limits, missing artist identities, and labels supplied by later works.
No production defect was exposed and no production change was retained.
This remains one bounded follow-up on PR #804; no new PR was created.

Each case below failed with its own temporary production mutation and passed
after exact byte restoration. The [executed harness](review-mutation-harness.txt)
and [full RED/GREEN receipts](review-mutation-proofs.json) retain the commands,
mutations, outputs, exits, and original production SHA-256.

| Test case | Deliberate defect | Broken | Restored |
|---|---|---|---|
| `test_review_lists_reject_zero_limit_before_loading_state[acquisitions]` | Allow a zero limit to reach the review state loader | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_review_lists_reject_zero_limit_before_loading_state[review/works]` | Allow a zero limit to reach the review state loader | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_review_lists_reject_zero_limit_before_loading_state[review/artists]` | Allow a zero limit to reach the review state loader | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_review_lists_reject_zero_limit_before_loading_state[review/held]` | Allow a zero limit to reach the review state loader | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_gate_details_preserve_summary_and_item_order[truncated]` | Ignore the requested item limit | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_gate_details_preserve_summary_and_item_order[all-items]` | Report zero returned items for a populated gate | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_unknown_gate_is_404_even_when_other_gates_exist[no-gates]` | Return the wrong status for an unknown gate | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_unknown_gate_is_404_even_when_other_gates_exist[other-gate]` | Return the wrong status after searching unrelated gates | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_artist_review_omits_candidates_without_artist_identity` | Include candidates that cannot identify their artist | 1 failed (exit 1) | 1 passed (exit 0) |
| `test_artist_review_recovers_label_from_a_later_work` | Discard the artist label supplied by a later work | 1 failed (exit 1) | 1 passed (exit 0) |

Targeted validation passes **161 tests, 4 skipped**; `collect/verify.py` and
`collect/acquisition_flow.py` both show **100%**. The review-only selection passes
**56 tests** and the unchanged 25% coverage floor. Running only the 10 added
cases initially passed all tests but failed that floor (20.32% over the entire
API module); the broader targeted selection fixes the measurement scope without
changing the floor. Whole-tree Black checks **362 files**; changed-file Ruff and
`git diff --check` pass.

Matched full-suite measurements cover **25 more units** (14 statements + 11
branches) in `api/main.py`: **69 + 42 missing (93.95%) → 55 + 31 missing
(95.32%)**. No previously covered API statements or branches were lost.
Repository blended coverage rises **89.52% → 89.71%**. The original targets
remain **100%**; this adds 25 units to the PR's previously established 62-unit
improvement. The fresh starting result is below 90%, so the stop rule does not
apply.

Baseline: **4 failed, 2312 passed, 12 skipped in 124.24s**. Candidate:
**4 failed, 2322 passed, 12 skipped in 126.98s**. The four failures are exactly
the baseline read-only-home failures documented above. No tests were disabled,
no coverage floor changed, and no new production bug was found. Full commands,
exact coverage summaries, changed arcs, source hashes, and environment details
are in [review-followup.json](review-followup.json).

The starting commit `4a68aea` passed [Gate](https://github.com/stranske/Fine-Art-Archive/actions/runs/38962798201),
including both Python 3.12 and 3.13 unit-test and coverage jobs. This verifies the
preceding iteration only; CI for these new tests remains pending. The five
continuation-contract items below have local implementation evidence: current
ranking, individual executed proofs, no new production bug, test-only scope,
and the same PR #804.

PR #804 was rechecked **open** with **draft=false**. Staging the source tests and
receipts failed with `Unable to create '.git/index.lock': Read-only file system`.
The sandbox therefore prevents a commit or push; the source changes and verified
receipts remain available for the automation handoff. The GitHub connector also
rejected the prepared PR title/body update with `MCP tool call requires approval,
but approval policy is never`; the live PR's five continuation checkboxes could
not be reconciled. This file remains the complete proposed body and proof table.

## Tasks

- [x] Cover `src/fine_art_archive/collect/verify.py` (50 uncovered statements+branches): write tests under `tests/` for its untested lines and branches.
- [x] Cover `src/fine_art_archive/collect/acquisition_flow.py` (12 uncovered statements+branches): write tests under `tests/` for its untested lines and branches.
- [x] For each new test, run the break-and-revert proof (break the code it covers, `pytest` fails; revert, `pytest` passes) and record both results in the PR body.
- [ ] If a test exposes a real bug in a target above, fix it with the smallest diff and show `pytest tests/` green again.
- [x] Open ONE PR whose body states each target's coverage before and after (from `pytest --cov`) and has a closing line for THIS issue (`Closes #<this issue's number>`), so the round closes when the PR merges.

## Acceptance criteria

- [ ] `pytest` passes in CI with the new tests, and each new test fails when the code it covers is deliberately broken (the PR body shows the break-and-revert run).
- [ ] The PR's Gate coverage shows the targets' uncovered statements+branches down by about 60 or more, or the PR body explains each target that could not be meaningfully covered.
- [x] Production code changes only where a test found a real bug, each one explained in the PR body.
- [x] Same contract as every round in this initiative:
  1. [x] Pick the next target by the repo's own coverage-gap ranking (escaped-defect priority, then churn, then uncovered mass), not by file size.
  2. [x] Every new test must FAIL when the code it covers is deliberately broken and PASS when reverted -- run that break-and-revert for real and report it, don't assert it.
  3. [x] Real bugs found while writing tests get fixed with a minimal, targeted diff in the same PR, not worked around. Watch for the negative-cache pattern.
  4. [x] Low blast radius only -- test-only or tightly-scoped fixes, no refactors.
  5. [x] One PR per logical chunk of work.
- [x] The goal is to improve the code, not a metric. The measured starting coverage is below 90%; no new PR was opened for this follow-up.

This ready-for-review PR continues to supersede #803 on the registry branch. Fresh-head CI remains the outstanding acceptance check; no waiver is inferred from the local evidence.

Closes #799
