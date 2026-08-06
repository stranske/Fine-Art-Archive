# Large-format e-paper survey — development target

Machine-readable companion: `config/eink_targets.json`.
Raw researcher output: `docs/research/eink/stream-{a,b,c}*.json` (merged by
`scripts/merge_eink_survey.py`, so every claim below traces to a stream).

**Scope:** reflective e-paper, **viewing area larger than 15 inches diagonal**,
shipping or announced. LCD/LED "art frames" (Meural, Samsung Frame, Canvia) are
out of scope by definition — they are not reflective.

**Why this exists:** the owner is deferring E-Ink support for a few months but
wants a target to develop toward now, and wants the research readable during
development rather than buried in a chat log. Two criteria dominate:

1. **Staying power** — will the vendor and the product line still exist in ~3 years?
2. **Integration openness** — can *this* app push images over the local network,
   with no vendor cloud in the path?

**Coverage:** 52 device records (48 above 15"),
67 vendor records, 51 recorded-but-unexhausted
leads, from three parallel researchers (shipping hardware / upcoming + open-hardware /
vendor financials). Citations were link-checked; facts that could not be tied to a
working URL are marked unverified rather than given a guessed source.

---

## Recommended target: Samsung Color E-Paper EM32DX

31.5", Spectra 6, **$1,350**, shipping at mainstream retail.

It is the only device that scores well on *both* decisive criteria at once:

- **Staying power is not in question.** Samsung Electronics, KRW 333.6tn FY2025 revenue.
- **Local, cloud-free push works** — and this is the part vendor documentation hides.
  Samsung publishes only a phone app and a paid cloud CMS, which is why the first
  read of this device was "closed". In fact it answers Samsung's long-standing **MDC
  protocol on TCP 1515**, including content-download commands, with two independent
  open-source clients validated against real hardware: `vgavro/samsung-mdc` (which
  lists EM32DX explicitly) and `WeeJeWel/node-samsung-emdx`, which displays an image
  in a single shell command with no cloud and no Samsung app.
- **Genuine full colour** — Spectra 6 uses six primaries, not Kaleido's colour-filter
  overlay on a mono panel. That distinction matters more for reproductions than any
  spec on the sheet.

**The risk to hold in mind:** the control path is undocumented by Samsung. It is not
a published API, so a firmware update could remove it without that being a breach of
anything. Mitigate by keeping the renderer decoupled from the transport (below).

**Runner-up, if you want a documented path instead of an undocumented one:**
BOOX Mira Pro Color 25.3" at $1,899 — Onyx has shipped e-paper for years and rates
open, but it is a *monitor*: mains-powered, no battery, and it must stay powered to
hold an image. Kaleido 3 colour (4,096 colours via filter array) is visibly weaker
than Spectra 6 for paintings.

### What to build against

**Local HTTP/TCP push, with an SD-card fallback.** That pairing is the common
denominator across every open device found here, so a renderer written to it survives
a change of frame. Keep the image pipeline (dither → palette-map → resize) independent
of the transport; the transport is the part that will change.

---

## Ranked by the two criteria that matter

Openness first, then vendor durability, then size. One row per vendor+size.

| Size | Vendor | Model | Status | Price | Openness | Vendor durability |
|---|---|---|---|---|---|---|
| 31.5" | Samsung Electronics | Samsung Color E-Paper EMDX / EM32DX- | shipping | $1,350 | **open** | high |
| 31.5" | E Ink Holdings | E Ink 31.5" Spectra 6 ePaper Display | shipping | — | **open** | high |
| 25.3" | Onyx International Inc.  | BOOX Mira Pro (Color Version) 25.3" | shipping | $1,899 | **open** | high |
| 31.5" | Dalian Good Display Co., | Good Display GDEP315C01(E6) 31.5" Sp | shipping | — | **open** | medium |
| 31.2" | Visionect d.o.o. | Visionect Place & Play 32" | shipping | $2,300 | **open** | medium |
| 25.3" | Bigme (Xinruizhi Technol | Bigme B251 PRO 25.3" | shipping | $1,349 | **open** | medium |
| 75.0" | E Ink Corporation / E In | E Ink Spectra 6 75" module (single)  | announced | — | **open** | unknown |
| 31.5" | Dalian Good Display / E  | GDEP315C01(E6) - 31.5" bare panel (E | dev-kit | — | **open** | unknown |
| 28.5" | BLOOMIN8 (arpobot) | EinkCanvas 28.5" (Large) | preorder | $2,399 | **open** | unknown |
| 25.3" | Dalian Good Display | GDEP253C02(E6) - 25.3" bare panel | dev-kit | $898 | **open** | unknown |
| 31.5" | PPDS (Philips profession | Philips Tableaux 5150I (32") | shipping | — | **partly-open** | medium |
| 25.3" | DASUNG Tech Co., Ltd. | DASUNG Paperlike Color (Revolutionar | shipping | $1,698 | **partly-open** | medium |
| 25.3" | Geniatech | EPC2530 (25.3") / EPC2850 (28.5") /  | shipping | — | **partly-open** | medium |
| 25.3" | Bigme (brand of Xinruizh | Bigme B251 Pro 25.3 colour e-ink mon | shipping | $1,349 | **partly-open** | medium |
| 32.0" | PPDS (TP Vision Europe B | Philips Tableaux 5150I 32in (and 25i | shipping | — | **partly-open** | unknown |
| 31.5" | PPDS / TP Vision / MMD ( | Philips Tableaux 5150I — 32BDL5150I/ | shipping | — | **partly-open** | unknown |
| 31.5" | Dalian Good Display Co., | DMPH315E62 — 31.5" Spectra 6 finishe | shipping | $1,636 | **partly-open** | unknown |
| 31.5" | SEEKINK (Jiangxi Xingtai | S315E6 Spectra 6 wall-mounted billbo | shipping | — | **partly-open** | unknown |

---

## Corrections — claims that look true and are not

These cost real research time to disprove. They are recorded so nobody re-derives them.

**There is no open-source controller that can drive any e-paper panel over 15".**
The widely repeated "Modos Glider supports 4–42 inch" is a misreading of an appendix
screen list whose own disclaimer says it is *not* a compatibility list; the largest
screen actually tested there is 5.0". The bandwidth arithmetic agrees: a 25.3"
3200×1800 panel needs ~364 MP/s at 60 Hz against Glider's ~224 MP/s ceiling. epdiy
caps at 13.3"; ESPHome at 13.3" mono. **An earlier draft of this survey recommended
Glider plus a 25.3" Spectra 6 panel. That build does not work.** The one viable >15"
self-build is the **QSPI 31.5" panel with Good Display's ESP32-S3 kit** — 25.3" panels
are Mini-LVDS and need a TCON or FPGA in between.

**Visionect is not the openness yardstick it appears to be.** It has the best-documented
push API in the survey (`PUT /backend/{Uuid}`, self-hosted Docker) but its own install
docs state devices "will not be able to operate" without a valid `VSS_LICENSE_ID` —
licence enforcement running on *your* server, reportedly ~$7/month/device. On a
monochrome panel. Both facts disqualify it for this use.

**DASUNG's 25.3" generation cannot hold a picture by itself.** The current models blank
the image after ~5 seconds without a USB heartbeat every 4–5 seconds, so displaying a
painting requires an always-running daemon. Downgraded from open to partly-open.

**Philips Tableaux' "60,000 colours" is marketing.** The real palette is ~8 colours with
device-side dithering. `adb push` into `/storage/emulated/0/Pictures/` is confirmed
working; the documented USB-autoplay route reportedly is not.

**Dead ends at the bare-panel level:** Waveshare tops out at **13.3"**, Pervasive Displays
at **3.4"**. Neither is a route above 15". The real counterparties are Good Display /
buy-lcd, E Ink's own shopkit store, and **Digital View** — founder-owned since 1995, sold
inside E Ink's own store, making TCON boards for E Ink panels from 13.3" to 75". That
last one is the single most useful product here for a self-built frame.

---

## Counterparty risk

**PocketBook is consolidating the category and it is not obvious from the outside.**
It owns InkPoster, acquired IONNYK (2025-09-02), and became co-owner of Bigme
(2024-05-25). Three apparently independent options are one counterparty — concentration
risk dressed as choice. Its Swiss entity is a CHF 100,000 shell with a single
administrator and no accounts on file.

**E Ink Holdings is a near-monopoly that has stranded a panel generation before.**
FY2025 revenue NT$36.1bn, 30% net margin, net cash, capex guided *up* to NT$5–8bn for
2026 specifically to add large-format capacity. So the risk is not that E Ink
disappears. The risk is Gallery 3: over $100M spent, shipped in one size, dropped —
and the Hydis subsidiary, closed in 2015. E Ink also does not sell to individuals,
which is why a cracked panel becomes unobtainable the moment a small frame vendor folds.

**Corporate size does not protect a product line.** Sony shipped the best large-format
e-paper device on the market, then closed the division and deleted the page within
about three years. reMarkable — the only vendor here with audited financials and real
profit — has cut roughly 40% of staff in eight months and carries a NOK 500m bond at
NIBOR+700bp maturing inside the three-year window. The governing precedent is Memento:
~$900 cloud-only frames bricked when the servers were switched off.

**The inversion worth keeping in view:** the most resilient *content architecture* belongs
to the least durable *company*. BLOOMIN8 (six people, no legal entity, eight months late)
loads from SD card with no subscription, so its frames outlive their own vendor. IONNYK
(€12.99/mo catalogue) and SwitchBot (10-image cache, $3.99/mo) are far better funded and
fail the no-cloud test outright. Two options that score best on staying power are signage
rather than frames: **PPDS/Philips Tableaux 32"** (TPV Technology subsidiary) and **LG's
battery-powered 32"**. And **Geniatech** — a 27-year Shenzhen ODM with its own factory,
published API/SDK, and the 163 PPI 25.3" panel, the sharpest above 15" anywhere (31.5"
panels are only ~93 PPI) — is the most under-recognised name in the set.

---

## The gap this survey could not close

**No vendor at these sizes publishes a colour profile, a measured gamut volume, or a
Delta-E figure.** Only platform marketing numbers exist (4,096 colours, ~85% NTSC,
~30:1 contrast, refresh up to ~15 s). For an archive of paintings that is the single
most important unknown, and no amount of further desk research will close it — it needs
measurement on real hardware. Budget for that when a device is bought, and expect to
build a per-device colour profile rather than trusting a vendor number.
