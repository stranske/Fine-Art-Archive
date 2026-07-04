"""Tests for the D017 dedup cascade (collect/dedup_cascade.py) and its wiring into
the acquire path. The cheap layers (sha256 / pHash / artist-Q-ID / metadata) are
exercised directly; the DINOv2 layer is exercised via an injected stub hook (the
real vision pass needs torch + the archive embedding cache, run operationally).
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from fine_art_archive.collect.dedup_cascade import (
    ArchiveEntry,
    Candidate,
    dedup_check,
    hamming,
    load_archive_index,
    perceptual_hashes,
)

_FAR = (1 << 256) - 1  # max Hamming distance from 0 → never a pHash match


def _ramp(path: Path, *, reverse: bool = False) -> Path:
    img = Image.new("L", (256, 256))
    px = img.load()
    for y in range(256):
        for x in range(256):
            px[x, y] = (255 - x) if reverse else x
    img.save(path)
    return path


def test_hamming() -> None:
    assert hamming(0, 0) == 0
    assert hamming(0b1010, 0b1011) == 1
    assert hamming(0, (1 << 256) - 1) == 256


def test_perceptual_hashes_identity_and_sensitivity(tmp_path: Path) -> None:
    a, b, rev = (
        _ramp(tmp_path / "a.png"),
        _ramp(tmp_path / "b.png"),
        _ramp(tmp_path / "r.png", reverse=True),
    )
    da, _ = perceptual_hashes(a)
    db, _ = perceptual_hashes(b)
    dr, _ = perceptual_hashes(rev)
    assert hamming(da, db) == 0
    assert hamming(da, dr) > 200


def test_library_backed_hashes_flag_near_duplicate_and_distinct(tmp_path: Path) -> None:
    original = _ramp(tmp_path / "original.png")
    near = tmp_path / "near.jpg"
    distinct = _ramp(tmp_path / "distinct.png", reverse=True)
    with Image.open(original) as original_image:
        original_image.resize((128, 128)).save(near, "JPEG", quality=92)

    original_dh, original_ah = perceptual_hashes(original)
    near_dh, near_ah = perceptual_hashes(near)
    distinct_dh, distinct_ah = perceptual_hashes(distinct)

    archive = [
        ArchiveEntry(wid="near", dhash=near_dh, ahash=near_ah),
        ArchiveEntry(wid="distinct", dhash=distinct_dh, ahash=distinct_ah),
    ]
    verdict = dedup_check(Candidate(dhash=original_dh, ahash=original_ah), archive)

    assert verdict.is_duplicate
    assert verdict.layer == "phash"
    assert verdict.matched_wid == "near"
    assert hamming(original_dh, near_dh) <= 13
    assert hamming(original_dh, distinct_dh) > 200


def test_layer1_sha256_exact() -> None:
    cand = Candidate(sha256="deadbeef", dhash=_FAR, artist_qid="Q1", title="X")
    archive = [ArchiveEntry(wid="w1", sha256="deadbeef", dhash=0)]
    v = dedup_check(cand, archive)
    assert v.is_duplicate and v.layer == "sha256" and v.matched_wid == "w1"


def test_layer2_phash_near() -> None:
    cand = Candidate(dhash=0b1010)
    archive = [ArchiveEntry(wid="w2", dhash=0b1011)]  # Hamming 1
    v = dedup_check(cand, archive)
    assert v.is_duplicate and v.layer == "phash" and v.distance == 1


def test_layer2_uses_ahash_as_tiebreaker() -> None:
    cand = Candidate(dhash=0b1010, ahash=0b1111)
    archive = [
        ArchiveEntry(wid="worse-ahash", dhash=0b1011, ahash=0b0000),
        ArchiveEntry(wid="better-ahash", dhash=0b1000, ahash=0b1110),
    ]
    v = dedup_check(cand, archive)
    assert v.is_duplicate and v.matched_wid == "better-ahash"
    assert v.detail == "dHam 1 <= 13; aHam 1"


def test_layer4_metadata_same_artist_needs_review() -> None:
    cand = Candidate(dhash=0, artist_qid="Q762", title="Mona Lisa")
    archive = [ArchiveEntry(wid="w3", dhash=_FAR, artist_qid="Q762", title="Mona Lisa")]
    v = dedup_check(cand, archive)
    assert v.status == "needs_review" and v.layer == "metadata" and v.matched_wid == "w3"


def test_unrelated_is_new() -> None:
    cand = Candidate(dhash=0, artist_qid="Q762", title="Mona Lisa")
    archive = [ArchiveEntry(wid="w4", dhash=_FAR, artist_qid="Q999", title="Sunflowers")]
    assert dedup_check(cand, archive).status == "new"


def test_layer5_dino_hook() -> None:
    cand = Candidate(dhash=0, artist_qid="Q762", title="X")
    archive = [ArchiveEntry(wid="w5", dhash=_FAR, artist_qid="Q762", title="Y")]

    def hook(_c: Candidate, block: list[ArchiveEntry]) -> tuple[str, float]:
        return block[0].wid, 0.95

    v = dedup_check(cand, archive, dino_hook=hook)
    assert v.is_duplicate and v.layer == "dinov2" and v.matched_wid == "w5"


def test_load_archive_index(tmp_path: Path) -> None:
    cache = {
        "w1": {"dhash": format(15, "064x"), "ahash": format(0, "064x"), "title": "T"},
        "w2": {"err": "no-master"},  # entries without a dhash are skipped
    }
    p = tmp_path / "archive_phash_cache.json"
    p.write_text(json.dumps(cache))
    idx = load_archive_index(p, artist_qids={"w1": "Q1"})
    assert len(idx) == 1
    assert idx[0].wid == "w1" and idx[0].dhash == 15 and idx[0].artist_qid == "Q1"


def test_acquisition_flow_attaches_dedup_verdict(tmp_path: Path) -> None:
    from fine_art_archive.collect import acquisition_flow as af

    work = tmp_path / "cand-mona"
    work.mkdir()
    master = work / "master.jpg"
    img = Image.new("RGB", (400, 300))
    px = img.load()
    for y in range(300):
        for x in range(400):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    img.save(master, "JPEG", quality=88)
    (work / "meta.json").write_text(
        json.dumps(
            {
                "artist": {"wikidata_q": "Q762"},
                "title": "Mona Lisa",
                "dimensions_original": {"h_cm": 77.0, "w_cm": 53.0},
            }
        )
    )

    dh, ah = perceptual_hashes(master)
    archive = [
        ArchiveEntry(wid="existing-mona", dhash=dh, ahash=ah, artist_qid="Q762", title="Mona Lisa")
    ]

    [res] = af.run_acquisition_flow("met", [work], archive=archive)
    assert res.dedup is not None
    assert res.dedup.is_duplicate and res.dedup.matched_wid == "existing-mona"

    # Without an archive the flow skips the dedup gate.
    [res2] = af.run_acquisition_flow("met", [work])
    assert res2.dedup is None


def test_acquisition_flow_attaches_inventory_match(tmp_path: Path) -> None:
    from fine_art_archive.collect import acquisition_flow as af

    work = tmp_path / "cand-caillebotte"
    work.mkdir()
    master = work / "master.jpg"
    Image.new("RGB", (400, 300)).save(master, "JPEG")
    (work / "meta.json").write_text(
        json.dumps(
            {
                "artist": {"name": "Gustave Caillebotte", "wikidata_q": "Q123"},
                "title": "Paris Street; Rainy Day",
                "dimensions_original": {"h_cm": 212.2, "w_cm": 276.2},
            }
        )
    )
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "\n".join(
            [
                "rel_path,size_bytes,title,artist",
                "Landscape/Paris Street.jpeg,84796647,Paris Street,Gustave Caillebotte",
            ]
        )
    )

    [res] = af.run_acquisition_flow("met", [work], inventory_csv=inventory)

    assert res.inventory_match is not None
    assert res.inventory_match.has_strong_match
    assert res.inventory_match.best is not None
    assert res.inventory_match.best.tier == "exact-artist+near-title"


def test_acquisition_flow_loads_inventory_once_per_batch(tmp_path: Path, monkeypatch) -> None:
    from fine_art_archive.collect import acquisition_flow as af

    work_dirs = []
    for idx in range(2):
        work = tmp_path / f"cand-{idx}"
        work.mkdir()
        Image.new("RGB", (400, 300)).save(work / "master.jpg", "JPEG")
        (work / "meta.json").write_text(
            json.dumps(
                {
                    "artist": {"name": "Gustave Caillebotte"},
                    "title": "Paris Street; Rainy Day",
                    "dimensions_original": {"h_cm": 212.2, "w_cm": 276.2},
                }
            )
        )
        work_dirs.append(work)

    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "\n".join(
            [
                "rel_path,size_bytes,title,artist",
                "Landscape/Paris Street.jpeg,84796647,Paris Street,Gustave Caillebotte",
            ]
        )
    )
    calls = 0
    real_loader = af.load_inventory_rows

    def counting_loader(path: Path):
        nonlocal calls
        calls += 1
        return real_loader(path)

    monkeypatch.setattr(af, "load_inventory_rows", counting_loader)

    results = af.run_acquisition_flow("met", work_dirs, inventory_csv=inventory)

    assert calls == 1
    assert len(results) == 2
    assert all(res.inventory_match and res.inventory_match.has_strong_match for res in results)
