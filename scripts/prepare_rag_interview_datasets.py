#!/usr/bin/env python3
"""Prepare pinned local-only RAG and Agent interview benchmark receipts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rag_ime.rag_benchmark_datasets import (  # noqa: E402
    prepare_crud_rag_dataset,
    prepare_enterprise_rag_dataset,
    prepare_swe_bench_verified_dataset,
)


ENTERPRISE_REVISION = "69916e31c68aa5963c00248fd7f0bc12d04fd235"
CRUD_REVISION = "1aace383994e1f68efa12cf2a8e2dadfb4102ceb"
SWE_REVISION = "91aa3ed51b709be6457e12d00300a6a596d4c6a3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=REPO_ROOT / ".rag-ime-data" / "public-benchmarks",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / ".rag-ime-data" / "prepared" / "rag-interview",
    )
    parser.add_argument("--public-receipt", type=Path)
    parser.add_argument("--crud-distractors", type=int, default=5_000)
    parser.add_argument("--swe-interview-size", type=int, default=50)
    args = parser.parse_args(argv)

    source_root = args.source_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    enterprise = prepare_enterprise_rag_dataset(
        source_root / "enterpriserag-bench" / "data" / "questions" / "test.parquet",
        source_root / "enterpriserag-bench" / "data" / "documents" / "test.parquet",
        source_url=(
            "https://huggingface.co/datasets/onyx-dot-app/EnterpriseRAG-Bench"
        ),
        version=f"hf:{ENTERPRISE_REVISION}; release:v1.0.0",
        license_reference=(
            "https://github.com/onyx-dot-app/EnterpriseRAG-Bench/blob/v1.0.0/LICENSE"
        ),
        split_seed="paw-enterprise-rag-v1",
    )
    crud = prepare_crud_rag_dataset(
        source_root / "crud-rag" / "data" / "crud_split" / "split_merged.json",
        source_root / "crud-rag" / "data" / "80000_docs",
        source_url="https://github.com/IAAR-Shanghai/CRUD_RAG",
        version=f"git:{CRUD_REVISION}",
        license_reference=(
            "No explicit LICENSE file at the pinned revision; keep corpus local and "
            "research-only: https://github.com/IAAR-Shanghai/CRUD_RAG"
        ),
        split_seed="paw-crud-rag-v1",
        distractor_limit=args.crud_distractors,
    )
    swe = prepare_swe_bench_verified_dataset(
        source_root / "swe-bench-verified" / "data" / "test.parquet",
        source_url=(
            "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified"
        ),
        version=f"hf:{SWE_REVISION}",
        license_reference=(
            "Dataset card has no license field; task repositories retain their own "
            "licenses: https://www.swebench.com/SWE-bench/guides/datasets/"
        ),
        split_seed="paw-swe-bench-interview-v1",
        interview_size=args.swe_interview_size,
    )

    _write_json(output_root / "enterprise-rag.prepared.json", enterprise)
    _write_json(output_root / "crud-rag.prepared.json", crud)
    _write_json(output_root / "swe-bench-verified.prepared.json", swe)

    public_receipt = {
        "schemaVersion": "rag-ime.rag-interview-dataset-receipt.v1",
        "publication": "manifest_only_no_corpus_no_results",
        "enterprise": {
            "manifest": enterprise["manifest"],
            "adapter": enterprise["adapter"],
            "sourceArtifacts": enterprise["sourceArtifacts"],
        },
        "crud": {
            "manifest": crud["manifest"],
            "adapter": crud["adapter"],
            "sourceArtifacts": crud["sourceArtifacts"],
        },
        "sweBenchVerified": {
            "source": swe["source"],
            "adapter": swe["adapter"],
            "fullInstanceIds": swe["fullInstanceIds"],
            "fullSplitSha256": swe["fullSplitSha256"],
            "interviewInstanceIds": swe["interviewInstanceIds"],
            "interviewSplitSha256": swe["interviewSplitSha256"],
        },
    }
    _write_json(output_root / "public-dataset-receipt.v1.json", public_receipt)
    if args.public_receipt is not None:
        _write_json(args.public_receipt.resolve(), public_receipt)

    print(
        json.dumps(
            {
                "enterprise": enterprise["adapter"],
                "crud": crud["adapter"],
                "sweBenchVerified": swe["adapter"],
                "outputRoot": str(output_root),
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
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
