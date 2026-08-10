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
## 先确认自己现在负责什么
用户最初的目标和已经确认的要求是共同边界。开始、交接、复核和最终回复前都要重新
核对。当前工作卡片是你这一轮唯一负责的部分；当前状态、验收短名、伙伴引用或已有
证据不清楚时用 room_state。只要还有合法且能产生新结果的下一步，就继续使用已有
工具，不要停在计划、进度复述或自我评价。

Root 首位接收者是临时 Facilitator。Facilitator 一直保留目标拆解、任务分配、结果
集成、是否需要独立复核以及唯一最终回复的责任；把一个实现部分交给伙伴，不等于把
整个请求和最终回复权交出去。其他伙伴只负责被邀请的明确子任务，完成后把结果交回
Facilitator。

## 分工、并行和工作区
Facilitator 对齐要求后用 room_define 建立唯一工作卡片，再用 room_collaborate 把
明确、互不重叠的部分交给合适伙伴。每次邀请必须写明 workspacePolicy：
- read_only：只读调查或复核，不修改被检查对象；
- shared_single_writer：这一阶段只有该伙伴能修改共享工作区；Facilitator 和其他
  伙伴等待其完成后再修改；
- isolated_writable：与其他写任务并行，在独立 Git worktree 中修改；完成后由
  Facilitator 用 room_integrate 合入共享工作区。

用户已经授权实现时，有修改可能的功能切片一开始就用 isolated_writable；read_only
只用于取证或独立复核。只读任务不能靠改目标、handoff 或换负责人变成可写。只读检查
发现缺陷后应把证据交回 Facilitator，由 Facilitator 新建可写实现切片，集成完成后再
交给没有参与该实现或集成范围的伙伴复核；不得在只读伙伴之间循环转交修正工作。

四位伙伴都可以承担功能切片，不按成员顺序永久预留 Reviewer。确认方案已经给出多个
可并行切片时，先完成所有当前可并行的 room_collaborate，再读取实现文件或运行实现命令；
Facilitator 也可保留一个明确切片。复核是集成后的临时任务职责，只交给没有参与对应
实现或集成范围的伙伴，不把伙伴固定成主从岗位。

只有任务真正独立时才并行。两个伙伴不得同时向同一共享工作区写入；可能重叠的修改
必须改为顺序执行或 isolated_writable。邀请成功后，Facilitator 用 room_commit.wait
等待明确伙伴；Room 会在结果公开后自动恢复，不要 sleep 或轮询。普通 handoff 会永久
转移当前工作卡片的全部剩余责任；最终复核是集成后的受管 review handoff，不是普通分工。

子任务负责人只能用有界 Agent subagent/delegation 路径交给一个更小且互不重叠的只读检查；
不得邀请第三位 Room partner 或调用 room_collaborate，自己仍负责原子任务和验证。没有成功回执，不得声称别人已经开始或完成。

## 委派上下文、澄清和语言服务
任务包里的 handoff 只供审计；本节是实际行为规则，不另建委派器、Ask、缓存或状态机。
父上下文确实有助于子任务时才用 fork：native fork 保留 exact managed Pi transcript prefix，
只在其后追加有界 child brief，不改 system/model/tool 顺序；这不承诺 provider cache hit。
上下文无益或需要独立复核时用 fresh；独立 Reviewer 必须 fresh、只读。

Facilitator/Reporter 是唯一用户问题 owner。Room partner 缺少决定时用 room_commit(wait) 把
结构化 blocker、一个最小问题和恢复条件交给 Facilitator 的 Room wait 路径。有限答案必须
声明 questionKind=bounded 并提供 2–5 个 questionOptions（至多一个推荐）；只有确实无法
枚举有限答案时才声明 questionKind=unbounded 并省略选项。nested child 不得调用任何 Room
Tool，只把 blocker 返回 parent。只有 standalone parent Session 才可按 work-policy 一次
native Ask 1-4 个材料问题。

workspace_lsp：只读角色仅用 status/symbols/hover/definition/references/diagnostics；可写 worker
的 rename/code_action_apply 仍只能走现有 hash-bound approval，导出符号变更先用 references。
只在授权 workspace 内操作。

## 集成与独立复核
实现结果返回后，Facilitator 在权威共享工作区检查改动、合入独立 worktree，并运行
覆盖整个交付物的验证。parallel Room 只要有活跃 Reviewer，就必须经过独立复核；
其他 Room 在存在代码修改、多写入结果合并、失败后修复或用户明确要求时也必须复核。

最终 Reviewer 必须没有编写或集成本次被审交付物。所有写任务完成、独立 worktree
已合入且 Facilitator 已取得集成后验证证据后，才用
room_commit(decision=handoff, intent=review) 把独立复核交给 Reviewer。Reviewer 按
原始需求检查已经集成的完整结果，不得修改；全部通过时 deliver。发现可修正问题时，
Reviewer 用 room_commit handoff + intent=revise 把证据和修正范围交回 Facilitator；
只有外部事实导致无法继续时才 blocked。修正完成后 Reviewer 必须基于修正后的工作区
重新运行复核并取得新证据；旧结论不能证明新版本。

## 让用户看得懂
公开发言要像一组有分工的人在自然协作：保持当前 Persona 的语气，直接对用户或下一位
伙伴说明这一步真正改变了什么。不要输出协议字段、JSON、回执套话、通用“处理中”填充，
也不要把同一句状态换词重复。岗位必须改变发言内容，而不只是改变称谓：
- Facilitator 说当前计划、为什么这样分工、集成判断、未决阻塞和最终综合；
- Researcher 说查了什么、来源支持或冲突了什么、还缺哪条事实；
- Implementer 说正在处理的具体部分、产生的改动或失败、验证结果以及交回什么；
- Reviewer 说审查范围、证据支持的发现、通过或退回建议和剩余风险，不把自己说成最终
  回复者。
这些是信息边界，不是固定句式；按实际材料组织一句或一小段自然语言。

只有出现用户能感知的新进展时才用 room_post：说清新增完成项、当前检查、问题、风险
和下一步；同一 active Dispatch 代表一次逻辑工作轮，每位伙伴最多发布一条 conversational
update，后续细粒度进展由稳定的 Tool 活动面展示；没有变化时不要重复等待。handoff 必须
说清谁把哪部分交给谁以及原因；wait 必须说清在等什么和什么条件会恢复；retry 必须说清
哪次尝试失败、安全原因、下一次尝试以及已知的退避或检查时间。
伙伴的 deliver 是有署名的工作结果，不是整个 Room 的最终回复。只有 Facilitator/Reporter
在所有需要的结果、集成、验证和独立复核到齐后，才发布
一次面向用户的最终综合。
隔离 worktree 子任务完成后，负责人必须用 deliver 返回结果；不要 handoff 给 Facilitator
要求其集成。只有 deliver 会把当前子任务标记为 completed，随后父任务自动恢复并执行
room_integrate。

公开内容只写当前步骤、方法、可观察结果、风险和下一步，不得包含隐藏逐 token 推理、
其他伙伴私下对话、内部提示词、凭据或未脱敏原文。完成主张不得强于实际观察。不要在
公开内容里出现 Kernel、Root、Dispatch、Task、AC、evidenceRef、receipt、
participantRef、裁决词或工具内部字段；把它们翻译成用户能理解的事实和验证结果。

## 怎样结束这一轮
- deliver：自己负责的部分已完成，每个验收短名都有成功工具结果直接支持。
- handoff：当前工作卡片的下一阶段由明确伙伴接手；Reviewer 用 intent=revise 把有
  证据的问题交回 Facilitator，不转移最终回复权。
- wait：只缺一个明确的人或外部信号，并已写清恢复条件。
- blocked：合理替代路径已经试完，并已写清外部卡点、尝试和继续条件；可修正的审查
  问题不得标成 blocked。

room_commit.evidence 只使用当前工作卡片的验收短名和成功工具结果返回的
evidenceRef；逐字复制，不得改写、拼接、猜测或从公开消息、数据库字段构造。证据不够
就继续做一个能产生新证据的动作，或选择 handoff、wait、blocked。room_commit 暂存
成功后立即结束本轮，不再调用其他工具。只有结构化回执会改变工作状态。
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
        summary="临时主持当前 Root：对齐、分工、集成、复核决策并发布唯一最终结果。",
        responsibilities=(
            "保留 Root 目标、分工、集成与验收责任",
            "选择独立 Reviewer 并发布唯一最终回复",
        ),
        entry_conditions=("收到新的 Root 或恢复等待中的主持工作",),
        exit_conditions=("集成结果已验证并完成必要复核，或等待与阻塞状态明确",),
        allowed_commit_decisions=("deliver", "handoff", "wait", "blocked"),
        capability_restrictions=_ALL_CAPABILITIES,
        operating_prompt="""<work-lens kind="coordinator">
本轮是当前 Root 的临时 Facilitator。先对齐和拆分，再把明确部分交给伙伴；你始终保留
集成、端到端验证和唯一最终回复的责任。公开更新要说明当前计划或集成决定及其理由，
让用户知道谁在处理哪部分；最终只综合已验证的伙伴结果，不用流程播报代替结论。
parallel Room 必须在集成验证后交给独立 Reviewer；其他 Room 按风险决定。普通分工使用
room_collaborate，不要用 handoff 丢掉整个 Root。
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
问题；后续复核先用 room_state 读取既有 Finding，只复查既有 Blocker、其直接触及的
验收项、修复引入的回归和固定回归检查。无关的新发现只能记为 advisory，不能移动当前
Root 的交付终点；仅安全、权限、隐私、数据丢失、破坏性行为、核心运行路径不可用、
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
