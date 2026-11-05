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


## Later native payload through `dc229bbbb0d0ce373657083c375c7bbb6cda40ce`

Compared the complete two-file delta from the previously reconciled Muse commit
`37dc8b0f85b4a087eacd8bd14eae0ecb2832e29d` through the head above. It adds nine
regressions and dated evidence paragraphs; no production file changes occur in
that delta. All nine regressions are retained on this branch, with original Muse
attribution. This comparison does not claim to have executed Muse or to accept
its historical test-count claims as current results.

| Native payload | Current retention and review disposition |
|---|---|
| Each spec control | Nine-test payload retained; the existing Node-executed request test now supplies all controls and family selections, checks actual emitted fields and rejects empty family values. This corrects the earlier narrow Node fixture, which only supplied sort, limit and selection mode. |
| Exact save/export delivery fields and saved playlist forwarding | Native exact-field assertions retained alongside the stronger existing executed transport comparison. |
| Limit guard/reset and explanatory text | Native guard regression retained; this is a source-level UI contract check, not a visual/browser acceptance claim. |
| Export buttons, path guard and saved-feed clearing | Native coverage retained; button assertions now bind Dry run to false and Write card to true, so swapping handlers is detected. |
| Estimated palette, no-master preview, skipped export, missing-metadata drops, selection diagnostics | All five native disclosure regressions retained separately. They protect literal UI producers/markup; they do not prove physical-panel behavior. |
| Dated probe/mutation claims in the native report | Preserved at the pinned [native report](https://github.com/stranske/Fine-Art-Archive/blob/dc229bbbb0d0ce373657083c375c7bbb6cda40ce/docs/reports/eink_surface_divergence_audit.md). Current local results are recorded separately after this union. Runner-local links and raw `<img>` failure markup are not copied into the canonical report; its relative source links remain valid. |

The invalid runner-local links and literal-HTML review findings on #824 are
superseded in the canonical report, while their historical source remains
unchanged. The family-selector and swapped-button review findings are addressed
by the strengthened checks above. #825/#826/#827 retain their earlier
intentional/unknown, unaccepted dispositions. Both PRs/branches stay preserved
until union CI/review and a fresh all-writer terminal gate permit supersession.

Current union proof: **242 passed** across pipeline, feed, SD-export and render
strategy suites, using the existing explicit polling-selector audit harness.
Ten actual production-UI mutations each failed their unchanged named regression;
family extraction and saved-feed forwarding also failed the executed Node request
cases. Swapped button handlers failed the strengthened label-bound check.
Production UI was restored byte-identically (`d65b9650f582633754b8b8f014dd847d7def95a1e1d02de39fad44484f4f2a52`).
See [portable proof](union-proof-20261017T1802.json) for cases, commands and hashes.
Pinned Black26.10.1/Ruff0.17.1 pass. Main's approved source806 year-zero fix and
its tests were integrated; no production behavior was changed by this union.
The older audit/report/source anchors remain historical evidence.
