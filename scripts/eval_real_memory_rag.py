#!/usr/bin/env python3
"""Evaluate real curated Memory through hybrid RAG and Agent prompt injection."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.activity_timeline_evaluation import (
    load_luna_structured_run,
    run_luna_structured,
)
from rag_ime.embeddings import (
    HashingEmbeddingProvider,
    NullEmbeddingProvider,
    embedding_provider_from_env,
)
from rag_ime.personal_memory_luna_evaluation import (
    prepare_private_shadow_schema_view,
    prepare_verified_memory_shadow,
    private_shadow_core,
)
from rag_ime.real_memory_rag_evaluation import (
    REAL_MEMORY_RAG_EVALUATION_SCHEMA_VERSION,
    build_real_memory_query_prompt,
    evaluate_real_memory_rag,
    prepare_real_legacy_atom_cases,
    real_memory_query_output_schema,
    redacted_real_memory_rag_summary,
    validate_real_memory_queries,
)


DEFAULT_PRODUCTION_DB = (
    Path.home() / "Library" / "Application Support" / "RagIme" / "rag-ime.sqlite"
)
EVALUATED_SOURCE_PATHS = (
    "rag_ime/agent_context_runtime.py",
    "rag_ime/agent_prompt_application.py",
    "rag_ime/agent_prompt_delivery.py",
    "rag_ime/session_memory_recall.py",
    "rag_ime/real_memory_rag_evaluation.py",
    "scripts/eval_real_memory_rag.py",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate held-out queries from real curated Atoms, then evaluate "
            "hybrid retrieval, Session recall, and the final runtime prompt on "
            "a private shadow copy. Production SQLite is never opened."
        )
    )
    parser.add_argument("--shadow-db", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--public-report", type=Path)
    parser.add_argument("--max-cases", type=int, default=12)
    parser.add_argument("--timeout-seconds", type=float, default=1_200.0)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument(
        "--embedding-from-env",
        action="store_true",
        help=(
            "Use the configured semantic embedding provider instead of the "
            "deterministic local-hash baseline."
        ),
    )
    parser.add_argument(
        "--query-run",
        type=Path,
        help=(
            "Reuse a completed private Luna query run after verifying its "
            "prompt and schema hashes."
        ),
    )
    parser.add_argument("--production-db", type=Path, default=DEFAULT_PRODUCTION_DB)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = build_parser().parse_args(argv)
    private_root = args.private_dir.expanduser().resolve(strict=False)
    _prepare_private_root(private_root)

    source_db = args.shadow_db.expanduser().resolve(strict=True)
    prepared_shadow = prepare_verified_memory_shadow(
        source_db,
        private_root=private_root,
        production_db=args.production_db,
    )
    working_db = Path(prepared_shadow["workingDb"])
    embedding_provider = (
        embedding_provider_from_env()
        if args.embedding_from_env
        else HashingEmbeddingProvider(dimensions=96)
    )
    if isinstance(embedding_provider, NullEmbeddingProvider):
        raise SystemExit(
            "--embedding-from-env resolved to a disabled provider"
        )
    core = private_shadow_core(
        working_db,
        embedding_provider=embedding_provider,
    )
    schema_view = prepare_private_shadow_schema_view(private_root)
    prepared_cases = prepare_real_legacy_atom_cases(
        core,
        migrations_dir=schema_view,
        max_cases=max(1, min(32, int(args.max_cases))),
    )
    private_cases = [
        dict(item)
        for item in prepared_cases.get("cases") or []
        if isinstance(item, Mapping)
    ]
    if not private_cases:
        raise SystemExit("no real, lineaged, currently retrievable legacy Atoms exist")

    prompt = build_real_memory_query_prompt(private_cases)
    schema = real_memory_query_output_schema()
    query_artifact = (
        args.query_run.expanduser().resolve(strict=True)
        if args.query_run is not None
        else private_root / "luna-real-query-generation"
    )
    if query_artifact.exists():
        model_run = load_luna_structured_run(
            query_artifact,
            phase="real-memory-queries",
        )
        if model_run.prompt_sha256 != _sha256(prompt):
            raise ValueError("resumed real-query prompt does not match current data")
        if model_run.schema_sha256 != _sha256_json(schema):
            raise ValueError("resumed real-query schema does not match current contract")
    else:
        model_run = run_luna_structured(
            prompt=prompt,
            schema=schema,
            artifact_dir=query_artifact,
            phase="real-memory-queries",
            timeout_seconds=float(args.timeout_seconds),
            codex_bin=str(args.codex_bin),
        )
    queries = validate_real_memory_queries(model_run.output, cases=private_cases)
    evaluation = evaluate_real_memory_rag(
        core,
        cases=private_cases,
        queries=queries,
        model_run=model_run,
    )
    source_unchanged = _file_identity(source_db) == prepared_shadow["sourceIdentity"]
    redacted = redacted_real_memory_rag_summary(prepared_cases, evaluation)
    passed = bool(evaluation.get("passed")) and source_unchanged
    summary = {
        "schemaVersion": REAL_MEMORY_RAG_EVALUATION_SCHEMA_VERSION,
        "status": "pass" if passed else "iterate",
        "passed": passed,
        "sourceShadowUnchanged": source_unchanged,
        "productionDatabaseOpened": False,
        "productionMutationPerformed": False,
        "gatewayInstalledAcceptance": False,
        "realData": True,
        "sourceSnapshot": _source_snapshot(),
        "evaluation": redacted,
        "shadow": {
            "resumed": bool(prepared_shadow.get("resumed")),
            "sourceFileSha256": str(prepared_shadow.get("sourceFileSha256") or ""),
            "verification": dict(prepared_shadow.get("verification") or {}),
        },
    }
    _write_private_json(
        private_root / "real-memory-rag-private-summary.json",
        {
            **summary,
            "privateCases": private_cases,
            "privateQueries": [dict(item) for item in queries],
        },
    )
    if args.public_report is not None:
        _write_public_report(args.public_report.expanduser(), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passed else 1


def _prepare_private_root(path: Path) -> None:
    if path.is_relative_to(ROOT):
        raise SystemExit("--private-dir must be outside the Git worktree")
    if path.exists():
        if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise SystemExit("existing --private-dir must be a mode-0700 directory")
        return
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)


def _write_private_json(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(dict(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def _write_public_report(path: Path, summary: Mapping[str, object]) -> None:
    if path.exists():
        raise ValueError("public report path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = dict(summary.get("evaluation") or {})
    embedding = dict(evaluation.get("embedding") or {})
    query_generator = dict(evaluation.get("queryGenerator") or {})
    source_snapshot = dict(summary.get("sourceSnapshot") or {})
    cases = [
        dict(item)
        for item in evaluation.get("cases") or []
        if isinstance(item, Mapping)
    ]
    lines = [
        "# Real Memory RAG Evaluation",
        "",
        f"- Result: `{summary.get('status')}`.",
        "- Dataset: real, previously curated legacy Atoms from a verified private recovery shadow.",
        "- Safety: the source shadow stayed read-only; production SQLite was not opened or modified.",
        "- Admission boundary: no legacy row was promoted to capture-v2 Evidence.",
        "- Installed Gateway acceptance: not performed in this source-level run.",
        "",
        "## Evaluated Source Snapshot",
        "",
        *(
            f"- `{relative_path}`: `{digest}`."
            for relative_path, digest in sorted(source_snapshot.items())
        ),
        f"- Luna query prompt: `{query_generator.get('promptSha256')}`.",
        f"- Luna query output: `{query_generator.get('outputSha256')}`.",
        "",
        "## Corpus",
        "",
        f"- Stored eligible legacy Atoms: `{evaluation.get('storedEligibleAtomCount')}`.",
        f"- Currently projected by governed retrieval rules: `{evaluation.get('projectedEligibleAtomCount')}`.",
        f"- Projected Atoms with auditable source-event lineage: `{evaluation.get('evaluableLineagedAtomCount')}`.",
        f"- Excluded from this evaluation for missing source-event lineage: `{evaluation.get('skippedWithoutLineageCount')}`.",
        f"- Evaluated cases: `{evaluation.get('caseCount')}`.",
        "- Query construction: Luna generated a natural held-out recall question from each real Atom; raw text and queries remain only in the private artifact directory.",
        f"- Query generator: `{query_generator.get('model')}` / `{query_generator.get('thinking')}`; exit `{query_generator.get('exitCode')}`.",
        "",
        "## Retrieval and Prompt Results",
        "",
        f"- Hit@1: `{evaluation.get('hitAt1')}/{evaluation.get('caseCount')}` (`{evaluation.get('hitAt1Rate')}`).",
        f"- Hit@3: `{evaluation.get('hitAt3')}/{evaluation.get('caseCount')}` (`{evaluation.get('hitAt3Rate')}`).",
        f"- Hit@5: `{evaluation.get('hitAt5')}/{evaluation.get('caseCount')}` (`{evaluation.get('hitAt5Rate')}`).",
        f"- Vector-only Hit@1: `{evaluation.get('vectorOnlyHitAt1')}/{evaluation.get('caseCount')}` (`{evaluation.get('vectorOnlyHitAt1Rate')}`).",
        f"- Vector-only Hit@3: `{evaluation.get('vectorOnlyHitAt3')}/{evaluation.get('caseCount')}` (`{evaluation.get('vectorOnlyHitAt3Rate')}`).",
        f"- Vector-only Hit@5: `{evaluation.get('vectorOnlyHitAt5')}/{evaluation.get('caseCount')}` (`{evaluation.get('vectorOnlyHitAt5Rate')}`).",
        f"- Mean reciprocal rank: `{evaluation.get('meanReciprocalRank')}`.",
        f"- Session Recall selected target: `{evaluation.get('sessionSelectedCount')}/{evaluation.get('caseCount')}`.",
        f"- Final runtime prompt included target inside the isolated RAG block: `{evaluation.get('promptInjectedCount')}/{evaluation.get('caseCount')}`.",
        f"- Current user message remained separate from Session memory: `{evaluation.get('promptIsolatedCount')}/{evaluation.get('caseCount')}`.",
        "",
        "| Case | Query hash | Target hash | Source events | Hybrid rank | Vector-only rank | Lane | Session | Prompt | Isolated |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for item in cases:
        lines.append(
            "| {case} | `{query}` | `{target}` | {events} | {rank} | {vector_rank} | `{lane}` | `{session}` | `{prompt}` | `{isolated}` |".format(
                case=item.get("caseRef"),
                query=str(item.get("querySha256") or "")[:16],
                target=str(item.get("targetTextSha256") or "")[:16],
                events=item.get("sourceEventCount"),
                rank=item.get("directRank"),
                vector_rank=item.get("vectorOnlyRank"),
                lane=item.get("directSourceLane"),
                session=item.get("sessionSelected"),
                prompt=item.get("promptInjected"),
                isolated=item.get("promptIsolated"),
            )
        )
    provider_interpretation = (
        "- This run used a real semantic embedding model and the vector-only ablation isolates that lane from BM25, TagMemo, feedback, and time recall. It still does not prove the installed Gateway is configured to use the same provider."
        if bool(embedding.get("semantic"))
        else "- This provider is a deterministic local term-vector baseline, not a semantic embedding model. The run therefore proves current source-level hybrid/lexical retrieval and the exact RAG-to-prompt wiring, not production BGE quality."
    )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- Embedding provider: `{embedding.get('provider')}` / `{embedding.get('model')}` (`{embedding.get('fingerprint')}`).",
            provider_interpretation,
            "- Queries are model-generated rather than human relevance labels. Treat Hit@K as a reproducible engineering gate, not an unbiased benchmark or leaderboard result.",
            "- The public report contains no Atom text, generated query, private identifier, database path, or raw input history.",
        ]
    )
    encoded = "\n".join(lines) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(encoded)


def _file_identity(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "size": int(value.st_size),
        "mtimeNs": int(value.st_mtime_ns),
    }


def _source_snapshot() -> dict[str, str]:
    return {
        relative_path: hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        for relative_path in EVALUATED_SOURCE_PATHS
    }


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
