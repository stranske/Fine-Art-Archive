#!/usr/bin/env bash
# Launch the Fine Art Archive Companion App (FastAPI service) locally.
#
#   pip install -e ".[app]"          # installs uvicorn (the ASGI server)
#   ./scripts/run_companion_app.sh   # then browse http://127.0.0.1:8401/
#
# Environment:
#   FAA_APP_HOST         bind host (default 127.0.0.1)
#   FAA_APP_PORT         bind port (default 8401)
#   FAA_ART_WORKS_ROOT   promoted masters root (default ~/Library/CloudStorage/Dropbox/Pictures/Art/works)
#   FAA_WORKS_DIR        sidecar root (default ~/Library/CloudStorage/Dropbox/Pictures/Art/works)
#   FAA_STAGING_DIR      RETIRED name for FAA_WORKS_DIR, still honoured. D020 collapsed the
#                        two sidecar trees onto Art/works and quarantined ./staging_sidecars,
#                        so anything still setting this points the app at a tree that no
#                        longer exists — an empty archive, reported as an empty archive.
#   FAA_MANIFEST_CSV     flat manifest path (default ./manifest.csv)
#   FAA_RATINGS_LOG      ratings JSONL path (default ./data/ratings_log.jsonl)
#   FAA_IMAGE_CACHE_DIR  resized image cache (default ./data/image_cache)
# Extra args are passed through to uvicorn (e.g. --reload).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pin WHICH CHECKOUT serves. Two clones of this package exist on the operator's
# machine and the venv installs one of them editable, so `import
# fine_art_archive` is decided by an import race. That is not only a code
# question: api/config.py derives REPO_ROOT from the module's own location, so
# the losing clone also takes `data/artist_allowlist.jsonl` and
# `data/work_decisions.jsonl` with it -- and both loaders return an empty set
# for a file they cannot open.
#
# On 2026-09-02 a launch resolved to the install rather than this repo. 129
# artist decisions and 120 work decisions vanished in one step: the routed
# queue reported 116 items instead of 16 and asked the owner again for feedback
# he had already given, with every count on the page looking entirely
# plausible. Pinning it here, next to the REPO_ROOT that is already correct,
# means no caller has to remember.
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

HOST="${FAA_APP_HOST:-127.0.0.1}"
PORT="${FAA_APP_PORT:-8401}"

if ! python -c "import uvicorn" >/dev/null 2>&1; then
  echo "uvicorn is not installed. Run: pip install -e \".[app]\"" >&2
  exit 1
fi

# Rebuild the navigation index before serving. manifest.csv is the ONLY way the
# UI reaches a work, and promotion into Art/works/ happens outside this repo, so
# between two launches the archive can have grown by any number of works this
# process would otherwise never list. A full rebuild is ~1 s over 3499 works, so
# there is nothing to save by skipping it.
#
# Deliberately non-fatal: a failure here must not cost you the app. /healthz
# reports the resulting drift, and names this command as the remedy.
if ! python scripts/build_manifest.py; then
  echo "manifest rebuild failed; starting anyway — see /healthz for drift" >&2
fi

echo "Companion App → http://${HOST}:${PORT}/"
exec python -m uvicorn fine_art_archive.api.main:app --host "$HOST" --port "$PORT" "$@"
