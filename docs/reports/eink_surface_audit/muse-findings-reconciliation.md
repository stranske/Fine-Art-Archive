# Reconciliation of Muse source #805 findings

This note retains the historical Muse audit at PR #824 commit
`37dc8b0f85b4a087eacd8bd14eae0ecb2832e29d` without treating its follow-up
issues as accepted implementation scope. It is paired with the current Codex
audit on this branch at `f4c09470cbf88e9da10113ed2ae9ebf016002198`.

The original Muse execution is attributed to reservation
`6f6a52d0f1eb45329f8bc7e6787c5b96`, workflow attempt
`39047557359:1`, and its completed Muse child `117439393458`. That is a
historical provider record; this reconciliation did not execute Muse.

## Observation disposition at the current contract

| Historical observation | Current contract/source evidence | Reconciled status | Follow-up status |
|---|---|---|---|
| #825: caller-supplied `quality_scores` and `embeddings` affect only preview | The primary journey promises a saved playlist and playable selection (C3/C5). `PlaylistIn` accepts transient caller evidence while saved playlists store only `PlaylistSpec`; the companion UI never supplies those maps. The current audit's P1 reproduces the difference and explicitly declares persistence intentionally unsupported. | **Intentional for current delivery.** This does not claim that persistence would be undesirable; it records that it is outside source #805's audit/remediation scope. | Keep #825 as a paused, unaccepted historical proposal. No storage or forwarding change is included. |
| #826: `PlaylistIn.target` is accepted by selection preview but target-specific policy is applied only when rendering an item/feed/card | C2 promises a panel-sized rendered image, and the item preview route consumes target. C3 promises a selection; it does not specify target-dependent selection diagnostics. Source inspection confirms the accepted field could be confusing, but does not establish incorrect delivered pixels or selection. | **Unknown, not reproduced as a contract failure.** The field's API/documentation treatment needs a later bounded decision or an explicit contract addition. | Keep #826 paused and unaccepted; do not remove, reinterpret, or implement the field in this audit PR. |
| #827: preview counts no-master candidates, while feed excludes them and SD export reports selected plus skipped writes | C3 exposes selection and coverage; C5 requires a playable feed. The current audit verifies the preview `has_master=false` diagnostic, feed exclusion preventing a 404, and export skip/report behavior. | **Intentional diagnostic-versus-deliverable distinction.** Count equality is not a stated product contract. | Keep #827 paused and unaccepted. A future UI-count policy may be proposed separately if desired. |

## Retention map

- The three Muse static UI assertions remain historical evidence in #824.
  Their behavior is retained more strongly on this branch by the executable
  Node harness `test_ui_preview_save_and_export_carry_the_same_inputs`, which
  invokes preview/save/export and checks emitted spec, target, dither and fit.
- The Muse matrix, issue links and original source anchors stay preserved on
  #824. This note supplies the current-contract disposition instead of
  overwriting that dated report.
- No source file, API contract, acceptance checkbox, issue state, PR state, or
  Muse provenance was changed. #821 and #824 remain open until ordinary review,
  CI and final source805 reconciliation gates are satisfied.
