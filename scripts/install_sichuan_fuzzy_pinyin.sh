#!/usr/bin/env bash
set -euo pipefail

RIME_USER_DIR="${RAG_IME_RIME_USER_DIR:-$HOME/Library/Rime}"
ENABLED="${RAG_IME_SICHUAN_FUZZY_PINYIN:-1}"
TARGET="$RIME_USER_DIR/luna_pinyin_simp.custom.yaml"
MARKER="# rag-ime-managed-sichuan-fuzzy-pinyin"

bool_true() {
  [[ "$1" == "1" || "$1" == "true" || "$1" == "TRUE" || "$1" == "yes" || "$1" == "YES" || "$1" == "on" || "$1" == "ON" ]]
}

if ! bool_true "$ENABLED"; then
  printf '[OK] Sichuan fuzzy pinyin disabled by RAG_IME_SICHUAN_FUZZY_PINYIN=%s\n' "$ENABLED"
  exit 0
fi

mkdir -p "$RIME_USER_DIR"

if [[ -f "$TARGET" ]] && ! grep -Fq "$MARKER" "$TARGET"; then
  backup="$TARGET.rag-ime-before-sichuan-fuzzy-$(date +%Y%m%d-%H%M%S)"
  cp "$TARGET" "$backup"
  printf '[OK] backed up existing luna_pinyin_simp.custom.yaml: %s\n' "$backup"
fi

cat >"$TARGET" <<'YAML'
# rag-ime-managed-sichuan-fuzzy-pinyin
# encoding: utf-8
#
# Default RAG-IME Simplified Chinese profile for Sichuan-style fuzzy pinyin.
# Rime still owns pinyin parsing; RAG-IME only installs this schema patch.

patch:
  switches/@next:
    name: rag_ime_sichuan_fuzzy
    reset: 1
    states: [精准, 四川模糊]

  speller/algebra:
    # z/zh, c/ch, s/sh are common Southwestern Mandarin fuzzy pairs.
    - derive/^zh/z/
    - derive/^z/zh/
    - derive/^ch/c/
    - derive/^c/ch/
    - derive/^sh/s/
    - derive/^s/sh/

    # n/l and h/f are commonly confused by Sichuan users.
    - derive/^n/l/
    - derive/^l/n/
    - derive/^h/f/
    - derive/^f/h/

    # eng/en, ing/in, ang/an are useful nasal finals for fuzzy input.
    - derive/eng$/en/
    - derive/en$/eng/
    - derive/ing$/in/
    - derive/in$/ing/
    - derive/ang$/an/
    - derive/an$/ang/

    # Preserve convenient initials and partial pinyin behavior.
    - abbrev/^([a-z]).+$/$1/
    - abbrev/^([zcs]h).+$/$1/
YAML

printf '[OK] installed Sichuan fuzzy pinyin profile: %s\n' "$TARGET"
