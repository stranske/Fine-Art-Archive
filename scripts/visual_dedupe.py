#!/usr/bin/env python3
"""DINOv2 visual-identity matcher — residual (vision) stage of the D017 dedup cascade.

Why DINOv2, not CLIP: CLIP embeddings cluster by semantic subject/style, which is
good for "find thematically similar art" but weak for "is this the SAME work, just a
different photograph?" DINOv2 (Meta, self-supervised ViT) is near-SOTA for
instance-level visual retrieval — the right tool for same-artwork identity. It loads
through the already-installed `transformers` (facebook/dinov2-large).

Runs in the .faa-venv (torch + transformers). NOT runnable in the Cowork sandbox
(no torch). Designed to score a SMALL candidate set produced by the artist-Q-ID /
metadata blocking stages (--artist-block), so the vision pass stays cheap.

Usage (on the Mac, in the venv):
  python scripts/visual_dedupe.py embed-archive [--budget S] [--model base|large]
  python scripts/visual_dedupe.py match WID [WID ...] [--artist-block] [--topk 5]
  python scripts/visual_dedupe.py match-all [--artist-block]

Cache: dinov2_embed_cache.npz (stacked float16 vectors) + dinov2_embed_index.json
       (wid -> {row, title, artist_qid}). Resumable, like perceptual_dedupe.py.
Cosine guide: >=0.90 likely same work; 0.80-0.90 near/related; lower unrelated.
Tune against real matches before trusting thresholds.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT.parent / "Art" / "works"
STAGE = ROOT / "staging_acquisitions"
SIDE = ROOT / "staging_sidecars"
EMB = ROOT / "dinov2_embed_cache.npz"
IDX = ROOT / "dinov2_embed_index.json"
MODELS = {"base": "facebook/dinov2-base", "large": "facebook/dinov2-large"}

_model = _proc = _dev = None


def _load_model(which="large"):
    # AutoModel needs only torch; we do DINOv2's standard preprocessing manually
    # (PIL + numpy) so torchvision is NOT required.
    global _model, _dev
    if _model is not None:
        return
    import torch
    from transformers import AutoModel

    name = MODELS.get(which, which)
    if torch.cuda.is_available():
        _dev = "cuda"
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        _dev = "mps"
    else:
        _dev = "cpu"
    _model = AutoModel.from_pretrained(name).to(_dev).eval()
    print(f"loaded {name} on {_dev} (manual PIL preprocessing, no torchvision)")


def embed_image(path):
    import numpy as np
    import torch
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(path)
    try:
        im.draft("RGB", (512, 512))  # fast scaled JPEG decode for huge masters
    except Exception:
        pass
    im = im.convert("RGB")
    # DINOv2 preprocessing: resize shortest side to 256 (bicubic), center-crop 224,
    # rescale to [0,1], ImageNet-normalize.
    w, h = im.size
    s = 256.0 / min(w, h)
    im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.BICUBIC)
    w, h = im.size
    left, top = (w - 224) // 2, (h - 224) // 2
    im = im.crop((left, top, left + 224, top + 224))
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = (arr - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
        [0.229, 0.224, 0.225], np.float32
    )
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(_dev)
    with torch.no_grad():
        out = _model(pixel_values=t)
        v = getattr(out, "pooler_output", None)
        v = v[0] if v is not None else out.last_hidden_state[0, 0]
        v = torch.nn.functional.normalize(v, dim=0)
    return v.float().cpu().numpy().astype("float16")


def master_of(d):
    g = sorted(glob.glob(str(Path(d) / "master.*"))) or sorted(glob.glob(str(Path(d) / "*.jp*g")))
    return g[0] if g else None


def _meta(wid, prefer=SIDE):
    for b in (prefer, STAGE, SIDE):
        p = b / wid / "meta.json"
        if p.exists():
            try:
                return json.load(open(p))
            except Exception:
                return {}
    return {}


def _artist_qid(wid, prefer=SIDE):
    a = _meta(wid, prefer).get("artist")
    if isinstance(a, dict):
        return a.get("wikidata_q") or (a.get("canonical") or {}).get("wikidata_q")
    return None


def _title(wid, prefer=SIDE):
    return _meta(wid, prefer).get("title") or ""


def _load_cache():
    if EMB.exists() and IDX.exists():
        return np.load(EMB)["emb"], json.load(open(IDX))
    return None, {}


def embed_archive(budget=300, which="large"):
    _load_model(which)
    dirs = [d for d in sorted(glob.glob(str(ART / "*"))) if os.path.isdir(d)]
    emb, idx = _load_cache()
    vecs = list(emb) if emb is not None and len(emb) else []
    t0 = time.time()
    done = 0
    for d in dirs:
        wid = os.path.basename(d)
        if wid in idx:
            continue
        if time.time() - t0 > budget:
            break
        m = master_of(d)
        if not m:
            continue
        try:
            v = embed_image(m)
        except Exception:
            continue
        idx[wid] = {"row": len(vecs), "title": _title(wid), "artist_qid": _artist_qid(wid)}
        vecs.append(v)
        done += 1
        if done % 250 == 0:  # checkpoint so a long run is resumable if interrupted
            np.savez_compressed(EMB, emb=np.stack(vecs).astype("float16"))
            json.dump(idx, open(IDX, "w"))
    arr = np.stack(vecs).astype("float16") if vecs else np.zeros((0, 1), "float16")
    np.savez_compressed(EMB, emb=arr)
    json.dump(idx, open(IDX, "w"))
    print(f"embed-archive: +{done} | cached {len(idx)}/{len(dirs)} | {time.time()-t0:.1f}s")


def match(wids, artist_block=False, topk=5, which="large"):
    emb, idx = _load_cache()
    if emb is None or len(idx) == 0:
        print("no embedding cache; run embed-archive first")
        return
    _load_model(which)
    rows = np.asarray(emb, dtype="float32")
    wid_by_row = {v["row"]: k for k, v in idx.items()}
    for wid in wids:
        m = master_of(STAGE / wid)
        if not m:
            print(f"\n{wid}: no master")
            continue
        q = np.asarray(embed_image(m), dtype="float32")
        sims = rows @ q
        sa = _artist_qid(wid, STAGE)
        print(f"\n=== {wid}  ({_title(wid, STAGE)})  artist_qid={sa}")
        shown = 0
        for r in np.argsort(-sims):
            ew = wid_by_row.get(int(r))
            if not ew:
                continue
            if artist_block and sa and idx[ew].get("artist_qid") and idx[ew]["artist_qid"] != sa:
                continue
            s = float(sims[r])
            tag = "SAME?" if s >= 0.90 else ("near" if s >= 0.80 else "")
            print(f"   cos={s:.3f} {tag:5} {ew[:44]:44} {idx[ew]['title'][:30]}")
            shown += 1
            if shown >= topk:
                break


def smoketest(which="base"):
    """Quick proof that DINOv2 separates same-work from different-work: embeds a
    few staged works + their known archive twins and prints cosine similarity.
    Same-work pairs should score clearly higher than the cross pairs."""
    import numpy as np

    _load_model(which)
    pairs = [
        (
            "Night Watch",
            "1016bed-the-night-watch-rembrandt",
            "d4563ec-the-night-watch-militia-company-of-rijn",
        ),
        (
            "Arnolfini",
            "8f36d6e-arnolfini-portrait-eyck",
            "3e18a69-portrait-of-giovanni-arnolfini-and-his-eyck",
        ),
        (
            "Little Street",
            "1f1d9cc-the-little-street-vermeer",
            "9c589da-view-of-houses-in-delft-street",
        ),
        (
            "Paris Street",
            "f17f552-paris-street-rainy-day-caillebotte",
            "92aee30-paris-street-caillebotte",
        ),
    ]
    sv, tv = {}, {}
    print(f"\nDINOv2 ({MODELS.get(which, which)}) — same-work vs different-work cosine\n")
    for label, sw, tw in pairs:
        sp, tp = master_of(STAGE / sw), master_of(ART / tw)
        if not sp or not tp:
            print(f"  {label:14} SKIP (missing master file)")
            continue
        s = np.asarray(embed_image(sp), dtype="float32")
        t = np.asarray(embed_image(tp), dtype="float32")
        sv[label], tv[label] = s, t
        print(f"  SAME  {label:14} cos={float(s @ t):+.3f}")
    labels = list(sv)
    print()
    for i, lbl in enumerate(labels):
        if len(labels) < 2:
            break
        lbl2 = labels[(i + 1) % len(labels)]
        print(f"  DIFF  {lbl:14} vs {lbl2:14} cos={float(sv[lbl] @ tv[lbl2]):+.3f}")
    print("\nExpect SAME clearly above DIFF -> DINOv2 is separating work identity as intended.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("embed-archive")
    e.add_argument("--budget", type=int, default=300)
    e.add_argument("--model", default="large")
    mm = sub.add_parser("match")
    mm.add_argument("wids", nargs="+")
    mm.add_argument("--artist-block", action="store_true")
    mm.add_argument("--topk", type=int, default=5)
    mm.add_argument("--model", default="large")
    ma = sub.add_parser("match-all")
    ma.add_argument("--artist-block", action="store_true")
    ma.add_argument("--model", default="large")
    st = sub.add_parser("smoketest")
    st.add_argument("--model", default="base")
    a = ap.parse_args()
    if a.cmd == "embed-archive":
        embed_archive(a.budget, a.model)
    elif a.cmd == "match":
        match(a.wids, a.artist_block, a.topk, a.model)
    elif a.cmd == "match-all":
        match(
            [os.path.basename(d) for d in sorted(glob.glob(str(STAGE / "*"))) if os.path.isdir(d)],
            a.artist_block,
            which=a.model,
        )
    elif a.cmd == "smoketest":
        smoketest(a.model)
