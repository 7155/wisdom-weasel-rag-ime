#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIP_CACHE_DIR="${RAG_IME_PIP_CACHE_DIR:-$ROOT/.pip-cache}"
PACKAGE="${RAG_IME_MLX_PACKAGE:-mlx-lm}"

detect_python() {
  local candidate
  for candidate in "$(command -v python3 2>/dev/null || true)" "$(command -v python3.13 2>/dev/null || true)"; do
    if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

python_has_mlx() {
  "$1" -c 'import mlx.core' >/dev/null 2>&1
}

PYTHON="${RAG_IME_MLX_SETUP_PYTHON:-$(detect_python || true)}"
if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
  echo "Python executable not found: $PYTHON" >&2
  exit 1
fi

"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "Python 3.11+ is required for MLX setup: $PYTHON" >&2
  exit 1
}

USE_SYSTEM_SITE_PACKAGES="${RAG_IME_MLX_USE_SYSTEM_SITE_PACKAGES:-auto}"
if [[ "$USE_SYSTEM_SITE_PACKAGES" == "auto" ]]; then
  if python_has_mlx "$PYTHON"; then
    USE_SYSTEM_SITE_PACKAGES=1
  else
    USE_SYSTEM_SITE_PACKAGES=0
  fi
fi

if [[ -n "${RAG_IME_MLX_VENV:-}" ]]; then
  VENV_DIR="$RAG_IME_MLX_VENV"
elif [[ "$USE_SYSTEM_SITE_PACKAGES" == "1" || "$USE_SYSTEM_SITE_PACKAGES" == "true" || "$USE_SYSTEM_SITE_PACKAGES" == "TRUE" ]]; then
  VENV_DIR="$ROOT/.venv-mlx314sys"
else
  VENV_DIR="$ROOT/.venv-mlx313"
fi

mkdir -p "$PIP_CACHE_DIR"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  if [[ "$USE_SYSTEM_SITE_PACKAGES" == "1" || "$USE_SYSTEM_SITE_PACKAGES" == "true" || "$USE_SYSTEM_SITE_PACKAGES" == "TRUE" ]]; then
    "$PYTHON" -m venv --system-site-packages "$VENV_DIR"
  else
    "$PYTHON" -m venv "$VENV_DIR"
  fi
fi

pip_no_proxy() {
  env \
    -u PIP_PROXY \
    -u HTTP_PROXY \
    -u HTTPS_PROXY \
    -u ALL_PROXY \
    -u FTP_PROXY \
    -u WSS_PROXY \
    -u WS_PROXY \
    -u http_proxy \
    -u https_proxy \
    -u all_proxy \
    -u ftp_proxy \
    -u wss_proxy \
    -u ws_proxy \
    PIP_CACHE_DIR="$PIP_CACHE_DIR" \
    "$VENV_DIR/bin/python" -m pip "$@"
}

if python_has_mlx "$VENV_DIR/bin/python"; then
  pip_no_proxy install --no-deps "$PACKAGE"
  pip_no_proxy install "transformers>=5.0.0" sentencepiece protobuf pyyaml jinja2
else
  pip_no_proxy install "$PACKAGE"
fi

"$VENV_DIR/bin/python" - <<'PY'
import mlx_lm
print(f"mlx-lm import OK: {getattr(mlx_lm, '__file__', '')}")
PY

echo "$VENV_DIR/bin/python"
