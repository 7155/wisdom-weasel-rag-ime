#!/usr/bin/env bash
set -euo pipefail

RIME_USER_DIR="${RAG_IME_RIME_USER_DIR:-$HOME/Library/Rime}"
TARGET="${RAG_IME_SICHUAN_FUZZY_TARGET:-$RIME_USER_DIR/luna_pinyin_simp.custom.yaml}"
ENABLED="${RAG_IME_SICHUAN_FUZZY_PINYIN:-1}"
MODE="dry-run"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    *)
      echo "usage: $0 [--dry-run|--apply]" >&2
      exit 2
      ;;
  esac
done

python3 - "$TARGET" "$MODE" "$ENABLED" <<'PY'
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path


TARGET = Path(sys.argv[1]).expanduser()
MODE = sys.argv[2]
ENABLED = sys.argv[3].strip().lower()
BEGIN = "# rag-ime-managed-sichuan-fuzzy-pinyin: begin"
LEGACY = "# rag-ime-managed-sichuan-fuzzy-pinyin"
END = "# rag-ime-managed-sichuan-fuzzy-pinyin: end"


def bool_true(value: str) -> bool:
    return value in {"1", "true", "yes", "on"}


MANAGED_BLOCK = f"""{BEGIN}
# encoding: utf-8
#
# RAG-IME Sichuan mild fuzzy-pinyin profile.
# Rime still owns pinyin parsing; RAG-IME only installs this schema patch.
# Mild defaults: z_zh/c_ch/s_sh/en_eng/in_ing enabled; n_l/f_h disabled.

patch:
  switches/@next:
    name: rag_ime_sichuan_fuzzy
    reset: 1
    states: [精准, 四川模糊]

  speller/algebra:
    - derive/^zh/z/
    - derive/^z/zh/
    - derive/^ch/c/
    - derive/^c/ch/
    - derive/^sh/s/
    - derive/^s/sh/
    - derive/eng$/en/
    - derive/en$/eng/
    - derive/ing$/in/
    - derive/in$/ing/
    - abbrev/^([a-z]).+$/$1/
    - abbrev/^([zcs]h).+$/$1/
{END}
"""


def render_new_text(text: str) -> str:
    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        finish = text.index(END) + len(END)
        return text[:start].rstrip() + "\n\n" + MANAGED_BLOCK + text[finish:].lstrip()
    if LEGACY in text:
        start = text.index(LEGACY)
        return text[:start].rstrip() + "\n\n" + MANAGED_BLOCK
    if text.strip():
        return text.rstrip() + "\n\n" + MANAGED_BLOCK
    return MANAGED_BLOCK


def main() -> int:
    if not bool_true(ENABLED):
        payload = {
            "schemaVersion": "rag-ime.sichuan-fuzzy-apply.v1",
            "ok": True,
            "target": str(TARGET),
            "enabled": False,
            "dryRun": MODE != "apply",
            "applied": False,
            "changed": False,
            "backupPath": "",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    old_text = TARGET.read_text(encoding="utf-8", errors="replace") if TARGET.exists() else ""
    new_text = render_new_text(old_text)
    changed = old_text != new_text
    backup_path = ""
    applied = False
    if MODE == "apply" and changed:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        if TARGET.exists():
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            backup = TARGET.with_name(TARGET.name + f".rag-ime-before-sichuan-fuzzy-{timestamp}")
            shutil.copy2(TARGET, backup)
            backup_path = str(backup)
        TARGET.write_text(new_text, encoding="utf-8")
        applied = True
    payload = {
        "schemaVersion": "rag-ime.sichuan-fuzzy-apply.v1",
        "ok": True,
        "target": str(TARGET),
        "enabled": True,
        "profile": "sichuan-mild",
        "dryRun": MODE != "apply",
        "applied": applied,
        "changed": changed,
        "backupPath": backup_path,
        "enabledPairs": ["z_zh", "c_ch", "s_sh", "en_eng", "in_ing"],
        "disabledPairs": ["n_l", "f_h"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


raise SystemExit(main())
PY
