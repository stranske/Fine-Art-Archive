"""D017 dedup cascade — the blocking, cheapest-first gate for the acquire path.

A new acquisition is checked against the archive *before* promotion
(DECISIONS D017), replacing the name+size guessing that mis-flagged the
2026-05-25 batch:

  1. sha256          exact byte-identical file
  2. perceptual hash near-identical reproduction (dHash, Hamming <= threshold)
  3. artist Q-ID     block candidates to the same creator (Q-ID, not name string)
  4. metadata        title similarity within the artist block
  5. DINOv2          vision confirmation on the residual (pluggable hook)

Layers 1-4 are pure-Python (PIL + stdlib) and decide the common cases. Layer 5
needs torch + the archive embedding cache and is supplied as a hook so it runs
operationally (scripts/visual_dedupe.py) without being a library/CI dependency.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from fine_art_archive.collect.dedupe import _title_similarity

Image.MAX_IMAGE_PIXELS = None

PHASH_BITS = 16  # 16x16 grid -> 256-bit dHash / aHash


def hamming(a: int, b: int) -> int:
    """Bit-count of the XOR — the Hamming distance between two hashes."""
    return bin(a ^ b).count("1")


def perceptual_hashes(image_path: Path | str, hs: int = PHASH_BITS) -> tuple[int, int]:
    """Return (dHash, aHash) as 256-bit ints — resolution/format invariant."""
    im = Image.open(image_path)
    with contextlib.suppress(Exception):
        im.draft("L", (hs * 4, hs * 4))  # fast scaled decode for huge masters
    im = im.convert("L")  # type: ignore[assignment]
    gd = im.resize((hs + 1, hs), Image.Resampling.BILINEAR)
    px = gd.tobytes()
    width = hs + 1
    dh = 0
    for row in range(hs):
        base = row * width
        for col in range(hs):
            dh = (dh << 1) | (1 if px[base + col] < px[base + col + 1] else 0)
    ga = im.resize((hs, hs), Image.Resampling.BILINEAR)
    pa = ga.tobytes()
    avg = sum(pa) / len(pa)
    ah = 0
    for p in pa:
        ah = (ah << 1) | (1 if p >= avg else 0)
    return dh, ah


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class ArchiveEntry:
    """One archived work, as known to the cascade (from the pHash cache + sidecars)."""

    wid: str
    sha256: str | None = None
    dhash: int | None = None
    ahash: int | None = None
    artist_qid: str | None = None
    title: str = ""


@dataclass
class Candidate:
    """A staged acquisition's identity keys."""

    sha256: str | None = None
    dhash: int | None = None
    ahash: int | None = None
    artist_qid: str | None = None
    title: str = ""


@dataclass
class DedupVerdict:
    status: str  # "new" | "duplicate" | "needs_review"
    layer: str  # the cascade layer that decided
    matched_wid: str | None = None
    distance: int | None = None  # Hamming distance for the pHash layer
    detail: str = ""

    @property
    def is_duplicate(self) -> bool:
        return self.status == "duplicate"


# A hook: given the candidate and the residual archive block, return the best
# (wid, cosine_similarity) match or None. Supplied operationally (DINOv2).
DinoHook = Callable[[Candidate, Sequence[ArchiveEntry]], "tuple[str, float] | None"]


def dedup_check(
    candidate: Candidate,
    archive: Sequence[ArchiveEntry],
    *,
    phash_threshold: int = 13,
    title_threshold: float = 0.85,
    dino_threshold: float = 0.90,
    dino_hook: DinoHook | None = None,
) -> DedupVerdict:
    """Run the D017 cascade and return a promotion verdict for ``candidate``."""
    # Layer 1 — exact byte match
    if candidate.sha256:
        for e in archive:
            if e.sha256 and e.sha256 == candidate.sha256:
                return DedupVerdict("duplicate", "sha256", e.wid, 0, "exact byte match")

    # Layer 2 — perceptual hash (near-identical reproduction)
    if candidate.dhash is not None:
        best: tuple[int, int | None, str] | None = None
        for e in archive:
            if e.dhash is None:
                continue
            d = hamming(candidate.dhash, e.dhash)
            a_dist = (
                hamming(candidate.ahash, e.ahash)
                if candidate.ahash is not None and e.ahash is not None
                else None
            )
            rank = (d, a_dist if a_dist is not None else PHASH_BITS * PHASH_BITS + 1)
            if best is None:
                best = (d, a_dist, e.wid)
                continue
            best_rank = (
                best[0],
                best[1] if best[1] is not None else PHASH_BITS * PHASH_BITS + 1,
            )
            if rank < best_rank:
                best = (d, a_dist, e.wid)
        if best is not None and best[0] <= phash_threshold:
            detail = f"dHam {best[0]} <= {phash_threshold}"
            if best[1] is not None:
                detail = f"{detail}; aHam {best[1]}"
            return DedupVerdict(
                "duplicate",
                "phash",
                best[2],
                best[0],
                detail,
            )

    # Layer 3 — artist Q-ID block (narrow to the same creator)
    block = [e for e in archive if candidate.artist_qid and e.artist_qid == candidate.artist_qid]

    # Layer 4 — metadata narrow (title similarity within the block)
    if block and candidate.title:
        scored = sorted(
            ((_title_similarity(candidate.title, e.title), e) for e in block if e.title),
            key=lambda t: t[0],
            reverse=True,
        )
        if scored and scored[0][0] >= title_threshold:
            e = scored[0][1]
            return DedupVerdict(
                "needs_review",
                "metadata",
                e.wid,
                detail=f"same artist + title sim {scored[0][0]:.2f}",
            )

    # Layer 5 — DINOv2 vision confirmation on the residual block (operational hook)
    if dino_hook is not None and block:
        hit = dino_hook(candidate, block)
        if hit is not None:
            wid, sim = hit
            status = "duplicate" if sim >= dino_threshold else "needs_review"
            return DedupVerdict(status, "dinov2", wid, detail=f"cosine {sim:.3f}")

    return DedupVerdict("new", "none", detail="no match across the cascade")


def build_candidate(master_path: Path | str, meta: dict) -> Candidate:
    """Compute a candidate's identity keys from its master image + sidecar meta."""
    artist = meta.get("artist")
    qid = artist.get("wikidata_q") if isinstance(artist, dict) else None
    dh, ah = perceptual_hashes(master_path)
    return Candidate(
        sha256=sha256_file(master_path),
        dhash=dh,
        ahash=ah,
        artist_qid=qid,
        title=meta.get("title") or "",
    )


def load_archive_index(
    phash_cache_path: Path | str,
    *,
    artist_qids: dict[str, str] | None = None,
) -> list[ArchiveEntry]:
    """Build the cascade's archive index from the perceptual-hash cache
    (``archive_phash_cache.json``: wid -> {dhash, ahash, title}). ``artist_qids``
    optionally supplies a wid -> Q-ID map resolved from the sidecars."""
    cache = json.loads(Path(phash_cache_path).read_text())
    qids = artist_qids or {}
    out: list[ArchiveEntry] = []
    for wid, rec in cache.items():
        if "dhash" not in rec:
            continue
        out.append(
            ArchiveEntry(
                wid=wid,
                dhash=int(rec["dhash"], 16),
                ahash=int(rec["ahash"], 16),
                title=rec.get("title", ""),
                artist_qid=qids.get(wid),
            )
        )
    return out
