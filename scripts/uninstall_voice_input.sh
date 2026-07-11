#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARGS=(--component voice)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      ARGS+=(--apply)
      shift
      ;;
    --purge-credentials)
      ARGS+=(--purge-credentials --purge-voice-config)
      shift
      ;;
    -h|--help)
      echo "usage: $0 [--apply] [--purge-credentials]"
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      echo "usage: $0 [--apply] [--purge-credentials]" >&2
      exit 2
      ;;
  esac
done

exec python3 "$SCRIPT_DIR/uninstall_rag_ime.py" "${ARGS[@]}"
