import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import { GovernanceCenter, GovernanceFeature } from './index';
import { activeGuards, safeDisplay, type GovernanceProjection, type KnowledgeGovernanceProjection } from './model';

const hash = 'a'.repeat(64);

describe('GovernanceCenter', () => {
  afterEach(cleanup);

  it('shows a truthful loading state and waits for both protection projections before rendering metrics', async () => {
    const pendingGovernance = deferred<{ governance: GovernanceProjection }>();
    const pendingKnowledge = deferred<{ knowledge: KnowledgeGovernanceProjection }>();
    const transport = new StubControlTransport('native', {
      'agent.governance.read': () => pendingGovernance.promise,
      'agent.knowledgeGovernance.read': () => pendingKnowledge.promise,
    });

    render(
      <ControlTransportProvider transport={transport}>
        <GovernanceFeature />
      </ControlTransportProvider>,
    );

    expect(screen.getByText('正在核对本机保护')).toBeInTheDocument();
    expect(screen.queryByText('安全记录暂时只读')).not.toBeInTheDocument();
    expect(screen.queryByText('异常事件', { selector: 'dt' })).not.toBeInTheDocument();
    expect(screen.queryByText('当前保护结果')).not.toBeInTheDocument();

    await act(async () => {
      pendingGovernance.resolve({ governance: governance() });
      pendingKnowledge.resolve({ knowledge: knowledge() });
    });

    expect(await screen.findByText('当前保护结果')).toBeInTheDocument();
    const incidentMetric = screen.getByText('异常事件', { selector: 'dt' }).parentElement;
    expect(incidentMetric).not.toBeNull();
    expect(within(incidentMetric!).getByText('1')).toBeInTheDocument();
    expect(screen.queryByText('正在核对本机保护')).not.toBeInTheDocument();
  });

  it('keeps failed reads out of the metrics and retries without changing any rule', async () => {
    let unavailable = true;
    const transport = new StubControlTransport('native', {
      'agent.governance.read': () => {
        if (unavailable) throw new Error('service unavailable');
        return { governance: governance() };
      },
      'agent.knowledgeGovernance.read': { knowledge: knowledge() },
    });

    render(
      <ControlTransportProvider transport={transport}>
        <GovernanceFeature />
      </ControlTransportProvider>,
    );

    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法读取安全记录');
    expect(screen.queryByText('异常事件', { selector: 'dt' })).not.toBeInTheDocument();
    expect(screen.queryByText('当前保护结果')).not.toBeInTheDocument();

    unavailable = false;
    fireEvent.click(screen.getByRole('button', { name: '重新检查' }));

    expect(await screen.findByText('当前保护结果')).toBeInTheDocument();
    expect(transport.requests.filter((request) => request.pathId === 'agent.governance.read')).toHaveLength(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('is strictly read-only while formal backend routes are missing', () => {
    render(<GovernanceCenter governance={governance()} knowledge={knowledge()} />);
    expect(screen.getByText('本机保护记录', { selector: '.mgmt-page__eyebrow' })).toBeInTheDocument();
    expect(screen.getByText('当前保护结果')).toBeInTheDocument();
    expect(screen.getByText('安全记录暂时只读')).toBeInTheDocument();
    expect(screen.getByText('当前为查看模式；规则变更会在具备完整审计与授权边界后开放。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /批准|激活|回滚|撤销/ })).not.toBeInTheDocument();
  });

  it('derives active state only from activePointers, never an activation receipt', () => {
    const projection = governance();
    projection.activePointers = [];
    expect(activeGuards(projection)).toEqual([]);
    render(<GovernanceCenter governance={projection} knowledge={knowledge()} />);
    fireEvent.click(screen.getByText('高级：规则管理与审计'));
    expect(screen.getByText('规则已启用')).toBeVisible();
    const activeMetric = screen.getByText('正在生效', { selector: 'dt' }).parentElement;
    expect(activeMetric).not.toBeNull();
    expect(within(activeMetric!).getByText('0')).toBeVisible();
    expect(screen.queryByText('活动指针', { selector: '.mgmt-status' })).not.toBeInTheDocument();
  });

  it('surfaces tamper and stale epoch evidence and keeps report-only eval explicit', () => {
    const projection = governance();
    projection.approvals[0]!.candidateHash = 'b'.repeat(64);
    projection.materializations[0]!.guardEpoch = 6;
    render(<GovernanceCenter governance={projection} knowledge={knowledge()} />);
    fireEvent.click(screen.getByText('高级：规则管理与审计'));
    expect(screen.getByText('完整性异常')).toBeInTheDocument();
    expect(screen.getByText('版本已过期')).toBeInTheDocument();
    expect(screen.getByText('仅报告')).toBeInTheDocument();
    const qualityCheck = screen.getByText('引用质量检查').closest('article');
    const qualityStandard = screen.getByText('引用质量标准').closest('article');
    expect(qualityCheck).not.toBeNull();
    expect(qualityStandard).not.toBeNull();
    fireEvent.click(within(qualityCheck!).getByText('高级：记录详情'));
    fireEvent.click(within(qualityStandard!).getByText('高级：记录详情'));
    expect(within(qualityCheck!).getByText(/authorizationLeakageCount/)).toBeVisible();
    expect(within(qualityStandard!).getByText(/minUsedCitationRate/)).toBeVisible();
  });

  it('keeps internal identifiers and raw enums behind per-record technical disclosure', () => {
    render(<GovernanceCenter governance={governance()} knowledge={knowledge()} />);

    const outerDisclosure = screen.getByText('高级：规则管理与审计').closest('details');
    expect(outerDisclosure).not.toBeNull();
    expect(outerDisclosure).not.toHaveAttribute('open');
    expect(screen.queryByRole('textbox', { name: '对话' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('高级：规则管理与审计'));
    expect(screen.getByText('重复路由')).toBeVisible();
    expect(screen.getByText('高风险')).toBeVisible();
    expect(screen.getByText('协作范围可见')).toBeVisible();
    expect(screen.getByText('指定责任方 · 协作空间范围')).toBeVisible();
    expect(screen.getByText('已退出检索')).toBeVisible();

    const confirmed = screen.getByText('已确认信息').closest('article');
    expect(confirmed).not.toBeNull();
    expect(within(confirmed!).queryByText('owner-a')).not.toBeInTheDocument();
    expect(within(confirmed!).queryByText('room-1')).not.toBeInTheDocument();
    expect(within(confirmed!).getByText('高级：记录详情').closest('details')).not.toHaveAttribute('open');

    fireEvent.click(within(confirmed!).getByText('高级：记录详情'));
    expect(within(confirmed!).getByText('owner-a')).toBeVisible();
    expect(within(confirmed!).getByText('room-1')).toBeVisible();

    const tombstone = screen.getByText('已退出检索').closest('article');
    expect(tombstone).not.toBeNull();
    expect(within(tombstone!).queryByText('session-1')).not.toBeInTheDocument();
    fireEvent.click(within(tombstone!).getByText('高级：记录详情'));
    expect(within(tombstone!).getByText('session-1')).toBeVisible();
  });

  it('hides secret and external raw text, redacts sensitive object keys, and supports scoped filters', () => {
    const data = knowledge();
    data.claims.push({ claimVersionId: 'claim:secret', claimIdentity: 'secret', claimKey: 'secret-key', claimText: 'DO_NOT_RENDER_SECRET', claimHash: hash, ownerKind: 'owner', ownerId: 'owner-b', scopeKind: 'session', scopeId: 'session-secret', visibility: 'secret', provenance: {}, contradictionRefs: [] });
    render(<GovernanceCenter governance={governance()} knowledge={data} />);
    expect(screen.queryByText('DO_NOT_RENDER_EXTERNAL')).not.toBeInTheDocument();
    expect(screen.queryByText('DO_NOT_RENDER_SECRET')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('高级：规则管理与审计'));
    expect(screen.getAllByText('[外部内容仅作为数据引用，不展示原文]')).toHaveLength(2);
    expect(screen.getByText('[秘密内容已隐藏]')).toBeInTheDocument();
    expect(safeDisplay({ apiKey: 'RAW_KEY', nested: { password: 'RAW_PASSWORD', ok: 1 } })).toBe('{\n  "apiKey": "[已隐藏]",\n  "nested": {\n    "password": "[已隐藏]",\n    "ok": 1\n  }\n}');
    fireEvent.click(screen.getByText('精确查找特定记录'));
    fireEvent.change(screen.getByLabelText('对话'), { target: { value: 'session-secret' } });
    const secretRecord = screen.getByText('[秘密内容已隐藏]').closest('article');
    expect(secretRecord).not.toBeNull();
    fireEvent.click(within(secretRecord!).getByText('高级：记录详情'));
    expect(within(secretRecord!).getByText('secret-key')).toBeInTheDocument();
    expect(screen.queryByText('external-key')).not.toBeInTheDocument();
  });

  it('keeps long identifiers contained and exposes every filter by accessible label', () => {
    const projection = governance();
    projection.incidents[0]!.failureSignature = 'failure/'.repeat(80);
    const { container } = render(<GovernanceCenter governance={projection} knowledge={knowledge()} />);
    fireEvent.click(screen.getByText('高级：规则管理与审计'));
    fireEvent.click(screen.getByText('精确查找特定记录'));
    expect(screen.getByRole('region', { name: '安全记录范围筛选' })).toBeInTheDocument();
    for (const label of ['整项任务', '责任方', '协作空间', '对话']) expect(screen.getByLabelText(label)).toBeInTheDocument();
    expect(container.querySelector('.governance-columns')).toBeInTheDocument();
    const incident = screen.getByText('重复路由').closest('article');
    expect(incident).not.toBeNull();
    expect(within(incident!).queryByText('failure/'.repeat(80))).not.toBeInTheDocument();
    fireEvent.click(within(incident!).getByText('高级：记录详情'));
    expect(within(incident!).getByText('failure/'.repeat(80))).toBeVisible();
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

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}
