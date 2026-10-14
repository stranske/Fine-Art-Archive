# Monochrome delivery proof — issue #788

Companion image previews, indexed/current feeds and SD-card writes now apply the
same existing A11 strategy selected from master colours before fitting or reduced
decoding. The policy and its Spectra-6 thresholds are unchanged. Grayscale uses
native neutral levels (gray16), otherwise native black/paper-white inks. Duotone
uses only the target endpoints with a median-luminance split. Color retains the
full target palette. PNG/BMP remain lossless and the SD palette guard remains active.

Image responses expose `X-Render-Strategy`. Feed validators include the applied
strategy and a representation version. Written SD manifests and API evidence come
from each successfully rendered item; failed items have no claimed applied evidence.
Dry runs still describe a plan. The original implementation excluded the separate
fit-mode ETag issue #786/#787; the current branch is rebased onto that merged change,
so feed validators now include both the effective fit and the applied strategy.

## Validation

- `uv run --locked --extra dev pytest tests/test_eink_monochrome_delivery.py tests/test_eink_export_format.py tests/test_render_strategy.py tests/test_render_color_strategy.py tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py -q -o addopts=''`: **218 passed, zero skipped** (`acceptance.log`, `acceptance.xml`).
- `uv run --locked --extra dev pytest -q`: **2250 passed, 12 skipped, 89.08% coverage** (`full-suite.log`, `full-suite.xml`). Existing opt-in live audits/acquisition workspace/sample-master/calibration fixtures account for skips. Local coverage floor is 25%; result also exceeds hosted 81% floor. Existing Starlette/httpx deprecation warning remains.
- Ruff on changed sources/tests and replay, Black on all 348 repository Python files (349 including this replay), and focused mypy on all four changed functional source modules pass. Logs are included; import re-exports are also linted.

Tests create temporary masters/sidecars/PlaylistStore/card directories, use real
FastAPI HTTP, actual gamut classification, Pillow quantization and saved image
bytes. No selector, classifier, store, renderer or export stubs. The policy-change
test changes the existing mapping input only. The fixture gamut distributions
produce actual well-served, compromised and poorly-served verdicts. Tests cover all
three dithers, three fit modes/rotation, four target palettes, both card formats,
cache 200/304 behavior, strategy changes, failed-item evidence and invalid strategies.

## Falsifiability and restoration

Run from the repository root:
`uv run --locked --extra dev python docs/evidence/monochrome-delivery/mutation.py`.
This temporarily changes production files and restores identical bytes in `finally`.

1. Final tests against immutable original source `5a236579ab0becd260e717c7497c3023af614000`: **11 failures** in `original-red.xml` — three missing-header failures and eight pixel failures. Its two policy-change cases stop at the pixel assertion and do not check for stale 304s. The two stale-304 failures are recorded separately in `etag-red.xml` (`original-red.*`, `etag-red.*`).
2. Force only `targets.render_for_target` to ignore the selected strategy and use color: **6 failed, 3 passed**; restore exact source: **9 passed** (`strategy-red.*`, `strategy-green.*`).
3. Remove only the strategy from `feed.item_etag`: **2 failed** (expected 200, actual 304); restore exact source: **2 passed** (`etag-red.*`, `etag-green.*`).

`mutation-receipt.json` binds original/corrected/mutated/restored source and the
final delivery test file by SHA256. The named export/feed gate files also contain direct regressions and are bound in the manifest. `manifest.json` binds source, tests and proof artifacts.
The full suite ran on the same corrected production/test bytes before mutations.
Only local worktree/run path and JUnit hostname metadata are redacted; outcomes,
assertions and tracebacks are retained. No operational archive/card was changed.
Hosted CI, post-merge provider acceptance and physical-panel fidelity remain UNKNOWN.
