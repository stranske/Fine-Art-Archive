#!/usr/bin/env bash
# Launch the Fine Art Archive Companion App (FastAPI service) locally.
#
#   pip install -e ".[app]"          # installs uvicorn (the ASGI server)
#   ./scripts/run_companion_app.sh   # then browse http://127.0.0.1:8401/
#
# Environment:
#   FAA_APP_HOST   bind host (default 127.0.0.1)
#   FAA_APP_PORT   bind port (default 8401)
# Extra args are passed through to uvicorn (e.g. --reload).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

HOST="${FAA_APP_HOST:-127.0.0.1}"
PORT="${FAA_APP_PORT:-8401}"

if ! python -c "import uvicorn" >/dev/null 2>&1; then
  echo "uvicorn is not installed. Run: pip install -e \".[app]\"" >&2
  exit 1
fi

echo "Companion App → http://${HOST}:${PORT}/"
exec python -m uvicorn fine_art_archive.api.main:app --host "$HOST" --port "$PORT" "$@"
