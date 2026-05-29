from __future__ import annotations

from pathlib import Path

from scripts import sync_test_dependencies


def test_fallback_fix_handles_dev_group_with_trailing_optional_groups(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "example"
version = "0.1.0"

[project.optional-dependencies]
dev = [
    "pytest==9.0.3",
] # keep comment
docs = [
    "mkdocs",
]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    original_pyproject_file = sync_test_dependencies.PYPROJECT_FILE
    original_tomlkit_error = sync_test_dependencies.TOMLKIT_ERROR
    try:
        sync_test_dependencies.PYPROJECT_FILE = pyproject
        sync_test_dependencies.TOMLKIT_ERROR = ImportError("tomlkit unavailable")
        changed = sync_test_dependencies._add_dependencies_without_tomlkit({"requests"})
    finally:
        sync_test_dependencies.PYPROJECT_FILE = original_pyproject_file
        sync_test_dependencies.TOMLKIT_ERROR = original_tomlkit_error

    assert changed
    text = pyproject.read_text(encoding="utf-8")
    assert '"requests",' in text
    assert "docs = [" in text
