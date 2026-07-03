#!/usr/bin/env python3
from __future__ import annotations

import argparse
import heapq
import re
import unicodedata
from pathlib import Path


CURATED_ENGLISH_TERMS = [
    "agent",
    "api",
    "browser",
    "cache",
    "codex",
    "debug",
    "embedding",
    "github",
    "git",
    "hello",
    "http",
    "input",
    "javascript",
    "json",
    "llm",
    "markdown",
    "memory",
    "mlx",
    "model",
    "notion",
    "openai",
    "python",
    "qwen",
    "rag",
    "rime",
    "shell",
    "sqlite",
    "swift",
    "terminal",
    "typescript",
    "vector",
    "vscode",
    "world",
    "xcode",
    "yaml",
]


def normalize_pinyin(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in folded if ch.isalnum() and not unicodedata.combining(ch))


def initials_from_code(code: str) -> str:
    parts = re.split(r"[\s'_-]+", code.strip())
    return "".join((normalize_pinyin(part)[:1] for part in parts if normalize_pinyin(part)))


def commonness_penalty(text: str) -> int:
    penalty = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            continue
        if ch.isascii() and ch.isalnum():
            continue
        penalty += 1
    return penalty


def is_single_cjk(text: str) -> bool:
    return len(text) == 1 and "\u4e00" <= text <= "\u9fff"


def is_ascii_english_candidate(text: str, *, max_len: int) -> bool:
    if not 2 <= len(text) <= max_len:
        return False
    if not any(ch.isalpha() for ch in text):
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9+_.#-]*", text))


def import_tables(path: Path) -> list[str]:
    imports: list[str] = []
    in_imports = False
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line == "import_tables:":
            in_imports = True
            continue
        if not in_imports:
            continue
        if line.startswith("-"):
            table = line[1:].strip()
            if table:
                imports.append(table)
            continue
        if line:
            break
    return imports


def expand_dictionary(path: Path, visited: set[Path] | None = None) -> list[Path]:
    visited = visited or set()
    path = path.resolve()
    if path in visited:
        return []
    visited.add(path)
    imports = import_tables(path)
    if not imports:
        return [path]
    paths = [path]
    base = path.parent
    parent = base.parent
    for table in imports:
        candidates = [Path(table)] if table.startswith("/") else [
            base / f"{table}.dict.yaml",
            parent / f"{table}.dict.yaml",
        ]
        found = next((candidate for candidate in candidates if candidate.exists()), None)
        if found:
            paths.extend(expand_dictionary(found, visited))
    return paths


def body_rows(path: Path):
    in_body = False
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            trimmed = raw.strip()
            if trimmed == "...":
                in_body = True
                continue
            if not in_body or not trimmed or trimmed.startswith("#"):
                continue
            fields = raw.rstrip("\n").split("\t")
            if len(fields) < 2:
                continue
            yield fields


def load_essay_weights(path: Path | None) -> dict[str, float]:
    if path is None or not path.exists():
        return {}
    weights: dict[str, float] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw in fh:
            fields = raw.rstrip("\n").split("\t")
            if len(fields) < 2:
                continue
            text = fields[0].strip()
            try:
                weight = float(fields[1].strip())
            except ValueError:
                continue
            if text:
                weights[text] = max(weights.get(text, 0.0), weight)
    return weights


def push_candidate(
    index: dict[str, list[tuple[float, int, str, str, int]]],
    *,
    prefix: str,
    rank: float,
    order: int,
    text: str,
    comment: str,
    cap: int,
) -> None:
    if not prefix:
        return
    heap = index.setdefault(prefix, [])
    item = (-rank, -order, text, comment, order)
    if len(heap) < cap:
        heapq.heappush(heap, item)
    elif item > heap[0]:
        heapq.heapreplace(heap, item)


def add_prefixes(
    index: dict[str, list[tuple[float, int, str, str, int]]],
    *,
    value: str,
    exact_score: int,
    prefix_score: int,
    base_score: int,
    order: int,
    text: str,
    comment: str,
    cap: int,
    max_prefix_len: int,
    min_prefix_len: int = 1,
) -> None:
    if not value:
        return
    for length in range(max(1, min_prefix_len), min(len(value), max_prefix_len) + 1):
        prefix = value[:length]
        score = exact_score if length == len(value) else prefix_score
        rank = float(score * 1_000 + base_score)
        push_candidate(index, prefix=prefix, rank=rank, order=order, text=text, comment=comment, cap=cap)


def collect_entries(
    entrypoint: Path,
    max_text_len: int,
    essay_path: Path | None,
) -> list[tuple[float, float, int, str, str, str, str]]:
    paths = expand_dictionary(entrypoint)
    essay_weights = load_essay_weights(essay_path)
    seen_entry: set[tuple[str, str]] = set()
    entries: list[tuple[float, float, int, str, str, str, str]] = []
    order = 0
    label = "wanxiang" if "wanxiang" in str(entrypoint).lower() else "rime"
    for path in paths:
        for fields in body_rows(path):
            text = fields[0].strip()
            code_text = fields[1].strip()
            code = normalize_pinyin(code_text)
            if not text or not code:
                continue
            if len(text) > max_text_len:
                continue
            key = (text, code)
            if key in seen_entry:
                continue
            seen_entry.add(key)
            weight = 0.0
            for raw_weight in fields[2:]:
                try:
                    weight = float(raw_weight.strip())
                    break
                except ValueError:
                    continue
            weight = max(weight, essay_weights.get(text, 0.0))
            base_score = commonness_penalty(text) * 100 - min(weight, 999_999)
            initials = initials_from_code(code_text)
            selection_score = base_score + max(0, len(text) - 1) * 6
            entries.append((selection_score, base_score, order, text, code, initials, label))
            order += 1
    return entries


def collect_english_entries(
    entrypoint: Path | None,
    *,
    max_english_entries: int,
    max_english_text_len: int,
    start_order: int,
) -> list[tuple[float, float, int, str, str, str, str]]:
    rows: list[tuple[float, float, int, str, str, str, str]] = []
    seen: set[str] = set()
    if entrypoint is not None and entrypoint.exists():
        for path in expand_dictionary(entrypoint):
            for fields in body_rows(path):
                text = fields[0].strip()
                if not is_ascii_english_candidate(text, max_len=max_english_text_len):
                    continue
                code = normalize_pinyin(fields[1].strip() if len(fields) > 1 else text)
                normalized_text = normalize_pinyin(text)
                if not code:
                    code = normalized_text
                if not normalized_text or normalized_text in seen:
                    continue
                seen.add(normalized_text)
                base_score = commonness_penalty(text) * 100 + max(0, len(text) - 4) * 2
                rows.append((base_score, base_score, start_order + len(rows), text, code, "", "wanxiang_english"))
                if max_english_entries > 0 and len(rows) >= max_english_entries:
                    break
            if max_english_entries > 0 and len(rows) >= max_english_entries:
                break

    for term in CURATED_ENGLISH_TERMS:
        normalized = normalize_pinyin(term)
        if normalized in seen:
            continue
        seen.add(normalized)
        base_score = -50 + max(0, len(term) - 4) * 2
        rows.append((base_score, base_score, start_order + len(rows), term, normalized, "", "wanxiang_english"))

    return rows


def build_index(
    entrypoint: Path,
    output: Path,
    cap: int,
    max_prefix_len: int,
    max_text_len: int,
    max_entries: int,
    essay_path: Path | None,
    english_entrypoint: Path | None,
    max_english_entries: int,
    max_english_text_len: int,
    max_english_prefix_len: int,
) -> int:
    index: dict[str, list[tuple[float, int, str, str, int]]] = {}
    entries = collect_entries(entrypoint, max_text_len, essay_path)

    if max_entries > 0 and len(entries) > max_entries:
        single_chars = [entry for entry in entries if is_single_cjk(entry[3])]
        others = [entry for entry in entries if not is_single_cjk(entry[3])]
        remaining = max(0, max_entries - len(single_chars))
        selected = single_chars + sorted(others, key=lambda item: (item[0], item[2]))[:remaining]
        entries = selected

    entries.extend(
        collect_english_entries(
            english_entrypoint,
            max_english_entries=max_english_entries,
            max_english_text_len=max_english_text_len,
            start_order=len(entries),
        )
    )

    for _, base_score, order, text, code, initials, label in entries:
        is_english = label == "wanxiang_english"
        add_prefixes(
            index,
            value=code,
            exact_score=0,
            prefix_score=1,
            base_score=base_score,
            order=order,
            text=text,
            comment=label,
            cap=cap,
            max_prefix_len=max_english_prefix_len if is_english else max_prefix_len,
            min_prefix_len=2 if is_english else 1,
        )
        if not is_english:
            add_prefixes(
                index,
                value=initials,
                exact_score=2,
                prefix_score=3,
                base_score=base_score,
                order=order,
                text=text,
                comment=label,
                cap=cap,
                max_prefix_len=max_prefix_len,
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        fh.write("# rag-ime-rime-index-v1\tprefix\ttext\tcomment\tindex\n")
        for prefix in sorted(index):
            rows = sorted(index[prefix], key=lambda item: (-item[0], -item[1]))
            emitted: set[str] = set()
            rank = 1
            for neg_rank, neg_order, text, comment, original_order in rows:
                if text in emitted:
                    continue
                emitted.add(text)
                fh.write(f"{prefix}\t{text}\t{comment}\t{original_order}\n")
                rank += 1
                if rank > cap:
                    break
    return len(index)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dict-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cap", type=int, default=24)
    parser.add_argument("--max-prefix-len", type=int, default=18)
    parser.add_argument("--max-text-len", type=int, default=8)
    parser.add_argument("--max-entries", type=int, default=50_000)
    parser.add_argument("--english-dict")
    parser.add_argument("--max-english-entries", type=int, default=0)
    parser.add_argument("--max-english-text-len", type=int, default=32)
    parser.add_argument("--max-english-prefix-len", type=int, default=16)
    parser.add_argument("--essay-path")
    args = parser.parse_args()
    dict_dir = Path(args.dict_dir)
    entrypoint = dict_dir / "wanxiang.dict.yaml"
    if not entrypoint.exists():
        entrypoint = dict_dir / "luna_pinyin.dict.yaml"
    if not entrypoint.exists():
        raise SystemExit(f"missing Rime dictionary entrypoint under {dict_dir}")
    english_entrypoint = Path(args.english_dict) if args.english_dict else dict_dir / "wanxiang_english.dict.yaml"
    if not english_entrypoint.exists():
        english_entrypoint = None
    count = build_index(
        entrypoint,
        Path(args.output),
        args.cap,
        args.max_prefix_len,
        args.max_text_len,
        args.max_entries,
        Path(args.essay_path) if args.essay_path else None,
        english_entrypoint,
        args.max_english_entries,
        args.max_english_text_len,
        args.max_english_prefix_len,
    )
    print(f"wrote {count} prefixes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
