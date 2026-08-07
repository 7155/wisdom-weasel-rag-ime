from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from ..agent_room_kernel_contracts import validate_kernel_contract
from ..room_domain.model import DomainPolicyError
from ..room_domain.scheduling import validate_task_graph


class RoomPlanRepository:
    """Durable approved outcome graph; execution attempts never live here."""

    @staticmethod
    def propose(
        conn: sqlite3.Connection,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        plan = dict(payload)
        validate_kernel_contract("roomPlanRevision", plan)
        RoomPlanRepository._validate_graph(plan)
        encoded = _json(plan)
        existing = conn.execute(
            "SELECT payload_json FROM room_plan_revisions WHERE plan_revision_id=?",
            (plan["planRevisionId"],),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_json"]) != encoded:
                raise DomainPolicyError("plan revision identity was rebound")
            return json.loads(str(existing["payload_json"]))
        active = conn.execute(
            "SELECT 1 FROM room_plan_revisions WHERE root_id=? AND state='active'",
            (plan["rootId"],),
        ).fetchone()
        if active is not None:
            raise DomainPolicyError("active plan revision cannot be replaced implicitly")
        conn.execute(
            """INSERT INTO room_plan_revisions(
               plan_revision_id,root_id,revision,state,
               requirement_catalog_revision_id,work_document_ref_json,
               payload_json,created_at_ms,activated_at_ms)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                plan["planRevisionId"],
                plan["rootId"],
                plan["revision"],
                plan["state"],
                plan["requirementCatalogRevisionId"],
                None,
                encoded,
                plan["createdAtMs"],
                None,
            ),
        )
        return plan

    @staticmethod
    def latest(
        conn: sqlite3.Connection,
        root_id: str,
    ) -> dict[str, object] | None:
        row = conn.execute(
            """SELECT payload_json FROM room_plan_revisions
               WHERE root_id=? ORDER BY revision DESC LIMIT 1""",
            (root_id,),
        ).fetchone()
        return json.loads(str(row["payload_json"])) if row is not None else None

    @staticmethod
    def activate(
        conn: sqlite3.Connection,
        *,
        plan_revision_id: str,
        work_document_ref: Mapping[str, object],
        activated_at_ms: int,
    ) -> dict[str, object]:
        row = conn.execute(
            "SELECT * FROM room_plan_revisions WHERE plan_revision_id=?",
            (plan_revision_id,),
        ).fetchone()
        if row is None:
            raise KeyError(plan_revision_id)
        plan = json.loads(str(row["payload_json"]))
        reference = {
            "documentId": str(work_document_ref.get("documentId") or ""),
            "contentSha256": str(work_document_ref.get("contentSha256") or ""),
            "documentRevision": work_document_ref.get("documentRevision"),
        }
        if not reference["documentId"] or not reference["contentSha256"]:
            raise DomainPolicyError("plan activation requires its WorkDocument receipt")
        activated = {
            **plan,
            "state": "active",
            "activatedAtMs": int(activated_at_ms),
            "workDocumentRef": reference,
        }
        validate_kernel_contract("roomPlanRevision", activated)
        if str(row["state"]) == "active":
            if str(row["payload_json"]) != _json(activated):
                raise DomainPolicyError("active plan revision was rebound")
            return activated
        if str(row["state"]) != "proposed":
            raise DomainPolicyError("only a proposed plan revision can be activated")
        cursor = conn.execute(
            """UPDATE room_plan_revisions
               SET state='active',work_document_ref_json=?,payload_json=?,activated_at_ms=?
               WHERE plan_revision_id=? AND state='proposed'""",
            (
                _json(reference),
                _json(activated),
                int(activated_at_ms),
                plan_revision_id,
            ),
        )
        if cursor.rowcount != 1:
            raise DomainPolicyError("plan revision activation lost its compare-and-set")
        return activated

    @staticmethod
    def _validate_graph(plan: Mapping[str, object]) -> None:
        tasks = plan.get("tasks")
        if not isinstance(tasks, list):
            raise DomainPolicyError("plan tasks must be an array")
        graph = {
            str(task.get("taskId") or ""): [
                str(value) for value in task.get("dependencyTaskIds") or []
            ]
            for task in tasks
            if isinstance(task, Mapping)
        }
        if len(graph) != len(tasks):
            raise DomainPolicyError("plan task identity is duplicated or invalid")
        validate_task_graph(graph)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
