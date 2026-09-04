#!/usr/bin/env python3
"""List the bounded Agent Lab receipts required by an installed ledger."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Iterator


_RUN_REF_PREFIX = "eval/interview-metrics/runs/"
_OPTIMAL_PATH_GLOB = "agent-lab-optimal-path-*.json"


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _verified_receipt(path: Path, runs_root: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"invalid Agent Lab evidence ref: {label}") from error
    if path.is_symlink() or resolved.parent != runs_root or not resolved.is_file():
        raise ValueError(f"invalid Agent Lab evidence ref: {label}")
    return resolved


def required_receipts(ledger_path: Path) -> tuple[Path, ...]:
    ledger = ledger_path.resolve(strict=True)
    repository_root = ledger.parents[2]
    runs_root = (repository_root / "eval" / "interview-metrics" / "runs").resolve(strict=True)
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    receipts: set[Path] = set()

    for value in set(_strings(payload)):
        if not value.startswith(_RUN_REF_PREFIX):
            continue
        if not value.endswith(".json"):
            raise ValueError(f"invalid Agent Lab evidence ref: {value}")
        receipts.add(_verified_receipt(repository_root / value, runs_root, value))

    for path in runs_root.glob(_OPTIMAL_PATH_GLOB):
        receipts.add(_verified_receipt(path, runs_root, path.name))

    return tuple(sorted(receipts, key=lambda path: path.name))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: list_agent_lab_install_receipts.py LEDGER", file=sys.stderr)
        return 2
    try:
        receipts = required_receipts(Path(argv[1]))
    except (json.JSONDecodeError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    for receipt in receipts:
        print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
