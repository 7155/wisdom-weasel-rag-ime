import type { ReactNode } from 'react';
import type { TraceAuditReportModel } from './report-model';
import {
  traceCandidateActionLabel,
  type TraceCandidateAction,
  type TraceOptimizationReadingModel,
  type TraceReadingCandidate,
  type TraceReadingComparison,
} from './optimization-report-model';

export interface TraceOptimizationReportActions {
  onCandidateAction?: (candidateId: string, action: TraceCandidateAction) => void;
  onRunCandidate?: (candidateId: string) => void;
  onCancelCandidate?: (candidateId: string) => void;
  pendingCandidateId?: string;
  actionError?: string;
}

/** Shared foreground for the interactive App and the static HTML export. */
export function TraceOptimizationReportContent({ model, reading, onOpenEvidence, exported = false, appReturnHref, ...actions }: {
  model: TraceAuditReportModel;
  reading: TraceOptimizationReadingModel;
  onOpenEvidence?: (evidenceId: string) => void;
  exported?: boolean;
  appReturnHref?: string;
} & TraceOptimizationReportActions) {
  const evidence = (ids: string[]) => <ReadingEvidence aliases={model.evidenceAliases} ids={ids} onOpen={onOpenEvidence} />;
  return <div className="trace-audit__scan-layer trace-reading" onClick={exported ? undefined : (event) => {
    const link = event.target instanceof Element ? event.target.closest('a[href^="#"]') : null;
    if (!link) return;
    const id = link.getAttribute('href')!.slice(1);
    const destination = [...event.currentTarget.querySelectorAll<HTMLElement>('[id]')].find((element) => element.id === id);
    if (!destination) return;
    event.preventDefault();
    if (destination instanceof HTMLDetailsElement) destination.open = true;
    destination.scrollIntoView({ block: 'start' });
  }}>
    <section aria-labelledby="trace-reading-objective" className="trace-reading__objective">
      <h3 id="trace-reading-objective">本次希望改善什么</h3>
      <p>{reading.objective}</p>
      <dl className="trace-reading__scope"><div><dt>任务模式</dt><dd>{reading.modeLabel}</dd></div><div><dt>关注方向</dt><dd>{reading.focusLabel}</dd></div><div><dt>来源</dt><dd>{reading.sourceCount} 段对话或运行记录</dd></div></dl>
    </section>
    <section aria-labelledby="trace-reading-conclusion" className="trace-reading__conclusion">
      <h3 id="trace-reading-conclusion">{reading.recommendation}</h3>
      <p className="trace-reading__headline">{model.plainConclusion}</p>
      <p>{reading.recommendationDetail}</p>
      {model.impact ? <p>{model.impact}</p> : null}
    </section>
    <nav aria-label="报告阅读目录" className="trace-reading__navigation"><a href="#trace-reading-findings">问题与判断</a><a href="#trace-reading-changes">改动</a><a href="#trace-reading-validation">重测效果</a><a href="#trace-reading-decision">版本选择</a></nav>

    {reading.mode === 'distill' ? <ReadingSection id="distillation" title="这些经历值得沉淀什么" description="先对照现有能力，再选择复用形式；候选草稿与已经生效的能力分别记录。">
      {reading.distillation.length ? <div className="trace-reading__distillation">{reading.distillation.map((item, index) => <article key={`${item.outcome}:${index}`}><h4>{item.label}</h4>{item.title ? <p><strong>{item.title}</strong></p> : null}<p>{item.reason}</p>{item.proposedChange ? <p><strong>拟沉淀的内容：</strong>{item.proposedChange}</p> : null}<p className="trace-reading__field-note">{item.validationLabel}</p>{item.existingCapabilityIds.length ? <details><summary>已对照的现有能力</summary><ul>{item.existingCapabilityIds.map((id) => <li key={id}><code>{id}</code></li>)}</ul></details> : null}{evidence(item.evidenceIds)}{item.candidateIds.length ? <p className="trace-reading__related">关联候选：{item.candidateIds.map((id) => <a href={`#${candidateAnchor(id)}`} key={id}>{reading.candidates.find((candidate) => candidate.id === id)?.summary || id}</a>)}</p> : null}</article>)}</div> : <p className="trace-reading__empty">尚未记录沉淀结论。结果可以是改进已有能力、新增 Skill、新增真实工具、仅沉淀经验或无需沉淀。</p>}
    </ReadingSection> : null}

    <ReadingSection id="findings" title="发现了什么，为什么这样判断" description="观察事实与 Agent 假设分开阅读；展开问题即可查看来源、候选和验证要求。">
      {model.findings.length > 1 ? <ol className="trace-reading__problem-index">{model.findings.map((finding) => <li key={finding.findingId}><a href={`#${findingAnchor(finding.findingId)}`}>{finding.observation}</a></li>)}</ol> : null}
      <div className="trace-audit__findings">{model.findings.length ? model.findings.map((finding, index) => {
        const related = reading.candidates.filter((candidate) => candidate.findingIds.includes(finding.findingId));
        return <details className="trace-audit__finding trace-reading__finding" data-severity={finding.severity} id={findingAnchor(finding.findingId)} key={finding.findingId} open={index === 0}>
          <summary><span><strong>{finding.observation}</strong><small>{finding.severityLabel} · {finding.confidenceLabel}</small></span><span className="trace-reading__disclosure">事实与证据</span></summary>
          <div className="trace-reading__finding-body"><ReadingField title="观察到的事实">{finding.observation}</ReadingField><ReadingField title="Agent 的判断">{finding.hypothesis}<span className="trace-reading__field-note">{finding.conclusion}</span></ReadingField>{evidence(finding.evidenceIds)}<ReadingField title={related.length ? '对应候选' : '建议怎样改'}>{related.length ? related.map((candidate) => <a href={`#${candidateAnchor(candidate.id)}`} key={candidate.id}>{candidate.summary}</a>) : <>{finding.candidateRepair}<span className="trace-reading__field-note">尚无实际候选变更记录。</span></>}</ReadingField><ReadingField title="如何确认有效">{finding.verification}</ReadingField></div>
        </details>;
      }) : <p className="trace-reading__empty">{model.status === 'generating' ? 'Agent 正在读取所选证据，尚未形成结构化发现。' : '本报告没有结构化问题记录；不能据此断言已经没有问题。'}</p>}</div>
    </ReadingSection>

    <ReadingSection id="changes" title="候选实际改了什么" description="建议说明预期，版本与 diff 说明实际变更。没有实际变更记录时保持未实施。">
      {reading.candidates.length ? reading.candidates.map((candidate) => <CandidateChange candidate={candidate} key={candidate.id}>{evidence(candidate.evidenceIds)}</CandidateChange>) : <p className="trace-reading__empty">当前尚无已持久化候选或实际 diff。上面的改法仍是建议，原版应用状态未改变。</p>}
    </ReadingSection>

    <ReadingSection id="validation" title="用同一批任务重测，是否更好" description="原版与候选共享比较条件。显示真实分子、分母与退化案例；缺失数据保持未知。">
      {reading.candidates.length ? reading.candidates.map((candidate) => <article className="trace-reading__validation" key={candidate.id}>
        <header><h4>{candidate.summary}</h4><strong data-effect={candidate.comparison?.effect ?? 'not_run'}>{candidate.comparison?.effectLabel ?? '待重测'}</strong></header>
        {candidate.execution ? <div aria-live="polite" className="trace-reading__execution"><dl className="trace-reading__version-pair"><div><dt>原版执行</dt><dd>{candidate.execution.baselineState}</dd>{candidate.execution.baselineSummary ? <p>{candidate.execution.baselineSummary}</p> : null}</div><div><dt>候选执行</dt><dd>{candidate.execution.candidateState}</dd>{candidate.execution.candidateSummary ? <p>{candidate.execution.candidateSummary}</p> : null}</div></dl>{candidate.execution.awaitingComparison ? <p>两次执行已结束，正在整理可比结果。</p> : null}{candidate.execution.active && actions.onCancelCandidate && !exported ? <button className="trace-reading__button" disabled={Boolean(actions.pendingCandidateId)} onClick={() => actions.onCancelCandidate?.(candidate.id)} type="button">取消本次验证</button> : null}</div> : null}
        {candidate.comparison ? <ComparisonResult comparison={candidate.comparison} /> : <p className="trace-reading__empty">没有绑定原版与候选的验证结果，不能声称改善。</p>}
        {!exported && candidate.canRun && actions.onRunCandidate && !candidate.execution?.active ? <button className="trace-reading__button" disabled={Boolean(actions.pendingCandidateId)} onClick={() => actions.onRunCandidate?.(candidate.id)} type="button">{actions.pendingCandidateId === candidate.id ? '正在提交验证' : candidate.comparison ? '再次验证候选' : '运行候选验证'}</button> : null}
      </article>) : <div className="trace-reading__empty"><p>尚无同条件的原版 / 候选对照。</p>{model.repairLifecycle.comparisonMetrics.length || model.repairLifecycle.verificationReceiptId ? <p>这份历史报告有修复 Trace / Eval 记录，保留在证据详情的修复对照中；它未记录本轮优化合同与分母。</p> : null}</div>}
    </ReadingSection>

    <ReadingSection id="decision" title="决定采用哪个版本" description="改善结论与应用状态分别记录。操作结果从版本所属服务返回，当前对话继续使用其原绑定版本。">
      {reading.candidates.length ? reading.candidates.map((candidate) => <article className="trace-reading__decision" key={candidate.id}>
        <div><h4>{candidate.summary}</h4><p className="trace-reading__application-state">{candidate.applicationLabel}</p><dl><div><dt>应用目标</dt><dd>{candidate.target}</dd></div><div><dt>候选版本</dt><dd>{candidate.candidateVersion}</dd></div></dl></div>
        {exported ? <p>导出时的版本状态。安装、替换与保留操作请返回 App 完成。</p> : <div className="trace-reading__decision-actions">{candidate.availableActions.length ? candidate.availableActions.map((action) => <button className="trace-reading__button" data-primary={['install', 'replace', 'apply'].includes(action)} disabled={!actions.onCandidateAction || Boolean(actions.pendingCandidateId)} key={action} onClick={() => actions.onCandidateAction?.(candidate.id, action)} type="button">{actions.pendingCandidateId === candidate.id ? '正在处理' : traceCandidateActionLabel(action)}</button>) : <p>{['applying', 'interrupted'].includes(candidate.applicationStatus) ? '请刷新报告核对原操作回执，避免重复应用。' : '此目标尚无可执行的版本操作。'}</p>}{!candidate.availableActions.some((action) => ['install', 'replace', 'apply'].includes(action)) && !['applied', 'applying', 'interrupted'].includes(candidate.applicationStatus) ? <p className="trace-reading__field-note">安装目标或实测条件尚未就绪，候选保留为草稿。</p> : null}</div>}
        {candidate.applicationReceipt ? <details><summary>应用回执</summary><code>{candidate.applicationReceipt}</code></details> : null}
      </article>) : <p className="trace-reading__empty">原版保持不变。候选和验证准备好后，此处显示实际安装、替换或保留操作。</p>}
      {actions.actionError ? <p className="trace-reading__action-error" role="alert">{actions.actionError}</p> : null}
      {exported ? appReturnHref ? <a className="trace-reading__return" href={appReturnHref}>返回 PAW 查看此报告与版本状态</a> : <p className="trace-reading__field-note">在 PAW 打开 Trace Agent 工作台，查看「{model.title}」的最新版本状态。</p> : null}
    </ReadingSection>
  </div>;
}

function CandidateChange({ candidate, children }: { candidate: TraceReadingCandidate; children: ReactNode }) {
  return <article className="trace-reading__candidate" id={candidateAnchor(candidate.id)}>
    <header><h4>{candidate.summary}</h4><span>{candidate.kindLabel} · {candidate.executionLabel}</span></header>
    {candidate.findingIds.length ? <p className="trace-reading__related">对应问题：{candidate.findingIds.map((id, index) => <a href={`#${findingAnchor(id)}`} key={id}>问题 {index + 1}</a>)}</p> : null}
    <p><strong>预期改善：</strong>{candidate.expectedEffect}</p>
    <div className="trace-reading__version-pair"><div><span>原版</span><strong>{candidate.parentVersion}</strong>{candidate.diff?.before ? <pre><code>{candidate.diff.before}</code></pre> : null}</div><div><span>候选版</span><strong>{candidate.candidateVersion}</strong>{candidate.diff?.after ? <pre><code>{candidate.diff.after}</code></pre> : null}</div></div>
    {candidate.diff?.unified ? <details className="trace-reading__diff"><summary>查看实际 diff</summary><pre><code>{candidate.diff.unified}</code></pre></details> : !candidate.diff ? <p className="trace-reading__empty">{candidate.diffRef ? '已记录变更引用，实际 diff 正文尚未载入。' : '尚无实际 diff，不能确认候选已经实施。'}</p> : null}
    {candidate.diffRef ? <details className="trace-reading__diff-ref"><summary>变更来源</summary><code>{candidate.diffRef}</code></details> : null}
    {children}
  </article>;
}

function ComparisonResult({ comparison }: { comparison: TraceReadingComparison }) {
  return <><p>{comparison.explanation}</p><p className="trace-reading__field-note">{comparison.validationScopeLabel}</p>{!comparison.comparable ? <p className="trace-reading__notice">比较条件或执行证据不完整，以下记录不作为提升结论。</p> : null}
    {comparison.metrics.length ? <div className="trace-reading__paired-metrics">{comparison.metrics.map((metric) => <div className="trace-reading__metric" key={metric.id}>
      <h5>{metric.label}</h5><div className="trace-reading__metric-pair">{([{ label: '原版', value: metric.baselineDisplay, count: metric.baselineCount, ratio: metric.baselineRatio }, { label: '候选', value: metric.candidateDisplay, count: metric.candidateCount, ratio: metric.candidateRatio }] as const).map((side) => <div className="trace-reading__metric-side" key={side.label}><span>{side.label}</span><strong>{side.value}</strong><small>{side.count}</small>{side.ratio === null ? null : <div aria-label={`${side.label} ${side.count}`} className="trace-reading__bar"><span style={{ width: `${side.ratio * 100}%` }} /></div>}</div>)}</div>
    </div>)}</div> : <p className="trace-reading__empty">没有可展示的配对指标。</p>}
    <div className="trace-reading__regressions"><h5>退化案例</h5>{comparison.regressions.length ? <ul>{comparison.regressions.map((item) => <li key={item}>{item}</li>)}</ul> : <p>{comparison.comparable && comparison.cases.length ? `已记录的 ${comparison.cases.length} 个案例中，${comparison.cases.filter((item) => item.regressed).length} 个标记为退化。` : '尚无完整逐案例记录，退化情况未验证。'}</p>}</div>
    {comparison.cases.length ? <details className="trace-reading__cases"><summary>查看 {comparison.cases.length} 个案例的前后结果</summary><div className="trace-reading__case-table"><table><thead><tr><th>案例</th><th>原版</th><th>候选</th><th>变化</th></tr></thead><tbody>{comparison.cases.map((item) => <tr key={item.id}><th scope="row">{item.id}</th><td>{item.baseline ?? '未记录'}</td><td>{item.candidate ?? '未记录'}</td><td>{item.regressed ? '退化' : item.baseline === null || item.candidate === null ? '未验证' : '未标记退化'}</td></tr>)}</tbody></table></div></details> : null}
    <details className="trace-reading__comparison-details"><summary>比较条件、实际版本与用量</summary><p><strong>原始验证说明：</strong>{comparison.reason}</p><dl><div><dt>原版运行</dt><dd>{comparison.baselineTrialId || '未记录'}</dd></div><div><dt>候选运行</dt><dd>{comparison.candidateTrialId || '未记录'}</dd></div></dl><div className="trace-reading__version-pair">{(['baseline', 'candidate'] as const).map((side) => <div key={side}><strong>{side === 'baseline' ? '原版实际装载' : '候选实际装载'}</strong>{Object.keys(comparison.controls[side]).length ? <dl>{Object.entries(comparison.controls[side]).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl> : <p>未记录装载版本。</p>}</div>)}</div><p>{comparison.costNote}</p>{comparison.cost ? <p>原版 {comparison.cost.baseline} → 候选 {comparison.cost.candidate} {comparison.cost.currency}</p> : null}{comparison.evidenceRefs.length ? <ul>{comparison.evidenceRefs.map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul> : null}</details>
  </>;
}

function ReadingSection({ id, title, description, children }: { id: string; title: string; description: string; children: ReactNode }) { return <section aria-labelledby={`trace-reading-${id}`} className="trace-reading__section"><header><h3 id={`trace-reading-${id}`}>{title}</h3><p>{description}</p></header>{children}</section>; }
function ReadingField({ title, children }: { title: string; children: ReactNode }) { return <section className="trace-reading__field"><h4>{title}</h4><div>{children}</div></section>; }
function ReadingEvidence({ aliases, ids, onOpen }: { aliases: Record<string, string>; ids: string[]; onOpen?: (id: string) => void }) { return <div className="trace-reading__evidence">{ids.length ? <><span>来源证据</span>{ids.map((id) => onOpen ? <button aria-label={`查看证据 ${id}`} key={id} onClick={() => onOpen(id)} type="button">[{aliases[id] ?? '?'}]</button> : <a href={`#evidence-${(aliases[id] ?? 'unresolved').toLowerCase()}`} key={id}>[{aliases[id] ?? '?'}]</a>)}</> : <span>尚无冻结证据引用</span>}</div>; }
function candidateAnchor(id: string): string { return `trace-candidate-${encodeURIComponent(id)}`; }
function findingAnchor(id: string): string { return `trace-finding-${encodeURIComponent(id)}`; }
