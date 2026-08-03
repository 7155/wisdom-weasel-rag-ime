#!/usr/bin/env python3
"""Recurate all canonical history on a private candidate with Luna/max."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.deepseek_memory_organizer import ManagedPiMemoryOrganizer
from rag_ime.db import apply_database_migrations
from rag_ime.embeddings import (
    HashingEmbeddingProvider,
    NullEmbeddingProvider,
    embedding_provider_from_env,
)
from rag_ime.historical_memory_curation import (
    ATOM_FIRST_HISTORICAL_INSTRUCTION,
    curate_historical_memory_database,
    prepare_atom_first_historical_recuration,
    resume_atom_first_historical_recuration,
)
from rag_ime.hybrid_rag_models import HybridRagQuery
from rag_ime.hybrid_rag_retriever import retrieve_hybrid_rag_memory_hit_objects
from rag_ime.personal_memory_luna_evaluation import (
    PrivateCodexLunaMemoryExecutor,
    atom_first_memory_state_summary,
    prepare_private_shadow_schema_view,
    prepare_verified_memory_shadow,
    private_shadow_core,
    redacted_luna_request_summary,
)
from rag_ime.text_utils import compact_whitespace


DEFAULT_PRODUCTION_DB = (
    Path.home() / "Library" / "Application Support" / "RagIme" / "rag-ime.sqlite"
)
RAG_PROBES = (
    ("input-method-boundary", "输入法候选与 Rime 应该如何分工？"),
    ("memory-workflow", "长期记忆的 Evidence、Atom 和 Book 如何整理？"),
    ("room-collaboration", "Room 在项目中如何组织协作和上下文？"),
    ("recoverability", "删除或覆盖数据前需要保留什么恢复措施？"),
)
DEFAULT_MAX_LOGICAL_INPUTS_PER_BATCH = 70


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copy a verified recovery shadow, reopen every active canonical "
            "Evidence item, and run the unified Atom-first Luna/max pipeline."
        )
    )
    parser.add_argument("--shadow-db", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--public-report", type=Path)
    parser.add_argument("--project", default="wisdom-weasel-rag-ime")
    parser.add_argument(
        "--max-sources",
        type=int,
        default=DEFAULT_MAX_LOGICAL_INPUTS_PER_BATCH,
        help=(
            "maximum reconstructed user expressions per governed model batch; "
            "physical Rime fragments are coalesced before this limit"
        ),
    )
    parser.add_argument("--max-batches", type=int, default=64)
    parser.add_argument("--timeout-seconds", type=float, default=1_200.0)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--production-db", type=Path, default=DEFAULT_PRODUCTION_DB)
    parser.add_argument("--skip-timelines", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = build_parser().parse_args(argv)
    private_root = args.private_dir.expanduser().resolve(strict=False)
    if private_root.is_relative_to(ROOT):
        raise SystemExit("--private-dir must be outside the Git worktree")
    if private_root.exists():
        if not private_root.is_dir() or private_root.stat().st_mode & 0o077:
            raise SystemExit("existing --private-dir must be a mode-0700 directory")
    else:
        private_root.mkdir(parents=True, mode=0o700)
        private_root.chmod(0o700)

    source = args.shadow_db.expanduser().resolve(strict=True)
    production = args.production_db.expanduser().resolve(strict=False)
    if source == production:
        raise SystemExit("production SQLite cannot be a historical curation source")
    source_identity = _file_identity(source)
    prepared = prepare_verified_memory_shadow(
        source,
        private_root=private_root,
        production_db=production,
    )
    working_db = Path(prepared["workingDb"])
    prepare_private_shadow_schema_view(private_root)
    # Only a new disposable working copy receives forward-only schema
    # additions. A resumed candidate has already frozen and verified its
    # migration ledger; replaying a concurrently changed migration source would
    # either corrupt that audit boundary or raise a checksum collision.
    if not bool(prepared.get("resumed")):
        with sqlite3.connect(working_db) as migration_conn:
            apply_database_migrations(migration_conn)

    embedding = embedding_provider_from_env()
    if isinstance(embedding, (NullEmbeddingProvider, HashingEmbeddingProvider)):
        raise SystemExit("full-history acceptance requires a real semantic embedding provider")
    core = private_shadow_core(working_db, embedding_provider=embedding)
    baseline = atom_first_memory_state_summary(working_db)
    reset_run_id = (
        "historical-atom-first-reset:"
        + hashlib.sha256(
            f"{prepared['sourceFileSha256']}\0{compact_whitespace(args.project)}".encode()
        ).hexdigest()[:32]
    )
    reset = (
        resume_atom_first_historical_recuration(
            working_db,
            source_db_path=source,
            project=str(args.project),
            reset_run_id=reset_run_id,
            preverified_schema=True,
        )
        if bool(prepared.get("resumed"))
        else prepare_atom_first_historical_recuration(
            working_db,
            project=str(args.project),
            reset_run_id=reset_run_id,
            preverified_schema=True,
        )
    )

    executor = PrivateCodexLunaMemoryExecutor(
        private_root / "luna",
        audit_db_path=working_db,
        timeout_seconds=float(args.timeout_seconds),
        codex_bin=str(args.codex_bin),
    )
    # Dense historical days can need more than the production default because
    # one rejected repair may be consumed only by the local preservation gate.
    # Keep the larger bound exclusive to this stopped, disposable candidate.
    organizer = ManagedPiMemoryOrganizer(
        executor,
        max_semantic_repair_rounds=5,
    )
    try:
        curation = curate_historical_memory_database(
            working_db,
            organizer=organizer,
            project=str(args.project),
            embedding_provider=embedding,
            max_batches=max(1, int(args.max_batches)),
            max_sources=max(1, min(1_500, int(args.max_sources))),
            auto_apply=True,
            include_agent_dialogue=False,
            preverified_schema=True,
            approve_timelines=not bool(args.skip_timelines),
            instruction=ATOM_FIRST_HISTORICAL_INSTRUCTION,
        )
    finally:
        organizer.close()

    final_state = atom_first_memory_state_summary(working_db)
    rag = _historical_rag_probe(core, project=str(args.project))
    requests = redacted_luna_request_summary(executor.receipts)
    request_contract_ok = _request_contract_ok(requests)
    source_unchanged = _file_identity(source) == source_identity
    projection_fresh = bool(
        dict(dict(curation.get("projections") or {}).get("freshness") or {}).get("fresh")
    )
    pending_sources = int(
        dict(curation.get("ownerCuration") or {}).get("pendingSourceCount") or 0
    )
    passed = (
        bool(curation.get("ok"))
        and bool(reset.get("ok"))
        and reset.get("rawInputEventsMutated") is False
        and pending_sources == 0
        and curation.get("integrityCheck") == "ok"
        and int(curation.get("foreignKeyViolationCount") or 0) == 0
        and bool(final_state.get("allGovernedCurrentAtomsHaveLegalLineage"))
        and bool(dict(final_state.get("bookProjection") or {}).get("inSync"))
        and projection_fresh
        and request_contract_ok
        and source_unchanged
        and bool(rag.get("passed"))
    )
    summary: dict[str, object] = {
        "schemaVersion": "rag-ime.atom-first-historical-luna-evaluation.v1",
        "status": "pass" if passed else "iterate",
        "passed": passed,
        "model": "gpt-5.6-luna",
        "thinking": "max",
        "transport": "codex_cli_ephemeral",
        "candidateOnly": True,
        "productionDatabaseOpened": False,
        "productionMutationPerformed": False,
        "sourceShadowUnchanged": source_unchanged,
        "embeddingProviderFingerprint": embedding.fingerprint,
        "baselineState": baseline,
        "reset": reset,
        "curation": _redacted_historical_summary(curation),
        "finalState": final_state,
        "rag": rag,
        "modelRequests": requests,
        "modelRequestContractPassed": request_contract_ok,
        "privateArtifactDirectorySha256": _sha256(str(private_root)),
    }
    _write_private_json(private_root / "historical-evaluation-summary.json", summary)
    if args.public_report is not None:
        _write_public_report(args.public_report.expanduser(), summary)
    print(
        json.dumps(
            {
                "passed": passed,
                "status": summary["status"],
                "reset": reset,
                "curation": summary["curation"],
                "finalState": final_state,
                "rag": rag,
                "modelRequestCount": len(requests),
                "modelRequestContractPassed": request_contract_ok,
                "sourceShadowUnchanged": source_unchanged,
                "productionMutationPerformed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def _historical_rag_probe(core: object, *, project: str) -> dict[str, object]:
    results: list[dict[str, object]] = []
    with core._connect() as conn:  # type: ignore[attr-defined]  # private candidate owner.
        for probe_id, query in RAG_PROBES:
            hits = retrieve_hybrid_rag_memory_hit_objects(
                conn,
                HybridRagQuery(
                    query_text=query,
                    raw_input=query,
                    project=compact_whitespace(project),
                    top_k=12,
                    latency_budget_ms=4_000,
                    visible_owners=(("user", "default"),),
                    enabled_lanes=(("time", False), ("feedback", False)),
                ),
                core.embedding_provider,  # type: ignore[attr-defined]
            )
            governed = [hit for hit in hits if hit.doc_type in {"atom", "book"}]
            results.append(
                {
                    "probeId": probe_id,
                    "governedHitCount": len(governed),
                    "topGovernedRank": next(
                        (
                            index
                            for index, hit in enumerate(hits, start=1)
                            if hit.doc_type in {"atom", "book"}
                        ),
                        0,
                    ),
                }
            )
    hit_probes = sum(int(item["governedHitCount"]) > 0 for item in results)
    return {
        "schemaVersion": "rag-ime.atom-first-historical-rag-probe.v1",
        "passed": hit_probes >= 3,
        "probeCount": len(results),
        "probeWithGovernedHitCount": hit_probes,
        "cases": results,
    }


def _request_contract_ok(requests: list[dict[str, object]]) -> bool:
    if not requests:
        return False
    phases = [str(item.get("phase") or "") for item in requests]
    if any(
        item.get("model") != "gpt-5.6-luna"
        or item.get("thinking") != "max"
        for item in requests
    ):
        return False
    for index, phase in enumerate(phases):
        if phase == "atom-first-verifier":
            if not bool(requests[index].get("isolated")):
                return False
            continue
        if phase not in {"atom-first-curation", "atom-first-repair"}:
            return False
        if bool(requests[index].get("isolated")):
            return False
    if phases[-1] != "atom-first-verifier":
        return False
    curation_indexes = [
        index for index, phase in enumerate(phases) if phase == "atom-first-curation"
    ]
    if not curation_indexes:
        return False
    # One historical batch starts with curation and may use a bounded repair
    # before or after its first verifier. Every batch segment must still end in
    # an isolated verifier; a repair can never become the terminal authority.
    for ordinal, start in enumerate(curation_indexes):
        end = (
            curation_indexes[ordinal + 1]
            if ordinal + 1 < len(curation_indexes)
            else len(phases)
        )
        segment = phases[start:end]
        if segment[0] != "atom-first-curation" or segment[-1] != "atom-first-verifier":
            return False
        if "atom-first-verifier" not in segment:
            return False
    return True


def _redacted_historical_summary(report: Mapping[str, object]) -> dict[str, object]:
    before = dict(report.get("before") or {})
    after = dict(report.get("after") or {})
    timelines = dict(report.get("timelines") or {})
    projections = dict(report.get("projections") or {})
    owner = dict(report.get("ownerCuration") or {})
    return {
        "ok": bool(report.get("ok")),
        "startedAtMs": int(report.get("startedAtMs") or 0),
        "finishedAtMs": int(report.get("finishedAtMs") or 0),
        "before": before,
        "after": after,
        "batchCount": len(report.get("batches") or []),
        "reviewedRunCount": len(report.get("reviewedRuns") or []),
        "timelineDateCount": int(timelines.get("dateCount") or 0),
        "approvedTimelineCount": int(timelines.get("approvedNow") or 0),
        "pendingSourceCount": int(owner.get("pendingSourceCount") or 0),
        "projectionFreshness": dict(projections.get("freshness") or {}),
        "integrityCheck": str(report.get("integrityCheck") or ""),
        "foreignKeyViolationCount": int(report.get("foreignKeyViolationCount") or 0),
        "policy": dict(report.get("policy") or {}),
    }


def _write_public_report(path: Path, summary: Mapping[str, object]) -> None:
    if path.exists():
        raise ValueError("public report path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    curation = dict(summary.get("curation") or {})
    state = dict(summary.get("finalState") or {})
    books = dict(state.get("bookProjection") or {})
    reset = dict(summary.get("reset") or {})
    rag = dict(summary.get("rag") or {})
    lines = [
        "# Atom-first Historical Memory Luna Evaluation",
        "",
        f"- Result: `{summary.get('status')}`.",
        "- Scope: disposable verified recovery candidate; production SQLite was not opened or modified.",
        f"- Model: `{summary.get('model')}`, thinking `{summary.get('thinking')}`.",
        f"- Real semantic embedding: `{summary.get('embeddingProviderFingerprint')}`.",
        f"- Source recovery shadow unchanged: `{summary.get('sourceShadowUnchanged')}`.",
        "",
        "## Full-history flow",
        "",
        f"- Eligible Evidence reopened: `{reset.get('eligibleEvidenceCount')}`; changed `{reset.get('changedEvidenceCount')}`.",
        f"- Immutable input ledger unchanged: `{not bool(reset.get('rawInputEventsMutated'))}`; hash `{reset.get('inputEventsSha256')}`.",
        f"- Luna batches: `{curation.get('batchCount')}`; pending sources: `{curation.get('pendingSourceCount')}`.",
        f"- Current Atoms: `{state.get('currentAtomCount')}`; governed `{state.get('governedCurrentAtomCount')}`.",
        f"- Active Books: `{books.get('activeBookCount')}`; unbooked governed Atoms `{books.get('unbookedGovernedAtomCount')}`.",
        f"- Legal lineage gate: `{state.get('allGovernedCurrentAtomsHaveLegalLineage')}`; Book gate `{books.get('inSync')}`.",
        f"- Projection fresh: `{dict(curation.get('projectionFreshness') or {}).get('fresh')}`.",
        f"- Hybrid RAG topic probes: `{rag.get('probeWithGovernedHitCount')}/{rag.get('probeCount')}`.",
        f"- Content-addressed model request contract: `{summary.get('modelRequestContractPassed')}`.",
        "",
        "## Interpretation",
        "",
        "The run validates the single Evidence -> Atom -> Book path on recovered private history, including independent verifier receipts, semantic vector projection, integrity, and raw-input immutability. It does not by itself prove installed Gateway behavior or foreground input-method behavior.",
        "No raw input, Atom text, Book text, model output, database path, or private identifier is included.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_private_json(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(dict(value), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def _file_identity(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "size": int(value.st_size),
        "mtimeNs": int(value.st_mtime_ns),
    }


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
