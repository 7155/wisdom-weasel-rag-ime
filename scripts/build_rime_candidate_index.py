#!/usr/bin/env python3
from __future__ import annotations

import argparse
import heapq
import re
import unicodedata
from pathlib import Path


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
) -> None:
    if not value:
        return
    for length in range(1, min(len(value), max_prefix_len) + 1):
        prefix = value[:length]
        score = exact_score if length == len(value) else prefix_score
        rank = float(score * 1_000 + base_score)
        push_candidate(index, prefix=prefix, rank=rank, order=order, text=text, comment=comment, cap=cap)


def build_index(
    entrypoint: Path,
    output: Path,
    cap: int,
    max_prefix_len: int,
    max_text_len: int,
    max_entries: int,
    essay_path: Path | None,
) -> int:
    paths = expand_dictionary(entrypoint)
    essay_weights = load_essay_weights(essay_path)
    index: dict[str, list[tuple[float, int, str, str, int]]] = {}
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

    if max_entries > 0 and len(entries) > max_entries:
        single_chars = [entry for entry in entries if is_single_cjk(entry[3])]
        others = [entry for entry in entries if not is_single_cjk(entry[3])]
        remaining = max(0, max_entries - len(single_chars))
        selected = single_chars + sorted(others, key=lambda item: (item[0], item[2]))[:remaining]
        entries = selected

    for _, base_score, order, text, code, initials, label in entries:
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
            max_prefix_len=max_prefix_len,
        )
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
    parser.add_argument("--essay-path")
    args = parser.parse_args()
    dict_dir = Path(args.dict_dir)
    entrypoint = dict_dir / "wanxiang.dict.yaml"
    if not entrypoint.exists():
        entrypoint = dict_dir / "luna_pinyin.dict.yaml"
    if not entrypoint.exists():
        raise SystemExit(f"missing Rime dictionary entrypoint under {dict_dir}")
    count = build_index(
        entrypoint,
        Path(args.output),
        args.cap,
        args.max_prefix_len,
        args.max_text_len,
        args.max_entries,
        Path(args.essay_path) if args.essay_path else None,
    )
    print(f"wrote {count} prefixes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
