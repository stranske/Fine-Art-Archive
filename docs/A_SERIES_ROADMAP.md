# A-Series Capability Roadmap

This roadmap preserves the dependency order established in issue #515. An
item moves from roadmap to implementation only through a focused issue with a
falsifiable acceptance gate. Later-stage headings are sequencing constraints,
not authorization to add scaffolding.

## Stage A — actionable from measured Wave 6 inputs

- **A11 — monochrome-first rendering.** Implemented through
  [#548](https://github.com/stranske/Fine-Art-Archive/issues/548). The existing
  gamut-fit verdict selects a deliberate color, grayscale, or duotone strategy.
- **A15 — quality × diversity exhibition selection.** Implemented through
  [#549](https://github.com/stranske/Fine-Art-Archive/issues/549). Preference
  quality comes from the delivered Rocchio and Bradley-Terry surfaces; visual
  diversity comes from caller-supplied archive embeddings.
- **A8 — series-aware curation.** Its missing ordering contract is isolated in
  [#550](https://github.com/stranske/Fine-Art-Archive/issues/550). The issue
  extends existing `stable_identifiers.part_of_q` membership with explicit,
  evidence-backed `series.position` data before ordered curation begins.

## Stage B — measurable model upgrades

- **A3 — DINOv3 migration.** A/B compare with the current DINOv2 archive
  embeddings; migrate only after the archive-specific retrieval gate passes.
- **A4 — aspect-preserving multi-crop embeddings.** Preserve work composition
  while making extreme aspect ratios measurable rather than center-cropped.
- **A7 — embedding-augmented candidate generation.** Keep promotion
  deterministic and version the candidate/evidence boundary.
- **A14 — affect vocabulary grounding.** Ground affect terms in the measured
  embedding space rather than adding unverified descriptive tags.

## Stage C — physical measurement, strictly ordered

- **A9 — illuminant-aware rendering** comes first and requires measured
  spectral reflectance.
- **A12 — optimisation-based halftoning** may begin only after the preceding model is
  measured; otherwise it optimises against a guessed panel.
- **A13 — panel ownership and operationalization** follows the measured model
  and halftoning result.

The wait is evidence-based: #513 measured a **16.6%** palette error bar across
plausible published estimates, while #502 measured only **6.5%** separation
between Floyd-Steinberg and Atkinson. Stage C must not optimize inside an error
bar larger than the effect it is trying to improve. Long-horizon physical
evidence remains in durable holder #469; it is not an immediate human request.

## Stage D — publication contracts

- **A2 — Linked Art 1.0** as a pinned, CI-validated export contract.
- **A5 — C2PA Content Credentials** on promoted masters and rendered e-ink
  outputs.
- **A6 — reconciliation-client architecture** replacing bespoke resolvers.
- **A1 — two-witness reproduction-fidelity corpus** with versioned evidence.

## Stage E — dossiers and evaluation

- **A16 — demand-ordered dossier generation.** Spend enrichment effort in the
  order users actually request it.
- **A17 — internal VLM evaluation harness.** Use the archive as a versioned
  comparison corpus with explicit ground truth.
- **A10 — content-adaptive rendering.** Drive rendering policy from the ratings
  evidence only after the preference and display contracts above are stable.

## Coordination rules

- Every implementation item gets its own issue and PR.
- A roadmap entry is not complete because a module or TODO exists; its named
  issue must pass its deliberate-break gate.
- Stage C stays dormant until the physical-evidence threshold is met. The
  automation may keep collecting evidence, but should not report a live owner
  decision merely because measurement has not happened yet.
