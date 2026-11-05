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
- [x] Broad e-ink suite: 310 passed in 91.89 s. Narrow regression: 8 passed in
  8.79 s on Python 3.14.9. Both use `-m 'not slow'` and the existing sandbox
  scheduling harness; exact commands are recorded in the audit.
- [x] Audit records the chosen contract and links #805 and #825.

The repeated task/acceptance entries in the supplied work order correspond to
the verified items above. All work remained in this agent; nothing was delegated.

## Commit blocker

Branch: `codex/issue-825`. After Black's repository-wide check passed (377 files
unchanged), `git add` of the four task files failed with
`fatal: Unable to create '/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/.git/index.lock': Read-only file system`.
No files were staged and no commit or push was possible under the current
filesystem permissions. Source, tests and documentation remain in the workspace;
the required commit is still outstanding.

The connector rejected the live PR-body reconciliation, `needs-human` label
and blocker comment: `MCP tool call requires approval, but approval policy is never`.
The verified checkboxes above reconcile the duplicated work-order entries
locally; the live PR body still needs publication.
