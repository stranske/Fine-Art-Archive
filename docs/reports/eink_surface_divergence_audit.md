# E-ink surface divergence audit

## Provenance

- Inspected commit: `667c1558018b7d88d15c003ab0530d286204de4e` (re-verified
  against `41144c7ecd686ce55021c16b92a6e422e87b8b31`; line numbers below are
  at the inspected commit, where the cited functions sit at main.py:688/744/
  810/2080/2123, render.py:235, exhibition.py:57, targets.py:210).
- Companion UI readback: `src/fine_art_archive/ui/index.html` SHA-256
  `d65b9650f582633754b8b8f014dd847d7def95a1e1d02de39fad44484f4f2a52`, matching the
  scope note at `84b50094050db03522a2e80c09617c0cc46cb5e2`.
- Promise under audit: [PRODUCT_CONTRACT.md](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/docs/PRODUCT_CONTRACT.md:8)
  (primary journey: "render e-ink cards/playlist → serve feed") and C2/C3/C5 at
  lines 14–17; [A_SERIES_ROADMAP.md](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/docs/A_SERIES_ROADMAP.md:10)
  (A11 monochrome-first, A15 quality×diversity). The preview must match delivery.
- Enumeration method: `grep -rn` (no `rg` binary in this environment; equivalent
  pattern) over `src/fine_art_archive/api/main.py` and `src/fine_art_archive/eink/`
  for `eink_preview`, `_resolve_playlist`, `_render_feed_image`,
  `eink_playlist_export`, `render_evidence`, `item_etag`, plus reading the
  helpers in `src/fine_art_archive/display/render.py:235`
  (`gamut_render_evidence`) and `src/fine_art_archive/preference/exhibition.py:58`
  (`_validate_inputs` / `select_quality_diverse` at :100). Every matrix edge
  below was verified by reading the cited source, not from search hits alone.
- Surfaces: companion preview = `eink_playlist_preview` (main.py:688) +
  `eink_preview` (main.py:744); saved-playlist resolution = `_resolve_playlist`
  (main.py:2080); feed render = `_render_feed_image` (main.py:2123); SD export =
  `eink_playlist_export` (main.py:810) → `eink/sdcard.py:export` (:127).

## Input-by-surface matrix

Legend: ● consumed, ○ not consumed, — not applicable. Dispositions use only
`already-correct`, `confirmed-bug`, `needs-investigation`,
`intentionally-unsupported`.

| Input | Preview (JSON+img) | _resolve_playlist | Feed image | SD export | Disposition |
|---|---|---|---|---|---|
| `spec.*` filters/sort/seed/limit (`PlaylistSpec`, playlist.py:120) | ● via `_build_eink_playlist` (main.py:696) | ● (main.py:2088) | ● via resolve | ● (main.py:825) | already-correct |
| A15 `selection_mode=preference-diverse` | ● derived evidence when `None` (main.py:611-629) | ● same builder | ● same builder | ● same builder | already-correct |
| Caller `quality_scores`/`embeddings` (PlaylistIn:589) | ● explicit empty stays empty (main.py:605-606,700-703) | ○ always derives (passes `None`) | ○ via resolve | ○ always derives | needs-investigation |
| `ratings`, `dossier_ids` | ● inside builder (main.py:608,634) | ● | ● | ● | already-correct |
| `target` | img ● (main.py:761); JSON ○ (`PlaylistIn.target` unused, main.py:688) | ● `pl.target` (main.py:2130) | ● | ● (main.py:819) | needs-investigation |
| `dither` | img ● (main.py:763,791) | ● `pl.dither` | ● (main.py:2143,2162) | ● (main.py:852) | already-correct |
| `fit` | img ● `coerce_fit` (main.py:762,791); UI forwards `fitQ` (index.html, `ek-fitmode`) | ● `pl.fit` (main.py:2134) | ● incl. ETag (main.py:2145) | ● (main.py:853, sdcard:164) | already-correct |
| A11 `render_strategy` (render.py:235 → targets.py:210) | reported (main.py:727) + applied img (main.py:791) | — | applied + `X-Render-Strategy` + ETag (main.py:2146,2163) | applied + reported (sdcard:198-219, main.py:876) | already-correct |
| Master file / mtime | ● opened (main.py:787) | ● no-master works dropped (main.py:2103) | ● mtime in ETag (main.py:2144) | ● missing skipped (sdcard:184) | already-correct |
| `fmt` (png/bmp, main.py:651) | — PNG only | — | — PNG only | ● lossy refused (sdcard:147) | intentionally-unsupported |
| `max_px` / `sample` | ● presentation only (main.py:749,712) | — | — full size | — full size | intentionally-unsupported |
| `interval` / rotation `offset` | — | ● manifest/current | ● `rotation_index` (feed.py:150) | — static card order | intentionally-unsupported |
| `compress_range` / `fast` | defaults (targets.py:227-228) | — | defaults | defaults (sdcard:136-137) | already-correct |
| Palette / `palette.measured` | header (main.py:803) | — | header (main.py:2179) | manifest (sdcard:261) | already-correct |
| No-master works in counts | `selected` includes them; `has_master` flags (main.py:719) | excluded | 404 if none (main.py:2275) | counted selected, skipped at write (sdcard:185) | needs-investigation |

## Per-instance dispositions

1. **already-correct — the three scope-named defects at this commit.** A15
   evidence is derived inside the one shared builder `_build_eink_playlist`
   (main.py:562-637) used by preview, resolve and export, so it can no longer
   be derived at :635 and omitted downstream. A11 strategy is computed by
   `render_evidence` (targets.py:210, delegating to
   `gamut_render_evidence`, render.py:235) and *applied* by preview
   (main.py:791), feed (main.py:2163) and SD export (sdcard:219), not merely
   reported at main.py:727/876. The feed validator `item_etag` (feed.py:166)
   binds `fit` and `render_strategy` (main.py:2140-2147). Scope line numbers
   (:635/:785/:2042/:2096, targets.py:206) retain their reviewed-commit
   provenance; at the inspected commit these edges are closed. Contract:
   PRODUCT_CONTRACT.md:14-17 (C2/C3/C5).
2. **needs-investigation — caller-supplied A15 evidence is preview-only.**
   Only `eink_playlist_preview` forwards `quality_scores`/`embeddings`
   (main.py:700-703); resolve/export always derive server-owned evidence.
   A playlist previewed with explicit evidence can therefore select
   differently once saved. Owner:
   [#825](https://github.com/stranske/Fine-Art-Archive/issues/825); dedup
   below. Related open candidate
   [#807](https://github.com/stranske/Fine-Art-Archive/issues/807) covers
   descriptor reuse, not this preview-only input.
3. **needs-investigation — `PlaylistIn.target` is accepted and ignored.**
   `eink_playlist_preview` never reads `body.target`; per-item evidence is
   deliberately Spectra-6-calibrated (targets.py:210-218), so this may be
   intentional, but the field invites a false belief. Owner:
   [#826](https://github.com/stranske/Fine-Art-Archive/issues/826).
4. **needs-investigation — count semantics for no-master works differ.**
   Preview `selected` includes them (flagged `has_master`), the feed excludes
   them (main.py:2101-2104, by design so a panel never walks into a 404), and
   export reports `selected` while skipping at write. Each surface is locally
   justified; whether the counts should be reconciled in the UI is undecided.
   Owner: [#827](https://github.com/stranske/Fine-Art-Archive/issues/827).
5. **already-correct — fit/dither/target plumbing.** UI `ek-fitmode` reaches
   preview images (`fitQ`), saved playlists and export bodies (index.html,
   verified by the new regression below); feed coerces `pl.fit or tgt.fit`
   (main.py:2134) and binds the effective fit into the ETag (feed.py:180).
6. **intentionally-unsupported — `fmt`, `max_px`/`sample`, `interval`.**
   Feed/preview always serve PNG at panel or preview size; only the card has
   a file format. Rotation exists only for polling devices. No follow-up.

## What each cited test checks (inspected, not executed here)

| Test file | Layer checked |
|---|---|
| [test_eink_pipeline.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_pipeline.py:55) | IDs + reported policy + image bytes (palette conformance, fit geometry, preview-vs-diverse selection IDs/diagnostics); UI wire strings for `selection_mode` (:914), fit forwarding and dither/target forwarding (new tests below). No HTTP validators, no SD files. |
| [test_eink_feed_endpoints.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_feed_endpoints.py:92) | HTTP validators (ETag/304 on fit and strategy change, :92/:150), image bytes, resolved IDs/counts, rotation. No SD output. |
| [test_eink_export_format.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_export_format.py:33) | SD output: applied strategy with native palette (:33), lossless palette preservation, lossy refusal. No HTTP layer. |
| [test_render_strategy.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_render_strategy.py:14) | Reported policy only: gamut verdict → strategy choice (+ one pixel test :32). No IDs, validators, or SD output. |

## Executed probes (this session, kept separate from inspected tests)

- Baseline: `pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py -m "not slow"`
  → **186 passed** at the inspected commit plus this change (185 before the
  shared-spec regression below; a global 25% coverage gate in config
  reports 14.72% for this subset run; the tests themselves pass).
- New regression `test_operator_ui_forwards_fit_to_preview_images_save_and_export`
  in [test_eink_pipeline.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_pipeline.py:1060):
  **1 passed**.
- Deliberate-break gate: removing `${fitQ}` from the preview `<img>` URL in
  `src/fine_art_archive/ui/index.html` → that test **FAILED** with
  "preview <img> does not forward the chosen fit". Restored via
  `git checkout`; SHA-256 back to `d65b9650…a52`; rerun **1 passed**.
- Follow-on regression (this change)
  `test_operator_ui_forwards_dither_and_target_to_preview_images_save_and_export`
  in [test_eink_pipeline.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_pipeline.py:1091):
  locks the already-correct `dither`/`target` rows of the matrix above —
  both controls are read for the preview `<img>`, playlist save (feed) and
  export (SD). **1 passed** alongside the fit regression (2 passed).
- Deliberate-break gate for it: removing
  `&dither=${encodeURIComponent(dither)}` from the preview `<img>` URL →
  that test **FAILED** with "preview <img> does not forward the chosen
  target/dither". Restored via `git checkout`; SHA-256 back to
  `d65b9650…a52`; rerun **2 passed** (fit + dither/target).
- Follow-on regression (this change)
  `test_operator_ui_forwards_same_spec_to_preview_save_and_export`
  in [test_eink_pipeline.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_pipeline.py:1129):
  locks the `spec.*` row of the matrix above — preview, saved feed and SD
  export all consume the one shared `einkSpec()` builder, and the rotation
  `interval` reaches only the saved feed (the intentionally-unsupported
  asymmetry for preview/export). **1 passed**; no new issue filed, since
  this locks an already-correct row rather than uncovering an instance.
- Deliberate-break gate for it: replacing `spec: einkSpec(),` with
  `spec: {},` in the export body of `index.html` → that test **FAILED**
  with "SD export does not send the shared einkSpec()". Restored via
  `git checkout`; SHA-256 back to `d65b9650…a52`; rerun **3 passed**
  (fit + dither/target + shared-spec). No file under `src/` is touched
  by the committed change.
- Follow-on regression (this change)
  `test_operator_ui_einkspec_forwards_each_spec_control` in
  [test_eink_pipeline.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_pipeline.py:1171):
  locks the builder side of the `spec.*` row — every `ek-*` control
  (`ek-sort`, `ek-artist`, `ek-period`, `.ek-fam`, `ek-mood`, `ek-fit`,
  `ek-limit`, `ek-excl`, `ek-dossier`, `ek-selmode`) populates
  `einkSpec()`, so preview/save/export cannot silently lose an operator
  filter while still agreeing with each other. **1 passed**; no new
  issue filed, since this locks an already-correct row.
- Deliberate-break gate for it: deleting
  `if (v("ek-limit")) spec.limit = parseInt(v("ek-limit"), 10);` from
  `einkSpec()` in `index.html` → that test **FAILED** with
  "einkSpec() does not forward limit (ek-limit)". Restored via
  `git checkout`; SHA-256 back to `d65b9650…a52`; rerun **4 passed**
  (fit + dither/target + shared-spec + einkSpec controls). Full
  re-run `pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py -m "not slow" --no-cov`
  → **187 passed**. No file under `src/` is touched by the committed
  change.
- Follow-on regression (this change)
  `test_operator_ui_forwards_exact_delivery_fields_to_save_and_export`:
  locks exact (not count-based) save/export body fields
  (`target`/`dither`/`fit … || null`, export `path, write, overwrite`)
  and the saved-feed `playlist_id` forwarding
  (`if (einkCardPlaylistId) body.playlist_id = …`, consumed at
  main.py:813) that count-based tests could miss. **1 passed**.
- Deliberate-break gate for it: deleting the `body.playlist_id` line
  from `index.html` → that test **FAILED** with "export does not
  forward the chosen saved feed". Restored via `git checkout`;
  SHA-256 back to `d65b9650…a52`; rerun **5 passed** (all UI
  forwarding regressions). No file under `src/` is touched by the
  committed change.
- Follow-on regression (this change)
  `test_operator_ui_export_write_flag_and_saved_feed_clearing` in
  [test_eink_pipeline.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_pipeline.py:1239):
  locks where the export body's `write` flag comes from (dry run =
  `einkExport(false)`, write card = `einkExport(true)`), the no-path
  guard, and clearing a chosen saved feed via `ek-clear` or on its
  deletion so export cannot send a stale `playlist_id`. **1 passed**;
  no new issue filed, since this locks an already-correct row.
- Deliberate-break gate for it: flipping the dry-run button to
  `einkExport(true)` in `index.html` → that test **FAILED** with
  "dry run must not write the card". Restored via `git checkout`;
  SHA-256 back to `d65b9650…a52`; full re-run
  `pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py -m "not slow" --no-cov`
  → **189 passed**. No file under `src/` is touched by the
  committed change.

- Follow-on regression (this change)
  `test_operator_ui_selection_mode_requires_limit_guard` in
  [test_eink_pipeline.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_pipeline.py:1239):
  locks the operator-facing side of the A15 `selection_mode` row —
  `einkSyncSelectionMode()` disables `preference-diverse` without a
  limit, resets a stale choice to `ordered`, and explains why, mirroring
  the backend `preference-diverse selection requires limit` guard.
  Earlier tests only checked that `selection_mode` exists in the UI.
  **1 passed**; no new issue filed, since this locks an
  already-correct row.
- Deliberate-break gate for it: replacing
  `if (opt) opt.disabled = !hasLimit;` with
  `if (opt) opt.disabled = false;` in `index.html` → that test
  **FAILED** with "preference-diverse must be disabled without a
  limit". Restored via `git checkout`; SHA-256 back to
  `d65b9650…a52`; rerun **2 passed** (guard + fit forwarding). No
  file under `src/` is touched by the committed change.
- Follow-on regression (this change)
  `test_operator_ui_discloses_estimated_palette_on_export`: locks the
  operator-facing side of the `Palette / palette.measured` row —
  `einkExport` appends `colours estimated` only when the export
  response's `palette_measured` is false, so an unmeasured palette
  cannot read as measured. Backend tests already lock the flag in
  the SD manifest; this locks the disclosure. **1 passed**; no new
  issue filed, since this locks an already-correct row.
- Deliberate-break gate for it: replacing `d.palette_measured ? ""`
  with `true ? ""` in `index.html` → that test **FAILED** with
  "export result must disclose 'colours estimated' when
  palette_measured is false". Restored via `git checkout`; SHA-256
  back to `d65b9650…a52`; rerun **2 passed** (palette + fit). No
  file under `src/` is touched by the committed change.
- Follow-on regression (this change)
  `test_operator_ui_discloses_no_master_works_in_preview`: locks the
  operator-facing side of the no-master count row (#827) —
  `einkPreview` counts `!i.has_master` items and appends
  `— N shown have no local image` to the selection header only when
  non-zero, so the preview count cannot read as deliverable works the
  feed excludes and export skips. **1 passed**; no new issue filed,
  since #827 already owns this instance.
- Deliberate-break gate for it: removing
  `${noMaster ? ` — ${noMaster} shown have no local image` : ""}` from
  `index.html` → that test **FAILED** with "preview header does not
  disclose no-master works". Restored via `git checkout`; SHA-256
  back to `d65b9650…a52`; rerun **2 passed** (no-master + fit). No
  file under `src/` is touched by the committed change.
- Follow-on regression (this change)
  `test_operator_ui_discloses_skipped_works_on_export`: locks the
  export-facing side of the no-master count row (#827) —
  `einkExport` appends `· N skipped` only when the export response's
  `skipped` count (sdcard.py:185, :107) is non-zero, so
  `Wrote N file(s)` cannot read as the full selected count.
  **1 passed**; no new issue filed, since #827 already owns this
  instance.
- Deliberate-break gate for it: removing
  `+ (d.skipped ? ` · ${d.skipped} skipped` : "")` from
  `index.html` → that test **FAILED** with "export result does not
  disclose skipped works". Restored via `git checkout`; SHA-256
  back to `d65b9650…a52`; rerun **3 passed** (skipped + no-master +
  fit). No file under `src/` is touched by the committed change.

## Follow-up filing and dedup

- Dedup command run: `gh issue list --repo stranske/Fine-Art-Archive --search divergence`.
  Under the default `GH_TOKEN` (`github-actions[bot]`) that exact command
  returns placeholder rows (`0 … 0001-01-01T00:00:00Z`) in this environment —
  a credential/proxy visibility blocker, not an empty result. Re-run under
  the filing credential (`WORKFLOWS_TOKEN`, `stranske-keepalive[bot]`), the
  exact command succeeds; terminal output:

  ```text
  826  OPEN  eink divergence: playlist preview ignores PlaylistIn.target
  825  OPEN  eink divergence: caller-supplied A15 evidence is preview-only
  827  OPEN  eink divergence: no-master count semantics differ across preview, feed and export
  805  OPEN  Audit and remediate preview-vs-delivery divergence across the companion e-ink surfaces
  ```
- Existing covering candidates: parent
  [#805](https://github.com/stranske/Fine-Art-Archive/issues/805); open
  [PR #821](https://github.com/stranske/Fine-Art-Archive/pull/821) (earlier
  audit attempt on `codex/issue-805-eink-surface-audit`, still open — this
  report is the `muse/issue-805` counterpart, not a duplicate filing);
  [#806](https://github.com/stranske/Fine-Art-Archive/issues/806) (year-zero),
  [#807](https://github.com/stranske/Fine-Art-Archive/issues/807) (descriptor
  cache), [#808](https://github.com/stranske/Fine-Art-Archive/issues/808)
  (feed palette validators) — none covers instances 2–4 above.
- Filed follow-ups (one per needs-investigation instance; the default
  `GH_TOKEN` was refused with `Resource not accessible by integration
  (createIssue)`, so filing used the alternate `WORKFLOWS_TOKEN`
  credential, `stranske-keepalive[bot]`, which has `issues:write`):
  1. Instance 2 — [#825](https://github.com/stranske/Fine-Art-Archive/issues/825)
     "eink divergence: caller-supplied A15 evidence is preview-only"
  2. Instance 3 — [#826](https://github.com/stranske/Fine-Art-Archive/issues/826)
     "eink divergence: playlist preview ignores PlaylistIn.target"
  3. Instance 4 — [#827](https://github.com/stranske/Fine-Art-Archive/issues/827)
     "eink divergence: no-master count semantics differ across preview, feed
     and export"
  Verification: `gh issue view` confirms #825/#826/#827 are OPEN with the
  titles above, and the exact listing command
  `gh issue list --repo stranske/Fine-Art-Archive --search "divergence"`
  (filing credential, see above) lists #826, #825, #827 and parent #805.
  Dedup reasoning is recorded in each issue body: pre-filing searches
  found no covering issue, and #806/#807/#808 were checked as
  non-covering.
- Re-verification at `4d9536f` (shared-`einkSpec()` regression commit):
  the exact listing command above, re-run under the filing credential,
  again returns the same four OPEN rows (#826, #825, #827, parent #805),
  and `gh issue view` for each of #825/#826/#827 again confirms OPEN with
  the titles above. The default-credential placeholder rows were also
  reproduced and are not treated as evidence. In the same session
  `pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py -m "not slow"`
  re-ran to **186 passed**, and the committed diff from the bootstrap
  commit `41144c7` to HEAD touches only this report and
  `tests/test_eink_pipeline.py` — no file under `src/`.

## Reproducible checklist

1. `grep -rn "render_evidence\|item_etag" src/fine_art_archive/api/main.py src/fine_art_archive/eink/`
   and confirm strategy+fit appear at preview, feed and export call sites.
2. `pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py -m "not slow"`.
3. Break/restore probe: delete `${fitQ}` from the preview `<img>` URL in
   `index.html`, rerun the fit-forwarding test (must fail), restore, rerun.
4. No physical-panel acceptance is claimed: palettes are estimates
   (targets.py, `palette.measured` is false) and on-panel colour is unverified.
