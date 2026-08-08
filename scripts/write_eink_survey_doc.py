#!/usr/bin/env python3
"""Regenerate docs/EINK_DEVICE_SURVEY.md from config/eink_targets.json.

The first version of the doc was hand-written around a table produced by a
throwaway snippet, and it collapsed rows by (vendor, size) -- which hid real
SKUs rather than duplicates, and left a whole category (consumer art frames)
out of the summary entirely. Generating the tables from the config means the
doc cannot silently disagree with the data again.

Analysis prose stays hand-written here; only the tables are derived.

    python3 scripts/merge_eink_survey.py && python3 scripts/write_eink_survey_doc.py
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "eink_targets.json"
OUT = ROOT / "docs" / "EINK_DEVICE_SURVEY.md"

OPEN_RANK = {"open": 0, "partly-open": 1, "unknown": 2, "closed": 3}
STAY_RANK = {"high": 0, "medium-high": 1, "medium": 2, "unknown": 3, "low": 4}


def dia(x: dict) -> float:
    try:
        return float(x.get("diagonal_in") or 0)
    except (TypeError, ValueError):
        return 0.0


def price(x: dict) -> str:
    p = x.get("price") or {}
    amount = p.get("amount")
    if (
        not isinstance(amount, (int, float))
        or isinstance(amount, bool)
        or not math.isfinite(amount)
    ):
        return "—"
    currency = (p.get("currency") or "USD").upper()
    if currency == "USD":
        return f"${amount:,.0f}"
    return f"{currency} {amount:,.0f}"


def clip(text: str, n: int) -> str:
    """Truncate human-facing table cells on a word boundary."""
    normalized = " ".join((text or "").split())
    if len(normalized) <= n:
        return normalized
    return normalized[:n].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def _merge_mod():
    """Reuse the merge script's brand canonicalisation for the vendor join."""
    path = Path(__file__).resolve().parent / "merge_eink_survey.py"
    spec = importlib.util.spec_from_file_location("mg_doc", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load survey merge helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    d = json.loads(CFG.read_text())
    # Join devices to vendors on the canonical BRAND, not the raw name string.
    # Deduping normalised the device vendor strings, which broke an exact-name
    # join: 26 of 37 devices stopped resolving and 27 table rows fell back to
    # "unknown" durability -- including Samsung's, which is the whole point of
    # the recommendation. Durability is the column this survey exists for, so a
    # silent "unknown" there is worse than no column.
    mg = _merge_mod()
    vendors = {}
    for v in d.get("vendors") or []:
        vendors[v.get("name")] = v
        vendors.setdefault(mg.vendor_key(v), v)
    big = [x for x in d.get("devices") or [] if dia(x) > 15]

    def openness(x: dict) -> str:
        return (x.get("integration") or {}).get("openness") or "unknown"

    def staying(x: dict) -> str:
        v = vendors.get(x.get("vendor")) or vendors.get(mg.brand_of(x)) or {}
        return v.get("staying_power") or "unknown"

    rows = []
    for x in sorted(
        big, key=lambda y: (OPEN_RANK.get(openness(y), 9), STAY_RANK.get(staying(y), 9), -dia(y))
    ):
        rows.append(
            f"| {dia(x):.1f}\" | {clip(x.get('vendor') or '?', 26)} | "
            f"{clip(x.get('model') or '?', 40)} | {x.get('status', '?')} | "
            f"{price(x)} | **{openness(x)}** | {staying(x)} |"
        )
    table = "\n".join(rows)

    dl = d.get("delivery_record") or {}
    # Only >15in campaigns belong in a >15in survey. Modos (13.3in) and
    # MelonFrame (7.3in) were researched to establish the base rate and are
    # discussed in prose, not listed as if they were candidates.
    in_scope = [c for c in (dl.get("campaigns") or []) if (c.get("diagonal_in") or 99) > 15]
    shipped = [c for c in in_scope if c.get("backers_have_units") == "yes"]
    stuck = [c for c in in_scope if c.get("backers_have_units") == "no"]

    def camp_rows(cs: list) -> str:
        out = []
        for c in sorted(cs, key=lambda x: -(x.get("diagonal_in") or 0)):
            promised = clip(c.get("promised_ship") or "—", 26)
            out.append(
                f"| {clip(c.get('name', '?'), 30)} | "
                f"{(c.get('diagonal_in') or '—')}\" | "
                f"{promised} | "
                f"{clip(c.get('current_status', '?'), 84)} |"
            )
        return "\n".join(out)

    ps = d.get("panel_supply") or {}
    alts = [
        p
        for p in (ps.get("panel_makers") or [])
        if p.get("credible_alternative_to_eink") in ("yes", "partial")
        and (p.get("largest_reflective_panel_in") or 0) > 15
    ]
    alt_rows = "\n".join(
        f"| {p.get('name', '?')[:26]} | {p.get('largest_reflective_panel_in')}\" | "
        f"{(p.get('technology') or '?')[:30]} | "
        f"{'own film' if p.get('makes_own_electrophoretic_film') else 'not EPD film'} | "
        f"{p.get('credible_alternative_to_eink')} |"
        for p in sorted(alts, key=lambda x: -(x.get("largest_reflective_panel_in") or 0))
    )

    doc = f"""# Large-format e-paper survey — development target

Machine-readable companion: `config/eink_targets.json`.
Raw researcher output: `docs/research/eink/stream-*.json`, merged by
`scripts/merge_eink_survey.py` (gated by `scripts/test_merge_eink_survey.py`).
This document's tables are generated by `scripts/write_eink_survey_doc.py`, so
they cannot drift from the data.

**Scope:** reflective e-paper, **viewing area larger than 15 inches diagonal**,
shipping or announced. Backlit LCD "art frames" (Meural, Samsung Frame, Canvia,
Aura's 15" Walden) are out of scope by definition.

**Why this exists:** to pick a development target for the archive's display
push, and to stay readable during development. Two criteria dominate:

1. **Staying power** — will the vendor and product line exist in ~3 years?
2. **Integration openness** — can this app push images over the local network,
   with no vendor cloud in the path?

**Coverage:** {len(d.get('devices') or [])} device records ({len(big)} above 15"),
{len(d.get('vendors') or [])} vendors, {len(d.get('leads_not_followed') or [])} recorded
leads, from {len(d.get('_streams') or {})} researcher streams across three rounds.

---

## Read this before the recommendation

**Someone with a real 28.5" colour unit in hand reports that photographs look
"dark, desaturated, and low resolution."** The panel cannot render pure white —
only "a yellowish grey" — and a refresh takes about a minute. **Monochrome
reproductions fared markedly better than colour.** That is a reviewer's hands-on
account of an InkPoster Tela 28.5", and it is the only independent colour
assessment anyone has produced at this size.

No vendor at these sizes publishes a colour profile, a gamut volume, or a
Delta-E figure — only platform marketing (4,096 or 16.7M colours, ~85% NTSC,
~30:1 contrast). For an archive of paintings this is the decisive unknown, and
it will not be closed by more desk research.

**So the honest recommendation is: buy one unit and measure it before
committing the display pipeline to colour e-paper at all.** Everything below
assumes that test passes.

---

## Recommended target: Samsung Color E-Paper EM32DX

31.5", Spectra 6, **$1,350**, shipping at mainstream retail. It remains the only
device scoring well on *both* decisive criteria at once.

- **Staying power is not in question** — Samsung Electronics, KRW 333.6tn FY2025.
- **Local cloud-free push works, though the vendor hides it.** Samsung documents
  only a phone app and a paid cloud CMS. In fact the display answers Samsung's
  MDC protocol on **TCP 1515** including content-download commands, with two
  open-source clients validated against real hardware.
- **Genuine six-primary colour** rather than a filter overlay.

**The risk:** that path is undocumented, so firmware could remove it. Mitigate
architecturally — build to **local push with an SD-card fallback**, the common
denominator across every open device here, and keep the renderer decoupled from
the transport.

### The three serious alternatives, and what each costs

**Fraimic Large Canvas 31.5" — $1,299, shipped, and genuinely documented.**
Backers posted receipts on the public campaign wall on 4–5 August 2026.

An earlier draft here called its local API "a marketing claim, not a documented
one". That was wrong, and the correction matters: **Fraimic's own GitHub
organisation publishes a REST API guide** — "No internet required for local
communication. No account needed." — covering `GET /api/info`, refresh, sleep,
restart and direct artwork upload, with no authentication. The same org
publishes **`fraimic_bin_converter`** under MIT, which packs an image into the
exact 4-bit indexed format the panel expects (960,000 bytes at 1200×1600 for the
EL133UF1). So Fraimic, not only BLOOMIN8, accepts pre-dithered data. Its README
independently confirms this survey's colour finding, quantising with "a metric
tuned for the muted, real-world colours of Spectra 6" rather than naive RGB.
Eight public repos exist including two Home Assistant integrations and a
third-party ESP32-S3 reimplementation. Caveat: the converter targets the 13.3"
panel; whether the 31.5" uses the same path is unconfirmed. Against it: the list
price rose ~30% from the announced $999;
both SKUs currently show sold out; and delivery ran ~3 months late.

**BLOOMIN8 EinkCanvas 28.5" — the best-documented local control surface in the
survey, from its least durable vendor.** They publish an `openapi.yaml` under
MIT: an unauthenticated LAN REST API with `/upload`, gallery and playlist CRUD,
and `/image/dataUpload` for **pre-dithered raw data** — the only vendor that
lets you supply your own dithering, which on a 6-ink panel likely matters more
for colour fidelity than any ppi difference. There is also a documented pull
mode where the device wakes on a schedule, calls *your* server, and displays
what it returns, with no vendor cloud in the loop. But: the 28.5" was promised
**October 2025** and no backer has one; arpobot has launched a second campaign
while ~600 Large pledges from April 2025 remain unfilled. Because the control
surface is MIT-licensed and published, vendor death degrades to a warranty
problem rather than a brick — which is the argument for treating its low
durability rating as less disqualifying than it looks.

**InkPoster Tela 28.5" — the best image quality above 15", and fully closed.**
2160×3060 at 132 ppi in portrait 3:4: roughly 40% denser than every 31.5"
option and a far better aspect ratio for paintings. On general retail since
Nov–Dec 2025. But no local path at all, and it is the unit whose colour the
reviewer above found poor.

**SwitchBot AI Art Frame 31.5" — the strongest company, disqualified on the
second criterion.** Its parent OneRobotics listed on HKEX (6600) in December
2025 raising ~US$206M, reached ~US$3bn market cap, and turned profitable in
H1 2025. Nothing else in the frame category is close. But the image path is
cloud-mandatory: `uploadImage` exists, and routes through `api.switch-bot.com`
with an account token. The open question worth chasing is whether it also
exposes undocumented local HTTP — if it does, the strongest vendor becomes the
strongest pick outright.

---

## Every device above 15 inches

Sorted by openness, then vendor durability, then size.

| Size | Vendor | Model | Status | Price | Openness | Durability |
|---|---|---|---|---|---|---|
{table}

---

## Has anything actually shipped?

Yes — this was tested directly, because the earlier draft implied the open
options were vapour.

**Delivered, units confirmed in owners' hands:**

| Campaign / product | Size | Promised | Status |
|---|---|---|---|
{camp_rows(shipped) or "| _(none recorded)_ | | | |"}

**Funded or announced, no >15" unit delivered:**

| Campaign / product | Size | Promised | Status |
|---|---|---|---|
{camp_rows(stuck) or "| _(none recorded)_ | | | |"}

**The pattern is that the size slips, not the vendor.** BLOOMIN8 and InkJoy both
shipped their 7.3"/10"/13.3" SKUs and both are stuck on the big panel.

**Regular communication is not a safety signal.** Galari took $339,557 from 737
backers, funded March 2025 for a September delivery, and still has no panel
supplier, is redesigning its PCB, and has conceded its demo prototype was a
Raspberry Pi driving off-the-shelf Waveshare modules. Refunds refused. It posts
monthly updates.

---

## Is E Ink really a monopoly? Partly.

This was briefed as an attempt to **refute** the claim, because it carries the
whole counterparty argument. Verdict: **{ps.get('monopoly_claim_verdict', 'unknown')}**.

**What survives.** For multi-pigment *colour* electrophoretic film — what a
colour art frame needs — every large-format alternative collapses into E Ink's
supply chain. E Ink's own filings name BOE, DKE, Seekink, Innolux, Qingyue and
Yes Optoelectronics as **module** partners supplied with E Ink colour film. BOE,
the most-cited challenger, co-founded E Ink's trade alliance and holds ~40% of
the ESL *module* market while buying E Ink film. LG's 32" unit is an E Ink
Spectra 6 panel. Tianma is at 6.7" prototypes; CLEARink never shipped.

**Correction from round 3:** an earlier version of this document said the AUO
arrangement was "still only a term sheet". The partnership itself is confirmed —
E Ink pages name ADP as a partner — but the ownership split, Taoyuan site, and
"mass production since Q4 2025" claim remain in `unverified_facts` (press
summaries only; the JV announcement itself was not fetched). Treat those
figures as reported, not established. It comes with a warning attached:
StellarLink's 31.5" aecoPost is ADP-built, so an unknown number of apparently
independent 31.5" brands are one production line under different logos.

**What breaks it — two genuine second sources above 15":**

| Maker | Largest | Technology | Film | Alternative? |
|---|---|---|---|---|
{alt_rows or "| _(none found)_ | | | | |"}

**Guangzhou OED** makes its own microcapsule film on its own IP (175 granted
patents), survived E Ink's 2012–15 patent suit, and put a **31.2" colour panel
into mass production in March 2025** — larger than any single E Ink Spectra 6
panel. **ChLCD is structurally free of E Ink entirely**, running on ordinary LCD
lines: IRIS Optronics ships a 31.5" bistable full-colour ChLCD with sub-second
refresh, and Anhui Yutu's ePaint offers 28" and 32".

**The finding that most changes the advice isn't about competition.** E Ink's
own annual report calls 2025 "the First Year of Large-Size ePaper" and concedes
that since 1992 it has "consistently focused on the research and manufacturing
of small-size displays." The largest single Spectra 6 panel is **31.5"**; the
75" is **six tiled modules with visible seams**. So "buy close to the panel
supplier" buys proximity to a product line the supplier itself started last year.

---

## Counterparty risk

**PocketBook is the category, and it isn't visible from outside.** InkPoster is
not a partner of PocketBook — inkposter.com names "Pocketbook International SA"
as the entity. IONNYK was acquired (Sept 2025) and Bigme co-owned (2024). Four
apparently independent options are one counterparty. Its Swiss entity is a
CHF 100,000 shell with one administrator and no accounts on file.

**Corporate size does not protect a product line.** Sony shipped the best
large-format e-paper device on the market, then closed the division and deleted
the page within about three years. reMarkable — the only vendor here with
audited financials and real profit — has cut ~40% of staff in eight months and
carries a bond maturing inside the three-year window.

---

## Round 3 — what a discovery-first sweep added

Rounds 1 and 2 briefed researchers with vendor NAMES, so they largely re-found
what was already known. Round 3 started from search vocabulary instead — English
"poster"/signage terms, Chinese and Japanese manufacturer searches, the retail
ESL industry, community/DIY surfaces, Korean, and application verticals. The
new-to-known ratio ran from 3:2 to 17:1, which says the earlier ~33-vendor
picture was a sampling artifact rather than a small field.

**The strongest architectural finds, all new:**

- **CREA** (Japan) is the standout. Its **EPS 42"** monochrome (2160×2880, 16
  grey) has **HDMI in, RJ-45, USB host and an SD slot**, with documented
  standalone-slideshow and FTP auto-update modes — a self-hosted app can drive it
  with no vendor account at all. HDMI on a 42" e-paper panel means an ordinary
  computer drives it. Its **EPS s-color 31.5"** (Spectra 6, 1440×2560) is the
  colour sibling and takes a scheduled slideshow from a **microSD card**, cloud
  optional. CREA sells single units and lends evaluation units for two weeks.
- **Advantech** — 28.6" Spectra 6 at 3060×2160, USB carousel plus Ethernet and
  Wi-Fi, and `DeviceOn/ePaper` **installs on your own Ubuntu server**. Industrial
  vendor, single units, real datasheets.
- **Sharp ePoster** (EP-C251, 25.3" colour) loads purely from a **USB-C
  thumbdrive** — the cleanest offline path from a tier-1 manufacturer.
- **ADLAB** (Taiwan, found only via its Korean-language site) — 31.2" mono and
  13.3" colour running **stock Linux** with USB-A host, RJ45, IP65 and removable
  micro-SD system storage. Update path undocumented; one email would settle it.
- **AUO Display Plus AecoPost 31.5" *Mobile*** — Spectra 6, pushed from a phone
  over WiFi or Bluetooth. AUO sells a separate "Cloud Model", which is itself
  evidence the Mobile SKU needs none.
- **Frame Labs** — the frame **pulls from an image-server URL you set**, with an
  open-source server library, so there is no vendor server to switch off.

**Artwork actually on e-paper — one real precedent.** Cloud8 Blanc installed a
31.5" **CREA EPS s-color** in 2025 at a facility devoted to the late
illustrator Minoru Nagao, showing illustration posters. That is a colour e-paper
panel doing this exact job. (The other cases found — DAZZLE's 2,100-tile facade
at San Diego airport, the BMW i5 Flow NOSTOKANA carrying Esther Mahlangu's
Ndebele patterns — use E Ink Prism, which is segmented film, not an image
display.) Artec Design's 650-display PoE installation at the Estonian National
Museum remains the closest institutional analogue.

**A ceiling worth planning around.** 42" is the largest SINGLE panel; everything
above (75", 102") is tiled. And above 32" the colour is **Kaleido 3**, a
colour-filter array with weak saturation. **Artwork-capable colour (Spectra 6)
tops out at about 31.5–32" in shipping product.**

**Price floor, with a caveat.** Roughly fifteen Chinese suppliers accept MOQ 1,
including a 25.3" colour poster at USD 390–430 against $1,400 for E Ink's own
module. But essentially none of them document how an image gets onto the screen
— that silence is the finding. Several marketplace figures came via an AI
aggregator that demonstrably misclassifies (it listed a 4K Android LCD as
e-paper), so that tier is leads to verify, not quotes.

**Two hypotheses disconfirmed, recorded so nobody re-runs them.** The ESL majors
do NOT have large poster lines: VusionGroup stops at 12.2" e-paper and goes LCD
above; Hanshow tops out ~7.5". Only SOLUM fit the hypothesis. And there is **no
hidden Korean manufacturer tier** at ≥13" — thirteen Korean queries converged on
Samsung, LG and SOLUM. The Korean sweep still paid for itself by finding ADLAB
and a real street price for the Samsung 32" (₩1,710,000 against ₩2,390,000 list).

**Where the remaining tail is.** Saturation was reached in every stream, but on
the *reachable* web. Blocked or gated: Touch Taiwan's 101-partner exhibitor list,
every Alibaba/1688 product page, and Reddit (refused on every fetch — genuinely
unsampled, not saturated). The ePaper Industry Alliance directory turned out to
publish **52 members, not the 260+ assumed**; the remaining ~208 sit behind
registration, which is an account decision rather than a research one.

---

## Corrections — claims that look true and are not

Recorded so nobody re-derives them. Several were errors in earlier drafts of
this document.

- **No open-source controller drives any e-paper panel over 15".** "Modos Glider
  supports 4–42 inch" misreads an appendix screen list whose own disclaimer says
  it is not a compatibility list; largest tested is 5.0", and a 25.3" panel needs
  ~364 MP/s against Glider's ~224 MP/s ceiling. **An earlier draft here
  recommended Glider plus a 25.3" Spectra 6 panel. That build does not work.**
- **Aura Ink is 13.3", one size, $499** — out of scope, and cloud-only besides.
  It was this round's highest-priority target and it does not qualify.
- **IONNYK publishes frame dimensions, not screen sizes.** Jane is a 13.2"
  display, Linn ~31.2", Maxine ~40.2". An earlier draft listed "62 inch", which
  is Maxine's *frame* diagonal. Corrected in the config with provenance.
- **E Ink did not abandon Gallery 3.** reMarkable Paper Pro ships an 11.8"
  Gallery 3 panel and E Ink shipped an upgraded version in 2024. The ">$100M
  written off" figure is single-sourced. A cleaner precedent for consolidation
  is E Ink's 2012 acquisition of **SiPix**, its only real EPD rival.
- **Hydis (closed 2015) was an LCD business**, not e-paper.
- **Memento was not an e-paper frame** (35" 4K emissive). The bricking is
  verified — cite it as the cloud-dependency precedent, not an e-paper one.
- **MelonFrame is 7.3" only** and never belonged in a >15" list.
- **Visionect** gates operation on a licence ID enforced on *your* server,
  ~$7/month/device, on a monochrome panel.
- **DASUNG's 25.3"** blanks after ~5s without a USB heartbeat — it needs a
  daemon just to hold a picture.
- **Philips Tableaux' "60,000 colours"** is ~8 with device-side dithering.
- **Brands that reach you through ADVERTISING rather than search** were checked
  on 2026-08-07 after the owner reported seeing them promoted. Recorded so they
  are not re-investigated: **Muse** (museframe.io) is a backlit LCD frame for
  digital-art collectors — 4K, 1200:1 contrast, video playback; **Atmoph** is a
  27" FHD backlit LCD video-window with speakers and an ~$11/mo view
  subscription, confirmed by its CEO ("the LCD panel is FHD"); **Displate**
  sells physical steel prints, and even its powered "Lumino" line is fixed
  licensed art with OLED strips laminated in and no image input. All three are
  out of scope on technology, not on merit.
  **Inkanva** and **Jitrainno** ARE genuine Spectra 6, and both are unlaunched:
  each has a "Launching soon" Kickstarter that has never run and a creator
  profile reading "First created / 0 backed". Inkanva is anonymous — no legal
  entity, names or address — while already collecting $20 pre-launch deposits,
  and its headline perovskite self-charging covers only the 7.09" and 13.3"
  models, not the 28.5" flagship. Jitrainno is more substantial (named Hong Kong
  entity, four named leads, a published iOS app, a documented offline
  Bluetooth+hotspot binding mode with no vendor cloud) but is phone-app-only:
  no API, no SD card, no LAN endpoint.
  **The methodological point matters more than the five verdicts.** Advertising
  is not surfacing a class of vendor that search misses. It is surfacing
  pre-revenue crowdfunding entities that buy attention *because* organic search
  cannot rank them — no press, no retail, no live campaign. The two genuinely
  shipping large-format options reachable today rank on page one of a plain
  query. Treat an ad-sourced name as a pre-launch risk signal, not as a lead the
  research missed.
- **Dead ends:** Waveshare caps at 13.3", Pervasive Displays at 3.4". The real
  bare-panel counterparties are Good Display, E Ink's own shopkit store, and
  **Digital View** (founder-owned since 1995, TCON boards 13.3"–75").

## Sourcing

Every URL in the raw streams was fetched by the researcher that cited it; facts
that could not be tied to a live source carry `url: null` and sit in
`unverified_facts` rather than being given a guessed citation. Two claims that
arrived via search summaries and appear fabricated — a "BOE e-paper division
called Morispace", and a CLEARink executive transition that is actually a
different company's — are recorded as unverified rather than repeated. This
discipline exists because an early researcher fabricated 17 of 30 URLs, caught
by link-checking.
"""
    OUT.write_text(doc)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(doc):,} chars)")
    print(f'  {len(big)} devices >15" in table')
    print(f"  delivered: {len(shipped)}   stuck: {len(stuck)}")
    print(f'  alternative panel makers >15": {len(alts)}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
