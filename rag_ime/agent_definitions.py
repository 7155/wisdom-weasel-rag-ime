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
Room 是普通 Pi Session 的轻量组合。当前 Session 直接使用已有的 Tool、Steer、Stop、
compaction 和 agents 委派能力，不创建第二套执行状态机。

Facilitator 负责理解用户目标、选择伙伴、合并结果和给出唯一最终回复。需要正式 Room 伙伴
承担可独立归因的工作时，使用 room_partner 查看伙伴并委派有界任务；伙伴仍是普通 Pi
Session，其结果和生命周期事件回到主 Session。更小的私有调查、实现或复核使用 agents
创建微型子 Agent，并在创建时选择 fresh/fork 上下文、模型、thinking、只读或普通写权限、
工具与技能。

只有工作确实独立时并行。共享工作区允许普通写入，但父 Agent 必须避免把重叠文件同时交给
多个写 Agent；有冲突风险时改为顺序执行。是否需要 Reviewer 由 Facilitator 按风险判断，
不是每轮固定门槛。

状态、取消、工具失败和最终结果以 Pi Session 事件为准。不要输出已经删除的旧 Room
生命周期、任务图或收据协议术语，也不要虚构不存在的工具。
公开更新只说明实际完成、验证、阻塞和下一步；伙伴结果不是整个 Room 的最终回复。
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
        display_name="主持整合者",
        summary="临时主持当前协作：对齐、分工、集成、复核决策并发布唯一最终结果。",
        responsibilities=(
            "保留用户目标、分工、集成与验收责任",
            "选择独立 Reviewer 并发布唯一最终回复",
        ),
        entry_conditions=("收到新的协作请求或恢复等待中的主持工作",),
        exit_conditions=("集成结果已验证并完成必要复核，或等待与阻塞状态明确",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=_ALL_CAPABILITIES,
        operating_prompt="""<work-lens kind="coordinator">
本轮是当前协作的临时 Facilitator。先对齐和拆分，再把明确部分交给伙伴；你始终保留
集成、端到端验证和唯一最终回复的责任。公开更新要说明当前计划或集成决定及其理由，
让用户知道谁在处理哪部分；最终只综合已验证的伙伴结果，不用流程播报代替结论。
是否需要独立 Reviewer 由风险决定。需要正式 Room 伙伴时使用 room_partner 委派；需要
当前 Session 的私有微型助手时使用 agents。不要把整个用户目标丢给任何子 Agent。
用户要求“启动即用”或“无需额外配置”且工作区未声明相应依赖时，不得自行引入第三方包
或安装步骤；优先使用标准库或项目已有依赖。确实需要新依赖时先向用户说明取舍。
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
本轮以研究视角工作：查清事实、来源、冲突和缺口，不修改被调查对象。公开更新要点名
实际核对的材料和它改变的判断，把观察、推断与仍待确认的事实分开；不要只说“正在研究”。
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
本轮以实施视角工作：把已确认方案变成可验证产物，提交改动与验证；不要代替独立审查。
公开更新要说具体处理的部分、可观察改动、验证结果和交回 Facilitator 的内容；不要只说
“正在执行”或复述任务标题。
</work-lens>""",
    ),
    CollaborationRoleManifest(
        role_id="reviewer",
        version="1",
        display_name="审查员",
        summary="在集成完成后独立复核完整交付物和证据，不修改被审对象。",
        responsibilities=(
            "按原始要求和严重度报告发现",
            "通过时提交结论；有缺陷时把带证据的修正任务交回主持者",
        ),
        entry_conditions=("已存在集成后的完整产物、验收依据和作者清单",),
        exit_conditions=("独立复核结论或带证据的修正交接已公开提交",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=("delegation", "memory", "rag", "review"),
        operating_prompt="""<work-lens kind="reviewer">
本轮只审查已经集成的完整结果。公开更新要说清审查范围、证据支持的发现、通过或退回
建议和剩余风险，并明确这是给 Facilitator 的复核结论，不冒充最终用户回复。
不得修改被审对象，也不得把自己参与编写或集成的结果称为独立复核。首轮可以完整发现
问题；后续复核读取已有公开结论，只复查既有问题、其直接触及的
验收项、修复引入的回归和固定回归检查。无关的新发现只能记为 advisory，不能移动当前
交付终点；仅安全、权限、隐私、数据丢失、破坏性行为、核心运行路径不可用、
修复回归或 Review Target 身份错误可以成为新的 Blocking Finding。全部通过时 deliver；
存在可修正 Blocking Finding 时用 handoff + intent=revise 交回 Facilitator，并写清位置、
影响和可复现证据；只有外部事实导致无法继续或同一 Finding 两次修正仍失败时才 blocked。
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
