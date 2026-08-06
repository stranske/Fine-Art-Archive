# Large-format e-paper survey — development target

Generated 2026-08-05. Machine-readable companion: `config/eink_targets.json`.

**Scope:** reflective e-paper, **viewing area larger than 15 inches diagonal**, shipping or
announced. LCD/LED "art frames" (Meural, Samsung Frame, Canvia) are out of scope by definition —
they are not reflective.

**Why this exists:** to pick a development target for the archive's display push, and to stay
readable during development rather than living in a chat log. Two criteria dominate, per the owner:

1. **Staying power** — will the vendor and product still exist in ~3 years?
2. **Integration openness** — can *this* app push images to it over the local network, with no
   vendor cloud in the path?

**Coverage:** 52 device records (48 above 15"), 69 vendor
records, 49 leads recorded but not exhausted. Citations were
link-checked: 154 of 160 URLs resolved, 45 facts deliberately carry no URL rather than a guessed one.

---

## Ranked by the two criteria that matter

Sorted by integration openness, then vendor durability, then size.

| Size | Vendor | Model | Status | Price | Colour | Openness | Vendor durability |
|---|---|---|---|---|---|---|---|
| 31.5" | E Ink Holdings | E Ink 31.5" Spectra 6 ePaper Displ | shipping | — | full-colour 6-primary | **open** | high |
| 25.3" | Onyx International Inc. (B | BOOX Mira Pro (Color Version) 25.3 | shipping | $1,899 | Kaleido 3 — 4096 colours + | **open** | high |
| 25.3" | Onyx International Inc. (B | BOOX Mira Pro (monochrome) 25.3" | shipping | — | monochrome — 16 greyscale  | **open** | high |
| 25.3" | E Ink Holdings | E Ink 25.3" Spectra 6 ePaper Displ | shipping | $1,400 | full-colour 6-primary | **open** | high |
| 31.5" | Dalian Good Display Co., L | Good Display GDEP315C01(E6) 31.5"  | shipping | — | full-colour 6-primary (ven | **open** | medium |
| 31.2" | Visionect d.o.o. | Visionect Place & Play 32" | shipping | $2,300 | monochrome — 16-level grey | **open** | medium |
| 31.2" | Visionect d.o.o. | Visionect Place & Play 32" Develop | dev-kit | $6,000 | monochrome — 16-level grey | **open** | medium |
| 31.2" | Visionect d.o.o. | Place & Play 32" (31.2" monochrome | shipping | $2,300 | monochrome | **open** | medium |
| 25.3" | DASUNG Tech Co., Ltd. | DASUNG Paperlike Color (Revolution | shipping | $1,698 | Kaleido 3 colour (colour c | **open** | medium |
| 25.3" | DASUNG Tech Co., Ltd. | DASUNG Paperlike 253 (Revolutionar | shipping | $1,549 | monochrome | **open** | medium |
| 25.3" | Bigme (Xinruizhi Technolog | Bigme B251 PRO 25.3" | shipping | $1,349 | Kaleido 3 — 4096 colours + | **open** | medium |
| 75.0" | E Ink Corporation / E Ink  | E Ink Spectra 6 75" module (single | announced | — | full-colour 6-primary (E I | **open** | unknown |
| 31.5" | Dalian Good Display / E In | GDEP315C01(E6) - 31.5" bare panel  | dev-kit | — | full-colour 6-primary (E I | **open** | unknown |
| 28.5" | BLOOMIN8 (arpobot) | EinkCanvas 28.5" (Large) | preorder | $2,399 | full-colour 6-primary (E I | **open** | unknown |
| 25.3" | Dalian Good Display | GDEP253C02(E6) - 25.3" bare panel | dev-kit | $898 | full-colour 6-primary (E I | **open** | unknown |
| 31.5" | PPDS (Philips professional | Philips Tableaux 5150I (32") | shipping | — | full-colour 6-primary (E I | **partly-open** | medium |
| 25.3" | Geniatech | EPC2530 (25.3") / EPC2850 (28.5")  | shipping | — | full-colour 6-primary (E I | **partly-open** | medium |
| 25.3" | Dasung Tech Co., Ltd. | Dasung Paperlike 253 / 253U and Pa | shipping | $1,549 | monochrome or Kaleido 3 | **partly-open** | medium |
| 25.3" | Bigme (brand of Xinruizhi  | Bigme B251 Pro 25.3 colour e-ink m | shipping | $1,349 | Kaleido 3, 4096 colours | **partly-open** | medium |
| 32.0" | PPDS (TP Vision Europe B.V | Philips Tableaux 5150I 32in (and 2 | shipping | — | full-colour 6-primary | **partly-open** | unknown |
| 31.5" | PPDS / TP Vision / MMD (TP | Philips Tableaux 5150I — 32BDL5150 | shipping | — | full-colour 6-primary — 65 | **partly-open** | unknown |
| 31.5" | Dalian Good Display Co., L | DMPH315E62 — 31.5" Spectra 6 finis | shipping | $1,636 | full-colour 6-primary | **partly-open** | unknown |

---

## Recommended development target

**E Ink 25.3" Spectra 6 module** (~$1,400) or **BOOX Mira Pro Color 25.3"** ($1,899).

The reasoning is not "best specs" but "safest bet on both axes at once": E Ink Holdings is the
upstream panel supplier — a publicly listed company (8069.TWO) that every other vendor here depends
on — and Onyx has shipped e-paper hardware for years. Both rate **open** on integration and **high**
on durability, which almost nothing else does. Spectra 6 is genuinely full-colour (6 primaries)
rather than Kaleido's colour-filter overlay, which matters for reproductions.

**Develop against a local-HTTP-push model** with an **SD-card fallback**. That combination is the
common denominator across every open device found, so code written to it survives a change of frame.

### Notable alternatives, and what they cost you

- **BLOOMIN8 EinkCanvas 28.5"** ($2,399, ships Aug 2026) is the *openness* winner: local HTTP REST
  over mDNS, a vendor-published Home Assistant component documenting the endpoints, SD-card path, and
  ~19 third-party GitHub repos including a Node CLI implementing Spectra 6 dithering. But it is a
  Sydney crowdfunding startup on its second product — **durability low**. Good to develop against,
  risky to depend on.
- **Geniatech** (25.3 / 28.5 / 31.5", Android 11, in-house TCON, published API/SDK) is the most
  under-recognised find: a 27-year Shenzhen ODM with its own factory — the rare pairing of credible
  durability with plausible programmability. Its EPC2530 carries the **163 PPI** 25.3" panel, the
  sharpest above 15" anywhere (31.5" panels are only ~93 PPI).
- **Visionect Place & Play 32"** (€2,300) is the openness *yardstick* — self-hosted REST with
  programmatic dithering and bit-depth control — but **monochrome**, so not an answer for paintings.
- **Modos** is the explicit open-hardware trade-off: CERN-OHL schematics and a host API, but a
  two-person company under $1M lifetime funding, and its adapter caps at 13.3". Its docs cover 25.3"
  LVDS panels, so the route exists on paper; treat colour on Spectra 6 as unproven there.

### The dependency nobody escapes

E Ink Holdings is a near-monopoly on the panels. Every frame here is only as durable as E Ink's
decision to keep producing that panel generation. That is the argument for buying *closer* to the
panel supplier, and for keeping the app's renderer decoupled from any one device's API.

---

## The gap this survey could not close

**No vendor at these sizes documents a colour profile, a measured gamut, or ghosting behaviour.**
Only platform marketing figures exist (4,096 colours, ~85% NTSC, ~30:1 contrast, refresh up to ~15 s).
For an archive of paintings that is the single most important unknown, and it will need measurement
on real hardware rather than more research. Budget for it when a device is bought.

Two negative findings worth recording so nobody re-checks them: **Waveshare tops out at 13.3"** and
**Pervasive Displays at 3.4"** — neither is a viable bare-panel route above 15". The real
counterparties there are Good Display / buy-lcd and E Ink's own shopkits store.
