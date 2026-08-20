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

## 3. Nothing reads `source_image`, `crop_region`, or `files.variant_of` — **machine**

All three are now declared in `schemas/meta.schema.json` and populated (896 / 44 / 96), and
no code reads any of them. This project has now shipped an undeclared-and-unread lineage
field three times (`derived_from` 27, `files.variant_of` 96, `source_image` 896).

- **Do:** add a consumer for `crop_region` — cut a new device aspect from the parent using
  the recorded region as the starting frame.
- **Also do (small):** a CI check that validates the whole sidecar corpus against the
  schema and reports fields present in the data but absent from the schema. That converts
  the next occurrence from a discovery into a notification. ~20 lines, no recurring
  attention.

## 4. Two verified parent links were never written to their sidecars — **machine**

Both have a Dropbox-resident parent, a located region, and evidence stronger than the 858
`filename-prefix` / `probable` links that *were* written:

| work_id | NCC | self-check |
|---|---|---|
| `603c5f6-vase-with-gladioli-and-chinese-asters-gogh` | 0.9751 | 0.9969 |
| `a34f673-woman-with-a-book-picasso` | 0.8786 | 0.9159 |

Left undone deliberately: writing them creates a *new* link rather than recording a
position on an existing one, which was outside the 2026-08-19 request. Two-file change.

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

## 6. The 1,053 `candidate` rows — **do not work them as a queue**

`ART_LINEAGE.csv` holds 1,053 rows at `status=candidate` with an empty `superseded_by`.
They are DINOv2 cosine ≥ 0.90 guesses at ~6% precision, so ~990 of them are wrong by
construction. Testing them one by one is testing a bad hypothesis.

Measured options:

| approach | cost | expected yield |
|---|---|---|
| content-hash self-join against Dropbox's index | ~25 s, no I/O | **8 links** (`certain`) |
| targeted NCC on rows whose named parent is already local (72) | ~25 min | ~4 confirmations |
| same for the 981 online-only rows | **18.8 GiB** hydration + hours | ~59 confirmations |

**Recommendation:** take the 8 free ones, and otherwise leave the rows alone. Let coverage
grow from the *good* methods as the pinning migration makes originals local, and the rows
will retire themselves — `superseded_by` already flips to `sidecar:source_image:*` whenever
a real parent link appears for that work. Their standing value is the artist-level
narrowing hint, which the ART_LINEAGE README already records.

## 7. 22 ART_LINEAGE ↔ `source_image` conflicts — **decision, bounded**

Listed in full in `Metadata/ART_LINEAGE.README.md`. Cases where the two sources name
different parent files for one `work_id`. Not necessarily contradictions: ART_LINEAGE maps
*photo → work* while `source_image` maps *work → the file its master was cut from*, and
several works legitimately have more than one photo in the archive. Resolve by testing,
never by preferring a source.

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
