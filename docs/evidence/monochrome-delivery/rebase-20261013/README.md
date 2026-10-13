# PR 789 rebase qualification

Rebased the two existing implementation commits onto merged PR787, main30e1006a9c35e9b7e628ad53b8e62deb2a404212. Both effective fit and the A11 rendering strategy participate in the feed image ETag. Invalid saved fit still returns HTTP400 before representation validation. Both sets of fit/strategy regression tests remain present.

Validation uses this checkout's production modules through PYTHONPATH=src:
- Feed, pipeline, export and monochrome delivery gates:233 passed.
- Full suite:2271 passed,12 skipped,89.07% coverage (81% floor).
- Ruff and Black passed on the resolved production/test files; mypy passed on api/main.py and eink/feed.py.
- Remove fit from the hash:6 failures,13 passes; identical restoration:19 passes.
- Remove strategy from the hash:3 failures; identical restoration:3 passes.
- Force the renderer to ignore A11 strategy:6 failures,3 passes; identical restoration:9 passes.

Replay with `PYTHONPATH=src python docs/evidence/monochrome-delivery/rebase-20261013/recovery-mutations.py /tmp/faa789-replay` after creating the output directory. It temporarily mutates production files and restores exact bytes; run in an idle disposable checkout. Earlier proof artifacts in the parent directory remain historical, bound to their original source hashes. This supplement qualifies the combined implementation; fresh hosted CI, exact-head review and post-merge comparison remain separate gates. No physical-device result is claimed.
