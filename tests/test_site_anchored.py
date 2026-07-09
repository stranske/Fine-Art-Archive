"""Site-anchored sidecar and place-object verification tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive import sidecar  # noqa: E402
from fine_art_archive.collect.verify import verify_place_object  # noqa: E402


def _minimal_meta() -> dict[str, Any]:
    return {
        "work_id": "75d1fab-chartres-south-rose-window",
        "schema_version": "1.0",
        "category": "stained_glass",
        "artist": {
            "name": "Anonymous",
            "relation": "anonymous",
            "attribution_anchor": "Q4233718",
        },
        "title": "South Rose Window, Chartres Cathedral",
        "site": {
            "name": "Chartres Cathedral",
            "wikidata_q": "Q188527",
            "element": "South rose window",
            "commons_category": "Category:Rose windows of Chartres Cathedral",
            "depicts_q": ["Q188527"],
        },
        "depicts": {
            "label": "South rose window",
            "wikidata_q": "Q188527",
            "hierarchy": [
                {"label": "Chartres Cathedral", "wikidata_q": "Q188527"},
            ],
        },
        "files": {
            "master": {
                "filename": "master.png",
                "sha256": "75d1fab" + ("0" * 57),
                "size_bytes": 1234,
                "ingested_at": "2026-07-09T15:00:00Z",
            },
            "variants": [
                {
                    "rel_path": "works/75d1fab-chartres-south-rose-window/detail.png",
                    "role": "place-capture",
                }
            ],
        },
        "history": [
            {
                "ts": "2026-07-09T15:00:00Z",
                "actor": "codex",
                "op": "site-anchored-sidecar",
            }
        ],
    }


def _save(path: Path, image: Image.Image) -> Path:
    image.save(path, format="PNG")
    return path


def _rose_window(size: tuple[int, int] = (180, 180)) -> Image.Image:
    image = Image.new("RGB", size, (22, 28, 36))
    draw = ImageDraw.Draw(image)
    w, h = size
    cx, cy = w // 2, h // 2
    for radius, color in ((78, (185, 43, 58)), (58, (38, 93, 164)), (34, (232, 185, 70))):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=color, width=8)
    spokes = [
        (82, 0),
        (79, 21),
        (71, 41),
        (58, 58),
        (41, 71),
        (21, 79),
        (0, 82),
        (-21, 79),
        (-41, 71),
        (-58, 58),
        (-71, 41),
        (-79, 21),
    ]
    for dx, dy in spokes:
        draw.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=(238, 236, 210), width=3)
    return image


def _unrelated_arch(size: tuple[int, int] = (180, 180)) -> Image.Image:
    image = Image.new("RGB", size, (230, 228, 210))
    draw = ImageDraw.Draw(image)
    draw.rectangle((15, 35, 165, 160), fill=(116, 112, 104))
    draw.rectangle((45, 75, 70, 160), fill=(35, 36, 40))
    draw.rectangle((110, 75, 135, 160), fill=(35, 36, 40))
    return image


def _alternate_view(image: Image.Image) -> Image.Image:
    return image.crop((18, 8, 172, 164)).resize(image.size).rotate(3, fillcolor=(22, 28, 36))


def _shape_embedding(image: Image.Image) -> list[float]:
    resized = image.convert("RGB").resize((32, 32))
    mask: list[list[float]] = []
    for y in range(32):
        row: list[float] = []
        for x in range(32):
            red, green, blue = cast(tuple[int, int, int], resized.getpixel((x, y)))
            is_dark = (red + green + blue) / 3 < 80
            is_saturated = max(red, green, blue) - min(red, green, blue) > 45
            row.append(1.0 if is_dark or is_saturated else 0.0)
        mask.append(row)
    features: list[float] = []
    for y in range(0, 32, 8):
        for x in range(0, 32, 8):
            block_total = sum(mask[row][col] for row in range(y, y + 8) for col in range(x, x + 8))
            features.append(block_total / 64.0)
    return features


def test_site_anchored_sidecar_validates_and_derives_predicate():
    meta = _minimal_meta()

    assert sidecar.is_valid(meta)
    assert sidecar.is_site_anchored(meta)

    meta["category"] = "photograph"
    assert sidecar.is_valid(meta)
    assert not sidecar.is_site_anchored(meta)


def test_place_object_verify_passes_alternate_view(tmp_path):
    meta = _minimal_meta()
    reference = _save(tmp_path / "commons-reference.png", _rose_window())
    candidate = _save(tmp_path / "candidate.png", _alternate_view(_rose_window()))

    report = verify_place_object(
        meta=meta,
        candidate_path=candidate,
        reference_paths=[reference],
        embedding_backend=_shape_embedding,
    )

    statuses = {check.name: check.status for check in report.checks}
    assert report.overall == "PASS"
    assert statuses["site_identity"] == "PASS"
    assert statuses["site_embedding_similarity"] == "PASS"


def test_place_object_verify_fails_unrelated_image(tmp_path):
    meta = _minimal_meta()
    reference = _save(tmp_path / "commons-reference.png", _rose_window())
    candidate = _save(tmp_path / "candidate.png", _unrelated_arch())

    report = verify_place_object(
        meta=meta,
        candidate_path=candidate,
        reference_paths=[reference],
        embedding_backend=_shape_embedding,
    )

    assert report.overall == "FAIL"
    similarity = report.checks[-1]
    assert similarity.name == "site_embedding_similarity"
    assert similarity.status == "FAIL"
    assert similarity.detail["best_cosine_similarity"] < 0.55


def test_place_object_verify_fails_without_commons_anchor(tmp_path):
    meta = _minimal_meta()
    meta["site"]["commons_category"] = None
    candidate = _save(tmp_path / "candidate.png", _rose_window())

    report = verify_place_object(
        meta=meta,
        candidate_path=candidate,
        reference_paths=[],
        embedding_backend=_shape_embedding,
    )

    assert report.overall == "FAIL"
    assert report.checks[0].name == "site_identity"
    assert report.checks[0].status == "FAIL"
