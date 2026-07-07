#!/usr/bin/env bash
# Wrapper — see export-brand-icons.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/venv/bin/python" "$ROOT/scripts/export-brand-icons.py"
