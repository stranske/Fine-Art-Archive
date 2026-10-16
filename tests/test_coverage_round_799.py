"""Focused regressions for coverage-autopilot issue #799."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from PIL import Image

from fine_art_archive.collect import acquisition_flow as af
from fine_art_archive.collect import verify as verify_module
from fine_art_archive.collect.verify import (
    CheckResult,
    VerificationReport,
    check_embedding_similarity,
    check_perceptual_hash,
    check_place_object_similarity,
    check_site_identity,
    verify,
)


def _image(path: Path, color: tuple[int, int, int] = (20, 40, 80)) -> Path:
    Image.new("RGB", (16, 12), color).save(path)
    return path


def test_report_unverified_inputs_distinguish_skip_from_failure() -> None:
    report = VerificationReport([CheckResult("aspect_ratio", "SKIP")])

    assert report.overall == "UNVERIFIED"
    assert report.to_source_quality_inputs() == {
        "verify_match": None,
        "phash_match": None,
        "aspect_match": None,
        "dim_match": None,
    }

    assert VerificationReport([CheckResult("other", "UNVERIFIED")]).overall == "UNVERIFIED"


def test_perceptual_hash_falls_back_when_imagehash_backend_raises_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _image(tmp_path / "candidate.png")
    reference = _image(tmp_path / "reference.png")

    class BrokenImageHash:
        @staticmethod
        def phash(_: Image.Image) -> object:
            raise ValueError("incompatible scipy backend")

    monkeypatch.setitem(sys.modules, "imagehash", BrokenImageHash)

    result = check_perceptual_hash(candidate_path=candidate, reference_path=reference)

    assert result.status == "PASS"
    assert result.detail["hash_backend"] == "fallback"


@pytest.mark.parametrize(
    ("phash_distance", "dhash_distance", "status"),
    [(12, 8, "PASS"), (13, 7, "PASS"), (13, 8, "FAIL")],
    ids=["phash-at-threshold", "dhash-at-threshold", "both-over-threshold"],
)
def test_perceptual_hash_uses_working_imagehash_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phash_distance: int,
    dhash_distance: int,
    status: str,
) -> None:
    candidate = _image(tmp_path / "candidate.png")
    reference = _image(tmp_path / "reference.png")

    monkeypatch.setitem(
        sys.modules,
        "imagehash",
        SimpleNamespace(
            phash=Mock(side_effect=[phash_distance, 0]),
            dhash=Mock(side_effect=[dhash_distance, 0]),
        ),
    )

    result = check_perceptual_hash(
        candidate_path=candidate,
        reference_path=reference,
        phash_threshold=12,
        dhash_threshold=7,
        blocks_overall=False,
    )

    assert result.status == status
    assert result.blocks_overall is False
    assert result.detail["phash_distance"] == phash_distance
    assert result.detail["dhash_distance"] == dhash_distance
    assert result.detail["hash_backend"] == "imagehash"


@pytest.mark.parametrize("different", [False, True], ids=["same-work", "different-work"])
def test_perceptual_hash_fallback_preserves_image_discrimination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, different: bool
) -> None:
    # Exact-size opposing gradients give 64 differing bits in both fallback hashes.
    image = Image.new("L", (9, 8))
    image.putdata([x * 30 for _ in range(8) for x in range(9)])
    candidate = tmp_path / "candidate.png"
    reference = tmp_path / "reference.png"
    image.save(candidate)
    (image.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if different else image).save(reference)
    monkeypatch.setitem(sys.modules, "imagehash", None)

    result = check_perceptual_hash(candidate_path=candidate, reference_path=reference)

    assert result.status == ("FAIL" if different else "PASS")
    assert result.detail["hash_backend"] == "fallback"
    assert result.detail["phash_distance"] == (64 if different else 0)
    assert result.detail["dhash_distance"] == (64 if different else 0)


def test_open_clip_backend_wraps_model_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    model = Mock()
    preprocess = Mock()
    vector = MagicMock()
    normalized = vector.__truediv__.return_value
    normalized.squeeze.return_value.detach.return_value.cpu.return_value.tolist.return_value = [
        0.25,
        0.75,
    ]
    model.encode_image.return_value = vector
    factory = Mock(return_value=(model, None, preprocess))
    no_grad = MagicMock()
    monkeypatch.setitem(
        sys.modules, "open_clip", SimpleNamespace(create_model_and_transforms=factory)
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(no_grad=no_grad))
    verify_module._load_open_clip_backend.cache_clear()
    try:
        backend = verify_module._load_open_clip_backend()
        assert verify_module._load_open_clip_backend() is backend
        image = Image.new("RGB", (2, 2))
        assert backend(image) == [0.25, 0.75]
        factory.assert_called_once_with("ViT-B-32", pretrained="laion2b_s34b_b79k")
        model.eval.assert_called_once_with()
        preprocess.assert_called_once_with(image)
        preprocess.return_value.unsqueeze.assert_called_once_with(0)
        model.encode_image.assert_called_once_with(preprocess.return_value.unsqueeze.return_value)
        no_grad.return_value.__enter__.assert_called_once_with()
        no_grad.return_value.__exit__.assert_called_once_with(None, None, None)
        vector.norm.assert_called_once_with(dim=-1, keepdim=True)
        vector.__truediv__.assert_called_once_with(vector.norm.return_value)
        normalized.squeeze.assert_called_once_with(0)
    finally:
        verify_module._load_open_clip_backend.cache_clear()


def test_embedding_and_site_identity_reject_invalid_inputs(tmp_path: Path) -> None:
    candidate = _image(tmp_path / "candidate.png")
    reference = _image(tmp_path / "reference.png")

    mismatch = check_embedding_similarity(
        candidate_path=candidate,
        reference_path=reference,
        embedding_backend=lambda _: [1.0],
    )
    assert mismatch.status == "PASS"

    values = iter(([1.0], [1.0, 2.0]))
    invalid = check_embedding_similarity(
        candidate_path=candidate,
        reference_path=reference,
        embedding_backend=lambda _: next(values),
    )
    assert invalid.status == "FAIL"
    assert "same length" in invalid.message

    zero_vector = check_embedding_similarity(
        candidate_path=candidate,
        reference_path=reference,
        embedding_backend=lambda _: [0.0],
    )
    assert zero_vector.status == "FAIL"
    assert "non-zero" in zero_vector.message

    assert check_site_identity({"category": "painting"}).status == "FAIL"
    assert check_site_identity({"category": "stained_glass", "site": {}}).status == "FAIL"


def test_place_similarity_handles_empty_unavailable_and_invalid_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _image(tmp_path / "candidate.png")
    unreadable = tmp_path / "unreadable.png"
    unreadable.write_text("not an image")

    assert (
        check_place_object_similarity(
            candidate_path=candidate, reference_paths=[], embedding_backend=lambda _: [1.0]
        ).status
        == "FAIL"
    )

    def unavailable() -> object:
        raise ImportError("open_clip")

    monkeypatch.setattr(verify_module, "_load_open_clip_backend", unavailable)
    assert (
        check_place_object_similarity(candidate_path=candidate, reference_paths=[candidate]).status
        == "FAIL"
    )

    bad_reference = check_place_object_similarity(
        candidate_path=candidate, reference_paths=[unreadable], embedding_backend=lambda _: [1.0]
    )
    assert bad_reference.status == "FAIL"
    assert "failed to load reference" in bad_reference.message

    values = iter(([1.0], [1.0, 2.0]))
    invalid_vector = check_place_object_similarity(
        candidate_path=candidate,
        reference_paths=[candidate],
        embedding_backend=lambda _: next(values),
    )
    assert invalid_vector.status == "FAIL"
    assert "same length" in invalid_vector.message


@pytest.mark.parametrize(
    ("vectors", "best_index", "scores"),
    [
        ([(1.0, 0.0), (0.0, 1.0), (1.0, 1.0)], 1, [0.0, 0.7071]),
        ([(1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], 0, [0.7071, 0.0]),
        ([(1.0, 0.0), (1.0, 1.0), (1.0, 1.0)], 0, [0.7071, 0.7071]),
    ],
    ids=["later-best", "earlier-best", "tie-keeps-first"],
)
def test_place_similarity_records_best_of_multiple_references(
    tmp_path: Path,
    vectors: list[tuple[float, float]],
    best_index: int,
    scores: list[float],
) -> None:
    candidate = _image(tmp_path / "candidate.png")
    first = _image(tmp_path / "first.png")
    second = _image(tmp_path / "second.png")

    values = iter(vectors)
    result = check_place_object_similarity(
        candidate_path=candidate,
        reference_paths=[first, second],
        embedding_backend=lambda _: next(values),
        threshold=0.7,
    )

    assert result.status == "PASS"
    assert result.detail == {
        "threshold": 0.7,
        "reference_count": 2,
        "best_reference": str([first, second][best_index]),
        "best_cosine_similarity": 0.7071,
        "scores": [
            {"reference": str(first), "cosine_similarity": scores[0]},
            {"reference": str(second), "cosine_similarity": scores[1]},
        ],
    }


def test_verify_reports_unreadable_candidate_as_aspect_failure(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jpg"

    report = verify(h_cm=10.0, w_cm=10.0, h_px=10, w_px=10, candidate_path=missing)

    assert report.overall == "FAIL"
    assert "candidate image unavailable" in report.checks[0].message


def test_acquisition_missing_quality_config(tmp_path: Path) -> None:
    """An explicit missing routing config must fail with its path in the error."""
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="source-quality config not found") as exc:
        af.load_source_quality_config(missing)
    assert str(missing) in str(exc.value)


def test_acquisition_quality_config_without_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing but empty config must fail independently of the missing-file guard."""
    config = tmp_path / "quality.yaml"
    config.write_text("sources: {}")
    loader = Mock(return_value={"sources": {}})
    monkeypatch.setattr(af.source_quality, "load_aggregates", loader)
    with pytest.raises(ValueError, match="has no sources") as exc:
        af.load_source_quality_config(config)
    loader.assert_called_once_with(config)
    assert str(config) in str(exc.value)


def test_acquisition_unknown_host_has_no_source_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown hosts return an empty chain using the caller's registry."""
    config = tmp_path / "hosts.yaml"
    lookup = Mock(return_value=None)
    monkeypatch.setattr(af.host_registry, "find_by_wikidata_q", lookup)
    assert af.source_chain_for_host("Q0", config) == []
    lookup.assert_called_once_with("Q0", config)


def test_acquisition_select_source_rejects_empty_candidates() -> None:
    """Empty candidates must produce a useful error rather than an indexing failure."""
    with pytest.raises(ValueError, match="candidate_sources must not be empty"):
        af.select_source("painting", [], {})


@pytest.mark.parametrize(
    ("artist", "expected"),
    [
        ({"name": "  "}, ""),
        ({"name": 12, "label": "  Artist  "}, "Artist"),
        ({"name": "", "label": " ", "display_name": "  Display Artist  "}, "Display Artist"),
        (12, ""),
    ],
    ids=["blank-name", "label-fallback", "display-name-fallback", "non-string-artist"],
)
def test_acquisition_candidate_artist_name(artist: object, expected: str) -> None:
    """Inventory matching gets a trimmed artist name or an empty string."""
    assert af._candidate_artist_name({"artist": artist}) == expected


def test_acquisition_flow_accepts_work_without_metadata(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    _image(work / "master.jpg")

    [result] = af.run_acquisition_flow("met", [work])

    assert result.source == "met"
    assert result.work_dir == work
    assert result.verification["status"] == "UNVERIFIED"
    assert result.verification["checks"][0]["status"] == "SKIP"
    assert result.fitness
