"""The gate that keeps unactionable issues out of the automated lanes.

Grounded in docs/AGENT_ISSUE_FORMAT.md: Tasks and Acceptance Criteria are
required, and at least one acceptance criterion must name a real test, runnable
command or observable verification step (guide section 2).
"""

from fine_art_archive.issue_format import validate

GOOD = """
## Why
`store.py:181` keys the cache on the staging dir's mtime, which a nested write
does not change.

## Scope
The dossier-presence cache only.

## Non-Goals
- Do NOT refactor the manifest cache.

## Tasks
- [ ] Key the cache on per-sidecar mtime+size
- [ ] Add a regression test

## Acceptance Criteria
- `tests/test_companion_app_api.py::test_dossiers_cache_invalidates_on_sidecar_edit` passes
- Deliberate break: revert the change, that test FAILS, then restore
"""


def test_conforming_body_passes() -> None:
    r = validate(GOOD)
    assert r.ok
    assert not r.missing_required
    assert not r.problems


def test_audit_finding_shape_is_rejected() -> None:
    """The real #406-409 shape: evidence, no work order."""
    body = """
Filed by the weekly audit.

## Finding — severity BROKEN
**138 work Q-IDs are assigned to more than one sidecar.**

Not auto-applied: distinguishing duplicate-work from series-Q-ID needs judgement.
"""
    r = validate(body)
    assert not r.ok
    assert "Tasks" in r.missing_required
    assert "Acceptance Criteria" in r.missing_required


def test_acceptance_without_a_named_gate_is_rejected() -> None:
    body = """
## Tasks
- [ ] Fix the thing

## Acceptance Criteria
- The code works correctly
- Behaviour meets requirements
"""
    r = validate(body)
    assert not r.ok
    assert any("names no test" in p for p in r.problems)


def test_subjective_adjectives_are_flagged() -> None:
    body = """
## Tasks
- [ ] Fix it

## Acceptance Criteria
- `pytest tests/test_x.py::test_y` passes
- The result is clean and fast
"""
    r = validate(body)
    assert r.ok  # a real gate is present, so it is processable
    assert any("subjective wording" in p for p in r.problems)


def test_tasks_without_checkboxes_is_flagged() -> None:
    body = """
## Tasks
Do the work.

## Acceptance Criteria
- `pytest tests/test_x.py` passes
"""
    r = validate(body)
    assert any("no checkbox" in p for p in r.problems)


def test_heading_aliases_are_honoured() -> None:
    body = """
## Implementation
- [ ] Do it

## Definition of Done
- `make test` passes
"""
    assert validate(body).ok


def test_gh_run_command_is_a_qualifying_gate() -> None:
    body = """
## Tasks
- [ ] Inspect the failed run

## Acceptance Criteria
- `gh run view 12345 --log-failed` reports no failing jobs
"""
    assert validate(body).ok


def test_heading_with_trailing_qualifier_still_matches() -> None:
    body = """
## Tasks (in order)
- [ ] Step one

## Acceptance Criteria (all must hold)
- `tests/test_a.py::test_b` passes
"""
    assert validate(body).ok


def test_empty_body_is_rejected_not_crashed() -> None:
    r = validate("")
    assert not r.ok
    assert set(r.missing_required) == {"Tasks", "Acceptance Criteria"}
