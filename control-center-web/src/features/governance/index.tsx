import { AlertTriangle, BookOpenCheck, DatabaseZap, ShieldCheck } from 'lucide-react';
import { Children, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { Button, Disclosure, Field, Input, Skeleton } from '@/components/primitives';
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
type GovernanceLoadState = 'readonly' | 'loading' | 'ready' | 'error';
const emptyFilters: ScopeFilters = { root: '', owner: '', room: '', session: '' };

export function GovernanceFeature() {
  const transport = useControlTransport();
  const [governance, setGovernance] = useState(emptyGovernanceProjection);
  const [knowledge, setKnowledge] = useState(emptyKnowledgeGovernanceProjection);
  const [live, setLive] = useState(false);
  const [loadState, setLoadState] = useState<GovernanceLoadState>('loading');
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    setLoadState('loading');
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
      setLoadState('ready');
    }).catch(() => {
      if (!active) return;
      setLive(false);
      setLoadState('error');
    });
    return () => { active = false; };
  }, [reloadToken, transport]);

  return (
    <GovernanceCenter
      governance={governance}
      knowledge={knowledge}
      loadState={loadState}
      liveRoutesAvailable={live}
      onRetry={loadState === 'error' ? () => setReloadToken((current) => current + 1) : undefined}
    />
  );
}

export function GovernanceCenter({
  governance,
  knowledge,
  loadState,
  liveRoutesAvailable = false,
  onRetry,
}: {
  governance: GovernanceProjection;
  knowledge: KnowledgeGovernanceProjection;
  loadState?: GovernanceLoadState;
  liveRoutesAvailable?: boolean;
  onRetry?: () => void;
}) {
  const [filters, setFilters] = useState<ScopeFilters>(emptyFilters);
  const filteredGuards = useMemo(() => governance.guardCandidates.filter((item) => matchesScope(item, filters)), [filters, governance.guardCandidates]);
  const filteredClaims = useMemo(() => knowledge.claims.filter((item) => matchesScope(item, filters)), [filters, knowledge.claims]);
  const filteredPromotionCandidates = useMemo(() => knowledge.promotionCandidates.filter((item) => matchesScope(item, filters)), [filters, knowledge.promotionCandidates]);
  const active = activeGuards(governance);
  const deadOutbox = knowledge.outbox.filter((item) => item.state === 'dead_letter');
  const resolvedLoadState = loadState
    ?? (liveRoutesAvailable ? 'ready' : onRetry ? 'error' : 'readonly');

  return (
    <ManagementPage
      description="先查看当前保护是否生效、是否有需要处理的问题；具体规则和审计证据收在高级详情中。"
      eyebrow="本机保护记录"
      routeId="governance"
      title="安全与治理"
    >
      {resolvedLoadState === 'loading' ? <GovernanceLoadingState /> : null}
      {resolvedLoadState === 'error' ? (
        <div className="governance-load-error">
          <InlineNotice title="暂时无法读取安全记录" tone="danger">
            本机服务没有返回安全记录。重新检查只会再次读取状态，不会改变任何规则。
          </InlineNotice>
          {onRetry ? <Button onClick={onRetry}>重新检查</Button> : null}
        </div>
      ) : null}
      {resolvedLoadState === 'readonly' ? (
        <InlineNotice title={onRetry ? '暂时无法读取安全记录' : '安全记录暂时只读'} tone="warning">
          {onRetry ? '本机服务没有返回安全记录；重新检查不会改变任何规则。' : '当前为查看模式；规则变更会在具备完整审计与授权边界后开放。'}
        </InlineNotice>
      ) : null}
      {resolvedLoadState === 'ready' || resolvedLoadState === 'readonly' ? (
        <>
          <MetricStrip items={[
            { label: '异常事件', value: governance.incidents.length, icon: AlertTriangle, tone: governance.incidents.length ? 'warning' : 'neutral' },
            { label: '待确认规则', value: governance.guardCandidates.length, icon: ShieldCheck },
            { label: '正在生效', value: active.filter((item) => item.candidate).length, icon: BookOpenCheck, tone: 'success' },
            { label: '索引失败', value: deadOutbox.length, icon: DatabaseZap, tone: deadOutbox.length ? 'danger' : 'neutral' },
          ]} />

      <ManagementSection title="当前保护结果" description="只有已启用的规则会保护新任务；发现异常时先处理对应问题，再查看完整审计记录。">
        <dl className="mgmt-kv">
          <dt>正在保护</dt><dd>{active.filter((item) => item.candidate).length ? `${active.filter((item) => item.candidate).length} 条规则正在生效` : '当前没有生效中的保护规则'}</dd>
          <dt>需要处理</dt><dd>{governance.incidents.length || deadOutbox.length ? `${governance.incidents.length + deadOutbox.length} 项需要查看` : '没有待处理的问题'}</dd>
          <dt>下一步</dt><dd>{governance.guardCandidates.length ? '查看下方高级详情，核对待评估的保护建议。' : '继续正常使用；系统会在发现问题时记录建议。'}</dd>
        </dl>
      </ManagementSection>

      <Disclosure className="governance-advanced" summary="高级：规则管理与审计">
        <Disclosure className="governance-filter-disclosure" summary="精确查找特定记录">
          <p>手头已有完整记录编号时使用；日常查看无需填写。</p>
          <section className="governance-filters" aria-label="安全记录范围筛选">
            {(['root', 'owner', 'room', 'session'] as const).map((key) => (
              <Field htmlFor={`governance-filter-${key}`} key={key} label={key === 'root' ? '整项任务' : key === 'owner' ? '责任方' : key === 'room' ? '协作空间' : '对话'}>
                <Input
                  id={`governance-filter-${key}`}
                  onChange={(event) => setFilters((current) => ({ ...current, [key]: event.target.value }))}
                  placeholder="输入完整记录编号"
                  value={filters[key]}
                />
              </Field>
            ))}
          </section>
        </Disclosure>

      <ManagementSection title="异常与保护建议" description="系统会从失败中整理经验和保护建议；只有经过评估并明确启用的规则才会真正生效。">
        <div className="governance-columns">
          <GovernanceList title="异常事件" empty="目前没有异常事件">
            {governance.incidents.map((item) => <article key={item.incidentId}><header><strong>{incidentLabel(item.taxonomy)}</strong><StatusBadge label={`${item.occurrenceCount} 次`} tone="warning" /></header><p>系统已经记录这类异常，后续建议会先经过评估再启用。</p><RecordDetails rows={[
              ['异常记录编号', item.incidentId],
              ['异常分类', item.taxonomy],
              ['失败特征', item.failureSignature],
              ['证据引用', item.evidenceRefs.join('\n')],
            ]} /></article>)}
          </GovernanceList>
          <GovernanceList title="经验建议" empty="目前没有待确认的经验建议">
            {governance.lessons.map((item) => <article key={item.lessonCandidateId}><header><strong>可复核的处理经验</strong><StatusBadge label="尚未采用" /></header><p>系统已从异常中整理出建议；确认适用范围后才能转为保护规则。</p><RecordDetails rows={[
              ['建议编号', item.lessonCandidateId],
              ['来源异常编号', item.incidentId],
              ['建议状态', item.state],
            ]} payloads={[
              ['依据与边界', { facts: item.facts, causes: item.causes, applicabilityBoundary: item.applicabilityBoundary, counterexamples: item.counterexamples }],
            ]} /></article>)}
          </GovernanceList>
          <GovernanceList title="保护规则建议" empty="目前没有匹配的保护规则建议">
            {filteredGuards.map((item) => {
              const pointer = governance.activePointers.find((entry) => entry.activeGuardCandidateId === item.guardCandidateId);
              const integrity = guardIntegrity(governance, item, pointer);
              return <article key={item.guardCandidateId}><header><strong>{guardSummary(item.action)}</strong><StatusBadge label={pointer ? '正在生效' : '尚未启用'} tone={pointer ? 'success' : 'neutral'} /></header><div className="governance-badges"><StatusBadge label={riskLabel(item.risk)} tone="warning" />{integrity.tampered ? <StatusBadge label="完整性异常" tone="danger" /> : null}{integrity.staleEpoch ? <StatusBadge label="版本已过期" tone="danger" /> : null}</div><p>适用于当前责任范围；启用前需要完成评估与批准。</p><RecordDetails rows={[
                ['规则建议编号', item.guardCandidateId],
                ['来源建议编号', item.lessonCandidateId],
                ['责任方编号', item.owner],
                ['原始风险等级', item.risk],
                ['原始状态', item.state],
              ]} payloads={[
                ['规则条件与动作', { scope: item.scope, condition: item.condition, action: item.action, thresholds: item.thresholds }],
              ]} /></article>;
            })}
          </GovernanceList>
        </div>
      </ManagementSection>

      <ManagementSection title="规则启用记录" description="这里保留规则从评估、批准、启用到撤销的完整过程；只有标记为“正在生效”的规则会保护新任务。">
        <div className="governance-timeline">
          {active.map(({ pointer, candidate }) => <article key={pointer.scopeKey}><header><strong>{scopeLabel(pointer.scopeKey)}</strong><StatusBadge label={candidate ? '正在生效' : '当前无规则'} tone={candidate ? 'success' : 'neutral'} /></header><p>{candidate ? '这个范围已经由一条已确认规则保护。' : '这个范围暂时没有生效中的保护规则。'}</p><span className="governance-record-version">规则版本 {pointer.guardEpoch}</span><RecordDetails rows={[
            ['保护范围编号', pointer.scopeKey],
            ['规则建议编号', candidate?.guardCandidateId],
            ['启用记录编号', pointer.activationReceiptId],
          ]} /></article>)}
          {governance.evalRuns.map((item) => <article key={item.evalRunId}><header><strong>规则评估</strong><StatusBadge label={statusLabel(item.status)} tone={item.status === 'passed' ? 'success' : 'danger'} /></header><p>这次评估检查规则是否达到启用要求。</p><RecordDetails rows={[
            ['评估运行编号', item.evalRunId],
            ['规则建议编号', item.guardCandidateId],
            ['评估方式', item.mode],
            ['原始状态', item.status],
          ]} payloads={[["评估结果", item.metrics]]} /></article>)}
          {governance.approvals.map((item) => <article key={item.approvalReceiptId}><header><strong>规则批准记录</strong><StatusBadge label={decisionLabel(item.decision)} /></header><p>这条记录说明规则是否已获得正式批准。</p><RecordDetails rows={[
            ['批准记录编号', item.approvalReceiptId],
            ['规则建议编号', item.guardCandidateId],
            ['批准方编号', item.authorityRef],
            ['原始决定', item.decision],
          ]} /></article>)}
          {governance.activations.map((item) => <article key={item.activationReceiptId}><header><strong>规则已启用</strong><StatusBadge label={`版本 ${item.guardEpoch}`} tone="success" /></header><p>{scopeLabel(item.scopeKey)}从这条记录起受到保护。</p><RecordDetails rows={[
            ['启用记录编号', item.activationReceiptId],
            ['规则建议编号', item.guardCandidateId],
            ['保护范围编号', item.scopeKey],
            ['评估运行编号', item.evalRunIds.join('\n')],
          ]} /></article>)}
          {governance.rollbacks.map((item) => <article key={item.rollbackReceiptId}><header><strong>规则已撤销</strong><StatusBadge label={`版本 ${item.guardEpoch}`} tone="warning" /></header><p>{item.restoredGuardCandidateId ? '已恢复上一条可用规则。' : '这个范围现在没有生效中的保护规则。'}</p><RecordDetails rows={[
            ['撤销记录编号', item.rollbackReceiptId],
            ['被撤销规则编号', item.fromGuardCandidateId],
            ['恢复规则编号', item.restoredGuardCandidateId],
          ]} /></article>)}
          {!active.length && !governance.evalRuns.length && !governance.approvals.length && !governance.activations.length && !governance.rollbacks.length ? <p className="governance-empty">目前没有规则启用记录</p> : null}
        </div>
      </ManagementSection>

      <ManagementSection title="自动整理与规则应用">
        <div className="governance-columns governance-columns--two">
          <GovernanceList title="等待人工处理" empty="目前没有需要人工处理的整理任务">
            {governance.deadLetters.map((item) => <article key={item.deadLetterId}><header><strong>{deadLetterLabel(item.reasonCode)}</strong><StatusBadge label={`${item.attemptCount} 次尝试`} tone="danger" /></header><p>{nextActionLabel(item.nextAction)}</p><RecordDetails rows={[
              ['待处理记录编号', item.deadLetterId],
              ['来源异常编号', item.incidentId],
              ['责任方编号', item.ownerRef],
              ['原始原因', item.reasonCode],
              ['证据引用', item.lastEvidenceRefs.map(String).join('\n')],
            ]} /></article>)}
          </GovernanceList>
          <GovernanceList title="规则应用记录" empty="目前没有规则应用记录">
            {governance.materializations.map((item) => <article key={item.materializationReceiptId}><header><strong>{artifactLabel(item.artifactKind)}</strong><StatusBadge label={statusLabel(item.status)} tone={item.status === 'applied' ? 'success' : item.errorCode ? 'danger' : 'warning'} /></header><p>{item.errorCode ? '最近一次应用没有完成，需要检查记录详情。' : '规则已经同步到对应保护位置。'}</p><span className="governance-record-version">规则版本 {item.guardEpoch}</span><RecordDetails rows={[
              ['应用记录编号', item.materializationReceiptId],
              ['规则建议编号', item.guardCandidateId],
              ['投影引用', item.projectionRef],
              ['原始类型', item.artifactKind],
              ['原始状态', item.status],
              ['错误代码', item.errorCode],
            ]} /></article>)}
          </GovernanceList>
        </div>
      </ManagementSection>

      <KnowledgeGovernance projection={knowledge} filteredClaims={filteredClaims} filteredPromotionCandidates={filteredPromotionCandidates} />
          </Disclosure>
        </>
      ) : null}
    </ManagementPage>
  );
}

function GovernanceLoadingState() {
  return (
    <div aria-live="polite" className="governance-loading" role="status">
      <ManagementSection
        description="正在读取生效中的规则、异常事件和索引状态。完成前不会显示推测结果。"
        title="正在核对本机保护"
      >
        <div aria-hidden="true" className="governance-loading__skeletons">
          <Skeleton />
          <Skeleton />
          <Skeleton />
          <Skeleton />
        </div>
      </ManagementSection>
    </div>
  );
}

function KnowledgeGovernance({ projection, filteredClaims, filteredPromotionCandidates }: { projection: KnowledgeGovernanceProjection; filteredClaims: KnowledgeGovernanceProjection['claims']; filteredPromotionCandidates: KnowledgeGovernanceProjection['promotionCandidates'] }) {
  return <ManagementSection title="记忆与知识保护" description="查看哪些信息等待确认、哪些记录彼此冲突，以及旧内容如何失效和退出检索。">
    <div className="governance-columns governance-columns--two">
      <GovernanceList title="等待确认的信息" empty="目前没有等待确认的信息">
        {filteredPromotionCandidates.map((item) => <article key={item.promotionCandidateId}><header><strong>待确认信息</strong><StatusBadge label={riskLabel(item.risk)} tone={item.risk === 'low' ? 'neutral' : 'warning'} /></header><p>{visibleClaimText(item)}</p><p className="governance-record-summary">{evidenceLabel(item.evidenceKind)} · {scopeKindLabel(item.scopeKind)}</p><RecordDetails rows={[
          ['候选记录编号', item.promotionCandidateId],
          ['信息键', item.claimKey],
          ['证据类型', item.evidenceKind],
          ['证据引用', item.evidenceRef],
          ['归属类型', item.ownerKind],
          ['归属编号', item.ownerId],
          ['范围类型', item.scopeKind],
          ['范围编号', item.scopeId],
          ['原始可见性', item.visibility],
          ['原始风险等级', item.risk],
          ['冲突记录引用', item.conflictClaimRefs.join('\n')],
        ]} /></article>)}
        {projection.promotionReceipts.map((item) => <article key={item.promotionReceiptId}><header><strong>信息已确认</strong><StatusBadge label={`版本 ${item.knowledgeEpoch}`} tone="success" /></header><p>这项信息已经进入受保护知识。</p><RecordDetails rows={[
          ['确认记录编号', item.promotionReceiptId],
          ['候选记录编号', item.promotionCandidateId],
          ['信息版本编号', item.claimVersionId],
          ['保护范围编号', item.scopeKey],
        ]} /></article>)}
      </GovernanceList>
      <GovernanceList title="已确认信息与冲突" empty="目前没有匹配的信息">
        {filteredClaims.map((item) => <article key={item.claimVersionId}><header><strong>已确认信息</strong><StatusBadge label={visibilityLabel(item.visibility)} /></header><p>{visibleClaimText(item)}</p><p className="governance-record-summary">{ownerKindLabel(item.ownerKind)} · {scopeKindLabel(item.scopeKind)}</p><RecordDetails rows={[
          ['信息版本编号', item.claimVersionId],
          ['信息身份编号', item.claimIdentity],
          ['信息键', item.claimKey],
          ['归属类型', item.ownerKind],
          ['归属编号', item.ownerId],
          ['范围类型', item.scopeKind],
          ['范围编号', item.scopeId],
          ['原始可见性', item.visibility],
          ['矛盾记录引用', item.contradictionRefs.join('\n')],
        ]} payloads={[["来源信息", item.provenance]]} /></article>)}
        {projection.conflicts.map((item) => <article key={item.promotionCandidateId}><header><strong>发现信息冲突</strong><StatusBadge label={conflictStateLabel(item.state)} tone={item.state === 'clear' ? 'success' : 'warning'} /></header><p>{item.claimRefs.length} 条信息需要核对后再决定保留哪一条。</p><RecordDetails rows={[
          ['候选记录编号', item.promotionCandidateId],
          ['原始状态', item.state],
          ['冲突信息引用', item.claimRefs.join('\n')],
        ]} /></article>)}
      </GovernanceList>
      <GovernanceList title="更新与失效记录" empty="目前没有更新或失效记录">
        {projection.lifecycleReceipts.map((item) => <article key={item.lifecycleReceiptId}><header><strong>{operationLabel(item.operation)}</strong><StatusBadge label={`版本 ${item.knowledgeEpoch}`} tone="warning" /></header><p>这项信息的生命周期已经更新。</p><RecordDetails rows={[
          ['生命周期记录编号', item.lifecycleReceiptId],
          ['信息身份编号', item.claimIdentity],
          ['保护范围编号', item.scopeKey],
          ['原始操作', item.operation],
        ]} /></article>)}
        {projection.epochs.map((item) => <article key={item.scopeKey}><header><strong>{scopeLabel(item.scopeKey)}</strong><StatusBadge label={`版本 ${item.knowledgeEpoch}`} /></header><p>这个范围的知识保护版本已经更新。</p><RecordDetails rows={[["保护范围编号", item.scopeKey]]} /></article>)}
        {projection.tombstones.map((item) => <article key={item.tombstoneId}><header><strong>已退出检索</strong><StatusBadge label={reasonLabel(item.reason)} tone="warning" /></header><p>这段对话的旧内容不再用于后续检索。</p><span className="governance-record-version">知识版本 {item.knowledgeEpoch}</span><RecordDetails rows={[
          ['失效记录编号', item.tombstoneId],
          ['保护范围编号', item.scopeKey],
          ['对话编号', item.sessionId],
          ['原始原因', item.reason],
        ]} /></article>)}
      </GovernanceList>
      <GovernanceList title="导入隔离与索引队列" empty="目前没有隔离或索引异常">
        {projection.quarantines.map((item) => <article key={item.importId}><header><strong>{item.sourceName || '待检查的导入材料'}</strong><StatusBadge label={statusLabel(item.status)} tone={item.status === 'quarantined' ? 'danger' : 'success'} /></header><p>{item.findingCount} 个扫描发现，原始内容不展示。</p><RecordDetails rows={[
          ['导入记录编号', item.importId],
          ['内容校验值', item.contentHash],
          ['原始状态', item.status],
        ]} /></article>)}
        {projection.outbox.map((item) => <article key={item.outboxId}><header><strong>{operationLabel(item.operation)}</strong><StatusBadge label={statusLabel(item.state)} tone={item.state === 'applied' ? 'success' : item.state === 'dead_letter' ? 'danger' : 'warning'} /></header><p>{item.lastError ? '最近一次更新没有完成，请检查记录详情。' : '这项更新正在按顺序处理。'}</p><RecordDetails rows={[
          ['队列记录编号', item.outboxId],
          ['信息版本编号', item.claimVersionId],
          ['原始操作', item.operation],
          ['原始状态', item.state],
          ['最后错误', item.lastError],
        ]} /></article>)}
      </GovernanceList>
    </div>
    <GovernanceList title="检索与引用质量检查" empty="目前没有检索使用评估">
      {projection.evalDatasets.map((item) => <article key={item.datasetId}><header><strong>引用质量标准</strong><StatusBadge label={`第 ${item.datasetVersion} 版`} /></header><p>用于检查引用是否充分，以及是否越过授权边界。</p><RecordDetails rows={[
        ['标准数据编号', item.datasetId],
        ['内容校验值', item.contentHash],
      ]} payloads={[["检查阈值", item.thresholds]]} /></article>)}
      {projection.searchUseEvalRuns.map((item) => <article key={item.evalRunId}><header><strong>引用质量检查</strong><div className="governance-badges"><StatusBadge label={statusLabel(item.status)} tone={item.status === 'passed' ? 'success' : 'danger'} /><StatusBadge label="仅报告" tone="info" /></div></header><p>已检查 {item.traceCount} 条使用记录；结果只用于报告，不会自动改变知识。</p><RecordDetails rows={[
        ['检查运行编号', item.evalRunId],
        ['标准数据编号', item.datasetId],
        ['协作绑定编号', item.roomBindingId],
        ['评估方编号', item.evaluatorId],
        ['原始状态', item.status],
      ]} payloads={[["检查结果", { metrics: item.metrics, strataMetrics: item.strataMetrics, failureReasons: item.failureReasons }]]} /></article>)}
    </GovernanceList>
  </ManagementSection>;
}

function GovernanceList({ children, empty, title }: { children: ReactNode; empty: string; title: string }) {
  const hasChildren = Children.count(children) > 0;
  return <section className="governance-list"><h3>{title}</h3><div>{hasChildren ? children : <p className="governance-empty">{empty}</p>}</div></section>;
}

function RecordDetails({ rows, payloads = [] }: { rows: Array<[string, unknown]>; payloads?: Array<[string, unknown]> }) {
  const visibleRows = rows.filter(([, value]) => value !== undefined && value !== null && String(value).trim());
  if (!visibleRows.length && !payloads.length) return null;
  return (
    <Disclosure className="governance-record-details" summary="高级：记录详情">
      {visibleRows.length ? <dl>{visibleRows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><code>{String(value)}</code></dd></div>)}</dl> : null}
      {payloads.map(([label, value]) => <section key={label}><h4>{label}</h4><pre>{safeDisplay(value)}</pre></section>)}
    </Disclosure>
  );
}

function incidentLabel(value: string): string {
  return ({ routing_loop: '重复路由', permission_denied: '权限受限', timeout: '处理超时', stale_state: '状态已过期' } as Record<string, string>)[value] ?? '运行异常';
}

function guardSummary(action: Record<string, unknown>): string {
  return action.stop === true ? '阻止异常执行继续扩散' : '限制异常执行范围';
}

function riskLabel(value: string): string {
  return ({ low: '低风险', medium: '中风险', high: '高风险', critical: '极高风险' } as Record<string, string>)[value] ?? '风险待确认';
}

function statusLabel(value: string): string {
  return ({ applied: '已应用', candidate_only: '等待评估', clear: '已解决', completed: '已完成', dead_letter: '需要人工处理', failed: '未通过', open: '待处理', passed: '已通过', pending: '等待处理', quarantined: '已隔离', rejected: '未通过', running: '处理中' } as Record<string, string>)[value] ?? '状态待确认';
}

function decisionLabel(value: string): string {
  return ({ approved: '已批准', rejected: '未批准', pending: '等待决定' } as Record<string, string>)[value] ?? '决定待确认';
}

function artifactLabel(value: string): string {
  return ({ prompt_guard: '对话保护规则', runtime_guard: '运行保护规则', retrieval_guard: '检索保护规则' } as Record<string, string>)[value] ?? '保护规则';
}

function deadLetterLabel(value: string): string {
  return ({ retry_exhausted: '多次尝试后仍未完成', invalid_state: '记录状态不完整', unavailable: '相关服务暂不可用' } as Record<string, string>)[value] ?? '需要人工检查';
}

function nextActionLabel(value: string): string {
  if (/人工|复核|检查/u.test(value)) return '需要人工复核后再继续。';
  return '请检查记录详情并决定下一步。';
}

function evidenceLabel(value: string): string {
  return ({ external_import: '外部导入', local_observation: '本机观察', user_confirmed: '用户确认' } as Record<string, string>)[value] ?? '已有来源';
}

function visibilityLabel(value: string): string {
  return ({ private: '仅自己可见', room: '协作范围可见', secret: '敏感内容', shared: '项目共享', user: '仅自己可见' } as Record<string, string>)[value] ?? '可见范围待确认';
}

function ownerKindLabel(value: string): string {
  return ({ agent: '伙伴记忆', owner: '指定责任方', room: '协作记忆', shared: '项目共享', user: '个人记忆' } as Record<string, string>)[value] ?? '其他归属';
}

function scopeKindLabel(value: string): string {
  return ({ owner: '责任方范围', project: '项目范围', root: '整项任务', room: '协作空间范围', session: '对话范围', shared: '共享范围', user: '个人范围' } as Record<string, string>)[value] ?? '其他范围';
}

function conflictStateLabel(value: string): string {
  return ({ clear: '已解决', open: '等待核对', resolved: '已解决' } as Record<string, string>)[value] ?? '等待核对';
}

function operationLabel(value: string): string {
  return ({ create: '信息已建立', index: '索引更新', promote: '信息已确认', revoke: '信息已撤回', update: '信息已更新' } as Record<string, string>)[value] ?? '信息已更新';
}

function reasonLabel(value: string): string {
  return ({ expired: '已过期', revoke: '已撤回', superseded: '已被新内容替代' } as Record<string, string>)[value] ?? '不再使用';
}

function scopeLabel(value: string): string {
  return scopeKindLabel(value.split(':', 1)[0] ?? '');
}
