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
