"""Capture real health responses around a real manifest rebuild on temporary data."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from fine_art_archive.api import main, store

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    works = root / "works"
    works.mkdir()
    for work_id in ["work-a", "work-b", "work-c"]:
        work = works / work_id
        work.mkdir()
        (work / "meta.json").write_text(json.dumps({"work_id": work_id, "title": work_id}))
    manifest = root / "manifest.csv"
    with manifest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["work_id", "title"])
        writer.writeheader()
        writer.writerows(
            {"work_id": value, "title": value} for value in ["work-a", "retired", "work-c"]
        )
    store.WORKS = works
    store.MANIFEST_CSV = manifest
    store.RATINGS_LOG = root / "ratings.jsonl"
    main.ART_WORKS_ROOT = works
    main.QUEUES_DIR = root / "queues"
    store.invalidate_manifest_cache()
    store.invalidate_ratings_cache()
    client = TestClient(main.app)
    before_response = client.get("/healthz")
    before = before_response.json()
    assert before_response.status_code == 200 and before["ok"] is False
    assert before["manifest_drift"] == 0
    assert before["manifest_missing"] == ["work-b"] and before["manifest_extra"] == ["retired"]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_manifest.py",
            "--works-root",
            str(works),
            "--out",
            str(manifest),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    after_response = client.get("/healthz")
    after = after_response.json()
    assert after_response.status_code == 200 and after["ok"] is True
    assert after["manifest_missing"] == after["manifest_extra"] == []
    fields = [
        "ok",
        "manifest_loaded",
        "sidecar_works",
        "manifest_drift",
        "manifest_missing",
        "manifest_extra",
        "manifest_missing_count",
        "manifest_extra_count",
    ]
    print(
        json.dumps(
            {
                "before": {field: before[field] for field in fields},
                "after": {field: after[field] for field in fields},
                "http_statuses": [before_response.status_code, after_response.status_code],
                "builder_exit": result.returncode,
            },
            indent=2,
        )
    )
