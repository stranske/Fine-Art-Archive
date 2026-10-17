"""Read-only production probes; all archive/card writes stay in a temporary fixture."""

import dataclasses
import hashlib
import importlib.util
import inspect
import json
import platform
import sys
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
spec = importlib.util.spec_from_file_location(
    "feed_fixture", root / "tests/test_eink_feed_endpoints.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
main = fixture.api_main
palette = importlib.import_module("fine_art_archive.eink.palette")
TARGETS, RenderTarget = fixture.TARGETS, fixture.RenderTarget


def source_fingerprint():
    """Hash source and existing tests, including paths, before/after fixture writes."""
    paths = sorted(
        path
        for directory in (root / "src", root / "tests")
        for path in directory.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {"files": len(paths), "sha256": digest.hexdigest()}


def checked_json(response):
    assert response.status_code == 200, response.text
    return response.json()


def pixels(data):
    with Image.open(BytesIO(data)) as image:
        return image.size, image.convert("RGB").tobytes()


before_source = source_fingerprint()
playlist_defaults = dataclasses.asdict(main._eink.PlaylistSpec())
assert len(playlist_defaults) == 17
report = (root / "docs/reports/eink_surface_divergence_audit.md").read_text(encoding="utf-8")
assert all(f"| `{field}` |" in report for field in playlist_defaults)
request_fields = {
    model.__name__: list(model.model_fields)
    for model in (main.PlaylistIn, main.SavePlaylistIn, main.ExportIn)
}
for field in ("quality_scores", "embeddings"):
    assert field in request_fields["PlaylistIn"]
    assert all(field not in request_fields[name] for name in ("SavePlaylistIn", "ExportIn"))
render_defaults = {
    name: inspect.signature(main._eink.render_for_target).parameters[name].default
    for name in ("fit", "method", "compress_range", "fast", "strategy")
}
assert render_defaults == {
    "fit": None,
    "method": "floyd-steinberg",
    "compress_range": True,
    "fast": True,
    "strategy": None,
}
for name in ("fit", "method", "compress_range", "fast"):
    assert inspect.signature(main._eink.export).parameters[name].default == render_defaults[name]
out = {
    "inspected_commit": sys.argv[2],
    "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "python": platform.python_version(),
    "inventory": {
        "playlist_defaults": playlist_defaults,
        "request_fields": request_fields,
        "render_defaults": render_defaults,
    },
    "probes": {},
}
with (
    tempfile.TemporaryDirectory(prefix="faa805-probe-") as scratch,
    pytest.MonkeyPatch.context() as mp,
):
    tmp = Path(scratch)
    archive = fixture.archive.__wrapped__(tmp, mp)
    client = TestClient(main.app)
    diverse = fixture.diverse_archive.__wrapped__(archive, tmp, mp)
    preview = checked_json(client.post("/eink/playlist/preview", json={"spec": diverse}))
    supplied = {
        "quality_scores": dict(
            zip(
                ["aaa1111-red-work", "bbb2222-near-red", "ccc3333-blue-work"],
                [1, 10, 1],
                strict=True,
            )
        ),
        "embeddings": dict(
            zip(
                ["aaa1111-red-work", "bbb2222-near-red", "ccc3333-blue-work"],
                [[1, 0], [1, 0], [0, 1]],
                strict=True,
            )
        ),
    }
    override = checked_json(
        client.post("/eink/playlist/preview", json={"spec": diverse, **supplied})
    )
    saved = fixture._save(client, spec=diverse)
    feed = checked_json(client.get(f"/feed/{saved['id']}/manifest.json"))
    feed_ids = [x["work_id"] for x in feed["items"]]
    out["probes"]["explicit_preview_evidence"] = {
        "derived_preview": preview["work_ids"],
        "explicit_preview": override["work_ids"],
        "saved_feed": feed_ids,
        "derived_matches_saved": preview["work_ids"] == feed_ids,
        "explicit_matches_saved": override["work_ids"] == feed_ids,
    }
    assert preview["work_ids"] == feed_ids
    assert override["work_ids"] != feed_ids

    unsampled = checked_json(
        client.post("/eink/playlist/preview", json={"spec": diverse, "sample": 0})
    )
    assert unsampled["work_ids"] == feed_ids and unsampled["items"] == []
    empty_status = {}
    for field in ("quality_scores", "embeddings"):
        response = client.post("/eink/playlist/preview", json={"spec": diverse, field: {}})
        assert response.status_code == 400, response.text
        empty_status[field] = response.status_code
    out["probes"]["request_only_controls"] = {
        "sample_zero_work_ids": unsampled["work_ids"],
        "sample_zero_items": unsampled["items"],
        "explicit_empty_status": empty_status,
    }

    # Native-size comparisons avoid claiming thumbnail/dither resolution parity.
    native = RenderTarget("audit-native", "Audit native", 40, 20, "spectra6")
    mp.setitem(TARGETS, native.key, native)
    native_saved = fixture._save(client, spec=diverse, target=native.key, dither="none")
    base = f"/feed/{native_saved['id']}"
    navigation = []
    for cursor, expected in [
        (None, feed_ids[0]),
        *zip(feed_ids, feed_ids[1:] + feed_ids[:1]),
        ("unknown-work", feed_ids[0]),
    ]:
        params = {} if cursor is None else {"after": cursor}
        item = checked_json(client.get(f"{base}/next", params=params))
        assert item["work_id"] == expected
        image = client.get(item["image_url"])
        assert image.status_code == 200 and image.headers["X-Work-Id"] == expected
        navigation.append({"after": cursor, "work_id": item["work_id"]})
    invalid_index = client.get(f"{base}/image/{len(feed_ids)}")
    assert invalid_index.status_code == 404
    with pytest.MonkeyPatch.context() as clock_patch:
        real_rotation = main._eink.rotation_index
        clock_patch.setattr(
            main._eink,
            "rotation_index",
            lambda count, interval, *, offset=0: real_rotation(
                count, interval, now=datetime(2026, 10, 17, tzinfo=UTC), offset=offset
            ),
        )
        current = client.get(f"{base}/current")
        offset = client.get(f"{base}/current", params={"offset": 1})
    assert current.status_code == offset.status_code == 200
    assert current.headers["X-Work-Id"] != offset.headers["X-Work-Id"]
    out["probes"]["navigation"] = {
        "cursors": navigation,
        "invalid_index_status": invalid_index.status_code,
        "offset_changes_work": True,
    }
    parity = []
    for mode, request in (
        ("inline", {"spec": diverse, "target": native.key, "dither": "none"}),
        # Invalid inline values must be overridden by the saved query/render settings.
        (
            "saved",
            {
                "playlist_id": native_saved["id"],
                "spec": {"unknown": True},
                "target": "unknown-target",
                "dither": "invalid",
                "fit": "invalid",
            },
        ),
    ):
        card = tmp / f"card-{mode}"
        exported = checked_json(
            client.post("/eink/playlist/export", json={**request, "path": str(card), "write": True})
        )
        assert exported["written"] == len(feed_ids)
        manifest = json.loads((card / "playlist.json").read_text(encoding="utf-8"))
        assert [item["work_id"] for item in manifest["items"]] == feed_ids
        for index, item in enumerate(manifest["items"]):
            image = client.get(f"{base}/image/{index}")
            assert image.status_code == 200
            preview_image = client.get(
                f"/works/{item['work_id']}/eink_preview",
                params={"target": native.key, "dither": "none"},
            )
            assert preview_image.status_code == 200
            written = (card / item["file"]).read_bytes()
            assert pixels(written) == pixels(image.content) == pixels(preview_image.content)
            cached = client.get(
                f"{base}/image/{index}", headers={"If-None-Match": image.headers["ETag"]}
            )
            assert cached.status_code == 304
            explicit_fit = client.get(
                f"/works/{item['work_id']}/eink_preview",
                params={"target": native.key, "dither": "none", "fit": native.fit},
            )
            assert explicit_fit.status_code == 200
            assert pixels(explicit_fit.content) == pixels(preview_image.content)
            parity.append(
                {
                    "export": mode,
                    "work_id": item["work_id"],
                    "size": list(pixels(written)[0]),
                    "pixels_equal": True,
                    "unchanged_validator_status": cached.status_code,
                    "implicit_explicit_fit_equal": True,
                }
            )
    out["probes"]["native_surface_pixels"] = parity

    fixture._work(archive, "palette-probe", title="Palette probe")
    Image.new("RGB", (40, 20), (255, 0, 255)).save(
        archive / "palette-probe/master.jpeg", format="PNG"
    )
    target = RenderTarget("audit-palette", "Audit", 40, 20, "spectra6")
    mp.setitem(TARGETS, target.key, target)
    saved = fixture._save(client, spec={"sort": "title"}, target=target.key, dither="none")
    items = checked_json(client.get(f"/feed/{saved['id']}/manifest.json"))["items"]
    index = next(i for i, item in enumerate(items) if item["work_id"] == "palette-probe")
    url = f"/feed/{saved['id']}/image/{index}"
    before = client.get(url)
    assert before.headers["X-Render-Strategy"] == "grayscale"
    original = palette.PALETTES["spectra6"]
    altered = tuple(
        tuple(min(255, channel + 10) for channel in colour) for colour in original.colours
    )
    mp.setitem(palette.PALETTES, "spectra6", dataclasses.replace(original, colours=altered))
    # Pin strategy to isolate target palette identity from A11 policy changes.
    from fine_art_archive.display.render import RenderEvidence

    mp.setattr(
        main._eink,
        "render_evidence",
        lambda image: RenderEvidence("grayscale", "probe", "poorly-served"),
    )
    unconditional = client.get(url)
    conditional = client.get(url, headers={"If-None-Match": before.headers["ETag"]})
    out["probes"]["same_name_palette_change"] = {
        "before_status": before.status_code,
        "after_status": unconditional.status_code,
        "bytes_changed": before.content != unconditional.content,
        "etag_changed": before.headers["ETag"] != unconditional.headers["ETag"],
        "old_validator_status": conditional.status_code,
        "before_sha256": hashlib.sha256(before.content).hexdigest(),
        "after_sha256": hashlib.sha256(unconditional.content).hexdigest(),
    }
    assert before.status_code == unconditional.status_code == 200
    assert before.content != unconditional.content
    assert before.headers["ETag"] == unconditional.headers["ETag"]
    assert conditional.status_code == 304
    mp.setitem(palette.PALETTES, "spectra6", dataclasses.replace(original, measured=True))
    measured = client.get(url)
    measured_conditional = client.get(url, headers={"If-None-Match": before.headers["ETag"]})
    out["probes"]["measurement_status_change"] = {
        "before": before.headers["X-Palette-Measured"],
        "after": measured.headers["X-Palette-Measured"],
        "etag_changed": before.headers["ETag"] != measured.headers["ETag"],
        "old_validator_status": measured_conditional.status_code,
        "conditional_measurement_header": measured_conditional.headers.get("X-Palette-Measured"),
    }
    assert measured.status_code == 200
    assert before.headers["X-Palette-Measured"] == "False"
    assert measured.headers["X-Palette-Measured"] == "True"
    assert before.headers["ETag"] == measured.headers["ETag"]
    assert measured_conditional.status_code == 304
    assert "X-Palette-Measured" not in measured_conditional.headers
after_source = source_fingerprint()
assert before_source == after_source, "probe changed source or existing tests"
out["source_integrity"] = {"before": before_source, "after": after_source, "byte_identical": True}
print(json.dumps(out, indent=2))
