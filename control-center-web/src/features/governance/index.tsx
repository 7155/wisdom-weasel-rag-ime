import { AlertTriangle, BookOpenCheck, DatabaseZap, ShieldCheck } from 'lucide-react';
import { Children, useMemo, useState, type ReactNode } from 'react';
import { Field, Input } from '@/components/primitives';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  StatusBadge,
} from '@/features/overview/management-ui';
import {
  activeGuards,
  emptyGovernanceProjection,
  emptyKnowledgeGovernanceProjection,
  guardIntegrity,
  matchesScope,
  safeDisplay,
  visibleClaimText,
  type GovernanceProjection,
  type KnowledgeGovernanceProjection,
} from './model';
import './governance.css';

type ScopeFilters = { root: string; owner: string; room: string; session: string };
const emptyFilters: ScopeFilters = { root: '', owner: '', room: '', session: '' };

export function GovernanceFeature() {
  return <GovernanceCenter governance={emptyGovernanceProjection} knowledge={emptyKnowledgeGovernanceProjection} liveRoutesAvailable={false} />;
}

export function GovernanceCenter({
  governance,
  knowledge,
  liveRoutesAvailable = false,
}: {
  governance: GovernanceProjection;
  knowledge: KnowledgeGovernanceProjection;
  liveRoutesAvailable?: boolean;
}) {
  const [filters, setFilters] = useState<ScopeFilters>(emptyFilters);
  const filteredGuards = useMemo(() => governance.guardCandidates.filter((item) => matchesScope(item, filters)), [filters, governance.guardCandidates]);
  const filteredClaims = useMemo(() => knowledge.claims.filter((item) => matchesScope(item, filters)), [filters, knowledge.claims]);
  const filteredPromotionCandidates = useMemo(() => knowledge.promotionCandidates.filter((item) => matchesScope(item, filters)), [filters, knowledge.promotionCandidates]);
  const active = activeGuards(governance);
  const deadOutbox = knowledge.outbox.filter((item) => item.state === 'dead_letter');

  return (
    <ManagementPage
      description="从事故证据到 Guard 指针，以及知识晋升、索引和失效的只读控制面。"
      eyebrow="Room V2"
      routeId="governance"
      title="治理中心"
    >
      {!liveRoutesAvailable ? (
        <InlineNotice title="后端治理 route 尚未发布" tone="warning">
          当前严格只读，不提供批准、激活、回滚或撤销命令。待后端发布带回执的正式读取与命令路由后再接线。
        </InlineNotice>
      ) : null}

      <section className="governance-filters" aria-label="治理范围筛选">
        {(['root', 'owner', 'room', 'session'] as const).map((key) => (
          <Field htmlFor={`governance-filter-${key}`} key={key} label={key === 'root' ? '根任务' : key === 'owner' ? '归属' : key === 'room' ? 'Room' : 'Session'}>
            <Input
              id={`governance-filter-${key}`}
              onChange={(event) => setFilters((current) => ({ ...current, [key]: event.target.value }))}
              placeholder={`${key} ID`}
              value={filters[key]}
            />
          </Field>
        ))}
      </section>

      <MetricStrip items={[
        { label: '事故', value: governance.incidents.length, icon: AlertTriangle, tone: governance.incidents.length ? 'warning' : 'neutral' },
        { label: '候选 Guard', value: governance.guardCandidates.length, icon: ShieldCheck },
        { label: '活动指针', value: active.filter((item) => item.candidate).length, icon: BookOpenCheck, tone: 'success' },
        { label: '索引死信', value: deadOutbox.length, icon: DatabaseZap, tone: deadOutbox.length ? 'danger' : 'neutral' },
      ]} />

      <ManagementSection title="事故、Lesson 与 Guard 候选" description="候选永远不是活动规则；只有 activePointers 能声明活动 Guard。">
        <div className="governance-columns">
          <GovernanceList title="事故记录" empty="没有事故记录">
            {governance.incidents.map((item) => <article key={item.incidentId}><header><strong>{item.taxonomy}</strong><StatusBadge label={`${item.occurrenceCount} 次`} tone="warning" /></header><code>{item.incidentId}</code><p>{item.failureSignature}</p><RefList refs={item.evidenceRefs} /></article>)}
          </GovernanceList>
          <GovernanceList title="Lesson 候选" empty="没有 Lesson 候选">
            {governance.lessons.map((item) => <article key={item.lessonCandidateId}><header><strong>{item.lessonCandidateId}</strong><StatusBadge label="仅候选" /></header><code>incident: {item.incidentId}</code><pre>{safeDisplay({ facts: item.facts, causes: item.causes, applicabilityBoundary: item.applicabilityBoundary, counterexamples: item.counterexamples })}</pre></article>)}
          </GovernanceList>
          <GovernanceList title="Guard 候选" empty="没有匹配的 Guard 候选">
            {filteredGuards.map((item) => {
              const pointer = governance.activePointers.find((entry) => entry.activeGuardCandidateId === item.guardCandidateId);
              const integrity = guardIntegrity(governance, item, pointer);
              return <article key={item.guardCandidateId}><header><strong>{item.guardCandidateId}</strong><StatusBadge label={pointer ? '活动指针' : '仅候选'} tone={pointer ? 'success' : 'neutral'} /></header><div className="governance-badges"><StatusBadge label={`风险 ${item.risk}`} tone="warning" />{integrity.tampered ? <StatusBadge label="完整性异常" tone="danger" /> : null}{integrity.staleEpoch ? <StatusBadge label="Epoch 过期" tone="danger" /> : null}</div><code>owner: {item.owner}</code><pre>{safeDisplay({ scope: item.scope, condition: item.condition, action: item.action, thresholds: item.thresholds })}</pre></article>;
            })}
          </GovernanceList>
        </div>
      </ManagementSection>

      <ManagementSection title="评估、批准、激活、活动指针与回滚" description="批准和激活回执只提供证据，不能替代当前活动指针。">
        <div className="governance-timeline">
          {active.map(({ pointer, candidate }) => <article key={pointer.scopeKey}><header><strong>{pointer.scopeKey}</strong><StatusBadge label={candidate ? '活动' : '空指针'} tone={candidate ? 'success' : 'neutral'} /></header><p>{candidate?.guardCandidateId ?? '当前无活动 Guard'}</p><code>guardEpoch {pointer.guardEpoch}</code></article>)}
          {governance.evalRuns.map((item) => <article key={item.evalRunId}><header><strong>Eval {item.evalRunId}</strong><StatusBadge label={item.status} tone={item.status === 'passed' ? 'success' : 'danger'} /></header><code>{item.guardCandidateId}</code><pre>{safeDisplay(item.metrics)}</pre></article>)}
          {governance.approvals.map((item) => <article key={item.approvalReceiptId}><header><strong>Approval {item.approvalReceiptId}</strong><StatusBadge label={item.decision} /></header><code>{item.guardCandidateId}</code></article>)}
          {governance.activations.map((item) => <article key={item.activationReceiptId}><header><strong>Activation {item.activationReceiptId}</strong><StatusBadge label={`epoch ${item.guardEpoch}`} /></header><code>{item.scopeKey}</code></article>)}
          {governance.rollbacks.map((item) => <article key={item.rollbackReceiptId}><header><strong>Rollback {item.rollbackReceiptId}</strong><StatusBadge label={`epoch ${item.guardEpoch}`} tone="warning" /></header><p>{item.fromGuardCandidateId} → {item.restoredGuardCandidateId ?? '空指针'}</p></article>)}
          {!active.length && !governance.evalRuns.length && !governance.approvals.length && !governance.activations.length && !governance.rollbacks.length ? <p className="governance-empty">没有治理流水</p> : null}
        </div>
      </ManagementSection>

      <ManagementSection title="反思死信与物化状态">
        <div className="governance-columns governance-columns--two">
          <GovernanceList title="Reflection dead-letter" empty="没有反思死信">
            {governance.deadLetters.map((item) => <article key={item.deadLetterId}><header><strong>{item.reasonCode}</strong><StatusBadge label={`${item.attemptCount} 次`} tone="danger" /></header><code>{item.ownerRef}</code><p>{item.nextAction}</p><RefList refs={item.lastEvidenceRefs.map(String)} /></article>)}
          </GovernanceList>
          <GovernanceList title="Guard 物化" empty="没有物化记录">
            {governance.materializations.map((item) => <article key={item.materializationReceiptId}><header><strong>{item.artifactKind}</strong><StatusBadge label={item.status} tone={item.status === 'applied' ? 'success' : item.errorCode ? 'danger' : 'warning'} /></header><code>{item.guardCandidateId} · epoch {item.guardEpoch}</code><p>{item.projectionRef}</p>{item.errorCode ? <p className="governance-error">{item.errorCode}</p> : null}</article>)}
          </GovernanceList>
        </div>
      </ManagementSection>

      <KnowledgeGovernance projection={knowledge} filteredClaims={filteredClaims} filteredPromotionCandidates={filteredPromotionCandidates} />
    </ManagementPage>
  );
}

function KnowledgeGovernance({ projection, filteredClaims, filteredPromotionCandidates }: { projection: KnowledgeGovernanceProjection; filteredClaims: KnowledgeGovernanceProjection['claims']; filteredPromotionCandidates: KnowledgeGovernanceProjection['promotionCandidates'] }) {
  return <ManagementSection title="知识治理" description="晋升、冲突、生命周期、Epoch、隔离、Outbox 与缓存墓碑的完整读模型。">
    <div className="governance-columns governance-columns--two">
      <GovernanceList title="晋升候选与回执" empty="没有晋升候选">
        {filteredPromotionCandidates.map((item) => <article key={item.promotionCandidateId}><header><strong>{item.claimKey}</strong><StatusBadge label={item.risk} tone={item.risk === 'low' ? 'neutral' : 'warning'} /></header><p>{visibleClaimText(item)}</p><code>{item.evidenceKind}: {item.evidenceRef}</code>{item.conflictClaimRefs.length ? <RefList refs={item.conflictClaimRefs} /> : null}</article>)}
        {projection.promotionReceipts.map((item) => <article key={item.promotionReceiptId}><header><strong>{item.promotionReceiptId}</strong><StatusBadge label={`epoch ${item.knowledgeEpoch}`} tone="success" /></header><code>{item.claimVersionId}</code></article>)}
      </GovernanceList>
      <GovernanceList title="当前 Claim 与冲突" empty="没有匹配的 Claim">
        {filteredClaims.map((item) => <article key={item.claimVersionId}><header><strong>{item.claimKey}</strong><StatusBadge label={item.visibility} /></header><p>{visibleClaimText(item)}</p><code>{item.ownerKind}:{item.ownerId} · {item.scopeKind}:{item.scopeId}</code>{item.contradictionRefs.length ? <RefList refs={item.contradictionRefs} /> : null}</article>)}
        {projection.conflicts.map((item) => <article key={item.promotionCandidateId}><header><strong>冲突 {item.promotionCandidateId}</strong><StatusBadge label={item.state} tone={item.state === 'clear' ? 'success' : 'warning'} /></header><RefList refs={item.claimRefs} /></article>)}
      </GovernanceList>
      <GovernanceList title="生命周期、Epoch 与墓碑" empty="没有生命周期记录">
        {projection.lifecycleReceipts.map((item) => <article key={item.lifecycleReceiptId}><header><strong>{item.operation}</strong><StatusBadge label={`epoch ${item.knowledgeEpoch}`} tone="warning" /></header><code>{item.claimIdentity}</code></article>)}
        {projection.epochs.map((item) => <article key={item.scopeKey}><header><strong>{item.scopeKey}</strong><StatusBadge label={`epoch ${item.knowledgeEpoch}`} /></header></article>)}
        {projection.tombstones.map((item) => <article key={item.tombstoneId}><header><strong>缓存墓碑</strong><StatusBadge label={item.reason} tone="warning" /></header><code>{item.sessionId} · epoch {item.knowledgeEpoch}</code></article>)}
      </GovernanceList>
      <GovernanceList title="隔离与索引 Outbox" empty="没有隔离或 Outbox 记录">
        {projection.quarantines.map((item) => <article key={item.importId}><header><strong>{item.sourceName}</strong><StatusBadge label={item.status} tone={item.status === 'quarantined' ? 'danger' : 'success'} /></header><code>{item.contentHash}</code><p>{item.findingCount} 个扫描发现，原始内容不展示</p></article>)}
        {projection.outbox.map((item) => <article key={item.outboxId}><header><strong>{item.operation}</strong><StatusBadge label={item.state} tone={item.state === 'applied' ? 'success' : item.state === 'dead_letter' ? 'danger' : 'warning'} /></header><code>{item.claimVersionId}</code>{item.lastError ? <p className="governance-error">{item.lastError}</p> : null}</article>)}
      </GovernanceList>
    </div>
    <GovernanceList title="Search → Read → Citation 评估（仅报告）" empty="没有检索使用评估">
      {projection.evalDatasets.map((item) => <article key={item.datasetId}><header><strong>阈值 {item.datasetId}</strong><StatusBadge label={`v${item.datasetVersion}`} /></header><pre>{safeDisplay(item.thresholds)}</pre><code>{item.contentHash}</code></article>)}
      {projection.searchUseEvalRuns.map((item) => <article key={item.evalRunId}><header><strong>{item.evalRunId}</strong><div className="governance-badges"><StatusBadge label={item.status} tone={item.status === 'passed' ? 'success' : 'danger'} /><StatusBadge label="reportOnly" tone="info" /></div></header><code>{item.datasetId} · {item.roomBindingId}</code><pre>{safeDisplay({ metrics: item.metrics, strataMetrics: item.strataMetrics, failureReasons: item.failureReasons })}</pre></article>)}
    </GovernanceList>
  </ManagementSection>;
}

function GovernanceList({ children, empty, title }: { children: ReactNode; empty: string; title: string }) {
  const hasChildren = Children.count(children) > 0;
  return <section className="governance-list"><h3>{title}</h3><div>{hasChildren ? children : <p className="governance-empty">{empty}</p>}</div></section>;
}

function RefList({ refs }: { refs: string[] }) {
  return <ul className="governance-refs" aria-label="证据引用">{refs.map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul>;
}
