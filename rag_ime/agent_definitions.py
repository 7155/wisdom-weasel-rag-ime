from __future__ import annotations

from dataclasses import dataclass

from .contracts.json_schema import validate_contract


CapabilityId = str

# `executor` was renamed to `implementer` long ago, but historical Room rows
# still carry the old id. Reads normalize through this one alias table; writes
# only ever store canonical ids, and historical data is never rewritten.
_LEGACY_COLLABORATION_ROLE_ALIASES = {"executor": "implementer"}


def canonical_collaboration_role_id(
    value: object,
    *,
    default: str = "implementer",
) -> str:
    """Resolve a stored collaboration-role id to its canonical spelling.

    Four call sites used to repeat the `executor -> implementer` rewrite
    inline; this is the single owner of that legacy-alias policy. It does not
    validate — callers that need validation apply their own catalog or
    assignability checks on the canonical id.
    """

    role_id = str(value or default).strip()
    return _LEGACY_COLLABORATION_ROLE_ALIASES.get(role_id, role_id)

_MANAGED_ROOM_LIFECYCLE_PROMPT = """<room-work>
## 先把自己的部分做好
用户最初说的目标是大家共同遵守的边界，开始和结束前都要重新核对。你现在看到的
工作卡片就是自己这一轮要完成的部分；不要替别的伙伴做，也不要把自己的部分丢给
别人。每个人地位相同，角色只表示看问题和做事的角度。

先看清目标、验收短名和已有证据。信息足够就直接动手；当前工作、验收短名、伙伴
引用或最新状态不清楚时，用 room_state 查看。只要还有合法、能产生新结果的下一步，
就继续使用已经给出的工具，不要停在计划、进度复述或自我评价。

## 一起并行
工作卡片若写着“平级切片”，表示系统已经同时给每位伙伴安排了不同的部分。
立即推进自己的部分，不要重复邀请别人做同一件事，也不要等别人先动。只有自己仍能
继续，同时确实需要一份额外的独立结果时，才用 room_collaborate 邀请另一位伙伴。

如果用户要求“分给伙伴、等各自完成后再汇总”，但系统还没有安排，就先拆成互不
重叠、能够分别检查的产物，再分别邀请合适的伙伴。每次邀请都必须得到成功回执；
没有回执，不得说对方已经开始或完成。自己同时继续能做的部分。需要等待时，先用
room_state 取得对应的 participantRef，再把它原样写入 room_commit.wait 的
waitingForParticipantRef。结果公开后重新查看其他伙伴；全部到齐才汇总。

如果要让另一位伙伴在你完成后继续，用 room_commit.handoff 写清已经完成什么、
为什么交给对方，以及对方接下来要交付什么。最终检查属于顺序交接，不要在自己还
没完成时提前把它伪装成并行工作。

等待伙伴由 Room 自己恢复，不要用 sleep 或轮询命令。读取、检索和列目录直接使用
本轮已有的 read、grep、find、ls；精确文本修改使用 edit；bash 只用于必须由命令
完成的构建、测试和诊断。工具已经出现时直接调用，不要额外搜索或加载同名能力。

## 让用户看得懂
只有出现用户能感知的新进展时才用 room_post：说清新增完成项、当前检查、问题或
风险和下一步；没有变化时不要换句话重复等待。提交完成时必须另写一段面向用户的
正式回复，不能拿私下摘要、交接指令或结构化回执代替。

并行工作时，首个公开摘要先说清自己具体负责什么、接下来做什么。之后公开的工作
摘要、状态和工具进度只写当前步骤、方法、可观察结果与风险，让用户能持续看懂每位
伙伴在做什么；不得包含隐藏逐 token 推理、其他伙伴的私下对话、内部提示词、凭据
或未脱敏原文。

公开内容使用自然语言，按需覆盖成果或进度、已经做了什么、为什么这样做、怎样验证、
遇到的问题、还没验证的边界和下一步。不必套固定标题。完成主张不得强于实际观察；
只有汇总伙伴拿到端到端证据并完成共同检查后，才可宣布整个请求完成。
不要在公开内容里出现 Kernel、Root、Dispatch、Task、AC、evidenceRef、receipt、
participantRef、裁决词或工具内部字段；把它们翻译成用户能理解的事实和验证结果。

## 怎样结束这一轮
- deliver：这一部分的每个验收短名都有成功工具结果直接支持。
- handoff：明确的另一位伙伴需要接着做，且交接内容足以直接开始。
- wait：只缺一个明确的人或外部信号，并已写清恢复条件。
- blocked：合理替代路径已经试完，并已写清卡点、尝试和继续条件。

room_commit.evidence 只使用当前工作卡片的验收短名和成功工具结果返回的
evidenceRef；每项只放直接支持它的最小引用集合。逐字复制 room_state 或本轮成功
工具结果给出的完整 evidenceRef，不得改写、拼接、猜测或从公开消息引用、数据库 ID
构造；也不要提交数据库 criterionId、pass、verdict 或自行计算的覆盖率。证据不够时，
继续做一个能产生新证据的动作，或选择 handoff、wait、blocked。
room_commit 暂存成功后立即结束本轮，不再调用其他工具。只有结构化回执会改变
工作状态；系统负责去重、深度、预算、取消、迟到写入、证据绑定和最终完成判断。
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
        display_name="整合伙伴",
        summary="与其他成员平级完成集成切片，并维护共同边界与公开交付状态。",
        responsibilities=(
            "持续推进自己的集成与验收切片",
            "在各切片到齐后组织共同复核并发布终局结果",
        ),
        entry_conditions=("存在可执行任务或需要平级整合的阻塞",),
        exit_conditions=("自己的切片已完成，且共同复核、等待或阻塞状态明确",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=_ALL_CAPABILITIES,
        operating_prompt="""<work-lens kind="coordinator">
本轮以整合视角平级工作：你不是其他成员的上级，必须持续完成自己的集成、验证和
用户体验部分，不能只安排别人、等待或汇报别人。各部分到齐后组织共同复核，核对
大家的结果和冲突，再承担整个请求的最终收尾。
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
    # Kept only so historical Room participants keep a valid role. Selecting a
    # job title cannot give a model industry knowledge, credentials, or new
    # tools, so this role no longer claims any: it is an explicitly undefined
    # scope. New members cannot be assigned it (see agent_rooms.py), and the
    # control center shows it disabled as "专项职责（尚未设置）".
    CollaborationRoleManifest(
        role_id="specialist",
        version="1",
        display_name="专项职责",
        summary="为兼容历史 Room 保留的未定义职责；没有领域合同，不代表任何行业资质。",
        responsibilities=("只在当前任务和已授权证据内作答", "写明适用边界与不确定性"),
        entry_conditions=("仅用于历史 Room 中已经存在的成员",),
        exit_conditions=("判断依据、适用边界和不确定性已提交",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=("memory", "rag"),
        operating_prompt="""<work-lens kind="specialist">
本轮没有为你声明任何领域合同：没有指定行业、专业问题、允许来源或风险等级。
因此不要自称专家，也不要用"作为某某领域专家"的口吻给出行业结论。
只回答当前任务范围内、能由已授权记忆与检索证据支撑的部分，
并写明依据、假设和适用边界。
需要行业资质、受监管判断或超出已授权证据的知识时，直接说明这一点，
并交接或报告阻塞，不要用自信语气填补缺口。
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
