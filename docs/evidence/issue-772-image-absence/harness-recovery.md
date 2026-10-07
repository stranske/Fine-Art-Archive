# Reproduction harness recovery

The historical matched-pair.json is preserved as originally captured. Its exit-one
fields are historical claims, not process receipts. Future reruns use
process-harness.txt for each stage, which writes the actual subprocess return code,
argv and cwd. comparison-harness.txt requires these receipts and checks the return
code against nonempty JUnit results before emitting a replacement matched pair.
Unexecuted, interrupted, usage and collection-error processes cannot pass merely
because their failed-node lists match. ranking-harness.txt creates its output root
before its first write. These changes do not alter the retained coverage or mutation
captures, or claim a new full-suite run.

Each new comparison must use one fresh directory created by `mktemp -d
/tmp/772-api-boundaries.XXXXXX`. Pass that absolute directory as `--run-dir`
to both process-harness stages and comparison-harness. Use pytest output options
`--junitxml="$run_dir/<stage>.xml"` and
`--cov-report="json:$run_dir/<stage>-coverage.json"`, substituting baseline or
candidate for <stage>. Create any required shim inside that directory and use the
same interpreter/environment for both stages. The wrappers reject preexisting
stage outputs and record the run directory, stage, and hashes of emitted JUnit
and coverage files. Comparison verifies these bindings before accepting a pair.
Never copy an earlier stage into a new run or reuse a directory after interruption;
start both stages again. Historical captures remain unchanged and are not newly
validated process evidence.
