from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NotRequired, TypedDict

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations, sqlite_connection


WorkDocumentState = Literal[
    "active", "archive_pending", "archived", "reopen_pending", "error"
]


class WorkDocumentPayload(TypedDict):
    documentId: str
    authorityKind: Literal["session_todo", "session_goal", "room_work_item"]
    authorityId: str
    authorityRevision: int
    authorityKey: str
    documentRevision: int
    contentSha256: str
    workspaceRoot: str
    path: str
    activePath: str
    archivePath: str
    state: WorkDocumentState
    title: str
    terminalReceiptId: str
    error: str
    createdAtMs: int
    updatedAtMs: int


class WorkDocumentReopenContext(TypedDict):
    eligible: bool
    authorityRevision: int
    transitionReceiptId: str
    reasonCode: Literal[
        "ready",
        "document_not_archived",
        "authority_terminal",
        "authority_not_advanced",
        "authority_unavailable",
    ]


class WorkDocumentReceipt(TypedDict):
    receiptId: str
    operation: str
    status: Literal["accepted", "applied", "failed"]
    idempotent: bool
    createdAtMs: int


class WorkDocumentListResponse(TypedDict):
    schemaVersion: Literal["rag-ime.work-document-list.v1"]
    items: list[WorkDocumentPayload]
    total: int


class WorkDocumentDetailResponse(TypedDict):
    schemaVersion: Literal["rag-ime.work-document-detail.v1"]
    document: WorkDocumentPayload
    reopen: WorkDocumentReopenContext


class WorkDocumentCommandResponse(TypedDict):
    schemaVersion: Literal["rag-ime.work-document-command.v1"]
    ok: bool
    operation: str
    document: WorkDocumentPayload | None
    receipt: NotRequired[WorkDocumentReceipt]
    approval: NotRequired[dict[str, object]]
    payloadSha256: NotRequired[str]


class WorkDocumentContextItem(TypedDict):
    documentId: str
    title: str
    path: str
    contentSha256: str
    authorityKey: str
    workspaceRoot: NotRequired[str]
    canonicalPath: NotRequired[str]
    authorityKind: NotRequired[str]
    authorityId: NotRequired[str]
    authorityRevision: NotRequired[int]
    documentRevision: NotRequired[int]
    state: NotRequired[str]
    snapshot: NotRequired[dict[str, object]]


class WorkDocumentContextResponse(TypedDict):
    schemaVersion: Literal["rag-ime.work-document-context.v1"]
    items: list[WorkDocumentContextItem]


class WorkDocumentError(RuntimeError):
    pass


_KINDS = frozenset({"session_todo", "session_goal", "room_work_item"})
_SENSITIVE = frozenset({".git", ".ssh", ".aws", ".env", "secrets", "credentials", "keychains"})


class WorkDocumentService:
    """Registry and crash-safe filesystem reconciler for authority-bound work documents."""
    def __init__(
        self, db_path: str | Path, *, sessions: Any, context_runtime: Any
    ) -> None:
        self.db_path = Path(db_path)
        self.sessions = sessions
        self.context_runtime = context_runtime
        self._lock = threading.RLock()

    def initialize(self) -> None:
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            apply_database_migrations(conn)
        self.reconcile(retry_failed_observers=True)

    def preflight_register(self, payload: Mapping[str, object]) -> None:
        """Validate a receipt-bound registration before its approved file write."""
        kind = _required(payload.get("authorityKind"), "authorityKind", 40)
        authority_id = _required(payload.get("authorityId"), "authorityId", 240)
        revision = _integer(payload.get("authorityRevision"), "authorityRevision")
        if kind not in _KINDS:
            raise WorkDocumentError("unsupported work-document authority kind")
        root = Path(
            _required(payload.get("workspaceRoot"), "workspaceRoot", 2000)
        ).expanduser().resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            raise WorkDocumentError("workspaceRoot must be a real directory")
        relative = _relative(
            _required(payload.get("sourcePath"), "sourcePath", 1000)
        )
        if not relative.startswith("docs/") or not relative.endswith(".md"):
            raise WorkDocumentError("work documents must be Markdown files below docs/")
        if relative.startswith("docs/agent/work/archive/"):
            raise WorkDocumentError("archived paths require explicit reopen")
        source = _resolve(root, relative)
        authority_key = f"{kind}:{authority_id}"
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            authority = self._authority(conn, kind, authority_id)
            if authority["revision"] != revision:
                raise WorkDocumentError("authority revision is stale")
            if authority["terminal"]:
                raise WorkDocumentError(
                    "terminal authority cannot register an active document"
                )
            existing = conn.execute(
                "SELECT * FROM work_documents WHERE authority_key=?",
                (authority_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["state"]) == "archived":
                    raise WorkDocumentError(
                        "archived document must be reopened through its authority"
                    )
                if _resolve(root, str(existing["relative_path"])) != source:
                    raise WorkDocumentError(
                        "updates must use the canonical active path"
                    )

    def register(self, payload: Mapping[str, object]) -> dict[str, object]:
        kind = _required(payload.get("authorityKind"), "authorityKind", 40)
        authority_id = _required(payload.get("authorityId"), "authorityId", 240)
        revision = _integer(payload.get("authorityRevision"), "authorityRevision")
        if kind not in _KINDS:
            raise WorkDocumentError("unsupported work-document authority kind")
        root, source_relative, source = _source(payload.get("workspaceRoot"), payload.get("sourcePath"))
        authority_key = f"{kind}:{authority_id}"
        document_id = _document_id(authority_key)
        active_relative = f"docs/agent/work/active/{kind}/{document_id}.md"
        archive_relative = f"docs/agent/work/archive/{kind}/{document_id}.md"
        digest = _sha256_file(source)
        now = _now_ms()
        title = _text(payload.get("title"), 240)
        operation_key = _register_operation_key(
            document_id,
            authority_revision=revision,
            content_sha256=digest,
            title=title,
        )
        with self._lock, sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            authority = self._authority(conn, kind, authority_id)
            if authority["revision"] != revision:
                raise WorkDocumentError("authority revision is stale")
            if authority["terminal"]:
                raise WorkDocumentError("terminal authority cannot register an active document")
            existing = conn.execute("SELECT * FROM work_documents WHERE authority_key = ?", (authority_key,)).fetchone()
            if existing is not None:
                if str(existing["state"]) == "archived":
                    raise WorkDocumentError("archived document must be reopened through its authority")
                canonical = _resolve(root, str(existing["relative_path"]))
                if canonical != source:
                    raise WorkDocumentError("updates must use the canonical active path")
                failed_receipt = conn.execute(
                    "SELECT 1 FROM work_document_operation_receipts "
                    "WHERE operation_key=? AND status='failed'",
                    (operation_key,),
                ).fetchone()
                if failed_receipt is not None:
                    return _command(
                        "register",
                        _payload(existing),
                        self._receipt(
                            conn,
                            operation_key,
                            document_id,
                            "register",
                            "failed",
                            True,
                            now,
                        ),
                    )
                prior_receipt = conn.execute(
                    "SELECT status FROM work_document_operation_receipts "
                    "WHERE operation_key=?",
                    (operation_key,),
                ).fetchone()
                if (
                    prior_receipt is not None
                    and str(prior_receipt["status"]) == "applied"
                    and int(existing["authority_revision"]) == revision
                    and str(existing["title"]) == title
                    and str(existing["content_sha256"]) == digest
                ):
                    # A context refresh must not mutate workspace bytes when
                    # the governed document is already at this exact revision.
                    return _command(
                        "register",
                        _payload(existing),
                        self._receipt(
                            conn,
                            operation_key,
                            document_id,
                            "register",
                            "applied",
                            True,
                            now,
                        ),
                    )
                document_revision = int(existing["document_revision"]) + int(
                    digest != str(existing["content_sha256"])
                )
                duplicate = prior_receipt is not None
                conn.execute(
                    "UPDATE work_documents SET authority_revision=?,document_revision=?,title=?,content_sha256=?,error='',updated_at_ms=? WHERE document_id=?",
                    (revision, document_revision, title, digest, now, document_id),
                )
                receipt = self._receipt(
                    conn,
                    operation_key,
                    document_id,
                    "register",
                    "applied",
                    duplicate,
                    now,
                )
            else:
                conn.execute(
                    """INSERT INTO work_documents(
                    document_id,authority_kind,authority_id,authority_revision,authority_key,
                    document_revision,title,workspace_root,relative_path,active_relative_path,
                    archive_relative_path,content_sha256,state,created_at_ms,updated_at_ms
                    ) VALUES(?,?,?,?,?,1,?,?,?,?,?,?,'active',?,?)""",
                    (document_id, kind, authority_id, revision, authority_key, title, str(root), source_relative, active_relative, archive_relative, digest, now, now),
                )
                self._enqueue(conn, operation_key, document_id, "activate", source_relative, active_relative, now)
                receipt = self._receipt(conn, operation_key, document_id, "register", "accepted", False, now)
        self.reconcile(document_id)
        document = self._get(document_id)
        receipt_status = "applied" if document["state"] == "active" else "failed"
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            conn.execute(
                "UPDATE work_document_operation_receipts SET status=? "
                "WHERE receipt_id=?",
                (receipt_status, receipt["receiptId"]),
            )
        receipt["status"] = receipt_status
        return _command("register", document, receipt)

    def ensure_room_work_item(
        self,
        *,
        authority_id: str,
        workspace_root: str | Path,
        title: str,
        content: str,
    ) -> WorkDocumentPayload:
        """Create the one governed document for a started Room root WorkItem.

        Typed Room Start is itself the user's write authorization.  This helper
        turns that authorization into one deterministic staging file and then
        uses the ordinary WorkDocument registry/reconciler.  Replays return the
        existing authority-bound document and never create a peer-owned copy.
        """

        normalized_authority_id = _required(
            authority_id, "authorityId", 240
        )
        normalized_title = _text(title, 240)
        if not str(content).strip():
            raise WorkDocumentError("Room work-document content is required")
        root = Path(workspace_root).expanduser().resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            raise WorkDocumentError("workspaceRoot must be a real directory")
        authority_key = f"room_work_item:{normalized_authority_id}"
        document_id = _document_id(authority_key)
        with self._lock:
            with sqlite_connection(
                self.db_path,
                row_factory=sqlite3.Row,
                foreign_keys=True,
            ) as conn:
                authority = self._authority(
                    conn, "room_work_item", normalized_authority_id
                )
                existing = conn.execute(
                    "SELECT * FROM work_documents WHERE authority_key=?",
                    (authority_key,),
                ).fetchone()
                if existing is not None:
                    payload = _payload(existing)
                    if Path(payload["workspaceRoot"]).resolve() != root:
                        raise WorkDocumentError(
                            "Room WorkItem is already bound to another workspace"
                        )
                    if payload["state"] != "active":
                        raise WorkDocumentError(
                            "started Room WorkItem requires an active WorkDocument"
                        )
                    return payload
                revision = int(authority["revision"])
            relative = (
                "docs/agent/work/register/room_work_item/"
                f"{document_id}.md"
            )
            source = _resolve(root, relative)
            encoded = str(content).encode("utf-8")
            expected = hashlib.sha256(encoded).hexdigest()
            source.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                if (
                    source.is_symlink()
                    or not source.is_file()
                    or _sha256_file(source) != expected
                ):
                    raise WorkDocumentError(
                        "Room work-document staging file changed before registration"
                    )
            else:
                _atomic_bytes(source, encoded)
            result = self.register(
                {
                    "authorityKind": "room_work_item",
                    "authorityId": normalized_authority_id,
                    "authorityRevision": revision,
                    "workspaceRoot": str(root),
                    "sourcePath": relative,
                    "title": normalized_title,
                }
            )
            document = result.get("document")
            if not isinstance(document, Mapping):
                raise WorkDocumentError(
                    "Room work-document registration returned no document"
                )
            return WorkDocumentPayload(**dict(document))

    def append_room_delta_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        root_id: str,
        delta_id: str,
        delta_kind: str,
        source_ref: str,
        content: str,
        created_at_ms: int,
    ) -> dict[str, object]:
        """Record an idempotent structured delta in the caller's transaction.

        The database row is the durable recovery fact. Markdown materialization
        happens after commit (and again on every context read), so a process
        crash cannot lose an accepted correction or create a second document.
        """

        normalized_root_id = _required(root_id, "rootId", 320)
        normalized_delta_id = _required(delta_id, "deltaId", 320)
        normalized_kind = _required(delta_kind, "deltaKind", 80)
        if normalized_kind not in {
            "user_correction",
            "progress",
            "evidence",
            "failure_recovery",
            "handoff",
            "next_action",
            "plan_revision",
        }:
            raise WorkDocumentError("unsupported Room WorkDocument delta kind")
        normalized_source_ref = _required(source_ref, "sourceRef", 320)
        content_bytes = str(content).encode("utf-8")
        if not content_bytes:
            raise WorkDocumentError("Room WorkDocument delta content is required")
        digest = hashlib.sha256(content_bytes).hexdigest()
        created = _integer(created_at_ms, "createdAtMs")
        document = conn.execute(
            """
            SELECT d.document_id,d.state
            FROM work_documents AS d
            JOIN agent_room_work_items AS w ON w.id=d.authority_id
            WHERE d.authority_kind='room_work_item'
              AND w.root_turn_id=? AND w.root_work_id=w.id
            """,
            (normalized_root_id,),
        ).fetchone()
        if document is None:
            raise WorkDocumentError(
                "started Room Root has no governed WorkDocument"
            )
        if str(document["state"]) != "active":
            raise WorkDocumentError(
                "Room WorkDocument delta requires an active document"
            )
        existing = conn.execute(
            "SELECT * FROM room_work_document_deltas WHERE delta_id=?",
            (normalized_delta_id,),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["root_id"]) != normalized_root_id
                or str(existing["document_id"]) != str(document["document_id"])
                or str(existing["delta_kind"]) != normalized_kind
                or str(existing["source_ref"]) != normalized_source_ref
                or str(existing["content_sha256"]) != digest
            ):
                raise WorkDocumentError(
                    "Room WorkDocument delta identity was rebound"
                )
            return _room_delta_payload(existing)
        sequence = int(
            conn.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 "
                "FROM room_work_document_deltas WHERE root_id=?",
                (normalized_root_id,),
            ).fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO room_work_document_deltas(
                delta_id,document_id,root_id,sequence,delta_kind,source_ref,
                content_bytes,content_sha256,created_at_ms,materialized_at_ms
            ) VALUES (?,?,?,?,?,?,?,?,?,NULL)
            """,
            (
                normalized_delta_id,
                str(document["document_id"]),
                normalized_root_id,
                sequence,
                normalized_kind,
                normalized_source_ref,
                content_bytes,
                digest,
                created,
            ),
        )
        row = conn.execute(
            "SELECT * FROM room_work_document_deltas WHERE delta_id=?",
            (normalized_delta_id,),
        ).fetchone()
        if row is None:  # pragma: no cover - protected by the transaction
            raise RuntimeError("Room WorkDocument delta did not persist")
        return _room_delta_payload(row)

    def materialize_room_root(self, root_id: str) -> dict[str, object] | None:
        """Apply every durable delta to the one canonical Markdown document."""

        normalized_root_id = _required(root_id, "rootId", 320)
        with self._lock:
            with sqlite_connection(
                self.db_path,
                row_factory=sqlite3.Row,
                foreign_keys=True,
            ) as conn:
                row = conn.execute(
                    """
                    SELECT d.*
                    FROM work_documents AS d
                    JOIN agent_room_work_items AS w ON w.id=d.authority_id
                    WHERE d.authority_kind='room_work_item'
                      AND w.root_turn_id=? AND w.root_work_id=w.id
                    """,
                    (normalized_root_id,),
                ).fetchone()
                if row is None:
                    return None
                payload = _payload(row)
                deltas = conn.execute(
                    """
                    SELECT * FROM room_work_document_deltas
                    WHERE root_id=? ORDER BY sequence,delta_id
                    """,
                    (normalized_root_id,),
                ).fetchall()
                authority = self._authority(
                    conn,
                    "room_work_item",
                    str(payload["authorityId"]),
                )
            if payload["state"] != "active" or not deltas:
                return payload
            canonical = _resolve(
                Path(payload["workspaceRoot"]), str(payload["path"])
            )
            if canonical.is_symlink() or not canonical.is_file():
                raise WorkDocumentError(
                    "canonical Room WorkDocument is unavailable"
                )
            current = canonical.read_text(encoding="utf-8")
            changed = False
            for delta in deltas:
                marker = f"<!-- room-work-document-delta:{delta['delta_id']} -->"
                if marker in current:
                    continue
                current = _append_room_document_delta(
                    current,
                    marker=marker,
                    delta_kind=str(delta["delta_kind"]),
                    source_ref=str(delta["source_ref"]),
                    content=bytes(delta["content_bytes"]).decode("utf-8"),
                )
                changed = True
            if changed:
                _atomic_bytes(canonical, current.encode("utf-8"))
            refreshed = self.register(
                {
                    "authorityKind": "room_work_item",
                    "authorityId": payload["authorityId"],
                    "authorityRevision": int(authority["revision"]),
                    "workspaceRoot": payload["workspaceRoot"],
                    "sourcePath": payload["path"],
                    "title": payload["title"],
                }
            ).get("document")
            if not isinstance(refreshed, Mapping):
                raise WorkDocumentError(
                    "Room WorkDocument materialization returned no document"
                )
            now = _now_ms()
            with sqlite_connection(
                self.db_path,
                foreign_keys=True,
            ) as conn:
                conn.execute(
                    """
                    UPDATE room_work_document_deltas
                    SET materialized_at_ms=COALESCE(materialized_at_ms,?)
                    WHERE root_id=?
                    """,
                    (now, normalized_root_id),
                )
            return dict(refreshed)

    def room_root_context(
        self, root_id: str
    ) -> WorkDocumentContextItem | None:
        """Return the single canonical document shared by every Root Dispatch.

        Active documents are re-registered from their canonical path so normal
        facilitator edits advance the governed content hash before the next
        participant receives context.  Archived documents remain readable for
        close/report Dispatches but are never reactivated here.
        """

        normalized_root_id = _required(root_id, "rootId", 320)
        self.materialize_room_root(normalized_root_id)
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            rows = conn.execute(
                """
                SELECT d.*
                FROM work_documents d
                JOIN agent_room_work_items w ON w.id=d.authority_id
                WHERE d.authority_kind='room_work_item'
                  AND w.root_turn_id=?
                  AND w.root_work_id=w.id
                ORDER BY d.created_at_ms,d.document_id
                """,
                (normalized_root_id,),
            ).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise WorkDocumentError(
                    "Room Root has more than one governed WorkDocument"
                )
            payload = _payload(rows[0])
            if payload["state"] == "active":
                authority = self._authority(
                    conn,
                    "room_work_item",
                    str(payload["authorityId"]),
                )
                authority_revision = int(authority["revision"])
            else:
                authority_revision = int(payload["authorityRevision"])
        if payload["state"] == "active":
            refreshed = self.register(
                {
                    "authorityKind": "room_work_item",
                    "authorityId": payload["authorityId"],
                    "authorityRevision": authority_revision,
                    "workspaceRoot": payload["workspaceRoot"],
                    "sourcePath": payload["path"],
                    "title": payload["title"],
                }
            ).get("document")
            if not isinstance(refreshed, Mapping):
                raise WorkDocumentError(
                    "Room work-document refresh returned no document"
                )
            payload = WorkDocumentPayload(**dict(refreshed))
        canonical = _resolve(
            Path(payload["workspaceRoot"]), str(payload["path"])
        )
        snapshot = _bounded_utf8_snapshot(
            canonical,
            expected_sha256=str(payload["contentSha256"]),
        )
        return {
            "documentId": str(payload["documentId"]),
            "title": str(payload["title"]),
            "path": str(payload["path"]),
            "contentSha256": str(payload["contentSha256"]),
            "authorityKey": str(payload["authorityKey"]),
            "workspaceRoot": str(payload["workspaceRoot"]),
            "canonicalPath": str(canonical),
            "authorityKind": str(payload["authorityKind"]),
            "authorityId": str(payload["authorityId"]),
            "authorityRevision": int(payload["authorityRevision"]),
            "documentRevision": int(payload["documentRevision"]),
            "state": str(payload["state"]),
            "snapshot": snapshot,
        }

    def list(
        self,
        query: Mapping[str, object] | None = None,
        *,
        limit: object = 100,
    ) -> WorkDocumentListResponse:
        if query is not None:
            limit = query.get("limit", limit)
        self.reconcile()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            rows = conn.execute(
                "SELECT * FROM work_documents WHERE state IN ('active','archive_pending','reopen_pending','error') ORDER BY updated_at_ms DESC,document_id LIMIT ?",
                (_limit(limit),),
            ).fetchall()
            total = int(conn.execute("SELECT COUNT(*) FROM work_documents WHERE state IN ('active','archive_pending','reopen_pending','error')").fetchone()[0])
        return _validated(
            {
                "schemaVersion": "rag-ime.work-document-list.v1",
                "items": [_payload(row) for row in rows],
                "total": total,
            },
            "work-document-list.v1.json",
        )

    def history_search(
        self,
        arguments: Mapping[str, object] | None = None,
        *,
        query: object = "",
        limit: object = 100,
    ) -> WorkDocumentListResponse:
        if arguments is not None:
            query = arguments.get("query", query)
            limit = arguments.get("limit", limit)
        self.reconcile()
        normalized = _text(query, 240)
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            if normalized:
                like = f"%{normalized.replace('%', '')}%"
                where = "state='archived' AND (title LIKE ? OR authority_id LIKE ? OR relative_path LIKE ?)"
                rows = conn.execute(f"SELECT * FROM work_documents WHERE {where} ORDER BY updated_at_ms DESC,document_id LIMIT ?", (like, like, like, _limit(limit))).fetchall()
                total = int(conn.execute(f"SELECT COUNT(*) FROM work_documents WHERE {where}", (like, like, like)).fetchone()[0])
            else:
                rows = conn.execute("SELECT * FROM work_documents WHERE state='archived' ORDER BY updated_at_ms DESC,document_id LIMIT ?", (_limit(limit),)).fetchall()
                total = int(conn.execute("SELECT COUNT(*) FROM work_documents WHERE state='archived'").fetchone()[0])
        return _validated(
            {
                "schemaVersion": "rag-ime.work-document-list.v1",
                "items": [_payload(row) for row in rows],
                "total": total,
            },
            "work-document-list.v1.json",
        )

    def detail(self, document_id: str) -> WorkDocumentDetailResponse:
        identifier = _identifier(document_id)
        self.reconcile(identifier)
        with sqlite_connection(
            self.db_path,
            row_factory=sqlite3.Row,
            foreign_keys=True,
        ) as conn:
            row = self._row(conn, identifier)
            document = _payload(row)
            reopen = self._reopen_context(conn, row)
        return _validated(
            {
                "schemaVersion": "rag-ime.work-document-detail.v1",
                "document": document,
                "reopen": reopen,
            },
            "work-document-detail.v1.json",
        )

    def request_archive(
        self,
        document_id: str,
        payload: Mapping[str, object],
        *,
        _reconcile: bool = True,
    ) -> WorkDocumentCommandResponse:
        identifier = _identifier(document_id)
        terminal_receipt_id = _required(payload.get("terminalReceiptId"), "terminalReceiptId", 240)
        now = _now_ms()
        with self._lock, sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            row = self._row(conn, identifier)
            operation_key = f"archive:{identifier}:{terminal_receipt_id}"
            if str(row["state"]) == "archived":
                if str(row["terminal_receipt_id"]) != terminal_receipt_id:
                    raise WorkDocumentError("document was archived by a different terminal receipt")
                return _command("archive", _payload(row), self._receipt(conn, operation_key, identifier, "archive", "applied", True, now))
            failed_receipt = conn.execute(
                "SELECT 1 FROM work_document_operation_receipts "
                "WHERE operation_key=? AND status='failed'",
                (operation_key,),
            ).fetchone()
            if failed_receipt is not None:
                return _command(
                    "archive",
                    _payload(row),
                    self._receipt(
                        conn,
                        operation_key,
                        identifier,
                        "archive",
                        "failed",
                        True,
                        now,
                    ),
                )
            authority = self._authority(conn, str(row["authority_kind"]), str(row["authority_id"]))
            if authority["terminalState"] not in {"completed", "cancelled", "failed", "cleared"}:
                raise WorkDocumentError("waiting, blocked, unknown, or nonterminal work cannot be archived")
            if authority["receiptId"] != terminal_receipt_id:
                raise WorkDocumentError("terminal receipt is not canonical for this authority revision")
            authority_revision = int(authority["revision"])
            if authority_revision < int(row["authority_revision"]):
                raise WorkDocumentError("terminal authority revision is stale")
            if (
                authority_revision == int(row["authority_revision"])
                and str(row["terminal_receipt_id"]) not in {"", terminal_receipt_id}
            ):
                raise WorkDocumentError("terminal authority revision conflicts with its recorded receipt")
            current = _resolve(Path(str(row["workspace_root"])), str(row["relative_path"]))
            final_digest = _sha256_file(current)
            document_revision = int(row["document_revision"]) + int(final_digest != str(row["content_sha256"]))
            canonical = {"authorityKind": row["authority_kind"], "authorityId": row["authority_id"], "authorityRevision": authority_revision, "terminalState": authority["terminalState"], "receiptId": terminal_receipt_id}
            receipt_hash = _json_hash(canonical)
            previous = conn.execute("SELECT receipt_sha256 FROM work_document_terminal_receipts WHERE receipt_id=?", (terminal_receipt_id,)).fetchone()
            if previous is None:
                conn.execute("INSERT INTO work_document_terminal_receipts VALUES(?,?,?,?,?,?,?)", (terminal_receipt_id, row["authority_kind"], row["authority_id"], authority_revision, authority["terminalState"], receipt_hash, now))
            elif str(previous[0]) != receipt_hash:
                raise WorkDocumentError("terminal receipt replay changed its authority payload")
            duplicate = conn.execute(
                "SELECT 1 FROM work_document_outbox WHERE operation_key=?",
                (operation_key,),
            ).fetchone() is not None
            conn.execute("UPDATE work_documents SET state='archive_pending',authority_revision=?,terminal_receipt_id=?,document_revision=?,content_sha256=?,error='',updated_at_ms=? WHERE document_id=?", (authority_revision, terminal_receipt_id, document_revision, final_digest, now, identifier))
            self._enqueue(conn, operation_key, identifier, "archive", str(row["relative_path"]), str(row["archive_relative_path"]), now)
            receipt = self._receipt(conn, operation_key, identifier, "archive", "accepted", duplicate, now)
        if _reconcile:
            self.reconcile(identifier, observe_authorities=False)
        document = self._get(identifier)
        receipt["status"] = "applied" if document["state"] == "archived" else "failed" if document["state"] == "error" else "accepted"
        return _command("archive", document, receipt)

    def reopen(
        self, document_id: str, payload: Mapping[str, object]
    ) -> WorkDocumentCommandResponse:
        identifier = _identifier(document_id)
        revision = _integer(payload.get("authorityRevision"), "authorityRevision")
        transition = _required(payload.get("transitionReceiptId"), "transitionReceiptId", 240)
        operation_key = f"reopen:{identifier}:{transition}"
        now = _now_ms()
        with self._lock, sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            row = self._row(conn, identifier)
            if str(row["state"]) == "active" and int(row["authority_revision"]) == revision:
                duplicate = conn.execute(
                    "SELECT 1 FROM work_document_outbox WHERE operation_key=? AND state='applied'",
                    (operation_key,),
                ).fetchone()
                if duplicate is not None:
                    return _command(
                        "reopen",
                        _payload(row),
                        self._receipt(conn, operation_key, identifier, "reopen", "applied", True, now),
                    )
            failed_receipt = conn.execute(
                "SELECT 1 FROM work_document_operation_receipts "
                "WHERE operation_key=? AND status='failed'",
                (operation_key,),
            ).fetchone()
            if failed_receipt is not None:
                return _command(
                    "reopen",
                    _payload(row),
                    self._receipt(
                        conn,
                        operation_key,
                        identifier,
                        "reopen",
                        "failed",
                        True,
                        now,
                    ),
                )
            if str(row["state"]) not in {"archived", "reopen_pending"}:
                raise WorkDocumentError("only archived documents can be reopened")
            authority = self._authority(conn, str(row["authority_kind"]), str(row["authority_id"]))
            if authority["terminal"] or revision != authority["revision"] or revision <= int(row["authority_revision"]):
                raise WorkDocumentError("reopen requires the authority's next legal nonterminal revision")
            if transition != authority["receiptId"]:
                raise WorkDocumentError("reopen transition receipt is not canonical")
            duplicate = conn.execute("SELECT 1 FROM work_document_outbox WHERE operation_key=?", (operation_key,)).fetchone() is not None
            conn.execute("UPDATE work_documents SET state='reopen_pending',authority_revision=?,terminal_receipt_id='',error='',updated_at_ms=? WHERE document_id=?", (revision, now, identifier))
            self._enqueue(conn, operation_key, identifier, "reopen", str(row["relative_path"]), str(row["active_relative_path"]), now)
            receipt = self._receipt(conn, operation_key, identifier, "reopen", "accepted", duplicate, now)
        self.reconcile(identifier, observe_authorities=False)
        document = self._get(identifier)
        receipt["status"] = "applied" if document["state"] == "active" else "failed" if document["state"] == "error" else "accepted"
        return _command("reopen", document, receipt)

    def repair(self, document_id: str) -> WorkDocumentCommandResponse:
        identifier = _identifier(document_id)
        now = _now_ms()
        with self._lock, sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            row = self._row(conn, identifier)
            outbox_cursor = conn.execute("UPDATE work_document_outbox SET state='pending',error='',updated_at_ms=? WHERE document_id=? AND state='failed'", (now, identifier))
            observer_cursor = conn.execute("UPDATE work_document_observer_failures SET state='pending',error='',updated_at_ms=? WHERE document_id=? AND state='failed'", (now, identifier))
            pending = conn.execute("SELECT operation FROM work_document_outbox WHERE document_id=? AND state='pending' ORDER BY created_at_ms DESC LIMIT 1", (identifier,)).fetchone()
            observer_pending = conn.execute("SELECT 1 FROM work_document_observer_failures WHERE document_id=? AND state='pending'", (identifier,)).fetchone()
            if str(row["state"]) == "error" and pending is None and observer_pending is None:
                raise WorkDocumentError("document has no recoverable filesystem or authority observation")
            if pending is not None:
                desired = "archive_pending" if pending[0] == "archive" else "reopen_pending" if pending[0] == "reopen" else "active"
                conn.execute("UPDATE work_documents SET state=?,error='',updated_at_ms=? WHERE document_id=?", (desired, now, identifier))
            receipt = self._receipt(conn, f"repair:{identifier}:{now}", identifier, "repair", "accepted", outbox_cursor.rowcount == 0 and observer_cursor.rowcount == 0, now)
        self.reconcile(identifier)
        document = self._get(identifier)
        receipt_status = "failed" if document["state"] == "error" else "applied"
        with sqlite_connection(self.db_path, foreign_keys=True) as conn:
            conn.execute(
                "UPDATE work_document_operation_receipts SET status=? "
                "WHERE receipt_id=?",
                (receipt_status, receipt["receiptId"]),
            )
        receipt["status"] = receipt_status
        return _command("repair", document, receipt)

    def erase_preview(
        self, document_id: str, payload: Mapping[str, object]
    ) -> WorkDocumentCommandResponse:
        identifier = _identifier(document_id)
        session_id = _required(payload.get("sessionId"), "sessionId", 240)
        document = self._get(identifier)
        bound = {"documentId": identifier, "documentRevision": document["documentRevision"], "contentSha256": document["contentSha256"], "path": document["path"]}
        digest = _json_hash(bound)
        approval = self.sessions.create_approval(session_id=session_id, tool_name="work_document", operation="erase", payload_sha256=digest, preview={**bound, "warning": "Erase permanently deletes document history and content."}, risk_level="R3")
        return _validated(
            {"schemaVersion": "rag-ime.work-document-command.v1", "ok": True, "operation": "erase-preview", "document": document, "approval": approval, "payloadSha256": digest},
            "work-document-command.v1.json",
        )

    def erase(
        self, document_id: str, payload: Mapping[str, object]
    ) -> WorkDocumentCommandResponse:
        identifier = _identifier(document_id)
        session_id = _required(payload.get("sessionId"), "sessionId", 240)
        approval_id = _required(payload.get("approvalId"), "approvalId", 240)
        supplied = _required(payload.get("payloadSha256"), "payloadSha256", 64).lower()
        document = self._get(identifier)
        bound = {"documentId": identifier, "documentRevision": document["documentRevision"], "contentSha256": document["contentSha256"], "path": document["path"]}
        digest = _json_hash(bound)
        approval = self.sessions.get_approval(approval_id)
        valid = approval.get("sessionId") == session_id and approval.get("toolId") == "work_document" and approval.get("operation") == "erase" and approval.get("riskLevel") == "R3" and approval.get("state") == "approved" and approval.get("payloadSha256") == digest and supplied == digest
        if not valid:
            raise WorkDocumentError("erase requires its current hash-bound R3 approval")
        root = Path(str(document["workspaceRoot"]))
        path = _resolve(root, str(document["path"]))
        if path.exists():
            if path.is_symlink() or not path.is_file() or _sha256_file(path) != str(document["contentSha256"]):
                raise WorkDocumentError("work document changed after erase approval")
            path.unlink()
            _fsync_dir(path.parent)
        now = _now_ms()
        with self._lock, sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("DELETE FROM work_documents WHERE document_id=?", (identifier,))
            receipt = self._receipt(conn, f"erase:{identifier}:{approval_id}", identifier, "erase", "applied", False, now)
        self.sessions.complete_approval(approval_id, state="applied", receipt=receipt)
        self._projections(root)
        return _validated(
            {"schemaVersion": "rag-ime.work-document-command.v1", "ok": True, "operation": "erase", "document": None, "receipt": receipt},
            "work-document-command.v1.json",
        )

    def context_discovery(self, *, limit: object = 100) -> WorkDocumentContextResponse:
        listing = self.list(limit=limit)
        return _validated(
            {"schemaVersion": "rag-ime.work-document-context.v1", "items": [{key: item[key] for key in ("documentId", "title", "path", "contentSha256", "authorityKey")} for item in listing["items"] if item["state"] == "active"]},
            "work-document-context.v1.json",
        )

    def observe_authority(
        self,
        authority_kind: str,
        authority_id: str,
        *,
        _reconcile: bool = True,
    ) -> None:
        authority_key = f"{authority_kind}:{authority_id}"
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            row = conn.execute(
                "SELECT document_id FROM work_documents WHERE authority_key=?",
                (authority_key,),
            ).fetchone()
            if row is None:
                return
            document_id = str(row[0])
        try:
            with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
                authority = self._authority(conn, authority_kind, authority_id)
            if authority["terminalState"] in {"completed", "cancelled", "failed", "cleared"}:
                self.request_archive(
                    document_id,
                    {"terminalReceiptId": authority["receiptId"]},
                    _reconcile=_reconcile,
                )
        except Exception as exc:
            self._record_observer_failure(
                authority_kind,
                authority_id,
                document_id,
                exc,
            )
            self._sync_context(document_id)
            raise
        else:
            now = _now_ms()
            with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
                conn.execute(
                    "UPDATE work_document_observer_failures "
                    "SET state='applied',error='',updated_at_ms=?,applied_at_ms=? "
                    "WHERE authority_key=?",
                    (now, now, authority_key),
                )

    def reconcile(
        self,
        document_id: str = "",
        *,
        observe_authorities: bool = True,
        retry_failed_observers: bool = False,
    ) -> dict[str, int]:
        with self._lock:
            observer_failed = 0
            if observe_authorities:
                observer_failed = self._reconcile_authorities(
                    document_id,
                    retry_failed=retry_failed_observers,
                )
            with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
                sql = (
                    "SELECT * FROM work_document_outbox "
                    "WHERE state IN ('pending','processing')"
                )
                params: tuple[object, ...] = ()
                if document_id:
                    sql += " AND document_id=?"
                    params = (document_id,)
                rows = conn.execute(
                    sql + " ORDER BY created_at_ms,outbox_id", params
                ).fetchall()
            applied = failed = 0
            roots: set[Path] = set()
            for outbox in rows:
                try:
                    roots.add(self._apply(outbox))
                    applied += 1
                except Exception as exc:
                    failed += 1
                    now = _now_ms()
                    error = _error(exc)
                    with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
                        conn.execute(
                            "UPDATE work_document_outbox "
                            "SET state='failed',error=?,updated_at_ms=? "
                            "WHERE outbox_id=?",
                            (error, now, outbox["outbox_id"]),
                        )
                        conn.execute(
                            "UPDATE work_documents "
                            "SET state='error',error=?,updated_at_ms=? "
                            "WHERE document_id=?",
                            (error, now, outbox["document_id"]),
                        )
                        conn.execute(
                            "UPDATE work_document_operation_receipts "
                            "SET status='failed' WHERE operation_key=?",
                            (outbox["operation_key"],),
                        )
                    self._sync_context(str(outbox["document_id"]))
            with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
                roots.update(
                    Path(str(row[0]))
                    for row in conn.execute(
                        "SELECT DISTINCT workspace_root FROM work_documents"
                    ).fetchall()
                )
            for root in roots:
                self._projections(root)
            return {"applied": applied, "failed": failed + observer_failed}

    def _record_observer_failure(
        self,
        authority_kind: str,
        authority_id: str,
        document_id: str,
        exc: BaseException,
    ) -> None:
        now = _now_ms()
        error = _error(exc)
        authority_key = f"{authority_kind}:{authority_id}"
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute(
                """
                INSERT INTO work_document_observer_failures(
                    authority_key,authority_kind,authority_id,document_id,state,
                    attempt_count,error,created_at_ms,updated_at_ms
                ) VALUES(?,?,?,?,'failed',1,?,?,?)
                ON CONFLICT(authority_key) DO UPDATE SET
                    document_id=excluded.document_id,
                    state='failed',
                    attempt_count=work_document_observer_failures.attempt_count+1,
                    error=excluded.error,
                    updated_at_ms=excluded.updated_at_ms,
                    applied_at_ms=0
                """,
                (
                    authority_key,
                    authority_kind,
                    authority_id,
                    document_id,
                    error,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE work_documents SET state='error',error=?,updated_at_ms=? "
                "WHERE document_id=? AND state IN ('active','reopen_pending')",
                (error, now, document_id),
            )

    def _reconcile_authorities(
        self,
        document_id: str,
        *,
        retry_failed: bool,
    ) -> int:
        states = ("pending", "failed") if retry_failed else ("pending",)
        placeholders = ",".join("?" for _ in states)
        parameters: list[object] = [*states]
        document_clause = ""
        if document_id:
            document_clause = " AND d.document_id=?"
            parameters.append(document_id)
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT d.authority_kind,d.authority_id,d.document_id
                FROM work_documents d
                LEFT JOIN work_document_observer_failures f
                  ON f.authority_key=d.authority_key
                WHERE (d.state='active' OR f.state IN ({placeholders}))
                {document_clause}
                ORDER BY d.created_at_ms,d.document_id
                """,
                tuple(parameters),
            ).fetchall()
        failed = 0
        for row in rows:
            try:
                self.observe_authority(
                    str(row["authority_kind"]),
                    str(row["authority_id"]),
                    _reconcile=False,
                )
            except Exception:
                failed += 1
        return failed

    def _sync_context(self, document_id: str) -> None:
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            row = self._row(conn, document_id)
            kind = str(row["authority_kind"])
            authority_id = str(row["authority_id"])
            if kind == "session_todo":
                session_id = authority_id
            elif kind == "session_goal":
                goal = conn.execute(
                    "SELECT session_id FROM agent_thread_goal_events "
                    "WHERE goal_id=? ORDER BY sequence DESC LIMIT 1",
                    (authority_id,),
                ).fetchone()
                session_id = str(goal[0]) if goal is not None else ""
            else:
                session_id = ""
            state = str(row["state"])
            source_kind = f"work_document:{document_id}"
            if not session_id:
                return
            if state != "active":
                conn.execute(
                    "UPDATE agent_context_items SET status='expired',updated_at_ms=? "
                    "WHERE session_id=? AND source_kind=? "
                    "AND status IN ('pending','delivered','consumed')",
                    (_now_ms(), session_id, source_kind),
                )
                return
            payload = _payload(row)
        self.context_runtime.replace_active(
            session_id=session_id,
            source_kind=source_kind,
            source_id=document_id,
            lane="fact",
            lifecycle="persistent",
            dedupe_key=(
                f"work-document:{document_id}:{payload['documentRevision']}:"
                f"{payload['contentSha256']}"
            ),
            title=str(payload["title"] or "Active work document"),
            summary=(
                f"Active authority-bound work document: {payload['path']} "
                f"(sha256 {payload['contentSha256']}). Archived history is excluded."
            ),
            payload={
                "documentId": document_id,
                "authorityKey": payload["authorityKey"],
                "path": payload["path"],
                "contentSha256": payload["contentSha256"],
            },
        )

    def _apply(self, outbox: sqlite3.Row) -> Path:
        now = _now_ms()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("UPDATE work_document_outbox SET state='processing',attempt_count=attempt_count+1,updated_at_ms=? WHERE outbox_id=?", (now, outbox["outbox_id"]))
            document = self._row(conn, str(outbox["document_id"]))
        root = Path(str(document["workspace_root"]))
        _move(_resolve(root, str(outbox["source_relative_path"])), _resolve(root, str(outbox["target_relative_path"])), str(document["content_sha256"]))
        state = "archived" if outbox["operation"] == "archive" else "active"
        now = _now_ms()
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            conn.execute("UPDATE work_documents SET relative_path=?,state=?,error='',updated_at_ms=? WHERE document_id=?", (outbox["target_relative_path"], state, now, outbox["document_id"]))
            conn.execute("UPDATE work_document_outbox SET state='applied',error='',updated_at_ms=?,applied_at_ms=? WHERE outbox_id=?", (now, now, outbox["outbox_id"]))
            conn.execute("UPDATE work_document_operation_receipts SET status='applied' WHERE operation_key=?", (outbox["operation_key"],))
        self._sync_context(str(outbox["document_id"]))
        return root

    def _projections(self, root: Path) -> None:
        root = root.resolve(strict=False)
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            rows = conn.execute("SELECT * FROM work_documents WHERE workspace_root=? ORDER BY updated_at_ms DESC,document_id", (str(root),)).fetchall()
        projection_root = _resolve(root, "docs/agent/work")
        projection_root.mkdir(parents=True, exist_ok=True)
        for name, archived in (("ACTIVE.json", False), ("ARCHIVE.json", True)):
            items = [_projection(row) for row in rows if (str(row["state"]) == "archived") == archived]
            _atomic_json(projection_root / name, {"schemaVersion": "rag-ime.work-document-index.v1", "scope": "archive" if archived else "active", "items": items})

    def _reopen_context(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> WorkDocumentReopenContext:
        stored_revision = int(row["authority_revision"])
        if str(row["state"]) != "archived":
            return {
                "eligible": False,
                "authorityRevision": stored_revision,
                "transitionReceiptId": "",
                "reasonCode": "document_not_archived",
            }
        try:
            authority = self._authority(
                conn,
                str(row["authority_kind"]),
                str(row["authority_id"]),
            )
        except WorkDocumentError:
            return {
                "eligible": False,
                "authorityRevision": stored_revision,
                "transitionReceiptId": "",
                "reasonCode": "authority_unavailable",
            }
        revision = int(authority["revision"])
        transition_receipt_id = str(authority["receiptId"])
        if bool(authority["terminal"]):
            return {
                "eligible": False,
                "authorityRevision": revision,
                "transitionReceiptId": transition_receipt_id,
                "reasonCode": "authority_terminal",
            }
        if revision <= stored_revision:
            return {
                "eligible": False,
                "authorityRevision": revision,
                "transitionReceiptId": transition_receipt_id,
                "reasonCode": "authority_not_advanced",
            }
        return {
            "eligible": True,
            "authorityRevision": revision,
            "transitionReceiptId": transition_receipt_id,
            "reasonCode": "ready",
        }


    def _authority(self, conn: sqlite3.Connection, kind: str, authority_id: str) -> dict[str, object]:
        if kind == "session_todo":
            row = conn.execute(
                """
                SELECT event_id, revision, operation, phases_json
                FROM agent_todo_events
                WHERE session_id = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (authority_id,),
            ).fetchone()
            if row is None:
                raise WorkDocumentError("session Todo authority was not found")
            revision = int(row["revision"])
            try:
                phases = json.loads(str(row["phases_json"]))
            except (TypeError, ValueError) as error:
                raise WorkDocumentError("session Todo authority is invalid") from error
            task_statuses = [
                str(task.get("status") or "")
                for phase in phases if isinstance(phase, Mapping)
                for task in (
                    phase.get("tasks")
                    if isinstance(phase.get("tasks"), list)
                    else []
                )
                if isinstance(task, Mapping)
            ] if isinstance(phases, list) else []
            operation = str(row["operation"])
            if operation == "rm":
                status = "cleared"
                terminal_state = "cleared"
            elif task_statuses and not any(
                item in {"pending", "in_progress"}
                for item in task_statuses
            ):
                status = (
                    "cancelled"
                    if all(item == "abandoned" for item in task_statuses)
                    else "completed"
                )
                terminal_state = status
            else:
                status = "active"
                terminal_state = ""
        elif kind == "session_goal":
            row = conn.execute("SELECT event_id,sequence,status FROM agent_thread_goal_events WHERE goal_id=? ORDER BY sequence DESC LIMIT 1", (authority_id,)).fetchone()
            if row is None:
                raise WorkDocumentError("session goal authority was not found")
            status = str(row["status"])
            revision = int(row["sequence"])
            terminal_state = status if status in {"completed", "cancelled", "cleared"} else ""
        elif kind == "room_work_item":
            work = conn.execute("SELECT state FROM agent_room_work_items WHERE id=?", (authority_id,)).fetchone()
            row = conn.execute("SELECT event_id,sequence,event_type FROM agent_room_work_events WHERE work_id=? ORDER BY sequence DESC LIMIT 1", (authority_id,)).fetchone()
            if work is None or row is None:
                raise WorkDocumentError("Room work-item authority was not found")
            status = str(work["state"])
            revision = int(row["sequence"])
            terminal_state = "completed" if status == "done" else status if status in {"failed", "cancelled"} else ""
        else:
            raise WorkDocumentError("unsupported work-document authority kind")
        terminal = bool(terminal_state) or status in {"cleared", "failed"}
        return {"revision": revision, "state": status, "terminal": terminal, "terminalState": terminal_state, "receiptId": str(row["event_id"])}

    @staticmethod
    def _enqueue(conn: sqlite3.Connection, key: str, document_id: str, operation: str, source: str, target: str, now: int) -> None:
        conn.execute("INSERT OR IGNORE INTO work_document_outbox(outbox_id,operation_key,document_id,operation,source_relative_path,target_relative_path,state,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?,'pending',?,?)", (f"workdoc-outbox:{hashlib.sha256(key.encode()).hexdigest()[:32]}", key, document_id, operation, source, target, now, now))

    @staticmethod
    def _receipt(conn: sqlite3.Connection, key: str, document_id: str, operation: str, status: str, idempotent: bool, now: int) -> dict[str, object]:
        receipt_id = f"workdoc-receipt:{hashlib.sha256(key.encode()).hexdigest()[:32]}"
        conn.execute("INSERT OR IGNORE INTO work_document_operation_receipts(receipt_id,operation_key,document_id,operation,status,idempotent,created_at_ms) VALUES(?,?,?,?,?,?,?)", (receipt_id, key, document_id, operation, status, int(idempotent), now))
        row = conn.execute("SELECT * FROM work_document_operation_receipts WHERE operation_key=?", (key,)).fetchone()
        if (
            row is None
            or str(row["receipt_id"]) != receipt_id
            or str(row["document_id"]) != document_id
            or str(row["operation"]) != operation
        ):
            raise WorkDocumentError(
                "work-document idempotency key conflicts with another operation"
            )
        return {"receiptId": str(row["receipt_id"]), "operation": str(row["operation"]), "status": str(row["status"]), "idempotent": bool(idempotent or row["idempotent"]), "createdAtMs": int(row["created_at_ms"])}

    @staticmethod
    def _row(conn: sqlite3.Connection, document_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM work_documents WHERE document_id=?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        return row

    def _get(self, document_id: str) -> dict[str, object]:
        with sqlite_connection(self.db_path, row_factory=sqlite3.Row, foreign_keys=True) as conn:
            return _payload(self._row(conn, document_id))


def _command(
    operation: str,
    document: Mapping[str, object],
    receipt: Mapping[str, object],
) -> WorkDocumentCommandResponse:
    return _validated(
        {"schemaVersion": "rag-ime.work-document-command.v1", "ok": True, "operation": operation, "document": dict(document), "receipt": dict(receipt)},
        "work-document-command.v1.json",
    )


def _validated(payload: Any, contract: str) -> Any:
    validate_contract(payload, contract)
    return payload


def _payload(row: sqlite3.Row) -> WorkDocumentPayload:
    return {"documentId": str(row["document_id"]), "authorityKind": str(row["authority_kind"]), "authorityId": str(row["authority_id"]), "authorityRevision": int(row["authority_revision"]), "authorityKey": str(row["authority_key"]), "documentRevision": int(row["document_revision"]), "contentSha256": str(row["content_sha256"]), "workspaceRoot": str(row["workspace_root"]), "path": str(row["relative_path"]), "activePath": str(row["active_relative_path"]), "archivePath": str(row["archive_relative_path"]), "state": str(row["state"]), "title": str(row["title"]), "terminalReceiptId": str(row["terminal_receipt_id"]), "error": str(row["error"]), "createdAtMs": int(row["created_at_ms"]), "updatedAtMs": int(row["updated_at_ms"])}


def _room_delta_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "deltaId": str(row["delta_id"]),
        "documentId": str(row["document_id"]),
        "rootId": str(row["root_id"]),
        "sequence": int(row["sequence"]),
        "deltaKind": str(row["delta_kind"]),
        "sourceRef": str(row["source_ref"]),
        "contentSha256": str(row["content_sha256"]),
        "createdAtMs": int(row["created_at_ms"]),
        "materializedAtMs": (
            int(row["materialized_at_ms"])
            if row["materialized_at_ms"] is not None
            else None
        ),
    }


def _append_room_document_delta(
    document: str,
    *,
    marker: str,
    delta_kind: str,
    source_ref: str,
    content: str,
) -> str:
    section_by_kind = {
        "user_correction": "后续用户修正",
        "progress": "当前进度",
        "evidence": "证据",
        "failure_recovery": "失败与恢复",
        "handoff": "交接",
        "next_action": "下一步",
        "plan_revision": "已批准执行计划",
    }
    section = section_by_kind[delta_kind]
    heading = f"## {section}"
    longest_backtick_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", content)),
        default=0,
    )
    fence = "`" * max(3, longest_backtick_run + 1)
    block = (
        f"{marker}\n"
        f"### {source_ref}\n\n"
        f"{fence}text\n{content}\n{fence}\n"
    )
    normalized = document if document.endswith("\n") else document + "\n"
    if heading not in normalized:
        return f"{normalized}\n{heading}\n\n{block}"
    # Append-only materialization keeps exact user bytes and a deterministic
    # source marker. Section summaries can later be regenerated from these
    # governed deltas without rewriting the immutable correction chain.
    return f"{normalized}\n{block}"


def _projection(row: sqlite3.Row) -> dict[str, object]:
    item = _payload(row)
    return {key: item[key] for key in ("documentId", "authorityKey", "authorityRevision", "documentRevision", "contentSha256", "path", "state", "title", "updatedAtMs")}


def _source(root_value: object, path_value: object) -> tuple[Path, str, Path]:
    root = Path(_required(root_value, "workspaceRoot", 2000)).expanduser().resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise WorkDocumentError("workspaceRoot must be a real directory")
    relative = _relative(_required(path_value, "sourcePath", 1000))
    if not relative.startswith("docs/") or not relative.endswith(".md"):
        raise WorkDocumentError("work documents must be Markdown files below docs/")
    if relative.startswith("docs/agent/work/archive/"):
        raise WorkDocumentError("archived paths require explicit reopen")
    source = _resolve(root, relative)
    if source.is_symlink() or not source.is_file():
        raise WorkDocumentError("sourcePath must name a regular non-symlink file")
    return root, relative, source


def _relative(value: str) -> str:
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise WorkDocumentError("work-document paths must be normalized workspace-relative paths")
    if any(part.lower() in _SENSITIVE or part.lower().startswith(".env") for part in pure.parts):
        raise WorkDocumentError("sensitive paths cannot be governed as work documents")
    return pure.as_posix()


def _resolve(root: Path, relative: str) -> Path:
    candidate = (root / _relative(relative)).resolve(strict=False)
    try:
        candidate.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise WorkDocumentError("work-document path escapes workspace root") from exc
    return candidate


def _move(source: Path, target: Path, expected: str) -> None:
    source_exists, target_exists = source.exists(), target.exists()
    if source == target:
        if not source_exists or source.is_symlink() or _sha256_file(source) != expected:
            raise WorkDocumentError("canonical document content does not match its registered hash")
        return
    if (source_exists and source.is_symlink()) or (target_exists and target.is_symlink()):
        raise WorkDocumentError("work-document moves never follow symlinks")
    if target_exists:
        if not target.is_file() or _sha256_file(target) != expected:
            raise WorkDocumentError("move target exists with different content")
        if source_exists:
            if not source.is_file() or _sha256_file(source) != expected:
                raise WorkDocumentError("move source changed during reconciliation")
            source.unlink()
            _fsync_dir(source.parent)
        return
    if not source_exists or not source.is_file() or _sha256_file(source) != expected:
        raise WorkDocumentError("move source is missing or changed")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    _fsync_dir(source.parent)
    _fsync_dir(target.parent)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _atomic_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(131072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded_utf8_snapshot(
    path: Path,
    *,
    expected_sha256: str,
    maximum_bytes: int = 65_536,
) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise WorkDocumentError(
            "canonical Room WorkDocument is unavailable"
        )
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise WorkDocumentError(
            "canonical Room WorkDocument changed during context projection"
        )
    included = data[:maximum_bytes]
    while included:
        try:
            content = included.decode("utf-8")
            break
        except UnicodeDecodeError as exc:
            included = included[: exc.start]
    else:
        content = ""
    return {
        "content": content,
        "contentSha256": digest,
        "byteCount": len(data),
        "includedByteCount": len(included),
        "truncated": len(included) < len(data),
        "maximumBytes": maximum_bytes,
        "readOnly": True,
    }


def _json_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _register_operation_key(
    document_id: str,
    *,
    authority_revision: int,
    content_sha256: str,
    title: str,
) -> str:
    semantic_hash = _json_hash(
        {
            "documentId": document_id,
            "authorityRevision": authority_revision,
            "contentSha256": content_sha256,
            "title": title,
        }
    )
    return f"register:{document_id}:{semantic_hash}"


def _document_id(authority_key: str) -> str:
    return f"workdoc_{hashlib.sha256(authority_key.encode()).hexdigest()[:32]}"


def _identifier(value: object) -> str:
    identifier = _text(value, 80)
    if len(identifier) != 40 or not identifier.startswith("workdoc_"):
        raise WorkDocumentError("invalid work-document id")
    return identifier


def _required(value: object, field: str, maximum: int) -> str:
    normalized = _text(value, maximum + 1)
    if not normalized or len(normalized) > maximum:
        raise WorkDocumentError(f"{field} is required")
    return normalized


def _text(value: object, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _integer(value: object, field: str) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise WorkDocumentError(f"{field} must be an integer") from exc
    if parsed < 0:
        raise WorkDocumentError(f"{field} is out of range")
    return parsed


def _limit(value: object) -> int:
    try:
        return max(1, min(int(value), 200))
    except (TypeError, ValueError):
        return 100


def _now_ms() -> int:
    return int(time.time() * 1000)


def _error(exc: BaseException) -> str:
    return " ".join(f"{type(exc).__name__}: {exc}".split())[:500]
