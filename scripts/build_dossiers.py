#!/usr/bin/env python3
"""Build viewer *dossiers* (summary + key facts + durable source references).

First slice: runs on paintings that already have a holder, discovering the
holder object page (work P973) + the work's and artist's Wikipedia articles,
screening out commerce sources, snapshotting to Wayback + locally, and writing a
schema-valid ``dossier`` block. Dry-run by default; ``--apply`` writes.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from _paths import default_works_dir  # noqa: E402
from _sidecar_io import script_env_path as _env_path  # noqa: E402
from _sidecar_io import sidecar_paths as _sidecar_paths  # noqa: E402

from fine_art_archive import sidecar  # noqa: E402
from fine_art_archive.enrichment import dossier as dossier_mod  # noqa: E402

WD_API = "https://www.wikidata.org/w/api.php"
UA = "Fine-Art-Archive/0.1 (https://github.com/stranske/Fine-Art-Archive)"
DEFAULT_LIMIT = 20
_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
# Wikidata claims surfaced as key facts: (property, human label)
_FACT_PROPS = {"P135": "Movement", "P136": "Genre", "P180": "Depicts", "P186": "Material"}


class HttpFetchClient:
    """Throttled, retrying real client for Wikipedia / Wikidata / Wayback."""

    def __init__(self, *, timeout: float = 20.0, throttle: float = 0.25) -> None:
        self.timeout = timeout
        self.throttle = throttle
        self._last = 0.0
        self._label_cache: dict[str, str] = {}

    def _wait(self) -> None:
        gap = self.throttle - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()

    def _get(self, url: str, *, accept: str = "application/json") -> bytes | None:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
        for attempt in range(3):
            self._wait()
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body: bytes = r.read()
                    return body
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 2:
                    time.sleep(min(2.0**attempt, 10))
                    continue
                return None
            except (urllib.error.URLError, TimeoutError, OSError):
                return None
        return None

    def _json(self, url: str) -> dict[str, Any] | None:
        raw = self._get(url)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def wiki_title_for_qid(self, qid: str, wiki: str = "enwiki") -> str | None:
        params = {"action": "wbgetentities", "ids": qid, "props": "sitelinks", "format": "json"}
        data = self._json(f"{WD_API}?{urllib.parse.urlencode(params)}")
        try:
            title = data["entities"][qid]["sitelinks"][wiki]["title"]  # type: ignore[index]
        except (KeyError, TypeError):
            return None
        return title if isinstance(title, str) else None

    def wiki_summary(self, title: str, lang: str = "en") -> dict[str, Any] | None:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title, safe='')}"
        data = self._json(url)
        if not data or data.get("type") == "disambiguation":
            return None
        return {
            "title": data.get("title"),
            "extract": data.get("extract"),
            "content_url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
        }

    def _labels(self, qids: list[str]) -> dict[str, str]:
        need = [q for q in qids if q not in self._label_cache]
        for i in range(0, len(need), 50):
            batch = need[i : i + 50]
            params = {
                "action": "wbgetentities",
                "ids": "|".join(batch),
                "props": "labels",
                "languages": "en",
                "format": "json",
            }
            data = self._json(f"{WD_API}?{urllib.parse.urlencode(params)}") or {}
            for q, ent in (data.get("entities") or {}).items():
                lbl = ((ent.get("labels") or {}).get("en") or {}).get("value")
                if lbl:
                    self._label_cache[q] = lbl
        return {q: self._label_cache.get(q, q) for q in qids}

    def wikidata_facts(self, qid: str) -> list[dict[str, str]]:
        params = {"action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"}
        data = self._json(f"{WD_API}?{urllib.parse.urlencode(params)}")
        try:
            claims = data["entities"][qid]["claims"]  # type: ignore[index]
        except (KeyError, TypeError):
            return []
        facts: list[dict[str, str]] = []
        # P973 described-at URL
        for c in claims.get("P973", []) or []:
            with contextlib.suppress(KeyError, TypeError):
                facts.append({"prop": "P973", "text": c["mainsnak"]["datavalue"]["value"]})
        # entity-valued facts -> resolve labels
        qids_needed: list[str] = []
        pending: list[tuple[str, str]] = []
        for prop in _FACT_PROPS:
            for c in claims.get(prop, []) or []:
                try:
                    q = c["mainsnak"]["datavalue"]["value"]["id"]
                    pending.append((prop, q))
                    qids_needed.append(q)
                except (KeyError, TypeError):
                    pass
        labels = self._labels(qids_needed)
        seen = set()
        for prop, q in pending:
            key = (prop, q)
            if key in seen:
                continue
            seen.add(key)
            facts.append({"prop": prop, "text": f"{_FACT_PROPS[prop]}: {labels.get(q, q)}."})
        return facts

    def fetch(self, url: str) -> dict[str, Any] | None:
        raw = self._get(url, accept="text/html")
        if raw is None:
            return None
        html = raw.decode("utf-8", errors="ignore")
        text = _TAGS.sub(" ", _TAG.sub(" ", html))
        text = re.sub(r"\s+", " ", text).strip()
        return {"status": "live", "text": text[:6000]}

    def wayback_save(self, url: str) -> str | None:
        # prefer an existing snapshot (fast, read-only); else best-effort save
        avail = self._json(
            f"https://archive.org/wayback/available?{urllib.parse.urlencode({'url': url})}"
        )
        snap = ((avail or {}).get("archived_snapshots") or {}).get("closest") or {}
        existing = snap.get("url")
        if snap.get("available") and isinstance(existing, str):
            return existing
        self._get(f"https://web.archive.org/save/{url}", accept="text/html")
        avail = self._json(
            f"https://archive.org/wayback/available?{urllib.parse.urlencode({'url': url})}"
        )
        snap = ((avail or {}).get("archived_snapshots") or {}).get("closest") or {}
        url_out = snap.get("url")
        return url_out if snap.get("available") and isinstance(url_out, str) else None


def _needs_dossier(meta: dict[str, Any]) -> bool:
    return not (meta.get("dossier") or {}).get("viewer_summary")


def _in_slice(meta: dict[str, Any]) -> bool:
    holder = meta.get("holder") or {}
    artist = meta.get("artist") or {}
    stable = meta.get("stable_identifiers") or {}
    return (
        meta.get("category") == "painting"
        and bool(holder.get("name"))
        and (bool(artist.get("wikidata_q")) or bool(stable.get("wikidata_q")))
    )


def _write_snapshots(meta_dir: Path, work_id: str, doss: dossier_mod.Dossier) -> None:
    for ref in doss.references:
        if ref.snapshot_text:
            fname = f"snapshot_{re.sub(r'[^a-z0-9]+', '_', ref.id.lower())}.txt"
            (meta_dir / fname).write_text(ref.snapshot_text, encoding="utf-8")
            ref.local_snapshot_path = fname


def build(
    staging_dir: Path, *, client: Any, limit: int, apply: bool, art_works_root: Path | None = None
) -> dict[str, Any]:
    retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    attempted = built = 0
    samples: list[dict[str, Any]] = []
    for path in _sidecar_paths(staging_dir):
        if attempted >= limit:
            break
        meta = sidecar.load(path)
        if not _in_slice(meta) or not _needs_dossier(meta):
            continue
        attempted += 1
        doss = dossier_mod.build_dossier(meta, client=client, retrieved_at=retrieved_at)
        if not doss.viewer_summary and not doss.references:
            continue
        built += 1
        if apply:
            _write_snapshots(path.parent, str(meta["work_id"]), doss)
            meta["dossier"] = doss.to_json()
            sidecar.validate(meta)
            sidecar.write(path, meta)
            if art_works_root is not None:
                for base in (art_works_root / "works", art_works_root):
                    mp = base / str(meta["work_id"]) / "meta.json"
                    if mp.is_file():
                        sidecar.write(mp, meta)
        if len(samples) < 6:
            samples.append(
                {
                    "work_id": meta["work_id"],
                    "title": meta.get("title"),
                    "summary": (doss.viewer_summary or "")[:160],
                    "refs": [
                        (r.kind, r.live_url, r.authority_score, r.wayback_url is not None)
                        for r in doss.references
                    ],
                    "facts": [f["text"] for f in doss.key_facts],
                }
            )
    return {"attempted": attempted, "built": built, "samples": samples}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=default_works_dir(),
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--apply", action="store_true", help="write dossiers (default: dry-run)")
    args = parser.parse_args(argv)

    result = build(
        args.staging_dir,
        client=HttpFetchClient(),
        limit=args.limit,
        apply=args.apply,
        art_works_root=args.art_works_root,
    )
    mode = "apply" if args.apply else "dry-run"
    print(f"dossier build ({mode}): attempted={result['attempted']} built={result['built']}")
    for s in result["samples"]:
        print(f"\n=== {s['title']} ({s['work_id']}) ===")
        print(f"  summary: {s['summary']}...")
        print(f"  facts: {s['facts']}")
        for kind, url, score, wb in s["refs"]:
            print(f"  ref[{score}] {kind}: {url}  wayback={wb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
