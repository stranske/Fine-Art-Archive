"""Keep repository-owned CI callers on the owner's tested Python standard."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
RUNTIME_KEYS = {
    "python-version",
    "python-versions",
    "primary-python-version",
    "coverage-python-version",
    "PYTHON_VERSION",
    "COVERAGE_REFERENCE_RUNTIME",
}


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Reject ambiguous workflow mappings before any runtime pins can be discarded."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in keys:
                raise yaml.constructor.ConstructorError(
                    "while constructing a workflow mapping",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def _runtime_pins(
    node: Any, location: str, *, in_matrix: bool = False
) -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{location}.{key}"
            if key in RUNTIME_KEYS or (in_matrix and key == "python"):
                yield path, value
            yield from _runtime_pins(
                value,
                path,
                in_matrix=in_matrix or (key == "matrix" and location.endswith(".strategy")),
            )
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _runtime_pins(value, f"{location}[{index}]", in_matrix=in_matrix)


def _contains_old_runtime(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_old_runtime(item) for item in value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            pass
        else:
            if decoded != value:
                return _contains_old_runtime(decoded)
    return str(value) == "3.12" or str(value).startswith("3.12.")


def test_workflow_python_pins_follow_standard() -> None:
    workflows = {
        path.name: yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader)
        for path in sorted(WORKFLOWS.iterdir())
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    }
    assert workflows, "No workflow YAML was inspected"
    offenders = [
        location
        for filename, workflow in workflows.items()
        for location, value in _runtime_pins(workflow, filename)
        if _contains_old_runtime(value)
    ]
    assert not offenders, f"Python 3.12 runtime pins remain: {offenders}"
    for filename, job in (("ci.yml", "python"), ("pr-00-gate.yml", "python-ci")):
        config = workflows[filename]["jobs"][job]
        assert json.loads(config["with"]["python-versions"]) == ["3.13", "3.14"]
        assert not config.get("continue-on-error", False)


@pytest.mark.parametrize(
    "matrix",
    [
        {"python": ["3.12"]},
        {"python": ["3.12.9", "3.14"]},
        {"include": [{"python": "3.12", "os": "ubuntu-latest"}]},
    ],
)
def test_named_python_matrix_cannot_hide_old_runtime(matrix: dict[str, Any]) -> None:
    workflow = {
        "jobs": {
            "test": {
                "strategy": {"matrix": matrix},
                "steps": [{"with": {"python-version": "${{ matrix.python }}"}}],
            }
        }
    }
    offenders = [
        path for path, value in _runtime_pins(workflow, "ci.yml") if _contains_old_runtime(value)
    ]
    assert len(offenders) == 1
    assert ".strategy.matrix." in offenders[0]


@pytest.mark.parametrize("filename, job", [("ci.yml", "python"), ("pr-00-gate.yml", "python-ci")])
def test_json_matrix_deliberate_break_and_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, job: str
) -> None:
    """The named guard must reject a restored 3.12 JSON pin in either caller."""
    for name in ("ci.yml", "pr-00-gate.yml"):
        (tmp_path / name).write_bytes((WORKFLOWS / name).read_bytes())
    monkeypatch.setattr(f"{__name__}.WORKFLOWS", tmp_path)
    test_workflow_python_pins_follow_standard()

    path = tmp_path / filename
    original = path.read_bytes()
    workflow = yaml.safe_load(original)
    workflow["jobs"][job]["with"]["python-versions"] = '["3.12", "3.14"]'
    path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    with pytest.raises(AssertionError, match="Python 3.12 runtime pins remain") as failure:
        test_workflow_python_pins_follow_standard()
    assert str(failure.value).splitlines()[0] == (
        f"Python 3.12 runtime pins remain: ['{filename}.jobs.{job}.with.python-versions']"
    )

    path.write_bytes(original)
    test_workflow_python_pins_follow_standard()


def test_unrelated_python_metadata_is_not_a_runtime_pin() -> None:
    assert list(_runtime_pins({"metadata": {"python": "3.12"}}, "ci.yml")) == []


@pytest.mark.parametrize("filename, job", [("ci.yml", "python"), ("pr-00-gate.yml", "python-ci")])
@pytest.mark.parametrize("old_pin_first", [True, False])
def test_duplicate_runtime_pin_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    job: str,
    old_pin_first: bool,
) -> None:
    """Duplicate keys must not silently discard either caller's runtime pin."""
    for name in ("ci.yml", "pr-00-gate.yml"):
        (tmp_path / name).write_bytes((WORKFLOWS / name).read_bytes())
    monkeypatch.setattr(f"{__name__}.WORKFLOWS", tmp_path)
    pins = ['["3.12", "3.14"]', '["3.13", "3.14"]']
    if not old_pin_first:
        pins.reverse()
    (tmp_path / filename).write_text(
        f"jobs:\n  {job}:\n    with:\n"
        f"      python-versions: '{pins[0]}'\n"
        f"      python-versions: '{pins[1]}'\n",
        encoding="utf-8",
    )
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key 'python-versions'"):
        test_workflow_python_pins_follow_standard()


@pytest.mark.parametrize("suffix", [".yml", ".yaml"])
def test_duplicate_environment_pin_in_another_workflow_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    """The guard must inspect duplicate pins outside the two repository-owned callers."""
    for name in ("ci.yml", "pr-00-gate.yml"):
        (tmp_path / name).write_bytes((WORKFLOWS / name).read_bytes())
    monkeypatch.setattr(f"{__name__}.WORKFLOWS", tmp_path)
    (tmp_path / f"other{suffix}").write_text(
        "env:\n  PYTHON_VERSION: '3.12'\n  PYTHON_VERSION: '3.14'\n", encoding="utf-8"
    )
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key 'PYTHON_VERSION'"):
        test_workflow_python_pins_follow_standard()
