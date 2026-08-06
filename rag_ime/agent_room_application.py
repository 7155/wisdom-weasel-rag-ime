from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Callable, Mapping, Sequence

from .agent_definitions import canonical_collaboration_role_id
from .agent_personas import AgentPersonaStore
from .agent_role_book import AgentRoleBookStore
from .agent_room_capabilities import RoomCapabilityManifestStore
from .agent_room_context import RoomContextLedgerStore
from .agent_room_kernel import (
    RoomKernelFenceError,
    RoomKernelStore,
    kernel_owns_room_execution,
)
from .agent_room_kernel_contracts import (
    DEFAULT_RUNTIME_PROFILE_REVISION,
    DISPATCH_ENVELOPE_SCHEMA_VERSION,
    ROOM_POST_SCHEMA_VERSION,
    ROOM_TASK_SCHEMA_VERSION,
    ROOT_EXECUTION_SCHEMA_VERSION,
)
from .agent_room_kernel_projection import RoomKernelProjection
from .agent_room_kernel_worker import KernelCommandBus
from .agent_room_public_timeline import (
    RoomPublicTimelineProjector,
    canonical_room_alignment_content,
    public_room_post_payload,
)
from .agent_room_references import (
    ParticipantReferenceError,
    participant_ref_map,
    resolve_participant_ref,
)
from .agent_room_requirements import RequirementGovernanceStore
from .agent_room_work import AgentRoomWorkStore
from .agent_rooms import AgentRoomStore
from .agent_sessions import AgentSessionStore
from .agent_session_mode_gate import AgentSessionModeGate


DEFAULT_ROOT_BUDGET = 32
DEFAULT_MAX_HOPS = 6
DEFAULT_MAX_DEPTH = 3


_UNRESOLVED_DEFINITION_PLACEHOLDER = re.compile(
    r"(?:当前项目|规定入口|核心操作|真实结果|某个具体(?:界面|流程|功能)|"
    r"相关(?:界面|流程|功能)|现有(?:界面|流程|功能|\s*TUI))",
    re.IGNORECASE,
)
_VAGUE_DEFINITION_ONLY = re.compile(
    r"^(?:我要|请)?\s*(?:完成|实现|做好|补全|完善)?\s*"
    r"(?:一个|一套)?\s*(?:当前项目的?)?\s*"
    r"(?:TUI|终端(?:界面|页面|程序)?|界面|页面|程序)?\s*"
    r"(?:端到端可用(?:版本)?|可运行闭环|完整(?:版本)?|可用(?:版本)?|完成)?"
    r"[。.!！?？]*$",
    re.IGNORECASE,
)
_GENERIC_DEFINITION_FRAGMENT = re.compile(
    r"(?:我要|请|完成|实现|做好|补全|完善|一个|一套|当前项目的?|"
    r"TUI|终端(?:界面|页面|程序)?|界面|页面|程序|端到端可用(?:版本)?|"
    r"可运行闭环|完整(?:版本)?|可用(?:版本)?|具体|相关|现有|规定|"
    r"核心|真实|入口|操作|结果|交付)",
    re.IGNORECASE,
)
_GENERIC_ENTRY_SURFACE = re.compile(
    r"^(?:(?:当前|默认|主要|规定|相关|现有)?(?:项目|应用|系统|产品)?的?)?"
    r"(?:首页|页面|界面|入口|模块|功能|位置|地方)$",
    re.IGNORECASE,
)
_GENERIC_PRIMARY_INTERACTION = re.compile(
    r"^(?:执行|完成|进行|操作|体验|使用|run|execute|complete)"
    r"(?:主要|核心|相关|完整|main|core)?"
    r"(?:流程|操作|功能|任务|flow|action|feature|task)$",
    re.IGNORECASE,
)
_GENERIC_OBSERVABLE_COMPLETION = re.compile(
    r"^(?:看到|显示|获得|返回|得到|see|show|return)?"
    r"(?:成功|正确|最终|真实|预期|successful|correct|expected)?"
    r"(?:提示|结果|状态|反馈|产品|result|status|output|feedback)$",
    re.IGNORECASE,
)
_ENTRY_SURFACE_SIGNAL = re.compile(
    r"(?:任务页|对话页|页面|界面|视图|窗口|菜单|按钮|列表|时间线|卡片|命令|终端|文件|模块|接口|API|"
    r"服务|脚本|测试|工作区|仓库|目录|路径|应用|page|view|window|menu|"
    r"button|command|terminal|file|module|endpoint|service|script|test|"
    r"workspace|repository|directory|path|app|[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,8})",
    re.IGNORECASE,
)
_PRIMARY_INTERACTION_SIGNAL = re.compile(
    r"(?:点击|输入|选择|按下|按|打开|启动|运行|执行|提交|发送|编辑|修改|"
    r"创建|添加|删除|标记|停止|退出|展开|切换|调用|读取|检查|核对|"
    r"滚动|拖动|加载|刷新|重试|恢复|"
    r"点名|接手|实施|"
    r"click|type|select|press|open|start|run|submit|send|edit|update|"
    r"create|add|delete|mark|stop|exit|expand|switch|call|read|check)",
    re.IGNORECASE,
)
_OBSERVABLE_COMPLETION_SIGNAL = re.compile(
    r"(?:看到|显示|出现|输出|返回|生成|创建|保存|更新|通过|失败|错误|"
    r"状态|反馈|退出码|文件|记录|列表|结果|see|show|appear|output|return|"
    r"generate|create|save|update|pass|fail|error|status|feedback|exit code|"
    r"file|record|list|result)",
    re.IGNORECASE,
)
_USER_FACING_CODE_IDENTIFIER = re.compile(
    r"(?:`[^`\n]+`|\b[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b)"
)


def _definition_specific_remainder(value: str) -> str:
    without_placeholders = _UNRESOLVED_DEFINITION_PLACEHOLDER.sub(
        " ", value
    )
    without_generic = _GENERIC_DEFINITION_FRAGMENT.sub(
        " ", without_placeholders
    )
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", without_generic)


def _assert_specific_definition_field(value: str, *, field: str) -> None:
    normalized = re.sub(r"\s+", "", value.strip())
    generic_pattern = {
        "entry": _GENERIC_ENTRY_SURFACE,
        "interaction": _GENERIC_PRIMARY_INTERACTION,
        "completion": _GENERIC_OBSERVABLE_COMPLETION,
    }[field]
    required_signal = {
        "entry": _ENTRY_SURFACE_SIGNAL,
        "interaction": _PRIMARY_INTERACTION_SIGNAL,
        "completion": _OBSERVABLE_COMPLETION_SIGNAL,
    }[field]
    if (
        not normalized
        or _VAGUE_DEFINITION_ONLY.fullmatch(value.strip())
        or generic_pattern.fullmatch(normalized)
        or required_signal.search(value) is None
        or len(_definition_specific_remainder(value)) < 4
    ):
        raise ValueError(
            "还不能开始：请把具体入口或页面、关键操作，以及完成后能观察到的"
            "结果分别说明清楚。"
        )


def _assert_concrete_room_definition(
    *,
    objective: str,
    expected_output: str,
    entry_surface: str,
    primary_interaction: str,
    observable_completion: str,
    requirements: Sequence[str],
    criteria: Sequence[Mapping[str, object]],
) -> None:
    """Reject definitions that still hide the decision-changing specifics."""

    del requirements, criteria
    if not objective.strip() or not expected_output.strip():
        raise ValueError(
            "还不能开始：请说明这次要完成什么，以及最后会交付什么。"
        )
    # Objective and output may intentionally stay concise (for example
    # “完成终端原生 TUI 的可运行闭环”). The three dedicated fields carry the
    # decision-changing specifics and therefore own the strict validation.
    for field, value in (
        ("entry", entry_surface),
        ("interaction", primary_interaction),
        ("completion", observable_completion),
    ):
        _assert_specific_definition_field(value, field=field)


def _assert_user_facing_execution_plan_language(
    values: Sequence[str],
    *,
    reference: str,
) -> None:
    """Keep the start gate in the user's language instead of leaking schemas."""

    if not any("\u3400" <= char <= "\u9fff" for char in reference):
        return
    for value in values:
        if not value:
            continue
        if not any("\u3400" <= char <= "\u9fff" for char in value):
            raise ValueError(
                "开始行动前展示的方案必须使用用户正在使用的语言，不能直接展示英文数据结构。"
            )
        if _USER_FACING_CODE_IDENTIFIER.search(value):
            raise ValueError(
                "开始行动前展示的方案应从用户能做什么、能看到什么来描述；"
                "内部类型名和字段名请留到开始后的工作文档或技术详情。"
            )


def _resolve_room_answer_display(
    message: str,
    *,
    answer_kind: str,
    question_options: object,
) -> tuple[str, str]:
    """Resolve public answer text without guessing when the client is explicit."""

    normalized_kind = str(answer_kind or "").strip()
    if normalized_kind not in {"", "option", "custom"}:
        raise ValueError("answerKind must be option or custom")
    options = [
        option
        for option in question_options
        if isinstance(option, Mapping)
    ] if isinstance(question_options, list) else []
    matching_option = next(
        (
            option
            for option in options
            if str(option.get("value") or "") == message
        ),
        None,
    )
    if normalized_kind == "custom":
        return message, "custom"
    if normalized_kind == "option":
        if matching_option is None:
            raise ValueError(
                "Room clarification option answer does not match a presented option"
            )
        return (
            str(matching_option.get("label") or "").strip() or message,
            "option",
        )
    if matching_option is not None:
        return (
            str(matching_option.get("label") or "").strip() or message,
            "option",
        )
    return message, "custom"


class RoomApplicationService:
    """Product-facing Room commands backed by the canonical Kernel.

    This layer owns user intent, deterministic identities, immutable requirement
    capture, routing, and atomic fan-out. Runtime delivery remains exclusively
    owned by ``RoomKernelWorker``.
    """

    def __init__(
        self,
        *,
        rooms: AgentRoomStore,
        sessions: AgentSessionStore,
        personas: AgentPersonaStore,
        role_books: AgentRoleBookStore,
        work_items: AgentRoomWorkStore,
        kernel: RoomKernelStore,
        commands: KernelCommandBus,
        projection: RoomKernelProjection,
        context: RoomContextLedgerStore,
        requirements: RequirementGovernanceStore,
        capabilities: RoomCapabilityManifestStore,
        public_timeline: RoomPublicTimelineProjector,
        session_mode_gate: AgentSessionModeGate,
        wake_worker: Callable[[], None],
        restore_participant_sessions: Callable[[Mapping[str, object]], None],
        resolve_attachments: Callable[
            [str, Sequence[str], Sequence[str]], list[dict[str, object]]
        ],
        ensure_work_document: Callable[
            [Mapping[str, object]], Mapping[str, object] | None
        ],
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.rooms = rooms
        self.sessions = sessions
        self.personas = personas
        self.role_books = role_books
        self.work_items = work_items
        self.kernel = kernel
        self.commands = commands
        self.projection = projection
        self.context = context
        self.requirements = requirements
        self.capabilities = capabilities
        self.public_timeline = public_timeline
        self.session_mode_gate = session_mode_gate
        self.wake_worker = wake_worker
        self.restore_participant_sessions = restore_participant_sessions
        self.resolve_attachments = resolve_attachments
        self.ensure_work_document = ensure_work_document
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def post_message(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
        attachment_ids: Sequence[str] = (),
        answer_to_post_id: str = "",
        answer_to_root_id: str = "",
        answer_kind: str = "",
    ) -> dict[str, object]:
        room = self.rooms.get(room_id)
        self.restore_participant_sessions(room)
        room = self.rooms.get(room_id)
        active_session_ids = [
            str(value["sessionId"])
            for value in room.get("participants", [])
            if (
                isinstance(value, Mapping)
                and value.get("status") == "active"
                and str(value.get("sessionId") or "").strip()
            )
        ]
        with self.session_mode_gate.claim_room(active_session_ids):
            return self._post_message_claimed(
                room_id,

                message=message,
                client_message_id=client_message_id,
                requested_participant_ids=requested_participant_ids,
                work_item_id=work_item_id,
                attachment_ids=attachment_ids,
                answer_to_post_id=answer_to_post_id,
                answer_to_root_id=answer_to_root_id,
                answer_kind=answer_kind,
            )

    def start_execution(
        self,
        room_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Apply the typed one-shot start action after real clarification."""

        action = str(payload.get("action") or "").strip()
        root_id = str(payload.get("rootId") or "").strip()
        client_action_id = str(payload.get("clientActionId") or "").strip()
        if action != "start_execution" or not root_id or not client_action_id:
            raise ValueError(
                "start execution requires action=start_execution, rootId, and clientActionId"
            )
        room = self.rooms.get(room_id)
        root = self.kernel.root(root_id)
        if root.get("roomId") != room_id:
            raise RoomKernelFenceError(
                "typed start Root does not belong to this Room"
            )
        facilitator = self.rooms.participant(
            str(root["facilitatorParticipantId"])
        )
        if (
            facilitator.get("roomId") != room_id
            or facilitator.get("status") != "active"
        ):
            raise RoomKernelFenceError(
                "typed start Facilitator is no longer active"
            )
        timestamp = self.clock_ms()
        identity = _stable_digest(root_id, client_action_id, "typed-start")
        post_id = f"room-post:user:{identity}"
        prepared = self.kernel.prepare_defined_execution_start(
            root_id=root_id,
            client_action_id=client_action_id,
            user_post_id=post_id,
            room_id=room_id,
            topic_id=str(room.get("activeTopicId") or ""),
            now_ms=timestamp,
        )
        receipt_details = prepared["receipt"].get("details")
        if not isinstance(receipt_details, Mapping):
            raise RoomKernelFenceError("typed start receipt has no details")
        timestamp = int(prepared["receipt"]["createdAtMs"])
        post_id = str(receipt_details.get("userPostId") or post_id)
        effective_client_action_id = str(
            receipt_details.get("clientActionId") or client_action_id
        )
        chronology_after_post_id = str(
            receipt_details.get("chronologyAfterPostId") or ""
        )
        planned_dispatch = prepared.get("plannedDispatch")
        if not isinstance(planned_dispatch, Mapping):
            raise RoomKernelFenceError(
                "typed start preparation has no planned ExecuteDispatch"
            )
        task_id = str(planned_dispatch.get("taskId") or "").strip()
        if not task_id:
            raise RoomKernelFenceError(
                "typed start preparation has no defined Task"
            )
        prepared_topic_id = str(prepared.get("topicId") or "")
        prepare_receipt_id = str(
            prepared.get("prepareReceiptId")
            or prepared["receipt"]["receiptId"]
        )
        timeline_room = {
            **dict(room),
            "activeTopicId": prepared_topic_id,
        }
        user_post = {
            "schemaVersion": ROOM_POST_SCHEMA_VERSION,
            "postId": post_id,
            "roomId": room_id,
            "rootId": root_id,
            "generation": int(root["generation"]),
            "taskId": task_id,
            "authorActorRef": "user:local",
            "kind": "request",
            "visibility": "room",
            "content": "开始行动",
            "idempotencyKey": (
                f"typed-start:{root_id}:{effective_client_action_id}"
            ),
            "publicationSource": {
                "kind": "user",
                "ref": effective_client_action_id,
            },
            "createdAtMs": timestamp,
        }
        authorization_events = self.public_timeline.publish_ingress(
            room=timeline_room,
            post=user_post,
            client_message_id=effective_client_action_id,
            route_decisions=[],
            dispatches=[],
            chronology_after_post_id=chronology_after_post_id,
        )
        authorization_event = next(
            (
                event
                for event in authorization_events
                if event.get("eventType") == "user_message"
                and isinstance(event.get("payload"), Mapping)
                and str(event["payload"].get("postId") or "") == post_id
            ),
            None,
        )
        if authorization_event is None:
            authorization_event = (
                self.kernel.defined_execution_start_authorization(
                    root_id=root_id,
                    prepare_receipt_id=prepare_receipt_id,
                )
            )
        event_sequence = int(authorization_event["sequence"])
        user_post["chronology"] = {
            "schemaVersion": "wisdom-weasel.room-post-chronology.v1",
            "roomEventId": str(authorization_event["eventId"]),
            "roomEventSequence": event_sequence,
            "createdAtMs": timestamp,
            "afterPostId": chronology_after_post_id or None,
            "orderKey": f"room-event:{event_sequence:020d}",
        }
        transaction = sqlite3.connect(self.kernel.db_path, timeout=10)
        transaction.row_factory = sqlite3.Row
        try:
            transaction.execute("PRAGMA foreign_keys = ON")
            transaction.execute("BEGIN IMMEDIATE")
            user_post = self.projection.publish_post_in_transaction(
                transaction,
                user_post,
            )
            self.context.publish_post_in_transaction(
                transaction,
                user_post,
            )
            started = self.kernel.start_defined_execution(
                root_id=root_id,
                prepare_receipt_id=prepare_receipt_id,
                user_post=user_post,
                now_ms=timestamp,
                _conn=transaction,
            )
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        finally:
            transaction.close()
        dispatch = started["dispatch"]
        task = self.kernel.task(str(dispatch["taskId"]))
        work_document = self._ensure_started_work_document(
            room=room,
            root=root,
            task=task,
        )
        dispatch_result = _queued_dispatch_result(
            facilitator,
            dispatch,
            was_created=bool(started["created"]),
            phase="execution",
        )
        route_decision = {
            "routingPolicy": "typed_start_action",
            "reason": "用户确认开始已对齐的行动",
            "targetParticipantId": str(facilitator["id"]),
            "phase": "execution",
            "rootId": root_id,
            "taskId": str(task["taskId"]),
            "dispatchId": str(dispatch["dispatchId"]),
            "targetSessionId": str(facilitator["sessionId"]),
            "dependsOnDispatchIds": list(
                dispatch.get("dependsOnDispatchIds") or []
            ),
        }
        try:
            timeline_events = self.public_timeline.publish_ingress(
                room=timeline_room,
                post=user_post,
                client_message_id=effective_client_action_id,
                route_decisions=[route_decision],
                dispatches=[dispatch_result],
                chronology_after_post_id=chronology_after_post_id,
            )
        finally:
            # A retry after a crash between release and wake must kick the
            # already-durable outbox entry again, even when it is a replay.
            self.wake_worker()
        self.projection.sync_room(room_id, now_ms=timestamp)
        return {
            "schemaVersion": "rag-ime.room-start-execution.v1",
            "ok": True,
            "accepted": True,
            "created": bool(started["created"]),
            "roomId": room_id,
            "rootId": root_id,
            "taskId": str(task["taskId"]),
            "post": user_post,
            "dispatch": dispatch_result,
            "routeDecision": route_decision,
            "intake": started["intake"],
            "receipt": started["receipt"],
            "timelineEvents": timeline_events,
            "workDocument": work_document,
        }

    def _ensure_started_work_document(
        self,
        *,
        room: Mapping[str, object],
        root: Mapping[str, object],
        task: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        """Bind one WorkDocument after typed Start and before worker wake."""

        if str(room.get("roomKind") or "collaboration") != "collaboration":
            return None
        workspace_roots = [
            str(value).strip()
            for value in room.get("workspaceRoots") or []
            if str(value).strip()
        ]
        if not workspace_roots:
            raise RoomKernelFenceError(
                "collaboration Room Start requires an authorized workspace"
            )
        work_item_id = str(task.get("workItemId") or "").strip()
        if not work_item_id:
            raise RoomKernelFenceError(
                "collaboration Room Start has no root WorkItem authority"
            )
        work_item = self.work_items.get(
            work_item_id,
            room_id=str(room["id"]),
        )
        definition = self.kernel.definition_fence(
            root_id=str(root["rootId"])
        )
        if not isinstance(definition, Mapping):
            raise RoomKernelFenceError(
                "collaboration Room Start has no durable definition"
            )
        definition_receipt = definition.get("receipt")
        details = (
            definition_receipt.get("details")
            if isinstance(definition_receipt, Mapping)
            and isinstance(definition_receipt.get("details"), Mapping)
            else {}
        )
        anchor_id = str(root.get("requirementAnchorRef") or "").split(
            "@", 1
        )[0].strip()
        if not anchor_id:
            raise RoomKernelFenceError(
                "collaboration Room Start has no original requirement anchor"
            )
        original_vision = self.requirements.original_bytes(anchor_id).decode(
            "utf-8"
        )
        content = _room_work_document_markdown(
            room=room,
            root=root,
            work_item=work_item,
            original_vision=original_vision,
            execution_plan=(
                details.get("executionPlan")
                if isinstance(details, Mapping)
                else None
            ),
        )
        document = self.ensure_work_document(
            {
                "authorityId": work_item_id,
                "workspaceRoot": workspace_roots[0],
                "title": f"{str(room.get('title') or 'Room')} 工作文档",
                "content": content,
            }
        )
        if not isinstance(document, Mapping):
            raise RoomKernelFenceError(
                "collaboration Room Start did not establish its WorkDocument"
            )
        return dict(document)

    def define_room(
        self,
        room_id: str,
        *,
        dispatch_id: str,
        invocation_receipt_id: str,
        arguments: Mapping[str, object],
    ) -> dict[str, object]:
        """Atomically finalize alignment into one governed root WorkItem."""

        room = self.rooms.get(room_id)
        dispatch = self.kernel.dispatch(dispatch_id)
        root = self.kernel.root(str(dispatch["rootId"]))
        prior_definition = self.kernel.definition_fence(
            root_id=str(dispatch["rootId"]),
            dispatch_id=dispatch_id,
            invocation_receipt_id=invocation_receipt_id,
        )
        if (
            root.get("roomId") != room_id
            or dispatch.get("rootId") != root.get("rootId")
            or (
                prior_definition is None
                and not self.kernel.dispatch_is_active_alignment(dispatch_id)
            )
        ):
            raise RoomKernelFenceError(
                "room_define Dispatch does not belong to this Room alignment"
            )
        requested_review_policy = arguments.get(
            "independentReviewRequired"
        )
        if not isinstance(requested_review_policy, bool):
            raise ValueError(
                "room_define independentReviewRequired must be explicitly boolean"
            )
        participant_refs = participant_ref_map(room["participants"])
        implementation_ref = str(
            arguments.get("implementationParticipantRef") or ""
        ).strip()
        implementation_id = str(root["facilitatorParticipantId"])
        if implementation_ref:
            try:
                implementation_id = resolve_participant_ref(
                    implementation_ref,
                    participant_refs,
                )
            except ParticipantReferenceError:
                implementation_id = implementation_ref
                if not any(
                    isinstance(item, Mapping)
                    and str(item.get("id") or "") == implementation_id
                    and item.get("status") == "active"
                    for item in room.get("participants", [])
                ):
                    raise
        target = self.rooms.participant(implementation_id)
        if (
            target.get("roomId") != room_id
            or target.get("status") != "active"
            or not str(target.get("sessionId") or "").strip()
        ):
            raise RoomKernelFenceError(
                "room_define implementation participant is not active"
            )
        objective = str(arguments.get("objective") or "").strip()
        expected_output = str(arguments.get("expectedOutput") or "").strip()
        entry_surface = " ".join(
            str(arguments.get("entrySurface") or "").split()
        )
        primary_interaction = " ".join(
            str(arguments.get("primaryInteraction") or "").split()
        )
        observable_completion = " ".join(
            str(arguments.get("observableCompletion") or "").split()
        )
        raw_requirements = arguments.get("requirements")
        raw_criteria = arguments.get("acceptanceCriteria")
        if not objective or not expected_output:
            raise ValueError("room_define objective and expectedOutput are required")
        if (
            not isinstance(raw_requirements, Sequence)
            or isinstance(raw_requirements, (str, bytes))
            or not 1 <= len(raw_requirements) <= 8
        ):
            raise ValueError("room_define requirements must contain 1-8 items")
        if (
            not isinstance(raw_criteria, Sequence)
            or isinstance(raw_criteria, (str, bytes))
            or not 1 <= len(raw_criteria) <= 16
        ):
            raise ValueError(
                "room_define acceptanceCriteria must contain 1-16 items"
            )
        requirements = [
            " ".join(str(item or "").split())
            for item in raw_requirements
        ]
        if any(not item for item in requirements):
            raise ValueError("room_define requirements must not be empty")
        criteria_input: list[dict[str, object]] = []
        for value in raw_criteria:
            if isinstance(value, Mapping):
                statement = " ".join(
                    str(value.get("statement") or "").split()
                )
                criterion_kind = str(value.get("kind") or "requirement")
                full_name = str(
                    value.get("fullNameZh") or ""
                ).strip() or ""
                receipt_types = value.get("expectedReceiptTypes")
            else:
                statement = " ".join(str(value or "").split())
                criterion_kind = "requirement"
                full_name = ""
                receipt_types = None
            if not statement:
                raise ValueError("room_define acceptance criterion is empty")
            if criterion_kind not in {"requirement", "user_journey"}:
                raise ValueError("room_define acceptance criterion kind is invalid")
            normalized_receipt_types = [
                str(item).strip()
                for item in (
                    receipt_types
                    if isinstance(receipt_types, Sequence)
                    and not isinstance(receipt_types, (str, bytes))
                    else ["evidence"]
                )
                if str(item).strip()
            ]
            if not normalized_receipt_types or any(
                item not in {"test", "build", "install", "browser", "evidence"}
                for item in normalized_receipt_types
            ):
                raise ValueError(
                    "room_define acceptance criterion receipt types are invalid"
                )
            if not full_name:
                full_name = f"验收条件 {len(criteria_input) + 1}"
            if not any("\u4e00" <= char <= "\u9fff" for char in full_name):
                raise ValueError(
                    "room_define acceptance criterion fullNameZh must contain Chinese"
                )
            criteria_input.append(
                {
                    "statement": statement,
                    "criterionKind": criterion_kind,
                    "acceptanceCriterionFullNameZh": full_name,
                    "expectedReceiptTypes": list(
                        dict.fromkeys(normalized_receipt_types)
                    ),
                }
            )

        execution_plan = _normalize_room_execution_plan(
            arguments.get("executionPlan"),
            objective=objective,
            expected_output=expected_output,
            default_participant=target,
            participant_refs=participant_refs,
            participants=room.get("participants", []),
            acceptance_plan=[str(item["statement"]) for item in criteria_input],
        )

        if prior_definition is None:
            _assert_concrete_room_definition(
                objective=objective,
                expected_output=expected_output,
                entry_surface=entry_surface,
                primary_interaction=primary_interaction,
                observable_completion=observable_completion,
                requirements=requirements,
                criteria=criteria_input,
            )

        fence_id = f"room-definition-fence:{_stable_digest(invocation_receipt_id)}"
        alignment_post_id = (
            "room-post:alignment:"
            f"{_stable_digest(str(root['rootId']), 'defined-alignment')}"
        )
        alignment_idempotency_key = (
            f"room-define-alignment:{root['rootId']}"
        )
        prior_fence = prior_definition
        if prior_fence is not None:
            replay = {
                "schemaVersion": "rag-ime.room-define.v1",
                "ok": True,
                "created": False,
                **{
                    key: value
                    for key, value in prior_fence.items()
                    if key not in {"receipt"}
                },
                "definitionReceipt": prior_fence["receipt"],
                "idempotentReplay": True,
            }
            alignment_post = self.context.post_by_idempotency(
                room_id=room_id,
                idempotency_key=alignment_idempotency_key,
            )
            if alignment_post is not None:
                replay["alignmentPost"] = public_room_post_payload(
                    alignment_post
                )
            return replay
        if self.kernel.definition_fence(
            root_id=str(root["rootId"]),
            dispatch_id=dispatch_id,
        ) is not None:
            raise RoomKernelFenceError(
                "Root already has a different room_define fence"
            )

        context = self.requirements.dispatch_context(dispatch_id)
        if not isinstance(context, Mapping) or not isinstance(
            context.get("catalog"),
            Mapping,
        ):
            raise RoomKernelFenceError(
                "room_define requires the alignment RequirementCatalog"
            )
        current_catalog_id = str(
            context["catalog"].get("catalogRevisionId") or ""
        )
        current_catalog = self.requirements.catalog_revision(current_catalog_id)
        current_revision = int(current_catalog["revision"])
        existing_items = [
            dict(item)
            for item in current_catalog.get("items", [])
            if isinstance(item, Mapping)
        ]
        derived_item_ids: list[str] = []
        for ordinal, statement in enumerate(requirements):
            item_id = (
                f"requirement:{_stable_digest(str(root['rootId']), invocation_receipt_id, str(ordinal), statement)}"
            )
            derived_item_ids.append(item_id)
            existing_items.append(
                {
                    "itemId": item_id,
                    "kind": "agent_inferred_requirement",
                    "statement": statement,
                    "origin": "room_define",
                    "state": "active",
                    "sourceSpans": [],
                    "supersedes": [],
                    "ambiguity": "",
                    "confirmation": "derived_from_alignment",
                }
            )
        criterion_ids: list[str] = []
        final_criteria: list[dict[str, object]] = []
        for ordinal, item in enumerate(criteria_input):
            criterion_id = (
                f"criterion:{_stable_digest(str(root['rootId']), invocation_receipt_id, str(ordinal), str(item['statement']))}"
            )
            criterion_ids.append(criterion_id)
            final_criteria.append(
                {
                    "criterionId": criterion_id,
                    "itemId": derived_item_ids[
                        min(ordinal, len(derived_item_ids) - 1)
                    ],
                    "acceptanceCriterionFullNameZh": item[
                        "acceptanceCriterionFullNameZh"
                    ],
                    "criterionKind": item["criterionKind"],
                    "expectedReceiptTypes": item["expectedReceiptTypes"],
                    "statement": item["statement"],
                }
            )
        final_catalog_id = (
            f"requirement-catalog:{_stable_digest(str(root['rootId']), invocation_receipt_id)}"
        )
        work_id = (
            f"room-work:{_stable_digest(str(root['rootId']), invocation_receipt_id)}"
        )
        aliases = {
            f"AC-{ordinal + 1}": criterion_id
            for ordinal, criterion_id in enumerate(criterion_ids)
        }
        task = self.kernel.task(str(dispatch["taskId"]))
        task_payload = {
            **task,
            "workItemId": work_id,
            "objective": objective,
            "expectedOutput": expected_output,
            "requirementItemIds": [
                str(item["itemId"])
                for item in existing_items
                if str(item.get("itemId") or "").strip()
            ],
            "acceptanceCriterionIds": criterion_ids,
            "contextEvidenceRefs": [
                *[
                    str(value)
                    for value in task.get("contextEvidenceRefs") or []
                    if str(value).strip()
                ],
                fence_id,
            ],
            "revision": int(task.get("revision") or 0) + 1,
            "state": "active",
        }
        timestamp = self.clock_ms()
        facilitator = self.rooms.participant(
            str(root["facilitatorParticipantId"])
        )
        if (
            facilitator.get("roomId") != room_id
            or facilitator.get("status") != "active"
            or str(facilitator.get("sessionId") or "")
            != str(dispatch["targetSessionId"])
        ):
            raise RoomKernelFenceError(
                "room_define Facilitator Session is no longer active"
            )
        execute_dispatch_id = (
            f"room-dispatch:{_stable_digest(str(root['rootId']), invocation_receipt_id, 'execute')}"
        )
        execute_dispatch = {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": execute_dispatch_id,
            "rootId": str(root["rootId"]),
            "taskId": str(task_payload["taskId"]),
            "parentDispatchId": dispatch_id,
            "generation": int(dispatch["generation"]),
            "hopCount": int(dispatch["hopCount"]) + 1,
            "depth": int(dispatch["depth"]),
            "budgetCost": 1,
            "targetSessionId": str(facilitator["sessionId"]),
            "targetParticipantId": str(facilitator["id"]),
            "triggerId": fence_id,
            "intentKind": "execute",
            "idempotencyKey": f"room-define-execute:{root['rootId']}",
            "attempt": 0,
            "capabilityEpoch": int(dispatch["capabilityEpoch"]) + 1,
            "runtimeProfileRevision": str(
                dispatch["runtimeProfileRevision"]
            ),
            "dependsOnDispatchIds": [dispatch_id],
            "attachmentIds": list(dispatch.get("attachmentIds") or []),
            "state": "pending",
        }
        alignment_post: dict[str, object] | None = None
        transaction = sqlite3.connect(self.kernel.db_path, timeout=10)
        transaction.row_factory = sqlite3.Row
        try:
            transaction.execute("PRAGMA foreign_keys = ON")
            transaction.execute("BEGIN IMMEDIATE")
            catalog, _ = self.requirements.revise_catalog_in_transaction(
                transaction,
                catalog_revision_id=final_catalog_id,
                root_id=str(root["rootId"]),
                expected_current_revision=current_revision,
                anchor_refs=current_catalog["anchorRefs"],
                items=existing_items,
                acceptance_criteria=final_criteria,
                change_reason="对齐完成后建立最终实现需求与验收目录",
                provenance={
                    "derivedFrom": [current_catalog_id],
                    "definitionInvocationReceiptId": invocation_receipt_id,
                    "contextFenceId": fence_id,
                },
                created_by="room-define",
                created_at_ms=timestamp,
            )
            work_item, _ = self.work_items.create_root_in_transaction(
                transaction,
                work_id=work_id,
                room_id=room_id,
                objective=objective,
                expected_output=expected_output,
                current_owner_participant_id=str(
                    root["facilitatorParticipantId"]
                ),
                created_by_participant_id=str(root["facilitatorParticipantId"]),
                client_message_id=f"room-define:{invocation_receipt_id}",
                acceptance_criteria=[
                    str(item["statement"]) for item in final_criteria
                ],
                created_at_ms=timestamp,
                root_turn_id=str(root["rootId"]),
            )
            independent_review_required = bool(
                root.get("independentReviewRequired")
                or requested_review_policy is True
            )
            details = {
                "operation": "room_define",
                "dispatchId": dispatch_id,
                "invocationReceiptId": invocation_receipt_id,
                "definitionFenceId": fence_id,
                "catalogRevisionId": catalog["catalogRevisionId"],
                "catalogRevision": catalog["revision"],
                "anchorRefs": list(catalog["anchorRefs"]),
                "requirementItemIds": list(task_payload["requirementItemIds"]),
                "acceptanceCriterionIds": criterion_ids,
                "acceptanceAliases": aliases,
                "entrySurface": entry_surface,
                "primaryInteraction": primary_interaction,
                "observableCompletion": observable_completion,
                **({"executionPlan": execution_plan} if execution_plan else {}),
                "implementationParticipantId": implementation_id,
                "implementationParticipantRef": implementation_ref,
                "workItemId": work_item["id"],
                "independentReviewRequired": independent_review_required,
            }
            intake_before_definition = self.kernel.intake_state(
                str(root["rootId"]),
                conn=transaction,
            )
            if (
                execution_plan is not None
                or intake_before_definition.get("clarificationOccurred") is True
            ):
                alignment_post = {
                    "schemaVersion": ROOM_POST_SCHEMA_VERSION,
                    "postId": alignment_post_id,
                    "roomId": room_id,
                    "rootId": str(root["rootId"]),
                    "generation": int(root["generation"]),
                    "taskId": str(task_payload["taskId"]),
                    "dispatchId": dispatch_id,
                    "authorActorRef": str(
                        root["facilitatorParticipantId"]
                    ),
                    "kind": "alignment",
                    "visibility": "room",
                    "content": canonical_room_alignment_content(
                        objective=objective,
                        expected_output=expected_output,
                    ),
                    "idempotencyKey": alignment_idempotency_key,
                    "publicationSource": {
                        "kind": "room_post",
                        "ref": fence_id,
                    },
                    "createdAtMs": timestamp,
                }
                self.projection.publish_post_in_transaction(
                    transaction,
                    alignment_post,
                )
                self.context.publish_post_in_transaction(
                    transaction,
                    alignment_post,
                )
            revised = self.kernel.revise_definition_in_transaction(
                transaction,
                root_id=str(root["rootId"]),
                dispatch_id=dispatch_id,
                invocation_receipt_id=invocation_receipt_id,
                task_payload=task_payload,
                acceptance_criteria=criterion_ids,
                independent_review_required=independent_review_required,
                execute_dispatch_payload=execute_dispatch,
                details=details,
                now_ms=timestamp,
            )
            if bool(alignment_post) != bool(
                revised["receipt"]["details"].get("requiresStartAction")
            ):
                raise RoomKernelFenceError(
                    "room_define alignment publication disagrees with intake state"
                )
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        finally:
            transaction.close()
        response = {
            "schemaVersion": "rag-ime.room-define.v1",
            "ok": True,
            "created": True,
            "rootId": str(root["rootId"]),
            "taskId": str(task_payload["taskId"]),
            "dispatchId": dispatch_id,
            "definitionFenceId": fence_id,
            "definitionReceipt": revised["receipt"],
            "requirementCatalog": catalog,
            "acceptanceAliases": aliases,
            "implementationParticipant": target,
            "implementationParticipantRef": implementation_ref,
            **({"executionPlan": execution_plan} if execution_plan else {}),
            "workItem": work_item,
            "contextFence": {
                "definitionReceiptId": revised["receipt"]["receiptId"],
                "definitionFenceId": fence_id,
                "catalogRevisionId": catalog["catalogRevisionId"],
                "taskRevision": task_payload["revision"],
                "dispatchId": dispatch_id,
            },
            "intake": revised["intake"],
            "executionDispatch": revised["dispatch"],
            "requiresStartAction": bool(
                revised["receipt"]["details"].get("requiresStartAction")
            ),
            "next": (
                "await_typed_start_action"
                if revised["receipt"]["details"].get("requiresStartAction")
                else "room_collaborate_with_bounded_implementation_lanes"
            ),
        }
        if alignment_post is not None:
            response["alignmentPost"] = alignment_post
        self.projection.sync_room(room_id, now_ms=timestamp)
        return response
    def _replay_post_response(
        self,
        room_id: str,
        *,
        client_message_id: str,
        post: Mapping[str, object],
        expected_answer_to_post_id: str = "",
        expected_answer_to_root_id: str = "",
        expected_answer_kind: str = "",
    ) -> dict[str, object]:
        """Rebuild the durable ingress result without creating new state."""

        room = self.rooms.get(room_id)
        root_id = str(post.get("rootId") or "")
        task_id = str(post.get("taskId") or "")
        replay_identity = _message_identity(room_id, client_message_id)
        try:
            replay_anchor = self.requirements.anchor(
                f"requirement-anchor:{replay_identity}"
            )
        except KeyError:
            replay_anchor = None
        replay_provenance = (
            replay_anchor.get("provenance")
            if isinstance(replay_anchor, Mapping)
            else None
        )
        replay_topic_id = str(room.get("activeTopicId") or "")
        answer_to_post_id = ""
        answer_display_text = ""
        answer_kind = ""
        if (
            isinstance(replay_provenance, Mapping)
            and str(replay_provenance.get("roomId") or "") == room_id
            and str(replay_provenance.get("clientMessageId") or "")
            == client_message_id
        ):
            answer_to_post_id = str(
                replay_provenance.get("questionPostId") or ""
            )
            answer_display_text = str(
                replay_provenance.get("answerDisplayText") or ""
            )
            candidate_answer_kind = str(
                replay_provenance.get("answerKind") or ""
            )
            if candidate_answer_kind in {"option", "custom"}:
                answer_kind = candidate_answer_kind
            replay_topic_id = str(
                replay_provenance.get("topicId") or replay_topic_id
            )
        if expected_answer_to_post_id and (
            answer_to_post_id != expected_answer_to_post_id
            or str(post.get("rootId") or "") != expected_answer_to_root_id
            or (
                expected_answer_kind
                and answer_kind != expected_answer_kind
            )
        ):
            raise RoomKernelFenceError(
                "durable clarification answer provenance does not match its retry"
            )
        root = self.kernel.root(root_id)
        alignment_dispatches = self.kernel.requirement_alignment_dispatches(root_id)
        alignment_results: list[dict[str, object]] = []
        for dispatch in alignment_dispatches:
            target = self.rooms.participant(
                str(dispatch["targetParticipantId"])
            )
            alignment_results.append(
                _queued_dispatch_result(
                    target,
                    dispatch,
                    was_created=False,
                    phase="alignment",
                    alignment_ordinal=(
                        int(dispatch["alignmentOrdinal"])
                        if dispatch.get("alignmentOrdinal") is not None
                        else None
                    ),
                )
            )
        candidate_root_id = f"room-root:{_message_identity(room_id, client_message_id)}"
        resumed = root_id != candidate_root_id
        dispatch_results: list[dict[str, object]] = []
        route_decisions: list[dict[str, object]] = []
        if resumed and alignment_dispatches:
            alignment = alignment_dispatches[0]
            target = self.rooms.participant(
                str(alignment["targetParticipantId"])
            )
            resume_identity = replay_identity
            resume_id = (
                "room-dispatch:"
                + _stable_digest(
                    resume_identity,
                    "resume",
                    str(target["id"]),
                    "0",
                )
            )
            try:
                resume_dispatch = self.kernel.dispatch(resume_id)
            except KeyError:
                resume_dispatch = None
            if resume_dispatch is not None:
                dispatch_results.append(
                    _queued_dispatch_result(
                        target,
                        resume_dispatch,
                        was_created=False,
                        phase="resume",
                    )
                )
            route_decisions.append(
                {
                    "routingPolicy": "resume_wait",
                    "reason": "用户回答澄清问题",
                    "targetParticipantId": str(target["id"]),
                    "phase": "resume",
                    "rootId": root_id,
                    "taskId": task_id,
                    "dispatchId": resume_id,
                }
            )
        else:
            route_decisions = [
                {
                    "routingPolicy": "requirement_alignment",
                    "reason": "重复提交已复用原始需求对齐派发",
                    "targetParticipantId": str(
                        dispatch["targetParticipantId"]
                    ),
                    "phase": "alignment",
                    "alignmentOrdinal": int(
                        dispatch.get("alignmentOrdinal") or 0
                    ),
                    "rootId": root_id,
                    "taskId": task_id,
                    "dispatchId": str(dispatch["dispatchId"]),
                }
                for dispatch in alignment_dispatches
            ]
        participant = (
            self.rooms.participant(
                str(
                    (
                        alignment_dispatches[0]
                        if alignment_dispatches
                        else {"targetParticipantId": root["facilitatorParticipantId"]}
                    )["targetParticipantId"]
                )
            )
            if alignment_dispatches
            else self.rooms.participant(str(root["facilitatorParticipantId"]))
        )
        timeline_dispatches = dispatch_results if resumed else alignment_results
        timeline_room = {
            **dict(room),
            "activeTopicId": replay_topic_id,
        }
        timeline_events = self.public_timeline.publish_ingress(
            room=timeline_room,
            post=post,
            client_message_id=client_message_id,
            route_decisions=route_decisions,
            dispatches=timeline_dispatches,
            answer_to_post_id=answer_to_post_id,
            answer_display_text=answer_display_text,
            answer_kind=answer_kind,
        )
        self.projection.sync_room(
            room_id,
            now_ms=int(post.get("createdAtMs") or self.clock_ms()),
        )
        if timeline_events and timeline_dispatches:
            self.wake_worker()
        return {
            "schemaVersion": "rag-ime.agent-room-message.v1",
            "ok": True,
            "accepted": True,
            "resumed": resumed,
            "idempotentReplay": True,
            "status": "queued",
            "executionOwner": "kernel",
            "roomId": room_id,
            "roomTurnId": root_id,
            "rootId": root_id,
            "taskId": task_id,
            "clientMessageId": client_message_id,
            "participant": participant,
            "participants": [participant],
            "routeDecision": route_decisions[0] if route_decisions else {},
            "routeDecisions": route_decisions,
            "dispatches": dispatch_results,
            "alignmentDispatches": alignment_results,
            "topicId": replay_topic_id,
            "sessionTurnId": "",
            "post": dict(post),
            "timelineEvents": timeline_events,
        }

    def durable_message_post(
        self,
        room_id: str,
        *,
        client_message_id: str,
    ) -> dict[str, object] | None:
        """Return the durable user Post that proves local Room acceptance."""

        identity = _message_identity(room_id, client_message_id)
        return self.context.post_by_idempotency(
            room_id=room_id,
            idempotency_key=f"user-message:{identity}",
        )

    def replay_durable_message(
        self,
        room_id: str,
        *,
        client_message_id: str,
        expected_answer_to_post_id: str = "",
        expected_answer_to_root_id: str = "",
        expected_answer_kind: str = "",
    ) -> dict[str, object] | None:
        """Finish public projection for one already-durable Room message."""

        post = self.durable_message_post(
            room_id,
            client_message_id=client_message_id,
        )
        if post is None:
            return None
        return self._replay_post_response(
            room_id,
            client_message_id=client_message_id,
            post=post,
            expected_answer_to_post_id=expected_answer_to_post_id,
            expected_answer_to_root_id=expected_answer_to_root_id,
            expected_answer_kind=expected_answer_kind,
        )

    def resume_durable_answer(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        answer_to_post_id: str,
        answer_to_root_id: str,
        answer_kind: str,
        attachment_ids: Sequence[str],
    ) -> dict[str, object] | None:
        """Recover one staged answer under the ordinary Room entry gate."""

        room = self.rooms.get(room_id)
        self.restore_participant_sessions(room)
        room = self.rooms.get(room_id)
        active_session_ids = [
            str(value["sessionId"])
            for value in room.get("participants", [])
            if (
                isinstance(value, Mapping)
                and value.get("status") == "active"
                and str(value.get("sessionId") or "").strip()
            )
        ]
        with self.session_mode_gate.claim_room(active_session_ids):
            return self._resume_durable_answer_claimed(
                room_id,
                message=message,
                client_message_id=client_message_id,
                answer_to_post_id=answer_to_post_id,
                answer_to_root_id=answer_to_root_id,
                answer_kind=answer_kind,
                attachment_ids=attachment_ids,
            )

    def _resume_durable_answer_claimed(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        answer_to_post_id: str,
        answer_to_root_id: str,
        answer_kind: str,
        attachment_ids: Sequence[str],
    ) -> dict[str, object] | None:
        """Recover a staged answer without releasing work before it is public."""

        post = self.durable_message_post(
            room_id,
            client_message_id=client_message_id,
        )
        if post is None:
            return None
        identity = _message_identity(room_id, client_message_id)
        anchor_id = f"requirement-anchor:{identity}"
        anchor = self.requirements.anchor(anchor_id)
        provenance = anchor.get("provenance")
        if not isinstance(provenance, Mapping):
            raise RoomKernelFenceError(
                "durable clarification answer has no provenance"
            )
        normalized_answer_kind = str(
            provenance.get("answerKind") or ""
        )
        prepared_topic_id = str(provenance.get("topicId") or "")
        answer_display_text = str(
            provenance.get("answerDisplayText") or ""
        )
        if (
            str(anchor.get("rootId") or "") != answer_to_root_id
            or str(post.get("rootId") or "") != answer_to_root_id
            or str(provenance.get("roomId") or "") != room_id
            or str(provenance.get("clientMessageId") or "")
            != client_message_id
            or str(provenance.get("questionPostId") or "")
            != answer_to_post_id
            or str(provenance.get("answerValue") or "") != message
            or str(post.get("content") or "") != answer_display_text
            or normalized_answer_kind not in {"option", "custom"}
            or (
                answer_kind
                and normalized_answer_kind != answer_kind
            )
        ):
            raise RoomKernelFenceError(
                "durable clarification answer provenance does not match its retry"
            )
        pending = self.kernel.pending_user_wait(
            room_id,
            root_id=answer_to_root_id,
            question_post_id=answer_to_post_id,
        )
        if pending is None:
            return self._replay_post_response(
                room_id,
                client_message_id=client_message_id,
                post=post,
                expected_answer_to_post_id=answer_to_post_id,
                expected_answer_to_root_id=answer_to_root_id,
                expected_answer_kind=answer_kind,
            )
        requirement_catalog = self.requirements.catalog_revision(
            f"requirement-catalog:{_stable_digest(answer_to_root_id, identity, 'answer-catalog')}"
        )
        if str(pending.get("state") or "") == "resumed":
            replayed = self._replay_post_response(
                room_id,
                client_message_id=client_message_id,
                post=post,
                expected_answer_to_post_id=answer_to_post_id,
                expected_answer_to_root_id=answer_to_root_id,
                expected_answer_kind=answer_kind,
            )
            pending_payload = pending.get("payload")
            if not isinstance(pending_payload, Mapping):
                raise RoomKernelFenceError(
                    "resumed clarification answer lost its continuation payload"
                )
            resume_dispatch_id = str(
                pending_payload.get("resumeDispatchId") or ""
            )
            resume_receipt_id = str(
                pending_payload.get("resumeReceiptId") or ""
            )
            replayed_dispatches = replayed.get("dispatches")
            if (
                not resume_dispatch_id
                or not resume_receipt_id
                or not isinstance(replayed_dispatches, list)
                or len(replayed_dispatches) != 1
                or str(replayed_dispatches[0].get("dispatchId") or "")
                != resume_dispatch_id
            ):
                raise RoomKernelFenceError(
                    "resumed clarification answer lost its authoritative Dispatch"
                )
            replayed.update(
                {
                    "requirementAnchor": dict(anchor),
                    "requirementCatalog": requirement_catalog,
                    "resumeReceipt": self.kernel.receipt(
                        resume_receipt_id
                    ),
                    "continuationId": str(pending["continuationId"]),
                }
            )
            return replayed
        participant_id = str(pending["targetParticipantId"])
        target = self.rooms.participant(participant_id)
        if (
            target.get("roomId") != room_id
            or target.get("status") != "active"
        ):
            raise RoomKernelFenceError(
                "pending user wait participant is no longer active"
            )
        resume_dispatch = self._prepared_answer_dispatch(
            identity=identity,
            pending=pending,
            post_id=str(post["postId"]),
            target=target,
            attachment_ids=attachment_ids,
        )
        return self._release_prepared_user_answer(
            room=self.rooms.get(room_id),
            pending=pending,
            target=target,
            user_post=post,
            answer_anchor=anchor,
            requirement_catalog=requirement_catalog,
            client_message_id=client_message_id,
            answer_display_text=answer_display_text,
            normalized_answer_kind=normalized_answer_kind,
            resume_dispatch=resume_dispatch,
            topic_id=prepared_topic_id,
        )

    def _prepared_answer_dispatch(
        self,
        *,
        identity: str,
        pending: Mapping[str, object],
        post_id: str,
        target: Mapping[str, object],
        attachment_ids: Sequence[str],
    ) -> dict[str, object]:
        target_session_id = str(target["sessionId"])
        resume_dispatch = self._dispatch_envelope(
            identity=identity,
            root_id=str(pending["rootId"]),
            task_id=str(pending["taskId"]),
            post_id=post_id,
            target=target,
            ordinal=0,
            intent_kind="resume",
            capability_epoch=self._next_capability_epoch(target_session_id),
            depends_on_dispatch_ids=[],
            alignment_ordinal=None,
            attachment_ids=attachment_ids,
        )
        resume_dispatch.update(
            {
                "parentDispatchId": str(pending["parentDispatchId"]),
                "generation": int(pending["generation"]),
                "hopCount": int(pending.get("parentHopCount") or 0) + 1,
                "depth": int(pending.get("parentDepth") or 0),
            }
        )
        return resume_dispatch

    def _release_prepared_user_answer(
        self,
        *,
        room: Mapping[str, object],
        pending: Mapping[str, object],
        target: Mapping[str, object],
        user_post: Mapping[str, object],
        answer_anchor: Mapping[str, object],
        requirement_catalog: Mapping[str, object],
        client_message_id: str,
        answer_display_text: str,
        normalized_answer_kind: str,
        resume_dispatch: Mapping[str, object],
        topic_id: str,
    ) -> dict[str, object]:
        room_id = str(user_post["roomId"])
        root_id = str(pending["rootId"])
        task_id = str(pending["taskId"])
        question_post_id = str(pending["questionPostId"])
        timestamp = int(user_post["createdAtMs"])
        timeline_room = {
            **dict(room),
            "activeTopicId": str(topic_id or ""),
        }
        authorization_events = self.public_timeline.publish_ingress(
            room=timeline_room,
            post=user_post,
            client_message_id=client_message_id,
            route_decisions=[],
            dispatches=[],
            answer_to_post_id=question_post_id,
            answer_display_text=answer_display_text,
            answer_kind=normalized_answer_kind,
        )
        transaction = sqlite3.connect(self.kernel.db_path, timeout=10)
        transaction.row_factory = sqlite3.Row
        try:
            transaction.execute("PRAGMA foreign_keys = ON")
            transaction.execute("BEGIN IMMEDIATE")
            resumed = self.kernel.resume_user_wait_after_public_in_transaction(
                transaction,
                continuation_id=str(pending["continuationId"]),
                dispatch_payload=resume_dispatch,
                question_post_id=question_post_id,
                answer_root_id=root_id,
                answer_post=user_post,
                answer_anchor_id=str(answer_anchor["anchorId"]),
                client_message_id=client_message_id,
                answer_display_text=answer_display_text,
                answer_kind=normalized_answer_kind,
                topic_id=str(topic_id or ""),
                now_ms=timestamp,
            )
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        finally:
            transaction.close()
        dispatch = resumed["dispatch"]
        dispatch_result = _queued_dispatch_result(
            target,
            dispatch,
            was_created=True,
            phase="resume",
        )
        route_decision = {
            "routingPolicy": "resume_wait",
            "reason": "用户回答澄清问题",
            "targetParticipantId": str(target["id"]),
            "phase": "resume",
            "rootId": root_id,
            "taskId": task_id,
            "dispatchId": dispatch["dispatchId"],
        }
        try:
            route_events = self.public_timeline.publish_ingress(
                room=timeline_room,
                post=user_post,
                client_message_id=client_message_id,
                route_decisions=[route_decision],
                dispatches=[dispatch_result],
                answer_to_post_id=question_post_id,
                answer_display_text=answer_display_text,
                answer_kind=normalized_answer_kind,
            )
        finally:
            self.wake_worker()
        self.projection.sync_room(room_id, now_ms=timestamp)
        return {
            "schemaVersion": "rag-ime.agent-room-message.v1",
            "ok": True,
            "accepted": True,
            "resumed": True,
            "status": "queued",
            "executionOwner": "kernel",
            "roomId": room_id,
            "roomTurnId": root_id,
            "rootId": root_id,
            "taskId": task_id,
            "clientMessageId": client_message_id,
            "participant": target,
            "participants": [target],
            "routeDecision": route_decision,
            "routeDecisions": [route_decision],
            "dispatches": [dispatch_result],
            "alignmentDispatches": [],
            "topicId": str(topic_id or ""),
            "sessionTurnId": "",
            "post": dict(user_post),
            "requirementAnchor": dict(answer_anchor),
            "requirementCatalog": dict(requirement_catalog),
            "timelineEvents": [*authorization_events, *route_events],
            "resumeReceipt": resumed["receipt"],
            "continuationId": str(pending["continuationId"]),
        }

    def _resume_pending_user_wait(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        attachment_ids: Sequence[str],
        pending: Mapping[str, object],
        answer_kind: str,
    ) -> dict[str, object]:
        """Append one answer and resume the waiting participant once."""

        root_id = str(pending["rootId"])
        task_id = str(pending["taskId"])
        parent_dispatch_id = str(pending["parentDispatchId"])
        participant_id = str(pending["targetParticipantId"])
        room = self.rooms.get(room_id)
        target = self.rooms.participant(participant_id)
        if (
            target.get("roomId") != room_id
            or target.get("status") != "active"
        ):
            raise RoomKernelFenceError(
                "pending user wait participant is no longer active"
            )
        identity = _message_identity(room_id, client_message_id)
        anchor_id = f"requirement-anchor:{identity}"
        post_id = f"room-post:user:{identity}"
        timestamp = self.clock_ms()
        pending_payload = pending.get("payload")
        question_options = (
            pending_payload.get("questionOptions")
            if isinstance(pending_payload, Mapping)
            else []
        )
        answer_display_text, normalized_answer_kind = (
            _resolve_room_answer_display(
                message,
                answer_kind=answer_kind,
                question_options=question_options,
            )
        )
        context = self.requirements.dispatch_context(parent_dispatch_id)
        binding = context.get("binding") if isinstance(context, Mapping) else {}
        current_catalog_id = str(
            binding.get("catalogRevisionId") or ""
            if isinstance(binding, Mapping)
            else ""
        )
        if not current_catalog_id and isinstance(context, Mapping):
            catalog_value = context.get("catalog")
            if isinstance(catalog_value, Mapping):
                current_catalog_id = str(
                    catalog_value.get("catalogRevisionId") or ""
                )
        if not current_catalog_id:
            raise RoomKernelFenceError(
                "pending user wait has no RequirementCatalog"
            )
        current_catalog = self.requirements.catalog_revision(current_catalog_id)
        answer_item_id = (
            f"requirement:{_stable_digest(root_id, identity, 'answer')}"
        )
        answer_anchor_provenance = {
            "surface": "room",
            "roomId": room_id,
            "topicId": str(room.get("activeTopicId") or ""),
            "clientMessageId": client_message_id,
            "answerToContinuationId": str(pending["continuationId"]),
            "questionPostId": str(pending["questionPostId"]),
            "answerValue": message,
            "answerDisplayText": answer_display_text,
            "answerKind": normalized_answer_kind,
        }
        answer_item = {
            "itemId": answer_item_id,
            "kind": "explicit_user_requirement",
            "statement": answer_display_text,
            "origin": "room_user_answer",
            "state": "active",
            "sourceSpans": [
                {
                    "anchorId": anchor_id,
                    "startByte": 0,
                    "endByte": len(answer_display_text.encode("utf-8")),
                }
            ],
            "confirmation": "captured_from_user",
        }
        answer_catalog_id = (
            f"requirement-catalog:{_stable_digest(root_id, identity, 'answer-catalog')}"
        )
        user_post = {
            "schemaVersion": ROOM_POST_SCHEMA_VERSION,
            "postId": post_id,
            "roomId": room_id,
            "rootId": root_id,
            "generation": int(pending["generation"]),
            "taskId": task_id,
            "authorActorRef": "user:local",
            "kind": "request",
            "visibility": "room",
            "content": answer_display_text,
            "idempotencyKey": f"user-message:{identity}",
            "publicationSource": {
                "kind": "user",
                "ref": client_message_id or root_id,
            },
            "createdAtMs": timestamp,
        }
        resume_dispatch = self._prepared_answer_dispatch(
            identity=identity,
            pending=pending,
            post_id=post_id,
            target=target,
            attachment_ids=attachment_ids,
        )
        transaction = sqlite3.connect(self.kernel.db_path, timeout=10)
        transaction.row_factory = sqlite3.Row
        try:
            transaction.execute("PRAGMA foreign_keys = ON")
            transaction.execute("BEGIN IMMEDIATE")
            prior_preparation = (
                self.kernel.user_wait_answer_preparation_in_transaction(
                    transaction,
                    root_id=root_id,
                    continuation_id=str(pending["continuationId"]),
                )
            )
            if prior_preparation is not None:
                raise RoomKernelFenceError(
                    "user wait already has a different prepared answer"
                )
            answer_anchor, _ = self.requirements.append_anchor_in_transaction(
                transaction,
                anchor_id=anchor_id,
                root_id=root_id,
                original_content=answer_display_text,
                created_by="user:local",
                provenance=answer_anchor_provenance,
                created_at_ms=timestamp,
            )
            requirement_catalog, _ = (
                self.requirements.revise_catalog_in_transaction(
                    transaction,
                    catalog_revision_id=answer_catalog_id,
                    root_id=root_id,
                    expected_current_revision=int(current_catalog["revision"]),
                    anchor_refs=[
                        *[
                            str(value)
                            for value in current_catalog.get("anchorRefs", [])
                        ],
                        anchor_id,
                    ],
                    items=[
                        *[
                            dict(item)
                            for item in current_catalog.get("items", [])
                            if isinstance(item, Mapping)
                        ],
                        answer_item,
                    ],
                    acceptance_criteria=[
                        dict(item)
                        for item in current_catalog.get(
                            "acceptanceCriteria",
                            [],
                        )
                        if isinstance(item, Mapping)
                    ],
                    change_reason="用户回答澄清问题并恢复原对齐任务",
                    provenance={
                        "surface": "room",
                        "answerAnchorId": anchor_id,
                        "continuationId": str(pending["continuationId"]),
                    },
                    created_by="room-ingress",
                    created_at_ms=timestamp,
                )
            )
            self.projection.publish_post_in_transaction(
                transaction,
                user_post,
            )
            self.context.publish_post_in_transaction(
                transaction,
                user_post,
            )
            self.context.append_entry_in_transaction(
                transaction,
                root_id=root_id,
                room_id=room_id,
                generation=int(pending["generation"]),
                entry_kind="requirement_anchor",
                source_ref=anchor_id,
                dedupe_key=f"requirement-anchor:{anchor_id}",
                content=answer_display_text,
                created_at_ms=timestamp,
            )
            self.kernel.prepare_user_wait_answer_in_transaction(
                transaction,
                continuation_id=str(pending["continuationId"]),
                dispatch_payload=resume_dispatch,
                question_post_id=str(pending["questionPostId"]),
                answer_root_id=root_id,
                answer_post_id=post_id,
                answer_anchor_id=anchor_id,
                client_message_id=client_message_id,
                answer_display_text=answer_display_text,
                answer_kind=normalized_answer_kind,
                topic_id=str(room.get("activeTopicId") or ""),
                now_ms=timestamp,
            )
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        finally:
            transaction.close()
        return self._release_prepared_user_answer(
            room=room,
            pending=pending,
            target=target,
            user_post=user_post,
            answer_anchor=answer_anchor,
            requirement_catalog=requirement_catalog,
            client_message_id=client_message_id,
            answer_display_text=answer_display_text,
            normalized_answer_kind=normalized_answer_kind,
            resume_dispatch=resume_dispatch,
            topic_id=str(room.get("activeTopicId") or ""),
        )


    def _post_message_claimed(
        self,
        room_id: str,
        *,
        message: str,
        client_message_id: str,
        requested_participant_ids: Sequence[str],
        work_item_id: str,
        attachment_ids: Sequence[str],
        answer_to_post_id: str,
        answer_to_root_id: str,
        answer_kind: str,
    ) -> dict[str, object]:
        if not kernel_owns_room_execution(self.kernel.mode):
            raise RoomKernelFenceError("canonical Room ingress requires a managed Kernel")

        room = self.rooms.get(room_id)
        self.restore_participant_sessions(room)
        room = self.rooms.get(room_id)
        replay_post = self.durable_message_post(
            room_id,
            client_message_id=client_message_id,
        )
        if replay_post is not None:
            if answer_to_post_id:
                recovered_answer = self._resume_durable_answer_claimed(
                    room_id,
                    message=message,
                    client_message_id=client_message_id,
                    answer_to_post_id=answer_to_post_id,
                    answer_to_root_id=answer_to_root_id,
                    answer_kind=answer_kind,
                    attachment_ids=attachment_ids,
                )
                if recovered_answer is None:
                    raise RoomKernelFenceError(
                        "durable clarification answer disappeared during recovery"
                    )
                return recovered_answer
            return self._replay_post_response(
                room_id,
                client_message_id=client_message_id,
                post=replay_post,
            )
        if answer_to_post_id or answer_to_root_id:
            if not answer_to_post_id or not answer_to_root_id:
                raise ValueError(
                    "Room clarification answers require question and Root identity"
                )
            if str(work_item_id or "").strip():
                raise ValueError(
                    "Room clarification answers cannot be rebound to a WorkItem"
                )
            pending_user_wait = self.kernel.pending_user_wait(
                room_id,
                root_id=answer_to_root_id,
                question_post_id=answer_to_post_id,
            )
            if pending_user_wait is None:
                raise RoomKernelFenceError(
                    "clarification answer does not match an active question and Root"
                )
            return self._resume_pending_user_wait(
                room_id,
                message=message,
                client_message_id=client_message_id,
                requested_participant_ids=requested_participant_ids,
                attachment_ids=attachment_ids,
                pending=pending_user_wait,
                answer_kind=answer_kind,
            )
        timestamp = self.clock_ms()
        identity = _message_identity(room_id, client_message_id)
        root_id = f"room-root:{identity}"
        task_id = f"room-task:{identity}"
        anchor_id = f"requirement-anchor:{identity}"
        post_id = f"room-post:user:{identity}"
        managed_work = bool(str(work_item_id or "").strip())
        work_item: dict[str, object] | None = None
        authoritative_participant_id = ""
        if managed_work:
            work_item, authoritative_participant_id = self._work_item_owner(
                room_id,
                work_item_id,
            )
        active_participants = [
            value
            for value in room.get("participants", [])
            if isinstance(value, Mapping) and value.get("status") == "active"
        ]
        if not active_participants:
            raise RoomKernelFenceError(
                "managed Room execution requires an active participant"
            )
        preferred_facilitator = _opening_facilitator(
            room,
            active_participants,
            requested_participant_ids=requested_participant_ids,
            managed_work=managed_work,
        )
        requested_participant_ids = (
            (authoritative_participant_id,)
            if managed_work and authoritative_participant_id
            else (preferred_facilitator,)
        )
        decisions = self.rooms.plan_routes(
            room_id,
            message,
            requested_participant_ids=requested_participant_ids,
            profiles=self._routing_profiles(room),
            authoritative_participant_id=authoritative_participant_id,
            conversation_only=not managed_work,
        )
        targets = [
            self.rooms.participant(str(decision["targetParticipantId"]))
            for decision in decisions
        ]
        if not targets:
            raise RoomKernelFenceError(
                "managed Room execution requires an active response participant"
            )
        alignment_targets = [
            self.rooms.participant(preferred_facilitator)
        ]
        attachment_receipts = self.resolve_attachments(
            room_id,
            [str(target["sessionId"]) for target in targets],
            attachment_ids,
        )
        if work_item is not None:
            for decision in decisions:
                decision["workItemId"] = work_item_id
                decision["workItemState"] = str(work_item["state"])
        facilitator_participant_id = preferred_facilitator
        task_owner_participant_id = str(targets[0]["id"])
        requirement_item_id = (
            f"work-item:{work_item['id']}:revision:{work_item['revision']}"
            if work_item is not None
            else f"requirement:{identity}"
        )
        task_objective = (
            str(work_item.get("objective") or "").strip()
            if work_item is not None
            else message
        )
        task_expected_output = (
            str(work_item.get("expectedOutput") or "").strip()
            if work_item is not None
            else ""
        )
        if not task_expected_output:
            task_expected_output = (
                "以可验证的 Room Post、结构化交接、等待或阻塞之一完成本轮任务。"
            )
        work_acceptance_criteria = _work_item_acceptance_criteria(
            identity,
            work_item,
        )
        alignment_acceptance_criteria = _alignment_acceptance_criteria(
            identity,
            alignment_targets,
        )
        acceptance_criteria = (
            *work_acceptance_criteria,
            *alignment_acceptance_criteria,
        )
        work_acceptance_ids = tuple(
            criterion_id
            for criterion_id, _statement in work_acceptance_criteria
        )
        acceptance_ids = tuple(
            criterion_id for criterion_id, _statement in acceptance_criteria
        )
        # Roster composition is not review policy.  A later explicit Reviewer
        # handoff records the authoritative policy receipt and flips this flag.
        independent_review_required = False
        original_digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
        anchor_ref = f"{anchor_id}@sha256:{original_digest}"
        root = {
            "schemaVersion": ROOT_EXECUTION_SCHEMA_VERSION,
            "rootId": root_id,
            "roomId": room_id,
            "generation": 0,
            "state": "running",
            "facilitatorParticipantId": facilitator_participant_id,
            "reporterParticipantId": facilitator_participant_id,
            "reporterSelectionReceiptId": None,
            "requirementAnchorRef": anchor_ref,
            "createdByActorRef": "user:local",
            "terminalReceiptId": None,
            "activeProfileRef": "standard-room",
            "budgetPolicyRef": "room-budget:interactive-v1",
            "independentReviewRequired": independent_review_required,
            "createdAtMs": timestamp,
        }
        base_task = {
            "schemaVersion": ROOM_TASK_SCHEMA_VERSION,
            "taskId": task_id,
            "rootId": root_id,
            "parentTaskId": None,
            "taskKind": "work",
            "currentOwnerParticipantId": task_owner_participant_id,
            "ownershipRevision": 0,
            "ownershipReceiptId": None,
            "invitationId": None,
            "reviewState": "not_required",
            "reviewOfTaskIds": [],
            "reviewAuthorParticipantIds": [],
            "contextEvidenceRefs": [],
            "objective": task_objective,
            "expectedOutput": task_expected_output,
            "requirementItemIds": [requirement_item_id],
            "acceptanceCriterionIds": [
                criterion_id
                for criterion_id, _statement in (
                    alignment_acceptance_criteria
                    if not managed_work
                    else work_acceptance_criteria
                )
            ],
            "revision": 0,
            "state": "active",
        }
        if managed_work:
            base_task["workItemId"] = work_item_id
        else:
            # An ordinary user message uses this base Task as the alignment
            # Task itself. Keep the same conditional define/wait contract as
            # managed-work alignment children so the two ingress paths cannot
            # drift into different product behavior.
            base_task = _alignment_task(
                base_task,
                task_id=task_id,
                target=alignment_targets[0],
                message=message,
                criterion_id=alignment_acceptance_criteria[0][0],
                ordinal=0,
                total=len(alignment_targets),
            )
        task = base_task
        created = self.commands.create_root_task(
            root,
            task,
            budget=DEFAULT_ROOT_BUDGET,
            max_hops=DEFAULT_MAX_HOPS,
            max_depth=DEFAULT_MAX_DEPTH,
            acceptance_criteria=acceptance_ids,
            now_ms=timestamp,
        )
        target_task_ids = [task_id]
        alignment_task_ids: list[str] = []
        if not managed_work:
            alignment_task_ids.append(task_id)
        else:
            for ordinal, (
                target,
                (criterion_id, _statement),
            ) in enumerate(
                zip(
                    alignment_targets,
                    alignment_acceptance_criteria,
                    strict=True,
                )
            ):
                alignment_task_id = f"{task_id}:alignment:{ordinal}"
                self.commands.create_task(
                    _alignment_task(
                        base_task,
                        task_id=alignment_task_id,
                        target=target,
                        message=message,
                        criterion_id=criterion_id,
                        ordinal=ordinal,
                        total=len(alignment_targets),
                    ),
                    now_ms=timestamp,
                )
                alignment_task_ids.append(alignment_task_id)

        work_claimed = False
        timeline_events: list[dict[str, object]] = []
        previous_accepted_turn_id = ""
        try:
            anchor, _ = self.requirements.append_anchor(
                anchor_id=anchor_id,
                root_id=root_id,
                original_content=message,
                created_by="user:local",
                provenance={
                    "surface": "room",
                    "roomId": room_id,
                    "clientMessageId": client_message_id,
                },
                created_at_ms=timestamp,
            )
            requirement_catalog, _ = self.requirements.revise_catalog(
                catalog_revision_id=(
                    f"requirement-catalog:{identity}:1"
                ),
                root_id=root_id,
                expected_current_revision=0,
                anchor_refs=[anchor_id],
                items=[
                    {
                        "itemId": requirement_item_id,
                        "kind": "explicit_user_requirement",
                        "statement": message,
                        "origin": "room_user_message",
                        "state": "active",
                        "sourceSpans": [
                            {
                                "anchorId": anchor_id,
                                "startByte": 0,
                                "endByte": len(
                                    message.encode("utf-8")
                                ),
                            }
                        ],
                        "confirmation": "captured_from_user",
                    }
                ],
                acceptance_criteria=[
                    {
                        "criterionId": criterion_id,
                        "itemId": requirement_item_id,
                        "acceptanceCriterionFullNameZh": (
                            f"用户验收条件 {ordinal + 1}"
                        ),
                        "criterionKind": "user_journey",
                        "expectedReceiptTypes": ["evidence"],
                        "statement": statement,
                    }
                    for ordinal, (
                        criterion_id,
                        statement,
                    ) in enumerate(
                        work_acceptance_criteria
                        if managed_work
                        else alignment_acceptance_criteria
                    )
                ],
                change_reason="从本次 Room 用户请求建立初始需求目录",
                provenance={
                    "surface": "room",
                    "clientMessageId": client_message_id,
                    "derivedCatalog": True,
                    "originalBytesRemainInAnchor": True,
                },
                created_by="room-ingress",
                created_at_ms=timestamp,
            )
            self.context.append_entry(
                root_id=root_id,
                room_id=room_id,
                generation=0,
                entry_kind="requirement_anchor",
                source_ref=anchor_id,
                dedupe_key=f"requirement-anchor:{anchor_id}",
                content=message,
                created_at_ms=timestamp,
            )
            if work_item is not None:
                self.context.append_entry(
                    root_id=root_id,
                    room_id=room_id,
                    generation=0,
                    entry_kind="work_item",
                    source_ref=str(work_item["id"]),
                    dedupe_key=(
                        f"work-item:{work_item['id']}:revision:"
                        f"{work_item['revision']}"
                    ),
                    content=_work_item_context(
                        work_item,
                        acceptance_criteria=work_acceptance_criteria,
                    ),
                    created_at_ms=timestamp,
                )
            user_post = {
                "schemaVersion": ROOM_POST_SCHEMA_VERSION,
                "postId": post_id,
                "roomId": room_id,
                "rootId": root_id,
                "generation": 0,
                "taskId": task_id,
                "authorActorRef": "user:local",
                "kind": "request",
                "visibility": "room",
                "content": message,
                "idempotencyKey": f"user-message:{identity}",
                "publicationSource": {
                    "kind": "user",
                    "ref": client_message_id or root_id,
                },
                "createdAtMs": timestamp,
            }
            if attachment_receipts:
                user_post["attachments"] = attachment_receipts
            self.projection.publish_post(user_post)
            self.context.publish_post(user_post)

            if work_item is not None:
                previous_accepted_turn_id = str(
                    work_item.get("acceptedTurnId") or ""
                )
                work_item = self.work_items.claim_dispatch(
                    str(work_item["id"]),
                    room_id=room_id,
                    owner_participant_id=str(targets[0]["id"]),
                    assignment_key=str(work_item["assignmentKey"]),
                    previous_accepted_turn_id=previous_accepted_turn_id,
                    room_turn_id=root_id,
                )
                work_claimed = True

            next_epoch_by_session = {
                str(target["sessionId"]): self._next_capability_epoch(
                    str(target["sessionId"])
                )
                for target in (*alignment_targets, *targets)
            }
            alignment_envelopes: list[dict[str, object]] = []
            alignment_decisions: list[dict[str, object]] = []
            for ordinal, (target, alignment_task_id) in enumerate(
                zip(
                    alignment_targets,
                    alignment_task_ids,
                    strict=True,
                )
            ):
                session_id = str(target["sessionId"])
                envelope = self._dispatch_envelope(
                    identity=identity,
                    root_id=root_id,
                    task_id=alignment_task_id,
                    post_id=post_id,
                    target=target,
                    ordinal=ordinal,
                    intent_kind="align",
                    capability_epoch=next_epoch_by_session[session_id],
                    depends_on_dispatch_ids=[],
                    alignment_ordinal=ordinal,
                    attachment_ids=attachment_ids,
                )
                next_epoch_by_session[session_id] += 1
                alignment_envelopes.append(envelope)
                alignment_decisions.append(
                    {
                        "routingPolicy": "requirement_alignment",
                        "reason": (
                            f"需求对齐并行确认 {ordinal + 1}/"
                            f"{len(alignment_targets)}"
                        ),
                        "targetParticipantId": target["id"],
                        "phase": "alignment",
                        "alignmentOrdinal": ordinal,
                    }
                )
            alignment_dispatch_ids = [
                str(envelope["dispatchId"])
                for envelope in alignment_envelopes
            ]
            execution_envelopes: list[dict[str, object]] = []
            if managed_work:
                for ordinal, (target, target_task_id) in enumerate(
                    zip(targets, target_task_ids, strict=True)
                ):
                    session_id = str(target["sessionId"])
                    envelope = self._dispatch_envelope(
                        identity=identity,
                        root_id=root_id,
                        task_id=target_task_id,
                        post_id=post_id,
                        target=target,
                        ordinal=ordinal,
                        intent_kind="execute",
                        capability_epoch=next_epoch_by_session[session_id],
                        depends_on_dispatch_ids=alignment_dispatch_ids,
                        alignment_ordinal=None,
                        attachment_ids=attachment_ids,
                    )
                    next_epoch_by_session[session_id] += 1
                    execution_envelopes.append(envelope)
                    decisions[ordinal]["phase"] = "execution"
            envelopes = [*alignment_envelopes, *execution_envelopes]
            queued = self.commands.dispatch_many(
                envelopes,
                now_ms=timestamp,
            )
            alignment_queued = queued[: len(alignment_envelopes)]
            execution_queued = queued[len(alignment_envelopes) :]
            alignment_dispatch_results: list[dict[str, object]] = []
            for decision, target, target_task_id, (
                dispatch,
                was_created,
            ) in zip(
                alignment_decisions,
                alignment_targets,
                alignment_task_ids,
                alignment_queued,
                strict=True,
            ):
                decision.update(
                    rootId=root_id,
                    taskId=target_task_id,
                    dispatchId=dispatch["dispatchId"],
                    targetSessionId=target["sessionId"],
                    dependsOnDispatchIds=list(
                        dispatch.get("dependsOnDispatchIds") or []
                    ),
                )
                alignment_dispatch_results.append(
                    _queued_dispatch_result(
                        target,
                        dispatch,
                        was_created=was_created,
                        phase="alignment",
                        alignment_ordinal=int(
                            dispatch["alignmentOrdinal"]
                        ),
                    )
                )
            execution_dispatch_results: list[dict[str, object]] = []
            if managed_work:
                for decision, target, target_task_id, (
                    dispatch,
                    was_created,
                ) in zip(
                    decisions,
                    targets,
                    target_task_ids,
                    execution_queued,
                    strict=True,
                ):
                    decision.update(
                        rootId=root_id,
                        taskId=target_task_id,
                        dispatchId=dispatch["dispatchId"],
                        targetSessionId=target["sessionId"],
                        dependsOnDispatchIds=list(
                            dispatch.get("dependsOnDispatchIds") or []
                        ),
                    )
                    self.rooms.commit_route(
                        room_id,
                        decision,
                        updated_at_ms=timestamp,
                    )
                    execution_dispatch_results.append(
                        _queued_dispatch_result(
                            target,
                            dispatch,
                            was_created=was_created,
                            phase="execution",
                        )
                    )
            all_dispatch_results = [
                *alignment_dispatch_results,
                *execution_dispatch_results,
            ]
            public_route_decisions = (
                [*alignment_decisions, *decisions]
                if managed_work
                else alignment_decisions
            )
            timeline_events = self.public_timeline.publish_ingress(
                room=room,
                post=user_post,
                client_message_id=client_message_id,
                route_decisions=public_route_decisions,
                dispatches=all_dispatch_results,
            )
        except Exception as exc:
            if work_claimed and work_item is not None:
                try:
                    work_item = self.work_items.fail_dispatch(
                        str(work_item["id"]),
                        room_id=room_id,
                        actor_participant_id=str(targets[0]["id"]),
                        room_turn_id=root_id,
                        previous_accepted_turn_id=previous_accepted_turn_id,
                        reason=_public_error(exc),
                    )
                except Exception:
                    pass
            try:
                self.commands.cancel_root(root_id)
            except Exception:
                pass
            raise

        self.projection.sync_room(room_id, now_ms=timestamp)
        self.wake_worker()
        primary = 0
        response: dict[str, object] = {
            "schemaVersion": "rag-ime.agent-room-message.v1",
            "ok": True,
            "accepted": True,
            "status": "queued",
            "executionOwner": "kernel",
            "roomId": room_id,
            "roomTurnId": root_id,
            "rootId": root_id,
            "taskId": task_id,
            "clientMessageId": client_message_id,
            "participant": targets[primary],
            "participants": targets,
            "routeDecision": public_route_decisions[primary],
            "routeDecisions": public_route_decisions,
            "dispatches": execution_dispatch_results,
            "alignmentDispatches": alignment_dispatch_results,
            "topicId": str(room.get("activeTopicId") or ""),
            "sessionTurnId": "",
            "root": created["root"],
            "task": created["task"],
            "post": user_post,
            "requirementAnchor": anchor,
            "requirementCatalog": requirement_catalog,
            "timelineEvents": timeline_events,
        }
        if work_item is not None:
            response["workItem"] = work_item
        return response

    def _work_item_owner(
        self,
        room_id: str,
        work_item_id: str,
    ) -> tuple[dict[str, object] | None, str]:
        if not work_item_id:
            raise RoomKernelFenceError(
                "managed Room execution requires a confirmed WorkItem"
            )
        return self.work_items.authoritative_owner(work_item_id, room_id=room_id)

    def _routing_profiles(
        self,
        room: Mapping[str, object],
    ) -> dict[str, dict[str, object]]:
        profiles: dict[str, dict[str, object]] = {}
        for value in room.get("participants", []):
            if not isinstance(value, Mapping) or value.get("status") != "active":
                continue
            role = self.personas.resolve(
                value.get("roleId"),
                value.get("roleVersion") or "1",
            )
            session = self.sessions.get(str(value["sessionId"]))
            revision_id = str(session.get("roleBookRevisionId") or "")
            profile: Mapping[str, object] = {}
            if revision_id:
                try:
                    profile = self.role_books.routing_profile(
                        role.role_id,
                        role.version,
                        revision_id,
                    )
                except (ValueError, RuntimeError):
                    profile = {}
            capabilities = _texts(profile.get("capabilities"))
            recent_work = _texts(profile.get("recentWork"))
            profiles[str(value["id"])] = {
                "tagline": role.tagline,
                "summary": " ".join(
                    (role.summary, *capabilities[:4], *recent_work[:3])
                ),
                "traits": list(role.traits),
                "routingTags": [
                    *role.traits,
                    *capabilities[:8],
                    *recent_work[:4],
                ],
                # No revision means zero Role Book contribution. Do not inject a
                # warning paragraph merely to explain that nothing was loaded.
                "roleBookRevisionId": revision_id,
            }
        return profiles

    def _assert_targets_available(
        self,
        targets: Sequence[Mapping[str, object]],
    ) -> None:
        session_ids = [str(target["sessionId"]) for target in targets]
        if len(session_ids) != len(set(session_ids)):
            raise RoomKernelFenceError(
                "Room routing produced duplicate participant Sessions"
            )
        for target, session_id in zip(targets, session_ids, strict=True):
            if target.get("status") != "active":
                raise ValueError("selected Room participant is no longer active")
            binding = self.kernel.session_binding(session_id)
            session = self.sessions.get(session_id)
            session_status = str(session.get("status") or "")
            if binding is not None or session_status not in {
                "idle",
                "faulted",
            }:
                raise ValueError(
                    f"{target.get('displayName') or 'selected Room participant'} "
                    "is currently busy"
                )

    def _dispatch_envelope(
        self,
        *,
        identity: str,
        root_id: str,
        task_id: str,
        post_id: str,
        target: Mapping[str, object],
        ordinal: int,
        intent_kind: str,
        capability_epoch: int,
        depends_on_dispatch_ids: Sequence[str],
        alignment_ordinal: int | None,
        attachment_ids: Sequence[str],
    ) -> dict[str, object]:
        participant_id = str(target["id"])
        session_id = str(target["sessionId"])
        dispatch_identity = _stable_digest(
            identity,
            intent_kind,
            participant_id,
            str(ordinal),
        )
        payload: dict[str, object] = {
            "schemaVersion": DISPATCH_ENVELOPE_SCHEMA_VERSION,
            "dispatchId": f"room-dispatch:{dispatch_identity}",
            "rootId": root_id,
            "taskId": task_id,
            "parentDispatchId": None,
            "generation": 0,
            "hopCount": 0,
            "depth": 0,
            "budgetCost": 1,
            "targetSessionId": session_id,
            "targetParticipantId": participant_id,
            "triggerId": post_id,
            "intentKind": intent_kind,
            "idempotencyKey": (
                f"room-message:{identity}:{intent_kind}:{ordinal}:"
                f"participant:{participant_id}"
            ),
            "attempt": 0,
            "capabilityEpoch": capability_epoch,
            "runtimeProfileRevision": (
                f"{DEFAULT_RUNTIME_PROFILE_REVISION}:"
                f"{target.get('roleId')}@{target.get('roleVersion') or '1'}"
            ),
            "dependsOnDispatchIds": list(depends_on_dispatch_ids),
            "attachmentIds": list(attachment_ids),
            "state": "pending",
        }
        if alignment_ordinal is not None:
            payload["alignmentOrdinal"] = alignment_ordinal
        return payload

    def _next_capability_epoch(self, session_id: str) -> int:
        latest = self.capabilities.runtime_binding(session_id, active_only=False)
        if latest is None:
            return 1
        if latest.get("state") in {"active", "prepared"}:
            raise RoomKernelFenceError(
                "Room participant still has an active capability binding"
            )
        # Revocation advances the stored epoch and thereby publishes the next
        # safe generation. Reuse that fenced value rather than incrementing
        # twice and creating unexplained gaps.
        return max(1, int(latest.get("capabilityEpoch") or 0))


def _queued_dispatch_result(
    target: Mapping[str, object],
    dispatch: Mapping[str, object],
    *,
    was_created: bool,
    phase: str,
    alignment_ordinal: int | None = None,
) -> dict[str, object] | None:
    result: dict[str, object] = {
        "participantId": target["id"],
        "sessionId": target["sessionId"],
        "dispatchId": dispatch["dispatchId"],
        "accepted": True,
        "state": "queued",
        "created": was_created,
        "sessionTurnId": "",
        "error": "",
        "phase": phase,
        "dependsOnDispatchIds": list(
            dispatch.get("dependsOnDispatchIds") or []
        ),
    }
    if alignment_ordinal is not None:
        result["alignmentOrdinal"] = alignment_ordinal
    return result


def _message_identity(room_id: str, client_message_id: str) -> str:
    nonce = client_message_id or f"server:{uuid.uuid4()}"
    return _stable_digest(room_id, nonce)


def _stable_digest(*values: str) -> str:
    encoded = "\0".join(values).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def _root_facilitator(
    room: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
) -> str:
    active_participants = [
        value
        for value in room.get("participants", [])
        if isinstance(value, Mapping) and value.get("status") == "active"
    ]
    moderator_id = str(room.get("moderatorParticipantId") or "")
    coordinator_ids = [
        str(value.get("id") or "")
        for value in active_participants
        if canonical_collaboration_role_id(value.get("collaborationRole"))
        == "coordinator"
    ]
    if moderator_id in coordinator_ids:
        return moderator_id
    if coordinator_ids:
        return coordinator_ids[0]
    active_ids = [str(value.get("id") or "") for value in active_participants]
    if moderator_id in active_ids:
        return moderator_id
    target_ids = {
        str(value.get("id") or "")
        for value in targets
    }
    for participant_id in active_ids:
        if participant_id in target_ids:
            return participant_id
    if active_ids:
        return active_ids[0]
    raise RoomKernelFenceError("managed Room execution requires an active Facilitator")


def _opening_facilitator(
    room: Mapping[str, object],
    targets: Sequence[Mapping[str, object]],
    *,
    requested_participant_ids: Sequence[str],
    managed_work: bool,
) -> str:
    """Resolve the immutable initial Facilitator for a newly-created Root.

    One explicit opening mention may override the default.  Managed WorkItems
    keep their authoritative owner and later messages never call this helper,
    so a mention cannot transfer ownership after Root creation.
    """

    if not managed_work:
        requested = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in requested_participant_ids
                if str(value).strip()
            )
        )
        if len(requested) == 1:
            requested_id = requested[0]
            for participant in room.get("participants", []):
                if (
                    isinstance(participant, Mapping)
                    and str(participant.get("id") or "") == requested_id
                    and participant.get("status") == "active"
                ):
                    return requested_id
    return _root_facilitator(room, targets)


def _alignment_acceptance_criteria(
    identity: str,
    targets: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, str], ...]:
    criteria: list[tuple[str, str]] = []
    for ordinal, target in enumerate(targets):
        participant_id = str(target.get("id") or "")
        display_name = (
            " ".join(str(target.get("displayName") or "").split())
            or f"伙伴 {ordinal + 1}"
        )
        statement = (
            f"{display_name} 已读取原始请求并判断是否存在会改变实现的实质歧义；"
            "完整请求直接定义目标、交付、验收和禁区，有歧义时一次只询问一个"
            "必要问题；完成定义前不得开始执行。"
        )
        criteria.append(
            (
                "acceptance:"
                f"{identity}:alignment:{ordinal}:"
                f"{_stable_digest(participant_id, statement)}",
                statement,
            )
        )
    return tuple(criteria)


def _alignment_task(
    base_task: Mapping[str, object],
    *,
    task_id: str,
    target: Mapping[str, object],
    message: str,
    criterion_id: str,
    ordinal: int,
    total: int,
) -> dict[str, object]:
    display_name = (
        " ".join(str(target.get("displayName") or "").split())
        or f"伙伴 {ordinal + 1}"
    )
    return {
        **base_task,
        "taskId": task_id,
        "parentTaskId": None,
        "currentOwnerParticipantId": str(target["id"]),
        "objective": (
            f"{display_name} 作为本轮主持伙伴，先弄清用户到底要完成什么。"
            "此阶段只读取请求与已有信息，不搜索、不改文件、不运行实现任务。"
            "先调用 room_state 读取原始请求。在调用 room_define 前，必须能用普通"
            "用户听得懂的话具体说出：（1）具体入口或页面；（2）用户会做什么并看到"
            "什么；（3）要交付哪些真实产物；（4）怎样从界面或运行结果判断完成。"
            "“端到端可用、完整、可运行闭环”只能说明范围，不能替代具体目标；"
            "“当前项目、规定入口、核心操作、真实结果”都是未完成的占位说法。"
            "请求已经足够具体时，不要再问用户确认需求细节；先形成可展示的执行方案，再直接用 room_define "
            "一次写入具体目标、交付物、要求、可观察验收条件、禁区和方案。如果仍缺少"
            "会实质改变范围、风险或交付方式的决定，先从项目现状和"
            "安全的常规默认值推断；不得让用户复述能从代码、页面或已有请求中确定的"
            "信息，也不得为了填满入口、格式、字段、错误处理等清单而连续追问。最多"
            "只进行一轮补问：有 2–4 个互不依赖的问题时，一次列出 2–4 个互不依赖的问题，"
            "在正文中按 1/2/3/4 编号，并为每题给出 A/B/C 等简短方案，允许用户直接回复"
            "“1A 2C”；此时用 questionKind=unbounded 且不传 questionOptions。只有单个真正"
            "互斥的决定才使用可点击选择项：用 questionKind=bounded 并提供 2–5 个有简短"
            "标题和说明的 questionOptions，界面会另提供“其他”文本入口。非阻塞细节使用"
            "合理默认值并在定义中说明。收到这一轮回答后应直接形成方案并 room_define；仅当还剩"
            "一个无法安全推断的高风险决定时才允许再问一次，不得形成逐题问卷。定义前先锁定"
            "公共契约；若有多个用户可见功能，按功能纵向拆成最多四项，每项由一位同能力伙伴端到端"
            "负责并写明依赖波次、写入边界、集成和验收。单个功能只能交给一位 Room Agent，不能按"
            "前端、后端、解析或测试横向拆分。同一伙伴同一波只能负责一个功能；所有伙伴能力对等，"
            "主持伙伴只是额外承担分工、集成和最终汇报，也可以和其他伙伴一样端到端负责功能。不要在"
            "计划阶段把某位伙伴永久留作低能力的只读者或只复核者；独立复核在集成后依据真实实现、"
            "集成和交付记录选择没有参与待审成果的伙伴。角色名称只表示本轮责任，不代表模型能力高低。开始行动前的"
            "所有文案必须沿用用户正在使用的语言和用户视角：说清用户能做什么、会看到什么；不得把"
            "英文类型名、camelCase 字段表或协议术语直接展示在主方案中，这些细节留到开始后的工作"
            "文档或可展开技术详情。若真实页面、命令或代码入口尚未读取，只能明确写成用户提出的入口"
            "假设，并说明开始后先核对，不能冒充已确认的项目事实。executionPlan 的 continuityPlan"
            "还要说明：批准后先建立当前 WorkItem 唯一的受管工作文档，在不同章节保存用户原话与愿景、"
            "确认需求、执行方案、进度证据、失败路径和下一步；任何交接或上下文恢复都先读它再核对"
            "当前源码与运行状态。room_define 后始终展示方案并询问“现在开始行动吗？”，"
            "用户批准前不得分派、写入或测试。公开消息里不要使用“对齐、澄清、需求不足、"
            "工作卡片、门禁”，应自然说明“我明白了”或“还差一个会影响做法的问题”。"
            "如果 room_define 拒绝了占位定义，就继续问下一个具体问题，不要把工具"
            "失败当作本轮结论。不得把计划或执行结果冒充具体定义。"
            f" 原始请求：{message[:2_000]}"
        )[:4_000],
        "expectedOutput": (
            "一个具体且可执行的目标，以及开始行动前可审核的公共契约、纵向功能分工、"
            "依赖波次、写入边界、集成、验收和上下文记录方案。所有用户可见内容沿用用户语言，"
            "不展示内部数据结构。定义后由 Facilitator 先执行方案展示与等待；"
            "用户批准后，Facilitator 才按方案用"
            "room_collaborate 分配真正独立的完整功能。"
        ),
        "acceptanceCriterionIds": [criterion_id],
        "revision": 0,
        "state": "active",
    }


def _normalize_room_execution_plan(
    value: object,
    *,
    objective: str,
    expected_output: str,
    default_participant: Mapping[str, object],
    participant_refs: Mapping[str, str],
    participants: object,
    acceptance_plan: Sequence[str],
) -> dict[str, object]:
    """Validate the user-visible pre-start plan without creating parallel state."""

    active = {
        str(item.get("id") or ""): item
        for item in (
            participants
            if isinstance(participants, Sequence)
            and not isinstance(participants, (str, bytes))
            else []
        )
        if isinstance(item, Mapping)
        and item.get("status") == "active"
        and str(item.get("id") or "").strip()
    }

    def clean_text(raw: object, field: str, *, limit: int) -> str:
        text = " ".join(str(raw or "").split())
        if not text:
            raise ValueError(f"room_define executionPlan {field} is required")
        return text[:limit]

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("room_define executionPlan must be an object")
    raw_tasks = value.get("featureTasks")
    if (
        not isinstance(raw_tasks, Sequence)
        or isinstance(raw_tasks, (str, bytes))
        or not 1 <= len(raw_tasks) <= 4
    ):
        raise ValueError("room_define executionPlan featureTasks must contain 1-4 items")
    feature_tasks: list[dict[str, object]] = []
    feature_owner_ids: list[str] = []
    titles: set[str] = set()
    for ordinal, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, Mapping):
            raise ValueError("room_define executionPlan feature task must be an object")
        title = clean_text(raw_task.get("title"), "feature title", limit=200)
        if title in titles:
            raise ValueError("room_define executionPlan feature titles must be unique")
        titles.add(title)
        participant_ref = clean_text(
            raw_task.get("participantRef"),
            "participantRef",
            limit=320,
        )
        try:
            participant_id = resolve_participant_ref(
                participant_ref,
                participant_refs,
            )
        except ParticipantReferenceError:
            participant_id = participant_ref
        participant = active.get(participant_id)
        if participant is None:
            raise RoomKernelFenceError(
                "room_define executionPlan participant is not active"
            )
        feature_owner_ids.append(participant_id)
        dependencies = [
            " ".join(str(item or "").split())[:200]
            for item in (
                raw_task.get("dependencies")
                if isinstance(raw_task.get("dependencies"), Sequence)
                and not isinstance(raw_task.get("dependencies"), (str, bytes))
                else []
            )
            if " ".join(str(item or "").split())
        ][:4]
        wave = raw_task.get("wave")
        normalized_wave = (
            int(wave)
            if isinstance(wave, int) and not isinstance(wave, bool) and 1 <= wave <= 4
            else ordinal + 1 if dependencies else 1
        )
        feature_tasks.append(
            {
                "title": title,
                "participantRef": participant_ref,
                "ownerDisplayName": str(
                    participant.get("displayName") or f"伙伴 {ordinal + 1}"
                ),
                "userOutcome": clean_text(
                    raw_task.get("userOutcome"),
                    "userOutcome",
                    limit=2_000,
                ),
                "dependencies": dependencies,
                "wave": normalized_wave,
                "writeBoundary": " ".join(
                    str(raw_task.get("writeBoundary") or "").split()
                )[:1_000],
            }
        )
    owner_waves = [
        (owner_id, int(task["wave"]))
        for owner_id, task in zip(feature_owner_ids, feature_tasks, strict=True)
    ]
    if len(owner_waves) != len(set(owner_waves)):
        raise ValueError(
            "同一位伙伴不能在同一波并行承担两个功能；请调整波次或负责人。"
        )
    shared_contracts = [
        " ".join(str(item or "").split())[:1_000]
        for item in (
            value.get("sharedContracts")
            if isinstance(value.get("sharedContracts"), Sequence)
            and not isinstance(value.get("sharedContracts"), (str, bytes))
            else []
        )
        if " ".join(str(item or "").split())
    ][:8]
    raw_acceptance = value.get("acceptancePlan")
    normalized_acceptance = [
        " ".join(str(item or "").split())[:1_000]
        for item in (
            raw_acceptance
            if isinstance(raw_acceptance, Sequence)
            and not isinstance(raw_acceptance, (str, bytes))
            else acceptance_plan
        )
        if " ".join(str(item or "").split())
    ][:12]
    if not normalized_acceptance:
        raise ValueError("room_define executionPlan acceptancePlan is required")
    chinese_plan = any("\u3400" <= char <= "\u9fff" for char in objective)
    continuity_plan = " ".join(
        str(value.get("continuityPlan") or "").split()
    )[:2_000]
    if not continuity_plan:
        continuity_plan = (
            "批准开始后，负责人先建立并登记当前任务唯一的受管工作文档；"
            "其中分开保存用户原话与愿景、已确认需求、执行方案、进度证据、"
            "失败路径和下一步。任何伙伴接手或上下文恢复时都先读取这份文档，"
            "再核对最新代码和运行状态。"
            if chinese_plan
            else
            "After approval, the facilitator registers the task's single governed work "
            "document. It separately preserves the user's source and vision, confirmed "
            "requirements, execution plan, evidence, failed paths, and next action; every "
            "handoff or recovery reads it before checking current source and runtime state."
        )
    normalized = {
        "sharedContracts": shared_contracts,
        "featureTasks": feature_tasks,
        "integrationPlan": clean_text(
            value.get("integrationPlan"),
            "integrationPlan",
            limit=2_000,
        ),
        "acceptancePlan": normalized_acceptance,
        "continuityPlan": continuity_plan,
    }
    _assert_user_facing_execution_plan_language(
        [
            *shared_contracts,
            *[
                text
                for task in feature_tasks
                for text in (
                    str(task["title"]),
                    str(task["userOutcome"]),
                    *[str(item) for item in task["dependencies"]],
                    str(task["writeBoundary"]),
                )
                if text
            ],
            str(normalized["integrationPlan"]),
            *normalized_acceptance,
            continuity_plan,
        ],
        reference=f"{objective} {expected_output}",
    )
    return normalized


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        text
        for item in value
        if (text := " ".join(str(item or "").split()))
    )


def _public_error(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:500]


def _work_item_acceptance_criteria(
    identity: str,
    work_item: Mapping[str, object] | None,
) -> tuple[tuple[str, str], ...]:
    if work_item is None:
        return ()
    raw = work_item.get("acceptanceCriteria")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    criteria: list[tuple[str, str]] = []
    for ordinal, value in enumerate(raw):
        statement = " ".join(str(value or "").split())
        if not statement:
            continue
        criterion_id = (
            f"acceptance:{identity}:{ordinal}:"
            f"{_stable_digest(statement)}"
        )
        criteria.append((criterion_id, statement[:1_000]))
    return tuple(criteria)


def _work_item_context(
    work_item: Mapping[str, object],
    *,
    acceptance_criteria: Sequence[tuple[str, str]],
) -> str:
    return json.dumps(
        {
            "schemaVersion": "wisdom-weasel.room-work-item-context.v1",
            "authority": "task-only",
            "doesNotChange": [
                "identity",
                "toolPermissions",
                "approvalPolicy",
                "safetyPolicy",
            ],
            "workItemId": str(work_item.get("id") or ""),
            "revision": int(work_item.get("revision") or 0),
            "objective": str(work_item.get("objective") or "")[:4_000],
            "expectedOutput": str(
                work_item.get("expectedOutput") or ""
            )[:2_000],
            "acceptanceCriteria": [
                {"criterionId": criterion_id, "statement": statement}
                for criterion_id, statement in acceptance_criteria
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _room_work_document_markdown(
    *,
    room: Mapping[str, object],
    root: Mapping[str, object],
    work_item: Mapping[str, object],
    original_vision: str,
    execution_plan: object,
) -> str:
    """Render the durable Room brief without inventing a second authority."""

    criteria = [
        str(value).strip()
        for value in work_item.get("acceptanceCriteria") or []
        if str(value).strip()
    ]
    longest_backtick_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", original_vision)),
        default=0,
    )
    vision_fence = "`" * max(3, longest_backtick_run + 1)
    plan_text = (
        json.dumps(
            execution_plan,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        if isinstance(execution_plan, Mapping)
        else "尚无单独的并行拆分；负责人按已确认目标推进。"
    )
    indented_plan = "\n".join(
        f"    {line}" for line in plan_text.splitlines()
    )
    criteria_text = (
        "\n".join(f"- [ ] {item}" for item in criteria)
        or "- [ ] 按已确认交付目标完成并提供可复核证据"
    )
    return (
        f"# {str(room.get('title') or 'Room')} 工作文档\n\n"
        "> 这是本 Room 唯一的权威工作文档。负责人维护正文；伙伴只在交接中返回小型增量，"
        "不得另建副本文档。\n\n"
        "## 权威绑定\n\n"
        f"- Room Root：`{str(root.get('rootId') or '')}`\n"
        f"- WorkItem：`{str(work_item.get('id') or '')}`\n\n"
        "## 原始用户愿景\n\n"
        f"{vision_fence}text\n{original_vision}\n{vision_fence}\n\n"
        "## 已确认目标\n\n"
        f"{str(work_item.get('objective') or '').strip()}\n\n"
        "## 预期交付\n\n"
        f"{str(work_item.get('expectedOutput') or '').strip()}\n\n"
        "## 验收条件\n\n"
        f"{criteria_text}\n\n"
        "## 已批准执行计划\n\n"
        f"{indented_plan}\n\n"
        "## 当前进度\n\n"
        "- 已由用户确认开始行动。\n\n"
        "## 证据\n\n"
        "- 待补充。\n\n"
        "## 失败与恢复\n\n"
        "- 暂无。\n\n"
        "## 下一步\n\n"
        "- 按执行计划推进当前可运行的功能波次，并在每次实质进展后更新本文件。\n"
    )
