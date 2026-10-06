"""Tagger transport and payload boundaries through the actual HTTP endpoint."""

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main


@pytest.fixture
def tagger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = tmp_path / "vision_tag_works.py"
    script.touch()
    monkeypatch.setattr(main, "TAGGER_SCRIPT", script)
    monkeypatch.setattr(main, "TAGGER_PYTHON", "isolated-python")
    monkeypatch.setattr(main, "TAGGER_TIMEOUT_S", 7)
    return TestClient(main.app), script


def respond(monkeypatch, *, stdout="", stderr="", returncode=0):
    monkeypatch.setattr(
        main.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], returncode, stdout, stderr),
    )


def test_invalid_work_id_never_launches_tagger(tagger, monkeypatch):
    client, _ = tagger

    def forbidden(*args, **kwargs):
        pytest.fail("invalid identity launched tagger")

    monkeypatch.setattr(main.subprocess, "run", forbidden)
    response = client.post("/works/bad%20id/propose_tags")
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid work_id"}


def test_missing_script_reports_unavailable_without_launch(tagger, monkeypatch):
    client, script = tagger
    script.unlink()

    def forbidden(*args, **kwargs):
        pytest.fail("missing script launched tagger")

    monkeypatch.setattr(main.subprocess, "run", forbidden)
    response = client.post("/works/work-1/propose_tags")
    assert response.status_code == 503
    assert "FAA_TAGGER_SCRIPT" in response.json()["detail"]


def test_timeout_is_a_gateway_timeout(tagger, monkeypatch):
    client, _ = tagger

    def expired(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(main.subprocess, "run", expired)
    response = client.post("/works/work-1/propose_tags")
    assert response.status_code == 504
    assert response.json() == {"detail": "tagger timed out after 7s"}


def test_failed_process_reports_only_last_four_error_lines(tagger, monkeypatch):
    client, _ = tagger
    respond(monkeypatch, returncode=1, stdout='{"works": []}', stderr="old\na\nb\nc\nd\n")
    response = client.post("/works/work-1/propose_tags")
    assert response.status_code == 500
    assert response.json() == {"detail": "tagger failed: a / b / c / d"}


@pytest.mark.parametrize("stdout", ["", "progress only", '{"works": []}\ntrailing noise'])
def test_missing_final_json_reports_controlled_error(tagger, monkeypatch, stdout):
    client, _ = tagger
    respond(monkeypatch, stdout=stdout, stderr="diagnostic")
    response = client.post("/works/work-1/propose_tags")
    assert response.status_code == 500
    assert response.json() == {"detail": "tagger produced no JSON: diagnostic"}


@pytest.mark.parametrize(
    "payload",
    [None, [], "text", {"works": {}}, {"works": "text"}, {"works": [None]}, {"gate": []}],
    ids=["null", "list", "string", "works-object", "works-string", "null-work", "gate-list"],
)
def test_invalid_json_shape_reports_controlled_error(tagger, monkeypatch, payload):
    client, _ = tagger
    respond(monkeypatch, stdout=json.dumps(payload))
    response = client.post("/works/work-1/propose_tags")
    assert response.status_code == 500
    assert response.json() == {"detail": "tagger produced invalid JSON structure"}


def test_valid_result_preserves_proposals_and_launch_contract(tagger, monkeypatch):
    client, script = tagger
    payload = {
        "model": "clip-local",
        "gate": {"tags_enabled": ["theme:sea"]},
        "works": [
            {
                "written": True,
                "error": None,
                "proposals": [{"tag": "theme:sea", "score": 0.9}],
                "clip_tags_added": 1,
                "genre": "seascape",
                "genre_source": "clip",
                "elapsed_ms": 42,
            }
        ],
    }
    calls = []

    def completed(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "loading model\n" + json.dumps(payload), "")

    monkeypatch.setattr(main.subprocess, "run", completed)
    response = client.post("/works/work-1/propose_tags")
    assert response.status_code == 200
    assert response.json() == {
        "work_id": "work-1",
        "model": "clip-local",
        **payload["works"][0],
        "tags_enabled": ["theme:sea"],
    }
    assert calls == [
        (
            ["isolated-python", str(script), "--wid", "work-1", "--json", "--apply"],
            {"capture_output": True, "text": True, "timeout": 7, "check": False},
        )
    ]


def test_empty_result_uses_explicit_defaults(tagger, monkeypatch):
    client, _ = tagger
    respond(monkeypatch, stdout='{"model":"clip-local","works":[],"gate":null}')
    response = client.post("/works/work-1/propose_tags")
    assert response.status_code == 200
    assert response.json() == {
        "work_id": "work-1",
        "model": "clip-local",
        "written": False,
        "error": None,
        "proposals": [],
        "clip_tags_added": 0,
        "genre": None,
        "genre_source": None,
        "tags_enabled": [],
        "elapsed_ms": None,
    }
