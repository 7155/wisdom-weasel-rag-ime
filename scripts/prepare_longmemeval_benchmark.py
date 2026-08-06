#!/usr/bin/env python3
"""Prepare the pinned LongMemEval-S cleaned Memory benchmark locally."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.rag_benchmark_datasets import prepare_longmemeval_dataset  # noqa: E402


DATASET_REVISION = "98d7416c24c778c2fee6e6f3006e7a073259d48f"
SOURCE_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/"
    f"{DATASET_REVISION}/longmemeval_s_cleaned.json"
)
LICENSE_REFERENCE = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/"
    f"blob/{DATASET_REVISION}/README.md"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=(
            ROOT
            / ".rag-ime-data"
            / "public-benchmarks"
            / "longmemeval-cleaned"
            / "longmemeval_s_cleaned.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / ".rag-ime-data"
            / "prepared"
            / "rag-interview"
            / "longmemeval-s-cleaned.prepared.json"
        ),
    )
    parser.add_argument("--public-receipt", type=Path)
    parser.add_argument("--split-seed", default="paw-longmemeval-s-v1")
    args = parser.parse_args(argv)

    source = args.source.expanduser().resolve(strict=True)
    prepared = prepare_longmemeval_dataset(
        source,
        source_url=SOURCE_URL,
        version=f"hf:{DATASET_REVISION}; cleaned:2025-09",
        license_reference=LICENSE_REFERENCE,
        split_seed=str(args.split_seed),
    )
    output = args.output.expanduser().resolve(strict=False)
    _write_json(output, prepared)

    receipt = {
        "schemaVersion": "rag-ime.longmemeval-dataset-receipt.v1",
        "publication": "manifest_only_no_corpus_no_results",
        "manifest": prepared["manifest"],
        "adapter": prepared["adapter"],
        "sourceArtifact": {
            "fileName": source.name,
            "byteSize": source.stat().st_size,
            "sha256": prepared["manifest"]["sourceSha256"],
        },
    }
    if args.public_receipt is not None:
        _write_json(args.public_receipt.expanduser().resolve(strict=False), receipt)
    print(
        json.dumps(
            {
                "output": str(output),
                "manifest": prepared["manifest"],
                "adapter": prepared["adapter"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
