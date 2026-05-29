# Fine Art Archive

Code for the Fine Art Archive consumer repo. Operations and data live
separately in the Claude Project workspace under
`Dropbox/Pictures/Claude Project/`.

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

## Companion App

```bash
./scripts/run_companion_app.sh
# Browse at http://localhost:8401/
```

## Coordinated with

- `stranske/Workflows` — auto-pilot CI/orchestration
- `stranske/Template` — repo scaffold this was cloned from
- `Dropbox/Pictures/Claude Project/` — data + sidecars + operations.log
  (this repo never reads/writes that workspace directly; data flows
  through the Companion App API)
