#!/usr/bin/env bash
set -euo pipefail

RIME_USER_DIR="${RAG_IME_RIME_USER_DIR:-$HOME/Library/Rime}"
TARGET="${RAG_IME_SICHUAN_FUZZY_TARGET:-$RIME_USER_DIR/luna_pinyin_simp.custom.yaml}"

python3 - "$TARGET" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


TARGET = Path(sys.argv[1]).expanduser()
BEGIN = "# rag-ime-managed-sichuan-fuzzy-pinyin: begin"
LEGACY = "# rag-ime-managed-sichuan-fuzzy-pinyin"
END = "# rag-ime-managed-sichuan-fuzzy-pinyin: end"
EXPECTED = {
    "z_zh": ["derive/^zh/z/", "derive/^z/zh/"],
    "c_ch": ["derive/^ch/c/", "derive/^c/ch/"],
    "s_sh": ["derive/^sh/s/", "derive/^s/sh/"],
    "en_eng": ["derive/eng$/en/", "derive/en$/eng/"],
    "in_ing": ["derive/ing$/in/", "derive/in$/ing/"],
}
FORBIDDEN = {
    "n_l": ["derive/^n/l/", "derive/^l/n/"],
    "f_h": ["derive/^h/f/", "derive/^f/h/"],
}


def managed_block(text: str) -> str:
    if BEGIN in text and END in text:
        return text[text.index(BEGIN) : text.index(END) + len(END)]
    if LEGACY in text:
        return text[text.index(LEGACY) :]
    return ""


def main() -> int:
    exists = TARGET.exists()
    text = TARGET.read_text(encoding="utf-8", errors="replace") if exists else ""
    block = managed_block(text)
    missing = [
        rule
        for rules in EXPECTED.values()
        for rule in rules
        if rule not in block
    ]
    forbidden_present = [
        rule
        for rules in FORBIDDEN.values()
        for rule in rules
        if rule in block
    ]
    enabled = {
        name: all(rule in block for rule in rules)
        for name, rules in EXPECTED.items()
    }
    disabled = {
        name: not any(rule in block for rule in rules)
        for name, rules in FORBIDDEN.items()
    }
    ok = exists and bool(block) and not missing and not forbidden_present
    payload = {
        "schemaVersion": "rag-ime.sichuan-fuzzy-check.v1",
        "ok": ok,
        "target": str(TARGET),
        "exists": exists,
        "managed": bool(block),
        "profile": "sichuan-mild",
        "enabled": enabled,
        "disabled": disabled,
        "missingRules": missing,
        "forbiddenRulesPresent": forbidden_present,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1


raise SystemExit(main())
PY
