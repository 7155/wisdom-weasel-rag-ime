from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from .contracts.json_schema import validate_contract
from .db import apply_database_migrations


ROOM_PUBLIC_TOOLS = (
    "room_state",
    "room_post",
    "room_commit",
    "room_collaborate",
)
_SURFACES = frozenset({"prompt", "runtime", "gateway", "ui"})
_MODEL_TOOL_CATALOG_KEYS = (
    "name",
    "when",
    "notFor",
    "input",
    "output",
    "does",
)

_RICH_BLOCK_INPUT_SCHEMA = {
    "type": "array",
    "maxItems": 16,
    "items": {
        "type": "object",
        "required": ["id", "type", "data"],
        "properties": {
            "id": {"type": "string", "minLength": 1, "maxLength": 160},
            "type": {
                "enum": ["card", "checklist", "table", "artifact", "reference", "status", "file"]
            },
            "data": {"type": "object"},
        },
        "additionalProperties": False,
    },
}

_ACCEPTANCE_ALIAS_SCHEMA = {
    "type": "string",
    "pattern": "^AC-[1-9][0-9]*$",
}

_EVIDENCE_INPUT_SCHEMA = {
    "type": "array",
    "maxItems": 64,
    "items": {
        "type": "object",
        "required": ["acceptance", "refs"],
        "properties": {
            "acceptance": _ACCEPTANCE_ALIAS_SCHEMA,
            "refs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 64,
                "items": {"type": "string", "minLength": 1},
            },
        },
        "additionalProperties": False,
    },
}


def room_runtime_registry() -> dict[str, dict[str, object]]:
    """Canonical Room-only Provider surface; legacy names never enter the catalog."""

    return {
        "room_state": {
            "description": (
                "读取当前责任、AC 验收别名和有界参与者目录；同一状态修订重复"
                "读取时返回 unchanged=true。成功回执返回 evidenceRef，可用于证明"
                "本次读取到的 Room 状态。"
            ),
            "when": (
                "当前上下文或最近回执不足以确认责任、验收、可提交状态或协作目标",
            ),
            "notFor": ("已有同一状态修订的最新回执，或只需发布公开消息",),
            "input": "无参数",
            "output": (
                "当前责任、AC 验收别名、已接受证据、可提交状态、短 "
                "participantRef 和本次状态读取的 evidenceRef"
            ),
            "does": "读取当前 Room 任务真相，不创建任务或改变状态。",
            "risk": "R0",
            "operation": "room.state",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        "room_collaborate": {
            "description": (
                "在当前责任继续推进时，请一位可用 Room 成员承担同一受管 Root 下"
                "的一项有界子任务。目标必须是另一位可用成员，不能是当前参与者；"
                "acceptance 只能使用当前 Task 的 AC 别名。"
            ),
            "when": (
                "当前任务可继续，同时需要另一位成员独立查证、实现或复核",
                "需要结构化点名协作，但不转移当前责任",
            ),
            "notFor": (
                "当前责任必须转交给对方",
                "必须等对方结果才能继续当前步骤",
                "只想公开说一句话或私下自言自语",
            ),
            "input": (
                "目标 participantRef、意图、子任务、预期输出、"
                "至少一个当前 AC 验收别名和可选的已公开证据"
            ),
            "output": (
                "已入队、是否去重和目标 participantRef；当前责任继续"
            ),
            "does": "异步派生一个可取消、可去重、受深度和预算限制的协作任务。",
            "risk": "R1",
            "operation": "room.collaborate",
            "inputSchema": {
                "type": "object",
                "required": [
                    "targetParticipantRef",
                    "intent",
                    "objective",
                    "expectedOutput",
                    "acceptance",
                ],
                "properties": {
                    "targetParticipantRef": {
                        "description": (
                            "另一位可用成员的 participantRef；不得填写当前参与者自己。"
                        ),
                        "type": "string",
                        "minLength": 1,
                    },
                    "objective": {"type": "string", "minLength": 1},
                    "expectedOutput": {"type": "string", "minLength": 1},
                    "intent": {"enum": ["execute", "review", "revise"]},
                    "acceptance": {
                        "description": (
                            "本次子任务继承的当前 Task AC 别名；不得使用父任务、"
                            "Root 或其他成员的别名。"
                        ),
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": _ACCEPTANCE_ALIAS_SCHEMA,
                    },
                    "evidenceRefs": {
                        "type": "array",
                        "maxItems": 64,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "additionalProperties": False,
            },
        },
        "room_post": {
            "description": (
                "立即发布一条公开 Room 消息；它不会收工、完成或转移当前责任。"
            ),
            "when": ("需要向 Room 公开事实、进度、问题、答复或证据",),
            "notFor": ("私有推理、自言自语、创建任务或提交责任终态",),
            "input": "消息类型、公开内容、可选通知对象与结构化块",
            "output": "published、postRef 与 deduplicated；postRef 不是验收 evidenceRef",
            "does": "立即发布一条可重放、可去重的公共 Room 消息。",
            "risk": "R1",
            "operation": "room.post",
            "inputSchema": {
                "type": "object",
                "required": ["kind", "content"],
                "properties": {
                    "kind": {
                        "enum": [
                            "progress",
                            "question",
                            "answer",
                            "evidence",
                            "notice",
                        ]
                    },
                    "content": {"type": "string", "minLength": 1},
                    "mentions": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "blocks": _RICH_BLOCK_INPUT_SCHEMA,
                },
                "additionalProperties": False,
            },
        },
        "room_commit": {
            "description": (
                "把当前责任提交为 deliver、handoff、wait 或 blocked，然后结束"
                "模型轮次。所有决定都用 evidence 中的 acceptance 绑定当前 Task "
                "AC；acceptanceAliases 只用于 handoff 定义下一项 Task 的验收，"
                "deliver 不填写它。Kernel 校验回执并计算覆盖与裁决。"
            ),
            "when": (
                "完成实现或修复后，需要提交验收覆盖与证据",
                "当前责任已形成交付、交接、等待或阻塞出口",
                "处理复核意见后，需要重新提交可复核结果",
            ),
            "notFor": (
                "普通公开发言、私有进度、仍可直接推进的下一步或没有证据的完成声明",
            ),
            "input": (
                "decision、summary、按 AC 别名绑定的 evidence、residualRisks，"
                "以及 handoff/wait/blocked 的专属字段；deliver 只增加可选的"
                " publicSummary/blocks"
            ),
            "output": "受管提议已暂存；Kernel 随后返回权威提交或可修复原因",
            "does": "提交当前责任的唯一生命周期出口并触发 Kernel 收工门。",
            "risk": "R1",
            "operation": "room.commit",
            "inputSchema": {
                "type": "object",
                "required": [
                    "decision",
                    "summary",
                    "evidence",
                    "residualRisks",
                ],
                "properties": {
                    "decision": {
                        "description": (
                            "当前责任的唯一出口；deliver 完成当前 Task，handoff "
                            "创建明确接手任务，wait 等待外部信号，blocked 报告有界"
                            "替代路径已耗尽。"
                        ),
                        "enum": ["deliver", "handoff", "wait", "blocked"],
                    },
                    "summary": {
                        "description": "当前责任的简短结果或出口说明。",
                        "type": "string",
                        "minLength": 1,
                    },
                    "evidence": _EVIDENCE_INPUT_SCHEMA,
                    "residualRisks": {
                        "description": (
                            "当前出口仍保留的真实风险；没有时传空数组。"
                        ),
                        "type": "array",
                        "maxItems": 32,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "publicSummary": {
                        "description": (
                            "可选的公开交付摘要；不替代先前 room_post，也不填写"
                            " Kernel verdict。"
                        ),
                        "type": "string",
                        "minLength": 1,
                    },
                    "blocks": _RICH_BLOCK_INPUT_SCHEMA,
                    "targetParticipantRef": {
                        "description": "仅 handoff：接手成员的 participantRef。",
                        "type": "string",
                        "minLength": 1,
                    },
                    "intent": {
                        "description": "仅 handoff：下一项 Task 的协作意图。",
                        "enum": [
                            "execute",
                            "review",
                            "revise",
                            "resume",
                            "retry",
                            "callback",
                            "close",
                        ]
                    },
                    "nextTask": {
                        "description": "仅 handoff：接手者需要完成的明确任务。",
                        "type": "string",
                        "minLength": 1,
                    },
                    "expectedOutput": {
                        "description": "仅 handoff：接手任务的可观察产物。",
                        "type": "string",
                        "minLength": 1,
                    },
                    "acceptanceAliases": {
                        "description": (
                            "仅 handoff：从当前 Root 选择并交给下一项 Task 的 AC "
                            "别名。deliver 的验收覆盖只写在 evidence，禁止填写本字段。"
                        ),
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": _ACCEPTANCE_ALIAS_SCHEMA,
                    },
                    "waitingFor": {
                        "enum": ["user", "participant", "external"]
                    },
                    "resumeCondition": {"type": "string", "minLength": 1},
                    "question": {"type": "string", "minLength": 1},
                    "blocker": {"type": "string", "minLength": 1},
                    "attemptedAlternatives": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 16,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "unlockCondition": {"type": "string", "minLength": 1},
                    "suggestedParticipantOrModel": {
                        "type": "string",
                        "minLength": 1,
                    },
                },
                "oneOf": [
                    {
                        "properties": {"decision": {"const": "deliver"}},
                        "required": ["decision"],
                    },
                    {
                        "properties": {"decision": {"const": "handoff"}},
                        "required": [
                            "decision",
                            "targetParticipantRef",
                            "intent",
                            "nextTask",
                            "expectedOutput",
                            "acceptanceAliases",
                        ],
                    },
                    {
                        "properties": {"decision": {"const": "wait"}},
                        "required": [
                            "decision",
                            "waitingFor",
                            "resumeCondition",
                        ],
                    },
                    {
                        "properties": {"decision": {"const": "blocked"}},
                        "required": [
                            "decision",
                            "blocker",
                            "attemptedAlternatives",
                            "unlockCondition",
                        ],
                    },
                ],
                "allOf": [
                    {
                        "if": {
                            "properties": {"decision": {"const": "deliver"}},
                            "required": ["decision"],
                        },
                        "then": {
                            "not": {
                                "anyOf": [
                                    {"required": ["targetParticipantRef"]},
                                    {"required": ["intent"]},
                                    {"required": ["nextTask"]},
                                    {"required": ["expectedOutput"]},
                                    {"required": ["acceptanceAliases"]},
                                    {"required": ["waitingFor"]},
                                    {"required": ["resumeCondition"]},
                                    {"required": ["question"]},
                                    {"required": ["blocker"]},
                                    {"required": ["attemptedAlternatives"]},
                                    {"required": ["unlockCondition"]},
                                    {
                                        "required": [
                                            "suggestedParticipantOrModel"
                                        ]
                                    },
                                ]
                            }
                        },
                    },
                    {
                        "if": {
                            "properties": {"decision": {"const": "handoff"}},
                            "required": ["decision"],
                        },
                        "then": {
                            "not": {
                                "anyOf": [
                                    {"required": ["waitingFor"]},
                                    {"required": ["resumeCondition"]},
                                    {"required": ["question"]},
                                    {"required": ["blocker"]},
                                    {"required": ["attemptedAlternatives"]},
                                    {"required": ["unlockCondition"]},
                                    {
                                        "required": [
                                            "suggestedParticipantOrModel"
                                        ]
                                    },
                                ]
                            }
                        },
                    },
                    {
                        "if": {
                            "properties": {"decision": {"const": "wait"}},
                            "required": ["decision"],
                        },
                        "then": {
                            "not": {
                                "anyOf": [
                                    {"required": ["targetParticipantRef"]},
                                    {"required": ["intent"]},
                                    {"required": ["nextTask"]},
                                    {"required": ["expectedOutput"]},
                                    {"required": ["acceptanceAliases"]},
                                    {"required": ["blocker"]},
                                    {"required": ["attemptedAlternatives"]},
                                    {"required": ["unlockCondition"]},
                                    {
                                        "required": [
                                            "suggestedParticipantOrModel"
                                        ]
                                    },
                                ]
                            }
                        },
                    },
                    {
                        "if": {
                            "properties": {"decision": {"const": "blocked"}},
                            "required": ["decision"],
                        },
                        "then": {
                            "not": {
                                "anyOf": [
                                    {"required": ["targetParticipantRef"]},
                                    {"required": ["intent"]},
                                    {"required": ["nextTask"]},
                                    {"required": ["expectedOutput"]},
                                    {"required": ["acceptanceAliases"]},
                                    {"required": ["waitingFor"]},
                                    {"required": ["resumeCondition"]},
                                    {"required": ["question"]},
                                ]
                            }
                        },
                    },
                ],
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
        canonical_registry = room_runtime_registry()
        ordered_names = (
            *ROOM_PUBLIC_TOOLS,
            *sorted(
                _canonical_tool(name)
                for name, source in runtime_registry.items()
                if name not in ROOM_PUBLIC_TOOLS
                and isinstance(source, Mapping)
                and source.get("catalogKind") == "product-tool"
            ),
        )
        for name in ordered_names:
            source = runtime_registry.get(name)
            if not isinstance(source, Mapping):
                continue
            routing_source = canonical_registry.get(name, source)
            schema = source.get("inputSchema")
            if not isinstance(schema, Mapping):
                raise ValueError(f"runtime tool {name} requires inputSchema")
            denied_by = [gate for gate, allowed in gates.items() if name not in allowed]
            tool = {
                "name": name,
                "description": _required(source.get("description"), f"{name}.description"),
                "when": list(source.get("when") or routing_source["when"]),
                "notFor": list(source.get("notFor") or routing_source["notFor"]),
                "input": _required(
                    source.get("input") or routing_source["input"],
                    f"{name}.input",
                ),
                "output": _required(
                    source.get("output") or routing_source["output"],
                    f"{name}.output",
                ),
                "does": _required(
                    source.get("does") or routing_source["does"],
                    f"{name}.does",
                ),
                "risk": _required(source.get("risk") or "controlled", f"{name}.risk"),
                "operation": _required(source.get("operation") or name, f"{name}.operation"),
                "schemaHash": _hash_json(dict(schema)),
                # The schema is pinned in the backend manifest so a restart can
                # restore the exact disclosure contract. Search responses still
                # project only the six compact routing fields.
                "inputSchema": dict(schema),
                "available": True,
                "authorized": not denied_by,
                "deniedBy": denied_by,
            }
            projections = source.get("runtimeProjections")
            if projections:
                tool["runtimeProjections"] = _runtime_projections(
                    projections,
                    name,
                )
            tools.append(tool)
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
        normalized_query = str(query or "").strip()
        ranked = [
            (
                _tool_routing_score(normalized_query, _mapping(tool)),
                index,
                _mapping(tool),
            )
            for index, tool in enumerate(manifest["tools"])
        ]
        if normalized_query:
            ranked = [item for item in ranked if item[0] > 0]
            ranked.sort(
                key=lambda item: (
                    -item[0],
                    str(item[2].get("name") or ""),
                    item[1],
                )
            )
        items = [
            {key: tool[key] for key in _MODEL_TOOL_CATALOG_KEYS}
            for _score, _index, tool in ranked
        ]
        # Search deliberately never discloses inputSchema.
        return self._record_disclosure(
            receipt_id=receipt_id,
            manifest=manifest,
            kind="search",
            query=normalized_query,
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
        runtime_registry: Mapping[str, Mapping[str, object]] | None,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        receipts, created = self.tool_load_batch(
            manifest_id=manifest_id,
            manifest_hash=manifest_hash,
            loads=(
                {
                    "receiptId": receipt_id,
                    "toolName": tool_name,
                },
            ),
            runtime_registry=runtime_registry,
            created_at_ms=created_at_ms,
        )
        return receipts[0], created

    def tool_load_batch(
        self,
        *,
        manifest_id: str,
        manifest_hash: str,
        loads: Sequence[Mapping[str, object]],
        runtime_registry: Mapping[str, Mapping[str, object]] | None,
        created_at_ms: int,
    ) -> tuple[list[dict[str, object]], bool]:
        if not 1 <= len(loads) <= 4:
            raise ValueError("tool load batch must contain between one and four items")
        manifest = self._manifest(manifest_id, manifest_hash)
        payloads: list[dict[str, object]] = []
        receipt_ids: set[str] = set()
        tool_names: set[str] = set()
        for load in loads:
            receipt_id = _required(
                str(load.get("receiptId") or ""),
                "receipt_id",
            )
            canonical = _canonical_tool(str(load.get("toolName") or ""))
            if receipt_id in receipt_ids:
                raise ValueError("tool load batch receiptId values must be unique")
            if canonical in tool_names:
                raise ValueError("tool load batch toolName values must be unique")
            receipt_ids.add(receipt_id)
            tool_names.add(canonical)
            tool = _manifest_tool(manifest, canonical)
            pinned_schema = tool.get("inputSchema")
            if not isinstance(pinned_schema, Mapping):
                raise CapabilityManifestConflict(
                    "capability manifest has no pinned tool schema"
                )
            schema = dict(pinned_schema)
            source = (runtime_registry or {}).get(canonical)
            if source is not None:
                if not isinstance(source, Mapping) or not isinstance(
                    source.get("inputSchema"), Mapping
                ):
                    raise CapabilityManifestConflict(
                        "runtime registry no longer provides disclosed tool"
                    )
                if _hash_json(dict(source["inputSchema"])) != tool["schemaHash"]:
                    raise CapabilityManifestConflict(
                        "runtime tool schema hash differs from manifest"
                    )
            if _hash_json(schema) != tool["schemaHash"]:
                raise CapabilityManifestConflict(
                    "pinned tool schema hash differs from manifest"
                )
            payloads.append(
                self._disclosure_receipt(
                    receipt_id=receipt_id,
                    manifest=manifest,
                    kind="load",
                    query="",
                    tool_name=canonical,
                    schema_hash=str(tool["schemaHash"]),
                    items=[
                        {
                            **{
                                key: tool[key]
                                for key in _MODEL_TOOL_CATALOG_KEYS
                            },
                            "inputSchema": schema,
                        }
                    ],
                    created_at_ms=created_at_ms,
                )
            )
        return self._record_disclosures(payloads)

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
        normalized = validate_room_tool_command(tool_name, arguments)
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
                    key, canonical, canonical, command_hash,
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

    def runtime_identity(self, session_id: str) -> dict[str, object] | None:
        """Return the server-stored Room identity needed by context recall."""

        with self._connect() as conn:
            row = conn.execute(
                """SELECT binding.room_binding_json, manifest.dispatch_id
                   FROM room_v2_capability_runtime_bindings binding
                   JOIN room_v2_capability_manifests manifest
                     ON manifest.manifest_id = binding.manifest_id
                   WHERE binding.session_id = ?
                   ORDER BY CASE binding.state WHEN 'active' THEN 0 WHEN 'prepared' THEN 1 ELSE 2 END,
                            binding.updated_at_ms DESC, binding.created_at_ms DESC LIMIT 1""",
                (_required(session_id, "session_id"),),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["room_binding_json"]))
        if not isinstance(payload, dict):
            raise RuntimeError("Room runtime binding identity is corrupt")
        payload["dispatchId"] = str(row["dispatch_id"])
        return payload

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

    def manifest_for_runtime(
        self,
        session_id: str,
        *,
        active_only: bool = True,
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        binding = self.runtime_binding(session_id, active_only=active_only)
        if binding is None:
            return None
        return self._manifest(str(binding["manifestId"]), str(binding["manifestHash"])), binding

    def latest_runtime_invocation(
        self,
        *,
        session_id: str,
        dispatch_id: str,
        tool_name: str,
    ) -> dict[str, object] | None:
        """Return the newest authorized invocation for one fenced Dispatch."""

        canonical = _canonical_tool(tool_name)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT invocation.*
                   FROM room_v2_tool_invocation_receipts invocation
                   JOIN room_v2_capability_manifests manifest
                     ON manifest.manifest_id = invocation.manifest_id
                    AND manifest.manifest_hash = invocation.manifest_hash
                   JOIN room_v2_capability_runtime_bindings binding
                     ON binding.manifest_id = invocation.manifest_id
                    AND binding.manifest_hash = invocation.manifest_hash
                   WHERE binding.session_id = ?
                     AND manifest.dispatch_id = ?
                     AND invocation.canonical_tool_name = ?
                   ORDER BY invocation.created_at_ms DESC, invocation.receipt_id DESC
                   LIMIT 1""",
                (
                    _required(session_id, "session_id"),
                    _required(dispatch_id, "dispatch_id"),
                    canonical,
                ),
            ).fetchone()
        return _invocation_payload(row) if row is not None else None

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

    def latest_runtime_execution(
        self,
        *,
        session_id: str,
        dispatch_id: str,
        tool_name: str,
        exclude_invocation_receipt_id: str = "",
    ) -> dict[str, object] | None:
        """Return the newest sealed result for one Tool on the fenced Dispatch."""

        canonical = _canonical_tool(tool_name)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT execution.payload_json
                FROM room_v2_tool_execution_receipts execution
                JOIN room_v2_tool_invocation_receipts invocation
                  ON invocation.receipt_id = execution.invocation_receipt_id
                JOIN room_v2_capability_manifests manifest
                  ON manifest.manifest_id = invocation.manifest_id
                 AND manifest.manifest_hash = invocation.manifest_hash
                WHERE execution.session_id = ?
                  AND manifest.dispatch_id = ?
                  AND execution.tool_name = ?
                  AND execution.invocation_receipt_id <> ?
                ORDER BY execution.created_at_ms DESC,
                         execution.execution_receipt_id DESC
                LIMIT 1
                """,
                (
                    _required(session_id, "session_id"),
                    _required(dispatch_id, "dispatch_id"),
                    canonical,
                    str(exclude_invocation_receipt_id or ""),
                ),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        if not isinstance(payload, dict):
            raise RuntimeError("tool execution receipt is corrupt")
        return payload

    def runtime_evidence_refs(
        self,
        *,
        session_id: str,
        dispatch_id: str,
    ) -> set[str]:
        """Return successful evidence-producing Tool receipts for one Dispatch."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT execution.execution_receipt_id
                FROM room_v2_tool_execution_receipts execution
                JOIN room_v2_tool_invocation_receipts invocation
                  ON invocation.receipt_id = execution.invocation_receipt_id
                JOIN room_v2_capability_manifests manifest
                  ON manifest.manifest_id = invocation.manifest_id
                 AND manifest.manifest_hash = invocation.manifest_hash
                WHERE execution.session_id = ?
                  AND manifest.dispatch_id = ?
                  AND execution.status = 'applied'
                  AND execution.tool_name NOT IN (
                    'room_post',
                    'room_collaborate',
                    'room_commit'
                  )
                ORDER BY execution.execution_receipt_id
                """,
                (
                    _required(session_id, "session_id"),
                    _required(dispatch_id, "dispatch_id"),
                ),
            ).fetchall()
        return {str(row["execution_receipt_id"]) for row in rows}

    def record_runtime_execution(
        self,
        *,
        session_id: str,
        invocation_receipt_id: str,
        status: str,
        result_hash: str,
        created_at_ms: int,
    ) -> tuple[dict[str, object], bool]:
        """Seal one non-Room Tool result under its active Dispatch capability."""

        normalized_status = str(status or "").strip()
        if normalized_status not in {"applied", "rejected", "cancelled", "failed"}:
            raise ValueError("Room Tool execution status is invalid")
        binding = self.runtime_binding(session_id)
        if binding is None:
            raise ToolAuthorizationError(
                "Session Room Capability Manifest was revoked before Tool result"
            )
        invocation = self.invocation_receipt(invocation_receipt_id)
        if (
            invocation["manifestId"] != binding["manifestId"]
            or invocation["manifestHash"] != binding["manifestHash"]
        ):
            raise CapabilityManifestConflict(
                "Tool execution receipt belongs to another capability manifest"
            )
        tool_name = _canonical_tool(
            _mapping(invocation.get("canonicalCommand")).get("tool")
        )
        payload = {
            "schemaVersion": "wisdom-weasel.room-tool-execution-receipt.v1",
            "executionReceiptId": f"execution:{invocation_receipt_id}",
            "invocationReceiptId": invocation_receipt_id,
            "kernelReceiptId": None,
            "sessionId": _required(session_id, "session_id"),
            "toolName": tool_name,
            "status": normalized_status,
            "resultHash": _hash(result_hash, "result_hash"),
            "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
        }
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT payload_json FROM room_v2_tool_execution_receipts "
                "WHERE invocation_receipt_id = ?",
                (invocation_receipt_id,),
            ).fetchone()
            if existing is not None:
                stored = json.loads(str(existing["payload_json"]))
                stable_fields = (
                    "executionReceiptId",
                    "invocationReceiptId",
                    "sessionId",
                    "toolName",
                    "status",
                    "resultHash",
                )
                if any(stored.get(field) != payload[field] for field in stable_fields):
                    raise CapabilityManifestConflict(
                        "Tool execution receipt identity changed"
                    )
                return dict(stored), False
            conn.execute(
                """
                INSERT INTO room_v2_tool_execution_receipts(
                    execution_receipt_id, invocation_receipt_id,
                    kernel_receipt_id, session_id, tool_name, status,
                    result_hash, payload_json, created_at_ms
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["executionReceiptId"],
                    invocation_receipt_id,
                    payload["sessionId"],
                    tool_name,
                    normalized_status,
                    payload["resultHash"],
                    _json(payload),
                    payload["createdAtMs"],
                ),
            )
        return payload, True

    def invocation_receipt(self, invocation_receipt_id: str) -> dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM room_v2_tool_invocation_receipts WHERE receipt_id = ?",
                (_required(invocation_receipt_id, "invocation_receipt_id"),),
            ).fetchone()
        if row is None:
            raise KeyError(invocation_receipt_id)
        return _invocation_payload(row)

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
        self,
        *,
        session_id: str,
        receipt_id: str,
        tool_name: str,
        created_at_ms: int,
        runtime_registry: Mapping[str, Mapping[str, object]] | None = None,
    ) -> tuple[dict[str, object], bool]:
        binding = self.runtime_binding(session_id)
        if binding is None:
            raise ToolAuthorizationError("Session has no active Room Capability Manifest")
        return self.tool_load(
            receipt_id=receipt_id,
            manifest_id=str(binding["manifestId"]),
            manifest_hash=str(binding["manifestHash"]),
            tool_name=tool_name,
            runtime_registry=runtime_registry,
            created_at_ms=created_at_ms,
        )

    def runtime_tool_load_batch(
        self,
        *,
        session_id: str,
        loads: Sequence[Mapping[str, object]],
        created_at_ms: int,
        runtime_registry: Mapping[str, Mapping[str, object]] | None = None,
    ) -> tuple[list[dict[str, object]], bool]:
        binding = self.runtime_binding(session_id)
        if binding is None:
            raise ToolAuthorizationError(
                "Session has no active Room Capability Manifest"
            )
        return self.tool_load_batch(
            manifest_id=str(binding["manifestId"]),
            manifest_hash=str(binding["manifestHash"]),
            loads=loads,
            runtime_registry=runtime_registry,
            created_at_ms=created_at_ms,
        )

    def restore_runtime_tool_disclosures(
        self,
        *,
        session_id: str,
        recovery: Mapping[str, object],
        allow_revoked: bool = False,
    ) -> dict[str, object]:
        """Verify exact Tool load receipts after a managed Room compaction."""

        binding = self.runtime_binding(
            session_id,
            active_only=not allow_revoked,
        )
        if binding is None:
            raise ToolAuthorizationError(
                "Session has no active Room Capability Manifest"
            )
        manifest = self._manifest(
            str(binding["manifestId"]),
            str(binding["manifestHash"]),
        )
        raw_items = recovery.get("items")
        if not isinstance(raw_items, Sequence) or isinstance(
            raw_items, (str, bytes)
        ):
            raise CapabilityManifestConflict(
                "Room tool recovery items must be an array"
            )
        restored: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                raise CapabilityManifestConflict(
                    "Room tool recovery item must be an object"
                )
            name = _canonical_tool(raw_item.get("name"))
            if name in seen:
                raise CapabilityManifestConflict(
                    "Room tool recovery contains a duplicate tool"
                )
            seen.add(name)
            receipt_id = _required(
                raw_item.get("receiptId"),
                "receipt_id",
            )
            disclosure = self._disclosure(receipt_id)
            tool = _manifest_tool(manifest, name)
            if (
                disclosure["kind"] != "load"
                or disclosure["manifestId"] != manifest["manifestId"]
                or disclosure["manifestHash"] != manifest["manifestHash"]
                or disclosure["toolName"] != name
                or disclosure["schemaHash"] != tool["schemaHash"]
            ):
                raise CapabilityManifestConflict(
                    "Room tool recovery receipt is stale or belongs to another manifest"
                )
            restored.append(
                {
                    "name": name,
                    "receiptId": receipt_id,
                    "schemaHash": disclosure["schemaHash"],
                }
            )
        return {
            "schemaVersion": "wisdom-weasel.room-tool-recovery.v1",
            "manifestId": manifest["manifestId"],
            "manifestHash": manifest["manifestHash"],
            "capabilityEpoch": manifest["capabilityEpoch"],
            "items": restored,
        }

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
        payload = self._disclosure_receipt(
            receipt_id=receipt_id,
            manifest=manifest,
            kind=kind,
            query=query,
            tool_name=tool_name,
            schema_hash=schema_hash,
            items=items,
            created_at_ms=created_at_ms,
        )
        payloads, created = self._record_disclosures([payload])
        return payloads[0], created

    @staticmethod
    def _disclosure_receipt(
        *,
        receipt_id: str,
        manifest: Mapping[str, object],
        kind: str,
        query: str,
        tool_name: str,
        schema_hash: str,
        items: list[dict[str, object]],
        created_at_ms: int,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": "wisdom-weasel.room-tool-disclosure-receipt.v1",
            "receiptId": _required(receipt_id, "receipt_id"),
            "manifestId": manifest["manifestId"], "manifestHash": manifest["manifestHash"],
            "kind": kind, "query": query, "toolName": tool_name,
            "schemaHash": schema_hash, "items": items,
            "createdAtMs": _non_negative(created_at_ms, "created_at_ms"),
        }
        validate_contract(payload, "room-tool-disclosure-receipt.v1.json")
        return payload

    def _record_disclosures(
        self,
        payloads: Sequence[Mapping[str, object]],
    ) -> tuple[list[dict[str, object]], bool]:
        if not payloads:
            raise ValueError("tool disclosure batch cannot be empty")
        normalized = [dict(payload) for payload in payloads]
        receipt_ids = [str(payload["receiptId"]) for payload in normalized]
        if len(receipt_ids) != len(set(receipt_ids)):
            raise CapabilityManifestConflict(
                "tool disclosure receipt identities must be unique"
            )
        created = False
        with self._connect(immediate=True) as conn:
            existing_rows = {
                str(row["receipt_id"]): row
                for row in conn.execute(
                    f"""
                    SELECT * FROM room_v2_tool_disclosure_receipts
                    WHERE receipt_id IN ({','.join('?' for _ in receipt_ids)})
                    """,
                    receipt_ids,
                ).fetchall()
            }
            for payload in normalized:
                receipt_id = str(payload["receiptId"])
                existing = existing_rows.get(receipt_id)
                if existing is not None:
                    if _disclosure_payload(existing) != payload:
                        raise CapabilityManifestConflict(
                            "tool disclosure receipt identity changed"
                        )
                    continue
                payload_hash = _hash_json(
                    {
                        key: value
                        for key, value in payload.items()
                        if key != "receiptId"
                    }
                )
                conn.execute(
                    """
                    INSERT INTO room_v2_tool_disclosure_receipts(
                        receipt_id, manifest_id, manifest_hash, receipt_kind, query_text,
                        tool_name, schema_hash, payload_hash, payload_json, created_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["receiptId"],
                        payload["manifestId"],
                        payload["manifestHash"],
                        payload["kind"],
                        payload["query"],
                        payload["toolName"],
                        payload["schemaHash"],
                        payload_hash,
                        _json(payload),
                        payload["createdAtMs"],
                    ),
                )
                created = True
        return normalized, created

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


def validate_room_tool_command(
    tool_name: str,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Build a canonical command without executing or sending anything."""

    canonical = _canonical_tool(tool_name)
    return {
        "schemaVersion": "wisdom-weasel.room-tool-command-normalized.v1",
        "canonicalTool": canonical,
        "arguments": dict(arguments),
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
    canonical = _required(name, "tool_name")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", canonical):
        raise ValueError("Room capability tool name is not canonical")
    if canonical.startswith("room_") and canonical not in ROOM_PUBLIC_TOOLS:
        raise ValueError(
            "Room public tool surface only supports "
            "room_state/room_collaborate/room_post/room_commit"
        )
    return canonical


def _manifest_tool(manifest: Mapping[str, object], name: str) -> dict[str, object]:
    for value in manifest.get("tools") or []:
        if isinstance(value, Mapping) and value.get("name") == name:
            return dict(value)
    raise KeyError(name)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


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


def _tool_routing_score(
    query: str,
    tool: Mapping[str, object],
) -> int:
    normalized = query.strip().casefold()
    if not normalized:
        return 1
    name = str(tool.get("name") or "").casefold()
    fragments = _query_fragments(normalized)
    if normalized == name:
        return 1_000
    if name in fragments:
        return 900

    when = [str(value) for value in tool.get("when") or []]
    not_for = [str(value) for value in tool.get("notFor") or []]
    if any(
        normalized in value.casefold()
        or _fragment_coverage(normalized, value) >= 0.75
        for value in not_for
    ):
        return -1

    description = str(tool.get("description") or "")
    supporting = " ".join(
        [
            description,
            str(tool.get("input") or ""),
            str(tool.get("output") or ""),
            str(tool.get("does") or ""),
        ]
    ).casefold()
    when_text = " ".join(when).casefold()
    score = 0
    if normalized in name:
        score += 300
    if normalized in when_text:
        score += 120
    if normalized in supporting:
        score += 60
    for fragment in fragments:
        if fragment in name:
            score += 40
        if fragment in when_text:
            score += 16
        if fragment in supporting:
            score += 8
    positive_coverage = max(
        (0.0, *(_fragment_coverage(normalized, value) for value in when))
    )
    if positive_coverage >= 0.5:
        score += round(positive_coverage * 100)
    return score


def _query_fragments(query: str) -> set[str]:
    fragments: set[str] = set()
    for token in re.findall(r"[\w-]+", query.casefold(), flags=re.UNICODE):
        fragments.add(token)
        if len(token) >= 2 and all("\u4e00" <= char <= "\u9fff" for char in token):
            fragments.update(
                token[index : index + 2]
                for index in range(len(token) - 1)
            )
    return fragments


def _fragment_coverage(query: str, value: str) -> float:
    fragments = _query_fragments(query)
    if not fragments:
        return 0.0
    normalized = value.casefold()
    matched = sum(fragment in normalized for fragment in fragments)
    return matched / len(fragments)


def _names(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _runtime_projections(
    value: object,
    tool_name: str,
) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{tool_name}.runtimeProjections must be an array")
    result: list[dict[str, str]] = []
    names: set[str] = set()
    operations: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"{tool_name}.runtimeProjections[{index}] must be an object"
            )
        name = _required(
            item.get("name"),
            f"{tool_name}.runtimeProjections[{index}].name",
        )
        operation = _required(
            item.get("operation"),
            f"{tool_name}.runtimeProjections[{index}].operation",
        )
        if name in names or operation in operations:
            raise ValueError(
                f"{tool_name}.runtimeProjections must be unique"
            )
        names.add(name)
        operations.add(operation)
        result.append({"name": name, "operation": operation})
    return result


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
