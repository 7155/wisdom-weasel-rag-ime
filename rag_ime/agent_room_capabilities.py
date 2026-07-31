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

_QUESTION_OPTIONS_INPUT_SCHEMA = {
    "type": "array",
    "minItems": 2,
    "maxItems": 5,
    "items": {
        "type": "object",
        "required": ["value", "label"],
        "properties": {
            "value": {
                "type": "string",
                "minLength": 1,
                "maxLength": 80,
            },
            "label": {
                "type": "string",
                "minLength": 1,
                "maxLength": 120,
            },
            "description": {
                "type": "string",
                "minLength": 1,
                "maxLength": 500,
            },
            "recommended": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
}


def room_runtime_registry() -> dict[str, dict[str, object]]:
    """Canonical Room-only Provider surface; legacy names never enter the catalog."""

    return {
        "room_state": {
            "description": (
                "查看自己当前负责的部分、验收清单和可用伙伴。同一版本重复查看时，"
                "会返回 unchanged=true；成功结果中的 evidenceRef 可证明本次确实"
                "读到了这些状态。"
            ),
            "when": (
                "当前上下文不足以确认自己要做什么、怎样验收、是否可以结束，或该找谁协作",
            ),
            "notFor": ("已经拿到同一版本的最新结果，或只是要发布一条公开更新",),
            "input": "无参数",
            "output": (
                "当前工作、验收短名、已接受证据、可用结束方式、伙伴 participantRef "
                "和本次读取的 evidenceRef"
            ),
            "does": "只读取当前 Room 状态，不会创建工作或改变任何人的进度。",
            "risk": "R0",
            "operation": "room.state",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        "room_collaborate": {
            "description": (
                "自己继续手上工作的同时，请另一位平级伙伴完成一个明确、互不重叠的"
                "小部分。目标必须是另一位可用伙伴，不能是自己；acceptance 只能使用"
                "当前工作卡片给出的验收短名。"
            ),
            "when": (
                "自己仍能继续，同时需要另一位伙伴独立查证、实现或检查",
                "用户明确要求分成不同部分，自己继续推进并等待各自结果，"
                "结果到齐后一起复核",
                "需要清楚点名一位伙伴一起做，但不是把自己的全部工作交出去",
            ),
            "notFor": (
                "自己的全部工作必须由对方接着完成",
                "用户已经指定由该伙伴在你完成后做最终检查或下一阶段",
                "只想公开说一句话或私下自言自语",
            ),
            "input": (
                "目标伙伴的 participantRef、邀请目的、具体工作、预期结果、"
                "至少一个当前验收短名和可选的已公开证据"
            ),
            "output": (
                "是否邀请成功、是否已经邀请过，以及目标伙伴的 participantRef；"
                "自己继续手上的工作。没有成功结果时，不得声称对方已经开始"
            ),
            "does": "邀请一位伙伴并行完成一项范围明确、可取消且不会重复创建的工作。",
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
                            "从 room_state 选择另一位可用伙伴的 participantRef；"
                            "不得填写自己。"
                        ),
                        "type": "string",
                        "minLength": 1,
                    },
                    "objective": {"type": "string", "minLength": 1},
                    "expectedOutput": {"type": "string", "minLength": 1},
                    "intent": {"enum": ["execute", "review", "revise"]},
                    "acceptance": {
                        "description": (
                            "从当前工作卡片选择要由这位伙伴协助满足的验收短名；"
                            "不得使用其他工作或其他伙伴的验收短名。"
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
                "立即发布一条有实质新变化的公开 Room 中途消息；不会结束本轮工作，"
                "也不会转移自己的责任。"
            ),
            "when": (
                "仍要继续当前工作，并有新增的完成项、验证、问题、风险或下一步",
            ),
            "notFor": (
                "私下思考、自言自语、创建新工作、声称已经完成或重复既有状态",
                "马上要调用 room_commit，且同一内容会写在 publicSummary 中",
            ),
            "input": "消息类型、写给用户的内容、可选通知对象与结构化展示块",
            "output": "published、postRef 与 deduplicated；postRef 不能作为验收证据",
            "does": "立即发布一条用户可见、重试时不会重复出现的 Room 消息。",
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
                    "content": {
                        "description": (
                            "写给用户的自然语言更新，只报告相对上一条有意义的新变化；"
                            "不粘贴私有推理、协议字段、引用 ID 或工具调用流水。服务端会"
                            "拒绝内部 Room 标识、原始回执、哈希和机器绝对路径。"
                        ),
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 8000,
                    },
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
                "结束自己当前部分时，选择 deliver（完成）、handoff（交给下一位）、"
                "wait（等待明确信号）或 blocked（确实无法继续），然后结束本轮。"
                "完成声明必须把 evidence 中的 acceptance 绑定到当前工作卡片的验收"
                "短名；同一次普通工具执行不能直接证明多个验收项，需逐项运行对应验证"
                "或使用已绑定的正式验证回执。acceptanceAliases 只用于 handoff 定义"
                "下一位伙伴的验收，deliver 不填写它。服务端会核对实际结果和验收覆盖。"
            ),
            "when": (
                "已经完成实现或修复，并且要提交验收证据",
                "所有伙伴结果已经到齐，要完成最终验收并发布正式回复",
                "自己的部分已经完成、需要明确交接、正在等一个信号，或替代路径已经用尽",
                "用户指定另一位伙伴在当前工作完成后负责最终检查或下一阶段",
                "处理复核意见后，需要重新提交可检查的结果",
            ),
            "notFor": (
                "普通公开发言、私下进度、仍有能直接推进的下一步，或没有证据的完成声明",
            ),
            "input": (
                "decision、私有 summary、用户可见 publicSummary、按验收短名绑定的 "
                "evidence、residualRisks，以及 handoff/wait/blocked 所需字段"
                "和可选展示块"
            ),
            "output": "结束请求已暂存；服务端随后返回成功结果或说明需要修正什么",
            "does": (
                "这是结束或转交当前工作的唯一方式；成功后发布一条用户可见的完成、"
                "交接、等待或阻塞消息。"
            ),
            "risk": "R1",
            "operation": "room.commit",
            "inputSchema": {
                "type": "object",
                "required": [
                    "decision",
                    "summary",
                    "publicSummary",
                    "evidence",
                    "residualRisks",
                ],
                "properties": {
                    "decision": {
                        "description": (
                            "当前工作的结束方式：deliver 表示完成；handoff 表示明确交给"
                            "下一位伙伴；wait 表示等待外部信号；blocked 表示合理替代办法"
                            "已经用尽。"
                        ),
                        "enum": ["deliver", "handoff", "wait", "blocked"],
                    },
                    "summary": {
                        "description": (
                            "供服务端处理的私有结果或交接摘要，不会直接展示给用户。"
                        ),
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
                            "必填的用户可见正式回复。用自然语言说明结果或进度、已经做了"
                            "什么、为什么这样做、怎样验证、问题或风险、尚未验证的边界和"
                            "下一步；省略不适用项，不输出私下推理、内部协议字段、引用 ID "
                            "或工具流水。主张不得强于实际观察。服务端会拒绝内部 Room "
                            "标识、原始回执、哈希和机器绝对路径，并把它作为本轮唯一的"
                            "完成、交接、等待或阻塞回复发布；不要再用 room_post 重复发布。"
                        ),
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 8000,
                    },
                    "blocks": _RICH_BLOCK_INPUT_SCHEMA,
                    "targetParticipantRef": {
                        "description": (
                            "仅 handoff：从 room_state 选择接手伙伴的 participantRef。"
                        ),
                        "type": "string",
                        "minLength": 1,
                    },
                    "intent": {
                        "description": (
                            "仅 handoff：下一位伙伴要做什么。若对方负责最终验收或最终"
                            "收口，必须用 close；review 只表示独立检查，不负责最终回复。"
                        ),
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
                        "description": (
                            "仅 handoff：给接手伙伴的明确工作内容，不会直接显示给用户。"
                        ),
                        "type": "string",
                        "minLength": 1,
                    },
                    "expectedOutput": {
                        "description": "仅 handoff：接手伙伴应交付的可观察结果。",
                        "type": "string",
                        "minLength": 1,
                    },
                    "acceptanceAliases": {
                        "description": (
                            "仅 handoff：从当前工作卡片选择并交给下一位伙伴的验收短名。"
                            "deliver 的验收覆盖只写在 evidence，禁止填写本字段。"
                        ),
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 64,
                        "items": _ACCEPTANCE_ALIAS_SCHEMA,
                    },
                    "waitingFor": {
                        "description": (
                            "仅 wait：说明是在等待用户、另一位伙伴或外部信号。"
                            "等待伙伴时还必须填写 waitingForParticipantRef。"
                        ),
                        "enum": ["user", "participant", "external"]
                    },
                    "waitingForParticipantRef": {
                        "description": (
                            "仅 waitingFor=participant：从 room_state 原样复制正在等待的"
                            "伙伴 participantRef；该伙伴公开结果后，系统会恢复本轮一次。"
                        ),
                        "type": "string",
                        "minLength": 1,
                    },
                    "resumeCondition": {
                        "description": (
                            "说明出现什么可观察信号后可以继续；不得只写稍后再试。"
                        ),
                        "type": "string",
                        "minLength": 1,
                    },
                    "question": {"type": "string", "minLength": 1},
                    "questionOptions": _QUESTION_OPTIONS_INPUT_SCHEMA,
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
                                    {
                                        "required": [
                                            "waitingForParticipantRef"
                                        ]
                                    },
                                    {"required": ["resumeCondition"]},
                                    {"required": ["question"]},
                                    {"required": ["questionOptions"]},
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
                                    {
                                        "required": [
                                            "waitingForParticipantRef"
                                        ]
                                    },
                                    {"required": ["resumeCondition"]},
                                    {"required": ["question"]},
                                    {"required": ["questionOptions"]},
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
                            "properties": {
                                "decision": {"const": "wait"},
                                "waitingFor": {"const": "participant"},
                            },
                            "required": ["decision", "waitingFor"],
                        },
                        "then": {
                            "required": ["waitingForParticipantRef"]
                        },
                    },
                    {
                        "if": {
                            "properties": {
                                "decision": {"const": "wait"},
                                "waitingFor": {
                                    "enum": ["user", "external"]
                                },
                            },
                            "required": ["decision", "waitingFor"],
                        },
                        "then": {
                            "not": {
                                "required": [
                                    "waitingForParticipantRef"
                                ]
                            }
                        },
                    },
                    {
                        "if": {"required": ["questionOptions"]},
                        "then": {
                            "properties": {
                                "decision": {"const": "wait"},
                                "waitingFor": {"const": "user"},
                            },
                            "required": ["question", "waitingFor"],
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
                                    {
                                        "required": [
                                            "waitingForParticipantRef"
                                        ]
                                    },
                                    {"required": ["resumeCondition"]},
                                    {"required": ["question"]},
                                    {"required": ["questionOptions"]},
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
            if source.get("modelVisible") is False:
                tool["modelVisible"] = False
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

    def failed_command_replay(
        self,
        *,
        session_id: str,
        dispatch_id: str,
        invocation_receipt_id: str,
    ) -> dict[str, object] | None:
        """Return the failed/rejected command that the current call would replay.

        A new Tool call id is not new evidence. Once an exact command has
        failed, the same Session and Dispatch may retry it only after another
        Tool has produced a successful execution receipt. That keeps immediate
        model retries from re-running the same side effect while preserving the
        normal red-test -> patch -> green-test workflow.
        """

        invocation = self.invocation_receipt(invocation_receipt_id)
        command = _mapping(invocation.get("canonicalCommand"))
        command_hash = _hash(command.get("commandHash"), "command_hash")
        with self._connect() as conn:
            prior = conn.execute(
                """
                SELECT execution.rowid AS execution_order,
                       execution.payload_json
                FROM room_v2_tool_execution_receipts execution
                JOIN room_v2_tool_invocation_receipts candidate
                  ON candidate.receipt_id = execution.invocation_receipt_id
                JOIN room_v2_capability_manifests manifest
                  ON manifest.manifest_id = candidate.manifest_id
                 AND manifest.manifest_hash = candidate.manifest_hash
                WHERE execution.session_id = ?
                  AND manifest.dispatch_id = ?
                  AND candidate.command_hash = ?
                  AND execution.invocation_receipt_id <> ?
                ORDER BY execution.rowid DESC
                LIMIT 1
                """,
                (
                    _required(session_id, "session_id"),
                    _required(dispatch_id, "dispatch_id"),
                    command_hash,
                    _required(
                        invocation_receipt_id,
                        "invocation_receipt_id",
                    ),
                ),
            ).fetchone()
            if prior is None:
                return None
            payload = json.loads(str(prior["payload_json"]))
            if not isinstance(payload, dict):
                raise RuntimeError("tool execution receipt is corrupt")
            if payload.get("status") not in {"failed", "rejected"}:
                return None
            successful_evidence = conn.execute(
                """
                SELECT 1
                FROM room_v2_tool_execution_receipts execution
                JOIN room_v2_tool_invocation_receipts candidate
                  ON candidate.receipt_id = execution.invocation_receipt_id
                JOIN room_v2_capability_manifests manifest
                  ON manifest.manifest_id = candidate.manifest_id
                 AND manifest.manifest_hash = candidate.manifest_hash
                WHERE execution.session_id = ?
                  AND manifest.dispatch_id = ?
                  AND execution.status = 'applied'
                  AND execution.tool_name NOT IN (
                    'room_post',
                    'room_collaborate',
                    'room_commit'
                  )
                  AND execution.rowid > ?
                LIMIT 1
                """,
                (
                    _required(session_id, "session_id"),
                    _required(dispatch_id, "dispatch_id"),
                    int(prior["execution_order"]),
                ),
            ).fetchone()
        return None if successful_evidence is not None else payload

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
        resolved: list[dict[str, object]] = []
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
                    stored = _disclosure_payload(existing)
                    stable_stored = {
                        key: value
                        for key, value in stored.items()
                        if key != "createdAtMs"
                    }
                    stable_payload = {
                        key: value
                        for key, value in payload.items()
                        if key != "createdAtMs"
                    }
                    if stable_stored != stable_payload:
                        raise CapabilityManifestConflict(
                            "tool disclosure receipt identity changed"
                        )
                    resolved.append(stored)
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
                resolved.append(payload)
        return resolved, created

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
        if name in names:
            raise ValueError(
                f"{tool_name}.runtimeProjections names must be unique"
            )
        names.add(name)
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
