# E-ink divergence audit — reproducible subset and saved-feed preview classification

Inspected source revision: `5a92cc0c02e7ff6a0ec871161dce09af1f5e227d`
(current main, including merged PR #884; checked 2026-11-10).
The earlier claim that #884 added no `src/` change was false: it added
JSON shape guards in `api/gates.py::_held_by_artist_index` (line 404) and
`load_work_decisions` (line 789), with regression tests. Those productive
guards remain intact. This successor changes only this report; it neither
redoes nor reverts #884. All current source anchors below refer to this
inspected and tested tree, not #884's pre-merge branch head.

Enumeration method: read `PlaylistSpec` in
`src/fine_art_archive/eink/playlist.py:120`, the request models and endpoints
in `src/fine_art_archive/api/main.py`, and the producers in
`src/fine_art_archive/ui/index.html`; cross-check with
`docs/reports/eink_surface_audit/probe.py`, which asserts the same inventory
(17 spec fields, preview-only evidence fields, render defaults) against the
production code. `tests/test_eink_audit_report.py` enforces this report's
matrix and classification contract so the audit cannot silently drift again.

Disposition vocabulary — exactly one per row, no other shorthand (the former
duplicate/C/B notation is retired; a row previously described twice now
appears once, with the stricter disposition):

- `already-correct` — inspected source and an executed test agree.
- `confirmed-bug` — a stated claim is contradicted by inspected source.
- `needs-investigation` — plausible divergence, no contract decision yet.
- `intentionally-unsupported` — divergence is a declared product boundary.

## Input-by-surface matrix: the 17 `PlaylistSpec` fields

Every surface parses the spec with `PlaylistSpec.from_dict` and selects
through `_build_eink_playlist` (`src/fine_art_archive/api/main.py:679`), so
selection semantics for these fields are shared by construction:
preview (`eink_playlist_preview`, `main.py:791`), saved/served
(`_resolve_playlist`, `main.py:2229`), inline export and saved export
(`eink_playlist_export`, `main.py:945`). Unknown spec fields return HTTP 400
on each surface (`playlist.py:142`).

| `artists` | already-correct |
| `genres` | already-correct |
| `moods` | already-correct |
| `periods` | already-correct |
| `year_from` | already-correct |
| `year_to` | already-correct |
| `any_tags` | already-correct |
| `all_tags` | already-correct |
| `not_tags` | already-correct |
| `exclude_filters` | already-correct |
| `min_fit` | already-correct |
| `min_quality` | already-correct |
| `require_dossier` | already-correct |
| `selection_mode` | already-correct |
| `limit` | already-correct |
| `sort` | already-correct |
| `seed` | already-correct |

## Non-spec inputs and saved-setting precedence (classified separately)

| Row | Surface | Precedence and evidence | Disposition |
|---|---|---|---|
| S1 | `einkPreview` (UI, `index.html:3292`) → `POST /eink/playlist/preview` plus per-work `GET /works/{id}/eink_preview` images | Uses only the current filter controls (`einkSpec()`, `ek-target`, `ek-dither`, `ek-fitmode`). It never sends `einkCardPlaylistId`, so choosing a saved feed for the card does not change what preview selects or renders. | needs-investigation |
| S2 | `einkUseForCard` (UI, `index.html:3270`) → `einkExport` (`index.html:3366`) → `POST /eink/playlist/export` with `playlist_id` | Saved wins: `main.py:961` replaces inline spec, target and dither with the saved playlist's, and fit with `pl.fit`. Covered by `test_export_saved_playlist_overrides_inline_target_dither_fit`. | already-correct |
| S3 | Inline export (no `playlist_id`) | Inline spec/target/dither/fit win. Covered by `test_export_inline_spec_target_dither_fit_without_playlist_id`. | already-correct |
| S4 | Saved/served feed (`_resolve_playlist`, `_render_feed_image`, `main.py:2272`) | Stored spec re-runs live on every request; rendering uses saved target/dither/fit only. No inline or preview input can override it. | already-correct |
| S5 | Preview-only `quality_scores` / `embeddings` (`PlaylistIn`, `main.py:629`) | Affect only that preview request in preference-diverse mode; empty maps return HTTP 400. Save and both export forms ignore them and derive server-owned evidence through `_build_eink_playlist`. Persistence is not offered. | intentionally-unsupported |
| S6 | `sample` (`PlaylistIn.sample`) | Truncates only the preview `items` list; `selected`, `work_ids` and delivery counts stay full-selection. Preview-only by design. | already-correct |

### Banner versus parity caption (finding under S1)

Two UI statements pull in opposite directions once a saved feed is chosen:

- The `einkUseForCard` banner (`index.html:3275`) correctly states the
  export-side truth: "Card uses saved feed … — filters above are ignored."
- The preview caption (`index.html:3351`) states "Rendered as the panel
  would show it — same fit, range compression and dither as the card",
  which is false in that state: preview still renders the filter controls'
  selection with the controls' fit/dither, not the saved feed's.

Classification: the banner is `already-correct` for export (S2); the caption
over-claims parity for preview, so S1 stays `needs-investigation` — the fix
(caption wording, preview honouring the saved feed, or disabling preview in
that state) is a product decision, not made here. No code is changed by this
classification.

### Dedup and publication boundary

Checked 2026-11-10 as authenticated GitHub account `stranske` (active
account; repo/read:org scopes). These results describe that account's search
visibility, not proof of visibility into all GitHub content.

```text
gh issue list --repo stranske/Fine-Art-Archive --search divergence
# exit 0, empty output (default OPEN state, default limit 30)
gh issue list --repo stranske/Fine-Art-Archive --state all --search divergence --limit 1000 --json number,title,state,url
# exit 0, eight rows, all CLOSED
# Explicit all-state API search, following Link pagination:
gh api --paginate 'search/issues?q=repo%3Astranske%2FFine-Art-Archive+is%3Aissue+divergence&per_page=100' --jq '{total_count,incomplete_results,items:[.items[]|{number,title,state}]}'
# exit 0, total_count=8, incomplete_results=false; one page, no next page
```

The all-state CLI and paginated API searches returned the same eight issues.
Search matches indexed text, not semantic identity; the API search cap is
1,000 matches, not reached here. An empty default open search therefore does
not contradict filed, now-closed follow-ups. Direct `gh issue view N --repo
stranske/Fine-Art-Archive --json number,title,state,body` readbacks confirmed
#825/#826/#827 CLOSED. Closure alone is not execution acceptance.

| Returned issue | Current state | Row mapping / dedup result |
| --- | --- | --- |
| [#825](https://github.com/stranske/Fine-Art-Archive/issues/825) caller-supplied A15 evidence is preview-only | CLOSED | S5, caller evidence contract; not S1 saved settings |
| [#826](https://github.com/stranske/Fine-Art-Archive/issues/826) playlist preview ignores target | CLOSED | Preview target reporting, now resolved/validated at `main.py:813` and reported at `main.py:872`; not S1 |
| [#827](https://github.com/stranske/Fine-Art-Archive/issues/827) no-master count semantics | CLOSED | S6 and delivery counts, with `available_for_delivery` at `main.py:861`; not S1 |
| [#883](https://github.com/stranske/Fine-Art-Archive/issues/883) reproducible audit and saved-feed preview classification | CLOSED | Audit ownership/history; carries the S1-C1 proposal below, not an implemented S1 fix |
| [#805](https://github.com/stranske/Fine-Art-Archive/issues/805) surface audit | CLOSED | Parent audit and publication boundary |
| #523 master/sidecar trees | CLOSED | Unrelated storage divergence |
| #407 artist Q-ID fields | CLOSED | Unrelated metadata divergence |
| #188 duplicated primitives | CLOSED | Unrelated algorithm divergence |

**Durable tracked disposition S1-C1 (under #883, in this report):**
`needs-investigation`, unimplemented, awaiting separate publication approval.
None of #825/#826/#827 covers saved settings never reaching preview. Do not
represent closed #883 as an open implementation owner. The concrete candidate
is: clarify the preview caption when `einkCardPlaylistId` is set, stating that
preview uses current filters/render controls while card export uses the saved
feed. Keep saved-export precedence and selection unchanged. Acceptance would
execute the existing Node UI harness with conflicting saved/current settings,
assert the disclosure in the saved-feed state and the normal caption after
clearing it, and deliberately remove the conditional disclosure to obtain a
failing assertion followed by a restored pass. That candidate does not include
changing preview selection, evidence persistence, target calibration, counts,
or physical transport. This stable S1-C1 entry is the scoped proposal and
handoff for separate approval; no new issue, implementation, or external
follow-up publication is authorized or created here. #805's explicit
publication boundary remains in force; its later report-only clarification is
not treated as approval of this newly scoped instance. Physical-panel
acceptance remains unclaimed.

## Test layers (what each cited test actually checks)

| Retained test | Verified layer and limits |
| --- | --- |
| `test_ui_preview_save_and_export_carry_the_same_inputs` in `tests/test_eink_pipeline.py` | Node executes checked-in UI producers with DOM/network stubs for four fit values. Checks request bodies, saved interval and generated preview-image URL. Does not execute a browser, backend selection, rendering or device delivery. |
| `test_enumerated_eink_surface_inputs_match_backend_signatures` in `tests/test_eink_pipeline.py` | Inspects explicit function parameters and model/dataclass fields. Does not enumerate implicit archive/environment inputs or headers read through `request`, and does not prove behavioral parity. |
| `test_export_inline_spec_target_dither_fit_without_playlist_id` in `tests/test_eink_feed_endpoints.py` | Exercises the production endpoint and SD writer with temporary masters. Checks a non-default inline target, manifest dither/fit and complete selected-ID membership, excluding a distinguishable work through its tag. |
| `test_export_saved_playlist_overrides_inline_target_dither_fit` in `tests/test_eink_feed_endpoints.py` | Exercises saved-playlist precedence through the production endpoint and SD writer. Conflicting saved/inline tag filters select different IDs; checks complete delivered manifest membership and saved target/dither/fit. |
| `test_audit_report_matrix_and_classification_are_reproducible` in `tests/test_eink_audit_report.py` | Checks this report against the production `PlaylistSpec` inventory: one row and one disposition per field, separate S1/S2 classification rows, and the banner/caption finding. Checks the report only; it proves no runtime behavior. |

The export tests inspect manifest metadata and membership, not pixel
equivalence, HTTP validators, physical-card transport or panel appearance.
UI request parity alone does not establish preview versus saved-export
selection parity.

## Current validation

Inspected source revision: `5a92cc0c02e7ff6a0ec871161dce09af1f5e227d`
(the production/test tree from current main, including #884). Check date:
2026-11-10. This successor modifies only the report; the tests and production
bytes used below are unchanged from that revision after restoration.

Selected interpreter: `/opt/anaconda3/bin/python3`, output `Python 3.12.2`.
Neither `.venv` nor `.faa-venv` exists in this provisioned worktree, so this
is the owner-directed fallback. The project declares Python >=3.13; these
local receipts do not establish supported-runtime acceptance, which remains
CI's responsibility. No dependency pins or coverage configuration were edited.

Outcome 1: both complete test files execute successfully, including all slow
tests; default whole-source coverage fails, while an explicitly scoped e-ink
coverage run passes the existing 25% threshold. Both runs finish in under two
minutes. No tests were filtered or deselected.

```text
/opt/anaconda3/bin/python3 -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py
TOTAL 10288 8518 3634 60 15%
FAIL Required test coverage of 25.0% not reached. Total coverage: 15.13%
268 passed, 3 warnings in 74.62s (0:01:14)
Exit code: 1
Coverage: 15.13%, whole src, FAIL (25% required)

/opt/anaconda3/bin/python3 -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py --cov-reset --cov=fine_art_archive.eink
TOTAL 845 90 276 32 87%
Required test coverage of 25.0% reached. Total coverage: 87.15%
268 passed, 3 warnings in 71.01s (0:01:11)
Exit code: 0
Coverage: 87.15%, fine_art_archive.eink only, PASS (25% required)
```

`--cov-reset` clears the default `--cov=src` measurement scope before selecting
`fine_art_archive.eink`; it does not change `fail_under`, branch measurement,
or the two files executed. This is a passing configured subsystem run, not a
passing whole-source coverage gate. The default exit 1 is not relabelled as
success. No full suite or release/verify pipeline ran locally. Warnings concern
pytest-asyncio's unset loop-scope default and Starlette/httpx/AnyIO deprecations;
none were repaired in this acceptance push.

### Deliberate breaks and byte-identical restoration

Same interpreter, date and tested revision as above. Each exact command below
ran three times: original GREEN, one isolated mutation RED, restored GREEN.
`--no-cov` isolates regression assertions from whole-source coverage failure;
coverage is not claimed for these focused runs. Every run finished within two
minutes. Mutations were sequential and restored in a `finally` block before
any other production mutation or restored test.

```text
/opt/anaconda3/bin/python3 -m pytest --no-cov tests/test_eink_feed_endpoints.py::test_export_saved_playlist_overrides_inline_target_dither_fit
GREEN: 1 passed, 2 warnings in 8.27s; exit 0
RED:   1 failed, 2 warnings in 4.36s; exit 1
RESTORED: 1 passed, 2 warnings in 8.03s; exit 0

/opt/anaconda3/bin/python3 -m pytest --no-cov 'tests/test_eink_pipeline.py::test_ui_preview_save_and_export_carry_the_same_inputs[cover]'
GREEN: 1 passed in 0.46s; exit 0
RED:   1 failed in 0.55s; exit 1
RESTORED: 1 passed in 0.50s; exit 0
```

Saved-spec mutation: in `eink_playlist_export` at `main.py:961`, replaced only
`body_spec, target, dither = pl.spec, pl.target, pl.dither` with
`target, dither = pl.target, pl.dither`. Saved target/dither/fit remained
connected. The expected selection assertion failed at
`tests/test_eink_feed_endpoints.py:905`: `assert exported.json()["selected"] ==
len(saved_ids)`, `AssertionError: assert 1 == 2`. The inline-only selection
was distinguishable from the two saved IDs.

UI mutation: at `index.html:3356`, removed only preview-image `${fitQ}` from
`${encodeURIComponent(dither)}${fitQ}&max_px=380`. The expected URL assertion
failed at `tests/test_eink_pipeline.py:1543`: `assert params == {...}`;
`Right contains 1 more item: {'fit': ['cover']}`. Other URL parameters matched.

SHA-256 receipts (original and restored hashes are equal, and direct byte
comparison also passed; neither mutation is committed):

- `src/fine_art_archive/api/main.py`
  - Original/restored: `2ee01110684de51fc973ae1c85bfe49d30ea50bc40a32f93fe7bb21dd9a1dd20`
  - Mutated: `7b9d14fdf622add8aebf4e3bd1eadc75b47c16ae6f7fc9f963cbf27f43c7bbec`
- `src/fine_art_archive/ui/index.html`
  - Original/restored: `65e55c05ca96c4a03b54ee014b380870c8fc1dadbe3377b480b932d3a33db33f`
  - Mutated: `3f29c87d428c9f4866870bcfb98f0d029e35e77d8d8fcaf9a9b474ffe10bc10b`

### Report checks

```text
/opt/anaconda3/bin/python3 -m pytest --no-cov tests/test_eink_audit_report.py
2 passed in 0.28s
Exit code: 0
rg -c 'confirmed-bug|already-correct' docs/reports/eink_surface_divergence_audit.md
25
Exit code: 0
```

### Source-anchor and review reconciliation

Every current source anchor above was reread in the tested tree: PlaylistSpec
120/from_dict 142; main.py models 629, builder 679, preview 791, target 813/872,
available count 861, export 945/saved assignment 961, resolver 2229/render 2272;
UI saved-feed selector 3270/banner 3275, preview 3292/caption 3351/image 3356,
and export 3366; gates.py guard-owning functions 404/789. The guards themselves
are at 433/436/439 and 817. Historical anchors/receipts below retain their
original revision attribution. The successor's source diff against the tested
revision is empty; the report does not claim backend, browser, or panel evidence
beyond the test layers described above.

GraphQL review-thread readbacks on 2026-11-10 (first 100 threads, no next page):
merged #868 head `755c84d94a378d5a5bfb23af85c7f8b1c3151711` has 14 threads,
all resolved; merged #884 head `29bdade10716e80c2d45cce0c307ee23ce201a0b`
has zero threads. These are predecessor PR heads, not the tested merge commit.
No predecessor thread was silently treated as unresolved or as new acceptance.
The successor PR description records its final-head thread readback separately.

## Historical receipts (historical, not current validation)

Everything in this section is a dated receipt from an earlier revision. It
is retained as evidence of what was run then; it does not validate the
current head, and no count here is a current result.

- Test revision: `72729e6b3ddcac2d1027fd4c0d048936334ae9a7`.
  Selected interpreter: `/opt/anaconda3/bin/python3` (Python 3.12, the
  owner-directed fallback; the project declares Python >=3.13, so
  supported-runtime validation remains CI's responsibility).
- `pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py`:
  **268 passed**, exit **1** because default coverage was **15.14%**, below
  the repository-wide **25%** floor. Not a passing coverage gate.
- Focused four-test run with `--no-cov`: **7 passed**, exit **0**.
- Deliberate break at `60aa7bc`: removed only preview `${fitQ}`; the cover
  case failed on the missing `fit=cover` URL assertion; restored bytes
  passed again. Restored UI SHA-256:
  `65e55c05ca96c4a03b54ee014b380870c8fc1dadbe3377b480b932d3a33db33f`.
- Focused Ruff and Black checks on both test files: exit **0**.

Historical audit text and execution claims from before the salvage are
preserved in
[the pre-salvage revision](https://github.com/stranske/Fine-Art-Archive/blob/18629a6e4d329e72efe1719698b2b77022fe59f8/docs/reports/eink_surface_divergence_audit.md).
Those receipts are historical, not validation of this head.
