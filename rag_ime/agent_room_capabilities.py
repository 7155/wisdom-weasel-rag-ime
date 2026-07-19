from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


ROOM_PUBLIC_TOOLS = ("room_state", "room_post", "room_commit")
LEGACY_ROOM_TOOL_ALIASES = {
    "send": "room_post",
    "ask": "room_post",
    "reply": "room_post",
    "assign": "room_commit",
    "submit": "room_commit",
    "room_send": "room_post",
    "room_ask": "room_post",
    "room_reply": "room_post",
    "room_assign": "room_commit",
    "room_submit": "room_commit",
}
_SURFACES = frozenset({"prompt", "runtime", "gateway", "ui"})


class CapabilityManifestConflict(RuntimeError):
    """A manifest, receipt, binding, or consumer surface has drifted."""


class ToolAuthorizationError(PermissionError):
    """Disclosure exists, but current authorization does not permit invocation."""


class RoomCapabilityManifestStore:
    """Shadow-only Room tool catalog, disclosure, and invocation authorization.

    This component never executes a tool. An invocation receipt is an
    authorization handoff for the future single gateway path, not a second
    dispatcher or transport.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            return apply_database_migrations(conn).current_version

    def compile_manifest(
        self,
        *,
        manifest_id: str,
        room_binding: Mapping[str, object] | None,
        participant_binding: Mapping[str, object] | None,
        dispatch_id: str,
        runtime_registry: Mapping[str, Mapping[str, object]],
        user_authorized: Sequence[str],
        template_allowed: Sequence[str],
        role_allowed: Sequence[str],
        profile_allowed: Sequence[str],
        state_allowed: Sequence[str],
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool] | None:
        if room_binding is None and participant_binding is None:
            return None
        if room_binding is None or participant_binding is None:
            raise CapabilityManifestConflict("Room capability binding handshake is incomplete")
        identity = _binding_identity(room_binding, participant_binding, dispatch_id)
        gates = {
            "userAuthorization": set(_names(user_authorized)),
            "agentTemplate": set(_names(template_allowed)),
            "collaborationRoleProfile": set(_names(role_allowed)) & set(_names(profile_allowed)),
            "rootTaskState": set(_names(state_allowed)),
        }
        if room_binding.get("access") == "read":
            gates["rootTaskState"] &= {"room_state"}
        tools: list[dict[str, object]] = []
        for name in ROOM_PUBLIC_TOOLS:
            source = runtime_registry.get(name)
            if not isinstance(source, Mapping):
                continue
            schema = source.get("inputSchema")
            if not isinstance(schema, Mapping):
                raise ValueError(f"runtime tool {name} requires inputSchema")
            denied_by = [gate for gate, allowed in gates.items() if name not in allowed]
            tools.append(
                {
                    "name": name,
                    "description": _required(source.get("description"), f"{name}.description"),
                    "risk": _required(source.get("risk") or "controlled", f"{name}.risk"),
                    "operation": _required(source.get("operation") or name, f"{name}.operation"),
                    "schemaHash": _hash_json(dict(schema)),
                    "available": True,
                    "authorized": not denied_by,
                    "deniedBy": denied_by,
                }
            )
        material = {**identity, "tools": tools}
        manifest = {
            "schemaVersion": "wisdom-weasel.room-capability-manifest.v1",
            "manifestId": _required(manifest_id, "manifest_id"),
            **material,
            "manifestHash": _hash_json(material),
            "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
        }
        validate_contract(manifest, "room-capability-manifest.v1.json")
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM room_v2_capability_manifests WHERE manifest_id = ?",
                (manifest["manifestId"],),
            ).fetchone()
            if existing is not None:
                payload = _manifest_payload(existing)
                if payload != manifest:
                    raise CapabilityManifestConflict("Capability Manifest identity changed")
                return payload, False
            conn.execute(
                """
                INSERT INTO room_v2_capability_manifests(
                    manifest_id, binding_id, room_id, root_id, task_id, dispatch_id,
                    generation, capability_revision, capability_epoch, manifest_hash,
                    payload_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest["manifestId"], manifest["bindingId"], manifest["roomId"],
                    manifest["rootId"], manifest["taskId"], manifest["dispatchId"],
                    manifest["generation"], manifest["capabilityRevision"],
                    manifest["capabilityEpoch"], manifest["manifestHash"],
                    _json(manifest), manifest["createdAtMs"],
                ),
            )
        return manifest, True

    def tool_search(
        self,
        *,
        receipt_id: str,
        manifest_id: str,
        manifest_hash: str,
        query: str,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        manifest = self._manifest(manifest_id, manifest_hash)
        needle = str(query or "").strip().casefold()
        items = [
            {
                "name": tool["name"], "description": tool["description"],
                "risk": tool["risk"], "schemaHash": tool["schemaHash"],
                "available": tool["available"], "authorized": tool["authorized"],
            }
            for tool in manifest["tools"]
            if not needle
            or needle in str(tool["name"]).casefold()
            or needle in str(tool["description"]).casefold()
        ]
        # Search deliberately never discloses inputSchema.
        return self._record_disclosure(
            receipt_id=receipt_id,
            manifest=manifest,
            kind="search",
            query=str(query or "").strip(),
            tool_name="",
            schema_hash="",
            items=items,
            created_at_ms=created_at_ms,
        )

    def tool_load(
        self,
        *,
        receipt_id: str,
        manifest_id: str,
        manifest_hash: str,
        tool_name: str,
        runtime_registry: Mapping[str, Mapping[str, object]],
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        manifest = self._manifest(manifest_id, manifest_hash)
        canonical = _canonical_tool(tool_name)
        tool = _manifest_tool(manifest, canonical)
        source = runtime_registry.get(canonical)
        if not isinstance(source, Mapping) or not isinstance(source.get("inputSchema"), Mapping):
            raise CapabilityManifestConflict("runtime registry no longer provides disclosed tool")
        schema = dict(source["inputSchema"])
        if _hash_json(schema) != tool["schemaHash"]:
            raise CapabilityManifestConflict("runtime tool schema hash differs from manifest")
        return self._record_disclosure(
            receipt_id=receipt_id,
            manifest=manifest,
            kind="load",
            query="",
            tool_name=canonical,
            schema_hash=str(tool["schemaHash"]),
            items=[
                {
                    "name": canonical, "description": tool["description"],
                    "risk": tool["risk"], "authorized": tool["authorized"],
                    "inputSchema": schema,
                }
            ],
            created_at_ms=created_at_ms,
        )

    def authorize_invocation(
        self,
        *,
        receipt_id: str,
        invocation_key: str,
        manifest_id: str,
        manifest_hash: str,
        load_receipt_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
        room_binding: Mapping[str, object],
        participant_binding: Mapping[str, object],
        dispatch_id: str,
        surface_manifest_hashes: Mapping[str, str],
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        manifest = self._manifest(manifest_id, manifest_hash)
        current = _binding_identity(room_binding, participant_binding, dispatch_id)
        _assert_manifest_context(manifest, current)
        self.assert_surface_manifest_hashes(manifest_hash, surface_manifest_hashes)
        canonical = _canonical_tool(tool_name)
        tool = _manifest_tool(manifest, canonical)
        if not bool(tool["authorized"]):
            raise ToolAuthorizationError(
                f"{canonical} is disclosed but not authorized: {','.join(tool['deniedBy'])}"
            )
        load = self._disclosure(load_receipt_id)
        if (
            load["kind"] != "load"
            or load["manifestId"] != manifest_id
            or load["manifestHash"] != manifest_hash
            or load["toolName"] != canonical
            or load["schemaHash"] != tool["schemaHash"]
        ):
            raise CapabilityManifestConflict("tool load receipt is stale or belongs to another manifest")
        loaded_items = load.get("items") or []
        loaded_schema = (
            loaded_items[0].get("inputSchema")
            if len(loaded_items) == 1 and isinstance(loaded_items[0], Mapping)
            else None
        )
        if not isinstance(loaded_schema, Mapping):
            raise CapabilityManifestConflict("tool load receipt has no exact input schema")
        validate_contract(dict(arguments), loaded_schema)
        normalized = normalize_room_tool_command(tool_name, arguments)
        command_material = {
            "tool": normalized["canonicalTool"],
            "arguments": normalized["arguments"],
            "rootId": manifest["rootId"], "taskId": manifest["taskId"],
            "dispatchId": manifest["dispatchId"], "generation": manifest["generation"],
            "capabilityEpoch": manifest["capabilityEpoch"],
        }
        command_hash = _hash_json(command_material)
        key = _required(invocation_key, "invocation_key")
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM room_v2_tool_invocation_receipts
                WHERE receipt_id = ? OR (manifest_id = ? AND invocation_key = ?)
                """,
                (_required(receipt_id, "receipt_id"), manifest_id, key),
            ).fetchall()
            if len(existing) > 1:
                raise CapabilityManifestConflict("invocation identifiers resolve to different receipts")
            if existing:
                payload = _invocation_payload(existing[0])
                if (
                    payload["manifestHash"] != manifest_hash
                    or payload["canonicalCommand"].get("commandHash") != command_hash
                ):
                    raise CapabilityManifestConflict("invocation key was reused for another command")
                return payload, False
            command = {**command_material, "commandHash": command_hash}
            payload = {
                "schemaVersion": "wisdom-weasel.room-tool-invocation-receipt.v1",
                "receiptId": _required(receipt_id, "receipt_id"),
                "manifestId": manifest_id, "manifestHash": manifest_hash,
                "loadReceiptId": load_receipt_id, "invocationKey": key,
                "canonicalCommand": command, "authorizationState": "authorized",
                "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
            }
            validate_contract(payload, "room-tool-invocation-receipt.v1.json")
            conn.execute(
                """
                INSERT INTO room_v2_tool_invocation_receipts(
                    receipt_id, manifest_id, manifest_hash, load_receipt_id,
                    invocation_key, canonical_tool_name, original_tool_name,
                    command_hash, command_json, authorization_state, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'authorized', ?)
                """,
                (
                    payload["receiptId"], manifest_id, manifest_hash, load_receipt_id,
                    key, canonical, str(tool_name).strip(), command_hash,
                    _json(command), payload["createdAtMs"],
                ),
            )
        return payload, True

    @staticmethod
    def assert_surface_manifest_hashes(
        manifest_hash: str,
        surface_hashes: Mapping[str, str],
    ) -> None:
        if set(surface_hashes) != _SURFACES:
            raise CapabilityManifestConflict("all Prompt/Runtime/Gateway/UI manifest hashes are required")
        mismatched = [name for name, value in surface_hashes.items() if value != manifest_hash]
        if mismatched:
            raise CapabilityManifestConflict(
                "Capability Manifest hash mismatch: " + ",".join(sorted(mismatched))
            )

    def _record_disclosure(
        self,
        *,
        receipt_id: str,
        manifest: Mapping[str, object],
        kind: str,
        query: str,
        tool_name: str,
        schema_hash: str,
        items: list[dict[str, object]],
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        payload = {
            "schemaVersion": "wisdom-weasel.room-tool-disclosure-receipt.v1",
            "receiptId": _required(receipt_id, "receipt_id"),
            "manifestId": manifest["manifestId"], "manifestHash": manifest["manifestHash"],
            "kind": kind, "query": query, "toolName": tool_name,
            "schemaHash": schema_hash, "items": items,
            "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
        }
        validate_contract(payload, "room-tool-disclosure-receipt.v1.json")
        payload_hash = _hash_json({key: value for key, value in payload.items() if key != "receiptId"})
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM room_v2_tool_disclosure_receipts WHERE receipt_id = ?",
                (payload["receiptId"],),
            ).fetchone()
            if existing is not None:
                stored = _disclosure_payload(existing)
                if stored != payload:
                    raise CapabilityManifestConflict("tool disclosure receipt identity changed")
                return stored, False
            conn.execute(
                """
                INSERT INTO room_v2_tool_disclosure_receipts(
                    receipt_id, manifest_id, manifest_hash, receipt_kind, query_text,
                    tool_name, schema_hash, payload_hash, payload_json, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["receiptId"], payload["manifestId"], payload["manifestHash"],
                    kind, query, tool_name, schema_hash, payload_hash,
                    _json(payload), payload["createdAtMs"],
                ),
            )
        return payload, True

    def _manifest(self, manifest_id: str, manifest_hash: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_capability_manifests WHERE manifest_id = ?",
                (_required(manifest_id, "manifest_id"),),
            ).fetchone()
        if row is None:
            raise KeyError(manifest_id)
        payload = _manifest_payload(row)
        if payload["manifestHash"] != _hash(manifest_hash, "manifest_hash"):
            raise CapabilityManifestConflict("Capability Manifest hash mismatch")
        return payload

    def _disclosure(self, receipt_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_tool_disclosure_receipts WHERE receipt_id = ?",
                (_required(receipt_id, "load_receipt_id"),),
            ).fetchone()
        if row is None:
            raise KeyError(receipt_id)
        return _disclosure_payload(row)

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


def normalize_room_tool_command(
    tool_name: str,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Normalize compatibility names without executing or sending anything."""

    original = _required(tool_name, "tool_name")
    canonical = _canonical_tool(original)
    return {
        "schemaVersion": "wisdom-weasel.room-tool-command-normalized.v1",
        "canonicalTool": canonical,
        "arguments": dict(arguments),
        "compatibility": (
            {"normalized": True, "originalTool": original}
            if original != canonical
            else {"normalized": False, "originalTool": original}
        ),
        "executionPerformed": False,
    }


def _binding_identity(
    room_binding: Mapping[str, object],
    participant_binding: Mapping[str, object],
    dispatch_id: str,
) -> dict[str, object]:
    validate_contract(dict(room_binding), "room-binding.v2.json")
    validate_contract(dict(participant_binding), "room-participant-binding.v2.json")
    expected_ref = {
        "bindingId": room_binding["bindingId"],
        "schemaVersion": room_binding["schemaVersion"],
    }
    if participant_binding.get("roomBindingRef") != expected_ref:
        raise CapabilityManifestConflict("ParticipantBinding does not reference RoomBinding")
    if participant_binding["capabilityRevision"] != room_binding["capabilityRevision"]:
        raise CapabilityManifestConflict("capability revision differs across bindings")
    return {
        "bindingId": str(participant_binding["bindingId"]),
        "roomId": str(room_binding["roomId"]), "rootId": str(room_binding["rootId"]),
        "taskId": str(room_binding.get("taskId") or ""),
        "dispatchId": _required(dispatch_id, "dispatch_id"),
        "generation": int(room_binding["generation"]),
        "capabilityRevision": str(room_binding["capabilityRevision"]),
        "capabilityEpoch": int(participant_binding["capabilityEpoch"]),
    }


def _assert_manifest_context(
    manifest: Mapping[str, object],
    current: Mapping[str, object],
) -> None:
    fields = (
        "bindingId", "roomId", "rootId", "taskId", "dispatchId", "generation",
        "capabilityRevision", "capabilityEpoch",
    )
    drift = [field for field in fields if manifest[field] != current[field]]
    if drift:
        raise CapabilityManifestConflict("stale invocation context: " + ",".join(drift))


def _canonical_tool(name: str) -> str:
    normalized = _required(name, "tool_name")
    canonical = LEGACY_ROOM_TOOL_ALIASES.get(normalized, normalized)
    if canonical not in ROOM_PUBLIC_TOOLS:
        raise ValueError("Room public tool surface only supports room_state/room_post/room_commit")
    return canonical


def _manifest_tool(manifest: Mapping[str, object], name: str) -> dict[str, object]:
    for value in manifest.get("tools") or []:
        if isinstance(value, Mapping) and value.get("name") == name:
            return dict(value)
    raise KeyError(name)


def _manifest_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = json.loads(str(row["payload_json"]))
    if not isinstance(payload, dict):
        raise RuntimeError("Capability Manifest payload is corrupt")
    return payload


def _disclosure_payload(row: sqlite3.Row) -> dict[str, object]:
    payload = json.loads(str(row["payload_json"]))
    if not isinstance(payload, dict):
        raise RuntimeError("tool disclosure receipt is corrupt")
    return payload


def _invocation_payload(row: sqlite3.Row) -> dict[str, object]:
    command = json.loads(str(row["command_json"]))
    return {
        "schemaVersion": "wisdom-weasel.room-tool-invocation-receipt.v1",
        "receiptId": str(row["receipt_id"]), "manifestId": str(row["manifest_id"]),
        "manifestHash": str(row["manifest_hash"]),
        "loadReceiptId": str(row["load_receipt_id"]),
        "invocationKey": str(row["invocation_key"]),
        "canonicalCommand": command, "authorizationState": str(row["authorization_state"]),
        "createdAtMs": int(row["created_at_ms"]),
    }


def _names(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _required(value: object, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _non_negative(value: object, field: str) -> int:
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{field} must be non-negative")
    return normalized


def _hash(value: object, field: str) -> str:
    normalized = _required(value, field)
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{field} must be a lowercase sha256")
    return normalized


def _hash_json(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
