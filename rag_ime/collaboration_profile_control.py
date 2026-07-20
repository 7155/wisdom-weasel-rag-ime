from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence

from .collaboration_profile_store import CollaborationProfileStore
from .contracts.json_schema import validate_contract


_ROUTE_DESCRIPTOR = {
    "projection": {
        "method": "GET",
        "path": "/api/agent/collaboration-profiles/{profileId}",
        "scopes": ["agent.read"],
    },
    "command": {
        "method": "POST",
        "path": "/api/agent/collaboration-profiles/commands",
        "scopes": ["agent.write", "agent.approve"],
    },
}
COLLABORATION_PROFILE_ROUTE_HASH = "sha256:" + hashlib.sha256(
    json.dumps(_ROUTE_DESCRIPTOR, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

_ADMIN_CONFIRMATIONS = {
    "activate": "ACTIVATE PROFILE",
    "rollback": "ROLLBACK PROFILE",
    "revoke": "REVOKE PROFILE",
}


class CollaborationProfileControl:
    """Single typed command path for declarative CollaborationProfile changes."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        trusted_signers: Mapping[str, bytes],
        baseline_capabilities: Sequence[str],
        binding_revision: str,
        cancel_root: Callable[[str, int], Mapping[str, object]] | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.conn = conn
        self.store = CollaborationProfileStore(
            conn,
            trusted_signers=trusted_signers,
            clock=clock,
        )
        self._baseline_capabilities = tuple(str(value) for value in baseline_capabilities)
        self._binding_revision = str(binding_revision).strip()
        if not self._binding_revision:
            raise ValueError("profile control binding revision is required")
        self._cancel_root = cancel_root

    def execute(self, command: Mapping[str, object]) -> dict[str, object]:
        payload = dict(command)
        validate_contract(payload, "collaboration-profile-command.v1.json")
        command_hash = _hash(payload)
        existing = self.conn.execute(
            "SELECT command_hash, payload_json FROM collaboration_profile_command_receipts WHERE idempotency_key = ?",
            (payload["idempotencyKey"],),
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != command_hash:
                raise ValueError("profile command idempotency key was reused with different content")
            return _json_object(existing[1])

        action = str(payload["action"])
        profile_id = _optional_text(payload.get("profileId"))
        candidate_id = _optional_text(payload.get("candidateId"))
        content_hash = _optional_text(payload.get("contentHash"))
        body = payload.get("payload")
        if not isinstance(body, Mapping):
            raise ValueError("profile command payload must be an object")

        if action == "inspect":
            bundle = body.get("bundle")
            if not isinstance(bundle, Mapping):
                raise ValueError("inspect requires payload.bundle")
            result = self.store.inspect(bundle)
            profile_id = str(result["profileId"])
        elif action == "validate":
            result = self.store.validate(_required(candidate_id, "candidateId"))
            profile_id = str(result["profileId"])
        elif action == "compile":
            result = self.store.compile(
                _required(candidate_id, "candidateId"),
                baseline_capabilities=self._baseline_capabilities,
                binding_revision=self._binding_revision,
            )
            profile_id = self._candidate_profile_id(_required(candidate_id, "candidateId"))
        elif action == "dry_run":
            result = self.store.dry_run(_required(candidate_id, "candidateId"))
            profile_id = str(result["profileId"])
        elif action == "stage":
            result = self.store.stage(_required(candidate_id, "candidateId"))
            profile_id = str(result["profileId"])
        elif action == "activate":
            self._require_admin_confirmation(payload, action)
            result = self._pointer_command(
                payload,
                action=action,
                profile_id=_required(profile_id, "profileId"),
                content_hash=_required(content_hash, "contentHash"),
                command_hash=command_hash,
            )
            return result
        elif action == "rollback":
            self._require_admin_confirmation(payload, action)
            result = self._pointer_command(
                payload,
                action=action,
                profile_id=_required(profile_id, "profileId"),
                command_hash=command_hash,
            )
            return result
        elif action == "revoke":
            self._require_admin_confirmation(payload, action)
            result = self._pointer_command(
                payload,
                action=action,
                profile_id=profile_id,
                content_hash=_required(content_hash, "contentHash"),
                command_hash=command_hash,
            )
            return result
        else:  # pragma: no cover - schema owns the enum
            raise ValueError("unsupported profile command action")

        receipt = self._receipt(
            command=payload,
            command_hash=command_hash,
            profile_id=profile_id,
            result=dict(result),
            guard_epoch=self.store.guard_epoch(profile_id) if profile_id else 0,
        )
        with self.conn:
            self._insert_receipt(payload, command_hash, receipt)
        return receipt

    def _candidate_profile_id(self, candidate_id: str) -> str:
        row = self.conn.execute(
            "SELECT profile_id FROM collaboration_profile_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("profile candidate disappeared during command execution")
        return str(row[0])

    def projection(self, profile_id: object, *, receipt_limit: int = 20) -> dict[str, object]:
        normalized = _required(_optional_text(profile_id), "profileId")
        rows = self.conn.execute(
            """SELECT payload_json FROM collaboration_profile_command_receipts
               WHERE profile_id = ? ORDER BY created_at_ms DESC, receipt_id DESC LIMIT ?""",
            (normalized, max(1, min(int(receipt_limit), 50))),
        ).fetchall()
        result = {
            "schemaVersion": "rag-ime.collaboration-profile-projection.v1",
            "profileId": normalized,
            "routeHash": COLLABORATION_PROFILE_ROUTE_HASH,
            "requiredReadScopes": ["agent.read"],
            "requiredWriteScopes": ["agent.write", "agent.approve"],
            "guardEpoch": self.store.guard_epoch(normalized),
            "normalAgentFallback": True,
            "inspection": self.store.inspect_profile(normalized),
            "recentReceipts": [_json_object(row[0]) for row in rows],
        }
        validate_contract(result, "collaboration-profile-projection.v1.json")
        return result

    def _pointer_command(
        self,
        command: dict[str, object],
        *,
        action: str,
        profile_id: str | None,
        command_hash: str,
        content_hash: str = "",
    ) -> dict[str, object]:
        expected = command.get("expectedPointerRevision")
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ValueError(f"{action} requires expectedPointerRevision")
        receipt_box: list[dict[str, object]] = []

        def persist(result: dict[str, object]) -> None:
            resolved_profile = str(result.get("profileId") or profile_id or "") or None
            receipt = self._receipt(
                command=command,
                command_hash=command_hash,
                profile_id=resolved_profile,
                result=result,
                guard_epoch=int(result.get("guardEpoch") or 0),
            )
            self._insert_receipt(command, command_hash, receipt)
            if action in {"rollback", "revoke"}:
                source_kind = "profile_rollback" if action == "rollback" else "profile_revoke"
                for root_id in result.get("affectedRootIds", []):
                    self.conn.execute(
                        """INSERT OR IGNORE INTO room_v2_managed_cancel_outbox(
                           cancel_id,source_kind,source_receipt_id,root_id,state,
                           created_at_ms,updated_at_ms)
                           VALUES (?,?,?,?, 'pending',?,?)""",
                        (
                            f"profile-cancel:{receipt['receiptId']}:{root_id}", source_kind,
                            receipt["receiptId"], str(root_id), int(command["createdAtMs"]),
                            int(command["createdAtMs"]),
                        ),
                    )
            receipt_box.append(receipt)

        if action == "activate":
            self.store.activate(
                profile_id=profile_id,
                content_hash=content_hash,
                expected_pointer_revision=expected,
                activation_scope=str(command.get("activationScope") or "immediate"),
                receipt_callback=persist,
            )
        elif action == "rollback":
            self.store.rollback(
                profile_id=profile_id,
                expected_pointer_revision=expected,
                receipt_callback=persist,
            )
        else:
            reason = command["payload"].get("reason")  # type: ignore[union-attr]
            self.store.revoke(
                content_hash=content_hash,
                reason=reason,
                expected_pointer_revision=expected,
                receipt_callback=persist,
            )
        receipt = receipt_box[0]
        return receipt

    @staticmethod
    def _require_admin_confirmation(command: Mapping[str, object], action: str) -> None:
        expected = _ADMIN_CONFIRMATIONS[action]
        if command.get("adminConfirmation") != expected:
            raise PermissionError(f"{action} requires adminConfirmation={expected}")

    def _receipt(
        self,
        *,
        command: Mapping[str, object],
        command_hash: str,
        profile_id: str | None,
        result: dict[str, object],
        guard_epoch: int,
    ) -> dict[str, object]:
        receipt_id = f"profile-command-receipt:{hashlib.sha256((str(command['commandId']) + command_hash).encode()).hexdigest()[:24]}"
        receipt = {
            "schemaVersion": "rag-ime.collaboration-profile-command-receipt.v1",
            "receiptId": receipt_id,
            "commandId": str(command["commandId"]),
            "commandHash": command_hash,
            "action": str(command["action"]),
            "status": "applied",
            "profileId": profile_id,
            "routeHash": COLLABORATION_PROFILE_ROUTE_HASH,
            "guardEpoch": int(guard_epoch),
            "result": result,
            "createdAtMs": int(command["createdAtMs"]),
        }
        validate_contract(receipt, "collaboration-profile-command-receipt.v1.json")
        return receipt

    def _insert_receipt(
        self,
        command: Mapping[str, object],
        command_hash: str,
        receipt: Mapping[str, object],
    ) -> None:
        self.conn.execute(
            """INSERT INTO collaboration_profile_command_receipts(
               receipt_id, command_id, idempotency_key, command_hash, action,
               profile_id, route_hash, guard_epoch, payload_json, created_at_ms
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                receipt["receiptId"], command["commandId"], command["idempotencyKey"],
                command_hash, command["action"], receipt["profileId"],
                COLLABORATION_PROFILE_ROUTE_HASH, receipt["guardEpoch"],
                json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                command["createdAtMs"],
            ),
        )


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _json_object(value: object) -> dict[str, object]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise RuntimeError("stored profile command receipt is not an object")
    return parsed


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("profile command text field is invalid")
    return value.strip()


def _required(value: str | None, field: str) -> str:
    if not value:
        raise ValueError(f"{field} is required")
    return value
