# E-ink regression subset retained from #805

PR #868 retains bounded regression coverage; it does not complete the
comprehensive audit in [#805](https://github.com/stranske/Fine-Art-Archive/issues/805).

| Retained test | Verified layer and limits |
| --- | --- |
| `test_ui_preview_save_and_export_carry_the_same_inputs` in `tests/test_eink_pipeline.py` | Node executes checked-in UI producers with DOM/network stubs for four fit values. Checks request bodies, saved interval and generated preview-image URL. Does not execute a browser, backend selection, rendering or device delivery. This regression and its harness already exist on `main`; this PR retains them and adds the interval assertion. |
| `test_enumerated_eink_surface_inputs_match_backend_signatures` in `tests/test_eink_pipeline.py` | Inspects explicit function parameters and model/dataclass fields. Does not enumerate implicit archive/environment inputs or headers read through `request`, and does not prove behavioral parity. |
| `test_export_inline_spec_target_dither_fit_without_playlist_id` in `tests/test_eink_feed_endpoints.py` | Exercises the production endpoint and SD writer with temporary masters. Checks a non-default inline target, manifest dither/fit and complete selected-ID membership, excluding a distinguishable work through its tag. |
| `test_export_saved_playlist_overrides_inline_target_dither_fit` in `tests/test_eink_feed_endpoints.py` | Exercises saved-playlist precedence through the production endpoint and SD writer. Conflicting saved/inline tag filters select different IDs; checks complete delivered manifest membership and saved target/dither/fit. |

The export tests inspect manifest metadata and membership, not pixel equivalence,
HTTP validators, physical-card transport or panel appearance. UI request parity
alone does not establish preview versus saved-export selection parity.

The unfinished source-revision reconciliation, complete input matrix, duplicate
dispositions, C/B notation, saved-setting precedence classification, banner versus
parity-caption analysis, candidate deduplication and comprehensive test-layer audit
remain with #805. Existing related candidates are
[#825](https://github.com/stranske/Fine-Art-Archive/issues/825),
[#826](https://github.com/stranske/Fine-Art-Archive/issues/826) and
[#827](https://github.com/stranske/Fine-Art-Archive/issues/827); this subset does not
claim their coverage is exhaustive. New findings remain subject to #805's separate
publication boundary; this salvage publishes no new finding issue.

Historical audit text and execution claims are preserved in
[the pre-salvage revision](https://github.com/stranske/Fine-Art-Archive/blob/18629a6e4d329e72efe1719698b2b77022fe59f8/docs/reports/eink_surface_divergence_audit.md).
Those receipts are historical, not validation of this narrowed head.

Validation receipts for this subset follow after execution.
