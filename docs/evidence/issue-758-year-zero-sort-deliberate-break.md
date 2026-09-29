# Issue #758: year-zero sort deliberate-break evidence

This record closes the missing evidence gate identified for issue #737 and merged
PR #755. The replay ran from `origin/main` commit
`9b09dd99b124071be091614a2c868795b6a3d054`, after the production fix had merged.

## Baseline PASS

Command:

```text
uv run --frozen pytest tests/test_known_works_fetchers.py -k merge_works_sorts_astronomical_year_zero -q -o addopts=
```

Result:

```text
.                                                                        [100%]
1 passed, 23 deselected in 0.25s
```

## Deliberate break FAIL

Only the production sort expression in
`src/fine_art_archive/known_works/fetchers.py` was temporarily changed from:

```python
w.year if w.year is not None else 9999
```

to the former falsy fallback:

```python
w.year or 9999
```

Running the same command returned exit code 1:

```text
FAILED tests/test_known_works_fetchers.py::test_merge_works_sorts_astronomical_year_zero_before_year_one
AssertionError: assert ['Year one', ..., 'Year zero'] == ['Year zero', ..., 'Unknown year']
At index 0 diff: 'Year one' != 'Year zero'
1 failed, 23 deselected in 0.28s
```

This failure proves the named regression distinguishes astronomical year zero
from an unknown year and catches restoration of the former `w.year or 9999`
behavior.

## Exact restoration PASS

The production expression was restored exactly. The same command then passed:

```text
.                                                                        [100%]
1 passed, 23 deselected in 0.23s
```

Cleanup proof:

```text
git diff --exit-code -- src/fine_art_archive/known_works/fetchers.py tests/test_known_works_fetchers.py
```

The command exited 0 with no output, proving the deliberate break left no source
or test mutation behind. This evidence document is the only intended repository
change for issue #758.
