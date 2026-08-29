import {
  Activity,
  ArrowUpRight,
  BrainCircuit,
  CheckCircle2,
  FolderOpen,
  GitBranch,
  LoaderCircle,
  MessageSquareText,
  Network,
  RefreshCw,
  Search,
  Sparkles,
  TriangleAlert,
  Wrench,
} from 'lucide-react';
import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { Button, EmptyState } from '@/components/primitives';
import type { EvalRunV1 } from '@/contracts/generated/eval-run.v1';
import type { ObservationSnapshotV1 } from '@/contracts/generated/observation-snapshot.v1';
import type { AgentRoomSnapshotV1 } from '@/contracts/generated/agent-room-snapshot.v1';
import type { ObservabilityEvalListV1 } from '@/contracts/generated/observability-eval-list.v1';
import type { ObservabilityTraceGetV1 } from '@/contracts/generated/observability-trace-get.v1';
import {
  ManagementPage,
  ManagementSection,
  QueryState,
  StatusBadge,
  asRecord,
  numberValue,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import { parseRoomEventPage, type RoomEventPage } from '@/contracts/room-reducer';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import type { LucideIcon } from 'lucide-react';
import {
  parseTraceAgentHandoff,
  redactTraceAgentError,
  redactTraceAgentText,
  type TraceAgentHandoff,
} from './handoff';
import './trace-agent.css';

const TRACE_AGENT_SKILL_REF = 'integrations/pi/skills/trace-agent-diagnostics/SKILL.md';
const TRACE_DIAGNOSTIC_TITLE_PREFIX = 'Trace 诊断 · ';
const TRACE_TIMELINE_PAGE_SIZE = 60;

type TraceTargetKind = 'session' | 'room' | 'run';

type TraceTarget = {
  kind: TraceTargetKind;
  id: string;
  title: string;
  status: string;
  updatedAtMs: number;
  detail: string;
  workspaceRoots: string[];
  handoffOnly?: boolean;
  handoff?: TraceAgentHandoff;
};

type TraceAgentReport = {
  sessionId: string;
  target: TraceTarget;
  traceId: string;
  promptAccepted: boolean;
  evidence: TraceEvidenceItem[];
};

type TraceRepairHandoff = {
  sessionId: string;
  promptAccepted: boolean;
};

type TraceEvalReceipt = {
  sourceTraceId: string;
  repairTraceId: string;
  evalRun: EvalRunV1;
};

type TraceTargetCatalog = {
  sessions: TraceTarget[];
  rooms: TraceTarget[];
  runs: TraceTarget[];
  hasMore: Record<TraceTargetKind, boolean>;
};

export function TraceAgentFeature() {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const [searchParams] = useSearchParams();
  const incomingHandoff = useMemo(
    () => parseTraceAgentHandoff(searchParams),
    [searchParams],
  );
  const incomingTarget = useMemo(
    () => incomingHandoff ? traceTargetFromHandoff(incomingHandoff) : null,
    [incomingHandoff],
  );
  const targets = useTraceTargets(transport);
  const [kind, setKind] = useState<TraceTargetKind>(incomingTarget?.kind ?? 'session');
  const [selectedId, setSelectedId] = useState(incomingTarget?.id ?? '');
  const [report, setReport] = useState<TraceAgentReport | null>(null);
  const [repairHandoff, setRepairHandoff] = useState<TraceRepairHandoff | null>(null);
  const [evalReceipt, setEvalReceipt] = useState<TraceEvalReceipt | null>(null);
  const catalogItems = kind === 'session'
    ? targets.data?.sessions ?? []
    : kind === 'room'
      ? targets.data?.rooms ?? []
      : targets.data?.runs ?? [];
  const items = incomingTarget?.kind === kind
    ? [incomingTarget, ...catalogItems.filter((item) => item.id !== incomingTarget.id)]
    : catalogItems;
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const persistedReports = (targets.data?.sessions ?? []).filter(isTraceDiagnosticSession);
  const moreTargetsAvailable = targets.data?.hasMore[kind] ?? false;
  const snapshot = useQuery({
    queryKey: ['trace-agent', 'observations', kind, selected?.id ?? ''],
    enabled: Boolean(selected && !selected.handoffOnly),
    queryFn: ({ signal }) => transport.request<ObservationSnapshotV1>({
      pathId: 'observability.snapshot',
      query: {
        limit: 100,
        ...(kind === 'session'
          ? { sessionId: selected?.id ?? '' }
          : kind === 'room'
            ? { roomId: selected?.id ?? '' }
            : { runId: selected?.id ?? '' }),
      },
      responseContract: 'observation-snapshot.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const latestTraceId = useMemo(
    () => selected?.handoff?.traceId || latestTrace(snapshot.data),
    [selected, snapshot.data],
  );
  const evalTraceId = evalReceipt?.repairTraceId ?? '';
  const evals = useQuery<ObservabilityEvalListV1>({
    queryKey: ['trace-agent', 'evals', evalTraceId],
    enabled: Boolean(evalTraceId),
    queryFn: ({ signal }) => transport.request<ObservabilityEvalListV1>({
      pathId: 'observability.evals.list',
      query: { traceId: evalTraceId, limit: 20 },
      responseContract: 'observability-eval-list.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const sourceSnapshot = useQuery({
    queryKey: ['trace-agent', 'source', selected?.kind ?? '', selected?.id ?? ''],
    enabled: Boolean(selected && selected.kind !== 'run'),
    queryFn: ({ signal }) => selected?.kind === 'session'
      ? transport.request({
        pathId: 'agent.session.snapshot',
        params: { sessionId: selected.id },
        signal,
      })
      : transport.request<AgentRoomSnapshotV1>({
        pathId: 'agent.room.snapshot',
        params: { roomId: selected?.id ?? '' },
        responseContract: 'agent-room-snapshot.v1',
        signal,
      }),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const evidence = useMemo(
    () => sourceEvidence(snapshot.data, sourceSnapshot.data),
    [snapshot.data, sourceSnapshot.data],
  );
  const start = useMutation({
    mutationFn: async (target: TraceTarget) => {
      const created = await transport.request({
        pathId: 'agent.sessions.create',
        body: {
          title: `Trace 诊断 · ${target.title}`,
          mode: 'assistant',
          toolProfileVersion: 'control-center-v1',
          executionMode: 'read_only',
          workspaceRoots: [],
        },
      });
      const sessionId = createdSessionId(created);
      if (!sessionId) throw new Error('诊断 Session 创建失败。');
      // Session creation intentionally stays on the existing public contract.
      // Enable the exact diagnostic Skill source through the normal Session
      // policy seam before the first turn, so the SkillRef is real at runtime
      // rather than only a label in this page.
      await transport.request({
        pathId: 'agent.session.mode.update',
        params: { sessionId },
        body: {
          mode: 'assistant',
          executionMode: 'read_only',
          toolProfileVersion: 'control-center-v1',
          projectContextEnabled: false,
          piSkillsEnabled: true,
          codexSkillsEnabled: false,
        },
      });
      await transport.request({
        pathId: 'agent.session.prompt',
        params: { sessionId },
        body: {
          message: diagnosticPrompt(target, latestTraceId),
          clientMessageId: `trace-agent:${sessionId}:${Date.now()}`,
          delivery: 'prompt',
        },
      });
      return {
        sessionId,
        target,
        traceId: latestTraceId,
        promptAccepted: true,
        evidence,
      } satisfies TraceAgentReport;
    },
    onSuccess: (next) => {
      setRepairHandoff(null);
      setEvalReceipt(null);
      setReport(next);
    },
  });
  const repair = useMutation({
    mutationFn: async (diagnostic: TraceAgentReport) => {
      const executionMode = 'per_action' as const;
      const created = await transport.request({
        pathId: 'agent.sessions.create',
        body: {
          title: `修复 Trace 诊断 · ${diagnostic.target.title}`,
          mode: diagnostic.target.workspaceRoots.length ? 'coordinator' : 'assistant',
          toolProfileVersion: 'control-center-v1',
          executionMode,
          workspaceRoots: diagnostic.target.workspaceRoots,
        },
      });
      const sessionId = createdSessionId(created);
      if (!sessionId) throw new Error('修复 Agent Session 创建失败。');
      // A repair handoff is an ordinary per-action Session. The diagnostic
      // Session never receives write capability; each real change remains in
      // the existing Agent approval flow.
      await transport.request({
        pathId: 'agent.session.mode.update',
        params: { sessionId },
        body: {
          mode: diagnostic.target.workspaceRoots.length ? 'coordinator' : 'assistant',
          executionMode,
          workspaceRoots: diagnostic.target.workspaceRoots,
          toolProfileVersion: 'control-center-v1',
          toolAllowlistMode: 'profile',
          projectContextEnabled: true,
          piSkillsEnabled: true,
          codexSkillsEnabled: false,
        },
      });
      await transport.request({
        pathId: 'agent.session.prompt',
        params: { sessionId },
        body: {
          message: repairPrompt(diagnostic),
          clientMessageId: `trace-agent-repair:${sessionId}:${Date.now()}`,
          delivery: 'prompt',
        },
      });
      return { sessionId, promptAccepted: true } satisfies TraceRepairHandoff;
    },
    onSuccess: (next) => setRepairHandoff(next),
  });
  const recheck = useMutation({
    mutationFn: async ({ diagnostic, repairSessionId }: { diagnostic: TraceAgentReport; repairSessionId: string }) => {
      if (!diagnostic.traceId) throw new Error('当前诊断没有可复检的 Trace。');
      const repairSnapshot = await transport.request<ObservationSnapshotV1>({
        pathId: 'observability.snapshot',
        query: { limit: 100, sessionId: repairSessionId },
        responseContract: 'observation-snapshot.v1',
      });
      const repairTraceId = latestCompletedTrace(repairSnapshot, repairSessionId);
      if (!repairTraceId) throw new Error('修复 Session 尚未产生已完成 Trace，请先完成修复后再复检。');
      const detail = await transport.request<ObservabilityTraceGetV1>({
        pathId: 'observability.trace.get',
        params: { traceId: repairTraceId },
        responseContract: 'observability-trace-get.v1',
      });
      if (detail.traceId !== repairTraceId || detail.trace.traceId !== repairTraceId) {
        throw new Error('修复 Trace 返回标识不一致，暂不能复检。');
      }
      if (detail.truncated) throw new Error('修复 Trace 仍是截断窗口，暂不能复检。');
      if (detail.trace.status !== 'completed') {
        throw new Error(`修复 Trace 当前状态为 ${detail.trace.status}，暂不能复检。`);
      }
      // The existing Eval endpoint is the persistence authority.  A repair
      // handoff is an explicit user confirmation, so the evidence currently
      // present in the repair Trace becomes this run's human baseline.
      // It is deliberately labelled as a recheck baseline, not an automatic
      // quality claim or a second evaluation state machine.
      const requiredEvidenceIds = [...new Set(
        detail.trace.evidence
          .filter((item) => item.disposition === 'included')
          .map((item) => item.evidenceId),
      )];
      const evalRun = await transport.request<EvalRunV1>({
        pathId: 'observability.evals.evidence.run',
        body: {
          schemaVersion: 'rag-ime.observability-evidence-eval-request.v1',
          traceId: repairTraceId,
          requiredEvidenceIds,
          datasetId: 'trace-agent:recheck',
          labelRevision: `repair:${repairSessionId}`,
          truthKind: 'human',
        },
        responseContract: 'eval-run.v1',
      });
      return { sourceTraceId: diagnostic.traceId, repairTraceId, evalRun } satisfies TraceEvalReceipt;
    },
    onSuccess: (next) => {
      setEvalReceipt(next);
    },
  });

  useEffect(() => {
    if (!incomingTarget) return;
    setKind(incomingTarget.kind);
    setSelectedId(incomingTarget.id);
  }, [incomingTarget]);

  useEffect(() => {
    if (!items.length) {
      setSelectedId('');
      return;
    }
    if (!items.some((item) => item.id === selectedId)) setSelectedId(items[0].id);
  }, [items, selectedId]);

  useEffect(() => {
    setReport(null);
    setRepairHandoff(null);
    setEvalReceipt(null);
    repair.reset();
    recheck.reset();
  }, [kind, selectedId]);

  const refresh = () => {
    void targets.refetch();
    if (selected && !selected.handoffOnly) void snapshot.refetch();
    if (selected && selected.kind !== 'run') void sourceSnapshot.refetch();
  };
  const error = targets.error as Error | null;

  return (
    <ManagementPage
      actions={(
        <Button
          leadingIcon={<RefreshCw size={15} />}
          loading={targets.isFetching || snapshot.isFetching || sourceSnapshot.isFetching}
          onClick={refresh}
          size="small"
        >
          刷新对象
        </Button>
      )}
      description="从一段真实 Session 或 Room 运行记录开始，让诊断 Agent 找到失败、上下文问题、返工和浪费。"
      eyebrow="Trace / Eval"
      routeId="trace-agent"
      title="Trace Agent"
    >
      <QueryState error={error} isPending={targets.isPending} onRetry={() => void targets.refetch()}>
        <section aria-label="Trace Agent 诊断工作台" className="trace-agent-workspace">
          <header className="trace-agent-intro">
            <div className="trace-agent-intro__mark" aria-hidden="true"><Search size={20} /></div>
            <div>
              <span className="trace-agent-kicker">选择 → 关联 → 解释</span>
              <h2>让一段运行记录自己说清楚问题</h2>
              <p>诊断 Session 只读运行，加载专用 Skill，先给证据和候选修复；真正改动仍由普通 Agent 在授权后完成。</p>
            </div>
            <StatusBadge label="只读诊断" tone="info" />
          </header>

          <ManagementSection
            title="选择诊断输入"
            description="可选当前或历史对象。选择 Room 时会把主持 Session、全部行星、子 Agent、WorkItem、公开流转和相关 Trace 一起交给诊断 Agent。"
            trailing={<StatusBadge label={`${items.length} 个${kind === 'session' ? ' Session' : kind === 'room' ? ' Room' : '运行'}`} tone="neutral" />}
          >
            <div aria-label="诊断对象类型" className="trace-agent-kind-tabs" role="tablist">
              {(['session', 'room', 'run'] as const).map((candidate) => (
                <button
                  aria-selected={kind === candidate}
                  data-active={kind === candidate}
                  key={candidate}
                  onClick={() => setKind(candidate)}
                  role="tab"
                  type="button"
                >
                  {candidate === 'session' ? <MessageSquareText size={15} /> : candidate === 'room' ? <Network size={15} /> : <Activity size={15} />}
                  {candidate === 'session' ? 'Session 对话' : candidate === 'room' ? 'Room 协作' : '运行记录'}
                </button>
              ))}
            </div>
            {incomingHandoff ? (
              <div className="trace-agent-inline-note" data-testid="trace-agent-incoming-handoff">
                已从原位置带入：{incomingHandoff.title} · {incomingHandoff.entityId}。启动诊断时会同时提交原对象、错误和证据引用。
              </div>
            ) : null}
            {persistedReports.length ? (
              <section aria-label="已保存的 Trace 诊断报告" className="trace-agent-persisted-reports">
                <div className="trace-agent-persisted-reports__heading">
                  <div>
                    <span className="trace-agent-kicker">持久化报告</span>
                    <strong>已保存的 Trace 诊断</strong>
                    <p>报告正文保存在这个 Agent Session；刷新后仍可从这里重新打开。</p>
                  </div>
                  <StatusBadge label={`${persistedReports.length} 份`} tone="success" />
                </div>
                <div className="trace-agent-persisted-reports__list">
                  {persistedReports.map((item) => (
                    <div className="trace-agent-persisted-report" key={item.id}>
                      <div className="trace-agent-persisted-report__icon" aria-hidden="true"><CheckCircle2 size={15} /></div>
                      <div className="trace-agent-persisted-report__copy">
                        <strong>{item.title}</strong>
                        <small>{item.detail} · {formatTime(item.updatedAtMs)}</small>
                      </div>
                      <Button
                        leadingIcon={<ArrowUpRight size={14} />}
                        onClick={() => openDiagnosticSession(desktop, item.id)}
                        size="small"
                        variant="quiet"
                      >
                        打开诊断报告
                      </Button>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
            {selected ? (
              <div
                className="trace-agent-diagnostic-action"
                data-state={report ? 'complete' : start.isPending ? 'loading' : start.error ? 'error' : 'ready'}
                data-sticky="true"
                data-testid="trace-agent-diagnostic-action"
              >
                <div>
                  <strong>诊断当前{selected.handoffOnly ? '交接输入' : selected.kind === 'room' ? ' Room' : selected.kind === 'session' ? ' Session' : '运行'}</strong>
                  <span>{selected.handoffOnly ? '仅依据结构化交接包 · 不伪造 Session / Room / Run 快照' : selected.kind === 'room' ? '当前 Room · 全部行星 · WorkItems · 失败工具 · Context / Trace' : selected.kind === 'session' ? '完整时间线 · 失败工具 · Context / Trace' : '当前运行 · 关联 Trace / Eval / Sandbox'}</span>
                </div>
                <Button
                  disabled={start.isPending || Boolean(report)}
                  leadingIcon={start.isPending ? <LoaderCircle className="ui-spin" size={15} /> : <Sparkles size={15} />}
                  onClick={() => start.mutate(selected)}
                >
                  {report ? '诊断已启动' : start.isPending ? '正在启动诊断' : '开始诊断'}
                </Button>
                {report ? (
                  <Button
                    leadingIcon={<ArrowUpRight size={14} />}
                    onClick={() => openDiagnosticSession(desktop, report.sessionId)}
                    size="small"
                    variant="quiet"
                  >
                    打开诊断 Agent 对话
                  </Button>
                ) : null}
              </div>
            ) : null}
            {items.length ? (
              <>
                <div aria-label="可诊断对象" className="trace-agent-target-list" role="listbox">
                  {items.map((item) => (
                    <button
                      aria-selected={item.id === selectedId}
                      className="trace-agent-target"
                      data-active={item.id === selectedId}
                      key={item.id}
                      onClick={() => setSelectedId(item.id)}
                      role="option"
                      type="button"
                    >
                      <span className="trace-agent-target__icon" aria-hidden="true">
                        {item.kind === 'session' ? <MessageSquareText size={16} /> : item.kind === 'room' ? <Network size={16} /> : <Activity size={16} />}
                      </span>
                      <span className="trace-agent-target__copy">
                        <strong>{item.title}</strong>
                        <small>{item.detail}</small>
                      </span>
                      <span className="trace-agent-target__meta">
                        <StatusBadge label={statusLabel(item.status)} tone={statusTone(item.status)} />
                        <small>{formatTime(item.updatedAtMs)}</small>
                      </span>
                    </button>
                  ))}
                </div>
                {moreTargetsAvailable ? (
                  <Button
                    loading={targets.isFetchingNextPage[kind]}
                    onClick={() => void targets.fetchNextPage(kind)}
                    size="small"
                    variant="quiet"
                  >
                    加载更多 {kind === 'session' ? 'Session' : kind === 'room' ? 'Room' : '运行'}
                  </Button>
                ) : null}
              </>
            ) : (
              <EmptyState
                action={<Button onClick={refresh} size="small">重新读取</Button>}
                description={`当前没有可选的${kind === 'session' ? ' Session 对话' : kind === 'room' ? ' Room 协作' : '运行记录'}。`}
                icon={kind === 'session' ? MessageSquareText : kind === 'room' ? Network : Activity}
                title="没有诊断对象"
              />
            )}
          </ManagementSection>

          {selected ? (
            <section aria-label="已选择诊断对象" className="trace-agent-selected">
              <div className="trace-agent-selected__heading">
                <div>
                  <span className="trace-agent-kicker">当前输入</span>
                  <h2>{selected.title}</h2>
                  <p>{selected.handoffOnly ? '仅结构化交接包；没有可用的 canonical Session / Room / Run' : selected.kind === 'room' ? 'Room 全量协作拓扑' : selected.kind === 'run' ? '单个运行及其关联 Trace' : '单个 Session 对话与运行记录'} · {selected.id}</p>
                </div>
              </div>
              <div className="trace-agent-scope-grid" aria-label="诊断范围">
                <ScopeCard icon={Wrench} label="Tool / Browser / Runtime" detail="失败、超时、重复调用与运行状态" />
                <ScopeCard icon={GitBranch} label="Context / Room" detail="上下文质量、分工、返工与等待" />
                <ScopeCard icon={BrainCircuit} label="Memory / Knowledge / RAG" detail="召回、解析、排序与 Eval 对比" />
                <ScopeCard icon={Activity} label="Token / 延迟" detail="找出不成比例的流程成本" />
              </div>
              <div className="trace-agent-source-links" aria-label="原始证据入口">
                <span>原始证据</span>
                <Button leadingIcon={<ArrowUpRight size={14} />} onClick={() => openOriginal(desktop, selected)} size="small" variant="quiet">
                  {selected.handoff ? '回到原位置' : selected.kind === 'run' ? '打开运行记录' : '打开原对话'}
                </Button>
                <Button
                  disabled={!latestTraceId}
                  leadingIcon={<Activity size={14} />}
                  onClick={() => latestTraceId && openTrace(desktop, latestTraceId)}
                  size="small"
                  variant="quiet"
                >
                  {latestTraceId ? '打开最新 Trace' : '暂无 Trace'}
                </Button>
                {selected.kind === 'session' && selected.workspaceRoots.length ? (
                  <Button leadingIcon={<FolderOpen size={14} />} onClick={() => openFiles(desktop, selected.id)} size="small" variant="quiet">
                    打开工作区文件
                  </Button>
                ) : null}
              </div>
              {selected.kind !== 'run' ? (
                <TraceSourceTimeline
                  kind={selected.kind}
                  roomId={selected.kind === 'room' ? selected.id : ''}
                  loading={sourceSnapshot.isFetching}
                  source={sourceSnapshot.data}
                />
              ) : null}
              <TraceEvidence desktop={desktop} evidence={evidence} loading={sourceSnapshot.isFetching || snapshot.isFetching} />
              {selected.handoffOnly ? <p className="trace-agent-inline-note">这是 handoff-only 输入；没有 Session、Room 或 Run 标识，因此未请求 canonical snapshot。诊断 Agent 会以交接包和可回跳原位置为边界报告未知。</p> : null}
              {snapshot.error ? <p className="trace-agent-inline-note">最新 Trace 暂时无法读取；仍可以启动诊断，Agent 会在 Session 内按权限重新查询。</p> : null}
              {sourceSnapshot.error ? <p className="trace-agent-inline-note">原始对话快照暂时无法读取；诊断 Agent 仍会以可用的 Trace、Room 和运行证据标注未知边界。</p> : null}
            </section>
          ) : null}

          {start.error ? (
            <div aria-live="polite" className="trace-agent-result trace-agent-result--error" role="alert">
              <TriangleAlert size={18} />
              <div><strong>诊断未启动</strong><p>{publicErrorText(start.error, '诊断 Session 暂时无法启动，请稍后重试。')}</p></div>
            </div>
          ) : null}
          {report ? (
            <TraceAgentReport
              desktop={desktop}
              onRepair={() => repair.mutate(report)}
              onRerun={() => {
                setReport(null);
                setRepairHandoff(null);
                setEvalReceipt(null);
                repair.reset();
                recheck.reset();
                if (report.traceId) openTrace(desktop, report.traceId);
                else openOriginal(desktop, report.target);
              }}
              repairState={{ error: repair.error, isPending: repair.isPending }}
              repairHandoff={repairHandoff}
              evalReceipt={evalReceipt}
              evalList={evals.data}
              recheckState={{ error: recheck.error, isPending: recheck.isPending }}
              onRecheck={(handoff) => recheck.mutate({ diagnostic: report, repairSessionId: handoff.sessionId })}
              report={report}
            />
          ) : null}
        </section>
      </QueryState>
    </ManagementPage>
  );
}

function TraceAgentReport({
  report,
  desktop,
  onRepair,
  onRerun,
  repairState,
  repairHandoff,
  evalReceipt,
  evalList,
  onRecheck,
  recheckState,
}: {
  report: TraceAgentReport;
  desktop: ReturnType<typeof usePawOsDesktop>;
  onRepair: () => void;
  onRerun: () => void;
  repairState: { isPending: boolean; error: unknown };
  repairHandoff: TraceRepairHandoff | null;
  evalReceipt: TraceEvalReceipt | null;
  evalList?: ObservabilityEvalListV1;
  onRecheck: (handoff: TraceRepairHandoff) => void;
  recheckState: { isPending: boolean; error: unknown };
}) {
  const recheckLabelRevision = repairHandoff ? `repair:${repairHandoff.sessionId}` : '';
  const persistedEval = evalReceipt?.evalRun ?? evalList?.items.find((item) => (
    item.datasetId === 'trace-agent:recheck'
    && item.labelRevision === recheckLabelRevision
  )) ?? null;
  const sourceTraceId = evalReceipt?.sourceTraceId ?? report.traceId;
  const repairTraceId = evalReceipt?.repairTraceId ?? evalList?.traceId ?? '';
  return (
    <section aria-label="Trace 诊断报告" className="trace-agent-result trace-agent-result--success">
      <div className="trace-agent-result__icon" aria-hidden="true"><CheckCircle2 size={20} /></div>
      <div className="trace-agent-result__body">
        <div className="trace-agent-result__heading">
          <div><span className="trace-agent-kicker">报告已创建</span><h2>诊断 Session 正在生成证据报告</h2></div>
          <StatusBadge label="已提交" tone="success" />
        </div>
        <p>它会按 Tool、Runtime、Context、Room 分工、Memory 和 Knowledge/RAG 分段回看；未经重放或 Eval 支持的建议会标为候选/假设。</p>
        <div className="trace-agent-report-links">
          <Button leadingIcon={<ArrowUpRight size={14} />} onClick={() => openDiagnosticSession(desktop, report.sessionId)} size="small">打开诊断 Agent 对话</Button>
          <Button leadingIcon={<ArrowUpRight size={14} />} onClick={() => openOriginal(desktop, report.target)} size="small" variant="quiet">回到原{report.target.kind === 'room' ? ' Room' : report.target.kind === 'run' ? '运行记录' : ' Session'}</Button>
          {report.traceId ? <Button leadingIcon={<Activity size={14} />} onClick={() => openTrace(desktop, report.traceId)} size="small" variant="quiet">查看关联 Trace</Button> : null}
          <Button
            data-testid="trace-agent-repair"
            disabled={repairState.isPending || Boolean(repairHandoff)}
            leadingIcon={repairState.isPending ? <LoaderCircle className="ui-spin" size={14} /> : <Wrench size={14} />}
            onClick={onRepair}
            variant="primary"
          >
            {repairHandoff ? '修复 Agent 已就绪' : repairState.isPending ? '正在交接修复' : '交给 Agent 修复'}
          </Button>
          <Button leadingIcon={<RefreshCw size={14} />} onClick={onRerun} size="small" variant="quiet">
            {report.traceId ? '回到 Trace 重跑诊断' : '回到原记录重跑诊断'}
          </Button>
        </div>
        {repairState.error ? (
          <div aria-live="polite" className="trace-agent-repair-state trace-agent-repair-state--error" role="alert">
            <TriangleAlert size={15} />
            <span>{publicErrorText(repairState.error, '修复 Agent 暂时无法启动，请稍后重试。')}</span>
          </div>
        ) : null}
        {repairHandoff ? (
          <div aria-live="polite" className="trace-agent-repair-state trace-agent-repair-state--success" data-testid="trace-agent-repair-ready">
            <CheckCircle2 size={15} />
            <span>已创建按操作确认的普通 Agent Session；它收到当前对象、诊断 Session、Trace 和失败证据。完成并授权修改后，再读取修复 Session 的新 Trace 运行 Eval 复检。</span>
            <Button leadingIcon={<ArrowUpRight size={13} />} onClick={() => openDiagnosticSession(desktop, repairHandoff.sessionId)} size="small">
              打开修复 Session
            </Button>
            <Button
              disabled={recheckState.isPending || Boolean(persistedEval)}
              leadingIcon={recheckState.isPending ? <LoaderCircle className="ui-spin" size={13} /> : <RefreshCw size={13} />}
              onClick={() => onRecheck(repairHandoff)}
              size="small"
              variant="primary"
            >
              {persistedEval ? '复检已持久化' : recheckState.isPending ? '正在运行 Eval 复检' : '修复后运行 Eval 复检'}
            </Button>
          </div>
        ) : null}
        {recheckState.error ? (
          <div aria-live="polite" className="trace-agent-repair-state trace-agent-repair-state--error" role="alert">
            <TriangleAlert size={15} />
            <span>{publicErrorText(recheckState.error, '修复 Session 尚未形成可复检的 Trace。')}</span>
          </div>
        ) : null}
        {persistedEval ? (
          <div aria-live="polite" className="trace-agent-repair-state trace-agent-repair-state--success" data-testid="trace-agent-eval-receipt" role="status">
            <CheckCircle2 size={15} />
            <span>
              Eval 复检已持久化：{persistedEval.evalRunId} · {evalStatusLabel(persistedEval.status)}
            </span>
            <small>诊断 Trace：{sourceTraceId || '未知'} · 修复 Trace：{repairTraceId || '未知'} · 本次以修复 Trace 已记录 evidence 作为显式复检基线，不代替独立质量标注。</small>
          </div>
        ) : null}
        <dl className="trace-agent-report-meta">
          <div><dt>SkillRef</dt><dd>{TRACE_AGENT_SKILL_REF}</dd></div>
          <div><dt>诊断输入</dt><dd>{report.target.kind} · {report.target.id}</dd></div>
          <div><dt>权限</dt><dd>只读；候选修复需普通 Agent 授权</dd></div>
        </dl>
      </div>
    </section>
  );
}

function ScopeCard({ icon: Icon, label, detail }: { icon: LucideIcon; label: string; detail: string }) {
  return <div className="trace-agent-scope-card"><Icon aria-hidden="true" size={16} /><div><strong>{label}</strong><small>{detail}</small></div></div>;
}

type TraceEvidenceItem = {
  id: string;
  source: string;
  status: string;
  title: string;
  summary: string;
  createdAtMs: number;
  traceId?: string;
};

type TraceTimelineKind = 'user' | 'assistant' | 'reasoning' | 'tool_started' | 'tool_finished' | 'room_event';

type TraceTimelineEntry = {
  id: string;
  kind: TraceTimelineKind;
  label: string;
  summary: string;
  originalText?: string;
  sequence: number;
  createdAtMs: number;
};

function TraceSourceTimeline({
  kind,
  loading,
  roomId,
  source,
}: {
  kind: 'session' | 'room';
  loading: boolean;
  roomId: string;
  source: unknown;
}) {
  const roomHistory = useRoomTraceHistory(kind === 'room' ? roomId : '', kind === 'room' ? source : undefined);
  const timelineSource = kind === 'room' ? roomHistory.source : source;
  const entries = useMemo(() => sourceTimeline(kind, timelineSource), [kind, timelineSource]);
  const [visibleCount, setVisibleCount] = useState(TRACE_TIMELINE_PAGE_SIZE);
  const [expandedEntries, setExpandedEntries] = useState<ReadonlySet<string>>(() => new Set());
  useEffect(() => {
    setVisibleCount(TRACE_TIMELINE_PAGE_SIZE);
    setExpandedEntries(new Set());
  }, [kind, roomId, source]);
  const visibleEntries = entries.slice(-visibleCount);
  const hiddenCount = entries.length - visibleEntries.length;
  const loadEarlierRoomHistory = async () => {
    const loadedCount = await roomHistory.loadEarlier();
    if (loadedCount > 0) setVisibleCount((current) => Math.min(entries.length + loadedCount, current + loadedCount));
  };
  return (
    <section
      aria-label="原始对话时间线"
      className="trace-agent-timeline"
      data-scrollable={entries.length ? 'true' : 'false'}
    >
      <div className="trace-agent-timeline__heading">
        <div>
          <span className="trace-agent-kicker">原始记录</span>
          <h3>{kind === 'room' ? 'Room 对话与行动' : 'Session 对话与行动'}</h3>
          <p>按 timelineSequence / sequence 保留原始顺序；摘要辅助浏览，长消息可展开全文。</p>
        </div>
        <StatusBadge
          label={loading || roomHistory.loading ? '读取中' : `${visibleEntries.length} / ${entries.length} 条`}
          tone={loading || roomHistory.loading ? 'info' : entries.length ? 'neutral' : 'warning'}
        />
      </div>
      {visibleEntries.length ? (
        <>
          <div aria-label="原始对话与行动列表" className="trace-agent-timeline__list" tabIndex={0}>
          {visibleEntries.map((entry) => {
            const preview = compactTimelineText(entry.summary);
            const originalText = entry.originalText?.trim() || entry.summary;
            const expandable = preview !== entry.summary || originalText !== entry.summary;
            const expanded = expandedEntries.has(entry.id);
            return (
            <article
              className={`trace-agent-timeline__entry trace-agent-timeline__entry--${entry.kind}`}
              data-kind={entry.kind}
              data-sequence={entry.sequence}
              data-testid="trace-agent-timeline-entry"
              key={entry.id}
            >
              <span className="trace-agent-timeline__icon" aria-hidden="true">
                {entry.kind === 'reasoning' ? <BrainCircuit size={14} /> : entry.kind === 'tool_started' || entry.kind === 'tool_finished' ? <Wrench size={14} /> : entry.kind === 'room_event' ? <Network size={14} /> : <MessageSquareText size={14} />}
              </span>
              <div className="trace-agent-timeline__copy">
                <div className="trace-agent-timeline__title">
                  <strong>{entry.label}</strong>
                  <span> · {expandable ? preview : entry.summary}</span>
                  {expandable ? (
                    <button
                      aria-expanded={expanded}
                      aria-label={`${expanded ? '收起' : '展开'}${entry.label}全文`}
                      onClick={() => setExpandedEntries((current) => toggled(current, entry.id))}
                      type="button"
                    >
                      {expanded ? '收起' : '展开全文'}
                    </button>
                  ) : null}
                  <small>#{entry.sequence}</small>
                </div>
                {expanded ? <pre className="trace-agent-timeline__original">{originalText}</pre> : null}
              </div>
            </article>
          );})}
          </div>
          <div className="trace-agent-timeline__controls">
            {hiddenCount > 0 ? (
              <Button
                onClick={() => setVisibleCount((current) => Math.min(entries.length, current + TRACE_TIMELINE_PAGE_SIZE))}
                size="small"
                variant="quiet"
              >
                加载更早 {Math.min(hiddenCount, TRACE_TIMELINE_PAGE_SIZE)} 条
              </Button>
            ) : null}
            {kind === 'room' && roomHistory.hasMore ? (
              <Button
                disabled={roomHistory.loading}
                loading={roomHistory.loading}
                onClick={() => void loadEarlierRoomHistory()}
                size="small"
                variant="quiet"
              >
                从 Room history 加载更早
              </Button>
            ) : null}
          </div>
          {roomHistory.error ? (
            <p aria-live="polite" className="trace-agent-inline-note" role="alert">
              Room history 暂时无法读取：{publicErrorText(roomHistory.error, '请稍后重试。')}
            </p>
          ) : null}
        </>
      ) : (
        <p className="trace-agent-timeline__empty">当前快照没有可投影的对话或行动摘要；仍可打开原始{kind === 'room' ? ' Room' : ' Session'}查看完整记录。</p>
      )}
    </section>
  );
}

type RoomTraceHistoryState = {
  source: unknown;
  hasMore: boolean;
  loading: boolean;
  error: unknown;
  loadEarlier: () => Promise<number>;
};

function useRoomTraceHistory(roomId: string, source: unknown): RoomTraceHistoryState {
  const transport = useControlTransport();
  const [pages, setPages] = useState<RoomEventPage[]>([]);
  const [nextBeforeSequence, setNextBeforeSequence] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setPages([]);
    setNextBeforeSequence(roomHistoryCursor(source));
    setLoading(false);
    setError(null);
  }, [roomId, source]);

  const loadEarlier = async (): Promise<number> => {
    if (!roomId || loading || !nextBeforeSequence) return 0;
    const requestedBeforeSequence = nextBeforeSequence;
    setLoading(true);
    setError(null);
    try {
      const page = parseRoomEventPage(await transport.request({
        pathId: 'agent.room.history',
        params: { roomId },
        query: { beforeSequence: requestedBeforeSequence, limit: 200 },
        responseContract: 'agent-room-event-page.v1',
      }));
      if (page.roomId !== roomId) throw new Error('Room history 返回了不属于当前 Room 的事件。');
      setPages((current) => [...current, page]);
      setNextBeforeSequence(page.hasMore ? page.nextBeforeSequence : 0);
      return page.items.length;
    } catch (requestError) {
      setError(requestError);
      return 0;
    } finally {
      setLoading(false);
    }
  };

  return {
    source: mergeRoomTraceHistory(source, pages),
    hasMore: Boolean(nextBeforeSequence),
    loading,
    error,
    loadEarlier,
  };
}

function roomHistoryCursor(source: unknown): number {
  const payload = asRecord(source);
  const events = roomSourceEvents(payload);
  const firstEventSequence = events.reduce<number>((lowest, event) => {
    const sequence = numberValue(asRecord(event).sequence);
    return sequence > 0 && (lowest === 0 || sequence < lowest) ? sequence : lowest;
  }, 0);
  const firstSequence = numberValue(payload.firstSequence, firstEventSequence);
  return payload.truncated === true || firstSequence > 1 ? firstSequence : 0;
}

function mergeRoomTraceHistory(source: unknown, pages: RoomEventPage[]): unknown {
  const payload = asRecord(source);
  const events = [...roomSourceEvents(payload), ...pages.flatMap((page) => page.items)];
  const seen = new Set<string>();
  const mergedEvents = events.filter((event, index) => {
    const record = asRecord(event);
    const sequence = numberValue(record.sequence);
    const eventId = stringValue(record.eventId);
    const key = sequence > 0 ? `sequence:${sequence}` : eventId ? `id:${eventId}` : `index:${index}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return { ...payload, events: mergedEvents };
}

function roomSourceEvents(source: Record<string, unknown>): unknown[] {
  return Array.isArray(source.events)
    ? source.events
    : Array.isArray(source.posts)
      ? source.posts
      : [];
}

function sourceTimeline(kind: 'session' | 'room', source: unknown): TraceTimelineEntry[] {
  const entries: TraceTimelineEntry[] = [];
  const seen = new Set<string>();
  const add = (entry: TraceTimelineEntry) => {
    const summary = entry.summary.trim();
    if (!summary) return;
    const key = `${entry.kind}:${entry.sequence}:${summary}`;
    if (seen.has(key)) return;
    seen.add(key);
    entries.push({ ...entry, summary });
  };
  if (kind === 'session') sessionTimelineEntries(source, add);
  else roomTimelineEntries(source, add);
  return entries.sort((left, right) => (left.sequence - right.sequence) || (left.createdAtMs - right.createdAtMs));
}

function sessionTimelineEntries(
  source: unknown,
  add: (entry: TraceTimelineEntry) => void,
): void {
  const payload = asRecord(source);
  const rawMessages = Array.isArray(payload.items) ? payload.items : Array.isArray(payload.messages) ? payload.messages : [];
  rawMessages.forEach((rawMessage, index) => {
    const message = asRecord(rawMessage);
    const role = stringValue(message.role);
    if (role !== 'user' && role !== 'assistant') return;
    const messageSequence = timelinePosition(message, index);
    const blocks = Array.isArray(message.blocks) ? message.blocks : [];
    const text = blocks
      .map(asRecord)
      .filter((block) => stringValue(block.type) === 'text')
      .map((block) => firstText(asRecord(block.data), ['text', 'markdown', 'bodyMarkdown']))
      .filter(Boolean)
      .join(' ');
    const summary = text || firstText(message, ['text', 'message', 'summary']);
    if (summary) {
      add({
        id: `message:${stringValue(message.id, String(index))}`,
        kind: role,
        label: role === 'user' ? '用户' : '助手',
        summary,
        sequence: messageSequence,
        createdAtMs: numberValue(message.createdAtMs),
      });
    }
    blocks.forEach((rawBlock, blockIndex) => {
      const block = asRecord(rawBlock);
      const blockKind = sessionActivityKind(stringValue(block.type));
      if (!blockKind) return;
      const blockData = asRecord(block.data);
      add({
        id: `block:${stringValue(block.id, `${index}:${blockIndex}`)}`,
        kind: blockKind,
        label: timelineLabel(blockKind),
        summary: timelineSummary(blockData, block),
        originalText: timelineOriginalText(blockData),
        sequence: timelinePosition(block, messageSequence + (blockIndex + 1) / 100),
        createdAtMs: numberValue(blockData.createdAtMs, numberValue(message.createdAtMs)),
      });
    });
  });
  const rawEvents = Array.isArray(payload.liveEvents) ? payload.liveEvents : Array.isArray(payload.events) ? payload.events : [];
  rawEvents.forEach((rawEvent, index) => {
    const event = asRecord(rawEvent);
    const eventKind = sessionActivityKind(stringValue(event.eventType));
    if (!eventKind) return;
    const eventPayload = asRecord(event.payload);
    add({
      id: `event:${stringValue(event.eventId, String(index))}`,
      kind: eventKind,
      label: timelineLabel(eventKind),
      summary: timelineSummary(eventPayload, event),
      originalText: timelineOriginalText(eventPayload),
      sequence: timelinePosition(event, index),
      createdAtMs: numberValue(event.createdAtMs),
    });
  });
}

function roomTimelineEntries(
  source: unknown,
  add: (entry: TraceTimelineEntry) => void,
): void {
  const payload = asRecord(source);
  const rawEvents = Array.isArray(payload.events) ? payload.events : Array.isArray(payload.posts) ? payload.posts : [];
  rawEvents.forEach((rawEvent, index) => {
    const event = asRecord(rawEvent);
    const eventType = stringValue(event.eventType);
    const eventPayload = asRecord(event.payload);
    const eventData = asRecord(eventPayload.data);
    const activityKind = sessionActivityKind(stringValue(
      eventPayload.sourceEventType,
      stringValue(
        eventData.sourceEventType,
        stringValue(eventPayload.activityKind, stringValue(eventPayload.activityType, stringValue(eventPayload.kind))),
      ),
    )) ?? sessionActivityKind(stringValue(
      eventPayload.activityKind,
      stringValue(eventPayload.activityType, stringValue(eventPayload.kind)),
    ));
    const kind = activityKind
      ?? (eventType === 'user_message' ? 'user' : eventType === 'participant_message' || eventType === 'room_post' || eventType === 'participant_delta' ? 'assistant' : 'room_event');
    add({
      id: `room-event:${stringValue(event.eventId, String(index))}`,
      kind,
      label: kind === 'user' ? '用户' : kind === 'assistant' ? '助手' : timelineLabel(kind),
      summary: timelineSummary(eventPayload, event),
      originalText: timelineOriginalText(eventPayload),
      sequence: timelinePosition(event, index),
      createdAtMs: numberValue(event.createdAtMs),
    });
  });
}

function sessionActivityKind(value: string): Extract<TraceTimelineKind, 'reasoning' | 'tool_started' | 'tool_finished'> | undefined {
  if (value === 'reasoning' || value === 'reasoning_summary') return 'reasoning';
  if (value === 'tool_started' || value === 'tool_start') return 'tool_started';
  if (value === 'tool_finished' || value === 'tool_result' || value === 'tool_finish') return 'tool_finished';
  if (value === 'tool_call') return 'tool_started';
  return undefined;
}

function timelineLabel(kind: TraceTimelineKind): string {
  return ({
    user: '用户',
    assistant: '助手',
    reasoning: '思考摘要',
    tool_started: '工具开始',
    tool_finished: '工具完成',
    room_event: 'Room 事件',
  } satisfies Record<TraceTimelineKind, string>)[kind];
}

function timelineSummary(value: Record<string, unknown>, fallback: Record<string, unknown> = {}): string {
  const direct = firstText(value, ['summary', 'text', 'message', 'content', 'error', 'label', 'title']);
  if (direct) return direct;
  const nestedData = asRecord(value.data);
  const nested = firstText(nestedData, ['summary', 'text', 'message', 'content', 'error', 'label', 'title']);
  if (nested) return nested;
  const post = asRecord(value.post);
  const postText = firstText(post, ['content', 'text', 'summary', 'message']);
  if (postText) return postText;
  const directMessage = asRecord(value.message);
  const message = Object.keys(directMessage).length ? directMessage : asRecord(nestedData.message);
  const messageText = firstText(message, ['text', 'summary', 'message']);
  if (messageText) return messageText;
  const blockText = Array.isArray(message.blocks)
    ? message.blocks.map(asRecord)
      .map((block) => firstText(asRecord(block.data), ['text', 'markdown', 'bodyMarkdown', 'content']))
      .filter(Boolean)
      .join(' ')
    : '';
  if (blockText) return blockText;
  const tool = [
    stringValue(value.toolName, stringValue(nestedData.toolName, stringValue(fallback.toolName))),
    stringValue(value.toolId, stringValue(nestedData.toolId, stringValue(fallback.toolId))),
    stringValue(value.operation, stringValue(nestedData.operation, stringValue(fallback.operation))),
  ]
    .filter(Boolean)
    .join(' · ');
  if (tool) return tool;
  const items = Array.isArray(value.items) ? value.items.map((item) => stringValue(item)).filter(Boolean).join(' · ') : '';
  return items;
}

function timelineOriginalText(value: Record<string, unknown>): string {
  const direct = firstText(value, ['text', 'markdown', 'bodyMarkdown', 'content', 'message', 'error', 'summary']);
  if (direct) return direct;
  const nested = asRecord(value.data);
  const nestedText = firstText(nested, ['text', 'markdown', 'bodyMarkdown', 'content', 'message', 'error', 'summary']);
  if (nestedText) return nestedText;
  const post = asRecord(value.post);
  return firstText(post, ['content', 'text', 'message', 'summary']);
}

function timelinePosition(value: Record<string, unknown>, fallback: number): number {
  return numberValue(value.timelineSequence, numberValue(value.sequence, numberValue(value.createdAtMs, fallback)));
}

function compactTimelineText(value: string, maxLength = 180): string {
  const compact = value.replace(/\s+/g, ' ').trim();
  return compact.length > maxLength ? `${compact.slice(0, maxLength - 1)}…` : compact;
}

function toggled(current: ReadonlySet<string>, key: string): Set<string> {
  const next = new Set(current);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

function TraceEvidence({ desktop, evidence, loading }: { desktop: ReturnType<typeof usePawOsDesktop>; evidence: TraceEvidenceItem[]; loading: boolean }) {
  return (
    <section aria-label="已读取的失败证据" className="trace-agent-evidence">
      <div className="trace-agent-evidence__heading">
        <div>
          <span className="trace-agent-kicker">证据先于结论</span>
          <h3>已读取的失败与异常</h3>
        </div>
        <StatusBadge label={loading ? '读取中' : `${evidence.length} 条证据`} tone={loading ? 'info' : evidence.length ? 'warning' : 'neutral'} />
      </div>
      {evidence.length ? (
        <div className="trace-agent-evidence__list">
          {evidence.map((item) => (
            <article className="trace-agent-evidence__item" key={item.id}>
              <span className={`trace-agent-evidence__dot trace-agent-evidence__dot--${item.status}`} aria-hidden="true" />
              <div>
                <div className="trace-agent-evidence__title"><strong>{item.title}</strong><small>{item.source} · {formatTime(item.createdAtMs)}</small></div>
                <p>{item.summary}</p>
                {item.traceId ? (
                  <Button leadingIcon={<Activity size={12} />} onClick={() => openTrace(desktop, item.traceId!)} size="small" variant="quiet">
                    跳到此 Trace
                  </Button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="trace-agent-evidence__empty">当前没有已投影的失败明细。诊断 Agent 会继续检查原始 Session JSONL、Room 事件与 Trace；没有证据的地方会明确标为未知。</p>
      )}
    </section>
  );
}

function useTraceTargets(
  transport: ReturnType<typeof useControlTransport>,
) {
  const sessions = useInfiniteQuery({
    queryKey: ['trace-agent', 'targets', 'session'],
    initialPageParam: null as TraceListCursor | null,
    queryFn: async ({ pageParam, signal }) => listTargetPage(
      await transport.request({
        pathId: 'agent.sessions.list',
        query: {
          limit: 200,
          includeArchived: true,
          includeInternal: false,
          ...(pageParam ? pageParam : {}),
        },
        signal,
      }),
      'session',
    ),
    getNextPageParam: (lastPage) => lastPage.nextCursor,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const rooms = useInfiniteQuery({
    queryKey: ['trace-agent', 'targets', 'room'],
    initialPageParam: null as TraceListCursor | null,
    queryFn: async ({ pageParam, signal }) => listTargetPage(
      await transport.request({
        pathId: 'agent.rooms.list',
        query: {
          limit: 100,
          includeArchived: true,
          ...(pageParam ? pageParam : {}),
        },
        signal,
      }),
      'room',
    ),
    getNextPageParam: (lastPage) => lastPage.nextCursor,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const runs = useInfiniteQuery({
    queryKey: ['trace-agent', 'targets', 'run'],
    initialPageParam: 0,
    queryFn: async ({ pageParam, signal }) => {
      const value = await transport.request<ObservationSnapshotV1>({
        pathId: 'observability.snapshot',
        query: { limit: 200, ...(pageParam > 0 ? { beforeSequence: pageParam } : {}) },
        responseContract: 'observation-snapshot.v1',
        signal,
      });
      return {
        items: runItems(value),
        nextBeforeSequence: observationNextBeforeSequence(value),
      };
    },
    getNextPageParam: (lastPage) => lastPage.nextBeforeSequence || undefined,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const data = useMemo<TraceTargetCatalog>(() => ({
    sessions: uniqueTargets(sessions.data?.pages.flatMap((page) => page.items) ?? []),
    rooms: uniqueTargets(rooms.data?.pages.flatMap((page) => page.items) ?? []),
    runs: uniqueTargets(runs.data?.pages.flatMap((page) => page.items) ?? []),
    hasMore: {
      session: Boolean(sessions.hasNextPage),
      room: Boolean(rooms.hasNextPage),
      run: Boolean(runs.hasNextPage),
    },
  }), [rooms.data, rooms.hasNextPage, runs.data, runs.hasNextPage, sessions.data, sessions.hasNextPage]);

  return {
    data,
    error: sessions.error ?? rooms.error ?? runs.error,
    isPending: sessions.isPending || rooms.isPending || runs.isPending,
    isFetching: sessions.isFetching || rooms.isFetching || runs.isFetching,
    isFetchingNextPage: {
      session: sessions.isFetchingNextPage,
      room: rooms.isFetchingNextPage,
      run: runs.isFetchingNextPage,
    } satisfies Record<TraceTargetKind, boolean>,
    fetchNextPage: (kind: TraceTargetKind) => (
      kind === 'session' ? sessions.fetchNextPage() : kind === 'room' ? rooms.fetchNextPage() : runs.fetchNextPage()
    ),
    refetch: () => Promise.all([sessions.refetch(), rooms.refetch(), runs.refetch()]),
  };
}

type TraceListCursor = {
  beforeUpdatedAtMs: number;
  beforeId: string;
};

type TraceListPage = {
  items: TraceTarget[];
  nextCursor?: TraceListCursor;
};

function listTargetPage(value: unknown, kind: 'session' | 'room'): TraceListPage {
  const payload = asRecord(value);
  const nextUpdatedAtMs = numberValue(payload.nextBeforeUpdatedAtMs);
  const nextId = stringValue(payload.nextBeforeId);
  return {
    items: targetItems(value, kind),
    nextCursor: payload.hasMore === true && nextUpdatedAtMs > 0 && nextId
      ? { beforeUpdatedAtMs: nextUpdatedAtMs, beforeId: nextId }
      : undefined,
  };
}

function observationNextBeforeSequence(value: ObservationSnapshotV1): number {
  if (!value.truncated) return 0;
  return value.items.reduce((lowest, item) => (
    item.sequence > 0 && (lowest === 0 || item.sequence < lowest) ? item.sequence : lowest
  ), 0);
}

function uniqueTargets(items: TraceTarget[]): TraceTarget[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${item.kind}:${item.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function runItems(value: ObservationSnapshotV1): TraceTarget[] {
  const grouped = new Map<string, ObservationSnapshotV1['items'][number]>();
  for (const item of value.items) {
    if (!item.runId) continue;
    const previous = grouped.get(item.runId);
    if (!previous || item.sequence > previous.sequence || item.createdAtMs > previous.createdAtMs) grouped.set(item.runId, item);
  }
  return [...grouped.values()]
    .sort((left, right) => (right.sequence - left.sequence) || (right.createdAtMs - left.createdAtMs))
    .map((item) => ({
      kind: 'run' as const,
      id: item.runId,
      title: item.status === 'failed' ? `运行失败 · ${item.name || item.runId}` : item.name || `运行 ${item.runId}`,
      status: item.status,
      updatedAtMs: item.createdAtMs,
      detail: `${item.runId} · ${item.category} · ${item.summary || '关联 Trace 运行'}`,
      workspaceRoots: [],
    }));
}

function targetItems(value: unknown, kind: TraceTargetKind): TraceTarget[] {
  const payload = asRecord(value);
  const raw = Array.isArray(payload.items) ? payload.items : Array.isArray(payload.sessions) ? payload.sessions : Array.isArray(payload.rooms) ? payload.rooms : [];
  return raw.map((entry) => {
    const item = asRecord(entry);
    const id = stringValue(item.id) || stringValue(item.sessionId) || stringValue(item.roomId);
    const title = stringValue(item.title) || (kind === 'session' ? `Session ${id}` : `Room ${id}`);
    const workspaceRoots = Array.isArray(item.workspaceRoots) ? item.workspaceRoots.map((root) => stringValue(root)).filter(Boolean) : [];
    const detail = kind === 'room'
      ? `${numberValue(item.participantCount, numberValue(item.memberCount, 0)) || '多'} 个协作节点 · ${stringValue(item.description, '协作运行记录')}`
      : `${numberValue(item.messageCount, 0)} 条消息 · ${stringValue(item.lastMessagePreview, '暂无最后消息')}`;
    return {
      kind,
      id,
      title,
      status: stringValue(item.status, 'idle'),
      updatedAtMs: numberValue(item.updatedAtMs, numberValue(item.createdAtMs)),
      detail,
      workspaceRoots,
    };
  }).filter((item) => Boolean(item.id));
}

function isTraceDiagnosticSession(target: TraceTarget): boolean {
  return target.kind === 'session' && target.title.startsWith(TRACE_DIAGNOSTIC_TITLE_PREFIX);
}

function latestTrace(value: ObservationSnapshotV1 | undefined): string {
  const items = Array.isArray(value?.items) ? value.items : [];
  return [...items]
    .sort((left, right) => (right.sequence - left.sequence) || (right.createdAtMs - left.createdAtMs))
    .map((item) => item.traceId)
    .find(Boolean) ?? '';
}

function latestCompletedTrace(value: ObservationSnapshotV1 | undefined, sessionId?: string): string {
  const items = Array.isArray(value?.items) ? value.items : [];
  return [...items]
    .filter((item) => item.status === 'completed' && Boolean(item.traceId) && (!sessionId || item.sessionId === sessionId))
    .sort((left, right) => (right.sequence - left.sequence) || (right.createdAtMs - left.createdAtMs))
    .map((item) => item.traceId)
    .find(Boolean) ?? '';
}

function sourceEvidence(observations: ObservationSnapshotV1 | undefined, source: unknown): TraceEvidenceItem[] {
  const evidence: TraceEvidenceItem[] = [];
  for (const item of observations?.items ?? []) {
    const summary = item.summary.trim();
    if (item.status === 'failed' || /(error|fail|failed|timeout|timed out|validation|失败|错误|超时|验证)/i.test(`${item.name} ${summary}`)) {
      evidence.push({
        id: `trace:${item.eventId}`,
        source: `Trace · ${item.traceId}`,
        status: item.status,
        title: item.name || item.phase,
        summary: summary || 'Trace 标记为异常，但未提供摘要。',
        createdAtMs: item.createdAtMs,
        traceId: item.traceId,
      });
    }
  }
  const payload = asRecord(source);
  const rawMessages = Array.isArray(payload.items) ? payload.items : Array.isArray(payload.messages) ? payload.messages : [];
  for (const rawMessage of rawMessages) {
    const message = asRecord(rawMessage);
    const messageId = stringValue(message.id, `message-${evidence.length}`);
    const blocks = Array.isArray(message.blocks) ? message.blocks : [];
    const directSummary = firstText(message, ['error', 'errorMessage', 'message', 'summary']);
    if (directSummary && (stringValue(message.status) === 'failed' || /(error|fail|failed|timeout|timed out|validation|失败|错误|超时|验证)/i.test(directSummary))) {
      evidence.push({
        id: `message:${messageId}:summary`,
        source: `Session transcript · ${messageId}`,
        status: stringValue(message.status, 'failed'),
        title: '消息异常',
        summary: directSummary,
        createdAtMs: numberValue(message.createdAtMs),
      });
    }
    for (const rawBlock of blocks) {
      const block = asRecord(rawBlock);
      const data = asRecord(block.data);
      const blockType = stringValue(block.type, 'message');
      const blockStatus = stringValue(block.status, stringValue(message.status, 'info'));
      const summary = firstText(data, ['error', 'errorMessage', 'message', 'summary', 'text', 'markdown']);
      if (!summary || (blockStatus !== 'failed' && blockType !== 'error' && !/(error|fail|failed|timeout|timed out|validation|失败|错误|超时|验证)/i.test(summary))) continue;
      evidence.push({
        id: `message:${messageId}:${stringValue(block.id, String(evidence.length))}`,
        source: `Session transcript · ${messageId}`,
        status: blockStatus,
        title: blockType === 'tool_result' ? 'Tool 结果' : blockType === 'error' ? '运行错误' : '消息异常',
        summary,
        createdAtMs: numberValue(message.createdAtMs),
      });
    }
  }
  const rawEvents = Array.isArray(payload.events) ? payload.events : Array.isArray(payload.liveEvents) ? payload.liveEvents : [];
  for (const rawEvent of rawEvents) {
    const event = asRecord(rawEvent);
    const eventPayload = asRecord(event.payload);
    const summary = firstText(eventPayload, ['error', 'errorMessage', 'message', 'summary', 'text']);
    const eventStatus = stringValue(event.status, stringValue(event.eventType, 'info'));
    if (!summary || (eventStatus !== 'failed' && !/(error|fail|failed|timeout|timed out|validation|失败|错误|超时|验证)/i.test(summary))) continue;
    evidence.push({
      id: `event:${stringValue(event.eventId, String(evidence.length))}`,
      source: `Room event · ${stringValue(event.eventType, 'event')}`,
      status: eventStatus,
      title: stringValue(event.name, stringValue(event.eventType, '协作事件')),
      summary,
      createdAtMs: numberValue(event.createdAtMs),
    });
  }
  const seen = new Set<string>();
  return evidence.filter((item) => {
    const key = `${item.source}:${item.summary}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).sort((left, right) => right.createdAtMs - left.createdAtMs).slice(0, 30);
}

function firstText(value: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const text = stringValue(value[key]);
    if (text) return text;
  }
  return '';
}

function evalStatusLabel(status: string): string {
  return ({
    queued: '排队中',
    running: '运行中',
    completed: '完成',
    failed: '失败',
  } as Record<string, string>)[status] ?? status;
}

function createdSessionId(value: unknown): string {
  const payload = asRecord(value);
  return stringValue(asRecord(payload.session).id) || stringValue(payload.sessionId);
}

function traceTargetFromHandoff(handoff: TraceAgentHandoff): TraceTarget {
  const roomScoped = ['room', 'planet', 'satellite'].includes(handoff.kind) && handoff.roomId;
  const handoffOnly = !handoff.sessionId && !handoff.roomId && !handoff.runId;
  const kind: TraceTargetKind = roomScoped
    ? 'room'
    : handoff.sessionId
      ? 'session'
      : handoff.roomId
        ? 'room'
        : 'run';
  const id = kind === 'session'
    ? handoff.sessionId!
    : kind === 'room'
      ? handoff.roomId!
      : handoff.runId || handoff.entityId;
  return {
    kind,
    id,
    title: handoff.title,
    status: 'failed',
    updatedAtMs: handoff.occurredAtMs,
    detail: handoff.summary,
    workspaceRoots: handoff.workspaceRoots,
    handoffOnly,
    handoff,
  };
}

function diagnosticPrompt(target: TraceTarget, traceId: string): string {
  const safeTargetId = redactTraceAgentText(target.id, 180);
  const safeTargetTitle = redactTraceAgentText(target.title, 180);
  const safeTraceId = redactTraceAgentText(traceId, 180);
  return [
    `先调用 skill_load 加载 name=trace-agent-diagnostics；SkillRef=${TRACE_AGENT_SKILL_REF}。`,
    '',
    '这是一次只读诊断。不要修改代码、配置、Prompt、路由或评测数据；只输出证据、根因判断和候选修复，任何真实改动都交给用户授权后的普通 Agent。',
    `诊断对象：${target.kind} ${safeTargetId}（${safeTargetTitle}）`,
    target.handoffOnly
      ? '这是 handoff-only 输入，没有可用的 canonical Session / Room / Run；不要把 entityId 当作 runId，也不要调用 observability.snapshot 伪造查询。'
      : traceId ? `当前已发现的最新 Trace：${safeTraceId}` : '当前尚未发现单一最新 Trace，请从对象范围读取关联 Trace。',
    ...(target.handoff ? [
      '',
      '下面是用户从原位置明确送来的结构化诊断输入。它是本次诊断的精确入口；保留所有 ID 和引用，并回跳到 sourceRoute 复核原记录。',
      '--- TRACE_AGENT_HANDOFF ---',
      JSON.stringify(target.handoff, null, 2),
      '--- END TRACE_AGENT_HANDOFF ---',
    ] : []),
    '',
    '请使用现有 Observability/TraceStore/Eval 与对象本身的真实记录，覆盖：',
    '1. Tool、Browser、Provider、Runtime 的失败、超时、重复调用和未闭合状态；',
    '2. 每轮实际 Context 的遗漏、污染、重复和不必要加载；',
    '3. Room 的任务分派、相互 @、等待、返工、重复确认、WorkItem 和子 Agent 关系；',
    '4. Memory 召回质量与 Knowledge/RAG 的解析、检索、排序、参数和 Eval 证据；',
    '5. 哪一步浪费了 Token/延迟，以及减少浪费的候选分工或流程。',
    '',
    '报告必须按“现象 → 影响 → Trace/span/run 证据 → 可能根因 → 置信度/未知边界 → 候选修复 → 如何用沙盒或 Eval 验证 → 可回跳的 Trace/Session/Room/文件”输出。不要把模型推测写成事实。',
  ].join('\n');
}

function repairPrompt(report: TraceAgentReport): string {
  const handoff = {
    target: {
      kind: report.target.kind,
      id: redactTraceAgentText(report.target.id, 180),
      title: redactTraceAgentText(report.target.title, 180),
      status: report.target.status,
      handoff: report.target.handoff,
    },
    diagnosticSessionId: redactTraceAgentText(report.sessionId, 180),
    diagnosticReportRef: `agent-session:${redactTraceAgentText(report.sessionId, 180)}`,
    traceId: report.traceId ? redactTraceAgentText(report.traceId, 180) : null,
    // Roots from a URL handoff are deliberately not trusted or echoed into
    // the repair prompt.  A canonical catalog target gets its authoritative
    // binding from the backend and may retain it for the per-action Session.
    workspaceRoots: report.target.handoff ? [] : report.target.workspaceRoots,
    failedEvidence: report.evidence.map((item) => ({
      id: redactTraceAgentText(item.id, 180),
      source: redactTraceAgentText(item.source, 240),
      status: item.status,
      title: redactTraceAgentText(item.title, 180),
      summary: redactTraceAgentError(item.summary) || redactTraceAgentText(item.summary, 640),
      traceId: item.traceId ? redactTraceAgentText(item.traceId, 180) : null,
      createdAtMs: item.createdAtMs,
    })),
  };
  return [
    '这是 Trace Agent 的候选修复交接。你是普通可写 Agent，请先复核证据和诊断 Session，再向用户说明准备修改什么。',
    '不要静默修改：真实写入、命令或配置变更必须继续走当前 Session 的普通 per_action 授权；证据不足时报告未知并先询问，不要猜测。',
    '请优先定位根因，给出最小修复；完成后运行与问题直接相关的最小验证，并回报修改文件、授权动作、验证结果以及如何回到 Trace 重跑诊断。',
    '',
    '--- TRACE_DIAGNOSTIC_HANDOFF ---',
    JSON.stringify(handoff, null, 2),
    '--- END TRACE_DIAGNOSTIC_HANDOFF ---',
  ].join('\n');
}

function openDiagnosticSession(desktop: ReturnType<typeof usePawOsDesktop>, sessionId: string): void {
  openPawOsRoute(desktop, `/agent?session=${encodeURIComponent(sessionId)}`);
}

function openOriginal(desktop: ReturnType<typeof usePawOsDesktop>, target: TraceTarget): void {
  if (target.handoff?.sourceRoute) {
    openPawOsRoute(desktop, target.handoff.sourceRoute);
    return;
  }
  openPawOsRoute(desktop, target.kind === 'room'
    ? `/rooms?room=${encodeURIComponent(target.id)}`
    : target.kind === 'run'
      ? `/observability?runId=${encodeURIComponent(target.id)}`
      : `/agent?session=${encodeURIComponent(target.id)}`);
}

function openTrace(desktop: ReturnType<typeof usePawOsDesktop>, traceId: string): void {
  openPawOsRoute(desktop, `/observability?traceId=${encodeURIComponent(traceId)}`);
}

function openFiles(desktop: ReturnType<typeof usePawOsDesktop>, sessionId: string): void {
  openPawOsRoute(desktop, `/files?session=${encodeURIComponent(sessionId)}`);
}

function statusLabel(value: string): string {
  return ({ active: '进行中', running: '运行中', idle: '已结束', completed: '已完成', archived: '已归档', failed: '失败', stopped: '已停止' } as Record<string, string>)[value] ?? value;
}

function statusTone(value: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (['active', 'running'].includes(value)) return 'info';
  if (['failed', 'stopped'].includes(value)) return 'danger';
  if (['completed', 'idle'].includes(value)) return 'success';
  return 'neutral';
}

function formatTime(value: number): string {
  return value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '暂无时间';
}

export { TRACE_AGENT_SKILL_REF };
