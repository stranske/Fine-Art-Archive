# Applied: work Q-IDs, dimension fixes, and what was deliberately left alone

Companion to `work-qid-dimension-review.md`, which holds the full proposal
list and method. This records what was written to the archive.

## Written

- **193 work Q-IDs** assigned 119 tier A, 46 tier A2, 28 tier A3
- **34 dimension corrections** 23 raw-reparse, 11 wikidata
- every write logged to the archive's `operations.log`
- a full pre-write snapshot of all 3,405 sidecars is in the session scratchpad

Each sidecar was re-read from disk at write time and re-checked against the
archive's own `WorkQidClaims` guard, seeded from a fresh scan and updated as
the run proceeded. **No Q-ID was assigned that another work already held.**

## Not written

Three sidecars were refused by schema validation, all for the same
pre-existing reason and none caused by this work:

```
e9d9327-the-flagellation-of-christ-caravaggio   derived_from  (work Q-ID)
1c5c5da / others                                derived_from  (dimensions)
```

`derived_from` records that a sidecar is a detail of another work — e.g.
`e9d9327` is the 'torso detail' of `1c5c5da`. That is legitimate data the
schema does not declare, so `sidecar.write()` rejects the whole file.

## Schema fix applied

`stable_identifiers.part_of_q` was missing from `schemas/meta.schema.json`
while **197 sidecars already carried it** and
`identity/work_qid_uniqueness.py` names it as the remedy for a Q-ID
collision. Every one of those 197 failed validation, so any pass calling
`sidecar.write()` on them was blocked. The property is now declared.

Still undeclared, and still blocking 33 sidecars: `derived_from` (27),
`existence` / `identity_anchor` (4), `crop_position` (2). These were left
alone deliberately — unlike `part_of_q` their intended semantics are not
documented in the codebase, and guessing them into the schema is how junk
entries got in before (see `FORBIDDEN_P31`).

## The contested Q-IDs are not duplicates

79 Q-IDs are held by more than one work, covering 162 works. The instruction
that follows naturally — de-duplicate them — would destroy data in **87%** of
cases. Classified by evidence:

| Group kind | Count | What it means | Action |
|---|---:|---|---|
| display-crop | 69 | a member sits exactly on 16:9 or 9:16 — a crop cut for a picture frame | keep both |
| series member | 7 | `part_of_q` already set; Wikidata models the group, not the member | already correct |
| same image | 2 | one true duplicate entry; one sidecar has no master file at all | review |
| framed vs unframed | 1 | same painting, one photographed in its frame | keep both |

**Nothing requires deletion.** The two worth a human glance:

```
Q1134250  corr=1.0  834aa36-massacre-of-the-innocents-pieter-bruegel-156567, e01d018-the-massacre-of-the-innocents-elder
Q20188850  corr=1.0  087aa85-auguste-renoir-chatou, 3f0dc0d-oarsmen-at-chatou-renoir
Q29530  corr=0.464  2596f77-liberty-leading-the-people-framed-delacroix, 4eb930b-liberty-leading-the-people-delacroix
```

`834aa36-massacre-of-the-innocents-pieter-bruegel-1565-1567` has no master
file on disk, which is a separate defect from the shared Q-ID.

## What this says about the uniqueness invariant

`work_qid_uniqueness` assumes one Q-ID denotes one sidecar. This archive
deliberately stores several renditions of one painting — a master plus 16:9
and 9:16 frame crops — and the schema says of file variants: "These are NOT
duplicates: each is fit for a specific device." Those renditions are all
genuinely the same Wikidata work, so the guard will keep declining correct
assignments for them (it declined 31 in this run on that basis).

The guard is still right to refuse — it cannot tell a crop sibling from a
real collision. But the modelling gap is worth closing: crop siblings want
to be `files.variants[]` of one work, or to be linked to a parent, rather
than standing as rival claimants to one Q-ID.
