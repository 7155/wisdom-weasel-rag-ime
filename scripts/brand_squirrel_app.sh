#!/usr/bin/env bash
set -euo pipefail

APP="${1:-${RAG_IME_SQUIRREL_APP:-}}"
DEFAULT_BUNDLE_ID="im.rime.inputmethod.Squirrel"
BUNDLE_ID="${RAG_IME_SQUIRREL_BUNDLE_ID:-$DEFAULT_BUNDLE_ID}"
HANS_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_INPUT_SOURCE_ID:-$BUNDLE_ID.Hans}"
HANT_INPUT_SOURCE_ID="${RAG_IME_SQUIRREL_HANT_INPUT_SOURCE_ID:-$BUNDLE_ID.Hant}"
DISPLAY_NAME="${RAG_IME_SQUIRREL_DISPLAY_NAME:-澄输入法}"
if [[ "$DISPLAY_NAME" == "澄输入法" ]]; then
  DEFAULT_HANS_DISPLAY_NAME="澄输入法"
  DEFAULT_HANT_DISPLAY_NAME="澄输入法（繁体）"
else
  DEFAULT_HANS_DISPLAY_NAME="$DISPLAY_NAME - Simplified"
  DEFAULT_HANT_DISPLAY_NAME="$DISPLAY_NAME - Traditional"
fi
HANS_DISPLAY_NAME="${RAG_IME_SQUIRREL_HANS_DISPLAY_NAME:-$DEFAULT_HANS_DISPLAY_NAME}"
HANT_DISPLAY_NAME="${RAG_IME_SQUIRREL_HANT_DISPLAY_NAME:-$DEFAULT_HANT_DISPLAY_NAME}"
EXPECTED_CONNECTION_NAME="${BUNDLE_ID}_Connection"
CONNECTION_NAME="${RAG_IME_SQUIRREL_CONNECTION_NAME:-$EXPECTED_CONNECTION_NAME}"
PYTHON_EXECUTABLE="${RAG_IME_PYTHON:-$(command -v python3)}"

if [[ -z "$APP" ]]; then
  echo "usage: scripts/brand_squirrel_app.sh /path/to/Squirrel.app" >&2
  exit 64
fi

if [[ ! -d "$APP/Contents" ]]; then
  echo "app bundle not found: $APP" >&2
  exit 2
fi

if [[ -z "$PYTHON_EXECUTABLE" || ! -x "$PYTHON_EXECUTABLE" ]]; then
  echo "python3 is required to brand Squirrel.app" >&2
  exit 3
fi

if [[ "$CONNECTION_NAME" != "$EXPECTED_CONNECTION_NAME" ]]; then
  echo "InputMethodConnectionName must match <CFBundleIdentifier>_Connection" >&2
  echo "expected: $EXPECTED_CONNECTION_NAME" >&2
  echo "received: $CONNECTION_NAME" >&2
  exit 64
fi

"$PYTHON_EXECUTABLE" - \
  "$APP" \
  "$DEFAULT_BUNDLE_ID" \
  "$BUNDLE_ID" \
  "$HANS_INPUT_SOURCE_ID" \
  "$HANT_INPUT_SOURCE_ID" \
  "$DISPLAY_NAME" \
  "$HANS_DISPLAY_NAME" \
  "$HANT_DISPLAY_NAME" \
  "$CONNECTION_NAME" <<'PY'
from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

app = Path(sys.argv[1])
default_bundle_id = sys.argv[2]
bundle_id = sys.argv[3]
hans_id = sys.argv[4]
hant_id = sys.argv[5]
display_name = sys.argv[6]
hans_name = sys.argv[7]
hant_name = sys.argv[8]
connection_name = sys.argv[9]

info_path = app / "Contents" / "Info.plist"
if not info_path.exists():
    raise SystemExit(f"Info.plist missing: {info_path}")


def load_plist(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except Exception:
        converted = subprocess.run(
            ["/usr/bin/plutil", "-convert", "xml1", "-o", "-", str(path)],
            check=True,
            capture_output=True,
        ).stdout
        payload = plistlib.loads(converted)
    if not isinstance(payload, dict):
        raise SystemExit(f"plist root is not a dictionary: {path}")
    return payload


def dump_plist(path: Path, payload: dict[str, object]) -> None:
    with path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)


info = load_plist(info_path)
mode_dict = info.setdefault("ComponentInputModeDict", {})
if not isinstance(mode_dict, dict):
    raise SystemExit("ComponentInputModeDict is not a dictionary")
mode_list = mode_dict.setdefault("tsInputModeListKey", {})
if not isinstance(mode_list, dict):
    raise SystemExit("tsInputModeListKey is not a dictionary")

def find_mode(language: str, fallback_suffix: str) -> dict[str, object]:
    fallback_id = f"{default_bundle_id}.{fallback_suffix}"
    for key, value in mode_list.items():
        if isinstance(value, dict) and value.get("TISIntendedLanguage") == language:
            return dict(value)
    value = mode_list.get(fallback_id)
    if isinstance(value, dict):
        return dict(value)
    raise SystemExit(f"cannot find input mode for {language}")


hans = find_mode("zh-Hans", "Hans")
hant = find_mode("zh-Hant", "Hant")
hans["TISInputSourceID"] = hans_id
hant["TISInputSourceID"] = hant_id
hans["tsInputModeDefaultStateKey"] = True
hant["tsInputModeDefaultStateKey"] = False
for mode in (hans, hant):
    mode["tsInputModeMenuIconFileKey"] = "RagImeInputMenuIcon.png"
    mode["tsInputModeAlternateMenuIconFileKey"] = "RagImeInputMenuIcon.png"
    mode["tsInputModePaletteIconFileKey"] = "RagImeInputMenuIcon.png"

info["CFBundleIdentifier"] = bundle_id
info["CFBundleName"] = display_name
info["CFBundleDisplayName"] = display_name
info.pop("CFBundleIconName", None)
info["TISInputSourceID"] = bundle_id
info["InputMethodConnectionName"] = connection_name
# This is a patched product component, even when it keeps Squirrel's canonical
# bundle id. Sparkle must never replace it with an upstream unpatched build.
info["SUEnableAutomaticChecks"] = False
info["SUAutomaticallyUpdate"] = False

mode_dict["tsInputModeListKey"] = {
    hans_id: hans,
    hant_id: hant,
}
mode_dict["tsVisibleInputModeOrderedArrayKey"] = [hans_id, hant_id]
dump_plist(info_path, info)

resources = app / "Contents" / "Resources"
for strings_path in resources.glob("*.lproj/InfoPlist.strings"):
    payload = load_plist(strings_path)
    for key in [
        default_bundle_id,
        f"{default_bundle_id}.Hans",
        f"{default_bundle_id}.Hant",
        bundle_id,
        hans_id,
        hant_id,
    ]:
        payload.pop(key, None)
    payload["CFBundleName"] = display_name
    payload["CFBundleDisplayName"] = display_name
    payload[bundle_id] = display_name
    payload[hans_id] = hans_name
    payload[hant_id] = hant_name
    dump_plist(strings_path, payload)

print(f"branded_app={app}")
print(f"bundle_id={bundle_id}")
print(f"hans_input_source_id={hans_id}")
print(f"hant_input_source_id={hant_id}")
print(f"display_name={display_name}")
PY
