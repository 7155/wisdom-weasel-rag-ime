#!/bin/bash
set -euo pipefail
RESOURCES="$(cd "$(dirname "$0")" && pwd)"
[[ "$(uname -m)" == arm64 ]] || { echo "此安装包需要 Apple Silicon Mac。"; exit 1; }
[[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 14 ]] || { echo "需要 macOS 14 或更高版本。"; exit 1; }
umask 077
BASE="$HOME/Library/Application Support/RagIme/InstallerGenerations"
LOGS="$HOME/Library/Logs/PAW Installer"
mkdir -p "$BASE" "$LOGS"
GENERATION="$(mktemp -d "$BASE/install.XXXXXX")"
LOG="$LOGS/$(basename "$GENERATION").log"
exec > >(tee -a "$LOG") 2>&1
echo "安装日志：$LOG"
echo "正在准备离线运行环境…"
/usr/bin/ditto "$RESOURCES/payload" "$GENERATION"
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME PYTHONPATH
exec "$GENERATION/python/bin/python3" "$GENERATION/source/scripts/install_binary_payload.py" --install "$GENERATION"
