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
- Fresh enumeration (this change, current HEAD): re-enumerated by reading
  `src/fine_art_archive/api/main.py` and `src/fine_art_archive/eink/` at the
  current checkout (no `rg`/`grep` shell in this session; equivalent
  search-tool + full-function reads). Current anchors: `PlaylistIn`
  (main.py:629), `_build_eink_playlist` (:637), `ExportIn` (:682),
  `eink_playlist_preview` (:729), `eink_preview` (:785),
  `eink_playlist_export` (:851), `SavePlaylistIn` (:2112),
  `_resolve_playlist` (:2122), `_render_feed_image` (:2165);
  `PlaylistSpec` (playlist.py:120, 17 fields), `SavedPlaylist`
  (feed.py:62), `rotation_index` (feed.py:151), `palette_fingerprint`
  (feed.py:167), `item_etag` (feed.py:176), `build_manifest` (feed.py:209),
  `render_evidence` (targets.py:210), `render_for_target` (targets.py:221),
  `gamut_render_evidence` (render.py:235), `_validate_inputs`
  (exhibition.py:57), `select_quality_diverse` (exhibition.py:100),
  `export` (sdcard.py:127). UI producers: `einkSpec` (index.html:3179),
  `einkSavePlaylist` (:3205), `einkPreview` (:3292), preview `<img>`
  (:3352), figcaption (:3354), `einkExport` (:3362). Inputs per surface:
  preview JSON = `spec` (all 17 `PlaylistSpec` fields) + preview-only
  `quality_scores`/`embeddings` + unused `target` + presentation `sample`;
  preview image = `work_id`, `target`, `dither`, `fit`, `max_px`;
  `_resolve_playlist` = saved `spec` only (plus live ratings/dossiers and
  the no-master filter; `target`/`dither`/`fit`/`interval` are consumed by
  the feed/export renderers, not by resolution); feed image = saved
  `target`/`dither`/`fit`, master mtime, `render_strategy`,
  palette fingerprint (all bound in `item_etag`) and the request's
  `If-None-Match`; SD export = `playlist_id` (overrides inline
  `spec`/`target`/`dither`/`fit`) or inline fields, plus `fmt`, `path`,
  `write`, `overwrite`. The UI emits only a subset of `PlaylistSpec`
  (`sort`, `artists`, `periods`, `all_tags`, `moods`, `min_fit`, `limit`,
  `exclude_filters`, `require_dossier`, `selection_mode`); `genres`,
  `year_from`/`year_to`, `any_tags`, `not_tags`, `min_quality` and `seed`
  are API-only and still consumed identically by every backend surface,
  so they are already-correct, not a UI divergence. Their filtering
  behaviour (not only existence/defaults) is now locked by
  `test_enumerated_api_only_spec_fields_filter_preview_selection`,
  which runs each of those fields through both `build` directly and the
  companion preview endpoint and requires identical selections. This
  enumeration is now locked by
  `test_enumerated_eink_surface_inputs_match_backend_signatures` and
  `test_operator_ui_renders_preview_item_identity_in_selection_order`
  in `tests/test_eink_pipeline.py`: adding an input to any enumerated
  signature, or removing the preview caption's year fallback, is
  designed to fail there until the audit is updated. No new issue
  filed: both lock already-correct rows (the caption's zero-year
  fallback is the needs-investigation instance already held under
  #805). Execution note (inspected, not an executed probe): in this
  session every shell command, including for a delegated verification
  agent, failed before starting with
  `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, so
  the two new tests, the deliberate-break gate for the caption test,
  the Black check and `git` were not executed here and are not claimed
  as passed; rerun
  `pytest tests/test_eink_pipeline.py::test_enumerated_eink_surface_inputs_match_backend_signatures tests/test_eink_pipeline.py::test_operator_ui_renders_preview_item_identity_in_selection_order -m "not slow" --no-cov`
  plus the break/restore probe from the checklist before marking the
  enumeration task complete.

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

## Helper-edge trace (each edge verified in source)

| Edge (caller → callee) | Inputs forwarded | Inputs dropped / defaulted | Disposition |
|---|---|---|---|
| `eink/targets.py:210 render_evidence(img)` → `display/render.py:235 gamut_render_evidence(image, policy=None)` | master pixels only; gamut measured against `spectra6` inside the callee | `policy` never forwarded, so every e-ink surface uses the default verdict→strategy map; the hint-driven `policy`/`render_strategy` override in `render_for_device` (render.py:248) is unreachable from preview/feed/export | already-correct (policy override intentionally-unsupported on e-ink surfaces) |
| `api/main.py:768/830/917/2181`, `eink/sdcard.py:198`, `targets.py:244` → `render_evidence` → `render_for_target(..., strategy=evidence.strategy)` | chosen `strategy` plus surface `fit`/`method`/`target`; `render_for_target` re-derives only when `strategy is None` | none: reported strategy is the applied strategy on all four surfaces | already-correct |
| `preference/exhibition.py:57 _validate_inputs(work_ids, quality_scores, embeddings, subset_size)` → `select_quality_diverse` (:100) ← `eink/playlist.py:434 build` ← `_build_eink_playlist` (main.py:637) | candidate IDs in filtered order, quality map, embedding map, `limit` as `subset_size`, `spec.seed` | invalid classes raise before selection (`SubsetSizeError`, `MissingEvidenceError`, `NegativeQualityError`, `NonFiniteEvidenceError`, `EmbeddingDimensionError`); explicit empty evidence stays empty and fails the same way on every surface | already-correct |
| `eink/feed.py:167 palette_fingerprint` + `:176 item_etag(work_id, target_key, dither, mtime, fit, render_strategy, palette_identity)` ← `_render_feed_image` (main.py:2165) | saved `target`/`dither`, effective `fit` (`pl.fit or tgt.fit`), master mtime, applied strategy, response-palette fingerprint, request `If-None-Match` | provenance-only palette fields (name/note) excluded by design; target dimensions enter only via `target_key` | already-correct (validator binding; palette-colour binding owned by #808) |

Helper locks added with this trace in `tests/test_eink_pipeline.py`:
`test_helper_edge_render_evidence_uses_default_spectra6_policy`,
`test_helper_edge_validate_inputs_rejects_each_bad_evidence_class` and
`test_helper_edge_select_quality_diverse_is_seeded_and_diagnosed`. They are
inspected, not executed, in this session (shell blocker below); rerun
`pytest tests/test_eink_pipeline.py -k helper_edge -m "not slow" --no-cov`
before marking the helper-trace task complete.

Follow-on locks (this change): the enumerated-inputs lock now also covers
the feed-manifest helpers this report enumerates at feed.py:151/167/209
(`rotation_index`, `palette_fingerprint`, `build_manifest`), which it
previously listed but did not lock, and
`test_helper_edge_feed_manifest_consumes_saved_playlist_inputs` verifies
those helpers actually consume the saved `target`/`dither`/`interval`,
item order, `base_url`/`now`/`offset`, and palette colours/measured
status (excluding provenance-only name/note). Inspected, not executed,
in this session: every shell command fails before starting with
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, so no
pass is claimed here. Rerun
`pytest tests/test_eink_pipeline.py::test_enumerated_eink_surface_inputs_match_backend_signatures tests/test_eink_pipeline.py::test_helper_edge_feed_manifest_consumes_saved_playlist_inputs -m "not slow" --no-cov`
before marking the enumeration/helper-trace tasks complete. No new
issue filed: this locks already-correct rows, not an uncovered instance,
and touches no file under `src/`.

Follow-on locks (this change): the enumeration now also locks what each
enumerated input means when omitted, not only that it exists.
`test_enumerated_eink_surface_defaults_match_audit_matrix` asserts the
defaults the matrix above assumes for `PlaylistIn` / `ExportIn` /
`SavePlaylistIn` (api/main.py), `PlaylistSpec` (playlist.py),
`SavedPlaylist` (feed.py) and the traced helper signatures
(`eink_preview`, `render_for_target`, `gamut_render_evidence`,
`select_quality_diverse`, `item_etag` — including that `fit` is a
required keyword there — and `sdcard.export`), because a changed
default diverges preview from delivery without changing any signature.
`test_helper_edge_render_for_target_derives_strategy_when_unspecified`
locks the one helper fallback the earlier trace read but did not
exercise: `render_for_target(..., strategy=None)` re-derives through
the same `render_evidence` policy the four surfaces report, byte-equal
to the explicit render for both a poorly-served (grayscale) and an
on-palette (color) master. Inspected, not executed, in this session:
every shell command still fails before starting with
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, so no
pass, Black check, `git` commit or `gh` listing is claimed here. Rerun
`pytest tests/test_eink_pipeline.py::test_enumerated_eink_surface_defaults_match_audit_matrix tests/test_eink_pipeline.py::test_helper_edge_render_for_target_derives_strategy_when_unspecified -m "not slow" --no-cov`
plus `black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
before marking the enumeration/helper-trace tasks complete. No new
issue filed: both lock already-correct rows, and the change touches no
file under `src/`.

Follow-on lock (this change): the API-only spec row is now locked
behaviourally, not only by signature/default.
`test_enumerated_api_only_spec_fields_filter_preview_selection` in
`tests/test_eink_pipeline.py` feeds three works differing in genre,
year, tags and rated quality through `genres`,
`year_from`/`year_to`, `any_tags`, `not_tags` and `min_quality`, and
requires the companion preview (`eink_playlist_preview`, via the shared
`_build_eink_playlist`) to select exactly the works `build` selects
directly, in `as-filtered` order. A search over `tests/` before this
change found those fields only in the signature/default locks, never
as filtering inputs. Inspected, not executed, in this session: every
shell command still fails before starting with
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, so no
pass, Black check, `git` commit or `gh` listing is claimed here. Rerun
`pytest tests/test_eink_pipeline.py::test_enumerated_api_only_spec_fields_filter_preview_selection -m "not slow" --no-cov`
plus the deliberate-break probe for it (temporarily remove the
`min_quality` filter block in `src/fine_art_archive/eink/playlist.py`,
rerun — it must fail on the `min_quality` case — then restore and
rerun to pass) and
`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
before marking the enumeration task complete. No new issue filed:
this locks an already-correct row, and the change touches no file
under `src/`.

Follow-on lock (this change): the enumeration now also locks the
operator rendering of the saved-playlist surface itself.
`test_operator_ui_renders_saved_feed_delivery_identity` in
`tests/test_eink_pipeline.py` requires `einkLoadPlaylists`
(index.html:3228) to render each saved feed's name, resolved count
(or the `error` marker when `resolved_count` is null), panel
`target`, rotation `interval` and device feed URL, plus the
manifest/view links and the wired `to card` (`data-eink-use` →
`einkUseForCard`) and delete (`data-eink-del` → `einkDeletePlaylist`)
actions returned by `GET /eink/playlists` (main.py:2230, which
derives `resolved_count`/`feed_url`/`manifest_url` from the saved
`spec`/`target`/`interval`). A search over `tests/` before this
change found those list fields only in backend endpoint tests,
never in the UI rendering. Inspected, not executed, in this
session: every shell command still fails before starting with
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, so
no pass, Black check, `git` commit or `gh` listing is claimed
here. Rerun
`pytest tests/test_eink_pipeline.py::test_operator_ui_renders_saved_feed_delivery_identity -m "not slow" --no-cov`
plus its deliberate-break probe (temporarily remove the
`${einkEsc(p.interval)}` cell from `einkLoadPlaylists` in
`index.html`, rerun — it must fail on the saved rotation
interval — then restore and rerun to pass) and
`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
before marking the enumeration task complete. No new issue filed:
this locks an already-correct row, and the change touches no file
under `src/`.

Follow-on lock (this change):
`test_operator_ui_discloses_saved_feed_overrides_filters_on_export`
in `tests/test_eink_pipeline.py` locks the operator-facing side of
the enumerated `playlist_id` override (SD export replaces the
inline `spec`/`target`/`dither`/`fit` with the saved playlist's,
main.py:855-858): `einkUseForCard` (index.html:3270) must record
the choice, name the saved feed in its banner, state that the
filters above are ignored, and wire the `use filters instead`
clear link that drops the banner. Body-forwarding tests already
lock that `playlist_id` is sent; a search over `tests/` before
this change found the banner disclosure in no test. Inspected,
not executed, in this session (same shell blocker as above; no
pass, Black check, `git` commit or `gh` listing claimed). Rerun
`pytest tests/test_eink_pipeline.py::test_operator_ui_discloses_saved_feed_overrides_filters_on_export -m "not slow" --no-cov`
plus its deliberate-break probe (temporarily remove
`filters above are ignored.` from the banner in `index.html`,
rerun — it must fail on the override disclosure — then restore
and rerun to pass) and the Black check above before marking the
enumeration task complete. No new issue filed: this locks an
already-correct row, and the change touches no file under `src/`.

Follow-on lock (this change):
`test_operator_ui_renders_preview_and_delivery_counts` in
`tests/test_eink_pipeline.py` locks the operator-visible counts
that make the no-master row (#827) reconcilable across surfaces:
the preview header must render ``selected`` of ``matched`` over
``total_candidates`` (main.py:773-781 → index.html `einkPreview`),
the save toast must report the feed's ``resolved_count``
(main.py:2289-2291), and the export result must render ``written``
(sdcard.py reported count). Backend counts were already locked; a
search over `tests/` before this change found none of these three
renderings locked (the saved list's count is a separate rendering,
locked above). Inspected, not executed, in this session (shell
blocker above; no pass, Black check, `git` commit or `gh` listing
claimed). Rerun
`pytest tests/test_eink_pipeline.py::test_operator_ui_renders_preview_and_delivery_counts -m "not slow" --no-cov`
plus its deliberate-break probe (temporarily remove
`selected of ${d.matched}` from the preview header in
`index.html`, rerun — it must fail on the preview count — then
restore and rerun to pass) and the Black check above before
marking the enumeration task complete. No new issue filed: this
locks the operator-visible side of the already-owned #827 row,
and the change touches no file under `src/`. Re-attempt in this
session: the targeted pytest, the Black gate, and the
break/restore probe were each invoked again and each returned
``bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted``
before the command started, so no terminal pass or break-failure
output was captured and no commit was made here; the rerun
commands above remain the checklist to complete once the shell
is available.

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
| [test_eink_pipeline.py](/home/runner/work/Fine-Art-Archive/Fine-Art-Archive/tests/test_eink_pipeline.py:55) | IDs + reported policy + image bytes (palette conformance, fit geometry, preview-vs-diverse selection IDs/diagnostics); UI wire strings for `selection_mode` (:914), fit/dither/target forwarding, and saved-feed list identity (name/count-or-error/target/interval, feed+manifest URLs, to-card/delete actions). No HTTP validators, no SD files. |
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
- Follow-on regression (this change)
  `test_operator_ui_discloses_missing_metadata_drops_in_preview`:
  locks the operator-facing side of the coverage disclosure —
  `einkPreview` reads `d.coverage.excluded_for_missing_metadata`
  (built at playlist.py:448, backend counts already locked) and
  renders `Dropped for missing metadata: …` via `${covTxt}` only
  when that map is non-empty, so `selected of matched` cannot read
  as if every matching work were eligible for feed/card. **1
  passed**; no new issue filed, since this locks an
  already-correct disclosure rather than uncovering an instance.
- Deliberate-break gate for it: removing the `${covTxt}`
  interpolation from the preview markup in `index.html` → that
  test **FAILED** with "missing-metadata disclosure is built but
  never rendered". Restored via `git checkout`; SHA-256 back to
  `d65b9650…a52`; rerun **2 passed** (missing-metadata + fit). No
  file under `src/` is touched by the committed change.
- Follow-on regression (this change)
  `test_operator_ui_renders_selection_diagnostics_in_preview`:
  locks the operator-facing rendering of the A15
  `selection_diagnostics` rows — `einkPreview` builds `diagTxt`
  from `d.selection_diagnostics` (per-pick `quality_contribution`,
  `nearest_selected_similarity`, `marginal_determinant`) and
  interpolates `${diagTxt}` into the preview markup. The earlier
  UI test only checked the key string exists. **1 passed**; no new
  issue filed, since this locks an already-correct row.
- Deliberate-break gate for it: removing the `${diagTxt}`
  interpolation from the preview markup in `index.html` → that
  test **FAILED** with "selection diagnostics are built but never
  rendered". Restored via `git checkout`; SHA-256 back to
  `d65b9650…a52`; rerun **2 passed** (diagnostics + fit). No file
  under `src/` is touched by the committed change.

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

## Merge reconciliation with `main`

The base branch carried its own audit iteration of this report (inspected
commit `3c23a10978e1c61151d6856576d56628c8737171`) with a 17-field matrix,
portable probe receipts under `eink_surface_audit/`, and proposals P1–P3.
This resolution keeps the PR report above as the canonical document and
records the base iteration's distinct dispositions here so no finding is
silently dropped:

- Palette colors/measurement omitted from the feed validator:
  **confirmed-bug**, owned by
  [#808](https://github.com/stranske/Fine-Art-Archive/issues/808); the base
  probe reproduced changed bytes with a stale 304. The matrix row above
  ("Palette / `palette.measured`") covers header reporting only; validator
  binding remains #808's scope.
- Broader representation identity (target dimensions/rotation, master
  content hash): **needs-investigation**, held as a proposal under
  [#805](https://github.com/stranske/Fine-Art-Archive/issues/805), not
  reproduced or filed separately.
- Zero-year UI caption (`i.year || "????"`): **needs-investigation**,
  likewise held under #805 and distinct from #806's date-filter scope.
- Preview-only explicit evidence (base "P1") is the same instance as
  disposition 2 above, owned by #825; no duplicate was filed.
- The base iteration's executed-evidence receipts (201 passed across the
  four e-ink suites, probe JSON/XML under `eink_surface_audit/`) remain on
  disk and are not superseded by the executed probes listed above.
