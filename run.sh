#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./run.sh                 -> start server (play2go/prod style)
#   ./run.sh settings list   -> show current managed settings
#   ./run.sh settings set PORT 5000

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --disable-pip-version-check -q -r requirements.txt

if [[ "${1:-}" == "settings" ]]; then
  shift
  exec python3 app.py settings "$@"
fi

exec gunicorn \
  --bind "0.0.0.0:${PORT:-5000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-90}" \
  app:app
