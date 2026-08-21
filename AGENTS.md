# AGENTS.md - Consumer Repository Context

> Read this before changing workflows, prompts, or synced automation files.

## Working Stance — Critical Evaluator (read first)

Your job is correct judgment, not agreement. Evaluate claims, designs, and instructions on the merits before agreeing — including the orchestrator's and the user's. When something is wrong, weaker than an alternative, or missing, say so plainly and lead with the strongest objection. Separate "this is correct" from "I'll do as asked." State your confidence and what would change your mind; flag what you are unsure of. Do not soften a real problem to be agreeable, and do not manufacture disagreement to seem rigorous — calibrated dissent, not maximal.

## This Is A Consumer Repo

Most workflow logic for this repository lives in `stranske/Workflows`. The consumer repo should only carry repo-specific configuration unless it has an explicitly documented exception.

## Source Of Truth

For infrastructure work, follow this order:

1. `stranske/Workflows` root docs: `README.md`, `docs/WORKFLOW_GUIDE.md`, `docs/ci/WORKFLOWS.md`
2. `stranske/Workflows/docs/INTEGRATION_GUIDE.md` and `docs/ops/CONSUMER_REPO_MAINTENANCE.md`
3. The consumer sync source in `stranske/Workflows/templates/consumer-repo/`
4. This repo's local repo-specific files

If a file is synced from Workflows, fix it in Workflows first.

## Current Consumer Defaults

- First-party consumers currently reference reusable workflows with `@main`. Match that unless you are intentionally pinning to an exact commit SHA for a controlled reason.
- `ci.yml` and `autofix-versions.env` are repo-specific.
- `pr-00-gate.yml` is a create-only standard file. Keep it aligned with the standard gate unless this repo has a documented reason to diverge.
- Synced workflows, prompts, scripts, and consumer docs are managed through `.github/sync-manifest.yml` in Workflows.

## Pull Request Readiness Invariant

- Automation-created pull requests must be opened ready for review. Do not create drafts or convert ready pull requests back to draft.
- Draft state is not a staging, dependency, stack-order, or opener-cap control. Use explicit labels, PR-body lifecycle state, disabled auto-merge, required checks, and exact-head merge guards instead.
- Before handing off or ending work, verify every pull request created or changed by the run is open and has `isDraft=false`. Convert a pre-existing draft to ready as a recovery action.
- Do not close an otherwise valid pull request merely to free automation capacity; preserve its branch and route the real blocker or dependency explicitly.

## Commonly Managed Files

Usually edit locally only when the file is repo-specific:

| File | Default owner | Notes |
|------|---------------|-------|
| `ci.yml` | Consumer repo | Repo-specific CI wiring |
| `autofix-versions.env` | Consumer repo | Repo-specific dependency pins |
| `pr-00-gate.yml` | Consumer repo, but should match Workflows standard by default | Create-only standard file |
| `agents-*.yml` | Workflows | Fix in Workflows, not here |
| `autofix.yml` | Workflows | Fix in Workflows, not here |
| `.github/codex/` prompts | Workflows | Fix in Workflows, not here |
| synced scripts/docs | Workflows | Fix in Workflows, not here |

## Current Workflow Surfaces

The current consumer default automation surface is centered on:

- `agents-issue-intake.yml`
- `agents-80-pr-event-hub.yml`
- `agents-81-gate-followups.yml`
- `agents-verifier.yml`
- `autofix.yml`
- `ci.yml`
- `pr-00-gate.yml`

Legacy compatibility workflows may still exist during migrations. Do not assume an older filename is canonical without checking the Workflows docs first.

## Cross-Repo Policy

Before editing local workflow infrastructure, ask:

**Does this work belong in `stranske/Workflows` instead?**

The answer is usually yes if the change affects any of these:

- reusable workflows
- agent prompts or routing
- keepalive/autofix/verifier behavior
- synced workflow files
- synced scripts or docs

If yes:

1. Make the source-of-truth change in `stranske/Workflows`
2. Update the sync manifest if a consumer-facing file changed
3. Sync or manually align this repo afterward

## Optional GitNexus Context

- GitNexus may be available as a local MCP/indexing layer for cross-repo search and impact checks.
- Use it opportunistically for workflow/template drift, blast-radius checks, and Workflows-vs-consumer ownership questions when indexes are fresh.
- Treat `.gitnexus/` as local derived cache. Do not commit it, require it in CI, or make correctness depend on it.
- If GitNexus is unavailable or stale, continue with normal `rg`, git, and repository tests.

## Identifying a Work: Reverse Image Search Is the Next Step

**When you are stuck on a work's identity and you have its image, do a reverse image
search before concluding anything.** This is not a last resort. It is the next step, and
it comes BEFORE writing "unidentified", before an adjudicated `not_available`, and before
reporting the work as a hard case.

The archive holds a picture of every work. That picture is the strongest identifying
evidence available, and catalogue-metadata searches routinely fail on works the image
finds in seconds.

Worked example, 2026-08-21. `e7bc13e-estuary-at-day-s-end-vlieger` sat unidentified for
twelve days. A Wikidata oeuvre search over its artist returned nothing, and it was
reported as "still unidentified" twice. One reverse image search returned the answer as
the top visual match: Simon de Vlieger, *Beach View* (*Strandgezicht*), 1643, Mauritshuis
inv. 558, 60.6 x 83.5 cm, Q17275980 — with the museum's own description matching the
picture element for element.

**Why the metadata search could not have found it.** The by-creator strategy discriminates
on dimensions, and this sidecar was carrying 36.8 x 58.4 cm — the dimensions of a
*different* painting, left behind by an identification that had already been rejected. No
amount of oeuvre searching can match a work against another work's measurements. The image
carries no such inherited error, which is exactly why it should be consulted first.

### How

1. Downscale the master to ~2000 px (upload caps are ~10 MB).
2. Upload it to a reverse image service. Read the top *visual* matches, not the web results.
3. Take the identification to the **holding institution's own record**, then to Wikidata.
   Do not stop at an aggregator, a print shop, or Commons — see the archive's standing rule
   that the host museum outranks Commons for both identity and image quality.
4. Record the result in `field_provenance.work_qid` using only schema-supported
   fields. Set `source` to `reverse_image_search`, put the search-result URL in
   `source_ref`, stamp `checked_at`, and cite the holding institution's record and
   the Wikidata item in `note`. Use `status: available` only for a confirmed match.

### When it does not settle the question

Run the search before retaining an unidentified result. No results, unrelated results,
or results limited to print shops and stock-photo resellers have not identified the work;
record `status: not_available` and describe the outcome in `note`. When plausible matches
conflict, retain the work as unidentified, record `status: conflicting`, and cite each
candidate there. Do not promote any of these outcomes to an identification.

## Useful References

- `stranske/Workflows/README.md`
- `stranske/Workflows/docs/WORKFLOW_GUIDE.md`
- `stranske/Workflows/docs/ci/WORKFLOWS.md`
- `stranske/Workflows/docs/INTEGRATION_GUIDE.md`
- `stranske/Workflows/docs/ops/CONSUMER_REPO_MAINTENANCE.md`
- `stranske/Workflows/docs/keepalive/Agents.md`
- `stranske/Travel-Plan-Permission` as a reference consumer

## Agent-Specific Note

This file is the agent-generic contract. Keep it materially aligned with `CLAUDE.md`; differences between the two should only be agent-specific execution notes, not different repository rules.
