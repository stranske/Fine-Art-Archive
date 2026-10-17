# E-ink preview and delivery input audit

Inspected source: `3c23a10978e1c61151d6856576d56628c8737171`, 2026-10-17.
Source owner: [#805](https://github.com/stranske/Fine-Art-Archive/issues/805).
This is a bounded input inventory and evidence report. It changes no production
code, selector, image, palette, archive record or physical device. New proposals
below remain report-only under #805's follow-up publication boundary.

## Contract and enumeration

[Product contract](../PRODUCT_CONTRACT.md#primary-journey), lines 7–17 at the
inspected commit, connects selection, rendering, cards and playable feeds (C2,
C3, C5). [A-series roadmap](../A_SERIES_ROADMAP.md#stage-a--actionable-from-measured-wave-6-inputs)
links A11 strategy and A15 selection; its Stage C requires physical measurement.
Those promises do not establish byte equality between different resolutions,
different evidence snapshots or unmeasured panel output.

Enumeration used these commands, followed by reading each callee and caller:

```sh
rg -n 'class (PlaylistIn|ExportIn|SavePlaylistIn)|def (_build_eink_playlist|eink_playlist_preview|eink_preview|eink_playlist_export|_resolve_playlist|_render_feed_image|feed_)' src/fine_art_archive/api/main.py
rg -n 'class PlaylistSpec|def (build|render_for_target|render_evidence|item_etag|export|select_quality_diverse|gamut_render_evidence)' src/fine_art_archive/eink src/fine_art_archive/preference/exhibition.py src/fine_art_archive/display/render.py
rg -n 'function eink(Spec|Preview|SavePlaylist|Export|UseForCard)' src/fine_art_archive/ui/index.html
```

The inventory covers all 17 `PlaylistSpec` fields, request-only evidence,
archive-derived evidence, render arguments/defaults, saved-playlist overrides,
feed navigation and image-validator inputs. Scope excludes manifest health,
transport/firmware, physical panel measurements and unrelated display clients.
`display/render.py::render_for_device` is traced as a sibling helper, not
mistaken for the companion endpoint's pixel renderer.

### Source anchors (line numbers at the inspected commit)

| Key | Producer / consumer edge |
|---|---|
| S | `api/main.py:595–636`, `_build_eink_playlist`: filter candidates before deriving missing quality/embeddings, then call `eink.playlist.build` |
| P | `api/main.py:582–592,687–740`, `PlaylistIn` / `eink_playlist_preview`: explicit evidence vs absent evidence, diagnostics and sampled rows |
| R | `api/main.py:2080–2113`, `_resolve_playlist`: same builder, current ratings, then omit missing masters |
| E | `api/main.py:639–653,809–901`, `ExportIn` / `eink_playlist_export`: saved ID overrides spec/target/dither/fit; writer supplies delivered evidence |
| F | `api/main.py:2123–2181,2255–2318`, image renderer and four feed routes |
| B | `eink/playlist.py:120–159,293–460`, complete spec, AND filters, ordering, limit and selection diagnostics |
| Q | `preference/exhibition.py:57–97,100–161`, finite/dimension/nonzero/missing-evidence validation and seeded selection |
| V | `api/main.py:743–806`, per-work preview: select strategy from master, scale target, decode and render |
| T | `eink/targets.py:38–74,163–267`, target geometry, fit, strategy, range compression and quantization |
| A | `display/render.py:235–245`, `eink/render_strategy.py:10–44`, master-derived Spectra-6 gamut verdict → color/duotone/grayscale |
| D | `eink/sdcard.py:127–296`, format/safety validation, master lookup, actual render, palette guard, manifest and files |
| H | `eink/feed.py:150–225`, rotation, ETag and live manifest |
| U | `ui/index.html:3187–3227,3261–3283,3295–3390`, form spec, saved-card selection, preview image URL and export body |

## Input-by-surface matrix

Each cell has its own disposition: **C = already-correct**, **B = confirmed-bug**,
**N = needs-investigation**, **I = intentionally-unsupported**. “Same S” means the
same production builder, not merely similar code. C establishes source wiring;
executed test coverage is described separately below. An input unused by a
surface is I, rather than a claim that it has been tested there.

“Preview” includes selection preview P and per-work image preview V; “saved” is
R; “feed” includes F/H; “export” is E/D.

| Input | Preview | Saved resolution | Feed | SD export | Evidence / disposition owner |
|---|---|---|---|---|---|
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
| Caller `quality_scores` | C: P honors explicit values | I: save model has no field | I: R derives server evidence | I: export model has no field | Probe confirms different IDs; P1 proposal below; never promise override persistence |
| Caller `embeddings` | C: P honors explicit values | I: save model has no field | I: R derives server evidence | I: export model has no field | Explicit empty mappings refuse; P1 |
| Missing master | C: P reports `has_master=false`; V 404 | C: ordered R omits; diverse validates | C: no advertised missing image | C: writer skips/reports missing image | Intended diagnostic vs playable-output distinction; no byte-parity claim |
| Candidate corpus/metadata | C: current sidecars | C: current sidecars | C: re-resolves live | C: current sidecars | `api/main.py:489–511`; stable snapshot across later calls is I |
| Target key | C: V validates; P only diagnostic target field | C: saved for F | C: target registry | C: inline or saved target | P alone does not validate/produce target pixels; V does |
| Target width/height/rotation | C: V scales dimensions, keeps rotation | I: not a selection input | N: pixels use T, ETag only key | C: native T dimensions | P2 proposal: same-key registry geometry replacement not in H identity |
| Palette name / actual colors | C: V uses T palette | I: selection does not consume | B: bytes use palette, ETag omits colors | C: T + D palette-conformance assertion | [#808](https://github.com/stranske/Fine-Art-Archive/issues/808); executed changed-bytes/stale-304 probe |
| Palette `measured` | C: V header | I: selection does not consume | B: 200 header changes; old ETag yields 304 without this header | C: manifest/warning records status | #808; executed header probe; physical fidelity remains unverified |
| Master pixels + mtime | C: V reads master; no-store | C: Q descriptor derives master | C: mtime in ETag; N: content identity if mtime preserved | C: D reopens master | P2; byte/hash replacement with same mtime not covered by H |
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
| Title/artist/year metadata | C: P parses from same sidecars | C: R parses | C: manifest/next include | C: D manifest includes | Metadata is outside image ETag; year-zero UI label P3 below |
| `fmt` | I: PNG response | I | I: PNG response | C: PNG/BMP only; JPEG rejects | D; palette round-trip and lossy refusal tests executed |
| Path, write, overwrite | I | I | I | C: allowed root, dry run, owned-file overwrite, skip failures | E/D; write success evidence differs from dry-run proposal evidence |
| Custom ICC / forced render policy | I: V has no hints payload | I | I: F has no hints payload | I: HTTP export has no hints payload | `render_for_device` supports separate hints; no claim that companion calls it |

## Findings, deduplication and owned work

The search `gh issue list --repo stranske/Fine-Art-Archive --state all --search divergence`
was executed before proposals. A second all-state issue inventory matched titles
and input semantics, because title-only divergence search misses older instances.

| Instance | Disposition at inspected commit | Existing owner / reason no duplicate was filed |
|---|---|---|
| A15 evidence lost on save/feed/export | already-correct | #784 closed; S is shared; executed ID agreement covers both inline and saved export, dry and write |
| A11 policy reported but not applied | already-correct | #788 closed; V/F/D apply master-selected strategy; export test checks native palette pixels |
| Fit omitted from image validator | already-correct | #786 closed; old ETag invalidates after framing change; implicit/explicit defaults share identity |
| Palette colors/measurement omitted from validator | confirmed-bug | #808 open; reproduced on same target name, without filing another issue |
| Repeated unchanged descriptor computation | owned optimization, not a correctness fix in this report | #807 open; validation must stay intact |
| Explicit zero year bounds | confirmed-bug shared by all selectors | #806 / PR820 already owns this; the audit branch preserves that writer |

Additional observations are proposals for human review **within #805**, not newly
approved repair tasks or published issues:

- **P1 — preview-only explicit evidence.** Direct API callers can preview different
  IDs with explicit quality/embedding maps, then save the same spec and get the
  server-derived IDs. Reproduced: default preview and saved feed select red+blue;
  explicit preview selects near-red+blue. Companion U sends no explicit maps, so
  the UI's normal path is already-correct. The API boundary is intentionally
  unsupported for persistence. Decide whether documentation should promise only
  server-derived parity or whether a separate evidence-persistence feature is
  wanted. Do not add storage or accept fabricated evidence here.
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

## Executed evidence and test layers

Local runtime: `/opt/anaconda3/bin/python3`, Python 3.12, pytest 9.1.1,
FastAPI 0.138.1, Starlette 1.2.0, httpx 0.28.1. These are observed local versions,
not a claim that both hosted Python matrices passed. All archive/card fixtures
were temporary; no production archive or removable device was used.

```sh
/opt/anaconda3/bin/python3 -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py tests/test_render_strategy.py -q -o addopts= --junitxml=/absolute/evidence/805-surface-tests.xml
```

Result: **201 passed**, one Starlette/httpx deprecation warning, 52.95 seconds.
No tests were added or weakened for this report. The XML and raw output are held
in the opener receipt directory `run-20261017T1455`; the portable probe and its
observed results accompany this report in `eink_surface_audit/`.

| Test file / named controls | Layer actually checked | What it does not establish |
|---|---|---|
| `test_eink_pipeline.py`: filtering, seeded order, diversity, `test_ui_shaped_spec_reaches_preference_diverse_selection`, `test_operator_ui_can_emit_selection_mode_and_render_its_diagnostics` | IDs, metadata/accounting, selection diagnostics, static/Node-executed UI wiring; render helpers, palette pixels and card layout in other named cases | Every real browser interaction, every input cross-product, full physical output |
| `test_eink_feed_endpoints.py::test_preference_diverse_preview_saved_feed_and_exports_agree` (dry/write) | Real HTTP IDs and order across preview/save/list/manifest/next/image/inline and saved export; SD manifest IDs, PNG format and bytes written | Cross-route pixel-byte equality; test checks image work identity and format |
| Same file: `test_preference_diverse_invalid_evidence_never_commits`, `...filters_before_deriving_and_resolves_live`, `...preview_keeps_explicit_evidence` | Invalid evidence refuses without store/card mutation; live evidence changes; explicit preview overrides | Persistence of explicit caller maps |
| Same file: `test_fit_change_invalidates_saved_feed_image`, `test_unset_fit_and_explicit_target_default_share_feed_etag`, `test_applied_strategy_change_invalidates_etag` | HTTP 200/304, headers, changed image bytes, dimensions and effective policy | Palette/measurement/geometry/master-content identity beyond existing ETag inputs |
| `test_eink_export_format.py::test_export_applies_selected_strategy_with_native_palette` | Actual SD PNG pixels, native dimensions, delivered manifest strategy for color/grayscale/duotone | Physical panel response |
| Same file: `TestRoundTripFidelity`, `TestFormatRefusal`, `TestPaletteConformanceAssertion` | Exact PNG/BMP palette round-trip, observed JPEG damage, format refusal and stray-pixel guard | Device firmware's interpretation of those files |
| `test_render_strategy.py`: three verdict tests and `test_poorly_served_work_uses_deliberate_monochrome_pixels` | Strategy/reason and a sibling `render_for_device` grayscale pixel control | Companion/feed execution of that sibling function; their route-specific tests are separate |

The temporary-fixture probe additionally observed:

- Default preference preview IDs equal saved-feed IDs; explicitly overridden
  preview IDs differ, as described in P1.
- After same-name palette colors change, unconditional PNG bytes change but
  ETag does not; an old `If-None-Match` receives **304**. The strategy was pinned
  to grayscale after first checking its actual initial value, isolating palette
  identity. This is #808's existing scope, not a new finding.
- Flipping only the palette measurement flag changes the unconditional
  `X-Palette-Measured` header from `False` to `True`; ETag remains unchanged and
  conditional 304 omits that measurement header. This is also #808.

### Causal control and literal-gate limitation

An unchanged production regression was run with only `_resolve_playlist`'s
call changed from `_build_eink_playlist` to raw `eink.build`. Both dry/write
variants of `test_preference_diverse_preview_saved_feed_and_exports_agree`
failed at save's expected HTTP 200 because derived evidence no longer reached
selection. Original production bytes were restored, then both variants passed.
The SHA-256 equality and exact commands are in `transport-proof.json`.

#805 also contains a literal template criterion asking for a new pipeline test
and a disconnected change in `ui/index.html`, while its scope forbids bundled
production fixes and requires the existing suites unchanged. This audit does
**not** claim that literal UI mutation/new-test criterion was performed. The
production-edge control above tests the audited transport seam instead. Keep
source acceptance pending explicit review of that criterion; a report or green
suite alone does not close the issue. No additional production authority was
inferred from the conflicting template text.

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
4. Recheck #784/#786/#788 and #806/#807/#808 before proposing work; do not file
   duplicates. Return P1–P3 for review under #805. Do not publish new follow-ups
   without their separate approval.
5. Compare full-size output only with the same master snapshot, target, fit,
   strategy and dither. Thumbnail byte equality, freeze-at-preview membership,
   and physical panel acceptance have not been established by this report.
