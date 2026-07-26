import { AlertTriangle, BookOpenCheck, DatabaseZap, ShieldCheck } from 'lucide-react';
import { Children, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useControlTransport } from '@/app/control-transport';
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
  const transport = useControlTransport();
  const [governance, setGovernance] = useState(emptyGovernanceProjection);
  const [knowledge, setKnowledge] = useState(emptyKnowledgeGovernanceProjection);
  const [live, setLive] = useState(false);

  useEffect(() => {
    let active = true;
    void Promise.all([
      transport.request({ pathId: 'agent.governance.read' }),
      transport.request({ pathId: 'agent.knowledgeGovernance.read' }),
    ]).then(([governanceResponse, knowledgeResponse]) => {
      if (!active) return;
      const governancePayload = governanceResponse as { governance?: GovernanceProjection };
      const knowledgePayload = knowledgeResponse as { knowledge?: KnowledgeGovernanceProjection };
      setGovernance(governancePayload.governance ?? emptyGovernanceProjection);
      setKnowledge(knowledgePayload.knowledge ?? emptyKnowledgeGovernanceProjection);
      setLive(true);
    }).catch(() => {
      if (active) setLive(false);
    });
    return () => { active = false; };
  }, [transport]);

  return <GovernanceCenter governance={governance} knowledge={knowledge} liveRoutesAvailable={live} />;
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
      description="查看哪些规则正在保护你的任务和记忆，以及系统遇到问题后留下了什么证据。"
      eyebrow="高级安全记录"
      routeId="governance"
      title="安全与治理"
    >
      {!liveRoutesAvailable ? (
        <InlineNotice title="安全记录暂时只读" tone="warning">
          当前可以查看记录，但不能在这里批准、启用或撤销规则。相关操作准备完整后才会开放。
        </InlineNotice>
      ) : null}

      <details className="governance-filter-disclosure">
        <summary>按内部编号查找记录</summary>
        <p>排查具体任务时使用；日常查看不需要填写。</p>
        <section className="governance-filters" aria-label="安全记录范围筛选">
          {(['root', 'owner', 'room', 'session'] as const).map((key) => (
            <Field htmlFor={`governance-filter-${key}`} key={key} label={key === 'root' ? '整项任务' : key === 'owner' ? '责任方' : key === 'room' ? '协作空间' : '对话'}>
              <Input
                id={`governance-filter-${key}`}
                onChange={(event) => setFilters((current) => ({ ...current, [key]: event.target.value }))}
                placeholder="粘贴内部编号"
                value={filters[key]}
              />
            </Field>
          ))}
        </section>
      </details>

      <MetricStrip items={[
        { label: '异常事件', value: governance.incidents.length, icon: AlertTriangle, tone: governance.incidents.length ? 'warning' : 'neutral' },
        { label: '待确认规则', value: governance.guardCandidates.length, icon: ShieldCheck },
        { label: '正在生效', value: active.filter((item) => item.candidate).length, icon: BookOpenCheck, tone: 'success' },
        { label: '索引失败', value: deadOutbox.length, icon: DatabaseZap, tone: deadOutbox.length ? 'danger' : 'neutral' },
      ]} />

      <ManagementSection title="异常与保护建议" description="系统会从失败中整理经验和保护建议；只有经过评估并明确启用的规则才会真正生效。">
        <div className="governance-columns">
          <GovernanceList title="异常事件" empty="目前没有异常事件">
            {governance.incidents.map((item) => <article key={item.incidentId}><header><strong>{item.taxonomy}</strong><StatusBadge label={`${item.occurrenceCount} 次`} tone="warning" /></header><code>{item.incidentId}</code><p>{item.failureSignature}</p><RefList refs={item.evidenceRefs} /></article>)}
          </GovernanceList>
          <GovernanceList title="经验建议" empty="目前没有待确认的经验建议">
            {governance.lessons.map((item) => <article key={item.lessonCandidateId}><header><strong>{item.lessonCandidateId}</strong><StatusBadge label="尚未采用" /></header><code>来自异常：{item.incidentId}</code><pre>{safeDisplay({ facts: item.facts, causes: item.causes, applicabilityBoundary: item.applicabilityBoundary, counterexamples: item.counterexamples })}</pre></article>)}
          </GovernanceList>
          <GovernanceList title="保护规则建议" empty="目前没有匹配的保护规则建议">
            {filteredGuards.map((item) => {
              const pointer = governance.activePointers.find((entry) => entry.activeGuardCandidateId === item.guardCandidateId);
              const integrity = guardIntegrity(governance, item, pointer);
              return <article key={item.guardCandidateId}><header><strong>{item.guardCandidateId}</strong><StatusBadge label={pointer ? '正在生效' : '尚未启用'} tone={pointer ? 'success' : 'neutral'} /></header><div className="governance-badges"><StatusBadge label={`风险 ${item.risk}`} tone="warning" />{integrity.tampered ? <StatusBadge label="完整性异常" tone="danger" /> : null}{integrity.staleEpoch ? <StatusBadge label="版本已过期" tone="danger" /> : null}</div><code>责任方：{item.owner}</code><pre>{safeDisplay({ scope: item.scope, condition: item.condition, action: item.action, thresholds: item.thresholds })}</pre></article>;
            })}
          </GovernanceList>
        </div>
      </ManagementSection>

      <ManagementSection title="规则启用记录" description="这里保留规则从评估、批准、启用到撤销的完整过程；只有标记为“正在生效”的规则会保护新任务。">
        <div className="governance-timeline">
          {active.map(({ pointer, candidate }) => <article key={pointer.scopeKey}><header><strong>{pointer.scopeKey}</strong><StatusBadge label={candidate ? '正在生效' : '当前无规则'} tone={candidate ? 'success' : 'neutral'} /></header><p>{candidate?.guardCandidateId ?? '这个范围没有正在生效的保护规则'}</p><code>规则版本 {pointer.guardEpoch}</code></article>)}
          {governance.evalRuns.map((item) => <article key={item.evalRunId}><header><strong>评估 {item.evalRunId}</strong><StatusBadge label={item.status} tone={item.status === 'passed' ? 'success' : 'danger'} /></header><code>{item.guardCandidateId}</code><pre>{safeDisplay(item.metrics)}</pre></article>)}
          {governance.approvals.map((item) => <article key={item.approvalReceiptId}><header><strong>批准 {item.approvalReceiptId}</strong><StatusBadge label={item.decision} /></header><code>{item.guardCandidateId}</code></article>)}
          {governance.activations.map((item) => <article key={item.activationReceiptId}><header><strong>启用 {item.activationReceiptId}</strong><StatusBadge label={`版本 ${item.guardEpoch}`} /></header><code>{item.scopeKey}</code></article>)}
          {governance.rollbacks.map((item) => <article key={item.rollbackReceiptId}><header><strong>撤销 {item.rollbackReceiptId}</strong><StatusBadge label={`版本 ${item.guardEpoch}`} tone="warning" /></header><p>{item.fromGuardCandidateId} → {item.restoredGuardCandidateId ?? '无规则'}</p></article>)}
          {!active.length && !governance.evalRuns.length && !governance.approvals.length && !governance.activations.length && !governance.rollbacks.length ? <p className="governance-empty">目前没有规则启用记录</p> : null}
        </div>
      </ManagementSection>

      <ManagementSection title="自动整理与规则应用">
        <div className="governance-columns governance-columns--two">
          <GovernanceList title="等待人工处理" empty="目前没有需要人工处理的整理任务">
            {governance.deadLetters.map((item) => <article key={item.deadLetterId}><header><strong>{item.reasonCode}</strong><StatusBadge label={`${item.attemptCount} 次`} tone="danger" /></header><code>{item.ownerRef}</code><p>{item.nextAction}</p><RefList refs={item.lastEvidenceRefs.map(String)} /></article>)}
          </GovernanceList>
          <GovernanceList title="规则应用记录" empty="目前没有规则应用记录">
            {governance.materializations.map((item) => <article key={item.materializationReceiptId}><header><strong>{item.artifactKind}</strong><StatusBadge label={item.status} tone={item.status === 'applied' ? 'success' : item.errorCode ? 'danger' : 'warning'} /></header><code>{item.guardCandidateId} · 版本 {item.guardEpoch}</code><p>{item.projectionRef}</p>{item.errorCode ? <p className="governance-error">{item.errorCode}</p> : null}</article>)}
          </GovernanceList>
        </div>
      </ManagementSection>

      <KnowledgeGovernance projection={knowledge} filteredClaims={filteredClaims} filteredPromotionCandidates={filteredPromotionCandidates} />
    </ManagementPage>
  );
}

function KnowledgeGovernance({ projection, filteredClaims, filteredPromotionCandidates }: { projection: KnowledgeGovernanceProjection; filteredClaims: KnowledgeGovernanceProjection['claims']; filteredPromotionCandidates: KnowledgeGovernanceProjection['promotionCandidates'] }) {
  return <ManagementSection title="记忆与知识保护" description="查看哪些信息等待确认、哪些记录彼此冲突，以及旧内容如何失效和退出检索。">
    <div className="governance-columns governance-columns--two">
      <GovernanceList title="等待确认的信息" empty="目前没有等待确认的信息">
        {filteredPromotionCandidates.map((item) => <article key={item.promotionCandidateId}><header><strong>{item.claimKey}</strong><StatusBadge label={item.risk} tone={item.risk === 'low' ? 'neutral' : 'warning'} /></header><p>{visibleClaimText(item)}</p><code>{item.evidenceKind}: {item.evidenceRef}</code>{item.conflictClaimRefs.length ? <RefList refs={item.conflictClaimRefs} /> : null}</article>)}
        {projection.promotionReceipts.map((item) => <article key={item.promotionReceiptId}><header><strong>{item.promotionReceiptId}</strong><StatusBadge label={`版本 ${item.knowledgeEpoch}`} tone="success" /></header><code>{item.claimVersionId}</code></article>)}
      </GovernanceList>
      <GovernanceList title="已确认信息与冲突" empty="目前没有匹配的信息">
        {filteredClaims.map((item) => <article key={item.claimVersionId}><header><strong>{item.claimKey}</strong><StatusBadge label={item.visibility} /></header><p>{visibleClaimText(item)}</p><code>{item.ownerKind}:{item.ownerId} · {item.scopeKind}:{item.scopeId}</code>{item.contradictionRefs.length ? <RefList refs={item.contradictionRefs} /> : null}</article>)}
        {projection.conflicts.map((item) => <article key={item.promotionCandidateId}><header><strong>冲突 {item.promotionCandidateId}</strong><StatusBadge label={item.state} tone={item.state === 'clear' ? 'success' : 'warning'} /></header><RefList refs={item.claimRefs} /></article>)}
      </GovernanceList>
      <GovernanceList title="更新与失效记录" empty="目前没有更新或失效记录">
        {projection.lifecycleReceipts.map((item) => <article key={item.lifecycleReceiptId}><header><strong>{item.operation}</strong><StatusBadge label={`版本 ${item.knowledgeEpoch}`} tone="warning" /></header><code>{item.claimIdentity}</code></article>)}
        {projection.epochs.map((item) => <article key={item.scopeKey}><header><strong>{item.scopeKey}</strong><StatusBadge label={`版本 ${item.knowledgeEpoch}`} /></header></article>)}
        {projection.tombstones.map((item) => <article key={item.tombstoneId}><header><strong>已退出缓存</strong><StatusBadge label={item.reason} tone="warning" /></header><code>{item.sessionId} · 版本 {item.knowledgeEpoch}</code></article>)}
      </GovernanceList>
      <GovernanceList title="导入隔离与索引队列" empty="目前没有隔离或索引异常">
        {projection.quarantines.map((item) => <article key={item.importId}><header><strong>{item.sourceName}</strong><StatusBadge label={item.status} tone={item.status === 'quarantined' ? 'danger' : 'success'} /></header><code>{item.contentHash}</code><p>{item.findingCount} 个扫描发现，原始内容不展示</p></article>)}
        {projection.outbox.map((item) => <article key={item.outboxId}><header><strong>{item.operation}</strong><StatusBadge label={item.state} tone={item.state === 'applied' ? 'success' : item.state === 'dead_letter' ? 'danger' : 'warning'} /></header><code>{item.claimVersionId}</code>{item.lastError ? <p className="governance-error">{item.lastError}</p> : null}</article>)}
      </GovernanceList>
    </div>
    <GovernanceList title="检索与引用质量检查" empty="目前没有检索使用评估">
      {projection.evalDatasets.map((item) => <article key={item.datasetId}><header><strong>阈值 {item.datasetId}</strong><StatusBadge label={`v${item.datasetVersion}`} /></header><pre>{safeDisplay(item.thresholds)}</pre><code>{item.contentHash}</code></article>)}
      {projection.searchUseEvalRuns.map((item) => <article key={item.evalRunId}><header><strong>{item.evalRunId}</strong><div className="governance-badges"><StatusBadge label={item.status} tone={item.status === 'passed' ? 'success' : 'danger'} /><StatusBadge label="仅报告" tone="info" /></div></header><code>{item.datasetId} · {item.roomBindingId}</code><pre>{safeDisplay({ metrics: item.metrics, strataMetrics: item.strataMetrics, failureReasons: item.failureReasons })}</pre></article>)}
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
