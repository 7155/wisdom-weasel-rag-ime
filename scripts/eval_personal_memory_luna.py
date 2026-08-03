#!/usr/bin/env python3
"""Run the unified Atom-first pipeline on a private shadow with real Luna/max."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.deepseek_memory_organizer import ManagedPiMemoryOrganizer
from rag_ime.embeddings import NullEmbeddingProvider, embedding_provider_from_env
from rag_ime.activity_timeline_evaluation import load_frozen_activity_timeline
from rag_ime.memory_book_compiler import rollback_memory_book_run
from rag_ime.memory_evidence_admission import rollback_evidence_admissions_for_run
from rag_ime.local_sqlite_core import LocalSqliteCoreClient
from rag_ime.owner_memory_curation import OwnerMemoryCurator
from rag_ime.personal_memory_luna_evaluation import (
    PERSONAL_MEMORY_LUNA_EVALUATION_SCHEMA_VERSION,
    PrivateCodexLunaMemoryExecutor,
    atom_first_memory_state_summary,
    build_personal_memory_semantic_evaluation_bundle,
    evaluate_synthetic_personal_memory_rag,
    prepare_private_shadow_schema_view,
    prepare_verified_memory_shadow,
    private_shadow_core,
    redacted_luna_request_summary,
    redacted_owner_run_summary,
    redacted_personal_memory_rag_summary,
    redacted_semantic_curation_summary,
    redacted_synthetic_seed_summary,
    seed_synthetic_personal_memory_rag_cases,
    verify_recovered_memory_shadow,
)


DEFAULT_PRODUCTION_DB = (
    Path.home() / "Library" / "Application Support" / "RagIme" / "rag-ime.sqlite"
)
ATOM_FIRST_EVALUATION_INSTRUCTION = (
    "Use the single Evidence -> Atom -> Book pipeline. Retain durable personal facts, "
    "habits, preferences and principles, plus durable project requirements, decisions, "
    "constraints and facts that remain useful across sessions. Organize every accepted "
    "Atom into one or more stable topic Books. Reject temporary activity, one-off commands, "
    "unresolved questions and implementation status unless the evidence directly states a "
    "durable requirement or decision. Never infer facts from app, time or repetition."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the real unified Evidence -> Atom -> Book path on a "
            "verified private shadow. Production SQLite is never opened."
        )
    )
    parser.add_argument("--shadow-db", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--public-report", type=Path)
    parser.add_argument("--project", default="wisdom-weasel-rag-ime")
    parser.add_argument("--max-sources", type=int, default=1_000)
    parser.add_argument("--timeout-seconds", type=float, default=1_200.0)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument(
        "--embedding-from-env",
        action="store_true",
        help=(
            "Require the configured semantic embedding provider for projection "
            "and RAG instead of the degraded deterministic hash provider."
        ),
    )
    parser.add_argument("--production-db", type=Path, default=DEFAULT_PRODUCTION_DB)
    parser.add_argument(
        "--semantic-timeline-id",
        default="",
        help=(
            "Run a read-only semantic quality evaluation over one approved "
            "historical Timeline. This never admits legacy rows as Evidence."
        ),
    )
    parser.add_argument(
        "--seed-synthetic-rag-fixture",
        action="store_true",
        help=(
            "Seed public-safe capture-v2 cases into the private working copy, "
            "then require Atom/Book projection, hybrid RAG recall, rollback "
            "removal, and replay recall."
        ),
    )
    parser.add_argument(
        "--clean-synthetic-shadow",
        action="store_true",
        help=(
            "Use a fresh private SQLite for the public-safe synthetic fixture "
            "while still verifying that --shadow-db remains unchanged."
        ),
    )
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

    if str(args.semantic_timeline_id).strip():
        return _run_semantic_quality(args, private_root)

    if bool(args.clean_synthetic_shadow) and not bool(args.seed_synthetic_rag_fixture):
        raise SystemExit("--clean-synthetic-shadow requires --seed-synthetic-rag-fixture")
    embedding_provider = (
        embedding_provider_from_env()
        if bool(args.embedding_from_env)
        else None
    )
    if isinstance(embedding_provider, NullEmbeddingProvider):
        raise SystemExit("--embedding-from-env resolved to a disabled provider")
    rag_core = None
    if bool(args.clean_synthetic_shadow):
        source = args.shadow_db.expanduser().resolve(strict=True)
        source_identity = _file_identity(source)
        verification = verify_recovered_memory_shadow(source)
        working_db = private_root / "clean-synthetic-evaluation.sqlite"
        if working_db.exists():
            raise SystemExit("clean synthetic working database already exists")
        rag_core = LocalSqliteCoreClient(
            working_db,
            embedding_provider=embedding_provider,
        )
        rag_core.initialize()
        prepared = {
            "workingDb": working_db,
            "resumed": False,
            "sourceFileSha256": _file_sha256(source),
            "sourceIdentity": source_identity,
            "verification": verification,
        }
    else:
        prepared = prepare_verified_memory_shadow(
            args.shadow_db,
            private_root=private_root,
            production_db=args.production_db,
        )
        working_db = Path(prepared["workingDb"])
    schema_view = prepare_private_shadow_schema_view(private_root)
    synthetic_cases: tuple[dict[str, object], ...] = ()
    synthetic_seed: dict[str, object] = {}
    if bool(args.seed_synthetic_rag_fixture):
        if rag_core is None:
            rag_core = private_shadow_core(
                working_db,
                embedding_provider=embedding_provider,
            )
        synthetic_cases = seed_synthetic_personal_memory_rag_cases(
            rag_core,
            project=str(args.project),
        )
        synthetic_seed = redacted_synthetic_seed_summary(synthetic_cases)
    baseline = atom_first_memory_state_summary(working_db)
    executor = PrivateCodexLunaMemoryExecutor(
        private_root / "luna",
        audit_db_path=working_db,
        timeout_seconds=float(args.timeout_seconds),
        codex_bin=str(args.codex_bin),
    )
    organizer = ManagedPiMemoryOrganizer(executor)
    curator = OwnerMemoryCurator(
        working_db,
        organizer=organizer,
        project=str(args.project),
        initial_settle_ms=0,
        auto_apply=True,
        include_agent_dialogue=False,
        embedding_provider=(rag_core.embedding_provider if rag_core is not None else None),
        max_sources=max(1, min(1_500, int(args.max_sources))),
    )

    # The recovery builder already applied and verified every required
    # migration in an isolated migration view. Calling initialize() here would
    # re-open the known unrelated migration-0127 checksum collision. The
    # prepared-shadow receipt and required-table check above are the explicit
    # replacement gate for this private evaluation only.
    first = curator.run_due(
        manual=True,
        owner_kind="user",
        owner_id="default",
        instruction=ATOM_FIRST_EVALUATION_INSTRUCTION,
    )
    first_state = atom_first_memory_state_summary(working_db)
    first_result = _first_result(first)
    first_request_count = len(executor.receipts)
    run_id = str(first_result.get("runId") or "")
    first_rag_full: dict[str, object] = {}
    first_rag: dict[str, object] = {}
    seeded_atom_ids: list[str] = []
    if (
        rag_core is not None
        and bool(first.get("ok"))
        and str(first_result.get("runStatus") or "") == "applied"
    ):
        first_rag_full = evaluate_synthetic_personal_memory_rag(
            rag_core,
            synthetic_cases,
            project=str(args.project),
            migrations_dir=schema_view,
        )
        seeded_atom_ids = [
            str(value)
            for value in first_rag_full.get("atomIds") or []
            if str(value)
        ]
        first_rag = redacted_personal_memory_rag_summary(first_rag_full)
    rollback: dict[str, object] = {
        "attempted": False,
        "ok": False,
        "kind": "none",
        "restoredBaseline": False,
    }
    replay: dict[str, object] = {
        "attempted": False,
        "ok": False,
        "reusedModelRequests": False,
        "restoredAppliedState": False,
    }
    second: dict[str, object] = {}
    second_state: dict[str, object] = {}
    rollback_rag: dict[str, object] = {}
    replay_rag: dict[str, object] = {}

    if bool(first.get("ok")) and run_id:
        rollback["attempted"] = True
        with sqlite3.connect(working_db) as conn:
            conn.row_factory = sqlite3.Row
            if str(first_result.get("runStatus") or "") == "applied":
                rolled = rollback_memory_book_run(conn, run_id=run_id)
                rollback["kind"] = "memory_book_run"
                rollback["runStatus"] = str(rolled.get("status") or "")
            else:
                rolled = rollback_evidence_admissions_for_run(
                    conn,
                    run_id,
                    created_at_ms=int(time.time() * 1_000),
                )
                rollback["kind"] = "evidence_admission_run"
                rollback["guardedCount"] = len(rolled.get("guardedEvidenceIds") or [])
                rollback["restoredEvidenceCount"] = len(
                    rolled.get("restoredEvidenceIds") or []
                )
            conn.commit()
        rolled_back_state = atom_first_memory_state_summary(working_db)
        rollback["restoredBaseline"] = (
            rolled_back_state["logicalStateSha256"]
            == baseline["logicalStateSha256"]
        )
        if rag_core is not None and seeded_atom_ids:
            rollback_rag_full = evaluate_synthetic_personal_memory_rag(
                rag_core,
                synthetic_cases,
                project=str(args.project),
                expected_atom_ids=seeded_atom_ids,
                expect_present=False,
                migrations_dir=schema_view,
            )
            rollback_rag = redacted_personal_memory_rag_summary(rollback_rag_full)
            rollback["ragCleared"] = bool(rollback_rag_full.get("passed"))
        rollback["ok"] = bool(rollback["restoredBaseline"]) and (
            rag_core is None or bool(rollback.get("ragCleared"))
        )

        if rollback["ok"] and rollback["kind"] == "memory_book_run":
            replay["attempted"] = True
            receipt_count_before = len(executor.receipts)
            second = curator.run_due(
                manual=True,
                owner_kind="user",
                owner_id="default",
                instruction=ATOM_FIRST_EVALUATION_INSTRUCTION,
                current_ms=int(time.time() * 1_000) + 120_000,
            )
            second_state = atom_first_memory_state_summary(working_db)
            if rag_core is not None:
                replay_rag_full = evaluate_synthetic_personal_memory_rag(
                    rag_core,
                    synthetic_cases,
                    project=str(args.project),
                    migrations_dir=schema_view,
                )
                replay_rag = redacted_personal_memory_rag_summary(replay_rag_full)
                replay["ragRestored"] = bool(replay_rag_full.get("passed"))
                replay["ragAtomSetStable"] = (
                    str(replay_rag_full.get("discoveredAtomIdsSha256") or "")
                    == str(first_rag_full.get("discoveredAtomIdsSha256") or "")
                )
            replay_receipts = executor.receipts[receipt_count_before:]
            replay["reusedModelRequests"] = bool(replay_receipts) and all(
                bool(item.get("resumed")) for item in replay_receipts
            )
            replay["restoredAppliedState"] = (
                second_state["logicalStateSha256"]
                == first_state["logicalStateSha256"]
            )
            replay["ok"] = (
                bool(second.get("ok"))
                and bool(replay["reusedModelRequests"])
                and bool(replay["restoredAppliedState"])
                and (
                    rag_core is None
                    or (
                        bool(replay.get("ragRestored"))
                        and bool(replay.get("ragAtomSetStable"))
                    )
                )
            )

    source_identity_after = _file_identity(args.shadow_db.expanduser().resolve(strict=True))
    source_unchanged = source_identity_after == prepared["sourceIdentity"]
    requests = redacted_luna_request_summary(executor.receipts)
    phases = [str(item.get("phase") or "") for item in requests]
    first_ok = bool(first.get("ok"))
    lineage_ok = bool(
        first_state.get("allGovernedCurrentAtomsHaveLegalLineage")
    )
    book_ok = bool(dict(first_state.get("bookProjection") or {}).get("inSync"))
    first_phases = phases[:first_request_count]
    first_requests = requests[:first_request_count]
    model_ok = (
        bool(first_requests)
        and first_phases[0] == "atom-first-curation"
        and first_phases[-1] == "atom-first-verifier"
        and all(
            phase in {
                "atom-first-curation",
                "atom-first-repair",
                "atom-first-verifier",
            }
            for phase in first_phases
        )
        and bool(first_requests[-1].get("isolated"))
        and all(item.get("model") == "gpt-5.6-luna" for item in first_requests)
        and all(item.get("thinking") == "max" for item in first_requests)
    )
    passed = (
        first_ok
        and lineage_ok
        and book_ok
        and model_ok
        and bool(rollback.get("ok"))
        and (not replay["attempted"] or bool(replay["ok"]))
        and source_unchanged
        and (
            not bool(args.seed_synthetic_rag_fixture)
            or (
                bool(synthetic_seed.get("allStored"))
                and bool(synthetic_seed.get("allCandidateEvidence"))
                and bool(first_rag.get("passed"))
            )
        )
    )
    summary: dict[str, object] = {
        "schemaVersion": PERSONAL_MEMORY_LUNA_EVALUATION_SCHEMA_VERSION,
        "status": "pass" if passed else "iterate",
        "passed": passed,
        "model": "gpt-5.6-luna",
        "thinking": "max",
        "transport": "codex_cli_ephemeral",
        "gatewayInstalledAcceptance": False,
        "productionDatabaseOpened": False,
        "productionMutationPerformed": False,
        "sourceShadowUnchanged": source_unchanged,
        "syntheticRagFixtureEnabled": bool(args.seed_synthetic_rag_fixture),
        "syntheticSeed": synthetic_seed,
        "shadow": {
            "resumed": bool(prepared.get("resumed")),
            "sourceFileSha256": prepared["sourceFileSha256"],
            "verification": prepared["verification"],
        },
        "firstRun": redacted_owner_run_summary(first),
        "baselineState": baseline,
        "appliedState": first_state,
        "appliedRag": first_rag,
        "rollback": rollback,
        "rollbackRag": rollback_rag,
        "replay": replay,
        "replayRun": redacted_owner_run_summary(second) if second else {},
        "replayState": second_state,
        "replayRag": replay_rag,
        "modelRequests": requests,
        "privateArtifactDirectorySha256": _sha256(str(private_root)),
    }
    _write_private_summary(private_root / "evaluation-summary.json", summary)
    if args.public_report is not None:
        _write_public_report(args.public_report.expanduser(), summary)
    print(
        json.dumps(
            {
                "passed": passed,
                "status": summary["status"],
                "model": summary["model"],
                "thinking": summary["thinking"],
                "firstRun": summary["firstRun"],
                "appliedState": summary["appliedState"],
                "appliedRag": first_rag,
                "rollback": rollback,
                "rollbackRag": rollback_rag,
                "replay": replay,
                "replayRag": replay_rag,
                "modelRequests": requests,
                "sourceShadowUnchanged": source_unchanged,
                "productionMutationPerformed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def _run_semantic_quality(args: argparse.Namespace, private_root: Path) -> int:
    """Use real Luna to judge recovered history without changing its legal state."""

    source_db = args.shadow_db.expanduser().resolve(strict=True)
    source_before = _file_identity(source_db)
    verification = verify_recovered_memory_shadow(source_db)
    snapshot = load_frozen_activity_timeline(
        source_db,
        timeline_id=str(args.semantic_timeline_id),
        require_approved=True,
    )
    bundle, recovery = build_personal_memory_semantic_evaluation_bundle(snapshot)
    frozen_sha256 = str(recovery["semanticBundleSha256"])
    executor = PrivateCodexLunaMemoryExecutor(
        private_root / "luna",
        timeout_seconds=float(args.timeout_seconds),
        codex_bin=str(args.codex_bin),
    )
    organizer = ManagedPiMemoryOrganizer(executor)
    run_id = f"semantic-evaluation:{frozen_sha256[:32]}"
    try:
        executor.begin_run(run_id, frozen_input_sha256=frozen_sha256)
        result = organizer.curate_owner_memory(
            bundle=bundle,
            project=snapshot.project,
            owner_kind="user",
            owner_id="default",
            instruction=(
                "This is historical semantic quality evaluation only. Classify "
                "durable cross-project personal information conservatively. Project "
                "requirements, implementation details, tasks, documents, questions, "
                "temporary activity, and ambiguous reconstructed text are not personal "
                "Memory. Never treat evaluation-only boundaries as legal admission."
            ),
        )
        executor.finish_run()
    except BaseException as exc:
        executor.fail_run(exc)
        raise
    finally:
        organizer.close()

    expected_refs = [
        str(item.get("sourceRef") or "")
        for item in bundle.get("inputs") or []
        if isinstance(item, Mapping)
    ]
    curation = redacted_semantic_curation_summary(
        result,
        expected_source_refs=expected_refs,
    )
    requests = redacted_luna_request_summary(executor.receipts)
    phases = [str(item.get("phase") or "") for item in requests]
    source_unchanged = _file_identity(source_db) == source_before
    atom_phase_optional = int(curation.get("memoryAtomCount") or 0) == 0
    valid_phase_sequence = phases == [
        "evidence-adjudication",
        "atom-adjudication",
        "independent-verifier",
    ] or (
        atom_phase_optional
        and phases == ["evidence-adjudication", "independent-verifier"]
    )
    model_ok = (
        valid_phase_sequence
        and all(item.get("model") == "gpt-5.6-luna" for item in requests)
        and all(item.get("thinking") == "max" for item in requests)
        and bool(requests[-1].get("isolated"))
    )
    passed = (
        source_unchanged
        and model_ok
        and bool(curation.get("allSourceRefsCoveredExactlyOnce"))
        and bool(curation.get("independentlyVerified"))
        and recovery.get("legalEvidenceAdmissionAllowed") is False
    )
    summary: dict[str, object] = {
        "schemaVersion": PERSONAL_MEMORY_LUNA_EVALUATION_SCHEMA_VERSION,
        "evaluationKind": "historical_semantic_quality_only",
        "status": "pass" if passed else "iterate",
        "passed": passed,
        "model": "gpt-5.6-luna",
        "thinking": "max",
        "transport": "codex_cli_ephemeral",
        "semanticEvaluationOnly": True,
        "legalEvidenceAdmissionPerformed": False,
        "productionDatabaseOpened": False,
        "productionMutationPerformed": False,
        "sourceShadowUnchanged": source_unchanged,
        "shadowVerification": verification,
        "recovery": recovery,
        "curation": curation,
        "atomPhaseSkippedBecauseNoEligiblePersonalEvidence": (
            "atom-adjudication" not in phases
        ),
        "modelRequests": requests,
        "privateArtifactDirectorySha256": _sha256(str(private_root)),
    }
    _write_private_summary(private_root / "semantic-evaluation-summary.json", summary)
    if args.public_report is not None:
        _write_semantic_public_report(args.public_report.expanduser(), summary)
    print(
        json.dumps(
            {
                "passed": passed,
                "status": summary["status"],
                "model": summary["model"],
                "thinking": summary["thinking"],
                "recovery": recovery,
                "curation": curation,
                "modelRequests": requests,
                "sourceShadowUnchanged": source_unchanged,
                "legalEvidenceAdmissionPerformed": False,
                "productionMutationPerformed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


def _first_result(report: Mapping[str, object]) -> dict[str, object]:
    values = report.get("results")
    if not isinstance(values, list) or not values or not isinstance(values[0], Mapping):
        return {}
    return dict(values[0])


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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_private_summary(path: Path, summary: Mapping[str, object]) -> None:
    temporary = path.with_name("." + path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(dict(summary), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def _write_public_report(path: Path, summary: Mapping[str, object]) -> None:
    if path.exists():
        raise ValueError("public report path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    first = dict(summary.get("firstRun") or {})
    applied = dict(summary.get("appliedState") or {})
    rollback = dict(summary.get("rollback") or {})
    replay = dict(summary.get("replay") or {})
    seed = dict(summary.get("syntheticSeed") or {})
    applied_rag = dict(summary.get("appliedRag") or {})
    rollback_rag = dict(summary.get("rollbackRag") or {})
    replay_rag = dict(summary.get("replayRag") or {})
    requests = [
        dict(item)
        for item in summary.get("modelRequests") or []
        if isinstance(item, Mapping)
    ]
    lines = [
        "# Personal Memory Luna Shadow Evaluation",
        "",
        f"- Result: `{summary.get('status')}`.",
        "- Scope: verified private recovery shadow; production SQLite was not opened or modified.",
        f"- Model: `{summary.get('model')}`, thinking `{summary.get('thinking')}`.",
        f"- Transport: `{summary.get('transport')}`; installed Gateway acceptance remains separate.",
        f"- Source shadow unchanged: `{summary.get('sourceShadowUnchanged')}`.",
        "",
        "## Evidence -> Atom -> Book",
        "",
        f"- First run: `{first.get('ok')}`; scopes `{first.get('ranScopeCount')}`.",
        f"- Current Atoms: `{applied.get('currentAtomCount')}`; governed `{applied.get('governedCurrentAtomCount')}`.",
        f"- Unsupported governed Atoms: `{applied.get('unsupportedGovernedAtomCount')}`.",
        f"- All governed current Atoms have legal lineage: `{applied.get('allGovernedCurrentAtomsHaveLegalLineage')}`.",
        f"- Book projection in sync: `{dict(applied.get('bookProjection') or {}).get('inSync')}`.",
        f"- Logical applied-state SHA-256: `{applied.get('logicalStateSha256')}`.",
        "",
        "## Recovery",
        "",
        f"- Rollback kind: `{rollback.get('kind')}`; pass `{rollback.get('ok')}`.",
        f"- Rollback restored baseline: `{rollback.get('restoredBaseline')}`.",
        f"- Replay attempted: `{replay.get('attempted')}`; pass `{replay.get('ok')}`.",
        f"- Replay reused content-addressed model outputs: `{replay.get('reusedModelRequests')}`.",
        f"- Replay restored identical logical state: `{replay.get('restoredAppliedState')}`.",
        "",
    ]
    if bool(summary.get("syntheticRagFixtureEnabled")):
        lines.extend(
            [
                "## Hybrid RAG acceptance",
                "",
                f"- Synthetic capture-v2 cases: `{seed.get('caseCount')}`; durable `{seed.get('durableCaseCount')}`; non-memory controls `{seed.get('nonMemoryCaseCount')}`.",
                f"- Every fixture stored with candidate Evidence: `{seed.get('allStored') and seed.get('allCandidateEvidence')}`.",
                f"- Applied projection fresh: `{applied_rag.get('projectionFresh')}`; vector coverage `{applied_rag.get('vectorCoverage')}`.",
                f"- Applied hybrid recall passed: `{applied_rag.get('passed')}`; curated Atom count `{applied_rag.get('discoveredAtomCount')}`.",
                f"- Rollback removed the curated Atom set from retrieval: `{rollback_rag.get('passed')}`.",
                f"- Content-addressed replay restored the same Atom set and recall: `{replay_rag.get('passed') and replay.get('ragAtomSetStable')}`.",
                "",
                "| Case | Expected Memory | Linked Atoms | Retrieved | Best rank | Pass |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in applied_rag.get("cases") or []:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "| `{case}` | `{expected}` | `{linked}` | `{retrieved}` | `{rank}` | `{passed}` |".format(
                    case=item.get("caseId"),
                    expected=item.get("expectMemory"),
                    linked=item.get("linkedAtomCount"),
                    retrieved=item.get("retrieved"),
                    rank=item.get("bestRank"),
                    passed=item.get("passed"),
                )
            )
        lines.append("")
    lines.extend(["## Real-model receipts", ""])
    for item in requests:
        lines.append(
            "- `{phase}`: model `{model}`, thinking `{thinking}`, isolated `{isolated}`, "
            "resumed `{resumed}`, elapsed `{elapsed}` s, output `{output}`.".format(
                phase=item.get("phase"),
                model=item.get("model"),
                thinking=item.get("thinking"),
                isolated=item.get("isolated"),
                resumed=item.get("resumed"),
                elapsed=item.get("elapsedSeconds"),
                output=item.get("outputSha256"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This closes the private-shadow real-Luna quality and recovery slice only. "
            "It does not claim installed Gateway, Squirrel, Voice, or Control Center acceptance.",
            "No raw source text, model output, database path, or private identifier is included here.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_semantic_public_report(
    path: Path,
    summary: Mapping[str, object],
) -> None:
    if path.exists():
        raise ValueError("public report path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    recovery = dict(summary.get("recovery") or {})
    curation = dict(summary.get("curation") or {})
    requests = [
        dict(item)
        for item in summary.get("modelRequests") or []
        if isinstance(item, Mapping)
    ]
    lines = [
        "# Personal Memory Luna Historical Semantic Evaluation",
        "",
        f"- Result: `{summary.get('status')}`.",
        "- Scope: approved historical Timeline inside a verified private recovery shadow.",
        "- This is classification quality evidence only; legacy rows were not admitted, persisted, or relabeled as canonical Evidence.",
        f"- Model: `{summary.get('model')}`, thinking `{summary.get('thinking')}`.",
        f"- Source shadow unchanged: `{summary.get('sourceShadowUnchanged')}`.",
        "",
        "## Historical expression recovery",
        "",
        f"- Raw Timeline events: `{recovery.get('rawEventCount')}`.",
        f"- Raw input-method events: `{recovery.get('rawInputMethodEventCount')}`.",
        f"- Strong-final candidates: `{recovery.get('strongFinalCandidateCount')}`.",
        f"- Bounded-context recovered candidates: `{recovery.get('contextRecoveredCandidateCount')}`.",
        f"- Ambiguous fragments excluded: `{recovery.get('ambiguousExcludedCount')}`.",
        f"- Sensitive rows excluded: `{recovery.get('sensitiveExcludedCount')}`.",
        f"- Exact duplicate snapshots removed: `{recovery.get('deduplicatedCandidateCount')}`.",
        f"- Luna inputs: `{recovery.get('modelInputCount')}` expressions representing `{recovery.get('representedSourceEventCount')}` source events.",
        f"- Frozen semantic bundle SHA-256: `{recovery.get('semanticBundleSha256')}`.",
        "",
        "## Luna classification",
        "",
        f"- Exact source-ref coverage: `{curation.get('allSourceRefsCoveredExactlyOnce')}`.",
        f"- Dispositions: `{json.dumps(curation.get('dispositionCounts') or {}, sort_keys=True)}`.",
        f"- Proposed Atom count: `{curation.get('memoryAtomCount')}`.",
        f"- Proposed Atom kinds: `{json.dumps(curation.get('memoryAtomKindCounts') or {}, sort_keys=True)}`.",
        f"- Independent verifier passed: `{curation.get('independentlyVerified')}`.",
        f"- Redacted result SHA-256: `{curation.get('resultSha256')}`.",
        "",
        "## Real-model receipts",
        "",
    ]
    for item in requests:
        lines.append(
            "- `{phase}`: model `{model}`, thinking `{thinking}`, isolated `{isolated}`, "
            "resumed `{resumed}`, elapsed `{elapsed}` s, output `{output}`.".format(
                phase=item.get("phase"),
                model=item.get("model"),
                thinking=item.get("thinking"),
                isolated=item.get("isolated"),
                resumed=item.get("resumed"),
                elapsed=item.get("elapsedSeconds"),
                output=item.get("outputSha256"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This validates the compact personal-v2 prompts against real private history while preserving the fail-closed Evidence boundary. It does not replace legal capture-v2 lineage, RAG retrieval acceptance, or installed foreground acceptance.",
            "No raw input, reconstructed expression, Atom text, model output, database path, or private identifier is included in this report.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
