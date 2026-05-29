# Fine-Art-Archive — Code Tab Handoff (2026-05-29)

## Start here
`stranske/Fine-Art-Archive` (public, first-party consumer #13) is the code home for the Fine Art
Archive. Local clone: `Code/Fine-Art-Archive`. Built from `stranske/Template` with the full
Workflows consumer scaffold (auto-pilot, Gate, keepalive).

## Status — bootstrap complete
- Repo created from Template; **26 labels**; **17 Actions secrets** at parity with Manager-Database
  (the two GitHub Apps, four PATs, OpenAI/Claude/LangSmith keys, Codex auth).
- **Registered** as consumer #13 in `stranske/Workflows` — PR #2167 **merged**; sync + auto-pilot active.
- Identity set (README from `consumer_repo_handoff/`, `pyproject` name `fine-art-archive`).
- **Open starter issues:** #2 library+schema+tests (`agents:auto-pilot`), #3 dedup tooling,
  #4 acquisition/verify/quality, #5 FastAPI + Companion App (the latter three `agent:codex`).

## Where the source lives (important)
The reference implementation + design docs are in the **Cowork workspace**
`Dropbox/Pictures/Claude Project` — **not in this repo yet**. The **cloud auto-pilot cannot read that
local folder**, so the "port" issues need a **local agent** (`agent:codex`/`agent:claude` on this Mac)
with filesystem access. What to port (see `consumer_repo_handoff/MANIFEST.md`):
- `src/fine_art_archive/` (sidecar, parsers, collect, display) + `schemas/meta.schema.json` + `tests/`
- dedup tooling: `scripts/perceptual_dedupe.py`, `scripts/visual_dedupe.py`
  (DINOv2 via `transformers`, **manual PIL preprocessing — no torchvision**)
- design docs: `DECISIONS.md` (esp. **D017** dedup cascade) + the `*_design.md` set

## First moves (Code tab)
1. Route **issue #2** to a local agent → port library + schema + tests → green `pr-00-gate`.
2. Once #2 is green, promote #3/#4/#5 to `agents:auto-pilot`.
3. File the source-quality and preference-model issues next (Phase C).

## Next-phase plan
- **A — Foundation:** issues #2–#5 (library, dedup, acquisition, API/app).
- **B — Productionize identity:** wire the D017 cascade (sha256 → pHash → artist-Q-ID block → DINOv2)
  into the acquire path so new acquisitions are dedup-checked before promotion; finish work-Q-IDs.
- **C — Models:** source-quality (ready now, inputs-first) + preference model (after the app's rating loop).
- **D — Companion App + render/display** (E-Ink dithering/gamut; device integration deferred).

## Division of labor
- **This repo / Code tab** = code, CI, models, API/app — auto-pilot builds via issues.
- **Cowork (Mac session)** = operational/data layer: the archive bytes, the daily `fine-art-archive-driver`,
  data enrichment, running dedup on the real files, and the acquisition promotion (G18, in progress
  in Cowork — not the repo's job).

## Facts the agents need
- Archive: **3,301** canonical works in `Dropbox/Pictures/Art/works/`; sidecars in `staging_sidecars/`;
  artist-Q-ID coverage **87%**; schema **0% invalid**.
- Dedup: DINOv2 (`facebook/dinov2-large`, manual PIL preprocessing) separates same-work ≥0.85 from
  different <0.7 — validated on a 29-work batch; the promote/skip verdict is `promotion_dryrun_2026-05-29.csv`
  in the workspace.
- Conventions: Python 3.12+, pytest via the Gate, `@main` reusable workflows, secrets already set.
