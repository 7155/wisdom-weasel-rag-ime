#!/usr/bin/env python3
"""Benchmark small local embedding models on RAG-IME retrieval cases."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import psutil
MODELS = {
    "piccolo": ("sensenova/piccolo-base-zh", "查询：", "结果："),
    "bge": ("BAAI/bge-base-zh-v1.5", "为这个句子生成表示以用于检索相关文章：", ""),
    "m3e": ("moka-ai/m3e-base", "", ""),
    "granite": ("ibm-granite/granite-embedding-97m-multilingual-r2", "", ""),
    "bge-mlx-q8": (
        str(Path.home() / "Library/Application Support/RagIme/Models/bge-base-zh-v1.5-mlx-q8"),
        "为这个句子生成表示以用于检索相关文章：",
        "",
    ),
    "bge-mlx-fp16": (
        str(Path.home() / "Library/Application Support/RagIme/Models/bge-base-zh-v1.5-mlx-fp16"),
        "为这个句子生成表示以用于检索相关文章：",
        "",
    ),
}


@dataclass(frozen=True)
class Case:
    case_id: str
    query: str
    relevant: tuple[str, ...]
    group: str


def load_cases(path: Path) -> tuple[list[dict[str, str]], list[Case]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    documents = [row for row in rows if row.get("type") == "document"]
    cases = [
        Case(
            case_id=str(row["id"]),
            query=str(row["query"]),
            relevant=tuple(str(value) for value in row["relevant"]),
            group=str(row["group"]),
        )
        for row in rows
        if row.get("type") == "query"
    ]
    if not documents or not cases:
        raise ValueError("cases file must contain document and query rows")
    return documents, cases


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values), q))


def benchmark(name: str, spec: tuple[str, str, str], documents: list[dict[str, str]], cases: list[Case], batch_size: int) -> dict[str, object]:
    model_id, query_prefix, document_prefix = spec
    process = psutil.Process(os.getpid())
    load_started = time.perf_counter()
    if name.startswith("bge-mlx-"):
        from rag_ime.embeddings import MlxBertEmbeddingProvider

        model = MlxBertEmbeddingProvider(
            model=model_id, query_prefix=query_prefix, document_prefix=document_prefix,
            bits=8 if name.endswith("q8") else 0, group_size=32,
        )
        model._load_model()
        encode_documents = lambda texts: np.asarray([model.embed(text) for text in texts])
        encode_query = lambda text: np.asarray(model.embed_query(text))
    else:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_id, trust_remote_code=False)
        encode_documents = lambda texts: model.encode(
            [document_prefix + text for text in texts], batch_size=batch_size,
            normalize_embeddings=True, show_progress_bar=False,
        )
        encode_query = lambda text: model.encode(
            query_prefix + text, normalize_embeddings=True, show_progress_bar=False,
        )
    load_ms = (time.perf_counter() - load_started) * 1000
    rss_loaded = process.memory_info().rss

    document_texts = [str(row["text"]) for row in documents]
    doc_vectors = encode_documents(document_texts)
    doc_ids = [str(row["id"]) for row in documents]
    doc_groups = [str(row["group"]) for row in documents]

    latencies: list[float] = []
    reciprocal_ranks: list[float] = []
    recall5 = 0
    top1 = 0
    hard_negative_top1 = 0
    cross_group_top1 = 0
    details: list[dict[str, object]] = []
    for case in cases:
        started = time.perf_counter()
        query_vector = encode_query(case.query)
        latencies.append((time.perf_counter() - started) * 1000)
        scores = np.asarray(doc_vectors) @ np.asarray(query_vector)
        order = np.argsort(-scores)
        relevant_ranks = [rank for rank, index in enumerate(order, start=1) if doc_ids[int(index)] in case.relevant]
        best_rank = min(relevant_ranks) if relevant_ranks else 0
        reciprocal_ranks.append(1.0 / best_rank if best_rank else 0.0)
        recall5 += int(bool(best_rank and best_rank <= 5))
        top1 += int(best_rank == 1)
        winner = int(order[0])
        wrong_top1 = doc_ids[winner] not in case.relevant
        hard_negative_top1 += int(wrong_top1)
        cross_group_top1 += int(wrong_top1 and doc_groups[winner] != case.group)
        details.append({
            "id": case.case_id,
            "rank": best_rank,
            "top1": doc_ids[winner],
            "top1Score": round(float(scores[winner]), 6),
        })

    total = len(cases)
    rss_after_eval = process.memory_info().rss
    return {
        "name": name,
        "model": model_id,
        "dimensions": int(np.asarray(doc_vectors).shape[1]),
        "cases": total,
        "metrics": {
            "recallAt5": round(recall5 / total, 6),
            "MRR": round(statistics.fmean(reciprocal_ranks), 6),
            "top1UsefulRate": round(top1 / total, 6),
            "hardNegativeTop1Rate": round(hard_negative_top1 / total, 6),
            "crossGroupWrongTop1Rate": round(cross_group_top1 / total, 6),
        },
        "latency": {
            "loadMs": round(load_ms, 2),
            "queryP50Ms": round(percentile(latencies, 50), 2),
            "queryP95Ms": round(percentile(latencies, 95), 2),
        },
        "memory": {
            "loadedProcessRssMiB": round(rss_loaded / 1048576, 2),
            "afterEvalProcessRssMiB": round(rss_after_eval / 1048576, 2),
        },
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path("docs/eval/embedding-ime-cases.jsonl"))
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    documents, cases = load_cases(args.cases)
    requested = [value.strip() for value in args.models.split(",") if value.strip()]
    unknown = [value for value in requested if value not in MODELS]
    if unknown:
        parser.error(f"unknown models: {', '.join(unknown)}")

    report = {
        "schemaVersion": "rag-ime.embedding-matrix.v1",
        "generatedAt": int(time.time()),
        "dataset": {"path": str(args.cases), "documents": len(documents), "queries": len(cases)},
        "models": [benchmark(name, MODELS[name], documents, cases, args.batch_size) for name in requested],
    }
    report["ranking"] = [
        row["name"]
        for row in sorted(
            report["models"],
            key=lambda row: (
                -row["metrics"]["recallAt5"],
                -row["metrics"]["MRR"],
                -row["metrics"]["top1UsefulRate"],
                row["metrics"]["crossGroupWrongTop1Rate"],
                row["latency"]["queryP95Ms"],
            ),
        )
    ]
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
