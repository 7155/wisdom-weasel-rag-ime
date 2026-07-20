import type { GuardActivationProjectionV1 } from '@/contracts/generated/guard-activation-projection.v1';
import type { GuardActivePointerProjectionV1 } from '@/contracts/generated/guard-active-pointer-projection.v1';
import type { GuardApprovalProjectionV1 } from '@/contracts/generated/guard-approval-projection.v1';
import type { GuardCandidateProjectionV1 } from '@/contracts/generated/guard-candidate-projection.v1';
import type { GuardEvalRunProjectionV1 } from '@/contracts/generated/guard-eval-run-projection.v1';
import type { GuardMaterializationStatusProjectionV1 } from '@/contracts/generated/guard-materialization-status-projection.v1';
import type { GuardRollbackProjectionV1 } from '@/contracts/generated/guard-rollback-projection.v1';
import type { IncidentOccurrenceProjectionV1 } from '@/contracts/generated/incident-occurrence-projection.v1';
import type { KnowledgeSearchUseEvalRunV1 } from '@/contracts/generated/knowledge-search-use-eval-run.v1';
import type { LessonCandidateProjectionV1 } from '@/contracts/generated/lesson-candidate-projection.v1';
import type { ReflectionDeadLetterProjectionV1 } from '@/contracts/generated/reflection-dead-letter-projection.v1';

export type GovernanceProjection = {
  incidents: IncidentOccurrenceProjectionV1[];
  lessons: LessonCandidateProjectionV1[];
  guardCandidates: GuardCandidateProjectionV1[];
  evalRuns: GuardEvalRunProjectionV1[];
  approvals: GuardApprovalProjectionV1[];
  activations: GuardActivationProjectionV1[];
  rollbacks: GuardRollbackProjectionV1[];
  activePointers: GuardActivePointerProjectionV1[];
  deadLetters: ReflectionDeadLetterProjectionV1[];
  materializations: GuardMaterializationStatusProjectionV1[];
};

export type KnowledgePromotionCandidate = {
  promotionCandidateId: string;
  evidenceKind: string;
  evidenceRef: string;
  claimKey: string;
  claimText?: string;
  ownerKind: string;
  ownerId: string;
  scopeKind: string;
  scopeId: string;
  visibility: string;
  risk: string;
  candidateHash: string;
  conflictClaimRefs: string[];
};

export type KnowledgeGovernanceProjection = {
  promotionCandidates: KnowledgePromotionCandidate[];
  promotionReceipts: Array<{ promotionReceiptId: string; promotionCandidateId: string; claimVersionId: string; scopeKey: string; knowledgeEpoch: number; candidateHash: string }>;
  claims: Array<{ claimVersionId: string; claimIdentity: string; claimKey: string; claimText?: string; claimHash: string; ownerKind: string; ownerId: string; scopeKind: string; scopeId: string; visibility: string; provenance: Record<string, unknown>; contradictionRefs: string[] }>;
  conflicts: Array<{ promotionCandidateId: string; state: string; claimRefs: string[] }>;
  lifecycleReceipts: Array<{ lifecycleReceiptId: string; claimIdentity: string; operation: string; knowledgeEpoch: number; scopeKey: string }>;
  epochs: Array<{ scopeKey: string; knowledgeEpoch: number }>;
  quarantines: Array<{ importId: string; sourceName: string; status: string; contentHash: string; findingCount: number }>;
  outbox: Array<{ outboxId: string; claimVersionId: string; operation: string; state: string; attemptCount: number; lastError?: string }>;
  tombstones: Array<{ tombstoneId: string; scopeKey: string; knowledgeEpoch: number; sessionId: string; reason: string }>;
  evalDatasets: Array<{ datasetId: string; datasetVersion: number; thresholds: Record<string, unknown>; contentHash: string; expiresAtMs: number }>;
  searchUseEvalRuns: KnowledgeSearchUseEvalRunV1[];
};

export const emptyGovernanceProjection: GovernanceProjection = {
  incidents: [], lessons: [], guardCandidates: [], evalRuns: [], approvals: [], activations: [], rollbacks: [], activePointers: [], deadLetters: [], materializations: [],
};

export const emptyKnowledgeGovernanceProjection: KnowledgeGovernanceProjection = {
  promotionCandidates: [], promotionReceipts: [], claims: [], conflicts: [], lifecycleReceipts: [], epochs: [], quarantines: [], outbox: [], tombstones: [], evalDatasets: [], searchUseEvalRuns: [],
};

const SECRET_KEY = /(secret|token|password|credential|api.?key|private.?key|raw.?text)/i;
const SHA256 = /^[a-f0-9]{64}$/i;

export function safeDisplay(value: unknown): string {
  return JSON.stringify(scrub(value), null, 2);
}

function scrub(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(scrub);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, entry]) => [key, SECRET_KEY.test(key) ? '[已隐藏]' : scrub(entry)]));
}

export function visibleClaimText(item: { claimText?: string; visibility?: string; evidenceKind?: string; provenance?: Record<string, unknown> }): string {
  const external = item.evidenceKind === 'external_import' || item.provenance?.dataOnly === true;
  if (external) return '[外部内容仅作为数据引用，不展示原文]';
  if (item.visibility === 'secret') return '[秘密内容已隐藏]';
  if (item.visibility === 'private') return '[私有内容已隐藏]';
  return item.claimText?.trim() || '[无正文]';
}

export function activeGuards(projection: GovernanceProjection) {
  const candidates = new Map(projection.guardCandidates.map((candidate) => [candidate.guardCandidateId, candidate]));
  return projection.activePointers.map((pointer) => ({ pointer, candidate: pointer.activeGuardCandidateId ? candidates.get(pointer.activeGuardCandidateId) ?? null : null }));
}

export function guardIntegrity(projection: GovernanceProjection, candidate: GuardCandidateProjectionV1, pointer?: GuardActivePointerProjectionV1) {
  const approvals = projection.approvals.filter((item) => item.guardCandidateId === candidate.guardCandidateId);
  const materializations = projection.materializations.filter((item) => item.guardCandidateId === candidate.guardCandidateId);
  const tampered = !SHA256.test(candidate.candidateHash)
    || approvals.some((item) => item.candidateHash !== candidate.candidateHash)
    || materializations.some((item) => item.artifactHash && !SHA256.test(item.artifactHash));
  const staleEpoch = Boolean(pointer && materializations.some((item) => item.guardEpoch !== pointer.guardEpoch));
  return { tampered, staleEpoch };
}

export function matchesScope(value: unknown, filters: { root: string; owner: string; room: string; session: string }): boolean {
  const text = JSON.stringify(value).toLowerCase();
  return Object.values(filters).every((filter) => !filter.trim() || text.includes(filter.trim().toLowerCase()));
}
