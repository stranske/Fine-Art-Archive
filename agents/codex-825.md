<!-- bootstrap for codex on issue #825 run:42034657326-1 -->

## Tasks

- [x] Read the issue-format guide, audit and current preview, resolution, export
  and builder implementations; recorded unchanged forwarding behavior and shifted
  source anchors in the audit's #825 follow-up.
- [x] Document preview-only caller evidence in request models and endpoint
  descriptions, including server-owned saved/served and export selection.
- [x] Update the audit with the selected contract, parity consequence and links
  to #805 and #825.
- [x] Add deterministic quality-only and embeddings-only preview regressions,
  checking real saved/served and inline/saved export paths (dry run and writes).
- [x] Run focused and broad e-ink tests with the active interpreter; exact
  commands and results are recorded in the audit.

## Acceptance Criteria

- [x] Generated API documentation states caller evidence is preview-only and
  selection parity with saved/served or exported playlists is not guaranteed.
- [x] Deterministic tests change preview IDs while delivery derives server-owned
  evidence through `_build_eink_playlist`; deliberate forwarding removal fails.
- [x] Broad e-ink suite: 308 passed in 86.17 s. Narrow regression: 6 passed in
  4.83 s. Both use `-m 'not slow'` and the existing sandbox scheduling harness.
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
