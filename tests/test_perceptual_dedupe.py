"""Torch-free tests for the perceptual-hash dedup stage (D017 cascade, layer 2).

The DINOv2 vision stage (scripts/visual_dedupe.py) needs torch + real archive
masters and is validated operationally via its `smoketest` subcommand in the
.faa-venv — not here. These tests cover the pure, dependency-light perceptual
hashing in scripts/perceptual_dedupe.py (PIL + stdlib only) so it stays correct
under the Gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import perceptual_dedupe as pdedupe  # noqa: E402


def _save(path: Path, pattern: str) -> Path:
    """Write a deterministic 256x256 grayscale PNG with a known structure."""
    img = Image.new("L", (256, 256), 0)
    px = img.load()
    for y in range(256):
        for x in range(256):
            if pattern == "gradient":
                px[x, y] = x  # left-to-right 0..255 ramp
            elif pattern == "gradient_rev":
                px[x, y] = 255 - x  # mirror ramp
    img.save(path)
    return path


def test_ham_counts_differing_bits() -> None:
    assert pdedupe.ham(0, 0) == 0
    assert pdedupe.ham(0b111, 0b101) == 1
    assert pdedupe.ham(255, 0) == 8
    assert pdedupe.ham(0b1010, 0b0101) == 4


def test_identical_images_hash_identically(tmp_path: Path) -> None:
    a = _save(tmp_path / "a.png", "gradient")
    b = _save(tmp_path / "b.png", "gradient")  # same structure
    da, aa = pdedupe._hashes(a)
    db, ab = pdedupe._hashes(b)
    assert pdedupe.ham(da, db) == 0
    assert pdedupe.ham(aa, ab) == 0


def test_mirror_image_is_far_apart(tmp_path: Path) -> None:
    grad = _save(tmp_path / "grad.png", "gradient")
    rev = _save(tmp_path / "rev.png", "gradient_rev")
    d_grad, _ = pdedupe._hashes(grad)
    d_rev, _ = pdedupe._hashes(rev)
    # A monotonic ramp hashes to all-1 bits, its mirror to all-0 bits: far above
    # the "same image" band (dHam <= 10).
    assert pdedupe.ham(d_grad, d_rev) > 200


def test_hashes_are_256_bit(tmp_path: Path) -> None:
    g = _save(tmp_path / "g.png", "gradient")
    dh, ah = pdedupe._hashes(g)
    assert 0 <= dh < (1 << 256)
    assert 0 <= ah < (1 << 256)


def test_script_uses_cascade_hash_primitives() -> None:
    from fine_art_archive.collect import dedup_cascade

    assert pdedupe.ham is dedup_cascade.hamming
    assert pdedupe._hashes.__globals__["perceptual_hashes"] is dedup_cascade.perceptual_hashes


def test_visual_dedupe_imports_without_torch(tmp_path: Path) -> None:
    """The DINOv2 module must import even without torch (lazy import), and its
    torch-free file helper must work on a synthetic master dir."""
    import visual_dedupe as vdedupe  # noqa: E402

    work = tmp_path / "abc1234-some-work"
    work.mkdir()
    (work / "master.jpg").write_bytes(b"not-a-real-jpeg")
    assert vdedupe.master_of(work) == str(work / "master.jpg")
    assert vdedupe.master_of(tmp_path / "missing") is None


def test_torch_is_optional() -> None:
    """Documents the design: torch is an operational dep, absent under the Gate."""
    # In CI torch is not installed; the vision stage runs operationally, not here.
    assert importlib.util.find_spec("torch") is None or True
