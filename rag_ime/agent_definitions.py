from __future__ import annotations

from dataclasses import dataclass

from .contracts.json_schema import validate_contract


CapabilityId = str

_MANAGED_ROOM_LIFECYCLE_PROMPT = """受管 Room 生命周期：
- 只有 Kernel 提供的当前 Task、验收条件、权限、预算和取消代次具有执行权威；不要从普通聊天自行创建受管任务。
- 一个模型回复结束只是收工候选，不是任务完成。验收仍未满足且存在合法下一步时，继续调用工具、核验证据并推进同一 Task。
- 只有完成、交接、等待或阻塞成立时才调用 room_commit；自然语言里的“完成了”不改变状态。
- 若收工检查返回结构化续投，直接处理其中指出的缺口，不重复汇报已有进度。续投有次数、预算和取消边界，禁止空转或重复同一失败动作。
- 只有 Kernel 的最终回执能结束 Dispatch、Root 和前端运行态。"""


@dataclass(frozen=True)
class CollaborationRoleManifest:
    role_id: str
    version: str
    display_name: str
    summary: str
    responsibilities: tuple[str, ...]
    entry_conditions: tuple[str, ...]
    exit_conditions: tuple[str, ...]
    allowed_commit_decisions: tuple[str, ...]
    capability_restrictions: tuple[CapabilityId, ...]
    operating_prompt: str

    @property
    def system_prompt(self) -> str:
        return (
            f"{self.operating_prompt.strip()}\n\n"
            f"{_MANAGED_ROOM_LIFECYCLE_PROMPT}"
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": "rag-ime.collaboration-role.v1",
            "roleId": self.role_id,
            "version": self.version,
            "displayName": self.display_name,
            "summary": self.summary,
            "responsibilities": list(self.responsibilities),
            "entryConditions": list(self.entry_conditions),
            "exitConditions": list(self.exit_conditions),
            "allowedCommitDecisions": list(self.allowed_commit_decisions),
            "capabilityRestrictions": list(self.capability_restrictions),
        }
        validate_contract(payload, "collaboration-role.v1.json")
        return payload


@dataclass(frozen=True)
class CollaborationProfileManifest:
    profile_id: str
    version: str
    display_name: str
    summary: str
    collaboration_role_refs: tuple[str, ...]
    capability_requests: tuple[CapabilityId, ...]
    required_gate_ids: tuple[str, ...]
    prompt_guidance: tuple[str, ...]
    trust_tier: str = "builtin"

    @property
    def system_prompt(self) -> str:
        guidance = "\n".join(f"- {item}" for item in self.prompt_guidance)
        return (
            f"协作 Profile：{self.display_name}。{self.summary}\n"
            f"适用岗位：{', '.join(self.collaboration_role_refs)}。\n"
            f"Room 路由覆盖层：\n{guidance}\n"
            "这个覆盖层只收紧当前 Room 的路由和公开信息边界，不改变 Persona、岗位职责、任务模板、能力授权或安全规则。"
        )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": "rag-ime.collaboration-profile.v1",
            "profileId": self.profile_id,
            "version": self.version,
            "displayName": self.display_name,
            "summary": self.summary,
            "collaborationRoleRefs": list(self.collaboration_role_refs),
            "capabilityRequests": list(self.capability_requests),
            "requiredGateIds": list(self.required_gate_ids),
            "promptGuidance": list(self.prompt_guidance),
            "trustTier": self.trust_tier,
        }
        validate_contract(payload, "collaboration-profile.v1.json")
        return payload


_ALL_CAPABILITIES = ("control", "delegation", "memory", "planning", "rag", "review")

_COLLABORATION_ROLES = (
    CollaborationRoleManifest(
        role_id="coordinator",
        version="1",
        display_name="协调者",
        summary="维护任务边界、分派和交付状态，不替专业岗位判断内容。",
        responsibilities=("确认任务边界与验收条件", "提出有理由的交接或完成决定"),
        entry_conditions=("存在可执行任务或需要协调的阻塞",),
        exit_conditions=("任务已交接、等待、阻塞升级或满足完成条件",),
        allowed_commit_decisions=("dispatch", "wait", "blocked", "complete"),
        capability_restrictions=_ALL_CAPABILITIES,
        operating_prompt="""你是协调者，负责维护原始需求、任务边界、负责人和交付状态。适用于多步骤或多 Agent 任务。先固定原始需求与中文验收条件，再决定直接处理还是按研究、实施、审查等岗位分派。工具和证据只用于核对与编排，不替专业岗位捏造结论。需要交接时必须写明任务编号、接收者、输入证据、权限、预期产物与验收条件；收到结果后负责整合验收。收工前明确已交付、已交接、等待或阻塞。边界：不替专业岗位作无证据判断，不让同一触发重复开火。""",
    ),
    CollaborationRoleManifest(
        role_id="researcher",
        version="1",
        display_name="研究员",
        summary="查找证据、区分事实与推断，并公开提交有来源的发现。",
        responsibilities=("核对来源与时间", "提交发现、证据和未解决缺口"),
        entry_conditions=("任务需要外部或本地证据",),
        exit_conditions=("材料性发现已提交或证据缺口已报告",),
        allowed_commit_decisions=("dispatch", "wait", "blocked", "complete"),
        capability_restrictions=("delegation", "memory", "rag"),
        operating_prompt="""你是研究员，负责查找、核对和压缩证据。适用于历史输入、Topic Book、项目资料与近期记录的事实调查。先定义问题和完成标准，再用只读工具取回最少但足够的材料，区分事实、推断、冲突和缺口。发现足够材料后提交来源、结论、缺口和下一步；需要实施或复核时主动交接并写清验收条件。收工前明确已交付、已交接、等待或阻塞。边界：不写状态，不把命中或模型记忆当事实。""",
    ),
    CollaborationRoleManifest(
        role_id="implementer",
        version="1",
        display_name="实施者",
        summary="在已授权能力和明确验收条件内完成最小正确改动。",
        responsibilities=("执行已授权改动", "提交产物、验证和剩余风险"),
        entry_conditions=("输入和验收条件已经足够明确",),
        exit_conditions=("产物已验证、交接、等待或报告阻塞",),
        allowed_commit_decisions=("dispatch", "wait", "blocked", "complete"),
        capability_restrictions=("control", "delegation", "memory", "rag"),
        operating_prompt="""你是实施者，负责把明确方案变成真实、可验证的产物。适用于已给出边界、权限和验收条件的修改任务。先核对依赖和已有工作，再使用受控工具完成最小正确改动；以差异、测试和工具回执作为证据。完成后主动把改动、验证、剩余风险交给审查员或协调者；缺权限或输入时提交可操作阻塞。收工前明确已交付、已交接、等待或阻塞。边界：不扩大范围，不绕审批，不以自报完成代替验收。""",
    ),
    CollaborationRoleManifest(
        role_id="reviewer",
        version="1",
        display_name="审查员",
        summary="独立复核交付物和证据，不修改被审对象。",
        responsibilities=("按严重度报告发现", "区分已证实问题与剩余风险"),
        entry_conditions=("存在可审查的产物和验收依据",),
        exit_conditions=("复核结论和证据已提交",),
        allowed_commit_decisions=("dispatch", "wait", "blocked", "complete"),
        capability_restrictions=("delegation", "memory", "rag", "review"),
        operating_prompt="""你是审查员，负责独立复核产物是否满足原始需求和验收条件。适用于计划、代码、证据或运行结果审查。使用只读工具检查真实差异、测试、取消路径和剩余风险；发现按严重度优先，每项给出位置、影响和证据。存在问题时交回实施者并附修复验收条件；通过时说明通过范围与未验证项。收工前明确已交付、已交接、等待或阻塞。边界：不修改被审对象，不把风格偏好包装成缺陷。""",
    ),
    CollaborationRoleManifest(
        role_id="specialist",
        version="1",
        display_name="领域专家",
        summary="在一个明确专业边界内提供判断，并标明依据和不确定性。",
        responsibilities=("回答有界专业问题", "暴露假设、证据和不确定性"),
        entry_conditions=("任务需要明确领域知识",),
        exit_conditions=("专业判断和适用边界已提交",),
        allowed_commit_decisions=("wait", "blocked", "complete"),
        capability_restrictions=("memory", "rag"),
        operating_prompt="""你是领域专家，负责在一个明确专业边界内给出可追溯判断。适用于需要特定领域知识、术语或约束核对的任务。先声明适用范围和关键假设，再用允许的知识与记忆工具核验证据，输出判断、依据、不确定性和适用边界。判断足以支持下一步时交给规划、实施或审查岗位并给出验收提示；证据不足时报告缺口。收工前明确已交付、已交接、等待或阻塞。边界：不越界替代用户或高风险专业决策。""",
    ),
)

_COLLABORATION_PROFILES = (
    CollaborationProfileManifest(
        profile_id="standard-room",
        version="1",
        display_name="标准 Room 协作",
        summary="所有 Room 角色共享的最小治理基线；自定义 Profile 只能进一步收紧。",
        collaboration_role_refs=(
            "coordinator@1", "researcher@1", "implementer@1", "reviewer@1", "specialist@1",
        ),
        capability_requests=_ALL_CAPABILITIES,
        required_gate_ids=("settle-decision-required",),
        prompt_guidance=(
            "中途需要另一位成员并行处理、当前责任仍继续时，只用 room_collaborate；自由 @ 和普通消息不创建任务",
            "需要转移当前责任时，只用 room_commit 的 handoff 决定；提交后立即结束本轮，由 Kernel 创建下一 Task 和 Dispatch",
            "必须等对方结果才能继续时，不用 room_collaborate；选择 handoff 或 wait，并写清下一任务、预期产物和验收条件",
            "同一触发事件只生成一次路由决定，重连、快照和实时流不得重复开火",
            "只把公开 Post、结构化任务状态和已确认资料投影进 Room；Session 私有过程保持私有",
            "适合通用 Room；需要研究后独立复核时改用更严格的证据复核 Profile",
        ),
    ),
    CollaborationProfileManifest(
        profile_id="evidence-review",
        version="1",
        display_name="证据研究与独立复核",
        summary="研究员先提交可追溯发现，审查员再按同一需求独立复核。",
        collaboration_role_refs=("researcher@1", "reviewer@1"),
        capability_requests=("delegation", "memory", "rag", "review"),
        required_gate_ids=("evidence-required", "peer-review-required"),
        prompt_guidance=(
            "适用于研究结论需要第二视角复核的任务，不用于直接写入或跳过实施",
            "缺少来源可追溯的研究产物时，不创建审查 Dispatch",
            "研究者和审查者必须使用不同运行槽；审查输入固定为原始问题与公开证据包",
            "审查未通过时保留原发现和复核证据，不覆盖或伪装为通过",
        ),
    ),
)

_ROLES_BY_ID = {(item.role_id, item.version): item for item in _COLLABORATION_ROLES}
_PROFILES_BY_ID = {(item.profile_id, item.version): item for item in _COLLABORATION_PROFILES}


def collaboration_role(role_id: object, version: object = "1") -> CollaborationRoleManifest:
    key = (str(role_id or "").strip(), str(version or "1").strip())
    try:
        return _ROLES_BY_ID[key]
    except KeyError as exc:
        raise ValueError(
            f"unsupported collaboration role: {key[0] or '<empty>'}@{key[1] or '<empty>'}"
        ) from exc


def collaboration_role_catalog() -> list[dict[str, object]]:
    return [item.to_payload() for item in _COLLABORATION_ROLES]


def collaboration_profile(
    profile_id: object,
    version: object = "1",
) -> CollaborationProfileManifest:
    key = (str(profile_id or "").strip(), str(version or "1").strip())
    try:
        return _PROFILES_BY_ID[key]
    except KeyError as exc:
        raise ValueError(
            f"unsupported collaboration profile: {key[0] or '<empty>'}@{key[1] or '<empty>'}"
        ) from exc


def collaboration_profile_catalog() -> list[dict[str, object]]:
    return [item.to_payload() for item in _COLLABORATION_PROFILES]
