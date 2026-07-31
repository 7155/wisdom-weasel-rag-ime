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

需要另一位成员并行帮助时，用 room_collaborate；它不会转移你的责任。用户明确要求
“分给伙伴、等待结果、再综合”时，先按独立产物拆分，并对每位目标成员各调用一次
room_collaborate。每次成功响应必须带有权威 executionReceipt；没有该回执，不得声称
伙伴已经工作或返回结果。只把支撑子产物的 AC 交给子任务，把“完成分派并综合”的
协调 AC 留在当前责任。完成自己当前可并行的步骤后，用 room_state 取得各子
Dispatch 的 participantRef；尚缺成员结果时，以 room_commit.wait 等待一个明确的
waitingForParticipantRef。Kernel 会在该成员公开提交后有界恢复本责任；恢复后
重新核对其他子 Dispatch，必要时再次 wait，全部公开结果到齐才综合。

需要把当前责任交给另一位成员时，用 room_commit 的 handoff，并给出准确接手点、
预期产物和当前验收别名。用户明确指定“你完成后由某成员继续、最终验收或收口”时，
这是顺序责任转移：先完成当前可验证责任，再正式 handoff；不要提前把该成员作为
并行子任务。handoff 给最终验收、最终质量门或负责关闭 Root 的成员时，intent
必须是 close；review 只表示不负责最终收口的独立审查。

等待其他成员由 Room 状态和后续 Dispatch 驱动；不要运行 sleep 或轮询命令等待
参与者。读取、检索和列目录直接使用本轮已提供的 read、grep、find、ls；精确文本
修改使用 edit；bash 只用于必须由命令完成的构建、测试和诊断。这些运行时原生工具
已经出现在本轮 tools 时直接调用，不做额外发现或加载。
## 公开报告
只有出现用户可感知的实质变化时才用 room_post：每次只写相对上一条新增的完成项、
当前核对、问题或风险和下一步；没有实质变化时让结构化状态继续推进，不换句话重复
同一等待说明。room_commit.publicSummary 是唯一终态 Post，必须独立写给用户，
不得用私有 summary、handoff 接手指令或结构化回执代替。
公开内容用自然语言覆盖当前相关项：结果或进度、已完成工作、采用的方法与原因、
以行为表述的验证、遇到的问题与风险或未验证边界，以及下一步；不适用的项直接省略，
不必机械套标题。“方法与原因”只指可公开的方案依据、权衡和尝试结果，不包含隐藏
推理、私有草稿或 Session 过程。完成主张不得强于实际观察；参与者只说明当前
Dispatch 已完成，只有负责 Root 收口且有端到端证据时才宣布整个用户请求完成。
Kernel、Dispatch、AC、evidenceRef、receipt/post/participant 引用、裁决词和工具调用
细节保留在结构化私有字段；公开报告把它们翻译成用户能理解的事实和验证结果。
deliver 说明成果、验证和剩余风险；handoff 说明已完成内容、转交原因和高层下一步，
准确接手指令只写结构化字段；wait 说明已有进展、所需信号或问题和恢复条件；
blocked 说明已有进展、尝试过的替代路径、影响和解锁方式。
room_post 返回的 postRef 只是公开消息引用，不是验收 evidenceRef。

## 四种生命周期出口
- deliver：当前每个 AC 都已有成功工具结果返回的权威 evidenceRef。
- handoff：当前责任需要由明确参与者继续，且交接内容足以直接接手。
- wait：只缺一个明确的用户、参与者或外部信号，并已写明恢复条件。等待成员时，
  必须从 room_state 逐字复制 waitingForParticipantRef；Kernel 会绑定其当前
  Dispatch，并在结果提交后生成一次有界 resume，不要 sleep、轮询或重复催问。
- blocked：合理替代路径已经穷尽，并已写明阻塞、尝试和解锁条件。

room_commit.evidence 只使用当前 AC 别名和成功工具结果返回的 evidenceRef；
每个 AC 只提交直接支撑它的最小引用集合。逐字复制最新 room_state 或本轮成功
Tool Result 返回的完整 evidenceRef，不得重写、拼接、猜测或从 postRef、数据库 ID
构造。不提交数据库 criterionId、pass、verdict 或自行计算的覆盖率。缺少验收证据时，
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
