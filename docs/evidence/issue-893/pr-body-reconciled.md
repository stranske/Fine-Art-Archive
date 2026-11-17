Refs #893

Remove the frozen Q547923 / 50-sidecar worst-offender paragraph from the weekly review collision decision card. Collision clusters, counts, and classifications now render exclusively from the weekly review JSON payload (`coll['qids_on_multiple']`, `coll['extra_assignments']`, `coll['worst']`); the decision card is omitted when `qids_on_multiple` is zero.

Validation (2026-11-17, branch `cursor/issue-893` @ `2820525`):

- `python3 -m pytest tests/test_weekly_review_thumb_paths.py::test_collision_section_reports_only_payload_evidence -q -o addopts=` — pass
- Deliberate break at `scripts/render_weekly_review.py` (restored hardcoded Q547923 paragraph after the taxonomy list) — named test fails on `assert "Q547923" not in collision_block`; reverted — pass
- `python3 -m pytest tests/test_weekly_review_thumb_paths.py -q -o addopts=` — 20 passed

Deliberate-break receipts: `docs/evidence/issue-893-collision-card-deliberate-break.md`

<!-- auto-status-summary:start -->
## Automated Status Summary

**Progress:** 9/9 tasks complete

#### Scope
Remove the hardcoded Q547923 and 50-sidecar worst-offender paragraph from `coll_body` in `scripts/render_weekly_review.py` without retaining any static historical example inside the card. Render collision findings exclusively from `coll['qids_on_multiple']`, `coll['extra_assignments']`, and `coll['worst']` (with classification shown as unknown unless supplied by payload), omitting the section when collisions are zero.

#### Tasks
- [x] `scripts/render_weekly_review.py:343-358` — remove the static Q547923/Q488841 worst-offender paragraph and derive summary evidence strictly from `coll['worst']` with unknown classification
- [x] `tests/test_weekly_review_thumb_paths.py:390` — add `test_collision_section_reports_only_payload_evidence` covering 2-work Q123456 collision, variable cluster size, and zero-collision omission
- [x] Named test `tests/test_weekly_review_thumb_paths.py::test_collision_section_reports_only_payload_evidence` passes
- [x] Deliberate break → revert, shown in the PR (`docs/evidence/issue-893-collision-card-deliberate-break.md`)
- [x] The whole test file still passes: `python3 -m pytest tests/test_weekly_review_thumb_paths.py -q`

#### Acceptance criteria
- [x] Named collision regression test passes (Q123456 / count 2 / omits Q547923 and 50 sidecars / omits section on zero collisions)
- [x] Deliberate break → revert recorded in PR evidence
- [x] Full `tests/test_weekly_review_thumb_paths.py` suite passes

<!-- auto-status-summary:end -->