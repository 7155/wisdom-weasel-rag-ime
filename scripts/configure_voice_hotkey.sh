#!/usr/bin/env bash
set -euo pipefail

choice="${1:-middle_mouse}"
case "$choice" in
  middle_mouse|right_option|option_space) ;;
  *)
    echo "usage: $0 [middle_mouse|right_option|option_space]" >&2
    exit 2
    ;;
esac

config_dir="$HOME/Library/Application Support/RagIme"
config_path="$config_dir/voice-hotkey.json"
tmp_path="$config_path.tmp.$$"

umask 077
mkdir -p "$config_dir"
printf '{"schemaVersion":"rag-ime.voice-hotkey.v1","choice":"%s"}\n' "$choice" > "$tmp_path"
chmod 600 "$tmp_path"
mv "$tmp_path" "$config_path"

echo "$config_path"
