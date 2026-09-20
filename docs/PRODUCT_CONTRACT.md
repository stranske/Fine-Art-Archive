# Product contract — stranske/Fine-Art-Archive
_First draft generated 2026-09-20 from the audit scorecard; the repo owns this file from now on. A PR that adds a user-facing route, command or page adds a line here. The audit's Phase 1.5 scores every line below and prints any surface not listed as UNSCORED._

## Purpose
Stage and curate a personal art archive, render selections for e-ink, and serve owner-review and companion display surfaces.

## Primary journey
Stage works and sidecars → build manifest → browse and filter selection → render e-ink cards/playlist → serve feed and review archive health.

## Core functions
| id | a <user> can … and sees … | entry point | probe (how to exercise it; vary these determinants) | status 2026-09-20 |
|---|---|---|---|---|
| C1 | an owner can stage works and sees every valid sidecar as a manifest row and browsable work | manifest CLI; `GET /works` | stage five master/sidecar pairs; build manifest and compare row/work count | WORKS |
| C2 | an owner can render a selected work and sees a panel-sized palette-quantized e-ink image | e-ink card CLI; `GET /works/{id}/eink_preview` | render red vs blue masters and request previews; compare hashes/palette | WORKS |
| C3 | an owner can build a playlist and sees selection and coverage change with filters | e-ink card CLI; `POST /eink/playlist/preview` | compare open-air vs nocturne mood filters; diff work, metadata and rendering | WORKS |
| C4 | an owner can generate weekly review and sees a decision page based on current archive measurements | `scripts/render_weekly_review.py --date DATE` | render supplied 5- vs 2-record weekly payloads; diff claims | BROKEN |
| C5 | an owner can serve companion and feed and sees archive health, works and playable selection | companion script; `/healthz`, `/works`, `/feed/{id}/next` | serve synthetic archive; compare filtered previews and feed result | WORKS |

## Known gaps at draft time
- C4: the renderer has no in-repo producer, documented schema or fixture for `weekly_review_DATE.json` and measures nothing itself, so it cannot generate a current review unaided.
