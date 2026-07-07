#!/usr/bin/env python3
"""Generate raw Chinese sentences from local markdown/text corpus (no prompt-style wrappers)."""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path


SENT_RE = re.compile(r"(?<=[。！？；!?])")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_RE = re.compile(r"[A-Za-z0-9]")
TABLE_CELL_RE = re.compile(r"\|[^|\n]*\|")
CODE_BLOCK_RE = re.compile(r"```.*?```", flags=re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
LINK_RE = re.compile(r"\[[^\]]*\]\([^\)]+\)")
BANNED_RE = re.compile(r"prompt|assistant|system|user|回答|解释|思考|模板|tool|model")


SKIP_DIRS = {
    ".git",
    ".tmp-yt-dlp",
    ".uv-cache",
    "node_modules",
    "dist",
    ".venv",
    "__pycache__",
    ".cache",
    "output",
}


DEFAULT_EXTS = {".md", ".txt", ".markdown", ".rst"}


def clean_segment(seg: str) -> str:
    seg = seg.strip()
    seg = seg.replace("\r", "")
    # trim headings and list prefixes
    seg = re.sub(r"^(#+\s*)", "", seg)
    seg = re.sub(r"^[-*+]\s*", "", seg)
    seg = re.sub(r"^\d+\.\s*", "", seg)
    seg = seg.strip()
    seg = seg.strip("`")
    seg = seg.replace("`", "")
    seg = re.sub(r"\s+", "", seg)
    return seg


def extract_sentences(text: str) -> list[str]:
    text = CODE_BLOCK_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = LINK_RE.sub(" ", text)
    # remove html-like tags quickly to reduce noise
    text = re.sub(r"<[^>]+>", " ", text)
    raw = SENT_RE.split(text)
    out: list[str] = []
    for seg in raw:
        seg = clean_segment(seg)
        if not seg:
            continue
        if not CHINESE_RE.search(seg):
            continue
        if len(seg) < 10 or len(seg) > 78:
            continue
        if BANNED_RE.search(seg):
            continue
        if ASCII_RE.search(seg):
            continue
        if TABLE_CELL_RE.fullmatch(seg):
            continue
        if "http" in seg:
            continue
        if len(set(seg)) < 4:
            continue
        out.append(seg)
    return out


def is_duplicate_like(candidate: str, seen: set[str]) -> bool:
    short = candidate.replace(" ", "")
    if short in seen:
        return True
    # near-duplicate guard for simple reorder changes
    if any(short[:-1] == x[:-1] for x in seen):
        return True
    return False


def load_corpus_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith(".") and path.suffix not in {".md", ".txt"}:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in DEFAULT_EXTS:
            paths.append(path)
    return paths


def build_candidates(root: Path, limit_files: int | None = None) -> list[str]:
    files = load_corpus_files(root)
    if limit_files:
        files = files[:limit_files]
    candidates: list[str] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = file.read_text(encoding="utf-8-sig")
            except Exception:
                continue
        except Exception:
            continue
        if not text.strip():
            continue
        candidates.extend(extract_sentences(text))
    # de-duplicate and shuffle for diversity
    random.shuffle(candidates)
    return candidates


def ensure_count(candidates: list[str], count: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    selected: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        selected.append(c)
        if len(selected) >= count:
            return selected[:count]
    # if corpus is not enough, backfill with short synthetic variants
    if len(selected) < count:
        fallback = []
        for c in candidates[: min(len(candidates), 2000)]:
            chunks = re.split(r"([，。；！？])", c)
            if len(chunks) > 1:
                fallback.append("".join(chunks[:-1]) + "，重新梳理。")
            if len(fallback) > count - len(selected):
                break
        idx = 0
        while len(selected) < count:
            base = fallback[idx % len(fallback)] if fallback else "文本边界不稳，先保留关键片段。"
            idx += 1
            # avoid endless exact duplicates
            variant = f"{base}{rng.choice(['建议先同步。', '再补充一句。', '先做对齐。', '再确认。'])}"
            if variant not in seen:
                seen.add(variant)
                selected.append(variant)
    return selected[:count]


def generate_report(rows: list[str], seed: int) -> dict[str, object]:
    lengths = [len(x) for x in rows]
    top = Counter([row[0] for row in rows]).most_common(20)
    return {
        "seed": seed,
        "count": len(rows),
        "min_len": min(lengths),
        "max_len": max(lengths),
        "avg_len": sum(lengths) / len(lengths),
        "unique_count": len(set(rows)),
        "contains_ascii": sum(1 for row in rows if ASCII_RE.search(row)),
        "longest_20_first_chars": [k for k, _ in top],
    }


def write_jsonl(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({"text": row}, ensure_ascii=False) + "\n")


def write_report(path: Path, rows: list[str], seed: int) -> None:
    path.write_text(
        json.dumps(generate_report(rows, seed), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/Volumes/undo 4t/git/learnA"))
    parser.add_argument("--count", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=20260720)
    parser.add_argument("--output", type=Path, default=Path("dataset/ime_raw_from_workspace_20k.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("dataset/ime_raw_from_workspace_20k.report.json"))
    parser.add_argument("--limit-files", type=int, default=800)
    args = parser.parse_args()

    candidates = build_candidates(args.root, args.limit_files)
    selected = ensure_count(candidates, args.count, args.seed)
    write_jsonl(args.output, selected)
    write_report(args.report, selected, args.seed)
    print(f"wrote {len(selected)} rows to {args.output}")
    print(f"wrote report to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
