# Independent closer research-request recovery evidence

This separate logical chunk recovers the research-request delta originally added by keeper commit `d652919f9c13c4573cea78d96fa9c8aa7060a82e` to DeepZoom PR #776. It adds a two-line dictionary guard and twelve HTTP regressions; DeepZoom source/tests remain in #776. Source #772 remains open below its combined 90% goal.

The historical Python3.14/shim runs in the parent evidence directory retain four identical workspace-location failures in both baseline and candidate. They are preserved as historical evidence. This closer pair ran the literal suite twice with Python3.12, the same dependencies, the same lane-owned worktree, `PYTHONPATH=src`, `PYTEST_ADDOPTS=-m "not slow"`, no external polling shim, and no coverage exclusions. Both exited0:

| State | Passed | Skipped | Combined coverage | Statements | Branches |
|---|---:|---:|---:|---:|---:|
| DeepZoom baseline6cb921d | 2146 | 12 | 88.20535194880745% | 10168 | 3584 |
| Research candidate231e8cb | 2158 | 12 | 88.22332073277116% | 10170 | 3586 |

There were zero test failures/errors in both runs; the candidate adds twelve cases, two production statements, and two branches. Source SHA256 baseline `d201269355b26f47b20b08a7020de9c277d6ada569e64e93e874a9d0006f93d3`, candidate `f02477af7bf92be083a31ad82f4a2051b7b86e4c0fd56511f85a1da5981db5b3`. Test SHA256 `cc3bd04a2e3ab35a60f2aef20c622f16950307d3282d16526f1f65676bbe6c50`.

The closer independently replayed all nine retained actual production mutations in a disposable private archive: 25 failing case executions across twelve unique tests, then byte-identical production restoration and twelve focused tests PASS. Mutations remove the dictionary guard, stop invalid-date recovery, discard existing requests, exclude the inclusive cutoff, retain expired requests, select the wrong latest request, omit the work filter, suppress retryable storage errors, or disable atomic replacement. All RED/GREEN JUnit/logs and the matched full-suite logs/JUnit/coverage are losslessly compressed here; the manifest pins decoded bytes and both compressed/decoded hashes. Temporary mutation archive was deleted.

Runtime versions:
```
3.12.2 | packaged by conda-forge | (main, Feb 16 2024, 20:54:21) [Clang 16.0.6 ]
9.1.1 7.16.2
```

Exact commands and paths are in `772-matched-pair.json.gz`; paths describe the executed evidence environment and are not portable command requirements. This document claims source/test equivalence to the inspected commits; future changed source requires fresh validation. Hosted checks, exact-head review threads, expected-check topology and the seven-minute floor remain required before merge.
