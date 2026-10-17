"""Read-only production probes; all archive/card writes stay in a temporary fixture."""

import dataclasses
import hashlib
import importlib.util
import json
import sys
import tempfile
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

out = {"inspected_commit": sys.argv[2], "probes": {}}
with (
    tempfile.TemporaryDirectory(prefix="faa805-probe-") as scratch,
    pytest.MonkeyPatch.context() as mp,
):
    tmp = Path(scratch)
    archive = fixture.archive.__wrapped__(tmp, mp)
    client = TestClient(main.app)
    diverse = fixture.diverse_archive.__wrapped__(archive, tmp, mp)
    preview = client.post("/eink/playlist/preview", json={"spec": diverse}).json()
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
    override = client.post("/eink/playlist/preview", json={"spec": diverse, **supplied}).json()
    saved = fixture._save(client, spec=diverse)
    feed = client.get(f"/feed/{saved['id']}/manifest.json").json()
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

    fixture._work(archive, "palette-probe", title="Palette probe")
    Image.new("RGB", (40, 20), (255, 0, 255)).save(
        archive / "palette-probe/master.jpeg", format="PNG"
    )
    target = RenderTarget("audit-palette", "Audit", 40, 20, "spectra6")
    mp.setitem(TARGETS, target.key, target)
    saved = fixture._save(client, spec={"sort": "title"}, target=target.key, dither="none")
    items = client.get(f"/feed/{saved['id']}/manifest.json").json()["items"]
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
print(json.dumps(out, indent=2))
