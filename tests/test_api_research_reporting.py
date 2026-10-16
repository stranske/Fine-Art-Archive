"""Research reports distinguish missing works, missing evidence, and developed dossiers."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store


@pytest.fixture
def research_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    works = tmp_path / "works"
    works.mkdir()
    monkeypatch.setattr(store, "WORKS", works)
    log = tmp_path / "research_requests.jsonl"
    monkeypatch.setattr(api_main, "RESEARCH_REQUESTS", log)
    return log


@pytest.mark.parametrize("operation", ["report", "request"])
def test_unknown_work_does_not_create_research_state(
    research_archive: Path, operation: str
) -> None:
    with TestClient(api_main.app) as client:
        if operation == "report":
            response = client.get("/works/unknown/research")
        else:
            response = client.post("/works/unknown/research_request", json={"note": "look closer"})

    assert response.status_code == 404
    assert response.json() == {"detail": "no sidecar for unknown"}
    assert not research_archive.exists()
    assert list(research_archive.parent.glob("*.lock")) == []


def test_missing_dossier_page_returns_a_handled_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_main, "DOSSIER_UI_FILE", tmp_path / "missing-dossier.html")
    monkeypatch.setattr(api_main, "_get_work_checked", lambda wid: {"work_id": wid})

    with TestClient(api_main.app) as client:
        response = client.get("/works/held/dossier")

    assert response.status_code == 404
    assert response.json() == {"detail": "dossier UI not found"}


@pytest.mark.parametrize("authority", [None, 7.9, 8], ids=["unscored", "below", "boundary"])
def test_research_report_identifies_missing_authoritative_sources(
    research_archive: Path, monkeypatch: pytest.MonkeyPatch, authority: float | None
) -> None:
    dossier = {
        "references": [{"kind": "essay", "authority_score": authority}, {}],
        "research": {
            "source_pool": [
                {"status": "PROMISING", "url": "https://example.org/private-lead"},
                {"status": "paywalled"},
                {"status": "unread"},
                {"status": "read"},
                {},
            ],
            "last_developed_at": "2026-10-01T12:00:00Z",
            "design_version": "v2",
        },
    }
    monkeypatch.setattr(api_main, "_get_work_checked", lambda wid: {"dossier": dossier})

    with TestClient(api_main.app) as client:
        response = client.get("/works/held/research")

    assert response.status_code == 200
    high = int(authority is not None and authority >= 8)
    gaps = ["no reading", "no stories", "no composition", "no context", "no provenance"]
    if not high:
        gaps.append("no high-authority source")
    assert response.json() == {
        "score": 5.4,
        "n_sources": 2,
        "n_high_authority": high,
        "n_promising_unread": 3,
        "kinds_covered": ["essay"],
        "gaps": [*gaps, "narrow source mix"],
        "sections": {"reading": 0, "stories": 0, "composition": 0, "context": 0, "provenance": 0},
        "last_developed_at": "2026-10-01T12:00:00Z",
        "design_version": "v2",
        "work_id": "held",
        "requested": False,
    }


def test_developed_dossier_saturates_score_without_hiding_actual_counts(
    research_archive: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dossier = {
        name: [{"text": "Observation"}] * 6
        for name in ("reading", "stories", "composition", "context", "provenance")
    }
    dossier["references"] = [
        {"kind": kind, "authority_score": 9}
        for kind in (
            "museum",
            "catalogue",
            "essay",
            "letter",
            "book",
            "article",
            "book",
            "book",
            "book",
        )
    ]
    monkeypatch.setattr(api_main, "_get_work_checked", lambda wid: {"dossier": dossier})

    with TestClient(api_main.app) as client:
        response = client.get("/works/held/research")

    assert response.status_code == 200
    assert response.json() == {
        "score": 100.0,
        "n_sources": 9,
        "n_high_authority": 9,
        "n_promising_unread": 0,
        "kinds_covered": ["article", "book", "catalogue", "essay", "letter", "museum"],
        "gaps": [],
        "sections": {"reading": 6, "stories": 6, "composition": 6, "context": 6, "provenance": 6},
        "last_developed_at": None,
        "design_version": None,
        "work_id": "held",
        "requested": False,
    }


@pytest.mark.parametrize(
    ("dossier", "expected_score", "expected_sources", "expected_kinds", "expected_reading"),
    [
        ({"reading": [{"text": "Observation"}] * 6}, 22.0, 0, [], 6),
        ({"references": [{"kind": "essay"}] * 9}, 14.4, 9, ["essay"], 0),
        (
            {
                "references": [
                    {"kind": kind}
                    for kind in ("article", "book", "catalogue", "essay", "letter", "museum")
                ]
            },
            21.0,
            6,
            ["article", "book", "catalogue", "essay", "letter", "museum"],
            0,
        ),
    ],
    ids=["section", "citations", "source-kinds"],
)
def test_dossier_score_saturates_each_evidence_component(
    research_archive: Path,
    monkeypatch: pytest.MonkeyPatch,
    dossier: dict,
    expected_score: float,
    expected_sources: int,
    expected_kinds: list[str],
    expected_reading: int,
) -> None:
    # Keep the other components empty so the overall 100-point ceiling cannot
    # conceal a broken cap in the component under test.
    monkeypatch.setattr(api_main, "_get_work_checked", lambda wid: {"dossier": dossier})

    with TestClient(api_main.app) as client:
        response = client.get("/works/held/research")

    assert response.status_code == 200
    report = response.json()
    assert report["score"] == expected_score
    assert report["n_sources"] == expected_sources
    assert report["kinds_covered"] == expected_kinds
    assert report["sections"]["reading"] == expected_reading
