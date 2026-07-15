#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-build}"

case "$ACTION" in
  build|build-release)
    exec "$ROOT/scripts/build_control_center_web_host.sh" build-release
    ;;
  install|install-release)
    exec "$ROOT/scripts/build_control_center_web_host.sh" install-release
    ;;
  *)
    echo "usage: $0 [build|install|build-release|install-release]" >&2
    exit 2
    ;;
esac
