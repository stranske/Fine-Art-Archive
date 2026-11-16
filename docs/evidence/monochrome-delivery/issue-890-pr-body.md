Reconciled task checkboxes for PR #891 (issue #890). Live `gh`/connector body update was not available in this runner (`GH_TOKEN` length 0).

### Tasks
- [x] `src/fine_art_archive/eink/targets.py:247-262` — compute duotone threshold/uniform fallback from artwork pixels only (threshold before compositing, or mask the pasted region from `fit_to_target:180-207`), keep letterbox exactly `palette.white`
- [x] `tests/test_eink_monochrome_delivery.py` — add library regression + extend HTTP/card parity case with an aspect-mismatched master
- [x] Named test `tests/test_eink_monochrome_delivery.py::test_duotone_contain_letterbox_does_not_set_threshold` passes
- [x] Deliberate break → revert: commit `245cb02` (padded-canvas median) fails the named test; `2b9485e` restores artwork-only median and passes; `test_padded_canvas_median_would_blacken_contain_artwork` pins the failure mode without mutating production code
- [x] The whole test file passes: `python3 -m pytest tests/test_eink_monochrome_delivery.py -q --no-cov`

### Acceptance criteria
- [x] Named test passes
- [x] Deliberate break → revert recorded (commits + evidence + in-test gate)
- [x] Full test file passes