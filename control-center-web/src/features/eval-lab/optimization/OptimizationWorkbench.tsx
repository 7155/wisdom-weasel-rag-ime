import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import type { EvalLabEvidenceRun, EvalLabExperiment, EvalLabRun } from '../api';
import { buildOptimizationWorkbenchModel } from './optimization-view-model';
import { useLinkedTraceReport } from './use-linked-trace-report';
import { experimentBaselineTraceIds } from '../evidence-identity';
import { CandidatePatchEvidence } from '../CandidatePatchEvidence';
import './optimization-workbench.css';

const LAYER_LABELS: Readonly<Record<string, string>> = {
  context: 'Context',
  execution_policy: '执行策略',
  guardrail: 'Guardrail',
  human_loop: 'Human Loop',
  memory_rag: 'Memory / RAG',
  model: '模型',
  pricing: '定价',
  prompt: 'Prompt',
  skill: 'Skill',
  tool: 'Tool',
  workflow: '工作流',
};

type OptimizationWorkbenchProps = {
  evidenceRuns: readonly EvalLabEvidenceRun[];
  experiment: EvalLabExperiment;
  linkedRuns: readonly EvalLabRun[];
  onOpenTraceReport?: (reportId: string) => void;
  traceReport?: TraceDiagnosticReportV1;
  traceLookupState?: 'loading' | 'error' | 'settled';
};

export function LinkedOptimizationWorkbench(props: Omit<OptimizationWorkbenchProps, 'traceLookupState' | 'traceReport'>) {
  const desktop = usePawOsDesktop();
  const baselineTraceIds = experimentBaselineTraceIds(props.evidenceRuns, props.experiment);
  const linkedReport = useLinkedTraceReport({
    baselineRunId: props.experiment.baseline.runId,
    baselineTraceIds,
  });
  return <OptimizationWorkbench
    {...props}
    onOpenTraceReport={(reportId) => openPawOsRoute(desktop, `/trace-agent?reportId=${encodeURIComponent(reportId)}`)}
    traceLookupState={linkedReport.isLoading ? 'loading' : linkedReport.error ? 'error' : 'settled'}
    traceReport={linkedReport.report}
  />;
}

export function OptimizationWorkbench(props: OptimizationWorkbenchProps) {
  const model = buildOptimizationWorkbenchModel(props);
  return (
    <section aria-label="Optimization Workbench" className="optimization-workbench">
      <header className="optimization-workbench__header">
        <div><span>Optimization Workbench</span><h3>从失败证据走到保留决策</h3></div>
        <span className="optimization-workbench__mode">{model.historical ? '历史只读' : '当前实验 · 证据只读'}</span>
      </header>

      <div className="optimization-workbench__primary-flow">
        <section aria-label="失败切片" role="group">
          <StepHeader index="1" title="失败切片" />
          {model.failure ? <dl>
            <Row label="Run" value={model.failure.runId} code />
            <Row label="Case" value={model.failure.caseId} code />
            <Row label="任务要求" value={model.failure.expected} />
            <Row label="实际结果" value={model.failure.actual} />
            <Row label="终态" value={model.failure.terminal} />
            <Row label="失败门禁" value={model.failure.failedGates.join('；') || '失败已记录，但门禁明细缺失'} />
          </dl> : <p className="optimization-workbench__unknown">尚未找到精确失败 Case；不从标题或相似场景推断。</p>}
          <IdentityList label="原运行 Trace" values={model.identity.baselineTraceIds} />
        </section>

        <section aria-label="根因归因" role="group">
          <StepHeader index="2" title="根因归因" />
          {model.attribution ? <>
            <p>{model.attribution.summary}</p>
            <ul className="optimization-workbench__layers">
              {model.attribution.layers.map((layer) => <li key={layer.layer}>
                <strong>{layer.label}</strong><span>{layer.verdictLabel}</span>
                <small>{layer.explanation}{layer.evidenceAliases.length ? ` · ${layer.evidenceAliases.join('、')}` : ''}</small>
              </li>)}
            </ul>
            <div className="optimization-workbench__trace-report">
              <code>{model.attribution.reportId}</code>
              {props.onOpenTraceReport ? <button onClick={() => props.onOpenTraceReport?.(model.attribution!.reportId)} type="button">打开 Trace 诊断报告</button> : null}
            </div>
          </> : <p className="optimization-workbench__unknown">{props.traceLookupState === 'loading'
            ? '正在按 Baseline 身份查找 Trace 诊断回执…'
            : props.traceLookupState === 'error'
              ? 'Trace 诊断回执暂时不可读；初步归因不升级为根因。'
              : '未绑定 Trace 诊断回执；初步归因不升级为根因。'}</p>}
        </section>

        <section aria-label="候选变化" role="group">
          <StepHeader index="3" title="候选变化" />
          <h4>变化摘要</h4>
          {model.changes.length ? <ul className="optimization-workbench__changes">{model.changes.map((change, index) => <li key={`${change.layer}-${index}`}>
            <strong>{LAYER_LABELS[change.layer] ?? change.layer}</strong>
            <span>{change.before} → {change.after}</span>
            <small>{change.reason}</small>
          </li>)}</ul> : <p className="optimization-workbench__unknown">没有候选变化记录。</p>}
          <CandidatePatchEvidence experiment={props.experiment} />
          <details><summary>冻结控制（{model.frozenControls.length}）</summary><ul>{model.frozenControls.map((control) => <li key={control.name}>{control.name}：{control.value}（{control.reason}）</li>)}</ul></details>
        </section>
      </div>

      <div className="optimization-workbench__closure">
        <section aria-label="Before / After" role="group">
          <StepHeader index="4" title="Before / After" />
          {model.comparison ? <div className="optimization-workbench__comparison">
            <div><span>Before</span><p>{model.comparison.before}</p></div>
            <div><span>After</span><p>{model.comparison.after}</p></div>
            <code>Case {model.comparison.caseId}</code>
          </div> : <p className="optimization-workbench__unknown">不可比较：缺少同一 Case 的 Baseline / Candidate 结果。</p>}
        </section>
        <section aria-label="Keep / Reject" role="group">
          <StepHeader index="5" title="Keep / Reject" />
          <strong className={`optimization-workbench__decision optimization-workbench__decision--${model.decision.label.toLowerCase()}`}>{model.decision.label}</strong>
          <p>{model.decision.reason}</p>
          <small>读取这轮保存的候选结论；保留候选不代表已经应用。</small>
        </section>
      </div>

      <footer className="optimization-workbench__identity">
        <IdentityList label="Experiment" values={[model.identity.experimentId]} />
        <IdentityList label="Baseline" values={[model.identity.baselineRunId]} />
        <IdentityList label="Candidate" values={[model.identity.candidateRunId]} />
        <IdentityList label="Evidence" values={model.identity.evidenceRefs} />
      </footer>
    </section>
  );
}

function StepHeader({ index, title }: { index: string; title: string }) {
  return <header className="optimization-workbench__step"><span>{index}</span><h4>{title}</h4></header>;
}

function Row({ code = false, label, value }: { code?: boolean; label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{code ? <code>{value}</code> : value}</dd></div>;
}

function IdentityList({ label, values }: { label: string; values: readonly string[] }) {
  return <div className="optimization-workbench__ids"><span>{label}</span>{values.length ? values.map((value) => <code key={value}>{value}</code>) : <em>未记录</em>}</div>;
}
