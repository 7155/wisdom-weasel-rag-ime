#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
TRIGGER="${1:-${RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER:-scheduled}}"

if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "python executable not found or not executable: $PYTHON_EXECUTABLE" >&2
  exit 1
fi

export RAG_IME_MEMORY_BOOK_MAINTENANCE_TRIGGER="$TRIGGER"
exec "$PYTHON_EXECUTABLE" "$ROOT/scripts/memory_book_maintenance_launch.py"
