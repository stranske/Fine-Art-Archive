# Project TODO — parent/crop lineage and file consolidation

Carried-forward work from the 2026-08-19 lineage session. Each item is self-contained:
what it is, the measured evidence, what it costs, and what "done" looks like. Numbers here
were measured, not estimated — re-measure before acting only if the archive has moved on.

**This is an FYI surface, not a queue.** Nothing here expires or escalates, and nothing
accumulates if it is ignored. Items marked **machine** need no human judgement; items
marked **decision** cannot proceed without one.

Standing context for any session touching this: the sidecar corpus lives **outside** the
repo at `Dropbox/Pictures/Art/works/<work_id>/meta.json` (3,423 works), and the lineage
metadata at `Dropbox/Pictures/Personal Photos/Metadata/`. Tooling for the archive side is
in `Metadata/tools/` with its own README.

---

## 1. Meural / reduced-size copies — deliberately deferred

**Status: waiting, by owner decision (2026-08-19). Do not start.**

The size-reduced copies made for Meural's 20 MB limit are the one file class that is
*purely* derivable — a downscale of an existing crop, with no edit to reproduce. Removing
them loses nothing and needs no `crop_region`.

Blocked on a prerequisite: **`display_derivative` is empty for all 42,653 rows of
`ARCHIVE_INDEX.csv`.** If those reduced copies exist on disk they are invisible to the
index, so they cannot be counted, located, or safely removed yet.

- **First step when resumed (machine):** find the reduced copies by content — same aspect
  as a known crop, materially smaller pixel dimensions, under 20 MB — and populate
  `display_derivative` so they become countable.
- **Done looks like:** every reduced copy is either indexed or removed, and export-time
  downscaling replaces them.

## 2. Crops cannot be replaced by `crop_region` — closed, recorded so it is not retried

Measured and settled. Do not re-open as a storage strategy.

Of 44 crops with a verified region, only **4 (9%)** regenerate from original + region at
>45 dB PSNR; the median is **30.0 dB**, a visible tonal difference. ~1,170 of the 2,010
display crops in the device albums were rendered in Luminar / Aurora HDR, whose output is
a re-grade, not a rectangle. 4 of 44 stored crops are also *upscaled* past their source
region. The archive's own `fitted local-affine transfer` reconstruction records a median
`reconstruction_mad` of 3.49/255 with none under 0.5.

**The trap worth remembering:** NCC ≈ 1.0 while PSNR ≈ 30 dB. Normalised cross-correlation
subtracts the mean and divides by variance, so it is blind by construction to brightness,
contrast, and grade. It proves the *geometry* of a crop and says nothing about its *tone*.
Never treat a high NCC as evidence that a crop is reproducible.

The parent and the crop are two different images, so keeping one copy of each already
satisfies "one version of each file". `crop_region` remains valuable for **re-cutting a new
aspect ratio** from the parent and for provenance.

## 3. Nothing reads `source_image`, `crop_region`, or `files.variant_of` — **machine (partly done)**

All three are now declared in `schemas/meta.schema.json` and populated (898 / 46 / 96), and
no code reads any of them. This project has now shipped an undeclared-and-unread lineage
field three times (`derived_from` 27, `files.variant_of` 96, `source_image` 898).

- **Do:** add a consumer for `crop_region` — cut a new device aspect from the parent using
  the recorded region as the starting frame.
- **Drift detection: done (2026-08-19), in two halves.** CI cannot scan the corpus — it
  lives outside the repo and no runner can see it — so the two directions are split:
  `tests/test_sidecar.py::test_lineage_field_stays_declared` fails in CI if a schema edit
  drops a field the data already uses (verified by deliberate break: 9 failures, clean
  revert), and `Metadata/tools/check_sidecar_drift.py` catches the direction CI cannot — a
  writer emitting a field the schema has never heard of. The scanner reports clean today
  and correctly reproduces the historic drift when pointed at the pre-fix schema.

## 4. Two verified parent links were never written to their sidecars — **done**

Both have a Dropbox-resident parent, a located region, and evidence stronger than the 858
`filename-prefix` / `probable` links that *were* written:

| work_id | NCC | self-check |
|---|---|---|
| `603c5f6-vase-with-gladioli-and-chinese-asters-gogh` | 0.9751 | 0.9969 |
| `a34f673-woman-with-a-book-picasso` | 0.8786 | 0.9159 |

**Done 2026-08-19.** Both written as `method: crop-located` / `confidence: verified` with a
`verification` block and a `crop_region`, validated against the schema before write; only
`source_image` was added and no pre-existing key changed. Corpus went 896 -> 898
`source_image` and 44 -> 46 `crop_region`.

## 5. Three parents live outside Dropbox — **decision**

`source_image.path` is defined relative to the Dropbox account root, so these cannot be
recorded in a sidecar at all. They are identity-stamped in `ART_PARENT_LINKS.csv` with a
`sha256:`-prefixed local hash instead, and cannot be relocated by the Dropbox index.

    ~/Pictures/Painting - Portrait/Jeremiah Lamenting the Destruction of Jerusalem - Rembrandt.jpeg
    ~/Pictures/Painting - Portrait/Jacob wrestling with the Angel (Rembrandt).jpeg
    ~/Pictures/Painting - Landscape/A Wooded Landscape with Travelers on a Path through a Hamlet (Hobbema).jpeg

Options: move them into Dropbox (consistent with the one-copy-backed-up-online goal), or
widen `source_image.path` to admit an account-external locator. The first is simpler and
matches the stated end state.

## 6. The `candidate` rows — content-hash pass DONE, the rest still not a queue

**Done 2026-08-21: 39 byte-identical parents written**, `method: byte-identical` /
`confidence: certain`. `source_image` coverage 898 -> 937.

The "8 links" estimate previously recorded here **did not reproduce, in both directions**, and
the reasons are worth keeping:

* Restricted to ART_LINEAGE's own pairings, the join finds only **3**. ART_LINEAGE's guesses
  are not where the free links live.
* The real self-join — every master against every non-Art file in the account — finds **39**.
  It can pair a work with a parent that has no candidate row at all, which is the whole point.
* Its prerequisite was **missing**: `tools/catalogue.sqlite` and `tools/nucleus_index.sqlite`
  did not exist, so the "~25 s, no I/O" claim was unrunnable. Rebuild with
  `tools/build_nucleus_index.py` — it reads Dropbox's own metadata store and indexed
  1,139,609 files in **38 s** with no downloads. Do this first.
* Skip twins under `_RETIRED-Photos-Library-*` and `staging_acquisitions/quarantine_*`: same
  bytes, but paths expected to disappear, so they are not provenance parents.

The remaining `candidate` rows are still **not** a queue, for the reason already recorded: at
~6% precision, testing them one by one is testing a bad hypothesis. What changed is that the
NCC crop-location test is now wired and measured (item 7), so the honest next step is to
extend THAT over the works, not to adjudicate rows.

## 7. ART_LINEAGE ↔ `source_image` conflicts — **RESOLVED 2026-08-21, by testing**

Not a decision after all. `Metadata/tools/test_lineage_conflicts.py` locates the master inside
BOTH candidates (`verify_art_links.locate_precise`, then re-cuts the located region and
re-correlates it independently). Full detail in `Metadata/ART_LINEAGE.README.md`; per-row
output in `Metadata/lineage_conflict_tests.json`.

**34 conflicts, not 22** — 12 more appeared once the byte-identical pass gave 39 works a
`certain` parent, putting a proven parent opposite an ART_LINEAGE claim.

| verdict | rows |
|---|---|
| `both-valid` — both contain the master; the work has two photographs | 23 |
| `sidecar-wins` — ART_LINEAGE's photo does NOT contain it; `superseded_by` set | 7 |
| `neither-located` — both claims unproven | 3 |
| `one-side-untestable` — a candidate would not materialise | 1 |

**Zero rows resolved against the sidecar.** And the README's hypothesis — that the
accession-named ART_LINEAGE photos "may well depict the same painting" — was **wrong for all
7 refutations**, in the predicted right-artist-wrong-painting way: three Giotto Scrovegni rows
named the wrong panel of the same cycle (*12. Wedding Procession* matched to *10. The Suitors
Praying*; *25. Raising of Lazarus* to a detail of itself), at NCC 0.17-0.31 against the
sidecar's 0.86-0.98.

**Net yield: 19 links moved `probable` -> `verified`** with a `crop_region` and an independent
self-check; 3 moved `probable` -> `unverified` (refuted, not merely untested).

**The rule the tester exists to enforce — untested is not refuted.** Its first version scored
"could not read the file" as "failed the test" and produced two false wins where the other
candidate was merely online-only; a `byte-identical` link needs no locating at all, since hash
equality holds for evicted files. Acting on those verdicts would have moved two parent links
off files whose identity was never contested.

Cost, measured: 2.05 GiB hydrated (57 files) then 2,127 s of locating. **Fetch concurrently** —
serial reads through the Dropbox File Provider managed one 15 MiB file in 15 minutes.

### What is left: 826 `probable` links whose parent is online-only

The same test would verify or refute every remaining `filename-prefix` link, with no human
input. It needs **24.4 GiB** hydrated (~24 h wall clock at the measured concurrent rate). Disk
is not the constraint. This is a cost decision, not a research problem.

## 8. `UPSCALE_LINEAGE.csv` has the same position gap — **machine, but unowned**

1,460 rows; 221 with at least one crop match, 59 at NCC ≥ 0.80. It stores `crop_best_area`
and no position, so the located geometry was computed and discarded — the same defect fixed
in `verify_art_links.py`. No generator for it exists in `Metadata/tools/`, and its matching
procedure is recorded nowhere, so positions would have to be re-derived by an invented
method and would carry more authority than they earned. Needs its generator found or
rewritten first.

## 9. `relink_parents.py` is not wired into the move process — **machine, optional**

`Metadata/tools/relink_parents.py` re-resolves every recorded parent path from its content
hash, so links survive the relocation/dedup migration. It runs in ~25 s, is idempotent, and
was functionally tested for both relocation and the refuse-to-guess path.

It is invoked by hand today. Because identity is recorded *in the files themselves*, a
missed run leaves links **stale, never lost**, and one later run repairs every accumulated
move at once — so no backlog can form and no schedule is required. Wire it into whatever
performs the moves only if that is convenient.
