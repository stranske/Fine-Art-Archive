# WACZ snapshot pipeline

Per CLAUDE.md hard rule: "Defeat link rot. Every linked resource gets a
local WACZ snapshot at ingest, refreshed on a schedule."

## Status

Pipeline is **operational** (initial backfill completed 2026-05-25 under
grant G15). Snapshots live at `Art/snapshots/<sha256(url)>.wacz`; the
backfill runs via `scripts/run_wacz_backfill.sh`.

## Install (run on the Mac, not in the sandbox)

Recommended: `browsertrix-crawler` (Docker-based, headless Chromium,
produces standards-compliant WACZ).

```bash
# If you don't already have Docker Desktop / OrbStack / Colima:
brew install --cask orbstack

# Pull the crawler image:
docker pull webrecorder/browsertrix-crawler:latest
```

Lighter alternative: `pywb` + `wget` for static pages only.

## Per-host policy

`policy.example.yaml` shows the schema. Each host in
`host_registry.yaml` gets a `wacz_policy` block:

```yaml
hosts:
  artic.edu:
    wacz_policy:
      max_depth: 1            # only the object page itself, not its links
      include_assets: true    # bundle CSS/JS/images for replay fidelity
      js_render: true         # ARTIC's page needs JS for the IIIF viewer
      refresh_days: 90        # re-crawl quarterly
      max_size_mb: 100        # cap per snapshot to keep storage sane
```

## Where snapshots live

`<archive_root>/snapshots/<sha256(url)>.wacz` — sha256 keying makes the
filenames idempotent. The sidecar references back via
`acquisition_provenance.snapshot_path`.

## Backfill queue

`backfill_queue.txt` lists URLs awaiting (or already covered by) a
snapshot. The step-3 handler seeds it from `operations.log` on first
run; after that, **the on-disk file is authoritative**. Audited
corrections — e.g., resolved Wikidata P18 truncations or replaced
ARTIC `<image_id>` placeholders — survive re-runs because the handler
will not overwrite an existing queue.

Run the backfill:

```bash
./scripts/run_wacz_backfill.sh           # dry-run: shows what would crawl
./scripts/run_wacz_backfill.sh --apply   # actually crawls, writes WACZ, appends G-grant ops rows
```

The script is idempotent (skips URLs whose snapshot is fresher than the
host's `refresh_days`).

## Grant model

Crawling writes new files outside the workspace and emits network
traffic to the listed hosts. Each batch needs a `permissions.md` grant
enumerating the URLs and scoping the write to
`Art/snapshots/<sha256(url)>.wacz`. The initial backfill ran under G15.
Adding new URLs requires either extending an existing grant or writing
a new one before running `--apply`; the step-3 handler will report a
non-empty `would-crawl` count and stay `blocked` until the grant catches
up.

## Quarterly refresh

A scheduled task analogous to the device-review one (in
`scheduled_tasks.md`) walks the snapshots/ directory, finds anything
older than its policy's `refresh_days`, and re-crawls.
