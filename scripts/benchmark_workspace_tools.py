#!/usr/bin/env python3
"""Benchmark governed workspace search against subprocess ripgrep.

The runner first verifies result parity. Timing is reported only after both
backends produce the same normalized result checksum.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_workspace import WorkspaceHarness  # noqa: E402

SCHEMA_VERSION = "paw.workspace-tool-benchmark.v1"
SEED = 20260730
NEEDLE = "PAW_WORKSPACE_BENCH_NEEDLE_20260730"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--files", type=int, default=1_000)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def _generate(root: Path, files: int) -> None:
    if files < 1 or files > 50_000:
        raise ValueError("--files must be between 1 and 50000")
    root.mkdir(parents=True, exist_ok=True)
    for index in range(files):
        directory = root / f"group-{index % 32:02d}"
        directory.mkdir(exist_ok=True)
        marker = f"\n{NEEDLE}\n" if index % 97 == 0 else "\n"
        payload = (
            f"seed={SEED} file={index:05d}\n"
            f"alpha beta gamma {index % 19}\n"
            f"unicode=澄清-{index % 13}{marker}"
        )
        (directory / f"fixture-{index:05d}.txt").write_text(payload, encoding="utf-8")


def _corpus_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.txt")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _python_search(root: Path) -> list[tuple[str, int]]:
    session = {
        "id": "benchmark:workspace",
        "mode": "coordinator",
        "workspaceRoots": [str(root)],
    }
    result = WorkspaceHarness(executor=lambda _prepared: {}).search(
        session,
        {
            "query": NEEDLE,
            "path": str(root),
            "mode": "content",
            "patternKind": "literal",
            "caseSensitive": True,
            "limit": 100,
        },
    )
    normalized = []
    for item in result["matches"]:
        path = Path(str(item["path"]))
        normalized.append((path.relative_to(root).as_posix(), int(item["lineNumber"])))
    return sorted(normalized)


def _rg_search(root: Path) -> list[tuple[str, int]]:
    executable = shutil.which("rg")
    if executable is None:
        raise RuntimeError("ripgrep is unavailable")
    completed = subprocess.run(
        [
            executable,
            "--no-heading",
            "--line-number",
            "--fixed-strings",
            "--color",
            "never",
            "--glob",
            "*.txt",
            NEEDLE,
            str(root),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr.strip() or f"rg exited {completed.returncode}")
    normalized = []
    for line in completed.stdout.splitlines():
        raw_path, raw_line, _preview = line.split(":", 2)
        normalized.append(
            (Path(raw_path).relative_to(root).as_posix(), int(raw_line))
        )
    return sorted(normalized)


def _checksum(rows: list[tuple[str, int]]) -> str:
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _benchmark(
    backend: str,
    search: Callable[[Path], list[tuple[str, int]]],
    root: Path,
    *,
    warmup: int,
    repeat: int,
) -> dict[str, object]:
    for _ in range(warmup):
        search(root)
    samples_ms: list[float] = []
    cpu_ms: list[float] = []
    result: list[tuple[str, int]] = []
    for _ in range(repeat):
        child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_before = time.process_time()
        started = time.perf_counter()
        result = search(root)
        samples_ms.append((time.perf_counter() - started) * 1_000)
        child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu = (
            child_after.ru_utime
            + child_after.ru_stime
            - child_before.ru_utime
            - child_before.ru_stime
        )
        cpu_ms.append((time.process_time() - cpu_before + child_cpu) * 1_000)
    usage_kind = resource.RUSAGE_SELF if backend == "python" else resource.RUSAGE_CHILDREN
    raw_rss = resource.getrusage(usage_kind).ru_maxrss
    max_rss_bytes = int(raw_rss if sys.platform == "darwin" else raw_rss * 1_024)
    ordered = sorted(samples_ms)
    p95_index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1))
    return {
        "backend": backend,
        "samplesMs": [round(value, 3) for value in samples_ms],
        "cpuMs": [round(value, 3) for value in cpu_ms],
        "p50Ms": round(statistics.median(samples_ms), 3),
        "p95Ms": round(ordered[p95_index], 3),
        "maxRssBytes": max_rss_bytes,
        "result": {
            "checksumSha256": _checksum(result),
            "matches": len(result),
        },
    }


def main() -> int:
    args = _arguments()
    if args.repeat < 1 or args.repeat > 100 or args.warmup < 0 or args.warmup > 20:
        raise ValueError("invalid repeat or warmup count")
    owned = args.root is None
    temporary = tempfile.TemporaryDirectory(prefix="paw-workspace-benchmark-") if owned else None
    root = (
        Path(temporary.name).resolve()
        if temporary is not None
        else args.root.expanduser().resolve()
    )
    try:
        _generate(root, args.files)
        python_result = _benchmark(
            "python",
            _python_search,
            root,
            warmup=args.warmup,
            repeat=args.repeat,
        )
        rg_result = _benchmark(
            "rg-subprocess",
            _rg_search,
            root,
            warmup=args.warmup,
            repeat=args.repeat,
        )
        python_checksum = python_result["result"]["checksumSha256"]
        rg_checksum = rg_result["result"]["checksumSha256"]
        if python_checksum != rg_checksum:
            raise RuntimeError(
                "backend result mismatch: "
                f"python={python_checksum} rg={rg_checksum}"
            )
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "environment": {
                "os": platform.platform(),
                "arch": platform.machine(),
                "python": platform.python_version(),
                "cpuCount": os.cpu_count(),
            },
            "case": {
                "id": f"search.literal.sparse.{args.files}",
                "seed": SEED,
                "files": args.files,
                "corpusSha256": _corpus_sha256(root),
                "warmup": args.warmup,
                "repeat": args.repeat,
            },
            "parity": True,
            "backends": [python_result, rg_result],
            "p95Speedup": round(
                float(python_result["p95Ms"]) / max(float(rg_result["p95Ms"]), 0.001),
                3,
            ),
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.json_out is not None:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
