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
- [x] Broad e-ink suite: 314 passed in 77.92 s. Narrow regression: 12 passed in
  7.41 s on Python 3.14.9. Both use `-m 'not slow'` and the existing sandbox
  scheduling harness; exact commands are recorded in the audit.
- [x] Audit records the chosen contract and links #805 and #825.

The repeated task/acceptance entries in the supplied work order correspond to
the verified items above. All work remained in this agent; nothing was delegated.

## Publication status

Branch: `codex/issue-825`. The runner committed the earlier implementations in
`237d676`, `bd1987d`, `cdcbf48`, `169b9da` and `724c676`; their combined diff
touches four task files. Earlier direct staging failures describe those runs,
not the publication state of that now-committed implementation.

The connector rejected the live PR-body reconciliation, `needs-human` label
and blocker comment: `MCP tool call requires approval, but approval policy is never`.
The verified checkboxes above reconcile the duplicated work-order entries
locally; the live PR body still needs publication.

At source `724c676`, the existing focused regressions passed 8 tests in 7.38 s.
The follow-up clarifies the API's top-level evidence fields and corrects the
export spec description: evidence nested inside `spec` returns HTTP 400 rather
than being ignored. Four new endpoint cases verify refusal before selection or
export writes. The expanded focused command passed 12 tests in 7.41 s; its
exact command and the completed broad run are recorded in the audit.

The current follow-up remains uncommitted: after all checks passed, staging
these four files failed with exit 128 because `.git/index.lock` cannot be
created on a read-only filesystem. No current-run commit or push occurred.
Read-only verification confirmed PR #870 is open with `draft=false` at
`724c676`.
