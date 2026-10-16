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

## Ranked research-reporting API follow-up

At starting head `21c3082`, fresh full-suite coverage is **89.52%**, below the 90% stop condition. `api/main.py` remains the next target under the repository's repair-history proxy, churn, then uncovered-mass ranking: **27 proxy repairs, 56 touches, 69 missing statements + 42 missing branches**. The [refreshed ranking](research-gap-ranking.csv) uses all reachable commit history and missing statements plus branches. The proxy matches commit subjects against `\b(fix|bug|correct|repair|guard|regression)\w*`; it is not a verified escaped-defect count.

The review-contract test file and receipts removed in `21c3082` remain removed. Their earlier 25-unit gain is excluded from these measurements. This follow-up adds ten research-reporting HTTP cases: absent works leave no request or lock state; absent dossier UI produces a handled 404; reference authority includes exactly 8 and excludes unscored/below-threshold sources; reports count unread leads without exposing the source pool; and section, citation, and source-kind saturation are checked independently, below the overall score ceiling. Actual counts remain visible on a fully developed dossier.

No production defect was found and no production change is retained. This continues PR #804; no new PR is opened. All ten cases were individually run against temporary production-source mutations, failed, and passed after restoring the original bytes. Commands, complete outputs, exact mutations, coverage changes, and source/test hashes are in [research-reporting-proofs.json](research-reporting-proofs.json).

| Test case in `tests/test_api_research_reporting.py` | Deliberate defect | Broken | Restored |
|---|---|---|---|
| `test_unknown_work_does_not_create_research_state[report]` | Return the wrong status for an unknown research work | 1 failed, 1 warning in 0.93s (exit 1) | 1 passed, 1 warning in 0.46s (exit 0) |
| `test_unknown_work_does_not_create_research_state[request]` | Accept a research request for an unknown work | 1 failed, 1 warning in 1.06s (exit 1) | 1 passed, 1 warning in 0.45s (exit 0) |
| `test_missing_dossier_page_returns_a_handled_error` | Remove the missing dossier UI guard | 1 failed, 1 warning in 0.98s (exit 1) | 1 passed, 1 warning in 0.50s (exit 0) |
| `test_research_report_identifies_missing_authoritative_sources[unscored]` | Treat unscored references as high authority | 1 failed, 1 warning in 0.51s (exit 1) | 1 passed, 1 warning in 0.47s (exit 0) |
| `test_research_report_identifies_missing_authoritative_sources[below]` | Accept sources below the high-authority threshold | 1 failed, 1 warning in 0.53s (exit 1) | 1 passed, 1 warning in 0.47s (exit 0) |
| `test_research_report_identifies_missing_authoritative_sources[boundary]` | Exclude sources exactly at the high-authority threshold | 1 failed, 1 warning in 0.54s (exit 1) | 1 passed, 1 warning in 0.49s (exit 0) |
| `test_developed_dossier_saturates_score_without_hiding_actual_counts` | Clip reported section counts to the scoring cap | 1 failed, 1 warning in 0.53s (exit 1) | 1 passed, 1 warning in 0.47s (exit 0) |
| `test_dossier_score_saturates_each_evidence_component[section]` | Remove the section score saturation | 1 failed, 1 warning in 0.53s (exit 1) | 1 passed, 1 warning in 0.48s (exit 0) |
| `test_dossier_score_saturates_each_evidence_component[citations]` | Remove the citation score saturation | 1 failed, 1 warning in 0.52s (exit 1) | 1 passed, 1 warning in 0.50s (exit 0) |
| `test_dossier_score_saturates_each_evidence_component[source-kinds]` | Remove the source-kind score saturation | 1 failed, 1 warning in 0.52s (exit 1) | 1 passed, 1 warning in 0.48s (exit 0) |

Matched full-suite `api/main.py` coverage: **69 + 42 (93.95%) → 65 + 37 (94.44%)** missing statements + branches. This covers **9 additional units**, with 0 lost statements and 0 lost branches. Repository blended coverage rises **89.52% → 89.59%**. The original `verify.py` and `acquisition_flow.py` targets remain at **100%** with zero missing statements or branches; their previously established 62-unit improvement is preserved.

- Targeted coverage: **836 passed, 5 skipped, 1 warning in 102.22s (0:01:42)**. `api/main.py`: **94.44%**; both original target rows: **100%**.
- Baseline full suite: **4 failed, 2312 passed, 12 skipped, 1 warning in 157.77s (0:02:37)**.
- Final full suite: **4 failed, 2322 passed, 12 skipped, 1 warning in 160.60s (0:02:40)**.
- Both full suites have the same four `tests/test_workspace_conflict_guard.py` failures because `/home/runner/.cache/fine-art-archive` is read-only. No existing tests were disabled. Fresh CI acceptance for these changes remains pending.
- Whole-tree Black: **362 files unchanged**, exit 0. Changed-file Ruff and `git diff --check` pass.

Targeted command:
```bash
PYTHONPATH=/tmp/faa804-harness COVERAGE_FILE=/tmp/faa804-target-complete.coverage pytest tests/test_companion_api.py tests/test_companion_app*.py tests/test_api_*.py tests/test_review_gates.py tests/test_acquisition_review.py tests/test_eink_*.py tests/test_judgement_surfaces.py tests/test_subject_action_state.py tests/test_variant_candidate_path_confinement.py tests/test_variant_upgrade_labels_and_dims.py tests/test_deepzoom_*.py tests/test_healthz_manifest_drift.py tests/test_candidate_image_proxy.py tests/test_operator_messages_name_real_artifacts.py tests/test_quarantine_ttl_report.py tests/test_verify.py tests/test_verify_embeddings.py tests/test_site_anchored.py tests/test_coverage_round_799.py tests/test_acquisition_flow.py tests/test_acquisition_routing.py tests/test_dedup_cascade.py tests/test_source_quality_wiring.py -o addopts= -q -m 'not slow' --cov-reset --cov=fine_art_archive.api.main --cov=fine_art_archive.collect.verify --cov=fine_art_archive.collect.acquisition_flow --cov-report=term-missing --cov-report=json:/tmp/faa804-target-complete.json
```

Full-suite command (use `start` for the matched baseline):
```bash
PYTHONPATH=/tmp/faa804-harness COVERAGE_FILE=/tmp/faa804-final.coverage pytest tests/ -o addopts= -q -m 'not slow' --cov=src --cov-report=term --cov-report=json:/tmp/faa804-final.json
```

The commands use the unchanged temporary selector-polling harness documented in [verification-followup.json](verification-followup.json) because sandboxed socketpair wakeups are unavailable. The harness changes no repository code or tests.

Staging the verified tests failed because `.git/index.lock` cannot be created on the read-only `.git` filesystem. No commit or push was possible; the source tests and evidence are ready for the automation handoff. The connector rejected the PR title/body update: `MCP tool call requires approval, but approval policy is never`. Final readiness recheck confirms PR #804 is open with `draft=false`, still at `21c3082`. The five continuation checkboxes are supported by local evidence in this proposed body; the live PR body could not be updated.

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
