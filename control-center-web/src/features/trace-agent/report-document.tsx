import { ArrowUpRight, Download, FileSearch, ShieldCheck } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/primitives';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
import { buildTraceDiagnosticReportHtml } from './html-export';
import {
  buildTraceAuditReportModel,
  type TraceAuditEvidence,
  type TraceAuditFinding,
} from './report-model';

export function TraceDiagnosticReportDocument({
  onOpenDiagnosticSession,
  onOpenTarget,
  onOpenTrace,
  report,
}: {
  onOpenDiagnosticSession: () => void;
  onOpenTarget: (target: TraceDiagnosticReportV1['targets'][number]) => void;
  onOpenTrace?: (traceId: string) => void;
  report: TraceDiagnosticReportV1;
}) {
  const model = buildTraceAuditReportModel(report);
  const exportHref = useTraceDiagnosticHtmlUrl(report);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState('');
  const selectedEvidence = model.evidence.find((item) => item.evidenceId === selectedEvidenceId) ?? null;
  const selectedEvidenceTarget = report.targets.find((target) => target.targetKey === selectedEvidence?.targetKey) ?? null;
  const openEvidence = (evidenceId: string) => setSelectedEvidenceId(evidenceId);
  return (
    <>
      <section
        aria-label="Trace 诊断网页报告"
        className="trace-audit"
        data-status={model.status}
        data-testid="trace-agent-web-report"
        data-tone={model.verdict.tone}
      >
      <header className="trace-audit__masthead">
        <div className="trace-audit__identity">
          <p className="trace-audit__document-type">PAW Trace Diagnostic · 工程审计报告</p>
          <h2>{model.title}</h2>
          <p className="trace-audit__lede">基于冻结 Trace、Runtime 回执与 Eval 证据生成；候选修复不等于已经应用。</p>
        </div>
        <dl className="trace-audit__document-meta">
          <Meta label="报告状态" value={model.statusLabel} />
          <Meta label="报告修订" value={`Revision ${model.revision}`} />
          <Meta label="更新时间" value={model.updatedAtLabel} />
        </dl>
      </header>

      <section aria-labelledby="trace-audit-verdict" className="trace-audit__verdict" data-tone={model.verdict.tone}>
        <div className="trace-audit__verdict-copy">
          <span className="trace-audit__section-label">审计判决</span>
          <h3 id="trace-audit-verdict">{model.verdict.title}</h3>
          <p>{model.verdict.detail}</p>
        </div>
        <dl className="trace-audit__verdict-metrics">
          <Meta label="高优先级问题" value={String(model.highPriorityCount)} />
          <Meta label="失败硬门槛" value={String(model.failedGateCount)} />
          <Meta label="冻结证据" value={String(model.evidenceCount)} />
          <Meta label="可用来源" value={`${model.sourceAvailableCount}/${model.targets.length}`} />
        </dl>
      </section>

      {model.failureReason ? (
        <p aria-live="polite" className="trace-audit__failure" role="alert">
          <strong>报告失败原因：</strong><span>{model.failureReason}</span>
        </p>
      ) : null}

      <AuditSection description={`${model.targets.length} 个对象 · ${model.traceIds.length} 条 Trace`} title="冻结诊断范围">
        <div className="trace-audit__targets">
          {model.targets.map((target) => (
            <article className="trace-audit__target" data-source-available={target.sourceAvailable} key={target.targetKey}>
              <div><strong>{target.title}</strong><span>{target.kindLabel} · {target.id}</span></div>
              <span className="trace-audit__source-state">{target.sourceAvailable ? '源快照可用' : '源快照不可用'}</span>
            </article>
          ))}
        </div>
      </AuditSection>

      <AuditSection
        description={`${model.requirementsSourceLabel} · ${model.requirements.length} 条${model.requirementsTruncated ? ' · 冻结快照已截断' : ''}`}
        title="用户需求完成矩阵"
      >
        {model.requirements.length ? (
          <div className="trace-audit__requirements" role="list">
            {model.requirements.map((requirement) => (
              <article className="trace-audit__requirement" data-status={requirement.status} key={requirement.requirementId} role="listitem">
                <div className="trace-audit__requirement-copy">
                  <strong>{requirement.statement}</strong>
                  <span>{requirement.owner} · {requirement.authorityLabel}</span>
                  <p>{requirement.note}</p>
                </div>
                <span className="trace-audit__requirement-status">{requirement.statusLabel}</span>
                <EvidenceIds onOpen={openEvidence} values={requirement.evidenceIds} />
              </article>
            ))}
          </div>
        ) : <p className="trace-audit__empty">未绑定稳定的用户要求集；不能从聚合数量倒推出逐条完成情况。</p>}
      </AuditSection>

      {model.gates.length ? (
        <AuditSection description="硬门槛失败时，低成本或局部高分不能把任务判为完成。" title="硬门槛">
          <div className="trace-audit__gates">
            {model.gates.map((gate) => (
              <article className="trace-audit__gate" data-status={gate.status} key={gate.gateId}>
                <div><strong>{gate.gateId}</strong><span>{gate.statusLabel}</span></div>
                <p>{gate.reason}</p>
                <EvidenceIds onOpen={openEvidence} values={gate.evidenceIds} />
              </article>
            ))}
          </div>
        </AuditSection>
      ) : null}

      <AuditSection
        description={model.causalLinks.length
          ? `${model.causalLinks.length} 条显式关联 · ${model.timeline.length} 条冻结事件${model.timelineTruncated ? ' · 快照已截断' : ''} · 因果判断均标注权威与置信度`
          : `${model.timeline.length} 条冻结事件 · 仅按时间排序，未把相邻事件冒充因果${model.timelineTruncated ? ' · 快照已截断' : ''}`}
        title="跨 Session / Agent 因果时间线"
      >
        {model.causalLinks.length ? (<>
          <ol className="trace-audit__causal-list">
            {model.causalLinks.map((link) => (
              <li key={link.linkId}>
                <div className="trace-audit__causal-event">
                  <span>{link.from?.targetLabel ?? '来源未解析'}</span>
                  <strong>{link.from?.summary ?? link.fromEvidenceId}</strong>
                  <EvidenceIds onOpen={openEvidence} values={[link.fromEvidenceId]} />
                </div>
                <div className="trace-audit__causal-relation">
                  <strong>{link.relationLabel}</strong>
                  <span>{link.authorityLabel} · {link.confidenceLabel}</span>
                  <p>{link.explanation}</p>
                </div>
                <div className="trace-audit__causal-event">
                  <span>{link.to?.targetLabel ?? '目标未解析'}</span>
                  <strong>{link.to?.summary ?? link.toEvidenceId}</strong>
                  <EvidenceIds onOpen={openEvidence} values={[link.toEvidenceId]} />
                </div>
              </li>
            ))}
          </ol>
          <details className="trace-audit__timeline-details">
            <summary><strong>查看完整冻结时间线</strong><span>{model.timeline.length} 条，包含未关联事件</span></summary>
            <TimelineList items={model.timeline} onOpenEvidence={openEvidence} />
          </details>
        </>
        ) : model.timeline.length ? (
          <TimelineList items={model.timeline} onOpenEvidence={openEvidence} />
        ) : <p className="trace-audit__empty">冻结报告没有公开时间线，因果关系不可判断。</p>}
      </AuditSection>

      <AuditSection description={model.summary} title="诊断结论">
        <div className="trace-audit__findings">
          {model.findings.length
            ? model.findings.map((finding) => <Finding finding={finding} key={finding.findingId} onOpenEvidence={openEvidence} />)
            : <p className="trace-audit__empty">没有结构化 Finding；这不等同于已经证明系统没有问题。</p>}
        </div>
      </AuditSection>

      <AuditSection description="系统指标、冻结真值与 AI 评审估计分别标注；未知不按零分处理。" title="八维诊断评分">
        <div className="trace-audit__score-table-wrap" data-testid="trace-diagnostic-scorecard">
          <table className="trace-audit__score-table">
            <thead><tr><th>维度</th><th>分数</th><th>证据权威</th><th>指标与边界</th></tr></thead>
            <tbody>
              {model.dimensions.map((dimension) => (
                <tr data-applicability={dimension.applicability} data-dimension-id={dimension.dimensionId} key={dimension.dimensionId}>
                  <th scope="row"><strong>{dimension.title}</strong><span>{dimension.applicabilityLabel}</span></th>
                  <td><strong>{dimension.scoreText}</strong>{dimension.judgeScore === null ? null : <span className="trace-audit__judge">AI 评审估计 {dimension.judgeScore}/3</span>}</td>
                  <td>{dimension.authorityLabel}</td>
                  <td><div className="trace-audit__metric-list">{dimension.metrics.length
                    ? dimension.metrics.map((metric) => <span key={`${dimension.dimensionId}:${metric.label}`}><strong>{metric.label}</strong> {metric.value}</span>)
                    : <span>{dimension.note}</span>}</div><EvidenceIds onOpen={openEvidence} values={dimension.evidenceIds} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AuditSection>

      <AuditSection
        description={`${model.environment.statusLabel} · 捕获于 ${model.environment.capturedAtLabel}`}
        title="可复现环境快照"
      >
        <details className="trace-audit__environment" open={model.environment.status !== 'complete'}>
          <summary>
            <strong>{model.environment.statusLabel}</strong>
            <span>{model.environment.rubricVersion}</span>
          </summary>
          {model.environment.targets.length ? (
            <div className="trace-audit__environment-targets">
              {model.environment.targets.map((target) => (
                <article key={target.targetKey}>
                  <h4>{target.targetLabel}</h4>
                  <dl>
                    <Meta label="Runtime" value={target.runtime} />
                    <Meta label="模型配置" value={target.modelProfile} />
                    <Meta label="Tool 配置" value={target.toolProfileVersion} />
                    <Meta label="执行模式" value={target.executionMode} />
                    <Meta label="策略修订" value={target.policyRevision} />
                    <Meta label="Shell 策略" value={target.shellPolicyVersion} />
                    <Meta label="源快照 SHA-256" value={target.sourceSha256} mono />
                    <Meta label="Workspace scope SHA-256" value={target.workspaceScopeSha256} mono />
                    <Meta label="Trace input fingerprint" value={target.traceInputFingerprints.join(' · ') || '未冻结'} mono />
                    <Meta label="Trace 状态" value={target.traceStatuses.join(' · ') || '未知'} />
                  </dl>
                </article>
              ))}
            </div>
          ) : <p className="trace-audit__empty">没有 Runtime 权威环境数据，不能声称可复现。</p>}
          {model.environment.limitations.length ? (
            <div className="trace-audit__limitations"><strong>复现边界</strong><ul>{model.environment.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
          ) : null}
        </details>
      </AuditSection>

      <AuditSection description="修复交接授权与实际写入权限分开记录；候选修复不会自动执行。" title="修复授权状态">
        <article className="trace-audit__repair-state" data-state={model.repairLifecycle.authorizationState}>
          <div>
            <span>修复交接</span>
            <strong>{model.repairLifecycle.authorizationStateLabel}</strong>
            <p>{model.repairLifecycle.writeAuthorityLabel}</p>
          </div>
          <dl>
            <Meta label="Finding" value={model.repairLifecycle.findingId || '尚未选择'} mono />
            <Meta label="授权范围" value={model.repairLifecycle.sourceScope || '尚未冻结'} mono />
            <Meta label="失败引用" value={model.repairLifecycle.failureRef || '尚未冻结'} mono />
            <Meta label="修复 Session" value={model.repairLifecycle.repairSessionId || '尚未创建'} mono />
            <Meta label="授权回执" value={model.repairLifecycle.authorizationId || '尚未记录'} mono />
            <Meta label="授权时间" value={model.repairLifecycle.authorizedAtLabel} />
          </dl>
        </article>
      </AuditSection>

      <AuditSection description={model.repairLifecycle.comparisonReason} title="修复前后 Trace / Eval 对照">
        <div className="trace-audit__comparison" data-status={model.repairLifecycle.comparisonStatus}>
          <header>
            <div><span>验证状态</span><strong>{model.repairLifecycle.verificationStateLabel}</strong></div>
            <div><span>可比性</span><strong>{model.repairLifecycle.comparisonStatusLabel}</strong></div>
            <div><span>测试证据</span><strong>{model.repairLifecycle.testStatus}</strong></div>
            <div><span>沙盒回放</span><strong>{model.repairLifecycle.sandboxStatus} · {model.repairLifecycle.sandboxedTestCount} 次</strong></div>
          </header>
          <dl className="trace-audit__comparison-refs">
            <MetaAction label="Before Trace" onClick={model.repairLifecycle.sourceTraceId && onOpenTrace ? () => onOpenTrace(model.repairLifecycle.sourceTraceId) : undefined} value={model.repairLifecycle.sourceTraceId || '未绑定'} />
            <MetaAction label="After Trace" onClick={model.repairLifecycle.repairTraceId && onOpenTrace ? () => onOpenTrace(model.repairLifecycle.repairTraceId) : undefined} value={model.repairLifecycle.repairTraceId || '等待新 Trace'} />
            <Meta label="EvalRun" value={model.repairLifecycle.evalRunId || '等待 Eval'} mono />
            <Meta label="修复回执" value={model.repairLifecycle.repairReceiptId || '尚未生成'} mono />
          </dl>
          {model.repairLifecycle.comparisonMetrics.length ? (
            <div className="trace-audit__comparison-table-wrap">
              <table className="trace-audit__comparison-table">
                <thead><tr><th>指标</th><th>Before</th><th>After</th><th>Δ</th></tr></thead>
                <tbody>{model.repairLifecycle.comparisonMetrics.map((metric) => (
                  <tr key={metric.metricId}><th scope="row">{metric.metricId}</th><td>{metric.before}</td><td>{metric.after}</td><td>{metric.delta}</td></tr>
                ))}</tbody>
              </table>
            </div>
          ) : <p className="trace-audit__empty">还没有可展示的修复前后指标。</p>}
          {model.repairLifecycle.verificationState === 'verified' ? <p className="trace-audit__comparison-note">“修复证据已绑定”只证明新 Trace、测试回执和 Eval 存在；是否改善仍由上面的可比性判定。</p> : null}
        </div>
      </AuditSection>

      <AuditSection
        description={`${model.evidence.length} 条公开冻结证据${model.evidenceTruncated ? ' · 快照已截断' : ''}`}
        title="Evidence 目录"
      >
        <details className="trace-audit__evidence-catalog">
          <summary><strong>查看全部 Evidence</strong><span>仅展示服务端脱敏后的公开投影</span></summary>
          <div className="trace-audit__evidence-catalog-list">
            {model.evidence.length
              ? model.evidence.map((item) => (
                <button key={item.evidenceId} onClick={() => openEvidence(item.evidenceId)} type="button">
                  <code>{item.evidenceId}</code><span>{item.summary}</span>
                </button>
              ))
              : <p className="trace-audit__empty">冻结报告不包含可公开展示的 Evidence。</p>}
          </div>
          {model.unresolvedEvidenceIds.length ? <p className="trace-audit__unresolved">{model.unresolvedEvidenceIds.length} 个引用未在冻结 Evidence 目录中解析，未尝试从实时系统补齐。</p> : null}
        </details>
      </AuditSection>

      <div aria-label="报告操作" className="trace-audit__links" role="toolbar">
        {exportHref ? (
          <a className="trace-audit__download" download="trace-diagnostic-report.html" href={exportHref}>
            <Download aria-hidden="true" size={14} />下载 HTML 报告
          </a>
        ) : <span aria-disabled="true" className="trace-audit__download">HTML 导出不可用</span>}
        <Button leadingIcon={<ShieldCheck size={14} />} onClick={onOpenDiagnosticSession} size="small">打开诊断 Agent 对话</Button>
        {report.targets.slice(0, 3).map((target) => (
          <Button key={target.targetKey} leadingIcon={<ArrowUpRight size={14} />} onClick={() => onOpenTarget(target)} size="small" variant="quiet">
            打开{target.kind === 'room' ? ' Room' : target.kind === 'run' ? '运行记录' : ' Session'}
          </Button>
        ))}
      </div>

      <footer className="trace-audit__provenance">
        <div><strong>报告身份</strong><span>{model.reportId}</span></div>
        <div><strong>冻结检查摘要</strong><span>{model.inspectionSha256}</span></div>
        <p>网页报告只读取持久化报告投影；诊断 Agent 对话保留过程，但不替代报告 authority。</p>
      </footer>
      </section>
      <Dialog open={Boolean(selectedEvidenceId)} onOpenChange={(open) => { if (!open) setSelectedEvidenceId(''); }}>
        <DialogContent className="trace-audit__evidence-dialog">
          <DialogHeader>
            <DialogTitle>Evidence 详情</DialogTitle>
            <DialogDescription>只读取这份报告冻结时保存的公开脱敏投影，不回查当前 Runtime。</DialogDescription>
          </DialogHeader>
          {selectedEvidence ? (
            <EvidenceDetail evidence={selectedEvidence} />
          ) : (
            <p className="trace-audit__evidence-missing" role="alert">未在冻结快照中找到 {selectedEvidenceId}，因此没有尝试读取未知原始数据。</p>
          )}
          {selectedEvidence ? (
            <div className="trace-audit__evidence-dialog-actions">
              {selectedEvidence.traceId && onOpenTrace ? (
                <Button leadingIcon={<FileSearch size={14} />} onClick={() => onOpenTrace(selectedEvidence.traceId)} size="small">打开 Trace</Button>
              ) : null}
              {selectedEvidenceTarget ? (
                <Button leadingIcon={<ArrowUpRight size={14} />} onClick={() => onOpenTarget(selectedEvidenceTarget)} size="small" variant="quiet">打开原对象</Button>
              ) : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}

function AuditSection({ children, description, title }: { children: ReactNode; description: string; title: string }) {
  const id = `trace-audit-${title}`;
  return (
    <section aria-labelledby={id} className="trace-audit__section">
      <header className="trace-audit__section-heading"><div><h3 id={id}>{title}</h3><p>{description}</p></div></header>
      {children}
    </section>
  );
}

function Finding({ finding, onOpenEvidence }: { finding: TraceAuditFinding; onOpenEvidence: (evidenceId: string) => void }) {
  return (
    <details className="trace-audit__finding" data-severity={finding.severity} open={['critical', 'high'].includes(finding.severity)}>
      <summary>
        <span className="trace-audit__finding-index">{finding.severityLabel}</span>
        <span><strong>{finding.conclusion}</strong><small>{finding.dimensionLabel} · {finding.confidenceLabel}</small></span>
        <code>{finding.findingId}</code>
      </summary>
      <div className="trace-audit__finding-body">
        <FindingField title="观察事实" value={finding.observation} />
        <FindingField title="待验证假设" value={finding.hypothesis} />
        <FindingField title="支持结论" value={finding.conclusion} />
        <FindingField title="候选修复" value={finding.candidateRepair} />
        <FindingField title="验证要求" value={finding.verification} />
        <section className="trace-audit__evidence"><h3>证据引用</h3><EvidenceIds onOpen={onOpenEvidence} values={finding.evidenceIds} /></section>
      </div>
    </details>
  );
}

function FindingField({ title, value }: { title: string; value: string }) {
  return <section><h3>{title}</h3><p>{value}</p></section>;
}

function TimelineList({ items, onOpenEvidence }: {
  items: ReturnType<typeof buildTraceAuditReportModel>['timeline'];
  onOpenEvidence: (evidenceId: string) => void;
}) {
  return (
    <ol className="trace-audit__timeline">
      {items.map((item) => (
        <li key={`${item.evidenceId}:${item.sequence}`}>
          <time>{item.createdAtLabel}</time>
          <div><span>{item.targetLabel} · {item.kind}</span><strong>{item.summary}</strong></div>
          <EvidenceIds onOpen={onOpenEvidence} values={[item.evidenceId]} />
        </li>
      ))}
    </ol>
  );
}

function EvidenceIds({ onOpen, values }: { onOpen: (evidenceId: string) => void; values: string[] }) {
  return values.length
    ? <div className="trace-audit__evidence-ids">{values.map((value) => (
      <button aria-label={`查看证据 ${value}`} key={value} onClick={() => onOpen(value)} type="button"><code>{value}</code></button>
    ))}</div>
    : <span className="trace-audit__evidence-empty">没有可引用证据</span>;
}

function EvidenceDetail({ evidence }: { evidence: TraceAuditEvidence }) {
  return (
    <div className="trace-audit__evidence-detail">
      <p>{evidence.summary}</p>
      <dl>
        <Meta label="Evidence ID" value={evidence.evidenceId} mono />
        <Meta label="来源类型" value={evidence.sourceKind} />
        <Meta label="Source ref" value={evidence.sourceRef} mono />
        <Meta label="诊断对象" value={evidence.targetLabel} />
        <Meta label="Trace" value={evidence.traceId || '未绑定'} mono />
        <Meta label="状态" value={evidence.status} />
        <Meta label="时间" value={evidence.createdAtLabel} />
      </dl>
    </div>
  );
}

function Meta({ label, mono = false, value }: { label: string; mono?: boolean; value: string }) {
  return <div><dt>{label}</dt><dd data-mono={mono}>{value}</dd></div>;
}

function MetaAction({ label, onClick, value }: { label: string; onClick?: () => void; value: string }) {
  return <div><dt>{label}</dt><dd data-mono="true">{onClick ? <button className="trace-audit__reference-link" onClick={onClick} type="button">{value}</button> : value}</dd></div>;
}

function useTraceDiagnosticHtmlUrl(report: TraceDiagnosticReportV1): string {
  const [url, setUrl] = useState('');
  useEffect(() => {
    if (typeof URL.createObjectURL !== 'function') return undefined;
    const next = URL.createObjectURL(new Blob(
      [buildTraceDiagnosticReportHtml(report)],
      { type: 'text/html;charset=utf-8' },
    ));
    setUrl(next);
    return () => {
      URL.revokeObjectURL(next);
    };
  }, [report]);
  return url;
}
