#!/usr/bin/env python3
"""Merge the three e-paper research streams into config/eink_targets.json.

The survey was gathered by three researchers working in parallel on different
angles -- shipping hardware, upcoming/open-hardware routes, and vendor
financial viability -- so the same device is often described by two of them
with different depth. This merges them deterministically.

Raw stream output is kept in docs/research/eink/ so the merge is reproducible
and every claim stays traceable to the researcher that made it. Run:

    python3 scripts/merge_eink_survey.py

Merge rules
-----------
* Devices are keyed by (vendor, model) after normalisation, so
  "BOOX Mira Pro (Color Version) 25.3"" and "BOOX Mira Pro Color 25.3in"
  collapse to one record.
* On a field collision the LONGER value wins. The streams differ mainly in how
  much they wrote, not in what they claim, and the longer answer is the one
  carrying the caveats -- which is what matters for a buying decision.
* `sources` lists are unioned by url. `integration.openness` takes the most
  RESTRICTIVE value across streams, because an openness claim is only as good
  as its least favourable finding: stream A found that DASUNG needs a USB
  heartbeat to hold an image and that Visionect enforces a per-device licence
  on the customer's own server, both of which downgrade an "open" rating that
  another stream had given in good faith.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "docs" / "research" / "eink"
OUT = ROOT / "config" / "eink_targets.json"

STREAMS = [
    ("shipping", RESEARCH / "stream-a-shipping.json"),
    ("upcoming-openhw", RESEARCH / "stream-b-upcoming-openhw.json"),
    ("vendor-viability", RESEARCH / "stream-c-vendor-viability.json"),
]

# Most restrictive first.
OPENNESS_ORDER = ["closed", "partly-open", "open", "unknown"]


def norm(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r'["“”″]|inch(es)?|\bin\b', "", s)
    s = re.sub(r"\((colour|color)\s*version\)", "", s)
    s = re.sub(r"[^a-z0-9.]+", "", s)
    return s


def dev_key(d: dict) -> str:
    return f"{norm(d.get('vendor'))}|{norm(d.get('model'))}"


def merge_sources(a: list, b: list) -> list:
    seen, out = set(), []
    for s in (a or []) + (b or []):
        u = s.get("url") if isinstance(s, dict) else None
        k = u or json.dumps(s, sort_keys=True)
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def restrictive_openness(a: str | None, b: str | None) -> str | None:
    vals = [v for v in (a, b) if v]
    if not vals:
        return None
    return min(vals, key=lambda v: OPENNESS_ORDER.index(v)
               if v in OPENNESS_ORDER else 99)


def deep_merge(cur: dict, new: dict, stream: str) -> dict:
    for k, v in new.items():
        if k == "sources":
            cur[k] = merge_sources(cur.get(k), v)
        elif k == "integration" and isinstance(v, dict) and isinstance(
                cur.get(k), dict):
            o = restrictive_openness(cur[k].get("openness"), v.get("openness"))
            cur[k] = deep_merge(cur[k], v, stream)
            if o:
                cur[k]["openness"] = o
        elif isinstance(v, dict) and isinstance(cur.get(k), dict):
            cur[k] = deep_merge(cur[k], v, stream)
        elif k not in cur or cur[k] in (None, "", [], {}):
            cur[k] = v
        elif isinstance(v, str) and isinstance(cur[k], str) and \
                len(v) > len(cur[k]):
            cur[k] = v
    cur.setdefault("_streams", [])
    if stream not in cur["_streams"]:
        cur["_streams"].append(stream)
    return cur


def main() -> int:
    devices: dict[str, dict] = {}
    vendors: dict[str, dict] = {}
    leads: list = []
    unverified: list = []
    counts = {}

    for stream, path in STREAMS:
        if not path.exists():
            print(f"MISSING {path}")
            continue
        d = json.loads(path.read_text())
        counts[stream] = {"devices": len(d.get("devices") or []),
                          "vendors": len(d.get("vendors") or [])}
        for dev in d.get("devices") or []:
            k = dev_key(dev)
            devices[k] = deep_merge(devices.get(k, {}), dev, stream) \
                if k in devices else deep_merge(dict(dev), {}, stream)
        for v in d.get("vendors") or []:
            k = norm(v.get("name"))
            vendors[k] = deep_merge(vendors.get(k, {}), v, stream) \
                if k in vendors else deep_merge(dict(v), {}, stream)
        for lead in d.get("leads_not_followed") or []:
            leads.append({"_stream": stream, **lead} if isinstance(lead, dict)
                         else {"_stream": stream, "lead": lead})
        for u in d.get("unverified_facts") or []:
            unverified.append({"_stream": stream, **u} if isinstance(u, dict)
                              else {"_stream": stream, "fact": u})

    dev_list = sorted(devices.values(),
                      key=lambda x: -(x.get("diagonal_in") or 0))
    out = {
        "_schema": "faa-eink-targets/1",
        "_purpose": "Development target for the archive's E-Ink display push. "
                    "Ranked on vendor staying power and integration openness, "
                    "not on spec sheets.",
        "_scope": "Reflective e-paper with viewing area >15in diagonal, "
                  "shipping or announced. LCD art frames excluded.",
        "_streams": counts,
        "_merge": "scripts/merge_eink_survey.py from docs/research/eink/*.json",
        "devices": dev_list,
        "vendors": sorted(vendors.values(), key=lambda x: x.get("name") or ""),
        "leads_not_followed": leads,
        "unverified_facts": unverified,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))

    big = [d for d in dev_list if (d.get("diagonal_in") or 0) > 15]
    print(f"streams: {counts}")
    print(f"merged : {len(dev_list)} devices ({len(big)} above 15in), "
          f"{len(vendors)} vendors, {len(leads)} leads, "
          f"{len(unverified)} unverified facts")
    print(f"wrote  : {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
