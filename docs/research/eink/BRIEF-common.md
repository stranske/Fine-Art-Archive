# Market survey — large-format e-paper displays for a fine-art display app

## Who is asking and why
The client runs a private fine-art archive (3,400 works, gigapixel scans, per-work research
dossiers) with a self-built app that selects, renders and pushes images to a display. He wants to
buy/target a LARGE e-paper frame and needs a survey good enough to (a) pick a development target
now, and (b) keep referring to during development. He has noted "a very large expansion of the
number of firms offering or planning to offer these", so DISCOVER vendors — do not rely on a
remembered shortlist.

## Scope
E-paper / e-ink displays with a **viewing area larger than 15 inches (diagonal)** — both
**currently purchasable** and **announced or in development**. Include colour e-paper (E Ink
Spectra 6, Gallery 3, Kaleido) and monochrome. Include:
- consumer digital art frames
- e-paper computer monitors (they can be driven as a display)
- commercial/signage panels sold in small quantities
- developer kits and open-hardware projects
- bare panels + controller boards, if a determined hobbyist could build a frame from them
EXCLUDE: LCD/LED "art frames" (Meural, Canvia, Samsung Frame) — reflective e-paper only.
EXCLUDE: anything 15 inches or smaller.

## What to report per device — standard evaluation
model · vendor · status (shipping / preorder / announced / dev-kit / discontinued) · diagonal ·
resolution and PPI · panel technology and generation · colour capability and how many colours ·
refresh characteristics · front light · price and currency (note if unavailable) · availability by
region · dimensions and mounting · power (battery vs mains) · release or expected date.

## What to report per device — THE TWO THINGS HE CARES MOST ABOUT

### 1. Staying power (will this product and vendor still exist in 3 years?)
For each VENDOR: corporate form and ownership, country, funding history (rounds, amounts, investors,
dates) or public-company status and financials, revenue scale if disclosed, headcount if findable,
how long they have shipped hardware, whether they have discontinued products or abandoned firmware
before, distributor/retail footprint, and any acquisition/insolvency news. Note E Ink Holdings
(8069.TWO) panel-supply dependence where relevant — a vendor is only as durable as its panel supply.
Give each vendor a **staying-power rating (high / medium / low / unknown)** with the evidence behind
it. Say plainly when a vendor is a one-product startup or a crowdfunding project.

### 2. Personalisation openness (can HIS app drive it?)
This is the decisive criterion. For each device, establish as concretely as you can:
- Is there a **documented API** (local HTTP, MQTT, BLE, USB, serial)? Link the docs.
- Can it be driven **on the local network without a vendor cloud account**? Is a cloud round-trip
  mandatory?
- Does it accept **push** from a self-hosted server, or only pull from the vendor's service?
- Can it run **custom software**? Is it Android-based (sideload an APK)? Linux? Locked firmware?
- **SD card / USB** as a fallback delivery path?
- Is the **firmware open** or the hardware **open-source**? Any published schematics/SDK?
- Is there an active **third-party / homebrew community** (repos, forums) doing this already? Link.
- Does the vendor's ToS or DRM forbid third-party image loading?
Rate **integration openness (open / partly open / closed / unknown)** with evidence.

Also flag anything that matters for ART specifically: colour gamut and accuracy for reproductions,
ghosting on image changes, dithering requirements, bit depth, and whether the vendor documents a
colour profile.

## Rules
- **Every `url` must be one you actually fetched this session.** If you cannot retrieve a working
  URL, still report the fact and set `"url": null` with `"confidence": "unverified"`. NEVER invent a
  URL — output is link-checked automatically and fabricated links are rejected wholesale.
- Prices and availability change; **stamp what you saw and where**.
- Distinguish hard fact from inference. Mark inference as such.
- Where a spec is unknown, write null rather than guessing.
- Prefer vendor documentation and primary filings over review-site summaries; use reviews for
  real-world behaviour (ghosting, colour) that vendors do not publish.

## Output — write a FILE, do not print it
Write raw JSON (no markdown fences) to the path in your assignment:

{
  "devices": [{
     "model": "...", "vendor": "...", "status": "shipping|preorder|announced|dev-kit|discontinued",
     "diagonal_in": 25.3, "resolution": "3200x1800", "ppi": 145,
     "panel": "E Ink Spectra 6", "colour": "full-colour 6-primary|Kaleido 3|monochrome",
     "price": {"amount": 1899, "currency": "USD", "as_of": "2026-08", "source_url": "..."},
     "availability": "...", "power": "...", "dimensions": "...", "released": "2025-03",
     "integration": {"openness": "open|partly-open|closed|unknown",
        "api": "...", "local_network_no_cloud": true, "push_supported": true,
        "custom_software": "...", "sd_or_usb": true, "open_firmware": false,
        "community": "...", "evidence_urls": ["..."], "notes": "..."},
     "art_suitability": {"gamut_notes": "...", "ghosting": "...", "bit_depth": "...",
        "colour_profile_documented": false},
     "sources": [{"url": "...", "what_it_supports": "...", "confidence": "verified|unverified"}]
  }],
  "vendors": [{
     "name": "...", "country": "...", "corporate_form": "...", "ownership": "...",
     "funding": "...", "public_ticker": "...", "revenue_scale": "...", "headcount": "...",
     "hardware_track_record": "...", "abandonment_history": "...",
     "staying_power": "high|medium|low|unknown", "rationale": "...",
     "sources": [{"url": "...", "what_it_supports": "...", "confidence": "..."}]
  }],
  "leads_not_followed": [{"what": "...", "why_promising": "...", "url": "..."}]
}
