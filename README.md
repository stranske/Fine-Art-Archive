# Fine Art Archive

Code and operational policy for the Fine Art Archive consumer repo. Artwork
data lives separately in the Claude Project workspace under
`Dropbox/Pictures/Claude Project/`, selected at runtime with `FAA_WORKSPACE`.

## Layout

```
src/fine_art_archive/    library code (parsers, collect, verify, api, ui)
schemas/                 meta.json JSON Schema
tests/                   pytest suite
scripts/                 CLI wrappers, automation handlers
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

To run the versioned Tier-3 tagger against the operational corpus, install its
optional model runtime and set the data root:

```bash
pip install -e ".[tagger]"
export FAA_WORKSPACE="$HOME/Library/CloudStorage/Dropbox/Pictures/Claude Project"
python scripts/vision_tag_works.py --limit 40
```

## Companion App

```bash
./scripts/run_companion_app.sh
# Browse at http://localhost:8401/
```

### Manifest

`manifest.csv` is the operator UI's only navigation path. `store.list_works()`
reads it and nothing else, so a work missing from it is served and rendered
correctly but cannot be reached, and therefore cannot be rated. It is generated,
not committed, and is rebuilt from the sidecar tree by:

```bash
python3 scripts/build_manifest.py
```

`./scripts/run_companion_app.sh` runs that on every launch, so browsing is
current as of the moment the app started. Anything else that adds, removes, or
retitles a work has to rebuild it too — including **promotion into
`Art/works/`, which happens outside this repository**. A promoter that writes a
work directory and does not run this script leaves that work unreachable; that
omission is what took the archive from 18 unfindable works on 2026-08-05 to all
3499 by 2026-09-01.

The rebuild is a full rewrite, ~1 s over 3499 works, so it is safe to run after
every promotion — there is no incremental path to keep in step with it.

- `--check` reports whether the manifest matches the tree and exits 1 if not,
  writing nothing. Use it to probe staleness from automation.
- `/healthz` reports `manifest_drift` and, when drifted, names this command in
  `manifest_remedy`.

## Coordinated with

- `stranske/Workflows` — auto-pilot CI/orchestration
- `stranske/Template` — repo scaffold this was cloned from
- `Dropbox/Pictures/Claude Project/` — data + sidecars + operations.log.
  The versioned Tier-3 tagger reads this operational corpus only when invoked
  with `FAA_WORKSPACE`; its implementation and policy live in this repository.
