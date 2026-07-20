from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

from .db import apply_database_migrations


ROOM_V2_RELEASE_MIGRATION_VERSION = 94
ROOM_V2_RELEASE_SCHEMA_COUNT = 136


def stage_room_v2_canary(*, product_root: str | Path, pi_root: str | Path, source_db: str | Path,
                         frontend_dist: str | Path, output_dir: str | Path, pi_build: str | Path | None = None) -> dict[str, object]:
    """Stage and inspect a canary without mutating the source checkout, DB, or installed apps."""
    product = Path(product_root).resolve(); pi = Path(pi_root).resolve(); source = Path(source_db).resolve()
    frontend = Path(frontend_dist).resolve(); output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError("canary staging output already exists")
    output.mkdir(parents=True)
    staged_db = output / "room-v2-dry-run.sqlite"
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as incoming, sqlite3.connect(staged_db) as staged:
        incoming.backup(staged)
        migration = apply_database_migrations(staged, applied_at_ms=0)
        quick_check = str(staged.execute("PRAGMA quick_check").fetchone()[0])
        foreign_keys = staged.execute("PRAGMA foreign_key_check").fetchall()
    schema_paths = sorted((product / "rag_ime/contracts/json").glob("*.json"))
    pi_build_path = Path(pi_build).resolve() if pi_build else None
    checks = {
        "productClean": not _git(product, "status", "--porcelain"),
        "piClean": not _git(pi, "status", "--porcelain"),
        "migrationVersion": migration.current_version,
        "expectedMigrationVersion": ROOM_V2_RELEASE_MIGRATION_VERSION,
        "databaseQuickCheck": quick_check,
        "databaseForeignKeyErrors": len(foreign_keys),
        "schemaCount": len(schema_paths),
        "expectedSchemaCount": ROOM_V2_RELEASE_SCHEMA_COUNT,
        "frontendPresent": frontend.is_dir(),
        "defaultOff": os.environ.get("RAG_IME_ROOM_KERNEL_MODE", "off").strip().lower() == "off",
        "piBuildPresent": bool(pi_build_path and pi_build_path.exists()),
    }
    readiness = {
        "product": _git(product, "rev-parse", "HEAD"),
        "pi": _git(pi, "rev-parse", "HEAD"),
        "migration": _sha256(staged_db),
        "schema": _tree_hash(schema_paths),
        "routes": _sha256(product / "control-center-web/src/platform/routes.ts"),
        "prompt": _tree_hash(sorted((product / "rag_ime").glob("*prompt*.py"))),
        "skills": _tree_hash(sorted((product / "rag_ime/contracts/json").glob("room-skill-*.json"))),
        "tools": _tree_hash(sorted((product / "rag_ime/contracts/json").glob("room-tool-*.json"))),
        "knowledge": _sha256(product / "rag_ime/agent_knowledge_promotion.py"),
        "profile": _sha256(product / "rag_ime/collaboration_profile_control.py"),
        "governance": _sha256(product / "rag_ime/agent_governance_projection.py"),
        "frontend": _tree_hash([path for path in frontend.rglob("*") if path.is_file()]) if frontend.is_dir() else "missing",
    }
    remaining = []
    if not all((checks["productClean"], checks["piClean"],
                checks["migrationVersion"] == checks["expectedMigrationVersion"], quick_check == "ok",
                not foreign_keys, checks["schemaCount"] == checks["expectedSchemaCount"],
                checks["frontendPresent"], checks["defaultOff"], checks["piBuildPresent"])):
        remaining.append("local_provenance_or_dry_run")
    remaining.extend(("loopback_worker_control_e2e", "metal_runtime_e2e", "network_provider_e2e", "named_canary_metrics", "administrator_promotion_approval"))
    receipt = {
        "schemaVersion": "rag-ime.room-v2-release-receipt.v1", "status": "staged_not_installed",
        "productionCanaryEligible": not remaining, "sourceDatabaseModified": False, "installedAppsModified": False,
        "productBranch": _git(product, "branch", "--show-current"), "productCommit": readiness["product"],
        "piCommit": readiness["pi"], "piBuildSha256": _sha256(pi_build_path) if pi_build_path and pi_build_path.is_file() else "",
        "checks": checks, "readiness": readiness, "readinessHash": _hash(readiness), "remainingGates": remaining,
        "stagedDatabase": staged_db.name,
    }
    receipt["receiptHash"] = _hash(receipt)
    (output / "release-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(str(path).encode()); digest.update(b"\0"); digest.update(_sha256(path).encode()); digest.update(b"\0")
    return digest.hexdigest()


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
