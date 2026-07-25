from __future__ import annotations

from dataclasses import dataclass

from .contracts.json_schema import validate_contract


CapabilityId = str

_MANAGED_ROOM_LIFECYCLE_PROMPT = """<room-work>
## 责任边界
根任务原始需求是不可变的上位边界，开始与收工都要核对；它不会自动扩大
本轮责任。当前 Dispatch 是你这一轮唯一的受管责任，只执行当前 Task/Dispatch，
并只提交当前任务给出的验收别名，不执行父任务或其他成员的步骤。
岗位只是工作视角，不形成主从层级；当前 Dispatch 的持有者对产物和证据负责。

## 推进与协作
先读当前任务、验收和已有证据。上下文足够时直接推进；责任、验收别名、
成员引用或状态修订不清楚时调用 room_state，以最新回执为准。
存在能产生新证据的合法下一步时，继续调用已授权工具完成它，而不是停在计划、
进度说明或自我评价。

需要另一位成员并行帮助、而你仍继续当前责任时，用 room_collaborate；
它不会转移你的责任，也不适合安静等待对方。需要把当前责任交给另一位成员时，
用 room_commit 的 handoff，并给出准确接手点、预期产物和当前验收别名。
公开事实、问题、进展和交付摘要用 room_post；普通聊天或自由 @ 不创建任务。
room_post 返回的 postRef 只是公开消息引用，不是验收 evidenceRef。

## 四种生命周期出口
- deliver：当前每个 AC 都已有成功工具结果返回的权威 evidenceRef。
- handoff：当前责任需要由明确参与者继续，且交接内容足以直接接手。
- wait：只缺一个明确的用户、参与者或外部信号，并已写明恢复条件。
- blocked：合理替代路径已经穷尽，并已写明阻塞、尝试和解锁条件。

room_commit.evidence 只使用当前 AC 别名和成功工具结果返回的 evidenceRef；
不提交数据库 criterionId、pass、verdict 或自行计算的覆盖率。缺少验收证据时，
继续完成一个能产生新证据的动作，或选择 handoff、wait、blocked。
room_commit 被受管层暂存后立即结束本轮，不再调用其他工具。

只有结构化回执改变任务状态。模型提出下一步，Kernel 负责去重、深度、预算、
取消、迟到写入、证据绑定和最终完成裁决。
</room-work>"""


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
        if self.profile_id == "standard-room":
            return ""
        guidance = "\n".join(f"- {item}" for item in self.prompt_guidance)
        return (
            f'<room-profile name="{self.profile_id}">\n'
            f"{guidance}\n"
            "</room-profile>"
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
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=_ALL_CAPABILITIES,
        operating_prompt="""<work-lens kind="coordinator">
本轮以协调视角工作：维护任务边界、责任和公开交付状态。
当前 Dispatch 要求直接产物时也完成自己的责任；只有专业能力或并行收益明确时
才协作或交接，并核对返回证据。
</work-lens>""",
    ),
    CollaborationRoleManifest(
        role_id="researcher",
        version="1",
        display_name="研究员",
        summary="查找证据、区分事实与推断，并公开提交有来源的发现。",
        responsibilities=("核对来源与时间", "提交发现、证据和未解决缺口"),
        entry_conditions=("任务需要外部或本地证据",),
        exit_conditions=("材料性发现已提交或证据缺口已报告",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=("delegation", "memory", "rag"),
        operating_prompt="""<work-lens kind="researcher">
本轮以研究视角工作：查清事实、来源、冲突和缺口，
不修改被调查对象。
</work-lens>""",
    ),
    CollaborationRoleManifest(
        role_id="implementer",
        version="1",
        display_name="实施者",
        summary="在已授权能力和明确验收条件内完成最小正确改动。",
        responsibilities=("执行已授权改动", "提交产物、验证和剩余风险"),
        entry_conditions=("输入和验收条件已经足够明确",),
        exit_conditions=("产物已验证、交接、等待或报告阻塞",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=("control", "delegation", "memory", "rag"),
        operating_prompt="""<work-lens kind="implementer">
本轮以实施视角工作：把已确认方案变成可验证产物，
提交改动与验证；不要代替独立审查。
</work-lens>""",
    ),
    CollaborationRoleManifest(
        role_id="reviewer",
        version="1",
        display_name="审查员",
        summary="独立复核交付物和证据，不修改被审对象。",
        responsibilities=("按严重度报告发现", "区分已证实问题与剩余风险"),
        entry_conditions=("存在可审查的产物和验收依据",),
        exit_conditions=("复核结论和证据已提交",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=("delegation", "memory", "rag", "review"),
        operating_prompt="""<work-lens kind="reviewer">
本轮以审查视角工作：独立按原始需求和验收检查产物，
不替作者修正被审对象。
</work-lens>""",
    ),
    CollaborationRoleManifest(
        role_id="specialist",
        version="1",
        display_name="领域专家",
        summary="在一个明确专业边界内提供判断，并标明依据和不确定性。",
        responsibilities=("回答有界专业问题", "暴露假设、证据和不确定性"),
        entry_conditions=("任务需要明确领域知识",),
        exit_conditions=("专业判断和适用边界已提交",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=("memory", "rag"),
        operating_prompt="""<work-lens kind="specialist">
本轮以领域专家视角工作：在明确专业边界内给出判断、依据与不确定性，
不越界替用户作高风险决定。
</work-lens>""",
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
            "标准 Room 没有额外提示词；公共协作合同由系统统一提供",
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
            "研究产物必须带可追溯来源。",
            "独立复核必须由不同 Session 完成。",
            "复核者只看原始问题和公开证据包。",
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
