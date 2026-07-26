import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { GovernanceCenter } from './index';
import { activeGuards, safeDisplay, type GovernanceProjection, type KnowledgeGovernanceProjection } from './model';

const hash = 'a'.repeat(64);

describe('GovernanceCenter', () => {
  afterEach(cleanup);

  it('is strictly read-only while formal backend routes are missing', () => {
    render(<GovernanceCenter governance={governance()} knowledge={knowledge()} />);
    expect(screen.getByText('安全记录暂时只读')).toBeInTheDocument();
    expect(screen.getByText(/当前可以查看记录，但不能在这里批准/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /批准|激活|回滚|撤销/ })).not.toBeInTheDocument();
  });

  it('derives active state only from activePointers, never an activation receipt', () => {
    const projection = governance();
    projection.activePointers = [];
    expect(activeGuards(projection)).toEqual([]);
    render(<GovernanceCenter governance={projection} knowledge={knowledge()} />);
    expect(screen.getByText('启用 activation:1')).toBeInTheDocument();
    expect(screen.queryByText('活动指针', { selector: '.mgmt-status' })).not.toBeInTheDocument();
  });

  it('surfaces tamper and stale epoch evidence and keeps report-only eval explicit', () => {
    const projection = governance();
    projection.approvals[0]!.candidateHash = 'b'.repeat(64);
    projection.materializations[0]!.guardEpoch = 6;
    render(<GovernanceCenter governance={projection} knowledge={knowledge()} />);
    expect(screen.getByText('完整性异常')).toBeInTheDocument();
    expect(screen.getByText('版本已过期')).toBeInTheDocument();
    expect(screen.getByText('仅报告')).toBeInTheDocument();
    expect(screen.getByText(/authorizationLeakageCount/)).toBeInTheDocument();
    expect(screen.getByText(/minUsedCitationRate/)).toBeInTheDocument();
  });

  it('hides secret and external raw text, redacts sensitive object keys, and supports scoped filters', () => {
    const data = knowledge();
    data.claims.push({ claimVersionId: 'claim:secret', claimIdentity: 'secret', claimKey: 'secret-key', claimText: 'DO_NOT_RENDER_SECRET', claimHash: hash, ownerKind: 'owner', ownerId: 'owner-b', scopeKind: 'session', scopeId: 'session-secret', visibility: 'secret', provenance: {}, contradictionRefs: [] });
    render(<GovernanceCenter governance={governance()} knowledge={data} />);
    expect(screen.queryByText('DO_NOT_RENDER_EXTERNAL')).not.toBeInTheDocument();
    expect(screen.queryByText('DO_NOT_RENDER_SECRET')).not.toBeInTheDocument();
    expect(screen.getAllByText('[外部内容仅作为数据引用，不展示原文]')).toHaveLength(2);
    expect(screen.getByText('[秘密内容已隐藏]')).toBeInTheDocument();
    expect(safeDisplay({ apiKey: 'RAW_KEY', nested: { password: 'RAW_PASSWORD', ok: 1 } })).toBe('{\n  "apiKey": "[已隐藏]",\n  "nested": {\n    "password": "[已隐藏]",\n    "ok": 1\n  }\n}');
    fireEvent.change(screen.getByLabelText('对话'), { target: { value: 'session-secret' } });
    expect(screen.getByText('secret-key')).toBeInTheDocument();
    expect(screen.queryByText('external-key')).not.toBeInTheDocument();
  });

  it('keeps long identifiers contained and exposes every filter by accessible label', () => {
    const projection = governance();
    projection.incidents[0]!.failureSignature = 'failure/'.repeat(80);
    const { container } = render(<GovernanceCenter governance={projection} knowledge={knowledge()} />);
    expect(screen.getByRole('region', { name: '安全记录范围筛选' })).toBeInTheDocument();
    for (const label of ['整项任务', '责任方', '协作空间', '对话']) expect(screen.getByLabelText(label)).toBeInTheDocument();
    expect(container.querySelector('.governance-columns')).toBeInTheDocument();
    expect(screen.getByText('failure/'.repeat(80))).toBeInTheDocument();
  });
});

function governance(): GovernanceProjection {
  return {
    incidents: [{ schemaVersion: 'wisdom-weasel.incident-occurrence-projection.v1', incidentId: 'incident:1', taxonomy: 'routing_loop', failureSignature: 'A→B→A', evidenceRefs: ['event:1'], occurrenceCount: 2, lastObservedAtMs: 10 }],
    lessons: [{ schemaVersion: 'wisdom-weasel.lesson-candidate-projection.v1', lessonCandidateId: 'lesson:1', incidentId: 'incident:1', facts: ['loop'], causes: ['missing depth'], applicabilityBoundary: { roomId: 'room-1' }, counterexamples: [], provenance: ['event:1'], candidateHash: hash, state: 'candidate_only', createdAtMs: 11 }],
    guardCandidates: [{ schemaVersion: 'wisdom-weasel.guard-candidate-projection.v1', guardCandidateId: 'guard:1', lessonCandidateId: 'lesson:1', version: 1, condition: { rootId: 'root-1', roomId: 'room-1', sessionId: 'session-1' }, action: { stop: true }, scope: { owner: 'owner-a', room: 'room-1' }, risk: 'high', thresholds: { maxDepth: 8 }, owner: 'owner-a', sunsetAtMs: 999, candidateHash: hash, state: 'candidate_only', createdAtMs: 12 }],
    evalRuns: [{ schemaVersion: 'wisdom-weasel.guard-eval-run-projection.v1', evalRunId: 'eval:1', guardCandidateId: 'guard:1', mode: 'shadow', datasetHash: hash, metrics: { loopRate: 0 }, status: 'passed', createdAtMs: 13 }],
    approvals: [{ schemaVersion: 'wisdom-weasel.guard-approval-projection.v1', approvalReceiptId: 'approval:1', guardCandidateId: 'guard:1', authorityRef: 'admin', decision: 'approved', candidateHash: hash, createdAtMs: 14 }],
    activations: [{ schemaVersion: 'wisdom-weasel.guard-activation-projection.v1', activationReceiptId: 'activation:1', scopeKey: 'room:room-1', guardCandidateId: 'guard:1', guardEpoch: 7, appliesToNewRootsAfterMs: 15, evalRunIds: ['eval:1'], createdAtMs: 15 }],
    rollbacks: [],
    activePointers: [{ schemaVersion: 'wisdom-weasel.guard-active-pointer-projection.v1', scopeKey: 'room:room-1', guardEpoch: 7, activeGuardCandidateId: 'guard:1', activationReceiptId: 'activation:1', updatedAtMs: 16 }],
    deadLetters: [{ schemaVersion: 'wisdom-weasel.reflection-dead-letter-projection.v1', deadLetterId: 'dead:1', incidentId: 'incident:1', ownerRef: 'owner-a', reasonCode: 'retry_exhausted', lastEvidenceRefs: ['event:1'], nextAction: '人工复核', attemptCount: 3, createdAtMs: 17 }],
    materializations: [{ schemaVersion: 'wisdom-weasel.guard-materialization-status-projection.v1', materializationReceiptId: 'material:1', guardCandidateId: 'guard:1', guardEpoch: 7, artifactKind: 'prompt_guard', status: 'applied', artifactHash: hash, projectionRef: 'prompt:1', errorCode: '', createdAtMs: 18 }],
  };
}

function knowledge(): KnowledgeGovernanceProjection {
  return {
    promotionCandidates: [{ promotionCandidateId: 'candidate:1', evidenceKind: 'external_import', evidenceRef: 'import:1', claimKey: 'external-key', claimText: 'DO_NOT_RENDER_EXTERNAL', ownerKind: 'owner', ownerId: 'owner-a', scopeKind: 'room', scopeId: 'room-1', visibility: 'room', risk: 'medium', candidateHash: hash, conflictClaimRefs: ['claim:old'] }],
    promotionReceipts: [{ promotionReceiptId: 'promotion:1', promotionCandidateId: 'candidate:1', claimVersionId: 'claim:1', scopeKey: 'room:room-1', knowledgeEpoch: 4, candidateHash: hash }],
    claims: [{ claimVersionId: 'claim:1', claimIdentity: 'identity:1', claimKey: 'external-key', claimText: 'DO_NOT_RENDER_EXTERNAL', claimHash: hash, ownerKind: 'owner', ownerId: 'owner-a', scopeKind: 'room', scopeId: 'room-1', visibility: 'room', provenance: { dataOnly: true, evidenceRef: 'import:1' }, contradictionRefs: ['claim:old'] }],
    conflicts: [{ promotionCandidateId: 'candidate:1', state: 'open', claimRefs: ['claim:old'] }],
    lifecycleReceipts: [{ lifecycleReceiptId: 'life:1', claimIdentity: 'identity:old', operation: 'revoke', knowledgeEpoch: 3, scopeKey: 'room:room-1' }],
    epochs: [{ scopeKey: 'room:room-1', knowledgeEpoch: 4 }],
    quarantines: [{ importId: 'import:q', sourceName: 'untrusted.txt', status: 'quarantined', contentHash: hash, findingCount: 2 }],
    outbox: [{ outboxId: 'outbox:1', claimVersionId: 'claim:1', operation: 'index', state: 'dead_letter', attemptCount: 5, lastError: 'adapter unavailable' }],
    tombstones: [{ tombstoneId: 'tomb:1', scopeKey: 'room:room-1', knowledgeEpoch: 4, sessionId: 'session-1', reason: 'revoke' }],
    evalDatasets: [{ datasetId: 'dataset:1', datasetVersion: 1, thresholds: { minUsedCitationRate: 0.95, maxAuthorizationLeakageCount: 0 }, contentHash: hash, expiresAtMs: 999 }],
    searchUseEvalRuns: [{ schemaVersion: 'wisdom-weasel.knowledge-search-use-eval-run.v1', evalRunId: 'knowledge-eval:1', datasetId: 'dataset:1', datasetContentHash: hash, roomBindingId: 'binding:1', traceCount: 6, metrics: { authorizationLeakageCount: 0, usedCitationRate: 1 }, strataMetrics: { 'room:room-1': { usedCitationRate: 1 } }, status: 'passed', failureReasons: [], reportOnly: true, evaluatorId: 'evaluator:1', contentHash: hash, evaluatorSignature: hash, createdAtMs: 20 }],
  };
}
