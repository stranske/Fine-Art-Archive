# Issue #893: weekly review collision card deliberate-break evidence

## Deliberate break FAIL

After restoring the hardcoded Q547923 / 50-sidecar paragraph at
`scripts/render_weekly_review.py` (coll_body, immediately after the three-way
taxonomy list), the named regression test fails as required:

```text
$ python3 -m pytest tests/test_weekly_review_thumb_paths.py::test_collision_section_reports_only_payload_evidence -q -o addopts=
F
assert 'Q547923' not in collision_block
```

The failure is on `assert "Q547923" not in collision_block` — the renderer again
emits the frozen worst-offender prose that is not present in the payload.

## Revert PASS

With the paragraph removed and collision clusters rendered only from
`coll['worst']` (classification defaulting to `unknown`, or taken from the
payload when present), the named test passes:

```text
$ python3 -m pytest tests/test_weekly_review_thumb_paths.py::test_collision_section_reports_only_payload_evidence -q -o addopts=
.
1 passed

$ python3 -m pytest tests/test_weekly_review_thumb_paths.py -q -o addopts=
....................
20 passed
```

## Re-verified (keepalive 2026-11-17)

Deliberate break restored the same paragraph immediately after the three-way taxonomy list; the named test failed again on `assert "Q547923" not in collision_block`. After revert, the named test and full file (`20 passed`) succeeded on HEAD `2820525`.