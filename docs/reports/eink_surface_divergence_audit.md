# E-ink divergence audit — reproducible subset and saved-feed preview classification

Inspected source revision: `0127357f8cf3d98b9e760b3076d3ef1252d5b00e`
(branch `muse/issue-883`, identical to its origin tip when inspected).
This change adds no `src/` change, so every source anchor below describes
that revision. Enumeration method: read `PlaylistSpec` in
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
preview (`eink_playlist_preview`, `main.py:790`), saved/served
(`_resolve_playlist`, `main.py:2229`), inline export and saved export
(`eink_playlist_export`, `main.py:944`). Unknown spec fields return HTTP 400
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
| S2 | `einkUseForCard` (UI, `index.html:3270`) → `einkExport` (`index.html:3366`) → `POST /eink/playlist/export` with `playlist_id` | Saved wins: `main.py:959` replaces inline spec, target and dither with the saved playlist's, and fit with `pl.fit`. Covered by `test_export_saved_playlist_overrides_inline_target_dither_fit`. | already-correct |
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

Dedup was checked against the existing divergence candidates before this
classification was written: #825 (preview-only caller evidence, S5),
#826 (preview `target` semantics), and #827 (preview counts versus feed and
export delivery counts). S1 is not a duplicate of those: it concerns saved
settings never reaching preview at all, rather than evidence, target
resolution, or counting. It is recorded here under #883, which is the
covering follow-up for this classification; no new issue is filed by this
change, preserving #805's separate publication boundary. Physical-panel
acceptance is not claimed anywhere in this report.

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
