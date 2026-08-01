#!/usr/bin/env python3
"""Backfill ``category`` for uncategorized works from visual classification.

The final slice of the uncategorized floor is works with no work QID, no usable
medium, and (for many) a multi-medium artist -- so P31, medium heuristics, safe
work-QID matching, and the creator-occupation prior all abstain. The one signal
left is the work's own image: a photo of an oil painting plainly shows a
painting; a woodblock print, a mosaic, a photograph, or a marble bust are each
unmistakable on sight.

:data:`IMAGE_CATEGORIES` is a curated table: each master image was inspected and
classified into the schema ``category`` enum. Because this is a visual inference
(not a catalogue fact), the category is written with provenance status
``unverified`` -- honestly distinguished from the ``available`` categories set
from P31 / medium evidence. A per-work guard only writes when the sidecar is
still uncategorized, so the table never overrides a value set by a
higher-confidence pass.

Dry-run by default; ``--apply`` writes, records ``field_provenance`` for
``category`` (status ``unverified``, source ``image``), mirrors to Art/works,
and logs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import provenance, sidecar  # noqa: E402

_UNCATEGORIZED = (None, "", "(uncategorized)")

# work_id -> category, from visual inspection of the master image (2026-08-01).
IMAGE_CATEGORIES: dict[str, str] = {
    "03af6bd-portrait-of-marcelle-roulin-gogh": "painting",  # Portrait of Marcelle Roulin
    "08dc17f-clovis-sleeping-gauguin": "painting",  # Clovis Sleeping
    "08e1f96-portrait-of-richard-m-nixon-rockwell": "painting",  # Portrait of Richard M. Nixon
    "0a005ef-the-shipbuilder-and-his-wife-jan": "painting",  # The Shipbuilder and His Wife
    "0b0b44a-quire-ceiling-cathedral": "mosaic",  # Quire Ceiling (St Paul's, mosaic domes)
    "0fa11af-model-soapstone": "sculpture",  # Model (soapstone head)
    "118b36a-the-butcher-los-gauchos-series-cesareo": "painting",  # The Butcher (Los Gauchos)
    "1532f6c-view-from-theo-s-apartment-gogh": "painting",  # View from Theo's Apartment
    "178eaf0-flagellation-and-bearing-of-the-cross-elder": "painting",  # Holbein panels
    "1a0a85f-thomas-jefferson-peale": "painting",  # Thomas Jefferson
    "1d182e8-after-the-battle-of-curupayti-lopez": "painting",  # After the Battle of Curupayti
    "1e21dd9-field-with-irises-near-arles-gogh": "painting",  # Field with Irises near Arles
    "20f8c49-19-rutherford-b-hayes": "painting",  # Rutherford B. Hayes
    "2b034ff-wheatfield-with-partridge-gogh": "painting",  # Wheatfield with Partridge
    "2ddc608-the-cathedral-and-metropolitical-church-of-1296": "stained_glass",  # York Great East Window
    "38a094b-wirbelwerk-eliasson": "sculpture",  # Wirbelwerk (hanging installation)
    "3aa5252-flowering-plum-orchard-after-hiroshige-gogh": "painting",  # Flowering Plum Orchard
    "3e0f4cf-marxism-will-give-health-to-the-masonite": "painting",  # Kahlo, Marxism...
    "45397d0-red-cliffs-near-anthe-or-valtat": "painting",  # Red Cliffs near Anthéor
    "4800c69-sant-apollinare-nuovo-built-by-the-chapel": "mosaic",  # Sant'Apollinare Nuovo Palatium
    "4842821-old-woman-reading-probably-the-prophetess-rijn": "painting",  # Rembrandt, Old Woman Reading
    "4972287-the-dutch-proverbs-elder": "painting",  # Bruegel, Netherlandish Proverbs
    "4a067a9-aeneas-taken-by-the-sibyl-to": "painting",  # Swanenburgh, Aeneas
    "4aed2be-sprig-of-flowering-almond-in-a-gogh": "painting",  # Sprig of Flowering Almond
    "54333c7-the-love-line-ensor": "painting",  # Ensor, The Love Line
    "56d4631-going-back-to-the-roots-jb": "painting",  # Maingi, Going back to the roots
    "5ce16da-the-black-obelisk-of-shalmaneser-iii-neoassyrian": "sculpture",  # relief obelisk
    "5da94a9-mishima-morning-mist-mishima-asagiri-hiroshige-print": "print",  # Hiroshige woodblock
    "5fe176a-roses-gogh": "painting",  # Roses
    "6013fa7-the-virgin-and-child-with-canon-eyck": "painting",  # van Eyck, Canon van der Paele
    "603c5f6-vase-with-gladioli-and-chinese-asters-gogh": "painting",  # Vase with Gladioli
    "61735c8-cascada-dynjandi-vestfirir": "photograph",  # Dynjandi waterfall (landscape photo)
    "65001ca-flute-concert-with-frederick-the-great-menzel": "painting",  # Menzel, Flute Concert
    "6aacb85-calvin-coolidge-hopkinson": "painting",  # Hopkinson, Coolidge portrait
    "6c391b5-gauguin-s-chair-gogh": "painting",  # Gauguin's Chair
    "726cf99-dog-town-from-searching-journeys-3-moriyama": "photograph",  # Moriyama photo
    "79b8431-sharing-the-cake-bertiers": "painting",  # Bertiers, Sharing the cake
    "7a54bbd-rembrandt-laughing-about-1628": "painting",  # Rembrandt Laughing
    "7ad5d41-cafe-table-with-absinthe-gogh": "painting",  # Café Table with Absinthe
    "7cfe915-montmartre-windmills-and-allotments-gogh": "painting",  # Montmartre, Windmills
    "817dc64-aeneas-taken-by-the-sibyl-to": "painting",  # Swanenburgh, Aeneas (dup)
    "872a0bc-weaver-gogh": "drawing",  # van Gogh, Weaver (watercolour on paper)
    "87f8847-buddha-redon": "drawing",  # Redon, Buddha (pastel on paper)
    "887c6d2-baturraden-overview-from-ridge-purwokerto": "photograph",  # landscape photo
    "8b7faad-paliotto-altar-frontal-novella": "other",  # embroidered altar frontal (no enum fit)
    "8e96b64-russian-cavalry-on-the-attack-in-yuriyevich": "painting",  # Russian Cavalry
    "918dff6-mural-by-hunto-milo-tchais-hunto": "mural",  # street murals on shutters
    "9422d1c-mural-by-hunto-millo": "painting",  # image is a cubist painting (metadata mismatch)
    "967f2ca-salome-receiving-the-head-of-john-rijn": "painting",  # circle of Rembrandt, Salome
    "995d564-the-mausoleum-of-galla-placidia-3-ce": "mosaic",  # Galla Placidia mosaic
    "a518eab-ulysses-companions-meet-the-daughter-of-292": "fresco",  # Roman Odyssey wall frescoes
    "acc7461-ulysses-simpson-grant-mathew-brady-studio-negative": "photograph",  # Brady studio photo
    "b0b3ea6-papa-mama-and-their-children-shoji": "photograph",  # Ueda Shoji photo
    "b15fc61-caucasus-ingushetia": "architecture",  # Ingush towers (site-anchored building)
    "b1ae4a8-pierrot-in-despair-ensor": "painting",  # Ensor, Pierrot in despair
    "b353d0e-do-you-want-a-piece-of": "mural",  # street mural
    "b44ff28-pennsylvania-station-excavation-george-wesley-bellows-canvas": "painting",  # Bellows
    "b601764-landscape-ruisdael": "painting",  # Ruisdael, Landscape
    "b9703b0-self-portrait-gogh": "painting",  # van Gogh self-portrait
    "bd7244f-30-calvin-coolidge-1919": "photograph",  # Coolidge photo portrait
    "c223291-sancho-panza-lying-down-portinari": "drawing",  # Portinari (crayon/pastel on paper)
    "cf87988-spring-de": "painting",  # van de Venne, Spring
    "cfdcd43-ruined-monastery-of-eldena-near-greifswald-friedrich": "painting",  # Friedrich
    "d3f98c4-37-richard-nixon-1973": "photograph",  # Nixon photo
    "d7869c2-34-dwight-eisenhower-june-1956": "photograph",  # Eisenhower photo
    "d7f07f4-the-mausoleum-of-galla-placidia-2-ce": "mosaic",  # Galla Placidia mosaic
    "d9f625c-rocky-landscape-in-the-elbe-sandstone": "painting",  # Friedrich, Rocky Landscape
    "ddaf77f-montmartre-in-the-rain-bonnard": "painting",  # Bonnard, Montmartre in the Rain
    "e42a2a4-thresher-after-millet-gogh": "painting",  # Thresher (after Millet)
    "e474fae-view-of-auvers-sur-oise-gogh": "painting",  # View of Auvers-sur-Oise
    "e5b659b-portrait-of-lyndon-b-johnson-rockwell": "painting",  # Rockwell, LBJ
    "e6494c8-32-2-anna-eleanor-roosevelt-portrait": "photograph",  # Eleanor Roosevelt photo (Karsh)
    "e9a1e89-the-dutch-proverbs-2-elder": "painting",  # Bruegel, Netherlandish Proverbs (dup)
    "ebe2cb4-birds-eye-view-of-the-village-teiko": "photograph",  # Shiotani Teiko pictorialist photo
    "eda0335-vase-of-flowers-gogh": "painting",  # van Gogh, Vase of Flowers
    "ef98d26-the-isle-of-the-dead-bocklin": "painting",  # Böcklin, Isle of the Dead
    "efa4110-the-virgin-and-child-with-canon-eyck": "painting",  # van Eyck, Canon van der Paele
    "f120db4-a-portrait-of-the-comet-boy-lee": "painting",  # Timothy Lee, mixed-media portrait panel
    "f8fc50e-the-mausoleum-of-galla-placidia-ce": "mosaic",  # Galla Placidia Good Shepherd mosaic
    "fc7e513-vase-of-flowers-and-cup-bernard": "painting",  # Emile Bernard
}

_NOTE = (
    "Category determined from visual inspection of the master image; unverified AI classification."
)


@dataclass
class ImageBackfillStats:
    matched: int  # table entries whose sidecar was found + still uncategorized
    updated_works: int  # sidecars written (0 in dry-run)
    skipped_categorized: int  # found but already categorized (guard)
    mirrored: int


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _write_existing_mirrors(
    meta: dict[str, Any], art_works_root: Path | None, *, exclude: Path
) -> list[Path]:
    if art_works_root is None:
        return []
    work_id = str(meta["work_id"])
    candidates = {
        art_works_root / "works" / work_id / "meta.json",
        art_works_root / work_id / "meta.json",
    }
    written: list[Path] = []
    for candidate in sorted(candidates):
        if candidate.is_file() and candidate.resolve() != exclude.resolve():
            sidecar.write(candidate, meta)
            written.append(candidate)
    return written


def _append_operation(
    log_path: Path, meta: dict[str, Any], category: str, staging_path: Path, mirrors: list[Path]
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_categories_from_image",
        "op": "category_image_backfill",
        "work_id": meta["work_id"],
        "category": category,
        "status": "unverified",
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirrors],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def backfill(
    staging_dir: Path,
    *,
    categories: dict[str, str] = IMAGE_CATEGORIES,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    apply: bool = False,
) -> tuple[ImageBackfillStats, Counter[str]]:
    matched = updated = skipped = mirrored = 0
    by_category: Counter[str] = Counter()
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        work_id = str(meta.get("work_id") or "")
        category = categories.get(work_id)
        if category is None:
            continue
        if meta.get("category") not in _UNCATEGORIZED:
            skipped += 1  # guard: a higher-confidence pass already set it
            continue
        matched += 1
        meta["category"] = category
        provenance.set(meta, "category", "unverified", "image", source_ref=None, note=_NOTE)
        sidecar.validate(meta)
        by_category[category] += 1
        if apply:
            sidecar.write(path, meta)
            mirrors = _write_existing_mirrors(meta, art_works_root, exclude=path)
            updated += 1
            mirrored += len(mirrors)
            if operations_log is not None:
                _append_operation(operations_log, meta, category, path, mirrors)
    return ImageBackfillStats(matched, updated, skipped, mirrored), by_category


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=_env_path("FAA_STAGING_DIR") or ROOT / "staging_sidecars",
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    args = parser.parse_args(argv)

    stats, by_category = backfill(
        args.staging_dir,
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"category-from-image backfill ({mode}): matched={stats.matched} "
        f"updated_works={stats.updated_works} skipped_categorized={stats.skipped_categorized} "
        f"mirrored={stats.mirrored}"
    )
    if by_category:
        print("by category:", dict(by_category.most_common()))
    if not args.apply and stats.matched:
        print("(dry-run: no files written; categories would be status=unverified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
