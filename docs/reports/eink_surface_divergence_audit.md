# E-ink surface divergence audit

## Provenance

Inspected source: `3c23a10978e1c61151d6856576d56628c8737171`, 2026-10-17.
Source owner: [#805](https://github.com/stranske/Fine-Art-Archive/issues/805).
The original audit was a bounded input inventory and evidence report with no
production changes. The #825 follow-up below documents the selected preview-only
API contract and its regression tests; it changes no selector, image, palette,
archive record or physical device. Other proposals remain report-only under
#805's follow-up publication boundary.

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
| `artists` | C: S/B normalized names | C: same S | C: R IDs | C: same S | B; pipeline artist alias/filter tests |
| `genres` | C: S/B genre predicate | C: same S | C: R IDs | C: same S | B; no separate feed selector |
| `moods` | C: S/B tag/genre predicate | C: same S | C: R IDs | C: same S | B; mood tests |
| `periods` | C: S/B known ranges | C: same S | C: R IDs | C: same S | B; missing-year coverage test |
| `year_from` | B: zero disables date block | B: same B | B: inherited R selection | B: same B | Existing [#806](https://github.com/stranske/Fine-Art-Archive/issues/806), PR820; shared selection defect, not a new divergence |
| `year_to` | B: zero disables date block | B: same B | B: inherited R selection | B: same B | #806; nonzero inclusive comparisons are present |
| `any_tags` | C: union intersection | C: same S | C: R IDs | C: same S | B |
| `all_tags` | C: subset predicate | C: same S | C: R IDs | C: same S | B/U generated family controls |
| `not_tags` | C: disjointness predicate | C: same S | C: R IDs | C: same S | B |
| `exclude_filters` | C: prefix normalization | C: same S | C: R IDs | C: same S | B/U; bare/prefixed-name test |
| `min_fit` | C: rating + missing accounting | C: same S | C: R IDs | C: same S | B; derived-diversity endpoint tests |
| `min_quality` | C: rating + missing accounting | C: same S | C: R IDs | C: same S | B; shared predicate inspected |
| `require_dossier` | C: current dossier IDs | C: same S | C: R IDs | C: same S | S/B; source trace, no claim of per-field endpoint parametrization |
| `selection_mode` | C: ordered/diverse validated | C: same S | C: R IDs | C: same S | [#784](https://github.com/stranske/Fine-Art-Archive/issues/784) closed; real ID agreement executed |
| `limit` | C: B after filtering / Q bound | C: same S | C: R IDs | C: same S | Ordered zero means no truncation; diverse requires positive count. Shared semantics, not newly corrected here |
| `sort` | C: B order before selection | C: same S | C: R order | C: same S | B; seeded and artist ordering controls |
| `seed` | C: B shuffle / Q tie rank | C: same S | C: R order | C: same S | B/Q; seeded selection is deterministic for identical evidence |
| Ratings quality / fit log | C: P reads current log | C: cached by mtime-ns + size | C: R each request | C: same cache as R | `api/main.py:515–524`; snapshot/live distinction below |
| Local master-derived embeddings | C: S derives for filtered candidates | C: same S | C: R each request | C: same S | Missing/unreadable/zero vectors refuse; [#807](https://github.com/stranske/Fine-Art-Archive/issues/807) owns descriptor reuse |
| Caller `quality_scores` | C: P honors explicit values | I: save model has no field | I: R derives server evidence | I: export model has no field | Different IDs are allowed by the preview-only contract selected in #825; P1 below |
| Caller `embeddings` | C: P honors explicit values | I: save model has no field | I: R derives server evidence | I: export model has no field | Explicit empty mappings refuse; preview-only contract in #825; P1 |
| Missing master | C: P reports `has_master=false`; V 404 | C: ordered R omits; diverse validates | C: no advertised missing image | C: writer skips/reports missing image | Intended diagnostic vs playable-output distinction; no byte-parity claim |
| Candidate corpus/metadata | C: current sidecars | C: current sidecars | C: re-resolves live | C: current sidecars | `api/main.py:489–511`; stable snapshot across later calls is I |
| Target key | C: V validates; P only diagnostic target field | C: saved for F | C: target registry | C: inline or saved target | P alone does not validate/produce target pixels; V does |
| Target width/height/rotation | C: V scales dimensions, keeps rotation | I: not a selection input | N: pixels use T, ETag only key | C: native T dimensions | P2 review candidate under [#805](https://github.com/stranske/Fine-Art-Archive/issues/805): same-key registry geometry replacement not in H identity |
| Palette name / actual colors | C: V uses T palette | I: selection does not consume | B: bytes use palette, ETag omits colors | C: T + D palette-conformance assertion | [#808](https://github.com/stranske/Fine-Art-Archive/issues/808); executed changed-bytes/stale-304 probe |
| Palette `measured` | C: V header | I: selection does not consume | B: 200 header changes; old ETag yields 304 without this header | C: manifest/warning records status | #808; executed header probe; physical fidelity remains unverified |
| Master pixels + mtime | C: V reads master; no-store | C: Q descriptor derives master | C: mtime in ETag; N: content identity if mtime preserved | C: D reopens master | P2 review candidate under [#805](https://github.com/stranske/Fine-Art-Archive/issues/805); byte/hash replacement with same mtime not covered by H |
| A11 verdict and chosen strategy | C: P reports; V applies | I: not stored as selection evidence | C: F applies + H includes choice | C: D applies and records written evidence | [#788](https://github.com/stranske/Fine-Art-Archive/issues/788) closed; strategy-change and native-pixel tests executed |
| `fit` / target default | C: V `coerce_fit` | C: saved canonical fit | C: F effective fit in pixels + ETag | C: saved or inline fit | [#786](https://github.com/stranske/Fine-Art-Archive/issues/786) closed; changed-byte and default-equivalence tests executed |
| `dither` | C: V allows none/FS/Atkinson | C: save validates | C: F consumes + H binds | C: D validates/consumes | Shared render T; unsupported names reject |
| Range compression | C: T default true | I: no selection role | C: same T default | C: E uses D default true | API exposes no override; duotone exact endpoints skip compression by design |
| `fast` quantization | C: T default true | I: no selection role | C: same T default | C: E uses D default true | Library-only overrides are I for HTTP; not silently described as UI controls |
| `max_px` | C: V reduced dimensions | I | I: native target pixels | I: native target pixels | Resolution-specific dithering differs; exact thumbnail/card bytes intentionally unsupported |
| `sample` | C: P caps diagnostic rows only | I: no persisted sample | I: full resolved list | I: full selected list | `work_ids` remains complete; do not infer selection size from thumbnail count |
| Saved `playlist_id` | I: preview takes inline spec | C: names stored query | C: retrieves saved query | C: overrides inline spec/target/dither/fit | E/U explicitly select saved feed for card; it is not a frozen membership snapshot |
| `interval`, time and `offset` | I: selection preview not rotating | C: interval validates/stores | C: H clock index; offset only current | I: filename order, not a timer | H; deterministic rotation tests executed |
| Cursor `after` / route index | I | I | C: next wraps; unknown cursor restarts; invalid index 404 | I | F; does not change selection policy |
| Title/artist/year metadata | C: P parses from same sidecars; N: UI year-zero caption | C: R parses | C: manifest/next include | C: D manifest includes | Metadata is outside image ETag; P3 caption review candidate under [#805](https://github.com/stranske/Fine-Art-Archive/issues/805), distinct from #806's date filtering |
| `fmt` | I: PNG response | I | I: PNG response | C: PNG/BMP only; JPEG rejects | D; palette round-trip and lossy refusal tests executed |
| Path, write, overwrite | I | I | I | C: allowed root, dry run, owned-file overwrite, skip failures | E/D; write success evidence differs from dry-run proposal evidence |
| Custom ICC / forced render policy | I: V has no hints payload | I | I: F has no hints payload | I: HTTP export has no hints payload | `render_for_device` supports separate hints; no claim that companion calls it |

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

Additional observations originated as proposals for human review **within #805**.
P1 now has the documentation-and-regression scope selected in #825; P2 and P3
remain proposals, not newly approved repair tasks or published issues:

- **P1 — preview-only explicit evidence.** Direct API callers can preview different
  IDs with explicit quality/embedding maps, then save the same spec and get the
  server-derived IDs. Reproduced: default preview and saved feed select red+blue;
  explicit preview selects near-red+blue. Companion U sends no explicit maps, so
  the UI's normal path is already-correct. The API boundary is intentionally
  unsupported for persistence. The follow-up
  [#825](https://github.com/stranske/Fine-Art-Archive/issues/825) selects the
  preview-only contract: document that caller evidence is transient and that
  selection parity with saved/served playlists or exports is not guaranteed.
  No evidence storage or forwarding change is part of this contract.
- **P2 — broader representation identity (needs-investigation).** H binds target
  key, dither, float master mtime, effective fit, `a11-v1` and strategy. It does
  not bind target dimensions/rotation, palette identity or master content hash.
  #808 covers palette/measurement only. Source inspection establishes missing
  inputs; geometry replacement and preserved-mtime master replacement were not
  executed in this audit and are not claimed as reproduced failures. A proposed
  bounded gate would replace a same-key target or same-mtime master, compare
  unconditional pixels, and require an old validator to return 200 when pixels
  change. Keep this proposal under #805 until separately approved/deduplicated.
- **P3 — zero-year label (needs-investigation).** U renders `i.year || "????"`,
  whereas the server uses integer zero as a valid parsed year. #806 covers date
  filtering, not this caption. Source arithmetic establishes the falsy-zero
  label; a browser interaction was not executed. Proposed gate: render a
  year-zero diagnostic card and assert its caption is `0`, with a missing-year
  control still `????`. No UI edit or new issue is bundled here.

## Preview-only evidence contract (#825 follow-up, 2026-11-05)

Re-read `docs/AGENT_ISSUE_FORMAT.md`, this audit, `PlaylistIn`, `ExportIn`,
`eink_playlist_preview`, `_resolve_playlist`, `eink_playlist_export` and
`_build_eink_playlist` at source commit
`e1a189b` on `codex/issue-825`. **No forwarding-behavior difference** from
the report was found. Before this follow-up, preview forwarding is at
`api/main.py:742–745`, rather than the issue's historical `700–703`;
`_build_eink_playlist` starts at 637, export at 852 and saved resolution at 2122.
The #807 descriptor cache has landed, without changing this evidence boundary.

The contract selected for
[#825](https://github.com/stranske/Fine-Art-Archive/issues/825), following
[#805](https://github.com/stranske/Fine-Art-Archive/issues/805), keeps caller
`quality_scores` and `embeddings` **preview-only** in preference-diverse mode.
Each omitted mapping derives server-owned evidence; an explicitly supplied
mapping, including an empty mapping, is used as supplied and validated. Invalid
empty evidence still returns HTTP 400. Ordered selection does not use these maps.
Saved playlists persist the spec, not caller evidence. Saved/served resolution
and both inline and saved-ID exports call `_build_eink_playlist` without caller
maps, deriving quality from current ratings and embeddings from local masters.
Undeclared evidence fields sent to save or export do not override that path.

Consequently, matching a preview that supplies caller evidence to a saved/served
or exported selection is **not guaranteed**. Without overrides, the same spec
and same server evidence snapshot share selection behavior; later archive,
ratings or master changes can still change a live selection. This is a
documentation contract, not evidence persistence or frozen membership.
`PlaylistIn` field descriptions and both endpoint docstrings expose the
contract in generated OpenAPI documentation; `ExportIn` describes its
server-owned evidence boundary.

`tests/test_eink_feed_endpoints.py::test_preference_diverse_caller_evidence_is_preview_only`
varies quality and embeddings independently against three temporary works.
Server evidence selects red+blue; caller quality selects near-red+blue; caller
embeddings select red+near-red. It checks direct `_resolve_playlist`, served
manifest membership, and inline/saved-ID exports with both dry runs and actual
temporary card writes. Spies wrap the real builder and derivation functions to
verify delivery still derives both server-owned mappings. The existing explicit
empty-evidence regression remains intact. `test_eink_openapi_describes_preview_only_evidence`
checks the generated API documentation.

Validation used the active repository automation interpreter, Python 3.14.10
at `/opt/hostedtoolcache/Python/3.14.10/x64/bin/python`; no `.venv`,
`.faa-venv` or `/opt/anaconda3/bin/python3` is present here. Exact commands,
using the existing sandbox scheduling harness described below:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest -k eink --maxfail=1 -m 'not slow' -o addopts= -q
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_feed_endpoints.py -k 'caller_evidence_is_preview_only or preview_keeps_explicit_evidence or openapi_describes_preview_only' --maxfail=1 -m 'not slow' -o addopts= -q
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
python -m ruff check src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
```

The broad e-ink command passed **308 tests**, with 2259 deselected, in **86.17 s**.
The narrower regression command passed **6 tests**, with 94 deselected, in
**4.83 s** after strengthening served-path assertions. Both runs reported
15 warnings (dependency deprecations and an existing duplicate OpenAPI operation
ID). `-o addopts=` suppresses repository-wide coverage reporting, as in the
prior audit's focused runs. Black and Ruff passed.

For a causal control, temporarily replaced both preview forwarding arguments
with `None` and ran the narrower command with only
`-k caller_evidence_is_preview_only`. It failed as expected in
`test_preference_diverse_caller_evidence_is_preview_only[quality_scores-False]`
at the selected-ID assertion: red+blue instead of near-red+blue (**1 failed**,
96 deselected, **1.12 s**, exit 1). A `finally` block restored the source bytes;
restored SHA-256 was
`1db8397d254c884da3b063378c93ef8687697980c152ac54aad2dc77647a3775`.
The six-test green run above then passed on the restored source.

### Request-schema follow-up (2026-11-05, source `237d676`)

Rechecked the issue-format guide, this audit, the preview/export request models
and all four selection functions. The reported evidence forwarding behavior is
unchanged: caller mappings affect preview only; saved/served resolution and
both export forms derive server-owned evidence. No selection or persistence
change was needed for [#825](https://github.com/stranske/Fine-Art-Archive/issues/825),
following [#805](https://github.com/stranske/Fine-Art-Archive/issues/805).

Expanded the existing `PlaylistIn` model and `spec` descriptions and the
`ExportIn.spec` / `playlist_id` descriptions. Generated API documentation now
states the boundary directly on these request fields, including saved-ID
overrides and the lack of selection-parity guarantees. Preview documentation
also states that ordered mode ignores caller evidence. The OpenAPI regression
now follows each endpoint's actual request-schema reference and checks these
model/field descriptions in addition to the existing endpoint descriptions.

Validation uses the active automation interpreter, Python **3.14.9** at
`/opt/hostedtoolcache/Python/3.14.9/x64/bin/python`. The initial command without
the opt-in harness stalled and was interrupted; the existing harness below
resolves this host's scheduling restriction. No application scheduling code
was changed. Exact focused command:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_feed_endpoints.py -k 'caller_evidence_is_preview_only or preview_keeps_explicit_evidence or openapi_describes_preview_only' --maxfail=1 -m 'not slow' -o addopts= -q
```

Result: **6 passed**, 94 deselected, 15 existing warnings, **4.06 s**.
The unmodified baseline also passed all six tests in 4.09 s. The expanded
OpenAPI assertion initially failed on `ExportIn`'s missing explicit
`preview-only` wording; the model description was corrected before the green
run above. The deterministic selection regressions continue to verify that
caller overrides change preview membership while saved/served resolution and
both export forms derive server-owned evidence.

The broad acceptance command also passed:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest -k eink --maxfail=1 -m 'not slow' -o addopts= -q
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
python -m ruff check src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
```

Results: **308 passed**, 2259 deselected, 15 existing warnings, **71.79 s**;
Black passed with **377 files unchanged**; Ruff and `git diff --check` passed.
As above, `-o addopts=` disables default whole-repository coverage reporting
for these focused regressions.

Verified local task checklist (does not claim publication of these edits):

- [x] Re-read required guidance and selection paths; recorded unchanged forwarding.
- [x] Updated preview/export model and API descriptions; generated OpenAPI regression passes.
- [x] Audit records the preview-only contract, parity consequence, #805 and #825.
- [x] Deterministic preview/saved/served/export evidence regressions pass.
- [x] Broad and narrower e-ink commands pass; exact commands and durations recorded.

Publication remains blocked: staging the three changed files failed with
`fatal: Unable to create .../.git/index.lock: Read-only file system`.
No new commit or push was possible in this run; the verified changes remain
in the workspace. Read-only verification confirmed PR #870 is open with
`draft=false`; its live checklist was not changed.

### Evidence-field validation follow-up (2026-11-05, source `bd1987d`)

Rechecked the request models and all four selection functions for
[#825](https://github.com/stranske/Fine-Art-Archive/issues/825), following
[#805](https://github.com/stranske/Fine-Art-Archive/issues/805). The forwarding
behavior still matches the audit: only preview accepts caller evidence;
saved/served and exported selections derive server-owned evidence. The
preview-only contract and selection-parity warning were already implemented
at this source commit despite unchecked entries in the live work order.

Clarified both preview evidence-field descriptions: omission derives that
mapping independently of its sibling, an explicit empty mapping returns HTTP
400 in preference-diverse mode, and ordered mode ignores the mapping. The
saved-ID export field now also explicitly warns that matching an overridden
preview's selection is not guaranteed. Extended the existing generated-OpenAPI
test and empty-evidence regression; the latter now checks each empty override
with either a supplied sibling or an omitted, server-derived sibling.

Validation used the active automation interpreter, Python **3.14.10** at
`/opt/hostedtoolcache/Python/3.14.10/x64/bin/python`, and the existing optional
scheduling harness. Exact commands:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_feed_endpoints.py -k 'caller_evidence_is_preview_only or preview_keeps_explicit_evidence or openapi_describes_preview_only' --maxfail=1 -m 'not slow' -o addopts= -q
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest -k eink --maxfail=1 -m 'not slow' -o addopts= -q
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --line-length 100 src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
python -m ruff check src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
git diff --check
```

The baseline focused run passed **6 tests** in **5.18 s**. After the changes,
the focused run passed **6 tests**, 94 deselected, in **5.21 s**; the broad run
passed **308 tests**, 2259 deselected, in **87.22 s**. Both reported the same
15 existing warnings. Black's repository-wide check passed with **377 files
unchanged**; Ruff and whitespace checks passed. The initial Black invocation
without the harness/worker setting failed on denied worker socket binding;
the documented configuration above passed.

The implementation and validation tasks remain verified. The required commit
is blocked: `git add src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py`
returned exit 128 because `.git/index.lock` cannot be created on a read-only
filesystem. No commit or push occurred. Read-only GitHub verification confirmed
PR #870 is open and `draft=false`; its live checklist was not modified.
All work stayed in this agent; no work was delegated.

### Request-scoped evidence follow-up (2026-11-05, source `cdcbf48`)

Rechecked the issue-format guide, request schemas and all four selection paths:
the forwarding behavior remains unchanged. The first unchecked documentation
task is already implemented in this checkout. The remaining observable contract
check is that supplying both caller maps changes only that preview request:
a subsequent preview without maps, saved/served resolution and exports must
all use server-owned evidence. The existing focused command below passed
**6 tests**, 94 deselected, in **5.53 s** before changes:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_feed_endpoints.py -k 'caller_evidence_is_preview_only or preview_keeps_explicit_evidence or openapi_describes_preview_only' --maxfail=1 -m 'not slow' -o addopts= -q
```

Clarified the preview model and endpoint descriptions to say overrides apply to
one request, and the export description to explain that live evidence changes
can change membership even without caller overrides. Extended the deterministic
regression to supply both maps together and verify a subsequent preview without
maps returns to server-owned selection. The existing saved/served and both
export paths are exercised for this combined case too. Generated OpenAPI checks
verify the new descriptions.

Validation used Python **3.14.10** at
`/opt/hostedtoolcache/Python/3.14.10/x64/bin/python` with the existing opt-in
harness. The focused command above passed **8 tests**, 94 deselected, in
**8.94 s**. The broad command passed **310 tests**, 2259 deselected, in
**92.57 s**; both reported 15 existing warnings. Exact remaining commands:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest -k eink --maxfail=1 -m 'not slow' -o addopts= -q
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --line-length 100 src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
python -m ruff check src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
git diff --check
```

Black passed with **377 files unchanged**; Ruff and whitespace checks passed.
The implementation and acceptance checks above are verified, but the required
commit remains blocked: `git add` returned exit 128 because `.git/index.lock`
cannot be created on a read-only filesystem. No commit or push occurred.
The requested `needs-human` label and blocker comment were also rejected by
the connector: tool approval is required, but this run's approval policy is
`never`. Read-only verification confirmed PR #870 remains open and ready for
review (`draft=false`). All work stayed in this agent.

### Ignored export fields and task reconciliation (2026-11-05, source `169b9da`)

Reviewed the four implementation commits since bootstrap: their combined
changes touch four files, not the reported 36. Re-read the required guidance,
request models and four selection functions; the forwarding boundary is
unchanged. The baseline focused command below passed **8 tests**, 94 deselected,
in **8.94 s** using Python **3.14.9** at
`/opt/hostedtoolcache/Python/3.14.9/x64/bin/python`.

The remaining documentation clarification is that undeclared caller evidence
sent to export is ignored, including empty mappings. The observable regression
must keep saved/served and both export selections on server-owned evidence even
when those fields would make a preview invalid. This preserves the selected
[#825](https://github.com/stranske/Fine-Art-Archive/issues/825) contract from
[#805](https://github.com/stranske/Fine-Art-Archive/issues/805).

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_feed_endpoints.py -k 'caller_evidence_is_preview_only or preview_keeps_explicit_evidence or openapi_describes_preview_only' --maxfail=1 -m 'not slow' -o addopts= -q
```

The live PR-body reconciliation was rejected by the connector with
`MCP tool call requires approval, but approval policy is never`. Existing
implementation tasks and their duplicated entries are verified locally;
publication of the checklist remains blocked.

After the clarification, the focused command passed **8 tests**, 94 deselected,
in **8.79 s**. The same interpreter and optional scheduling harness ran:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest -k eink --maxfail=1 -m 'not slow' -o addopts= -q
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --line-length 100 src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
python -m ruff check src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
git diff --check
```

The broad run passed **310 tests**, 2259 deselected, in **91.89 s**. Both
pytest runs reported the same 15 existing warnings. Black's repository-wide
check passed with **377 files unchanged**; Ruff and whitespace checks passed.
The focused command remains below two minutes. All five implementation tasks
and four acceptance criteria, including their duplicated entries, are verified
in the local checklist at `agents/codex-825.md`.

Staging the source, test and audit files failed with exit 128:
`.git/index.lock: Read-only file system`. No commit or push was possible.
The connector rejected the requested `needs-human` label and blocker comment
with the same approval-policy error as the PR-body update. All work stayed in
this agent; no work was delegated.

### Evidence placement clarification (2026-11-05, source `724c676`)

Reviewed the five implementation commits since bootstrap; their combined diff
touches four files. The required guide, audit, request models and four selection
functions were re-read. The caller forwarding boundary remains unchanged.
The prior implementation already satisfies the repeated task and acceptance
entries; `agents/codex-825.md` reconciles them locally. The connector rejected
the live PR-body update, blocker comment and `needs-human` label because tool
approval is required but the run's approval policy is `never`.

One remaining ambiguity in the descriptions was corrected: caller evidence
belongs in top-level preview request fields. Top-level export evidence is
ignored; placing either map inside an inline `spec` returns HTTP 400. The old
export spec description's "ignored if supplied here" could imply the opposite.
This clarification preserves the preview-only contract selected in
[#825](https://github.com/stranske/Fine-Art-Archive/issues/825) following
[#805](https://github.com/stranske/Fine-Art-Archive/issues/805). Four endpoint
regressions verify nested-map refusal before the builder runs or output is
written; generated OpenAPI descriptions now state that boundary too.

Using Python **3.14.9** at
`/opt/hostedtoolcache/Python/3.14.9/x64/bin/python` and the existing opt-in
sandbox scheduling harness, the pre-change focused baseline passed **8 tests**
in **7.38 s**. The expanded focused command is:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_feed_endpoints.py -k 'caller_evidence_is_preview_only or caller_evidence_inside_spec or preview_keeps_explicit_evidence or openapi_describes_preview_only' --maxfail=1 -m 'not slow' -o addopts= -q
```

Result: **12 passed**, 94 deselected, 15 existing warnings, **7.41 s**. The
first run caught a case mismatch in the new OpenAPI assertion; after correcting
the assertion, the same command passed. A prematurely started broad run was
cancelled before restarting against the corrected test.

The broad acceptance command and mandatory formatting gate were:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest -k eink --maxfail=1 -m 'not slow' -o addopts= -q
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --line-length 100 src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
python -m ruff check src/fine_art_archive/api/main.py tests/test_eink_feed_endpoints.py
git diff --check
```

The broad run passed **314 tests**, 2259 deselected, 15 existing warnings, in
**77.92 s**. Black passed with **377 files unchanged**; Ruff and whitespace
checks passed. Read-only PR verification confirmed #870 is open with
`draft=false` at source `724c676`.

After validation, staging the four follow-up files failed with exit 128:
`.git/index.lock: Read-only file system`. No current-run commit or push was
possible. This failure applies to this follow-up; the earlier implementations
are already present in the five reviewed runner commits.

## Executed evidence and test layers

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

Historical delivery checklist, verified by that probe and retained receipts
before the UI regression was added:

- [x] Report includes all 17 playlist fields, request-only evidence, render
  defaults, navigation and validator identity.
- [x] Prior repairs and existing owners are linked; P1–P3 remain unpublished
  proposals under #805.
- [x] Temporary-fixture probe, observed JSON and byte-identical production
  break/restore receipts are retained; production code and existing tests are
  unchanged.

This historical checklist does not close #805. The UI gate is now verified
below; remote checklist updates and follow-up publication remain pending.

## Keepalive reconciliation and UI gate (2026-10-17)

Reviewed commits `ee75d23` and `72000af` before continuing. They added this report,
the enumerated 17-field matrix, owned prior repairs, test-layer descriptions and
portable probe receipts. The supplied "40 files" warning does not match these
commits: their combined diff against `3c23a10` contains 13 files, all under
`docs/reports/`. Re-ran the enumeration commands and traced S → B → Q and
V/F/D → T → A. Product-contract references for selection rows are C3/C5,
`docs/PRODUCT_CONTRACT.md:15,17`; pixel-policy and representation rows use C2/C5,
lines 14,17. HTTP-only or export-only controls inherit those same bounded
contracts; I cells explicitly decline cross-surface support claims.

Added `tests/test_eink_pipeline.py::test_ui_preview_save_and_export_carry_the_same_inputs`,
four cases for default fit, contain, cover and stretch. It extracts and executes
the actual `einkSpec`, `einkPreview`, `einkSavePlaylist` and `einkExport` functions
in Node with fixture DOM controls and a recording fetch boundary. It checks
the emitted selection spec (including preference-diverse and limit), target,
dither, canonical/default fit and the rendered thumbnail URL. This is a
**request-policy and generated-URL** check: it does not check backend IDs,
image bytes, HTTP validators, real SD writes or physical panels. Those layers
remain covered only to the extent stated in the table and prior probes.
Node is required; this gate fails rather than silently skipping if unavailable.

The [UI mutation proof](eink_surface_audit/ui-inputs-proof.json) records source
commit `72000af814f558eb241c784d718799d888a53768`, the exact command and hashes:

1. Temporarily replaced the `einkPreview` fit-query producer with
   `const fitQ = "";` in `src/fine_art_archive/ui/index.html`. Save/export still
   sent `cover` while the preview image URL omitted it.
2. Ran the new `[cover]` case: **1 failed**, exit 1, specifically because the
   generated URL lacked `fit=cover`. See [red capture](eink_surface_audit/ui-inputs-red.txt).
3. Restored the original bytes in a `finally` block, then ran the same case:
   **1 passed**, exit 0. See [green capture](eink_surface_audit/ui-inputs-green.txt).
   Original and restored SHA-256 are both
   `d65b9650f582633754b8b8f014dd847d7def95a1e1d02de39fad44484f4f2a52`,
   matching the task's reviewed UI readback. No `src/` change remains.

The [full suite capture](eink_surface_audit/ui-inputs-tests.txt) and proof JSON
record **205 passed**, zero skips/failures/errors, one dependency deprecation
warning, in 66.76 seconds on Python 3.14.8. The four-file pytest command is the
one above, with `-o addopts= -m "not slow"`; original test assertions were not
modified. All four new UI cases passed as part of that run. Black formatted the
changed test and the mandatory repository-wide check passed with **370 files
unchanged**, using the opt-in sandbox scheduling harness described above.

GitHub reconciliation used the read-only connector after the required
`gh issue list --repo stranske/Fine-Art-Archive --search divergence` failed to
connect. The connector's same repository/divergence search found #805 and
unrelated archive issues #523/#407/#188. Direct issue reads confirm #784/#786/#788
closed and #806/#807/#808 open. P2's geometry/content-identity and P3's caption
candidates remain under the existing [#805 review owner](https://github.com/stranske/Fine-Art-Archive/issues/805):
neither #808's palette scope nor #806's filter scope covers those distinct
observations, so neither is falsely claimed as their repair. This is an existing
covering **review candidate**, not a filed dedicated repair or a claim that an
unexecuted investigation has reproduced a bug. P1 is intentionally-unsupported
explicit-evidence persistence and requires no bug issue.

The PR-body update, blocker comment and `needs-human` label were each rejected
by the connector with `MCP tool call requires approval, but approval policy is never`.
Consequently no live task checkbox was updated and no new issue was published.
The issue's separate human-publication boundary also remains recorded above.
The proposed reconciled PR body is retained in
[pr-body-reconciled.md](eink_surface_audit/pr-body-reconciled.md); publication
and the literal successful `gh issue list` acceptance remain unchecked.
Read-only PR verification confirmed #821 is open with `draft=false`.
The proposed checklist has 11 verified items and two pending items (dedicated
follow-up filing and the successful CLI listing). After all checks passed,
the required `git add`/commit attempt failed before staging because `.git` is
mounted read-only: `Unable to create .../.git/index.lock: Read-only file system`.
This iteration therefore leaves reviewable workspace changes, not a new commit.

## Reproducible review checklist

1. Confirm the inspected commit and read S/P/R/E/F/B/Q/V/T/A/D/H/U above. Re-run
   the enumeration commands; compare all 17 spec fields and each request model
   to the matrix, including defaults and saved-ID overrides.
2. Run the four-file pytest command with a real absolute XML destination and
   nonzero collection. Compare test layers above before making a broader claim.
3. Run `python docs/reports/eink_surface_audit/probe.py "$PWD" "$(git rev-parse HEAD)"`
   from this checkout. It uses only temporary fixtures, asserts the existing
   observations, and prints structured evidence. For this historical source,
   palette stale-304 assertions should reproduce; after #808 lands, update the
   audit/probe with new evidence rather than treating historical expectations
   as a permanent product requirement.
4. With Node installed, run the new UI regression with `-m "not slow"` and
   `-o addopts=`. To repeat its causal check, apply only the fit-query mutation
   above, run `[cover]`, restore the source bytes, and rerun the identical case.
   Require the missing-fit assertion to fail and the restored case to pass.
5. Recheck #784/#786/#788 and #806/#807/#808 before proposing work; do not file
   duplicates. Return P1–P3 for review under #805. Do not publish new follow-ups
   without their separate approval.
6. Compare full-size output only with the same master snapshot, target, fit,
   strategy and dither. Thumbnail byte equality, freeze-at-preview membership,
   and physical panel acceptance have not been established by this report.

## Playlist preview target contract (2026-11-05)

Checked on 2026-11-05 while implementing #826. The sections above stay the
historical inventory of inspected commit `3c23a10978e1c61151d6856576d56628c8737171`
and the 2026-10-17 UI gate. In that inventory, the Target key row says preview
only carried a diagnostic target field. That sentence describes the inspected
commit. The current preview contract is the one below.

`PlaylistIn.target` is still accepted, default `gooddisplay-315-diy`.
`eink_playlist_preview` resolves it with `get_target` before selection. An
unknown key returns HTTP 400, including when `sample` is 0. The response keeps
the existing selection fields and adds:

- `target`: the resolved registry key
- `evidence_calibration`: `Spectra-6`
- `evidence_scope`: `master-derived and target-independent`

Per-item `render_strategy`, `render_strategy_reason` and `gamut_verdict` still
come from `render_evidence` on the master. That policy is intentionally
independent of the destination panel (`eink/targets.py` `render_evidence`).
Omitting `target` resolves `gooddisplay-315-diy`. A work with no master stays
`has_master=false` and does not gain fabricated render evidence. `einkPreview`
prints the resolved target and states that strategy/gamut evidence uses
Spectra-6 policy rather than a measurement for the selected panel.

This does not close #805, recalibrate A11, or change selection or rendered
bytes. #806 remains year-zero date filtering, #807 descriptor-cache reuse, and
#808 feed palette validators. None of those owns this preview field.

Interpreter: `/opt/hostedtoolcache/Python/3.14.10/x64/bin/python3`. This host
has no repository virtualenv, and `/opt/anaconda3/bin/python3` is absent.

```sh
python3 -m pytest tests/test_eink_pipeline.py::test_playlist_preview_reports_resolved_target_and_stable_spectra6_evidence -q -o addopts= -m "not slow"
python3 -m pytest tests/test_eink_pipeline.py -q -o addopts= -m "not slow"
```

Outcome 1 focused command: **1 passed**, 14 warnings, 0.83 seconds. The same
temporary-master POST with `gooddisplay-315-diy` and `generic-mono-1bit`
reported each resolved key, `evidence_calibration=Spectra-6`, and
`evidence_scope=master-derived and target-independent`. Selected work IDs and
per-item strategy/gamut evidence were equal. The same test also covers an
omitted target, `sample=0`, and a missing master.

Full file: **136 passed**, 14 warnings, 19.13 seconds. That run includes
`test_playlist_preview_unknown_target_returns_400_including_sample_zero` and
`test_ui_preview_save_and_export_carry_the_same_inputs`, which asserts the
rendered `ek-target-evidence` disclosure.

Validation bypass, then restore. The unknown-target handler was temporarily
changed so a `KeyError` resolved `gooddisplay-315-diy` instead of raising
HTTP 400. The identical command was:

```sh
python3 -m pytest tests/test_eink_pipeline.py::test_playlist_preview_unknown_target_returns_400_including_sample_zero -q -o addopts= -m "not slow" --tb=short
```

Bypassed source SHA-256 `5406cdc604f09e17fb491a4d878dd26a88db982f5942787fdef18945ad541968`:
**1 failed**, exit 1, 0.50 seconds, `assert 200 == 400`. Receipt:
[preview-target-validation-red.txt](eink_surface_audit/preview-target-validation-red.txt).
Restored source SHA-256 `850ce2415ee066ff40ba31c85d2ed45ff50169aae430bf0f119237cccabd8fa9`
matches the pre-bypass file: **1 passed**, exit 0, 0.38 seconds. Receipt:
[preview-target-validation-green.txt](eink_surface_audit/preview-target-validation-green.txt).

`black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
left **377 files unchanged**. Physical panel output was not measured.

## Count contract (#827), checked 2026-11-05

This section labels the missing-master counts already described in the matrix
row "Missing master". It does not change who is selected, which works a feed
may advertise, or which files the writer skips. [#805](https://github.com/stranske/Fine-Art-Archive/issues/805)
remains the audit owner. The earlier deduplication still stands:
[#806](https://github.com/stranske/Fine-Art-Archive/issues/806) is the shared
year-bound filter, [#807](https://github.com/stranske/Fine-Art-Archive/issues/807)
is repeated descriptor work, and
[#808](https://github.com/stranske/Fine-Art-Archive/issues/808) is palette and
measurement identity in the image validator. None of those owns this count
labeling. The original divergence search found no separate covering issue.

The #826 target fields above stay on the preview response. `einkPreview`
prints both the count labels in this section and the `ek-target-evidence`
disclosure. Those are separate sentences.

### Historical line references are not current locations

The issue text cites the feed exclusion as `api/main.py:2101-2104` and the
writer skip as `eink/sdcard.py:185`, from the audit that opened this follow-up.
The anchors earlier in this report belong to inspected commit `3c23a109`:
preview `687–740`, `_resolve_playlist` `2080–2113`, export `809–901`, and
`eink/sdcard.py` `127–296`. Those numbers are historical. The symbols below
are the current producers. Line numbers were re-read on 2026-11-05 after
merging the #826 preview-target changes, which moved the API symbols, and
will drift again.

| Symbol | Where read on 2026-11-05 | Count fields | Missing-master behavior |
|---|---|---|---|
| `eink_playlist_preview` | `api/main.py:791` | `selected` at `:865` is `len(work_ids)`, including works with no master. Sampled `items[].has_master`. `work_ids` is the full selection. `items` stops at `sample` (default 24). | A missing master stays selected and is flagged on a sampled row. It is not removed. |
| `_resolve_playlist` | `api/main.py:2226` | Callers publish `resolved_count` and feed `count` as `len` of the returned list. | `:2249` `if _eink_master(wid) is None: continue`. The feed never advertises the missing master. An empty result still 404s with "no works with local images". |
| `eink_playlist_export` | `api/main.py:945` | Passes every selected id to the writer. Adds `selected` = `len(items)` at `:1034` on top of `ExportReport.as_dict()`. | Does not drop missing masters before the writer. Dry-run render evidence still skips a missing master. |
| `sdcard.export` | `eink/sdcard.py:133` | `written` is accepted names: the plan on a dry run, and files after a successful save on a real write. `skipped` is every skip. `skipped_detail` is the first 20 `(work_id, reason)` pairs. | `:191` missing or absent master: `skipped.append((work_id, "no local master image"))` and no file. Render failures are a different skip reason. |

`selected` therefore means "chosen", on both preview and export. It does not
mean "can be served" and it does not mean "was written".

### Chosen contract

Two totals were not recoverable from the existing payloads:

- Preview can flag `has_master` only on sampled rows. `sample=0`, or a sample
  that happens to contain only works with masters, cannot produce the
  delivery total for the whole selection. Preview now adds
  `available_for_delivery`, the count of `_eink_master(wid) is not None`
  over every selected id. `selected`, `items`, and `has_master` keep their
  meanings.
- Export `skipped` mixes missing masters with render failures, and
  `skipped_detail` stops at 20. Neither is a complete missing-master total.
  `ExportReport.as_dict()` now adds `missing_master_omissions`, the count of
  writer skips whose reason is `no local master image`. `written`, `skipped`,
  `dry_run`, and `selected` keep their meanings.

No further field was added. A feed list is already only the servable works, so
`resolved_count` / `count` are the delivery total and the missing master is
absent from the advertised URLs. Actually written is `0` when `dry_run` is
true and `written` when it is false: a dry run's `written` value is the plan,
including every master the writer would open, and is not a file on disk.

The companion labels those totals directly:

- Preview: `{selected} selected · {available_for_delivery} available for delivery`.
  The older "N shown have no local image" note still describes the sample only.
- Export: `{selected} selected · {actually written} actually written`, plus
  `{n} missing-master omission(s)` from `missing_master_omissions`. A dry run
  also says `would write {written} file(s)`. The existing skipped count and
  estimated-palette note stay.

The UI does not count sampled rows for either total, and it does not treat
`available_for_delivery` or `selected` as proof that a file was written.

### Verification, 2026-11-05

`/opt/anaconda3/bin/python3` is not installed on this host. The interpreter
used is CPython 3.14.10 at
`/opt/hostedtoolcache/Python/3.14.10/x64/bin/python3`.

```sh
/opt/hostedtoolcache/Python/3.14.10/x64/bin/python3 -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
```

Observed: **257 passed**, 14 warnings, exit 0, 61.86 seconds. The extra case is
`test_render_failure_is_not_a_missing_master_or_a_successful_write`: both
master files exist, the writer saves one image, and
`missing_master_omissions` is 0. That is the check that a failed write is
not reported as a missing master and is not counted as written.

UI regression, same interpreter:

```sh
/opt/hostedtoolcache/Python/3.14.10/x64/bin/python3 -m pytest tests/test_eink_pipeline.py::test_ui_count_consumers_do_not_treat_the_sample_as_delivered -q -o addopts= -m 'not slow'
```

The fixture response says `selected=2` and `available_for_delivery=1` while
both sampled rows claim `has_master: true`. The export response says
`written=1`, `dry_run` follows the button, and `missing_master_omissions=1`,
while also carrying a trap `available_for_delivery=2`.

Ambiguous rendering, repeated after the render-failure assertions were added
to the same UI test: the preview label was temporarily changed from
`${d.available_for_delivery}` to `${d.selected}`, so the screen read
`<strong>2</strong> selected · <strong>2</strong> available for delivery`.
The command above exited **1** in 0.44 seconds. The assertion that failed was
`'<strong>1</strong> available for delivery' in preview`. Captured in
[count-contract-red.txt](eink_surface_audit/count-contract-red.txt).

The original `index.html` bytes were restored (SHA-256
`2ce6f914be772753e9b46198b757a47773b40a8f20412d7f1a9074d153678484`
before the edit and after the restore). The same command then exited **0**,
**1 passed**, 13 warnings, 0.36 seconds. Captured in
[count-contract-green.txt](eink_surface_audit/count-contract-green.txt).

Black check, line length 100, excluding `.workflows-lib` and `node_modules`:
**377 files would be left unchanged**.

### Dry-run count follow-up, 2026-11-05

`test_export_dry_run_reports_planned_counts_without_writing` now exercises the
production export route for mixed-master, all-master, all-missing-master and
empty selections. Each runs with `write` omitted and explicitly false. The
eight cases verify selected and planned-written totals, full missing-master
omissions, proposed render-evidence IDs, zero bytes written, zero removals and
an absent output directory. This checks the real response that the UI uses to
distinguish planned files from actually written files; the existing UI test
continues to check the displayed distinction.

On this sandbox, the plain pytest command stalled on the documented asyncio
wakeup restriction and was interrupted. Black's default worker pool failed
with `PermissionError` on socket binding. Using the existing opt-in scheduling
harness and one Black worker, the exact successful commands were:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python3 -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python3 -m pytest tests/test_eink_export_format.py::test_export_dry_run_reports_planned_counts_without_writing tests/test_eink_pipeline.py::test_ui_count_consumers_do_not_treat_the_sample_as_delivered -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/test_eink_export_format.py
```

Interpreter: `/opt/hostedtoolcache/Python/3.14.10/x64/bin/python3`.
The three-suite run passed **279 tests**, 15 warnings, exit 0, in 84.34 seconds.
The new cases plus the UI regression passed **9 tests**, 14 warnings, exit 0,
in 1.15 seconds. Black left **377 files unchanged** and Ruff passed.

The commit attempt failed at `git add`: `.git/index.lock` could not be created
because `.git` is mounted read-only. The requested blocker comment and
`needs-human` label on #827 were also rejected by the GitHub connector:
`MCP tool call requires approval, but approval policy is never`. These changes
remain in the workspace without a commit or a remote status update.

### Same-archive count verification, 2026-11-05

Reconciliation reviewed the implementation and recent follow-ups through
`64bbec9`. PR #874 was open, ready for review, and already had all task and
acceptance checkboxes checked. The mixed-master preview, feed, export and UI
checks passed together (4 tests, 1.47 seconds); no additional task completion
claims were needed.

The earlier surface tests used separate archives. The new parametrized
`test_mixed_master_counts_across_preview_feed_and_export` exercises all three
production paths sequentially against one unchanged archive and specification.
It checks both a missing first master and a missing last master. A one-row
preview therefore samples either the missing or available work, while reporting
selected=2 and available-for-delivery=1 in both cases. The saved feed resolves
one work and its advertised image returns HTTP 200. Export of that saved
playlist writes one decodable 8-by-6 PNG, reports one missing-master omission,
and records the delivered work in the card manifest. Byte counts match the
file on disk. A final preview equals the initial response.

The existing opt-in sandbox scheduling harness was used with the selected
interpreter `/opt/hostedtoolcache/Python/3.14.10/x64/bin/python3`:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python3 -m pytest tests/test_eink_feed_endpoints.py::test_mixed_master_counts_across_preview_feed_and_export -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python3 -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python3 -m pytest tests/test_eink_pipeline.py::test_ui_count_consumers_do_not_treat_the_sample_as_delivered -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/test_eink_feed_endpoints.py
```

Results: the new regression passed **2 tests**, 14 warnings, in 1.70 seconds;
the required three suites passed **281 tests**, 15 warnings, in 83.69 seconds;
the named UI regression passed **1 test**, 13 warnings, in 0.61 seconds. All
commands exited zero. Black left **377 files unchanged**, Ruff passed, and
`git diff --check` passed. The earlier UI mutation's red/green receipts remain
unchanged; neither the UI implementation nor its regression changed this round.

The shared checkout still mounts `.git` read-only, so staging there failed at
`index.lock`. A writable checkout under `/tmp/faa-issue827-counts-review` was
created to preserve this follow-up as a commit and patch. The GitHub connector
rejected the requested PR-body reconciliation update because approval is
required while the run's approval policy is `never`; the existing checked
tasks were left intact.

### Same-archive edge cases, 2026-11-05

Reconciliation through `384b5b6` confirmed that PR #874 was open and ready for
review with every task and acceptance checkbox already checked. No checkbox
changes were needed. The existing mixed-master production-path and UI checks
passed before editing (3 tests, 1.98 seconds).

`test_counts_across_preview_feed_and_export` extends the previous mixed-master
test to all-master, all-missing-master and empty selections. Each case uses one
unchanged archive and specification across preview, saved-feed resolution and
export. It verifies full totals independently of the one-row preview sample,
manifest membership, every advertised image's HTTP 200, and export counts and
byte totals against decoded PNG files on disk. Selections with no deliverable
works retain empty feed manifests, the existing 404 responses and no card
manifest. A final preview must still equal the initial preview.

Using the selected CPython 3.14.10 interpreter and existing opt-in sandbox
scheduling harness, the exact commands were:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python3 -m pytest tests/test_eink_feed_endpoints.py::test_counts_across_preview_feed_and_export -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python3 -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python3 -m pytest tests/test_eink_pipeline.py::test_ui_count_consumers_do_not_treat_the_sample_as_delivered -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --line-length 100 tests/test_eink_feed_endpoints.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/test_eink_feed_endpoints.py
```

Results: the five-case regression passed in 3.45 seconds; the three required
suites passed **284 tests**, 15 warnings, in 87.80 seconds; the named UI test
passed **1 test**, 13 warnings, in 0.54 seconds. Black left **377 files
unchanged**, Ruff passed, and `git diff --check` passed. All commands exited
zero. The UI implementation and its retained mutation-test receipts are
unchanged.

Staging in the shared checkout failed because `.git/index.lock` is on a
read-only filesystem. The verified files were preserved in a writable clone
at `/tmp/faa-issue827-count-edges-20261105` for a local commit and patch; this
does not advance the shared checkout's branch or the remote PR head.
The GitHub connector rejected the blocker comment and `needs-human` label
with `MCP tool call requires approval, but approval policy is never`.

### UI zero-count verification, 2026-11-05

Reconciliation through `f2d6bab` confirmed all 22 task and acceptance checkboxes
were already checked on open, ready-for-review PR #874. Before editing, the
same-archive production-path cases and existing UI regression passed together
(6 tests, 3.81 seconds). No checkbox changes were needed.

The named Node-executed UI regression now covers mixed-master, all-master,
all-missing-master and empty preview totals. Nonempty samples deliberately
claim both masters exist, so a zero delivery total must come from the response
instead of the sample or a fallback to selected. Existing writer-result
assertions still run in every case.

Using CPython 3.14.9 at `/opt/hostedtoolcache/Python/3.14.9/x64/bin/python`
with the existing opt-in sandbox scheduling harness:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py::test_ui_count_consumers_do_not_treat_the_sample_as_delivered -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --line-length 100 tests/test_eink_pipeline.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/test_eink_pipeline.py
```

Temporarily rendering `d.available_for_delivery || d.selected` made the exact
UI command fail only its new all-missing case: **1 failed, 3 passed**, exit 1,
0.59 seconds. It displayed 2 available instead of 0. Byte-identical UI
restoration made the same command pass **4 tests**, exit 0, 0.51 seconds.
Raw outputs remain at `/tmp/eink-ui-zero-count-red.txt` and
`/tmp/eink-ui-zero-count-green.txt` on this runner. The full focused suites
passed **287 tests**, 15 warnings, exit 0, 91.06 seconds. Black left **377
files unchanged**, Ruff passed, and `git diff --check` passed.

The shared `.git` remains read-only; staging failed at `index.lock`. A writable
checkout at `/tmp/faa-issue827-ui-zero-counts` preserves the change as a local
commit and patch without advancing the shared branch or remote PR. Automatic
approval review rejected the PR-body update, blocker comment and `needs-human`
label because connector approval is required and the approval policy is `never`.

### UI export edge counts, 2026-11-05

Reconciliation through `fe47909` found PR #874 open and ready for review, with
all task and acceptance checkboxes already checked; no checkbox edits were
needed. The existing same-archive production-path and UI cases passed before
editing (9 tests, 4.02 seconds).

The named UI regression now exercises write and dry-run results for mixed,
all-master, all-missing-master and empty selections, instead of repeating the
mixed export in every preview case. It asserts explicit selected and written
counts, planned counts for dry runs, and zero, singular and plural omissions.
The separate render-failure payloads still distinguish missing masters from
other skips. Production behavior is unchanged.

Using `/opt/hostedtoolcache/Python/3.14.10/x64/bin/python` and the existing
opt-in sandbox scheduling harness, these commands exited zero:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py::test_ui_count_consumers_do_not_treat_the_sample_as_delivered -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --line-length 100 tests/test_eink_pipeline.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/test_eink_pipeline.py
```

Temporarily changing the export's selected label to `${d.selected || 2}` made
the identical UI command fail its empty case: **1 failed, 3 passed**, exit 1,
0.60 seconds. Byte-identical UI restoration passed **4 tests**, exit 0,
0.49 seconds. Raw receipts are `/tmp/eink-ui-export-zero-red.txt` and
`/tmp/eink-ui-export-zero-green.txt`. The required suites passed **287 tests**,
15 warnings, exit 0, 86.29 seconds. Black left **377 files unchanged**, Ruff
passed, and `git diff --check` passed.

The shared checkout could not stage the change because `.git/index.lock` is
read-only. A writable clone at `/tmp/faa-issue827-ui-export-counts` preserves
the test and audit changes for a local commit and patch; it does not advance
the shared branch or remote PR head.

### Failed-save count verification, 2026-11-05

All supplied checkboxes were already complete at `6559872`; PR #874 was open
and ready for review. Before editing, the same-archive count cases, UI checks
and existing render-failure test passed together (10 tests, 3.72 seconds).

`test_render_failure_is_not_a_missing_master_or_a_successful_write` now tests
both unreadable masters and a card save that writes partial bytes before
raising `OSError`, in both playlist positions. Each production export reports
selected=2, written=1 and missing-master omissions=0. The test checks partial
file cleanup, contiguous numbering, exact successful-image bytes, decoded PNG
dimensions, JSON/M3U membership and render evidence. This verifies actual save
results independently of master availability. Production behavior is unchanged.

Using the selected CPython 3.14.9 interpreter with the existing opt-in sandbox
scheduling harness, these commands exited zero:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_export_format.py::test_render_failure_is_not_a_missing_master_or_a_successful_write -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py::test_ui_count_consumers_do_not_treat_the_sample_as_delivered -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --line-length 100 tests/test_eink_export_format.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/test_eink_export_format.py
```

The expanded failure regression passed **4 tests** in 0.60 seconds; the three
required suites passed **290 tests**, 15 warnings, in 75.34 seconds; the named
UI regression passed **4 tests** in 0.55 seconds. Black left **377 files
unchanged**, Ruff passed, and `git diff --check` passed. The UI implementation
and previous mutation-test receipts are unchanged.

Staging failed because the shared checkout's `.git/index.lock` is read-only.
The verified changes are preserved for a local commit and patch in the writable
clone `/tmp/faa-issue827-partial-save-20261105`; this does not advance the
shared checkout's branch or the remote PR head.

### Production export response in the UI, 2026-11-05

Reconciliation through `71cda28` found every PR #874 task already checked and
the PR open with `draft=false`; no checkbox corrections were needed. The new
`test_ui_export_counts_match_the_production_mixed_master_response` passes an
actual production export response into the production `einkExport` function
using the existing Node UI test mechanism. The isolated two-work fixture writes
one PNG and displays selected=2, actually-written=1 and one missing-master
omission. This closes the API-to-UI validation gap left by constructed payloads.

Using the selected CPython 3.14.10 and existing opt-in scheduling harness:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_export_format.py::test_ui_export_counts_match_the_production_mixed_master_response -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py::test_ui_count_consumers_do_not_treat_the_sample_as_delivered -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
BLACK_NUM_WORKERS=1 black --line-length 100 tests/test_eink_export_format.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/test_eink_export_format.py
```

Temporarily rendering `d.selected` as actually written made the new test fail
in 0.50 seconds; byte-identical UI restoration made the identical command pass
in 0.46 seconds. Receipts are `/tmp/eink-production-ui-counts-red.txt` and
`/tmp/eink-production-ui-counts-green.txt`. The existing UI regression passed
four cases in 0.48 seconds. The required three suites passed **291 tests**, 15
warnings, in 85.35 seconds. Black checked 377 files; Ruff and `git diff --check`
passed.

The plain suite command stalled at the documented sandbox socketpair wakeup
limitation and was interrupted. The scheduling harness is required on this host.
The shared `.git` is read-only (`index.lock` could not be created); a writable
clone at `/tmp/faa-issue827-production-ui-counts` preserves the verified change
as a local commit and patch without advancing the shared or remote branch.
Automatic approval review also rejected the blocker comment and `needs-human`
label: GitHub writes require approval and this run's approval policy is `never`.

### Production preview response in the UI, 2026-11-05

At `49abf18`, all supplied tasks were already checked, and PR #874 was open
with `draft=false`. Before editing, the five same-archive preview/feed/export
cases passed in 3.47 seconds; the existing preview-count and UI tests passed
eight cases in 1.11 seconds. No checkbox changes were needed.

`test_ui_preview_counts_match_the_production_mixed_master_response` now feeds
actual production preview responses into the production `einkPreview` function
using the existing Node mechanism. Its six cases cover sample sizes 0, 1 and
24 with the missing master in either playlist position. Every response and
rendered summary retains selected=2 and available-for-delivery=1, regardless
of sampled rows. It also checks the rendered row count and missing-image
notice. This connects the API response to the UI's count contract; selection,
feed guards and production code are unchanged.

Using CPython 3.14.9 at
`/opt/hostedtoolcache/Python/3.14.9/x64/bin/python`, these commands exited zero:

```sh
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py::test_ui_preview_counts_match_the_production_mixed_master_response -q -o addopts= -m 'not slow'
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" python -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py -q -o addopts= -m 'not slow'
BLACK_NUM_WORKERS=1 black --line-length 100 tests/test_eink_pipeline.py
PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src" BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/test_eink_pipeline.py
git diff --check
```

Temporarily rendering `d.items.filter(i => i.has_master).length` as available
for delivery made the identical UI command fail: **3 failed, 3 passed**, exit
1, 1.11 seconds. Byte-identical UI restoration passed **6 tests**, exit 0,
0.94 seconds. Receipts remain at `/tmp/eink-production-preview-counts-red.txt`
and `/tmp/eink-production-preview-counts-green.txt`. The required suites passed
**297 tests**, 15 warnings, exit 0, 89.95 seconds; their output remains at
`/tmp/eink-production-preview-counts-suites.txt`. Black checked 377 files and
Ruff passed. The Black check without the documented scheduling harness stalled
and was interrupted; the harness-enabled command above passed.

The shared checkout cannot stage changes because `.git/index.lock` is
read-only. The test and audit changes are preserved for a local commit and
patch in `/tmp/faa-issue827-production-preview-counts`; this does not advance
the shared branch or remote PR head.

The local commit succeeded; its apply-ready patch is
`/tmp/eink-production-preview-counts.patch`. Automatic approval review rejected
the blocker comment and `needs-human` label because GitHub writes require
approval and this run's approval policy is `never`.
