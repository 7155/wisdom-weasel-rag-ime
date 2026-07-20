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


def room_runtime_registry() -> dict[str, dict[str, object]]:
    """Canonical Room-only Provider surface; legacy names never enter the catalog."""

    return {
        "room_state": {
            "description": "Read the current canonical Root, Task and Dispatch state.",
            "risk": "R0",
            "operation": "room.state",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        "room_post": {
            "description": "Publish one explicit RoomPost bound to the active Dispatch.",
            "risk": "R1",
            "operation": "room.post",
            "inputSchema": {
                "type": "object",
                "required": ["content"],
                "properties": {"content": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
        "room_commit": {
            "description": "Submit a governed continuation or completion proposal for the active Dispatch.",
            "risk": "R1",
            "operation": "room.commit",
            "inputSchema": {
                "type": "object",
                "required": ["result"],
                "properties": {"result": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        },
    }


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

    def bind_runtime(
        self,
        *,
        session_id: str,
        manifest_id: str,
        manifest_hash: str,
        prompt_compile_receipt: Mapping[str, object],
        compiled_runtime_profile_ref: Mapping[str, object],
        room_binding: Mapping[str, object],
        participant_binding: Mapping[str, object],
        surface_manifest_hashes: Mapping[str, str],
        created_at_ms: int,
        state: str = "active",
    ) -> tuple[dict[str, object], bool]:
        """Seal the one manifest identity consumed by Prompt, Runtime, Gateway and UI."""

        manifest = self._manifest(manifest_id, manifest_hash)
        _assert_manifest_context(
            manifest,
            _binding_identity(room_binding, participant_binding, str(manifest["dispatchId"])),
        )
        self.assert_surface_manifest_hashes(manifest_hash, surface_manifest_hashes)
        validate_contract(dict(prompt_compile_receipt), "prompt-compile-receipt.v1.json")
        plan = prompt_compile_receipt.get("plan")
        if not isinstance(plan, Mapping):
            raise CapabilityManifestConflict("PromptCompileReceipt has no PromptPlan")
        if (
            plan.get("bindingId") != manifest["bindingId"]
            or plan.get("roomId") != manifest["roomId"]
            or plan.get("rootId") != manifest["rootId"]
            or plan.get("sessionId") != session_id
            or int(plan.get("generation", -1)) != int(manifest["generation"])
            or plan.get("capabilityRevision") != manifest["capabilityRevision"]
            or int(plan.get("capabilityEpoch", -1)) != int(manifest["capabilityEpoch"])
        ):
            raise CapabilityManifestConflict("PromptCompileReceipt does not match Capability Manifest")
        profile_id = _required(compiled_runtime_profile_ref.get("profileId"), "profileId")
        profile_revision = _required(compiled_runtime_profile_ref.get("revision"), "profileRevision")
        profile_hash = _required(compiled_runtime_profile_ref.get("contentHash"), "profileHash")
        if participant_binding.get("compiledRuntimeProfileRef") != dict(compiled_runtime_profile_ref):
            raise CapabilityManifestConflict("CompiledRuntimeProfile ref differs from ParticipantBinding")
        binding_state = str(state).strip()
        if binding_state not in {"prepared", "active"}:
            raise ValueError("runtime capability binding state must be prepared or active")
        payload = {
            "sessionId": _required(session_id, "session_id"),
            "manifestId": manifest_id,
            "manifestHash": manifest_hash,
            "promptCompileReceiptId": _required(prompt_compile_receipt.get("receiptId"), "promptCompileReceiptId"),
            "promptPlanHash": _required(plan.get("planHash"), "promptPlanHash"),
            "compiledRuntimeProfileRef": {
                "profileId": profile_id,
                "revision": profile_revision,
                "contentHash": profile_hash,
            },
            "capabilityEpoch": int(manifest["capabilityEpoch"]),
            "state": binding_state,
        }
        timestamp = _non_negative(created_at_ms, "created_at_ms")
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM room_v2_capability_runtime_bindings WHERE session_id = ? AND manifest_id = ?",
                (session_id, manifest_id),
            ).fetchone()
            if existing is not None:
                stored = _runtime_binding_payload(existing)
                if stored != payload:
                    raise CapabilityManifestConflict("Session runtime capability binding changed")
                return stored, False
            conn.execute(
                """INSERT INTO room_v2_capability_runtime_bindings(
                   session_id, manifest_id, manifest_hash, prompt_compile_receipt_id,
                   prompt_plan_hash, compiled_profile_id, compiled_profile_revision,
                   compiled_profile_hash, room_binding_json, participant_binding_json,
                   capability_epoch, state, created_at_ms, updated_at_ms
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, manifest_id, manifest_hash, payload["promptCompileReceiptId"],
                    payload["promptPlanHash"], profile_id, profile_revision, profile_hash,
                    _json(dict(room_binding)), _json(dict(participant_binding)),
                    payload["capabilityEpoch"], binding_state, timestamp, timestamp,
                ),
            )
        return payload, True

    def runtime_binding(self, session_id: str, *, active_only: bool = True) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM room_v2_capability_runtime_bindings
                   WHERE session_id = ? AND (? = 0 OR state = 'active')
                   ORDER BY CASE state WHEN 'active' THEN 0 WHEN 'prepared' THEN 1 ELSE 2 END,
                            updated_at_ms DESC, created_at_ms DESC LIMIT 1""",
                (_required(session_id, "session_id"), 1 if active_only else 0),
            ).fetchone()
        if row is None:
            return None
        return _runtime_binding_payload(row)

    def revoke_runtime(self, session_id: str, *, capability_epoch: int, now_ms: int) -> None:
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                """SELECT manifest_id, capability_epoch FROM room_v2_capability_runtime_bindings
                   WHERE session_id = ? AND state = 'active'""",
                (_required(session_id, "session_id"),),
            ).fetchone()
            if row is None:
                return
            if int(capability_epoch) <= int(row["capability_epoch"]):
                raise CapabilityManifestConflict("revocation must advance capabilityEpoch")
            conn.execute(
                """UPDATE room_v2_capability_runtime_bindings
                   SET state = 'revoked', capability_epoch = ?, updated_at_ms = ?
                   WHERE session_id = ? AND manifest_id = ?""",
                (int(capability_epoch), _non_negative(now_ms, "now_ms"), session_id, row["manifest_id"]),
            )

    def manifest_for_runtime(self, session_id: str) -> tuple[dict[str, object], dict[str, object]] | None:
        binding = self.runtime_binding(session_id)
        if binding is None:
            return None
        return self._manifest(str(binding["manifestId"]), str(binding["manifestHash"])), binding

    def execution_receipt(self, invocation_receipt_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM room_v2_tool_execution_receipts WHERE invocation_receipt_id = ?",
                (_required(invocation_receipt_id, "invocation_receipt_id"),),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            raise RuntimeError("tool execution receipt is corrupt")
        return payload

    def runtime_tool_search(
        self, *, session_id: str, receipt_id: str, query: str, created_at_ms: int
    ) -> tuple[dict[str, object], bool]:
        binding = self.runtime_binding(session_id)
        if binding is None:
            raise ToolAuthorizationError("Session has no active Room Capability Manifest")
        return self.tool_search(
            receipt_id=receipt_id,
            manifest_id=str(binding["manifestId"]),
            manifest_hash=str(binding["manifestHash"]),
            query=query,
            created_at_ms=created_at_ms,
        )

    def runtime_tool_load(
        self, *, session_id: str, receipt_id: str, tool_name: str, created_at_ms: int
    ) -> tuple[dict[str, object], bool]:
        binding = self.runtime_binding(session_id)
        if binding is None:
            raise ToolAuthorizationError("Session has no active Room Capability Manifest")
        return self.tool_load(
            receipt_id=receipt_id,
            manifest_id=str(binding["manifestId"]),
            manifest_hash=str(binding["manifestHash"]),
            tool_name=tool_name,
            runtime_registry=room_runtime_registry(),
            created_at_ms=created_at_ms,
        )

    def authorize_runtime_invocation(
        self,
        *,
        session_id: str,
        receipt_id: str,
        invocation_key: str,
        load_receipt_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        binding = self.runtime_binding(session_id)
        if binding is None:
            raise ToolAuthorizationError("Session has no active Room Capability Manifest")
        manifest = self._manifest(str(binding["manifestId"]), str(binding["manifestHash"]))
        with self._connect() as conn:
            row = conn.execute(
                """SELECT room_binding_json, participant_binding_json
                   FROM room_v2_capability_runtime_bindings
                   WHERE session_id = ? AND manifest_id = ? AND state = 'active'""",
                (session_id, binding["manifestId"]),
            ).fetchone()
        assert row is not None
        return self.authorize_invocation(
            receipt_id=receipt_id,
            invocation_key=invocation_key,
            manifest_id=str(binding["manifestId"]),
            manifest_hash=str(binding["manifestHash"]),
            load_receipt_id=load_receipt_id,
            tool_name=tool_name,
            arguments=arguments,
            room_binding=json.loads(str(row["room_binding_json"])),
            participant_binding=json.loads(str(row["participant_binding_json"])),
            dispatch_id=str(manifest["dispatchId"]),
            surface_manifest_hashes={name: str(binding["manifestHash"]) for name in _SURFACES},
            created_at_ms=created_at_ms,
        )

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


def _runtime_binding_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "sessionId": str(row["session_id"]),
        "manifestId": str(row["manifest_id"]),
        "manifestHash": str(row["manifest_hash"]),
        "promptCompileReceiptId": str(row["prompt_compile_receipt_id"]),
        "promptPlanHash": str(row["prompt_plan_hash"]),
        "compiledRuntimeProfileRef": {
            "profileId": str(row["compiled_profile_id"]),
            "revision": str(row["compiled_profile_revision"]),
            "contentHash": str(row["compiled_profile_hash"]),
        },
        "capabilityEpoch": int(row["capability_epoch"]),
        "state": str(row["state"]),
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
