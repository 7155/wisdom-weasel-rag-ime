#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-status}"
shift || true
ALLOWED_LOGINS="${RAG_IME_REMOTE_ALLOWED_LOGINS:-}"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  scripts/configure_agent_gateway_tailscale.sh enable [--login user@example.com] [--dry-run]
  scripts/configure_agent_gateway_tailscale.sh disable [--dry-run]
  scripts/configure_agent_gateway_tailscale.sh status

This configures tailnet-only HTTPS for the existing loopback Agent Gateway.
It never enables Tailscale Funnel.
EOF
}

while (($#)); do
  case "$1" in
    --login)
      [[ $# -ge 2 ]] || { echo "--login requires a value" >&2; exit 2; }
      ALLOWED_LOGINS="${ALLOWED_LOGINS:+$ALLOWED_LOGINS,}$2"
      shift
      ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$ACTION" in
  enable|disable|status) ;;
  *) usage >&2; exit 2 ;;
esac

TAILSCALE="${RAG_IME_TAILSCALE:-$(command -v tailscale 2>/dev/null || true)}"
if [[ -z "$TAILSCALE" || ! -x "$TAILSCALE" ]]; then
  echo "tailscale CLI is unavailable" >&2
  exit 1
fi

detect_login() {
  "$TAILSCALE" status --json | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
self_node = payload.get("Self") or {}
user_id = str(self_node.get("UserID") or "")
users = payload.get("User") or {}
user = users.get(user_id) or users.get(int(user_id) if user_id.isdigit() else user_id) or {}
print(str(user.get("LoginName") or "").strip())
'
}

validate_logins() {
  python3 - "$1" <<'PY'
import sys

values = [value.strip() for value in sys.argv[1].split(",") if value.strip()]
if not values:
    raise SystemExit("at least one Tailscale login is required")
for value in values:
    if len(value) > 320 or any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise SystemExit(f"invalid Tailscale login: {value!r}")
print(",".join(dict.fromkeys(values)))
PY
}

if [[ "$ACTION" == "status" ]]; then
  "$TAILSCALE" serve status
  exit 0
fi

if [[ "$ACTION" == "disable" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "$TAILSCALE serve --https=443 off"
    exit 0
  fi
  "$TAILSCALE" serve --https=443 off
  echo "Agent Gateway Tailscale Serve route disabled; loopback :8768 remains available."
  exit 0
fi

if [[ -z "$ALLOWED_LOGINS" ]]; then
  ALLOWED_LOGINS="$(detect_login)"
fi
ALLOWED_LOGINS="$(validate_logins "$ALLOWED_LOGINS")"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "RAG_IME_REMOTE_ALLOWED_LOGINS=$ALLOWED_LOGINS scripts/install_agent_gateway_launch_agent.sh"
  echo "$TAILSCALE serve --bg --yes http://127.0.0.1:8768"
  exit 0
fi

RAG_IME_REMOTE_ALLOWED_LOGINS="$ALLOWED_LOGINS" \
  "$ROOT/scripts/install_agent_gateway_launch_agent.sh"
"$TAILSCALE" serve --bg --yes http://127.0.0.1:8768

echo "Allowed Tailscale login(s): $ALLOWED_LOGINS"
"$TAILSCALE" serve status
