#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SUPPORT_DIR="${RAG_IME_APP_SUPPORT_DIR:-$HOME/Library/Application Support/RagIme}"
RUNTIME_ROOT="${RAG_IME_MLX_RUNTIME_ROOT:-$APP_SUPPORT_DIR/components/mlx-predictor}"
VENV_DIR="${RAG_IME_MLX_VENV:-$RUNTIME_ROOT/.venv}"
PIP_CACHE_DIR="${RAG_IME_PIP_CACHE_DIR:-$HOME/Library/Caches/RagIme/pip}"
PYTHON_VERSION="${RAG_IME_MLX_PYTHON_VERSION:-3.13}"
UV_BIN="${UV_BIN:-$(command -v uv || true)}"

if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "uv is required to create the managed MLX predictor runtime" >&2
  exit 1
fi

mkdir -p "$RUNTIME_ROOT" "$PIP_CACHE_DIR"
chmod 700 "$RUNTIME_ROOT"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$UV_BIN" venv --python "$PYTHON_VERSION" "$VENV_DIR"
fi

REQUIREMENTS="$RUNTIME_ROOT/mlx-predictor-requirements.txt"
OVERLAY_REQUIREMENTS="$ROOT/scripts/mlx-predictor-overlay-requirements.txt"
UV_CACHE_DIR="$PIP_CACHE_DIR" "$UV_BIN" export \
  --project "$ROOT" \
  --frozen \
  --no-dev \
  --no-emit-project \
  --extra embedding-mlx \
  --output-file "$REQUIREMENTS" \
  >/dev/null
chmod 600 "$REQUIREMENTS"
# Converge the managed environment to the frozen base first. Unlike
# `pip install`, `pip sync` removes packages that disappeared from the lock,
# so an upgraded installation cannot retain an obsolete MLX dependency.
UV_CACHE_DIR="$PIP_CACHE_DIR" "$UV_BIN" pip sync \
  --python "$VENV_DIR/bin/python" \
  "$REQUIREMENTS"
UV_CACHE_DIR="$PIP_CACHE_DIR" "$UV_BIN" pip install \
  --python "$VENV_DIR/bin/python" \
  --no-deps \
  --requirement "$OVERLAY_REQUIREMENTS"
UV_CACHE_DIR="$PIP_CACHE_DIR" "$UV_BIN" pip check \
  --python "$VENV_DIR/bin/python"

"$VENV_DIR/bin/python" - <<'PY' >&2
import json
import sys

import mlx
import mlx_lm
import transformers

if sys.version_info < (3, 12):
    raise SystemExit(f"managed MLX runtime requires Python 3.12+, got {sys.version}")
print(
    json.dumps(
        {
            "ok": True,
            "python": sys.executable,
            "mlx": getattr(mlx, "__version__", ""),
            "mlxLm": getattr(mlx_lm, "__version__", ""),
            "transformers": getattr(transformers, "__version__", ""),
        },
        ensure_ascii=False,
    )
)
PY

printf '%s\n' "$VENV_DIR/bin/python"
