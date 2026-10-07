# Master-image HTTP boundaries — issue 772

The selected source is `api/main.py`, ranked first by the current repository's
repair-history subject-keyword proxy (24 matches), churn (52 commits), then
uncovered lines/branches. This is a proxy, not a claim that all matching commits
were escaped defects. [ranking.json](ranking.json) retains the full ordering.
Base is `1f4a837476758a5b07cd0a418848e973f51ca8d1`.

Six offline tests use real temporary PNGs, cache files, sidecars and the FastAPI
HTTP interface. They check transparent-master conversion and resize bounds,
unchanged-master cache reuse, missing/corrupt masters, a Pillow dependency outage,
and sidecar-filename fallback. Only input roots and the deliberately unavailable
external boundary are patched. No production file, workflow, coverage policy,
archive, external service or permission grant is changed.

## Matched full-suite evidence

Both stages run the same literal `python -m pytest -q --cov=src
--cov-report=json:<stage>-coverage.json --junitxml=<stage>.xml` command from the
same linked checkout and Python 3.12 environment. [matched-pair.json](matched-pair.json)
records full argv, cwd, zero exit statuses, hashes, counts and per-symbol coverage.
The JSON/JUnit/console artifacts are complete, retained as lossless gzip files;
[compressed-manifest.json](compressed-manifest.json) records compressed and
decoded SHA256 plus byte lengths. Decode with `gzip -dc <file>` or Python
`gzip.decompress(Path(file).read_bytes())`.

| Measurement | Baseline | Candidate |
| --- | ---: | ---: |
| Passed | 2,185 | 2,191 |
| Existing skips | 12 | 12 |
| Failures / errors | 0 / 0 | 0 / 0 |
| Combined line/branch coverage | 88.40537595350527% | 88.51434798401743% |
| Covered lines | 9,257 | 9,267 |
| Covered branches | 2,912 | 2,917 |
| Statement / branch universe | 10,175 / 3,590 | 10,175 / 3,590 |

Every source filename and coverage exclusion is identical, with no per-file
covered-line or covered-branch regression. Both runs retain the same two
existing dependency deprecation warnings. `_serve_resized` advances from 13/18
lines and 2/4 branches to 18/18 and 4/4; `work_image` advances from 1/4 lines and
0/2 branches to 4/4 and 2/2. The sidecar fallback adds two covered lines and one
branch to `_master_path`; its remaining two branches are not claimed complete.
Whole-repository Black passes (346 files), and touched Ruff passes.

## Actual source sensitivity

The [executed harness](mutation-harness.txt) edits only the selected production
function for each mutation, executes its exact new pytest node, restores original
source bytes in `finally`, and executes the same node again. Test bytes remain
fixed. [mutations.json](mutations.json) records all seven mutations, the six unique
new nodes, full commands, source/test/mutant hashes and actual exits.

- `rgba-conversion`: `test_transparent_master_is_a_bounded_jpeg` — RED exit 1, restored GREEN exit 0.
- `resize-bound`: `test_transparent_master_is_a_bounded_jpeg` — RED exit 1, restored GREEN exit 0.
- `cache-reuse`: `test_cached_master_response_does_not_decode_again` — RED exit 1, restored GREEN exit 0.
- `missing-master`: `test_missing_master_is_404_without_creating_cache` — RED exit 1, restored GREEN exit 0.
- `decode-failure`: `test_corrupt_master_reports_resize_failure_without_cached_output` — RED exit 1, restored GREEN exit 0.
- `pillow-outage`: `test_unavailable_pillow_reports_specific_failure` — RED exit 1, restored GREEN exit 0.
- `sidecar-fallback`: `test_sidecar_master_filename_fallback_is_served` — RED exit 1, restored GREEN exit 0.

Each RED is a real pytest assertion failure, not a collection/import error.
This proves sensitivity to a deliberately broken current implementation; it does
not claim the original production behavior was missing. Machine-local root,
output and interpreter paths in the executed harness are disclosed and must be
adapted when replaying in another checkout. Production is byte-identical to base.

The broader issue remains open below its 90% combined-coverage target. Hosted CI
and review are separate acceptance evidence. Matching keepalive owns those current
head checks; closer owns complete expected topology, active threads, unchanged
head and seven-minute floor before merge and `verify:compare`. Local test success
alone does not establish hosted checks, deployment or full initiative completion.
