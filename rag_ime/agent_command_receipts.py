from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .db import apply_database_migrations


class AgentCommandReceiptConflict(ValueError):
    http_status = 409


class AgentCommandReceiptPending(ValueError):
    http_status = 409


class AgentCommandReceiptFailed(ValueError):
    http_status = 409


@dataclass(frozen=True)
class AgentCommandClaim:
    claim_token: str
    replay_response: dict[str, object] | None = None

    @property
    def is_replay(self) -> bool:
        return self.replay_response is not None


class AgentCommandReceiptStore:
    """Durable idempotency boundary for commands that start Agent turns."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            apply_database_migrations(conn)

    def begin(
        self,
        *,
        command_scope: str,
        scope_id: str,
        client_message_id: str,
        payload: Mapping[str, object],
    ) -> AgentCommandClaim:
        digest = _sha256_json(payload)
        claim_token = str(uuid.uuid4())
        timestamp = _now_ms()
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_command_receipts
                WHERE command_scope = ? AND scope_id = ? AND client_message_id = ?
                """,
                (command_scope, scope_id, client_message_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO agent_command_receipts(
                        command_scope, scope_id, client_message_id, payload_sha256,
                        claim_token, state, response_json, error, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, '', ?, ?)
                    """,
                    (
                        command_scope,
                        scope_id,
                        client_message_id,
                        digest,
                        claim_token,
                        timestamp,
                        timestamp,
                    ),
                )
                return AgentCommandClaim(claim_token=claim_token)

            if str(row["payload_sha256"]) != digest:
                raise AgentCommandReceiptConflict(
                    "clientMessageId was already used for a different command payload"
                )
            state = str(row["state"])
            if state == "accepted":
                response = json.loads(str(row["response_json"] or "{}"))
                if not isinstance(response, dict):
                    raise RuntimeError("stored Agent command response is invalid")
                return AgentCommandClaim(
                    claim_token=str(row["claim_token"]),
                    replay_response=dict(response),
                )
            if state == "failed":
                raise AgentCommandReceiptFailed(
                    str(row["error"] or "the original Agent command failed")
                )
            raise AgentCommandReceiptPending(
                "the Agent command is already pending; refresh the session snapshot before retrying"
            )

    def complete(
        self,
        claim: AgentCommandClaim,
        *,
        command_scope: str,
        scope_id: str,
        client_message_id: str,
        response: Mapping[str, object],
    ) -> dict[str, object]:
        payload = dict(response)
        encoded = _json(payload)
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE agent_command_receipts
                SET state = 'accepted', response_json = ?, error = '', updated_at_ms = ?
                WHERE command_scope = ? AND scope_id = ? AND client_message_id = ?
                  AND claim_token = ? AND state = 'pending'
                """,
                (
                    encoded,
                    _now_ms(),
                    command_scope,
                    scope_id,
                    client_message_id,
                    claim.claim_token,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Agent command receipt changed before completion")
        return payload

    def fail(
        self,
        claim: AgentCommandClaim,
        *,
        command_scope: str,
        scope_id: str,
        client_message_id: str,
        error: BaseException,
    ) -> None:
        message = " ".join(str(error).split())[:240] or error.__class__.__name__
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE agent_command_receipts
                SET state = 'failed', response_json = NULL, error = ?, updated_at_ms = ?
                WHERE command_scope = ? AND scope_id = ? AND client_message_id = ?
                  AND claim_token = ? AND state = 'pending'
                """,
                (
                    message,
                    _now_ms(),
                    command_scope,
                    scope_id,
                    client_message_id,
                    claim.claim_token,
                ),
            )

    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _sha256_json(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_json(dict(payload)).encode("utf-8")).hexdigest()


def _json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _now_ms() -> int:
    return int(time.time() * 1000)
