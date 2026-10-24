"""Master-image HTTP responses must preserve rendering, cache and failure semantics."""

from __future__ import annotations

import ast
import builtins
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store


@pytest.fixture
def image_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    works = tmp_path / "works"
    work = works / "sample-work"
    work.mkdir(parents=True)
    cache = tmp_path / "cache"
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "IMAGE_CACHE_DIR", cache)
    monkeypatch.setattr(store, "WORKS", works)
    return {"works": works, "work": work, "cache": cache}


def test_transparent_master_is_a_bounded_jpeg(image_files: dict[str, Path]) -> None:
    master = image_files["work"] / "master.png"
    Image.new("RGBA", (128, 64), (220, 40, 20, 128)).save(master)
    original = master.read_bytes()

    with TestClient(api_main.app) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=86400"
    with Image.open(io.BytesIO(response.content)) as rendered:
        assert rendered.format == "JPEG"
        assert rendered.mode == "RGB"
        assert rendered.size == (64, 32)
        red, green, blue = rendered.getpixel((32, 16))
        assert red > green > blue
    assert master.read_bytes() == original


def test_cached_master_response_does_not_decode_again(
    image_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    master = image_files["work"] / "master.png"
    Image.new("RGB", (96, 48), "red").save(master)
    with TestClient(api_main.app) as client:
        first = client.get("/works/sample-work/image?max=64")
        assert first.status_code == 200
        cached = next(image_files["cache"].glob("*.jpg"))
        before = (cached.stat().st_mtime_ns, cached.read_bytes())

        def unexpected_decode(*args, **kwargs):
            pytest.fail("unchanged master cache hit decoded the source again")

        monkeypatch.setattr(Image, "open", unexpected_decode)
        second = client.get("/works/sample-work/image?max=64")

    assert second.status_code == 200
    assert second.content == first.content
    assert (cached.stat().st_mtime_ns, cached.read_bytes()) == before
    assert len(list(image_files["cache"].iterdir())) == 1


def test_missing_master_is_404_without_creating_cache(image_files: dict[str, Path]) -> None:
    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 404
    assert response.json() == {"detail": "no master image for sample-work"}
    assert not image_files["cache"].exists()


def test_corrupt_master_reports_resize_failure_without_cached_output(
    image_files: dict[str, Path],
) -> None:
    master = image_files["work"] / "master.png"
    master.write_bytes(b"not an image")
    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 500
    assert response.json()["detail"].startswith("resize failed:")
    assert list(image_files["cache"].iterdir()) == []
    assert master.read_bytes() == b"not an image"


def test_unavailable_pillow_reports_specific_failure(
    image_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    Image.new("RGB", (96, 48), "red").save(image_files["work"] / "master.png")
    original_import = builtins.__import__

    def without_pillow(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL" and "Image" in (fromlist or ()):
            raise ImportError("test dependency outage")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", without_pillow)
    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 500
    assert response.json() == {"detail": "Pillow not installed"}
    assert list(image_files["cache"].iterdir()) == []


def test_sidecar_master_filename_fallback_is_served(image_files: dict[str, Path]) -> None:
    work = image_files["work"]
    Image.new("RGB", (96, 48), "blue").save(work / "scan.png")
    (work / "meta.json").write_text(
        json.dumps({"work_id": "sample-work", "files": {"master": {"filename": "scan.png"}}}),
        encoding="utf-8",
    )

    with TestClient(api_main.app) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 200, response.text
    with Image.open(io.BytesIO(response.content)) as rendered:
        assert rendered.size == (64, 32)
        red, _, blue = rendered.getpixel((32, 16))
        assert blue > red


def test_is_master_image_accepts_pictures_and_rejects_sidecars() -> None:
    """An XMP sidecar starts with "master." too, so the prefix cannot decide."""
    from fine_art_archive.sidecar import is_master_image

    for name in (
        "master.jpeg",
        "master.jpg",
        "master.png",
        "master.tif",
        "master.tiff",
        "master.webp",
        "master.JPG",  # the lowercasing path, which no accepted name exercised
    ):
        assert is_master_image(name), name
    # digiKam writes "master.jpeg.xmp"; its compact naming writes "master.xmp"
    for name in ("master.jpeg.xmp", "master.xmp", "master.JPEG.XMP", "master.json"):
        assert not is_master_image(name), name
    assert not is_master_image("variant-landscape-crop.jpeg")


def test_a_sidecar_beside_the_master_is_not_served_as_the_image(
    image_files: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The picture is served even when an XMP sidecar shares its "master." prefix.

    Without the extension check the directory scan returns "master.png.xmp" -- it
    matched the prefix and nothing downstream re-checked the suffix -- and the API
    tries to render an XML file as a picture.
    """
    master = image_files["work"] / "master.png"
    Image.new("RGB", (64, 32), (10, 120, 200)).save(master)
    sidecar_file = image_files["work"] / "master.png.xmp"
    sidecar_file.write_text(
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta '
        'xmlns:x="adobe:ns:meta/"/><?xpacket end="w"?>',
        encoding="utf-8",
    )

    # Directory order decides which file the scan reaches first, and it is not
    # guaranteed: with the guard removed this test still passed on one run because
    # the picture happened to come first. Force the adversarial order so the test
    # fails whenever the extension check is dropped, on any filesystem.
    real_iterdir = Path.iterdir

    def sidecars_first(self: Path):
        return iter(sorted(real_iterdir(self), key=lambda p: (p.suffix != ".xmp", p.name)))

    monkeypatch.setattr(Path, "iterdir", sidecars_first)

    assert api_main._master_path("sample-work") == master

    with TestClient(api_main.app) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(response.content)) as rendered:
        assert rendered.format == "JPEG"


@pytest.mark.parametrize("extension", ["jpeg", "JPEG"])
def test_eink_master_rejects_xmp_only_directory(
    image_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch, extension: str
) -> None:
    """XMP-only dirs have no master; with a JPEG present, the glob must skip sidecars.

    The preferred exact-name loop is forced closed so both cases exercise the
    `master.*` glob + `is_master_image` path. Sidecars are ordered first so a
    missing guard cannot pass by lucky filename order.
    """
    work = image_files["work"]
    (work / "master.xmp").write_text("<x:xmpmeta/>", encoding="utf-8")
    assert api_main._eink_master("sample-work") is None

    master = work / f"master.{extension}"
    Image.new("RGB", (64, 32), "blue").save(master, format="JPEG")
    (work / f"master.{extension}.xmp").write_text("<x:xmpmeta/>", encoding="utf-8")

    # Skip the lowercase preferred loop so selection goes through glob fallback.
    preferred_exact = {
        work / f"master.{ext}" for ext in ("jpeg", "jpg", "png", "tif", "tiff", "webp")
    }
    real_exists = Path.exists

    def preferred_candidate_exists(path: Path) -> bool:
        if path in preferred_exact:
            return False
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", preferred_candidate_exists)

    # Put sidecars first even after sorting so filename order cannot hide a bug.
    def sidecars_first(paths):
        return sorted(paths, key=lambda path: (path.suffix.lower() != ".xmp", path.name))

    monkeypatch.setattr(api_main, "sorted", sidecars_first, raising=False)
    assert api_main._eink_master("sample-work") == master


def test_no_caller_locates_the_master_by_prefix_alone() -> None:
    """The prefix test lives in is_master_image and nowhere else.

    This is the break-test for the rule: reintroducing `startswith("master.")` at a
    call site reopens the bug silently, because a work directory without a sidecar
    still behaves correctly and nothing else notices.
    """
    repo = Path(__file__).resolve().parents[1]
    allowed = {repo / "src" / "fine_art_archive" / "sidecar.py"}
    offenders: list[str] = []
    unparsed: list[str] = []
    for path in sorted([*(repo / "src").rglob("*.py"), *(repo / "scripts").rglob("*.py")]):
        if path in allowed:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - a parse failure is reported, not skipped
            unparsed.append(f"{path.relative_to(repo)}: {exc}")
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "startswith"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("master.")
            ):
                offenders.append(f"{path.relative_to(repo)}:{node.lineno}")

    # A file the scan could not read has not been checked. Letting that pass would
    # make the guard report "clean" for a reason that has nothing to do with the code.
    assert not unparsed, f"scan did not cover: {unparsed}"
    assert not offenders, (
        "locate the master with fine_art_archive.sidecar.is_master_image(); "
        f"prefix-only checks found at: {offenders}"
    )
