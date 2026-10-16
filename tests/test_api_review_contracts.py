"""HTTP contracts for the next ranked coverage target, api/main.py."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import gates
from fine_art_archive.api import main as api


def _gate(name: str, items: list[dict]) -> gates.Gate:
    return gates.Gate(
        name=name,
        label="Owner review",
        blocking=len(items),
        drainable=None,
        clears_by="record an owner decision",
        item_kind="held_work",
        items=items,
    )


@pytest.mark.parametrize("route", ["acquisitions", "review/works", "review/artists", "review/held"])
def test_review_lists_reject_zero_limit_before_loading_state(
    monkeypatch: pytest.MonkeyPatch, route: str
) -> None:
    loader = Mock(side_effect=AssertionError("invalid requests must not load review state"))
    monkeypatch.setattr(api, "_all_gates", loader)
    monkeypatch.setattr(api.store, "acquisitions_since_epoch", loader)
    monkeypatch.setattr(gates, "load_allowlisted_artists", loader)

    with TestClient(api.app) as client:
        response = client.get(f"/{route}", params={"limit": 0})

    assert response.status_code == 400
    assert response.json() == {"detail": "limit must be >= 1"}
    loader.assert_not_called()


@pytest.mark.parametrize("limit", [1, 5], ids=["truncated", "all-items"])
def test_gate_details_preserve_summary_and_item_order(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    items = [{"id": "second-by-name"}, {"id": "first-by-name"}]
    held = _gate("held", items)
    monkeypatch.setattr(api, "_all_gates", lambda: [_gate("unrelated", []), held])

    with TestClient(api.app) as client:
        response = client.get("/review/held", params={"limit": limit})

    assert response.status_code == 200
    assert response.json() == {
        "name": "held",
        "label": "Owner review",
        "blocking": 2,
        "drainable": None,
        "drainable_measured": False,
        "clears_by": "record an owner decision",
        "advisory": True,
        "auto_clears": False,
        "item_kind": "held_work",
        "note": "",
        "deadlocked": False,
        "returned": min(limit, 2),
        "items": items[:limit],
    }
    assert held.items == items
    assert held.blocking == 2


@pytest.mark.parametrize("has_other_gate", [False, True], ids=["no-gates", "other-gate"])
def test_unknown_gate_is_404_even_when_other_gates_exist(
    monkeypatch: pytest.MonkeyPatch, has_other_gate: bool
) -> None:
    monkeypatch.setattr(api, "_all_gates", lambda: [_gate("other", [])] if has_other_gate else [])

    with TestClient(api.app) as client:
        response = client.get("/review/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "no gate named 'missing'"}


def test_artist_review_omits_candidates_without_artist_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "_all_gates",
        lambda: [_gate("new_artist", [{"id": "Q10"}, {"id": "Q11", "artist_qid": ""}])],
    )
    monkeypatch.setattr(gates, "load_allowlisted_artists", lambda: set())

    with TestClient(api.app) as client:
        response = client.get("/review/artists")

    assert response.status_code == 200
    assert response.json() == {
        "total_artists": 0,
        "total_works": 0,
        "already_decided": 0,
        "returned": 0,
        "artists": [],
    }


def test_artist_review_recovers_label_from_a_later_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "_all_gates",
        lambda: [
            _gate("new_artist", [{"id": "Q10", "artist_qid": "Q100", "sitelinks": 1}]),
            _gate(
                "routed_to_review",
                [
                    {
                        "id": "Q11",
                        "artist_qid": "Q100",
                        "artist_label": "A Painter",
                        "sitelinks": 5,
                        "would_pass_now": False,
                    }
                ],
            ),
        ],
    )
    monkeypatch.setattr(gates, "load_allowlisted_artists", lambda: {"Q200"})

    with TestClient(api.app) as client:
        response = client.get("/review/artists")

    assert response.status_code == 200
    body = response.json()
    assert (body["total_artists"], body["total_works"], body["already_decided"]) == (1, 2, 1)
    assert body["returned"] == 1
    artist = body["artists"][0]
    assert artist["artist_qid"] == "Q100"
    assert artist["artist_label"] == "A Painter"
    assert artist["gates"] == ["new_artist", "routed_to_review"]
    assert (artist["n_released"], artist["n_held_elsewhere"]) == (1, 1)
    assert [(work["id"], work["ready"]) for work in artist["works"]] == [
        ("Q11", False),
        ("Q10", True),
    ]
