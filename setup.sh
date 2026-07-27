#!/usr/bin/env bash
# One-command setup: create a virtualenv, install deps, build the index.
# Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

# Find a Python 3.11+ interpreter (tomllib + modern MCP SDK need it).
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,11) else 1)'; then
      PY="$c"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "Need Python 3.11 or newer. Install it and re-run." >&2
  exit 1
fi
echo "Using $($PY --version)"

[ -d .venv ] || "$PY" -m venv .venv
./.venv/bin/python -m pip install -q --upgrade pip
./.venv/bin/python -m pip install -q -r requirements.txt

# First index build (downloads the embedding model once, ~200MB).
./.venv/bin/python ingest.py

cat <<'DONE'

Setup complete.

  Add docs      : drop .md/.txt in inbox/, then  make add
  Index         : make index
  Search server : registered via .mcp.json — run Claude Code here, check /mcp
  Promote       : make promote name=<doc>

DONE
