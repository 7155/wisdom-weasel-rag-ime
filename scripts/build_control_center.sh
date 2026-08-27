#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-build}"

case "$ACTION" in
  build|build-release)
    exec "$ROOT/scripts/build_paw_os_electron_host.sh" build-release
    ;;
  install|install-release)
    exec "$ROOT/scripts/build_paw_os_electron_host.sh" install-release
    ;;
  install-stack)
    shift || true
    exec "$ROOT/scripts/install_product_stack.sh" "$@"
    ;;
  *)
    echo "usage: $0 [build|install|build-release|install-release|install-stack]" >&2
    exit 2
    ;;
esac
