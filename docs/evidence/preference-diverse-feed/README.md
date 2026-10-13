# Preference-diverse saved feeds and SD export — issue 784

The preview previously derived quality ratings and local RGB pixel descriptors, but saved resolution and export omitted both. Saved specs could be committed before that failure. The shared `_build_eink_playlist` now resolves filtered candidates and derives only omitted evidence for every path. Preview keeps explicit evidence, including explicit empty mappings. Saved specs continue to resolve live. Save resolves a detached candidate before any store write; invalid creates and updates return HTTP400 without changing persisted bytes. Selection failures in older entries produce per-playlist diagnostics, while valid rows remain available.

## Reproduce

Use Python3.12 and the locked dev environment: `uv run --frozen --extra dev ...`.

- Acceptance: `uv run --frozen --extra dev pytest tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py tests/test_eink_pipeline.py -q -o addopts=` — **172 passed**, no skips. `acceptance.log` captures the full result. Focused commands disable the repository-wide coverage addopts; the full run below retains them.
- Full repository: `uv run --frozen --extra dev pytest -q` — **2210 passed,12 skipped**,88.81% coverage, above the hosted81% requirement. `full-suite.log` retains the full output/coverage table. The twelve skipped tests and one existing Starlette/httpx deprecation warning are not reported as executed acceptance.
- `uv run --frozen --extra dev mypy src/fine_art_archive/api/main.py src/fine_art_archive/eink/playlist.py` — two source files pass; captured in `mypy.log`.
- `uv run --frozen --extra dev black --check --line-length 100 --extend-exclude '(\.workflows-lib|node_modules)' .` —347 repository files unchanged; captured in `black-source.log`. `--extend-exclude` retains Black's virtual-environment exclusions.
- Focused Ruff and `git diff --check` pass.

## Production-path proof

The HTTP tests substitute only temporary filesystem/configuration boundaries: real JPEG masters, sidecars, quality-rating JSONL and PlaylistStore. The real app, filters, local descriptor derivation, selector, feed/manifest, PNG renderer and SD exporter run. No selector/renderer/store stubs or live archive writes are used.

`test_preference_diverse_preview_saved_feed_and_exports_agree` uses the companion-shaped spec with no supplied quality/embeddings. It binds selected IDs across preview, save/list, feed manifest, `next`, served PNGs and both inline/saved exports. Both dry-run and actual temporary PNG-card writes are exercised; actual card manifest IDs and image decoding are checked. Other regressions check missing quality/master, unreadable masters, degenerate descriptors, byte-identical failed updates, refused creates, isolated malformed-entry listing, feed/export400, filter-before-evidence, live re-resolution, and explicit preview-evidence preservation. Existing ordered-mode regressions run unchanged.

## Original RED and surgical mutation

Command: `uv run --frozen --extra dev pytest tests/test_eink_feed_endpoints.py -k preference_diverse -q -o addopts= --tb=short`, with an explicit `--junitxml` path per capture.

1. Replay final regressions on both original source files from base52b591e5: **13 failed,1 passed**, exit1 (`original-replay-red.log/.xml`). The initial ten-test capture was also RED; its raw traceback is retained in the automation run directory and the complete final short-traceback replay is published here.
2. Restore corrected bytes. Change only saved `_resolve_playlist`'s call from `_build_eink_playlist` to `_eink.build`, bypassing evidence delivery. **3 failed,11 passed**, exit1 (`mutation-red.log/.xml`): both end-to-end journey variants and filtered live resolution fail.
3. Restore exact corrected source bytes in `finally`: **14 passed**, exit0 (`restored-green.log/.xml`). Corrected/restored SHA256 are identical in `mutation-receipt.json`; no mutation remains.

Full suite ran on the same corrected source/test bytes before the mutation; restoration hashes bind that run to the final source. Logs preserve full tracebacks and outcomes; JUnit preserves every case outcome and exception message, with duplicate original failure traceback text omitted because it is captured in original-replay-red.log. Only account/worktree/run path metadata is redacted. `manifest.json` binds every published proof plus both production files and the regression file to their actual bytes. No artifact proves physical-panel fidelity, operational archive deployment, hosted CI/review, or post-merge provider PASS; those remain pending/UNKNOWN.
