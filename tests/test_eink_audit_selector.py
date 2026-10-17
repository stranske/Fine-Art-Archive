"""The opt-in audit harness must cap waits without opening real sockets."""

import importlib.util
import selectors
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("requested", "expected"), [(None, 0.01), (1.0, 0.01), (0.01, 0.01), (0.005, 0.005), (0, 0)]
)
def test_audit_selector_caps_only_long_waits(monkeypatch, requested, expected):
    waits = []
    result = object()

    class RecordingSelector:
        def select(self, timeout=None):
            waits.append(timeout)
            return result

    # Import the actual helper against a fake parent: no process-wide selector
    # replacement survives fixture teardown and no operating-system I/O occurs.
    monkeypatch.setattr(selectors, "DefaultSelector", RecordingSelector)
    path = (
        Path(__file__).resolve().parents[1]
        / "docs/reports/eink_surface_audit/sandbox/sitecustomize.py"
    )
    spec = importlib.util.spec_from_file_location("audit_selector_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.AuditPollingSelector().select(requested) is result
    assert waits == [expected]
