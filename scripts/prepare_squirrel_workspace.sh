#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQUIRREL_REPO_URL="${RAG_IME_SQUIRREL_REPO_URL:-https://github.com/rime/squirrel.git}"
SQUIRREL_BASE_REF="${RAG_IME_SQUIRREL_BASE_REF:-2158538}"
SQUIRREL_WORKDIR="${RAG_IME_SQUIRREL_WORKDIR:-/tmp/rag-ime-squirrel}"
PATCH_FILE="${RAG_IME_SQUIRREL_PATCH:-$ROOT/squirrel-patches/0001-add-rag-ime-sidecar.patch}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"
DB_PATH="${RAG_IME_DB_PATH:-$ROOT/.rag-ime-data/rag-ime.sqlite}"
PROJECT="${RAG_IME_PROJECT:-wisdom-weasel-rag-ime}"
SIDECAR_HOST="${RAG_IME_SIDECAR_HOST:-127.0.0.1}"
SIDECAR_PORT="${RAG_IME_SIDECAR_PORT:-8766}"
RESET="${RAG_IME_SQUIRREL_RESET:-0}"
DRY_RUN="${RAG_IME_SQUIRREL_DRY_RUN:-0}"

if [[ ! -f "$PATCH_FILE" ]]; then
  echo "patch file not found: $PATCH_FILE" >&2
  exit 1
fi

if [[ "$DRY_RUN" == "1" || "$DRY_RUN" == "true" || "$DRY_RUN" == "TRUE" ]]; then
  cat <<EOF
repo_url=$SQUIRREL_REPO_URL
base_ref=$SQUIRREL_BASE_REF
workdir=$SQUIRREL_WORKDIR
patch=$PATCH_FILE
sidecar_url=http://$SIDECAR_HOST:$SIDECAR_PORT/api
repo_root=$ROOT
db_path=$DB_PATH
python=$PYTHON_EXECUTABLE
project=$PROJECT
EOF
  exit 0
fi

if [[ -e "$SQUIRREL_WORKDIR" && ! -d "$SQUIRREL_WORKDIR/.git" ]]; then
  echo "target exists but is not a git checkout: $SQUIRREL_WORKDIR" >&2
  exit 1
fi

if [[ ! -d "$SQUIRREL_WORKDIR/.git" ]]; then
  mkdir -p "$(dirname "$SQUIRREL_WORKDIR")"
  git clone "$SQUIRREL_REPO_URL" "$SQUIRREL_WORKDIR"
fi

if [[ -n "$(git -C "$SQUIRREL_WORKDIR" status --short)" && "$RESET" != "1" ]]; then
  echo "Squirrel workdir has local changes: $SQUIRREL_WORKDIR" >&2
  echo "Set RAG_IME_SQUIRREL_RESET=1 to discard changes in that Squirrel workdir." >&2
  exit 1
fi

git -C "$SQUIRREL_WORKDIR" fetch --tags --quiet origin || true
git -C "$SQUIRREL_WORKDIR" checkout "$SQUIRREL_BASE_REF" --quiet
git -C "$SQUIRREL_WORKDIR" reset --hard "$SQUIRREL_BASE_REF" --quiet
git -C "$SQUIRREL_WORKDIR" clean -fd --quiet
git -C "$SQUIRREL_WORKDIR" apply --check "$PATCH_FILE"
git -C "$SQUIRREL_WORKDIR" apply "$PATCH_FILE"
git -C "$SQUIRREL_WORKDIR" diff --check

require_patch_file() {
  local path="$1"
  if [[ ! -f "$SQUIRREL_WORKDIR/$path" ]]; then
    echo "patched Squirrel workdir is missing required RAG-IME file: $path" >&2
    exit 1
  fi
}

require_patch_text() {
  local path="$1"
  local text="$2"
  local description="$3"
  if ! grep -Fq "$text" "$SQUIRREL_WORKDIR/$path"; then
    echo "patched Squirrel workdir is missing $description in $path" >&2
    exit 1
  fi
}

require_patch_file "sources/RagImeSidecarModels.swift"
require_patch_file "sources/RagImeSidecarClient.swift"
require_patch_file "sources/SquirrelInputController.swift"
require_patch_text "sources/RagImeSidecarClient.swift" "rime-suggest" "sidecar suggestion request hook"
require_patch_text "sources/RagImeSidecarClient.swift" "rime-select" "side candidate selection writeback hook"
require_patch_text "sources/SquirrelInputController.swift" "selectRagImeSideCandidate" "number-key side-candidate routing"
require_patch_text "sources/SquirrelInputController.swift" "ragImeRequestFingerprint" "stale response fingerprint guard"
require_patch_text "sources/SquirrelInputController.swift" "mergedRagImePanelCandidates" "Rime and side candidate display merge"

CONFIG_PATH="$SQUIRREL_WORKDIR/rag-ime.squirrel.custom.yaml"
ROOT="$ROOT" \
DB_PATH="$DB_PATH" \
PYTHON_EXECUTABLE="$PYTHON_EXECUTABLE" \
PROJECT="$PROJECT" \
SIDECAR_HOST="$SIDECAR_HOST" \
SIDECAR_PORT="$SIDECAR_PORT" \
CONFIG_PATH="$CONFIG_PATH" \
"$PYTHON_EXECUTABLE" - <<'PY'
import os
from pathlib import Path

payload = f"""# Copy this rag_ime block into squirrel.yaml while testing RAG-IME.
rag_ime:
  enabled: true
  sidecar_url: http://{os.environ["SIDECAR_HOST"]}:{os.environ["SIDECAR_PORT"]}/api
  python: {os.environ["PYTHON_EXECUTABLE"]}
  repo_root: {os.environ["ROOT"]}
  db_path: {os.environ["DB_PATH"]}
  project: {os.environ["PROJECT"]}
  max_visible_candidates: 8
  max_side_candidates: 2
  latency_budget_ms: 180
  debounce_ms: 40
  timeout_ms: 1200
"""
Path(os.environ["CONFIG_PATH"]).write_text(payload, encoding="utf-8")
PY

if command -v swiftc >/dev/null 2>&1; then
  tmpdir="$(mktemp -d /tmp/rag-ime-squirrel-stub.XXXXXX)"
  stubfile="$tmpdir/SquirrelConfigStub.swift"
  printf 'import Foundation\nfinal class SquirrelConfig {\n  func getBool(_ option: String) -> Bool? { nil }\n  func getString(_ option: String) -> String? { nil }\n  func getDouble(_ option: String) -> Double? { nil }\n}\n' > "$stubfile"
  swiftc -typecheck \
    "$SQUIRREL_WORKDIR/sources/RagImeSidecarModels.swift" \
    "$SQUIRREL_WORKDIR/sources/RagImeSidecarClient.swift" \
    "$stubfile"
  rm -rf "$tmpdir"
fi

cat <<EOF
Prepared patched Squirrel workdir:
$SQUIRREL_WORKDIR

Generated config snippet:
$CONFIG_PATH

Start sidecar:
cd "$ROOT" && scripts/install_sidecar_launch_agent.sh

Then copy the rag_ime block into Squirrel's squirrel.yaml and build Squirrel with Xcode.
EOF
