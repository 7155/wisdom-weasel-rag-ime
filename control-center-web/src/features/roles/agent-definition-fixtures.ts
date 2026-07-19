// Temporary read-only projections. Lane A will regenerate the canonical wire
// types after room-participant-binding.v2 and the catalog endpoints are merged.
export type CollaborationRoleFixture = {
  roleId: 'coordinator' | 'researcher' | 'implementer' | 'reviewer' | 'specialist';
  version: '1';
  displayName: string;
  summary: string;
  responsibilities: string[];
  entryConditions: string[];
  exitConditions: string[];
  allowedCommitDecisions: Array<'dispatch' | 'wait' | 'blocked' | 'complete'>;
  capabilityRestrictions: string[];
};

export type CollaborationProfileFixture = {
  profileId: string;
  version: '1';
  displayName: string;
  summary: string;
  collaborationRoles: string[];
  requiredGates: string[];
  capabilityRequests: string[];
  trustTier: 'builtin';
  governance: CollaborationProfileGovernanceProjection;
};

export type CollaborationProfileGovernanceProjection = {
  pointerRevision: number;
  activeContentHash: string;
  activeVersion: string;
  signerId: string;
  pipelineChecks: Array<'inspect' | 'validate' | 'compile' | 'dry-run' | 'stage' | 'activate'>;
  compileReceipt: {
    receiptId: string;
    bindingRevision: string;
    effectiveCapabilities: string[];
    rejectedCapabilities: string[];
  };
  diff: {
    previousVersion: string | null;
    currentVersion: string;
    removedCapabilities: string[];
    addedCapabilities: string[];
  };
};

export const collaborationRoleFixtures: CollaborationRoleFixture[] = [
  {
    roleId: 'coordinator', version: '1', displayName: '协调者',
    summary: '维护任务边界、分派和交付状态，不替专业岗位判断内容。',
    responsibilities: ['确认任务边界与验收条件', '提出有理由的交接或完成决定'],
    entryConditions: ['存在可执行任务或需要协调的阻塞'],
    exitConditions: ['任务已交接、等待、阻塞升级或满足完成条件'],
    allowedCommitDecisions: ['dispatch', 'wait', 'blocked', 'complete'],
    capabilityRestrictions: ['control', 'delegation', 'memory', 'planning', 'rag', 'review'],
  },
  {
    roleId: 'researcher', version: '1', displayName: '研究员',
    summary: '查找证据、区分事实与推断，并公开提交有来源的发现。',
    responsibilities: ['核对来源与时间', '提交发现、证据和未解决缺口'],
    entryConditions: ['任务需要外部或本地证据'],
    exitConditions: ['材料性发现已提交或证据缺口已报告'],
    allowedCommitDecisions: ['dispatch', 'wait', 'blocked', 'complete'],
    capabilityRestrictions: ['delegation', 'memory', 'rag'],
  },
  {
    roleId: 'implementer', version: '1', displayName: '实施者',
    summary: '在已授权能力和明确验收条件内完成最小正确改动。',
    responsibilities: ['执行已授权改动', '提交产物、验证和剩余风险'],
    entryConditions: ['输入和验收条件已经足够明确'],
    exitConditions: ['产物已验证、交接、等待或报告阻塞'],
    allowedCommitDecisions: ['dispatch', 'wait', 'blocked', 'complete'],
    capabilityRestrictions: ['control', 'delegation', 'memory', 'rag'],
  },
  {
    roleId: 'reviewer', version: '1', displayName: '审查员',
    summary: '独立复核交付物和证据，不修改被审对象。',
    responsibilities: ['按严重度报告发现', '区分已证实问题与剩余风险'],
    entryConditions: ['存在可审查的产物和验收依据'],
    exitConditions: ['复核结论和证据已提交'],
    allowedCommitDecisions: ['dispatch', 'wait', 'blocked', 'complete'],
    capabilityRestrictions: ['delegation', 'memory', 'rag', 'review'],
  },
  {
    roleId: 'specialist', version: '1', displayName: '领域专家',
    summary: '在一个明确专业边界内提供判断，并标明依据和不确定性。',
    responsibilities: ['回答有界专业问题', '暴露假设、证据和不确定性'],
    entryConditions: ['任务需要明确领域知识'],
    exitConditions: ['专业判断和适用边界已提交'],
    allowedCommitDecisions: ['wait', 'blocked', 'complete'],
    capabilityRestrictions: ['memory', 'rag'],
  },
];

export const collaborationProfileFixtures: CollaborationProfileFixture[] = [
  {
    profileId: 'evidence-review', version: '1', displayName: '证据研究与独立复核',
    summary: '研究员先提交可追溯发现，审查员再按同一需求独立复核。',
    collaborationRoles: ['研究员', '审查员'],
    requiredGates: ['证据提交', '独立复核'],
    capabilityRequests: ['delegation', 'memory', 'rag', 'review'],
    trustTier: 'builtin',
    governance: {
      pointerRevision: 1,
      activeContentHash: `sha256:${'a'.repeat(64)}`,
      activeVersion: '1',
      signerId: 'builtin',
      pipelineChecks: ['inspect', 'validate', 'compile', 'dry-run', 'stage', 'activate'],
      compileReceipt: {
        receiptId: 'profile-compile:fixture00000000000000000',
        bindingRevision: 'binding-revision-1',
        effectiveCapabilities: ['memory', 'rag', 'review'],
        rejectedCapabilities: ['delegation'],
      },
      diff: {
        previousVersion: null,
        currentVersion: '1',
        removedCapabilities: ['delegation'],
        addedCapabilities: [],
      },
    },
  },
];
