from __future__ import annotations

from dataclasses import dataclass

from .contracts.json_schema import validate_contract


CapabilityId = str


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
        prompt_guidance=("收工前必须明确交接、等待、阻塞或完成决定",),
    ),
    CollaborationProfileManifest(
        profile_id="evidence-review",
        version="1",
        display_name="证据研究与独立复核",
        summary="研究员先提交可追溯发现，审查员再按同一需求独立复核。",
        collaboration_role_refs=("researcher@1", "reviewer@1"),
        capability_requests=("delegation", "memory", "rag", "review"),
        required_gate_ids=("evidence-required", "peer-review-required"),
        prompt_guidance=("先区分事实、推断和缺口", "复核结论必须引用可见证据"),
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
