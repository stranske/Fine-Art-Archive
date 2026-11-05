# Issue 806 current-head year-zero proof

Captured on 2026-10-17 for PR #823 at base `803e21bb4b7747c7be4b022b716c70ea70ca53fc` and pre-evidence head `bd815bae488c25117e063d1429d1db550d1b150f`.

## Runtime and exact gate

- Runtime: `/opt/anaconda3/bin/python3` (Python 3.12.2; pytest 9.1.1).
- Production predicate: `src/fine_art_archive/eink/playlist.py` line 338.
- Gate:

```sh
/opt/anaconda3/bin/python3 -m pytest \
  tests/test_eink_pipeline.py::test_year_zero_bounds_filter_and_report_missing_year \
  tests/test_eink_pipeline.py::test_year_zero_omitted_bounds_leave_the_date_filter_off \
  tests/test_eink_pipeline.py::test_year_zero_bounds_on_schema_shaped_string_years \
  tests/test_eink_feed_endpoints.py::test_year_zero_lower_bound_agrees_across_preview_saved_feed_and_export \
  -q --no-cov
```

## Deliberate-break recipe and raw-result binding

The only temporary edit replaced this literal production predicate:

```py
if period_ranges or spec.year_from is not None or spec.year_to is not None:
```

with the former truthiness form:

```py
if period_ranges or spec.year_from or spec.year_to:
```

The normalized pytest result was `6 failed, 2 passed, 1 warning in 1.63s` (exit 1). The six failures were the three explicit numeric-zero bound cases, the two schema-shaped zero bound cases, and the preview/saved-feed/export agreement test. This is a meaningful RED result: each failure admitted work that the explicit zero bound must exclude.

After restoring the exact `is not None` predicate, the same command produced `8 passed, 1 warning in 6.21s` (exit 0). `git diff -- src/fine_art_archive/eink/playlist.py` was empty after restoration, so no production source change is included in this evidence commit.

## Current-source hash binding

The post-restoration SHA-1 values are:

```text
7bb7563435d34ec30b40994f9c6df777c7c42788  src/fine_art_archive/eink/playlist.py
1a728ab0d53dc9398019b3359c5f53d2210ea245  tests/test_eink_pipeline.py
3d83812d3bca3b8c303927fb4eec2995372507c0  tests/test_eink_feed_endpoints.py
```

The predicate was restored before those hashes were collected. The pytest warning is the existing Starlette `TestClient` deprecation warning and did not affect either result.
