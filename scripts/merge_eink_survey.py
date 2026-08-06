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
    ("art-frames", RESEARCH / "stream-d-art-frames.json"),
]

# Round-2 streams that are not device/vendor shaped. They answer one question
# each rather than cataloguing hardware, so they ride alongside the device list
# instead of being merged into it.
SIDECAR_STREAMS = [
    ("delivery_record", RESEARCH / "stream-e-delivery-record.json"),
    ("panel_supply", RESEARCH / "stream-f-panel-supply.json"),
]

# Facts a later stream established that an earlier one got wrong. The merge
# rules cannot express this on their own: for a non-string field the first
# non-empty value wins, and for a string the LONGEST wins, so a wrong number or
# a wordier wrong sentence would outrank a researched correction. Each entry
# says who corrected what and why, so the override stays auditable.
CORRECTIONS: list[dict] = [
    {
        "match_brand": "ionnyk",
        # Scoped to the WRONG value only. A brand-wide match clobbered Jane
        # (13.2in) and Linn (31.2in), which were already correct -- a
        # correction must not become its own error.
        "only_if": {"diagonal_in": 62},
        "set": {"diagonal_in": 40.2},
        "why": "IONNYK publishes FRAME dimensions, not screen sizes. The 62in "
               "figure in round 1 is Maxine's frame diagonal; its display is "
               "~40.2in (Jane is 13.2in, Linn ~31.2in). Corrected by the "
               "art-frames stream, which read IONNYK's own spec pages.",
        "by": "art-frames",
    },
]


def apply_corrections(devices: dict) -> list[str]:
    applied = []
    for c in CORRECTIONS:
        for dev in devices.values():
            if brand_of(dev) != c["match_brand"]:
                continue
            guard = c.get("only_if") or {}
            if any(dev.get(gk) != gv for gk, gv in guard.items()):
                continue
            for k, v in c["set"].items():
                if dev.get(k) != v:
                    dev.setdefault("_corrections", []).append(
                        {"field": k, "was": dev.get(k), "now": v,
                         "why": c["why"], "by": c["by"]})
                    dev[k] = v
                    applied.append(f"{c['match_brand']}.{k}: {dev['_corrections'][-1]['was']} -> {v}")
    return applied

# Most restrictive first.
OPENNESS_ORDER = ["closed", "partly-open", "open", "unknown"]


# Product brands, most specific first. Three researchers wrote the same vendor
# three different ways -- "PocketBook International S.A.", "InkPoster (brand of
# PocketBook)", "InkPoster (Pocketbook International)" -- so keying on the raw
# vendor string counted one product as three. That inflated the corpus to 48
# devices above 15in; the corrected distinct count is 36.
#
# The canonical key is the PRODUCT brand, not the parent company: PocketBook
# owns InkPoster and IONNYK, but an InkPoster Tela and an IONNYK Jane are
# different devices. Ownership belongs in the vendor record, not in the key.
BRAND_CANON: list[tuple[str, tuple[str, ...]]] = [
    ("inkposter", ("inkposter",)),
    ("ionnyk", ("ionnyk",)),
    ("bigme", ("bigme", "xinruizhi")),
    ("boox", ("boox", "onyx")),
    ("dasung", ("dasung",)),
    ("good-display", ("good display", "dalian good", "gdep", "gdes", "dmph")),
    ("visionect", ("visionect",)),
    ("philips-tableaux", ("tableaux", "ppds", "tp vision", "tpvision", "mmd")),
    ("samsung", ("samsung",)),
    # MEiNK and BLOOMIN8's "EinkCanvas" both CONTAIN the substring "eink", so
    # these must be tested before the generic E Ink entry, and matching must be
    # word-bounded. Substring matching alone filed both under E Ink Holdings.
    ("meink", ("meink",)),
    ("bloomin8", ("bloomin8", "arpobot", "einkcanvas")),
    ("eink", ("e ink", "e-ink", "eink")),
    ("fraimic", ("fraimic",)),
    ("switchbot", ("switchbot", "woan")),
    ("geniatech", ("geniatech",)),
    ("seekink", ("seekink", "xingtai")),
    ("epaint", ("epaint", "anhui yutu", "e-chroma", "e-polar")),
    ("digital-view", ("digital view",)),
    ("papercast", ("papercast",)),
    ("modos", ("modos",)),
    ("pocketbook", ("pocketbook",)),   # parent, only if no product brand hit
]

# Words that carry no identity: they appear in some spellings of a model and
# not others, so leaving them in splits one product into several.
_MODEL_NOISE = re.compile(
    r"\b(e[\s-]?ink|e[\s-]?paper|epaper|display|module|monitor|signage|"
    r"panel|finished|version|series|the|and|with|inch(es)?|in|"
    r"colou?r|monochrome|mono|greyscale|grayscale)\b")


def _fallback_vendor_key(name: str) -> str:
    """Normalize an unrecognized vendor without shortening its identity."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def vendor_key(v: dict) -> str:
    """Vendors collapse on the same brand table, so the three spellings of
    PocketBook become one record instead of three."""
    b = brand_of({"vendor": v.get("name") or "", "model": ""})
    return b or _fallback_vendor_key(v.get("name") or "")


def _hit(hay: str, token: str) -> bool:
    # Word-bounded: "eink" must not match inside "meink" or "einkcanvas".
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", hay) is not None


def brand_of(dev: dict) -> str:
    """Most specific brand wins, scanning vendor and model together.

    Field order cannot decide this: the vendor "PocketBook International S.A."
    only reveals the parent, and it is the MODEL that says "InkPoster Tela".
    So brand priority does the work, and word-bounded matching is what keeps
    "MEiNK"/"EinkCanvas" from matching the generic "eink" token.
    """
    hay = f"{dev.get('vendor') or ''} {dev.get('model') or ''}".lower()
    for canon, tokens in BRAND_CANON:
        if any(_hit(hay, t) for t in tokens):
            return canon
    return _fallback_vendor_key(dev.get("vendor") or "")


def colour_class(dev: dict) -> str:
    """Distinguishes SKUs that share a brand, model name and size.

    Onyx ships "Mira Pro (Color Version) 25.3in" and "Mira Pro (monochrome)
    25.3in" -- genuinely different products. Stripping the colour qualifier out
    of the model name, as the first version of this did, collapsed them.
    """
    hay = f"{dev.get('panel') or ''} {dev.get('colour') or ''} {dev.get('model') or ''}".lower()
    if "spectra 6" in hay or "spectra6" in hay or "(e6)" in hay:
        return "spectra6"
    if "kaleido" in hay:
        return "kaleido"
    if "gallery" in hay:
        return "gallery"
    if "acep" in hay:
        return "acep"
    if any(w in hay for w in ("monochrome", "mono ", "greyscale", "grayscale")):
        return "mono"
    return "colour?" if "colour" in hay or "color" in hay else "unknown"


def model_core(dev: dict) -> str:
    m = (dev.get("model") or "").lower()
    for _, tokens in BRAND_CANON:            # drop the brand from the model
        for t in tokens:
            m = m.replace(t, " ")
    m = re.sub(r"\(.*?\)", " ", m)            # parentheticals are commentary
    # Strip sizes in every spelling that appears: 40.5" / 40.5 inch / bare 40.5
    # / the run-together 405 and 253 left behind by earlier passes. Without the
    # bare form, "Tela 40.5" and "Tela 40.5in" produced different cores.
    m = re.sub(r"\d+(\.\d+)?\s*[\"“”″]|\d+(\.\d+)?\s*inch(es)?\b", " ", m)
    m = re.sub(r"(?<![a-z])\d{2,3}\.\d(?![0-9])", " ", m)
    m = re.sub(r"(?<![a-z0-9])(253|285|315|312|405|320|750|75|32|28|25)(?![0-9])", " ", m)
    m = _MODEL_NOISE.sub(" ", m)
    m = re.sub(r"[^a-z0-9]+", "", m)
    return m


def dev_key(d: dict) -> str:
    try:
        dia = round(float(d.get("diagonal_in") or 0), 1)
    except (TypeError, ValueError):
        dia = 0.0
    return f"{brand_of(d)}|{model_core(d)}|{dia}|{colour_class(d)}"


# Markers that make two otherwise-similar records genuinely different products.
# Without this guard the containment rule below would swallow Visionect's $6,000
# Development Kit into its $2,300 retail unit, and Good Display's bare panel
# into its finished display.
DISTINCT_MARKERS = ("kit", "bare", "devkit", "evaluation", "reference")


def same_product(a: dict, b: dict) -> bool:
    """True when two records describe one product under different spellings.

    Exact-key matching cannot catch every case: one researcher wrote
    "Philips Tableaux 5150I (32in)" and another
    "Philips Tableaux 5150I - 32BDL5150I/00 (31.5in)". Same display, one with
    the order code appended. So within a (brand, size, colour) group, a core
    that CONTAINS another core is treated as the same product -- unless one
    carries a distinctness marker the other lacks.
    """
    if brand_of(a) != brand_of(b):
        return False
    if colour_class(a) != colour_class(b):
        return False
    try:
        if round(float(a.get("diagonal_in") or 0), 1) != round(
                float(b.get("diagonal_in") or 0), 1):
            return False
    except (TypeError, ValueError):
        return False
    ca, cb = model_core(a), model_core(b)
    for mk in DISTINCT_MARKERS:
        if (mk in ca) != (mk in cb):
            return False
    # An EMPTY core means the model name was nothing but brand and size --
    # BLOOMIN8's "EinkCanvas 28.5in (Large)" reduces to nothing once the brand
    # token is removed. Given brand, size and colour already match, that is the
    # brand's product at that size, so it should fold into the named record
    # rather than stand as a second device.
    if not ca or not cb:
        return True
    if min(len(ca), len(cb)) < 5:
        return ca == cb
    return ca in cb or cb in ca


def consolidate(devices: dict[str, dict], stream_of: dict[str, str]) -> dict:
    """Second pass: fold spelling variants that the exact key missed."""
    keys = list(devices)
    merged_into: dict[str, str] = {}
    for i, ka in enumerate(keys):
        if ka in merged_into:
            continue
        for kb in keys[i + 1:]:
            if kb in merged_into or kb not in devices:
                continue
            if same_product(devices[ka], devices[kb]):
                devices[ka] = deep_merge(devices[ka], devices[kb],
                                         stream_of.get(kb, "merged"))
                merged_into[kb] = ka
    for k in merged_into:
        devices.pop(k, None)
    return devices


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
        elif (
            k not in cur
            or cur[k] in (None, "", [], {})
            or (
                isinstance(v, str)
                and isinstance(cur[k], str)
                and len(v) > len(cur[k])
            )
        ):
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
            k = vendor_key(v)
            vendors[k] = deep_merge(vendors.get(k, {}), v, stream) \
                if k in vendors else deep_merge(dict(v), {}, stream)
        for lead in d.get("leads_not_followed") or []:
            leads.append({"_stream": stream, **lead} if isinstance(lead, dict)
                         else {"_stream": stream, "lead": lead})
        for u in d.get("unverified_facts") or []:
            unverified.append({"_stream": stream, **u} if isinstance(u, dict)
                              else {"_stream": stream, "fact": u})

    corrections_applied = apply_corrections(devices)
    devices = consolidate(devices, {k: (v.get("_streams") or ["merged"])[0]
                                    for k, v in devices.items()})
    dev_list = sorted(devices.values(),
                      key=lambda x: -(x.get("diagonal_in") or 0))
    sidecars = {}
    for key, path in SIDECAR_STREAMS:
        if path.exists():
            sidecars[key] = json.loads(path.read_text())
        else:
            print(f"MISSING {path}")

    out = {
        "_schema": "faa-eink-targets/2",
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
        "corrections_applied": corrections_applied,
        **sidecars,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))

    big = [d for d in dev_list if (d.get("diagonal_in") or 0) > 15]
    print(f"streams: {counts}")
    print(f"merged : {len(dev_list)} devices ({len(big)} above 15in), "
          f"{len(vendors)} vendors, {len(leads)} leads, "
          f"{len(unverified)} unverified facts")
    for c in corrections_applied:
        print(f"correction: {c}")
    for k, v in sidecars.items():
        n = len(v.get("campaigns") or v.get("panel_makers") or [])
        print(f"sidecar: {k} ({n} records)")
    print(f"wrote  : {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
