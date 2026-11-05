# E-ink preview and delivery input audit

Inspected source: `3c23a10978e1c61151d6856576d56628c8737171`, 2026-10-17.
Source owner: [#805](https://github.com/stranske/Fine-Art-Archive/issues/805).
The original audit was a bounded input inventory and evidence report with no
production changes. The #825 follow-up below documents the selected preview-only
API contract and its regression tests; it changes no selector, image, palette,
archive record or physical device. Other proposals remain report-only under
#805's follow-up publication boundary.

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

The HTTP render defaults are target `gooddisplay-315-diy` (2560 × 1440,
Spectra-6, contain, rotation 0), `dither=floyd-steinberg`, and unset `fit`
(resolved from the target). Per-work preview defaults to `max_px=900` and
selection preview to `sample=24`. The common pixel renderer and SD writer both
default `compress_range=True` and `fast=True`; neither option is exposed by
these HTTP request models. Export defaults to PNG and a dry run, with overwrite
disabled. The executable inventory below captures all 17 playlist defaults and
the three request models' fields; its assertions also compare renderer/writer
defaults.

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

Local runtime: `/opt/anaconda3/bin/python3`, Python 3.12, pytest 9.1.1,
FastAPI 0.138.1, Starlette 1.2.0, httpx 0.28.1. These are observed local versions,
not a claim that both hosted Python matrices passed. All archive/card fixtures
were temporary; no production archive or removable device was used.

```sh
/opt/anaconda3/bin/python3 -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py tests/test_render_strategy.py -q -o addopts= --junitxml=/absolute/evidence/805-surface-tests.xml
```

Result: **201 passed**, one Starlette/httpx deprecation warning, 52.95 seconds.
That initial run added or weakened no tests; the later UI regression is recorded
below. The XML and raw output are held
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

### Original production-edge causal control

An unchanged production regression was run with only `_resolve_playlist`'s
call changed from `_build_eink_playlist` to raw `eink.build`. Both dry/write
variants of `test_preference_diverse_preview_saved_feed_and_exports_agree`
failed at save's expected HTTP 200 because derived evidence no longer reached
selection. Original production bytes were restored, then both variants passed.
The SHA-256 equality and exact commands are in `transport-proof.json`.

The initial audit used this production-edge control rather than the requested
new pipeline test and `ui/index.html` mutation. The later UI regression below
now supplies that literal gate without a permanent production edit or changes
to existing test assertions. These are two distinct controls.

## Portable probe verification in the automation sandbox

The retained [probe](eink_surface_audit/probe.py) was extended and executed
against source at `ee75d23ad0e06cb73a2647a5c9dd0db569e43182` on Python 3.14.8.
Its [current JSON](eink_surface_audit/probe-results-current.json) binds the probe
hash to the source commit and records these additional assertions:

- All 17 dataclass fields have rows in this report. Request-model fields and
  pixel-renderer defaults are inventoried directly from the imported code;
  renderer/writer defaults agree. This checks inventory completeness, not
  endpoint behavior for every individual filter.
- `sample=0` removes diagnostic rows without changing membership. Explicit
  empty quality or embedding maps each return 400 instead of deriving evidence.
- A saved two-work feed starts, advances, wraps and restarts on an unknown
  cursor; its advertised image URLs return the expected work. An out-of-range
  index returns 404, and `current?offset=1` changes work at a fixed clock instant.
- For two fixture works at a native **40 × 20**, `dither=none`, default contain
  target, decoded RGB pixels and dimensions agree across per-work preview,
  feed and actual PNG card writes. Both inline and saved exports pass; saved
  export also overrides deliberately invalid inline spec/target/dither/fit.
  Explicit contain equals implicit fit in preview, and unchanged feed ETags
  return 304. These bounded pixel checks establish neither thumbnail equality
  nor parity for every dither, fit, palette, resolution or physical panel.
- Palette and measurement observations above now have explicit assertions,
  including the missing measurement header on 304. No new follow-up was filed.
- Source and existing-test file fingerprints agree before/after all fixture
  activity. `src/` and `tests/` also have no changes against the source commit.

The [current pytest capture](eink_surface_audit/surface-tests-current.txt) and
[JUnit](eink_surface_audit/surface-tests-current.xml) record **201 passed**, one
deprecation warning, in 49.43 seconds. This reruns the same four existing suites
with `-m "not slow"` and coverage disabled through `-o addopts=`; it is not a
coverage-target claim. [Validation metadata](eink_surface_audit/validation-current.json)
records commands, exits, artifact hashes and the successful repository-wide
Black check. The historical `probe-results.json`, suite summary and production
break/restore receipts remain intact; `transport-proof.json`'s equal original
and restored hash was also checked against the current `api/main.py` bytes.
This receipt check does not claim a new production mutation run.

This sandbox denies socketpair wakeup writes, causing unmodified asyncio
thread handoffs to stall, and denies Black's process-worker socket binding.
For these commands only, the retained
[optional harness](eink_surface_audit/sandbox/sitecustomize.py) bounds selector
waits to 10 ms; `BLACK_NUM_WORKERS=1` avoids process workers. It leaves I/O
permissions in force and changes scheduling only in the validation process.
Use it only on a host with this restriction:

```sh
export PYTHONPATH="$PWD/docs/reports/eink_surface_audit/sandbox:$PWD/src"
export BLACK_NUM_WORKERS=1
python docs/reports/eink_surface_audit/probe.py "$PWD" "$(git rev-parse HEAD)"
python -m pytest tests/test_eink_pipeline.py tests/test_eink_feed_endpoints.py tests/test_eink_export_format.py tests/test_render_strategy.py -q -o addopts= -m "not slow"
black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
```

The three prior repair links (#784/#786/#788) and existing owners
(#806/#807/#808) above were retained. GitHub access was unavailable during this
rerun, so their current remote states were not revalidated. P1–P3 remain
proposals under #805; this run published no follow-up issues.

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
