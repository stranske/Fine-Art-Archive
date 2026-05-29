# Fine-Art-Archive — Next-Phase Development Plan (2026-05-29)

## Where we are
- **Repo bootstrapped:** `stranske/Fine-Art-Archive` (public, from Template), registered as
  first-party consumer #13 (Workflows#2167), 26 labels, 17 secrets at parity with Manager-Database.
- **Archive data** (Cowork workspace, `Dropbox/Pictures/Claude Project`): 3,301 canonical works;
  artist-Q-ID coverage 87%; **0% schema-invalid**; the **D017 dedup cascade** is built + validated
  (DINOv2 separates same-work ≥0.85 from different <0.7; 29-work verdict produced).
- **Decisions of record:** `DECISIONS.md` through D017.

## Division of labor (important)
- **Cowork (this Mac session)** owns the **operational / data layer**: the archive bytes, the
  scheduled `fine-art-archive-driver`, data enrichment/backfills, running the dedup cascade on the
  *real files*, and promotions into `Art/works/`. **Stays here.**
- **Code tab (Claude Code + Workflows auto-pilot)** owns the **code**: the importable library, CI,
  the API/app, the models — built in the repo via issues. **Next phase moves here.**
- They meet at the data boundary: repo code operates on the workspace data; verdicts/ratings flow
  between. Note: the **cloud auto-pilot cannot read the local workspace**, so "port from workspace"
  issues need a **local** agent (`agent:claude`/`agent:codex` on the Mac).

## Phase A — Land the foundation (issues #2–#5) [Code tab]
1. **#2 Port library + schema + tests** — foundational; local agent. Goal: green `pr-00-gate`.
2. **#3 Port the D017 dedup cascade** — `perceptual_dedupe.py` + `visual_dedupe.py` (DINOv2, manual
   PIL preprocessing, no torchvision).
3. **#4 Port acquisition + verify/quality pipeline** — `collect/sources/*`, `verify.py`, `quality.py`.
4. **#5 FastAPI service + Companion App skeleton.**

Sequence: #2 → green CI → promote #3/#4/#5 to `agents:auto-pilot`.

## Phase B — Productionize identity + dedup
- Wire D017 into the acquire path: every new acquisition is dedup-checked
  (sha256 → pHash → artist-Q-ID block → DINOv2) against the archive **before** promotion — replacing
  the name/size guessing that started this.
- Finish the Q-ID work (the "other elements"): work-Q-ID + Wikidata metadata (genre/depicts/date)
  backfill. Offline-first from `enrichment_cache.json`; Wikidata tail via the driver.
- Promote the validated-new staged works (the 29-batch verdict) into `Art/works/` — operationally
  from Cowork under a **G18** grant, informed by the repo's dedup.

## Phase C — The two unfinished `path_forward` items
- **Source-quality model:** start inputs-only (per-source verify/aspect/dim/link-health →
  `config/source_quality.yaml`), then acquisition routing. **Ready to start now.**
- **Preference model:** needs rating data → ship the Companion App rating loop first, then learn the
  preference vector (online logistic regression over CLIP embeddings × ratings). **Gated on the app.**

## Phase D — Companion App + display
- Build out the Companion App (Focus mode, two-axis rating, queues, depth-ladder) per
  `companion_app_design.md`.
- Render pipeline (dither/gamut/Spectra6) for E-Ink; device integration deferred (SD-card fallback ok).

## Immediate next actions (Code tab)
1. ✅ Merge Workflows#2167 (registration + doc refresh).
2. Open the Code tab on `stranske/Fine-Art-Archive`; route **issue #2** to a local agent → land the
   library + green CI.
3. Promote #3/#4/#5 to `agents:auto-pilot` once #2 is green.
4. File the source-quality and preference-model issues when ready.

## What stays in Cowork
The scheduled driver (now daily), the artist-Q-ID Wikidata tail, running the dedup on real files, the
29-work promotion (G18), and the photography-category migration that folds personal photos into the
canonical scheme.
