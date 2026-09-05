#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

exec python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload "$@"
