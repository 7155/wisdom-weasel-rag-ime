from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Mapping

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations, sqlite_connection


class AgentLabExperimentConflict(RuntimeError):
    """A persisted experiment revision was rebound to different content."""


class AgentLabExperimentStore:
    """Append-only, revisioned storage for public-safe Agent Lab summaries."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            return apply_database_migrations(conn).current_version

    def persist(self, payload: Mapping[str, object]) -> dict[str, object]:
        experiment = dict(payload)
        validate_contract(experiment, "agent-lab-experiment.v1.json")
        canonical = _canonical_json(experiment)
        payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        experiment_id = str(experiment["experimentId"])
        revision = str(experiment["revisionSha256"])

        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT payload_hash, payload_json
                FROM agent_lab_experiment_revisions
                WHERE experiment_id = ? AND revision_sha256 = ?
                """,
                (experiment_id, revision),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["payload_hash"]) != payload_hash
                    or str(existing["payload_json"]) != canonical
                ):
                    raise AgentLabExperimentConflict(
                        f"Agent Lab experiment {experiment_id!r} revision {revision!r} changed"
                    )
                return _decode(str(existing["payload_json"]))
            conn.execute(
                """
                INSERT INTO agent_lab_experiment_revisions(
                    experiment_id, revision_sha256, imported_at_ms,
                    payload_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    revision,
                    int(experiment["importedAtMs"]),
                    payload_hash,
                    canonical,
                ),
            )
        return dict(experiment)

    def list_latest(self) -> list[dict[str, object]]:
        self.initialize()
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            rows = conn.execute(
                """
                SELECT experiment_id, payload_json
                FROM agent_lab_experiment_revisions
                ORDER BY imported_at_ms DESC, rowid DESC
                """
            ).fetchall()
        latest: list[dict[str, object]] = []
        seen: set[str] = set()
        for row in rows:
            experiment_id = str(row["experiment_id"])
            if experiment_id in seen:
                continue
            seen.add(experiment_id)
            latest.append(_decode(str(row["payload_json"])))
        latest.sort(key=lambda item: str(item["experimentId"]))
        return latest


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _decode(raw: str) -> dict[str, object]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("persisted Agent Lab experiment is not an object")
    # Revisions written before the factor/control contract remain readable. Do
    # not rewrite their append-only rows; expose an explicit legacy projection
    # so the API can keep serving old receipts while the next import records
    # the richer experiment identity.
    payload.setdefault(
        "factors",
        [{
            "name": "workflow",
            "before": "旧版回执未记录",
            "after": "待补实验变量",
            "reason": "该 revision 产生于 Agent Lab 变量合同之前。",
        }],
    )
    payload.setdefault(
        "frozenControls",
        [{
            "name": "legacy_revision",
            "value": "仅按原始 revision 读取",
            "reason": "旧版回执没有显式冻结控制投影。",
        }],
    )
    # Older append-only revisions predate the current/history projection. They
    # remain current unless a later import explicitly supersedes them.
    payload.setdefault("projectionState", "current")
    validate_contract(payload, "agent-lab-experiment.v1.json")
    return payload
