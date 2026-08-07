#!/usr/bin/env python3
"""Gate for the e-paper survey merge keys. Run after editing BRAND_CANON:

    python3 scripts/test_merge_eink_survey.py

Three researchers wrote the same vendor three different ways, so the merge key
has to collapse spellings without collapsing genuinely different SKUs. Both
directions have bitten:

* Keying on the raw vendor string counted PocketBook's products three times and
  inflated the corpus to 48 devices above 15in when the corrected figure is 36.
* Substring brand matching filed "MEiNK" and BLOOMIN8's "EinkCanvas" under
  E Ink Holdings, because both contain the letters "eink".
* An early attempt stripped "(Color Version)" out of model names, which
  collapsed the BOOX Mira Pro colour and monochrome SKUs into one device.

So the assertions come in pairs: must-collapse and must-stay-distinct.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "mg", Path(__file__).resolve().parent / "merge_eink_survey.py"
)
mg = importlib.util.module_from_spec(spec)
sys.modules["mg"] = mg
spec.loader.exec_module(mg)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(
        ("  PASS  " if cond else "  FAIL  ")
        + name
        + (f"\n           {detail}" if detail and not cond else "")
    )
    if not cond:
        _fails.append(name)


def dev(vendor: str, model: str, dia: float, panel: str = "", colour: str = "") -> dict:
    return {"vendor": vendor, "model": model, "diagonal_in": dia, "panel": panel, "colour": colour}


def same(a: dict, b: dict) -> bool:
    """What the merge actually does: exact key, then the containment pass."""
    return mg.dev_key(a) == mg.dev_key(b) or mg.same_product(a, b)


def writer_mod():
    """Load the survey writer exactly as its standalone entry point does."""
    spec = importlib.util.spec_from_file_location(
        "writer_test", Path(__file__).resolve().parent / "write_eink_survey_doc.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    # ---- brand attribution ------------------------------------------------
    check(
        "MEiNK is not filed under E Ink",
        mg.brand_of(
            dev("MEiNK (sold by media mea)", 'MEiNK 32" E Ink Spectra 6 ePaper Signage', 31.5)
        )
        == "meink",
        mg.brand_of(
            dev("MEiNK (sold by media mea)", 'MEiNK 32" E Ink Spectra 6 ePaper Signage', 31.5)
        ),
    )
    check(
        "BLOOMIN8's EinkCanvas is not filed under E Ink",
        mg.brand_of(dev("BLOOMIN8 (arpobot)", 'EinkCanvas 28.5" (Large)', 28.5)) == "bloomin8",
        mg.brand_of(dev("BLOOMIN8 (arpobot)", 'EinkCanvas 28.5" (Large)', 28.5)),
    )
    check(
        "E Ink's own module IS filed under E Ink",
        mg.brand_of(dev("E Ink Holdings", 'E Ink 31.5" Spectra 6 ePaper Display module', 31.5))
        == "eink",
    )
    check(
        "InkPoster keys to its product brand, not the parent",
        mg.brand_of(dev("PocketBook International S.A.", 'PocketBook InkPoster Tela 40.5"', 40.5))
        == "inkposter",
    )
    check(
        "IONNYK stays distinct from InkPoster despite shared owner",
        mg.brand_of(dev("IONNYK (brand of Pocketbook)", "IONNYK Jane", 25.0))
        != mg.brand_of(dev("InkPoster (brand of PocketBook)", "InkPoster Tela", 28.5)),
    )
    check(
        "unrecognized long vendor names do not collide after normalization",
        mg.vendor_key({"name": "Independent Display Manufacturer Alpha"})
        != mg.vendor_key({"name": "Independent Display Manufacturer Beta"}),
    )

    # ---- writer helper loading and generated-table formatting -------------
    writer = writer_mod()
    helpers = writer._merge_mod()
    check(
        "writer loads the merge helpers",
        hasattr(helpers, "vendor_key") and hasattr(helpers, "brand_of"),
    )
    check("writer helper import does not register mg_doc globally", "mg_doc" not in sys.modules)
    check(
        "writer truncates table cells at word boundaries",
        writer.clip("Dasung Paperlike 253 / 253U and Paperlike Color", 40)
        == "Dasung Paperlike 253 / 253U and…",
    )
    original_spec = writer.importlib.util.spec_from_file_location
    try:
        writer.importlib.util.spec_from_file_location = lambda *_args, **_kwargs: None
        try:
            writer._merge_mod()
        except ImportError:
            no_spec_raises = True
        else:
            no_spec_raises = False
        check("writer rejects a missing import specification", no_spec_raises)

        class NoLoaderSpec:
            loader = None

        writer.importlib.util.spec_from_file_location = lambda *_args, **_kwargs: NoLoaderSpec()
        try:
            writer._merge_mod()
        except ImportError:
            no_loader_raises = True
        else:
            no_loader_raises = False
        check("writer rejects an import specification without a loader", no_loader_raises)
    finally:
        writer.importlib.util.spec_from_file_location = original_spec

    # ---- must collapse: same product, three spellings ---------------------
    check(
        "PocketBook/InkPoster Tela 40.5 spellings collapse",
        same(
            dev(
                "PocketBook International S.A.",
                'PocketBook InkPoster Tela 40.5"',
                40.5,
                colour="Spectra 6",
            ),
            dev("InkPoster (brand of PocketBook)", "InkPoster Tela 40.5", 40.5, colour="Spectra 6"),
        ),
    )
    check(
        "Bigme B251 Pro spellings collapse",
        same(
            dev("Bigme (Xinruizhi Technology)", 'Bigme B251 PRO 25.3"', 25.3, panel="Kaleido 3"),
            dev(
                "Bigme (brand of Xinruizhi)",
                "Bigme B251 Pro 25.3 colour e-ink monitor",
                25.3,
                panel="Kaleido 3",
            ),
        ),
    )
    check(
        "Philips Tableaux 5150I spellings collapse",
        same(
            dev(
                "PPDS (Philips professional)",
                'Philips Tableaux 5150I (32")',
                31.5,
                colour="Spectra 6",
            ),
            dev(
                "PPDS / TP Vision / MMD",
                'Philips Tableaux 5150I — 32BDL5150I/00 (31.5")',
                31.5,
                colour="Spectra 6",
            ),
        ),
    )

    # ---- must NOT collapse: genuinely different products ------------------
    check(
        "BOOX Mira Pro colour vs monochrome stay distinct",
        not same(
            dev(
                "Onyx International Inc. (BOOX)",
                'BOOX Mira Pro (Color Version) 25.3"',
                25.3,
                panel="Kaleido 3",
            ),
            dev(
                "Onyx International Inc. (BOOX)",
                'BOOX Mira Pro (monochrome) 25.3"',
                25.3,
                panel="Carta mono",
            ),
        ),
    )
    check(
        "Visionect retail unit vs $6000 dev kit stay distinct",
        not same(
            dev("Visionect d.o.o.", 'Visionect Place & Play 32"', 31.2, colour="monochrome"),
            dev(
                "Visionect d.o.o.",
                'Visionect Place & Play 32" Development Kit',
                31.2,
                colour="monochrome",
            ),
        ),
    )
    check(
        "Good Display bare panel vs finished display stay distinct",
        not same(
            dev(
                "Dalian Good Display", 'GDEP315C01(E6) - 31.5" bare panel', 31.5, colour="Spectra 6"
            ),
            dev(
                "Dalian Good Display",
                'DMPH315E62 — 31.5" Spectra 6 finished e-paper display',
                31.5,
                colour="Spectra 6",
            ),
        ),
    )
    check(
        "InkPoster Tela vs Duna stay distinct",
        not same(
            dev("InkPoster", "InkPoster Tela 40.5", 40.5, colour="Spectra 6"),
            dev("InkPoster", "InkPoster Duna 40.5 (Pininfarina)", 40.5, colour="Spectra 6"),
        ),
    )
    check(
        "same model at different sizes stays distinct",
        not same(
            dev("InkPoster", "InkPoster Tela", 28.5, colour="Spectra 6"),
            dev("InkPoster", "InkPoster Tela", 40.5, colour="Spectra 6"),
        ),
    )

    print(f"\n{'ALL PASS' if not _fails else f'{len(_fails)} FAILURE(S)'}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
