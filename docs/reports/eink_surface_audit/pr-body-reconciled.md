Refs #805

The companion's preview, saved-feed and SD export paths share selection and rendering inputs. The audit in `docs/reports/eink_surface_divergence_audit.md` inventories all 17 playlist fields, request-only evidence, render defaults, navigation and validator identity, with source references and bounded test-layer claims.

Existing repairs are #784/#786/#788; current owners are #806/#807/#808. P1 remains intentionally unsupported evidence persistence. P2/P3 remain review candidates under #805's separate publication boundary; no new dedicated issues were filed.

Added a Node-executed regression in `tests/test_eink_pipeline.py` that compares actual preview/save/export request producers for default/contain/cover/stretch fit. Disconnecting fit in the preview image URL fails the cover case on the missing query input; byte-identical restoration passes. Red/green receipts are in `docs/reports/eink_surface_audit/ui-inputs-*.{txt,json}`. The final diff has no `src/` changes, and existing test assertions remain unchanged.

Validation: 205 passed across the four named suites with `-m "not slow"`; all four new cases passed, and no tests were skipped. The required repository-wide Black check passed (370 files unchanged). These fixture and request checks make no physical-panel acceptance claim.

Remote publication is pending: the CLI cannot connect, and the connector rejected the PR-body update, blocker comment and needs-human label because approval is required while this run's policy is never. These reconciled checkboxes are proposed local state until applied to GitHub. Read-only verification confirmed this PR is open and ready for review. Physical-panel acceptance remains unverified.

The required commit attempt was blocked by the runner's read-only `.git` mount before staging (`index.lock` could not be created). The new regression and receipts remain workspace changes pending a permitted commit.

<!-- pr-preamble:start -->
<!-- meta:related-issue:805 -->
> **Source:** Issue #805

Related to #805

<!-- pr-preamble:end -->

<!-- auto-status-summary:start -->
## Automated Status Summary
#### Scope
Three independently found defects share one shape: an input or policy that companion preview computes is consumed differently by saved-playlist resolution, the feed or SD export. A15 evidence is derived at `src/fine_art_archive/api/main.py:635` but omitted at :785-794 and :2042-2057; A11 strategy is reported at :688-698 and :830-844 but not applied by `src/fine_art_archive/eink/targets.py:206`; and the feed validator at :2096-2105 omits the fit input actually rendered. `docs/PRODUCT_CONTRACT.md:7` and `docs/A_SERIES_ROADMAP.md:10` promise that preview matches delivery. Fixing only the three known sites leaves no check that a fourth input diverges later.

Current source readback: `src/fine_art_archive/ui/index.html:3179` at `84b50094050db03522a2e80c09617c0cc46cb5e2` (file SHA-256 `d65b9650f582633754b8b8f014dd847d7def95a1e1d02de39fad44484f4f2a52`). Earlier detailed line ranges and reproductions retain their reviewed-commit provenance; intervening anchor changes were checked for relevance.

#### Tasks
- [x] Create `docs/reports/eink_surface_divergence_audit.md` with the already-approved surface inventory, dispositions and owned follow-up mappings.

- [x] Enumerate inputs consumed by `eink_preview` (`src/fine_art_archive/api/main.py:713`), `_resolve_playlist` (:2042), `_render_feed_image` (:2086) and `eink_playlist_export` (:772) using `rg` over `src/fine_art_archive/api/main.py` and `src/fine_art_archive/eink/`.
- [x] Trace the helpers in `src/fine_art_archive/display/render.py:235` and `src/fine_art_archive/preference/exhibition.py:58` and verify each edge in source.
- [x] Classify each instance in the matrix inside the new audit report (named `eink_surface_divergence_audit.md`, placed under `docs/reports/`) as already-correct, confirmed-bug, needs-investigation or intentionally-unsupported, citing source, test and `docs/PRODUCT_CONTRACT.md` line.
- [x] Write the new audit report `eink_surface_divergence_audit.md` into the `docs/reports/` directory with the inspected commit, matrix and per-instance dispositions, separating inspected tests from executed probes.
- [x] Record for each cited test (`tests/test_eink_pipeline.py`, `tests/test_eink_feed_endpoints.py`, `tests/test_eink_export_format.py`, `tests/test_render_strategy.py`) whether it checks IDs, reported policy, image bytes, HTTP validators or SD output.
- [ ] File one follow-up issue per uncovered instance after dedup by running `gh issue list --repo stranske/Fine-Art-Archive --search divergence`, and link each filed issue in the report.

#### Acceptance criteria
- [x] `docs/reports/eink_surface_divergence_audit.md` exists and records commit, enumeration method, input-by-surface matrix and a disposition for every instance; running `rg -c "confirmed-bug|already-correct" docs/reports/eink_surface_divergence_audit.md` returns a non-zero count.
- [x] Every confirmed-bug or needs-investigation instance links a filed issue or an existing covering candidate, with dedup reasoning.
- [x] The report states per cited test which layer it checks and gives a reproducible checklist without claiming physical-panel acceptance.
- [ ] `gh issue list --repo stranske/Fine-Art-Archive --search "divergence"` lists each filed follow-up, and `pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py` still passes unchanged.
- [x] The PR description names the report path and the filed issues; the diff touches no file under `src/`.
- [x] Deliberate-break gate: after adding the scope-specific regression in `tests/test_eink_pipeline.py`, temporarily disconnect its corresponding Scope change at `src/fine_art_archive/ui/index.html`; that regression must fail on the described behavior. Restore the change and rerun it successfully, capturing both outcomes.

<!-- auto-status-summary:end -->
