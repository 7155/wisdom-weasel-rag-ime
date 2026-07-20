#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PI_ROOT=${ROOM_V2_PI_ROOT:-"$ROOT/../room-v2-lane-a-pi"}
PRODUCT_COMMIT=${ROOM_V2_PRODUCT_COMMIT:-a97f403}
PI_COMMIT=${ROOM_V2_PI_COMMIT:-c5484d96}
PEER_REVIEW_COMMIT=${ROOM_V2_PEER_REVIEW_COMMIT:-659c7ea}
REQUIREMENTS_UI_COMMIT=${ROOM_V2_REQUIREMENTS_UI_COMMIT:-7436c03}

git -C "$ROOT" merge-base --is-ancestor "$PRODUCT_COMMIT" HEAD
git -C "$PI_ROOT" merge-base --is-ancestor "$PI_COMMIT" HEAD
git -C "$ROOT" merge-base --is-ancestor "$PEER_REVIEW_COMMIT" HEAD
git -C "$ROOT" merge-base --is-ancestor "$REQUIREMENTS_UI_COMMIT" HEAD

cd "$ROOT"
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/rag-ime-uv-cache}
uv run python -m unittest \
  tests.test_room_v2_readiness \
  tests.test_agent_room_capabilities.RoomCapabilityManifestTests.test_progressive_search_discloses_catalog_then_loads_exactly_one_schema \
  tests.test_agent_room_capabilities.RoomCapabilityManifestTests.test_legacy_and_canonical_entry_share_one_authorization_receipt
node scripts/generate_control_center_contracts.mjs --check

printf '%s\n' "Room V2 readiness gate passed: commits, 65->88 migration, 135 contracts, capability receipts, default-off rollback, and no-binding smoke."
