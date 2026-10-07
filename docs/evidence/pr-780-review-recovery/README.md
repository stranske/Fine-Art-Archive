# PR780 review recovery

This bounded repair follows the test-only predecessor `bdbe9ce552fdf19241591126a1fd7fbaa3631c86`. It changes production JSONL replay to skip non-object records and explicitly reads/writes the decision log as UTF-8. Null, list, number, Boolean and string records are included in the real HTTP regression. The existing Unicode POST/replay cases now force only the decision-log file's default text encoding to ASCII, covering both builtin keyword encoding and pathlib positional `locale` encoding. Actual file IO and HTTP handlers execute; host locale and live archive are untouched.

Focused command: `python3 -m pytest --no-cov -q tests/test_api_variant_review_history.py tests/test_variant_upgrade_labels_and_dims.py tests/test_variant_upgrade_crop_gate.py tests/test_promote_variant_upgrade.py`: **73 passed**, one existing Starlette deprecation warning. Review-history file: **19 passed**. Whole-repo Black **344 files**, touched Ruff and `git diff --check` pass.

`production-red-green.json` records three real production controls: remove non-object guard -> **5 failures**; restore default read encoding -> **3 failures**; restore default write encoding -> **3 failures**. Every control exited1. Exact source bytes were restored, SHA256 recorded, then all19 review-history cases exited0. Retained `mutation-harness.txt` is executable with Python. Red console outputs are losslessly gzipped; `compressed-manifest.json` records raw and compressed hashes/lengths. Decode with `gzip -dc` or Python gzip.

The first encoding wrapper missed pathlib's `locale` sentinel; the independent read mutation exposed this vacuous control. The wrapper was corrected and all three controls above rerun successfully. Do not reuse the earlier incomplete control.

A broader suite was attempted and interrupted while companion API tests stalled: **415 passed,2 skipped**, exit2/KeyboardInterrupt,71.99seconds. This is not a full-suite PASS, matched coverage measurement, or hosted CI substitute. The predecessor's 2166/2172 measurements and original source-byte invariance apply only to that historical test-only chunk. Current production fixes require fresh hosted CI and reviewer disposition. Broader issue772 remains OPEN below90percent.

## Harness encoding review follow-through

The harness now explicitly decodes source and reads/writes all text as UTF-8, including captured subprocess output. It accepts an optional output directory so fresh replays preserve previous evidence. At production head `dca98428f05720a2b1201a1d0ef7b8be7b7745bd`, all three real source mutants again produce 5/3/3 semantic failures; byte-identical restoration gives 19 passing history cases. The adjacent variant suites give 73 passes. A strict wrapper rejects every harness text operation without explicit UTF-8: 9 operations, zero implicit defaults. Complete replay receipt, wrapper, lossless compressed outputs and hashes are retained in `utf8-harness-replay/`. Earlier c73 production/control receipts remain historical and unchanged. This documentation-only harness repair does not establish a new full-suite/coverage result.

Replay: `python3 docs/evidence/pr-780-review-recovery/mutation-harness.txt /tmp/faa-harness-output` from the repository root.
