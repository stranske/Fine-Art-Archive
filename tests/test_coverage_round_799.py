"""Focused regressions for coverage-autopilot issue #799."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_perceptual_hash_uses_working_imagehash_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = _image(tmp_path / "candidate.png")
    reference = _image(tmp_path / "reference.png")

    class Hash:
        def __sub__(self, _: object) -> int:
            return 0

    monkeypatch.setitem(
        sys.modules,
        "imagehash",
        SimpleNamespace(phash=lambda _: Hash(), dhash=lambda _: Hash()),
    )

    result = check_perceptual_hash(candidate_path=candidate, reference_path=reference)

    assert result.status == "PASS"
    assert result.detail["hash_backend"] == "imagehash"


def test_open_clip_backend_wraps_model_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    class Tensor:
        def unsqueeze(self, _: int) -> Tensor:
            return self

        def norm(self, *, dim: int, keepdim: bool) -> Tensor:
            assert (dim, keepdim) == (-1, True)
            return self

        def __truediv__(self, _: Tensor) -> Tensor:
            return self

        def squeeze(self, _: int) -> Tensor:
            return self

        def detach(self) -> Tensor:
            return self

        def cpu(self) -> Tensor:
            return self

        def tolist(self) -> list[float]:
            return [0.25, 0.75]

    class Model:
        def eval(self) -> None:
            return None

        def encode_image(self, _: Tensor) -> Tensor:
            return Tensor()

    class NoGrad:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *_: object) -> None:
            return None

    open_clip = SimpleNamespace(
        create_model_and_transforms=lambda *_args, **_kwargs: (Model(), None, lambda _: Tensor())
    )
    torch = SimpleNamespace(no_grad=lambda: NoGrad())
    monkeypatch.setitem(sys.modules, "open_clip", open_clip)
    monkeypatch.setitem(sys.modules, "torch", torch)
    verify_module._load_open_clip_backend.cache_clear()

    assert verify_module._load_open_clip_backend()(Image.new("RGB", (2, 2))) == [0.25, 0.75]
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

    assert check_place_object_similarity(
        candidate_path=candidate, reference_paths=[], embedding_backend=lambda _: [1.0]
    ).status == "FAIL"

    def unavailable() -> object:
        raise ImportError("open_clip")

    monkeypatch.setattr(verify_module, "_load_open_clip_backend", unavailable)
    assert check_place_object_similarity(candidate_path=candidate, reference_paths=[candidate]).status == "FAIL"

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


def test_place_similarity_records_best_of_multiple_references(tmp_path: Path) -> None:
    candidate = _image(tmp_path / "candidate.png")
    first = _image(tmp_path / "first.png")
    second = _image(tmp_path / "second.png")

    result = check_place_object_similarity(
        candidate_path=candidate,
        reference_paths=[first, second],
        embedding_backend=lambda _: [1.0],
    )

    assert result.status == "PASS"
    assert result.detail["best_reference"] == str(first)
    assert len(result.detail["scores"]) == 2


def test_verify_reports_unreadable_candidate_as_aspect_failure(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jpg"

    report = verify(h_cm=10.0, w_cm=10.0, h_px=10, w_px=10, candidate_path=missing)

    assert report.overall == "FAIL"
    assert "candidate image unavailable" in report.checks[0].message


def test_acquisition_configuration_and_artist_name_failure_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="source-quality config not found"):
        af.load_source_quality_config(missing)

    config = tmp_path / "quality.yaml"
    config.write_text("sources: {}")
    monkeypatch.setattr(af.source_quality, "load_aggregates", lambda _: {})
    with pytest.raises(ValueError, match="has no sources"):
        af.load_source_quality_config(config)

    monkeypatch.setattr(af.host_registry, "find_by_wikidata_q", lambda *_: None)
    assert af.source_chain_for_host("Q0", config) == []
    with pytest.raises(ValueError, match="candidate_sources must not be empty"):
        af.select_source("painting", [], {})

    assert af._candidate_artist_name({"artist": {"name": "  "}}) == ""
    assert af._candidate_artist_name({"artist": {"label": "  Artist  "}}) == "Artist"
    assert af._candidate_artist_name({"artist": 12}) == ""


def test_acquisition_flow_accepts_work_without_metadata(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    _image(work / "master.jpg")

    [result] = af.run_acquisition_flow("met", [work])

    assert result.source == "met"
