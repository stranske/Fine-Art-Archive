<!-- bootstrap for codex on issue #825 run:42034657326-1 -->

## Tasks

- [x] Read the issue-format guide, audit and current preview, resolution, export
  and builder implementations; recorded unchanged forwarding behavior and shifted
  source anchors in the audit's #825 follow-up.
- [x] Document preview-only caller evidence in request models and endpoint
  descriptions, including server-owned saved/served and export selection.
- [x] Update the audit with the selected contract, parity consequence and links
  to #805 and #825.
- [x] Add deterministic quality-only, embeddings-only and combined preview regressions,
  verifying later previews without overrides derive server evidence again and
  checking real saved/served and inline/saved export paths (dry run and writes).
  Empty caller maps fail preview but are ignored by save and both export forms.
- [x] Run focused and broad e-ink tests with the active interpreter; exact
  commands and results are recorded in the audit.

## Acceptance Criteria

- [x] Generated API documentation states caller evidence is preview-only and
  selection parity with saved/served or exported playlists is not guaranteed.
- [x] Deterministic tests change preview IDs while delivery derives server-owned
  evidence through `_build_eink_playlist`; deliberate forwarding removal fails.
- [x] Broad e-ink suite: 314 passed in 81.90 s. Narrow regression: 12 passed in
  7.15 s on Python 3.14.10. Both use `-m 'not slow'` and the existing sandbox
  scheduling harness; exact commands are recorded in the audit.
- [x] Audit records the chosen contract and links #805 and #825.

The repeated task/acceptance entries in the supplied work order correspond to
the verified items above. All work remained in this agent; nothing was delegated.

## Publication status

Branch: `codex/issue-825`, source `2ae6f1b`. Read-only GitHub verification now
confirms PR #870 is **merged**, with `draft=false` and keepalive off. Earlier
open-PR observations and staging failures remain historical evidence in the
audit. The old unchecked work order is stale; this run does not reopen or
change the merged PR.

The current follow-up clarifies live selection in both request-model
descriptions and the preview endpoint: later archive, ratings or master changes
can alter membership even without caller overrides. The generated OpenAPI
regression now verifies that caveat for both request models and endpoints.
Exact test commands and results are recorded in the audit's live-selection
documentation check. Black, Ruff and whitespace checks passed.

The required staging/commit attempt failed at `git add` with exit 128 because
`.git/index.lock` cannot be created on the read-only filesystem. These four
follow-up files remain changed in the workspace; no new commit or push occurred.
