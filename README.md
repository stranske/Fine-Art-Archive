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

## Coordinated with

- `stranske/Workflows` — auto-pilot CI/orchestration
- `stranske/Template` — repo scaffold this was cloned from
- `Dropbox/Pictures/Claude Project/` — data + sidecars + operations.log.
  The versioned Tier-3 tagger reads this operational corpus only when invoked
  with `FAA_WORKSPACE`; its implementation and policy live in this repository.
