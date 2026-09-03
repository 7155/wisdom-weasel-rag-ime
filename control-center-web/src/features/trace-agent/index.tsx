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
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
} from '@/components/primitives';
import type { EvalRunV1 } from '@/contracts/generated/eval-run.v1';
import type { TraceRepairReceiptV1 } from '@/contracts/generated/trace-repair-receipt.v1';
import type { ObservationSnapshotV1 } from '@/contracts/generated/observation-snapshot.v1';
import type { AgentRoomSnapshotV1 } from '@/contracts/generated/agent-room-snapshot.v1';
import type { ObservabilityEvalListV1 } from '@/contracts/generated/observability-eval-list.v1';
import type { ObservabilityTraceGetV1 } from '@/contracts/generated/observability-trace-get.v1';
import type { TraceDiagnosticReportListV1 } from '@/contracts/generated/trace-diagnostic-report-list.v1';
import type { TraceDiagnosticReportV1 } from '@/contracts/generated/trace-diagnostic-report.v1';
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
import { TraceFailureReasonPanel } from './failure-reasons';
import {
  parseTraceRepairEvidenceWrite,
  parseTraceRepairReceiptCreate,
  parseTraceRepairRecheck,
  parseTraceRepairReceiptGet,
  TraceRepairValidationError,
  type TraceRepairIdentity,
} from './trace-repair';
import {
  TRACE_AGENT_MAX_TARGETS,
  traceTargetColorToken,
  traceTargetKey,
  toggleTraceTargetSelection,
  type TraceTargetKind,
} from './trace-agent-model';
import { TraceDiagnosticReportDocument } from './report-document';
import './engineering-audit-report.css';
import './trace-agent.css';

const TRACE_AGENT_SKILL_REF = 'integrations/pi/skills/trace-agent-diagnostics/SKILL.md';
const TRACE_DIAGNOSTIC_TITLE_PREFIX = 'Trace 诊断 · ';
const TRACE_TIMELINE_PAGE_SIZE = 60;
const TRACE_AGENT_DIAGNOSTIC_POLL_INTERVAL_MS = 1_500;
export const TRACE_AGENT_DIAGNOSTIC_MAX_POLL_DURATION_MS = 60_000;
const TRACE_AGENT_OWNER_APP_ID = 'extension:trace-agent';
export const TRACE_DIAGNOSTIC_SESSION_POLICY = {
  mode: 'coordinator',
  toolProfileVersion: 'control-center-auto-approve-v1',
  executionMode: 'full_trust',
  dangerousModeConfirmation: 'ENABLE_FULL_TRUST',
  workspaceRoots: ['/'] as string[],
  toolAllowlistMode: 'profile',
  projectContextEnabled: true,
  piSkillsEnabled: true,
  codexSkillsEnabled: true,
} as const;


type TraceTarget = {
  kind: TraceTargetKind;
  id: string;
  targetKey: string;
  title: string;
  status: string;
  updatedAtMs: number;
  detail: string;
  workspaceRoots: string[];
  sourceSessionId?: string;
  workspaceBindingState?: 'ready' | 'unbound' | 'conflict';
  handoffOnly?: boolean;
  handoff?: TraceAgentHandoff;
};

type TraceAgentReport = {
  sessionId: string;
  reportId: string;
  targets: TraceTarget[];
  primaryTarget: TraceTarget;
  /** @deprecated kept for existing repair/recheck identity code during migration. */
  target: TraceTarget;
  traceId: string;
  traceIds: string[];
  promptAccepted: boolean;
  evidence: TraceEvidenceItem[];
};

type TraceRepairHandoff = {
  sessionId: string;
  promptAccepted: boolean;
  findingId: string;
  identity: TraceRepairIdentity;
};

type TraceRepairReceipt = TraceRepairReceiptV1;

type TraceEvalReceipt = {
  sourceTraceId: string;
  repairTraceId: string;
  repairReceipt: TraceRepairReceipt;
  evalRun: EvalRunV1;
};

type TraceTargetCatalog = {
  sessions: TraceTarget[];
  rooms: TraceTarget[];
  runs: TraceTarget[];
  hasMore: Record<TraceTargetKind, boolean>;
};

export function TraceAgentFeature() {
  const [searchParams] = useSearchParams();
  const reportId = searchParams.get('reportId')?.trim() ?? '';
  return reportId ? <TraceDiagnosticReportPage reportId={reportId} /> : <TraceAgentWorkbench />;
}

type TraceDiagnosticReportSummary = TraceDiagnosticReportListV1['items'][number];

function useTraceDiagnosticReports(transport: ReturnType<typeof useControlTransport>) {
  return useQuery<TraceDiagnosticReportListV1>({
    queryKey: ['trace-agent', 'diagnostic-reports'],
    queryFn: ({ signal }) => transport.request<TraceDiagnosticReportListV1>({
      pathId: 'observability.traceDiagnosticReports.list',
      query: { limit: 100 },
      responseContract: 'trace-diagnostic-report-list.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

function useTraceDiagnosticReport(
  transport: ReturnType<typeof useControlTransport>,
  reportId: string,
  enabled = true,
) {
  return useQuery<TraceDiagnosticReportV1>({
    queryKey: ['trace-agent', 'diagnostic-report', reportId],
    enabled: Boolean(reportId) && enabled,
    queryFn: ({ signal }) => transport.request<TraceDiagnosticReportV1>({
      pathId: 'observability.traceDiagnosticReport.get',
      params: { reportId },
      responseContract: 'trace-diagnostic-report.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => query.state.data?.status === 'generating' ? TRACE_AGENT_DIAGNOSTIC_POLL_INTERVAL_MS : false,
  });
}

function TraceDiagnosticReportPage({ reportId }: { reportId: string }) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const report = useTraceDiagnosticReport(transport, reportId);
  return (
    <ManagementPage
      actions={(
        <Button leadingIcon={<RefreshCw size={15} />} loading={report.isFetching} onClick={() => void report.refetch()} size="small">
          刷新报告
        </Button>
      )}
      description="这是独立持久化的 Trace 诊断报告；原始 Agent 对话只作为可回溯的过程证据。"
      routeId="trace-agent"
      title="Trace 诊断报告"
    >
      <QueryState error={report.error} isPending={report.isPending} onRetry={() => void report.refetch()}>
        {report.data ? (
          <TraceDiagnosticReportDocument
            onOpenDiagnosticSession={() => openDiagnosticSession(desktop, report.data.diagnosticSessionId)}
            onOpenTarget={(target) => openReportTarget(desktop, target)}
            onOpenTrace={(traceId) => openTrace(desktop, traceId)}
            report={report.data}
          />
        ) : null}
      </QueryState>
    </ManagementPage>
  );
}

function TraceAgentWorkbench() {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const [searchParams] = useSearchParams();
  const incomingHandoff = useMemo(
    () => parseTraceAgentHandoff(searchParams),
    [searchParams],
  );
  const queryClient = useQueryClient();
  const incomingTarget = useMemo(
    () => incomingHandoff ? traceTargetFromHandoff(incomingHandoff) : null,
    [incomingHandoff],
  );
  const targets = useTraceTargets(transport);
  const [kind, setKind] = useState<TraceTargetKind>(incomingTarget?.kind ?? 'session');
  const [selectedKeys, setSelectedKeys] = useState<string[]>(() => (
    incomingTarget ? [incomingTarget.targetKey] : []
  ));
  const [focusedKey, setFocusedKey] = useState(incomingTarget?.targetKey ?? '');
  const [report, setReport] = useState<TraceAgentReport | null>(null);
  const [repairHandoff, setRepairHandoff] = useState<TraceRepairHandoff | null>(null);
  const [evalReceipt, setEvalReceipt] = useState<TraceEvalReceipt | null>(null);
  const [diagnosticPollingExpired, setDiagnosticPollingExpired] = useState(false);
  const [diagnosticPollingGeneration, setDiagnosticPollingGeneration] = useState(0);
  const catalogItems = kind === 'session'
    ? targets.data?.sessions ?? []
    : kind === 'room'
      ? targets.data?.rooms ?? []
      : targets.data?.runs ?? [];
  const resolvedIncomingTarget = useMemo(
    () => resolveIncomingTraceTarget(
      incomingTarget,
      [
        ...(targets.data?.sessions ?? []),
        ...(targets.data?.rooms ?? []),
        ...(targets.data?.runs ?? []),
      ],
    ),
    [incomingTarget, targets.data?.rooms, targets.data?.runs, targets.data?.sessions],
  );
  const items = resolvedIncomingTarget?.kind === kind
    ? [resolvedIncomingTarget, ...catalogItems.filter((item) => item.id !== resolvedIncomingTarget.id)]
    : catalogItems;
  const visibleItems = items.filter((item) => !isTraceDiagnosticSession(item));
  const catalogTargets = useMemo(() => uniqueTargets([
    ...(resolvedIncomingTarget ? [resolvedIncomingTarget] : []),
    ...(targets.data?.sessions ?? []),
    ...(targets.data?.rooms ?? []),
    ...(targets.data?.runs ?? []),
  ].filter((item) => !isTraceDiagnosticSession(item))), [resolvedIncomingTarget, targets.data?.rooms, targets.data?.runs, targets.data?.sessions]);
  const targetByKey = useMemo(
    () => new Map(catalogTargets.map((item) => [item.targetKey, item])),
    [catalogTargets],
  );
  const selected = visibleItems.find((item) => item.targetKey === focusedKey) ?? null;
  const selectedTargets = useMemo(
    () => selectedKeys.map((key) => targetByKey.get(key)).filter((item): item is TraceTarget => Boolean(item)).slice(0, TRACE_AGENT_MAX_TARGETS),
    [selectedKeys, targetByKey],
  );
  const toggleSelectedTarget = (item: TraceTarget) => {
    setFocusedKey(item.targetKey);
    setSelectedKeys((current) => {
      const wasSelected = current.includes(item.targetKey);
      const next = toggleTraceTargetSelection(current, item.targetKey);
      // A URL handoff is an ephemeral default. When the user deliberately
      // picks a canonical catalog object, replace that default instead of
      // silently submitting both the stale handoff and the new target. The
      // handoff remains available in the list and can be added back explicitly
      // for a comparison run.
      if (!wasSelected && incomingTarget?.handoff && item.targetKey !== incomingTarget.targetKey) {
        return next.filter((key) => key !== incomingTarget.targetKey);
      }
      return next;
    });
  };
  const visibleItemIdentity = visibleItems.map((item) => item.targetKey).join('|');
  const catalogTargetIdentity = catalogTargets.map((item) => item.targetKey).join('|');
  const persistedReportsQuery = useTraceDiagnosticReports(transport);
  const persistedReports = persistedReportsQuery.data?.items ?? [];
  const diagnosedByTargetKey = useMemo(() => {
    const result = new Map<string, TraceDiagnosticReportSummary>();
    for (const reportSummary of persistedReports) {
      for (const target of reportSummary.targets) {
        if (!result.has(target.targetKey)) result.set(target.targetKey, reportSummary);
      }
    }
    return result;
  }, [persistedReports]);
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
  const runHistory = useRunObservationHistory(
    selected?.kind === 'run' ? selected.id : '',
    snapshot.data,
  );
  const latestTraceId = useMemo(
    () => selected?.handoff?.traceId || latestTrace(snapshot.data),
    [selected, snapshot.data],
  );
  const evalTraceId = evalReceipt?.repairTraceId ?? '';
  const diagnosticSession = useQuery({
    queryKey: ['trace-agent', 'diagnostic-session', report?.sessionId ?? ''],
    enabled: Boolean(report?.sessionId),
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.session.snapshot',
      params: { sessionId: report?.sessionId ?? '' },
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (diagnosticPollingExpired || query.state.error || diagnosticSessionTerminalFailure(data)) return false;
      return diagnosticReportReady(data) && diagnosticSessionTerminal(data)
        ? false
        : TRACE_AGENT_DIAGNOSTIC_POLL_INTERVAL_MS;
    },
  });
  const persistedReport = useTraceDiagnosticReport(
    transport,
    report?.reportId ?? '',
    Boolean(report?.reportId),
  );
  const finalizedReportRef = useRef<string | null>(null);
  const finalizeReport = useMutation({
    mutationFn: async ({ reportId, expectedRevision }: { reportId: string; expectedRevision: number }) => transport.request<TraceDiagnosticReportV1>({
      pathId: 'observability.traceDiagnosticReport.finalize',
      params: { reportId },
      body: { expectedRevision },
      responseContract: 'trace-diagnostic-report.v1',
    }),
    onSuccess: (next) => {
      queryClient.setQueryData(['trace-agent', 'diagnostic-report', next.reportId], next);
      void persistedReportsQuery.refetch();
      if (report && next.reportId === report.reportId) setReport((current) => current ? { ...current, traceIds: next.traceIds, traceId: next.traceIds[0] || current.traceId } : current);
    },
  });
  useEffect(() => {
    if (!report || finalizedReportRef.current === report.reportId || !persistedReport.data || persistedReport.data.status !== 'generating' || finalizeReport.isPending) return;
    if (!report.promptAccepted) return;
    const structuredResultReady = diagnosticStructuredResultReady(diagnosticSession.data);
    const terminalFailure = diagnosticSessionTerminalFailure(diagnosticSession.data);
    const terminal = diagnosticSessionTerminal(diagnosticSession.data);
    const terminalAfterTimeout = diagnosticPollingExpired && terminal;
    if (!(structuredResultReady && terminal) && !terminalFailure && !terminalAfterTimeout) return;
    finalizedReportRef.current = report.reportId;
    finalizeReport.mutate({ reportId: report.reportId, expectedRevision: persistedReport.data.revision });
  }, [diagnosticPollingExpired, diagnosticSession.data, finalizeReport.isPending, persistedReport.data, report]);
  const runTrace = useQuery<ObservabilityTraceGetV1>({
    queryKey: ['trace-agent', 'run-trace', selected?.id ?? '', latestTraceId],
    enabled: selected?.kind === 'run' && Boolean(latestTraceId),
    queryFn: ({ signal }) => transport.request<ObservabilityTraceGetV1>({
      pathId: 'observability.trace.get',
      params: { traceId: latestTraceId },
      responseContract: 'observability-trace-get.v1',
      signal,
    }),
    retry: false,
    refetchOnWindowFocus: false,
  });
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
    () => sourceEvidence(selected?.kind === 'run' ? runHistory.source : snapshot.data, sourceSnapshot.data),
    [runHistory.source, selected?.kind, snapshot.data, sourceSnapshot.data],
  );
  const runBinding = useMemo(
    () => {
      if (selected?.kind !== 'run') return null;
      let bindingState: RunSourceBindingState = 'ready';
      if (!latestTraceId) bindingState = 'unavailable';
      else if (runTrace.isPending) bindingState = 'pending';
      else if (runTrace.error || !runTrace.data) bindingState = 'error';
      return runSourceBinding(runHistory.source, selected.id, runTrace.data, bindingState);
    },
    [latestTraceId, runHistory.source, runTrace.data, runTrace.error, runTrace.isPending, selected],
  );
  const start = useMutation({
    mutationFn: async (diagnosticTargets: TraceTarget[]) => {
      if (!diagnosticTargets.length) throw new Error('至少选择一个诊断对象。');
      if (diagnosticTargets.length > TRACE_AGENT_MAX_TARGETS) throw new Error(`最多选择 ${TRACE_AGENT_MAX_TARGETS} 个诊断对象。`);
      const primaryTarget = diagnosticTargets[0];
      const reportTitle = diagnosticTargets.length === 1
        ? `Trace 诊断 · ${primaryTarget.title}`
        : `Trace 诊断 · ${primaryTarget.title} 等 ${diagnosticTargets.length} 个对象`;
      const created = await transport.request({
        pathId: 'agent.sessions.create',
        body: {
          _modelRoute: 'traceDiagnostic',
          surfaceKind: 'extension_app',
          ownerAppId: TRACE_AGENT_OWNER_APP_ID,
          surfaceKey: 'diagnostic',
          title: reportTitle,
          ...TRACE_DIAGNOSTIC_SESSION_POLICY,
        },
      });
      const sessionId = createdSessionId(created);
      if (!sessionId) throw new Error('诊断 Session 创建失败。');
      // Carry the same explicit full-trust policy through the normal Session
      // update seam before the first turn, so transcript and workspace reads
      // use the profile-authorized scope rather than a UI-only label.
      await transport.request({
        pathId: 'agent.session.mode.update',
        params: { sessionId },
        body: { ...TRACE_DIAGNOSTIC_SESSION_POLICY },
      });
      const persistedReport = await transport.request<TraceDiagnosticReportV1>({
        pathId: 'observability.traceDiagnosticReports.create',
        body: {
          diagnosticSessionId: sessionId,
          title: reportTitle,
          targets: diagnosticTargets.map((target) => ({
            kind: target.kind,
            id: target.id,
            title: target.title,
            traceIds: target.handoff?.traceId ? [target.handoff.traceId] : [],
          })),
        },
        responseContract: 'trace-diagnostic-report.v1',
      });
      await transport.request({
        pathId: 'agent.session.prompt',
        params: { sessionId },
        body: {
          message: diagnosticPrompt(diagnosticTargets, latestTraceId, persistedReport.reportId),
          clientMessageId: `trace-agent:${sessionId}:${Date.now()}`,
          delivery: 'prompt',
        },
      });
      return {
        sessionId,
        reportId: persistedReport.reportId,
        targets: diagnosticTargets,
        primaryTarget,
        target: primaryTarget,
        traceId: primaryTarget.handoff?.traceId || latestTraceId,
        traceIds: diagnosticTargets.flatMap((target) => target.handoff?.traceId ? [target.handoff.traceId] : []),
        promptAccepted: true,
        evidence,
      } satisfies TraceAgentReport;
    },
    onSuccess: (next) => {
      setRepairHandoff(null);
      setEvalReceipt(null);
      setReport(next);
      void persistedReportsQuery.refetch();
    },
  });
  const repair = useMutation({
    mutationFn: async (diagnostic: TraceAgentReport) => {
      if (!diagnosticReportReady(diagnosticSession.data)) {
        throw new Error('结构化诊断报告尚未完成，暂不能交给 Agent 修复。');
      }
      const reportAuthority = await transport.request<TraceDiagnosticReportV1>({
        pathId: 'observability.traceDiagnosticReport.get',
        params: { reportId: diagnostic.reportId },
        responseContract: 'trace-diagnostic-report.v1',
      });
      if (reportAuthority.status !== 'completed') throw new Error('持久化诊断报告尚未完成，暂不能授权修复交接。');

      const existingAuthorization = reportAuthority.repairLifecycle?.authorization;
      let repairContext: {
        sessionId: string;
        findingId: string;
        identity: TraceRepairIdentity;
      };
      if (existingAuthorization?.state === 'authorized') {
        repairContext = {
          sessionId: existingAuthorization.repairSessionId,
          findingId: existingAuthorization.findingId,
          identity: {
            sourceScope: existingAuthorization.sourceScope,
            sourceTraceId: existingAuthorization.sourceTraceId,
            failureRef: existingAuthorization.failureRef,
          },
        };
      } else {
        const rawFindings = asRecord(reportAuthority.result).findings;
        const structuredFindings = Array.isArray(rawFindings) ? rawFindings.map(asRecord) : [];
        const finding = structuredFindings.find((item) => ['critical', 'high'].includes(stringValue(item.severity)))
          ?? structuredFindings[0];
        const findingId = stringValue(finding?.findingId);
        const sourceScope = diagnostic.primaryTarget.targetKey;
        const authorityTarget = reportAuthority.targets.find((target) => target.targetKey === sourceScope);
        const targetTraceIds = authorityTarget?.traceIds ?? [];
        const sourceTraceId = targetTraceIds.includes(diagnostic.traceId)
          ? diagnostic.traceId
          : targetTraceIds[0] ?? '';
        const rawFindingEvidenceIds = finding?.evidenceIds;
        const failureRef = (Array.isArray(rawFindingEvidenceIds)
          ? rawFindingEvidenceIds.map((item) => stringValue(item)).find(Boolean)
          : '') || findingId;
        if (!findingId || !sourceTraceId || !failureRef) {
          throw new Error('诊断报告没有可绑定到修复目标的 Finding、失败证据或 source Trace。');
        }
        const identity = { sourceScope, sourceTraceId, failureRef } satisfies TraceRepairIdentity;
        const created = await transport.request({
          pathId: 'agent.sessions.create',
          body: {
            title: `修复 Trace 诊断 · ${diagnostic.target.title}`,
            surfaceKind: 'extension_app',
            ownerAppId: TRACE_AGENT_OWNER_APP_ID,
            surfaceKey: 'repair',
            ...TRACE_DIAGNOSTIC_SESSION_POLICY,
          },
        });
        const sessionId = createdSessionId(created);
        if (!sessionId) throw new Error('修复 Agent Session 创建失败。');
        await transport.request({
          pathId: 'agent.session.mode.update',
          params: { sessionId },
          body: { ...TRACE_DIAGNOSTIC_SESSION_POLICY },
        });
        const linkedReport = await transport.request<TraceDiagnosticReportV1>({
          pathId: 'observability.traceDiagnosticReport.repairAuthorize',
          params: { reportId: diagnostic.reportId },
          body: {
            expectedRevision: reportAuthority.revision,
            findingId,
            sourceScope,
            sourceTraceId,
            failureRef,
            repairSessionId: sessionId,
          },
          responseContract: 'trace-diagnostic-report.v1',
        });
        queryClient.setQueryData(['trace-agent', 'diagnostic-report', linkedReport.reportId], linkedReport);
        repairContext = { sessionId, findingId, identity };
      }

      let promptAccepted = false;
      try {
        await transport.request({
          pathId: 'agent.session.prompt',
          params: { sessionId: repairContext.sessionId },
          body: {
            message: repairPrompt(diagnostic, repairContext.identity),
            clientMessageId: `trace-agent-repair:${repairContext.sessionId}:${diagnostic.reportId}`,
            delivery: 'prompt',
          },
        });
        promptAccepted = true;
      } catch {
        // Authorization is durable and identifies the only repair Session.
        // Keep it recoverable instead of creating a conflicting replacement.
      }
      return { ...repairContext, promptAccepted } satisfies TraceRepairHandoff;
    },
    onSuccess: (next) => {
      setRepairHandoff(next);
      void persistedReportsQuery.refetch();
    },
  });
  useEffect(() => {
    const persisted = persistedReport.data;
    const authorization = persisted?.repairLifecycle?.authorization;
    if (
      !report
      || persisted?.reportId !== report.reportId
      || authorization?.state !== 'authorized'
    ) return;
    setRepairHandoff((current) => {
      if (
        current?.sessionId === authorization.repairSessionId
        && current.findingId === authorization.findingId
      ) return current;
      return {
        sessionId: authorization.repairSessionId,
        promptAccepted: false,
        findingId: authorization.findingId,
        identity: {
          sourceScope: authorization.sourceScope,
          sourceTraceId: authorization.sourceTraceId,
          failureRef: authorization.failureRef,
        },
      };
    });
  }, [persistedReport.data, report]);
  const recheck = useMutation({
    mutationFn: async ({ diagnostic, handoff }: { diagnostic: TraceAgentReport; handoff: TraceRepairHandoff }) => {
      if (!diagnostic.traceId) throw new Error('当前诊断没有可复检的 Trace。');
      const repairSessionId = handoff.sessionId;
      const [repairSnapshot, repairSessionSnapshot] = await Promise.all([
        transport.request<ObservationSnapshotV1>({
          pathId: 'observability.snapshot',
          query: { limit: 100, sessionId: repairSessionId },
          responseContract: 'observation-snapshot.v1',
        }),
        transport.request({
          pathId: 'agent.session.snapshot',
          params: { sessionId: repairSessionId },
        }),
      ]);
      const repairTraceId = terminalRepairTurnTrace(repairSessionSnapshot)
        || latestCompletedTrace(repairSnapshot, repairSessionId);
      if (!repairTraceId) throw new Error('修复 Session 尚未产生已完成 Trace，请先完成修复后再复检。');
      const identity = handoff.identity;
      const repairRefs = { repairSessionId, repairTraceId };
      const changeResponse = await transport.request({
        pathId: 'observability.traceRepair.changeEvidence',
        body: {
          schemaVersion: 'rag-ime.trace-repair-change-evidence.v1',
          ...repairRefs,
        },
      });
      const changeEvidence = parseTraceRepairEvidenceWrite(changeResponse, 'change', repairRefs);
      const testResponse = await transport.request({
        pathId: 'observability.traceRepair.testEvidence',
        body: {
          schemaVersion: 'rag-ime.trace-repair-test-evidence.v1',
          ...repairRefs,
        },
      });
      const testEvidence = parseTraceRepairEvidenceWrite(testResponse, 'test', repairRefs);
      if (testEvidence.testStatus !== 'passed') {
        throw new Error('实际修复 Trace 的测试证据未通过，不能创建权威回执。');
      }
      const receiptResponse = await transport.request({
        pathId: 'observability.traceRepair.receipt.create',
        body: {
          schemaVersion: 'rag-ime.trace-repair-receipt-create.v1',
          sourceScope: identity.sourceScope,
          sourceTraceId: identity.sourceTraceId,
          failureRef: identity.failureRef,
          changeReceiptId: changeEvidence.evidenceId,
          testEvidenceId: testEvidence.evidenceId,
          repairTraceId,
          repairSessionId,
        },
      });
      const repairReceipt = parseTraceRepairReceiptCreate(receiptResponse, identity, {
        changeReceiptId: changeEvidence.evidenceId,
        testEvidenceId: testEvidence.evidenceId,
        repairTraceId,
        repairSessionId,
      });
      // Re-read the immutable server receipt before asking for a recheck. This
      // makes a stale/mutated transport fail closed and makes the final API
      // request opaque-ID-only as required by the backend contract.
      const verifiedReceiptResponse = await transport.request({
        pathId: 'observability.traceRepair.receipt.get',
        params: { repairReceiptId: repairReceipt.repairReceiptId },
      });
      const verifiedReceipt = parseTraceRepairReceiptGet(
        verifiedReceiptResponse,
        identity,
        repairReceipt.repairReceiptId,
      );
      const recheckResponse = await transport.request({
        pathId: 'observability.traceRepair.recheck',
        body: {
          schemaVersion: 'rag-ime.trace-repair-recheck-request.v1',
          repairReceiptId: verifiedReceipt.repairReceiptId,
        },
      });
      const recheckResult = parseTraceRepairRecheck(recheckResponse, identity, verifiedReceipt);
      const currentReport = await transport.request<TraceDiagnosticReportV1>({
        pathId: 'observability.traceDiagnosticReport.get',
        params: { reportId: diagnostic.reportId },
        responseContract: 'trace-diagnostic-report.v1',
      });
      const linkedReport = await transport.request<TraceDiagnosticReportV1>({
        pathId: 'observability.traceDiagnosticReport.repairVerify',
        params: { reportId: diagnostic.reportId },
        body: {
          expectedRevision: currentReport.revision,
          repairReceiptId: verifiedReceipt.repairReceiptId,
        },
        responseContract: 'trace-diagnostic-report.v1',
      });
      queryClient.setQueryData(['trace-agent', 'diagnostic-report', linkedReport.reportId], linkedReport);
      return {
        sourceTraceId: diagnostic.traceId,
        repairTraceId,
        repairReceipt: recheckResult.receipt,
        evalRun: recheckResult.evalRun,
      } satisfies TraceEvalReceipt;
    },
    onSuccess: (next) => {
      setEvalReceipt(next);
      void persistedReportsQuery.refetch();
    },
  });

  useEffect(() => {
    if (!incomingTarget) return;
    setKind(incomingTarget.kind);
    setFocusedKey(incomingTarget.targetKey);
    setSelectedKeys((current) => current.includes(incomingTarget.targetKey)
      ? current
      : [incomingTarget.targetKey, ...current].slice(0, TRACE_AGENT_MAX_TARGETS));
  }, [incomingTarget]);

  useEffect(() => {
    if (visibleItems.length && !visibleItems.some((item) => item.targetKey === focusedKey)) {
      const next = visibleItems[0];
      setFocusedKey(next.targetKey);
    } else if (!visibleItems.length && focusedKey && !targetByKey.has(focusedKey)) {
      setFocusedKey('');
    }
    const availableKeys = new Set(catalogTargets.map((item) => item.targetKey));
    setSelectedKeys((current) => {
      const retained = current.filter((key) => availableKeys.has(key)).slice(0, TRACE_AGENT_MAX_TARGETS);
      // Preserve the old single-target affordance on first load: the focused
      // item is selected by default. Once a selection exists in any tab, do
      // not replace it when the user switches tabs; selections are global to
      // the catalog, not to the currently visible page.
      const next = retained.length || !visibleItems.length
        ? retained
        : [visibleItems[0].targetKey];
      return next.length === current.length && next.every((key, index) => key === current[index]) ? current : next;
    });
  }, [catalogTargetIdentity, catalogTargets, focusedKey, kind, targetByKey, visibleItemIdentity, visibleItems]);

  useEffect(() => {
    setReport(null);
    setRepairHandoff(null);
    setEvalReceipt(null);
    setDiagnosticPollingExpired(false);
    repair.reset();
    recheck.reset();
  }, [kind, selectedKeys.join('|')]);

  useEffect(() => {
    if (!report?.sessionId) {
      setDiagnosticPollingExpired(false);
      return undefined;
    }
    setDiagnosticPollingExpired(false);
    const timeoutId = window.setTimeout(
      () => setDiagnosticPollingExpired(true),
      TRACE_AGENT_DIAGNOSTIC_MAX_POLL_DURATION_MS,
    );
    return () => window.clearTimeout(timeoutId);
  }, [diagnosticPollingGeneration, report?.sessionId]);

  const refresh = () => {
    void targets.refetch();
    if (selected && !selected.handoffOnly) void snapshot.refetch();
    if (selected && selected.kind !== 'run') void sourceSnapshot.refetch();
    if (selected?.kind === 'run' && latestTraceId) void runTrace.refetch();
    if (report?.sessionId) {
      setDiagnosticPollingExpired(false);
      setDiagnosticPollingGeneration((current) => current + 1);
      void diagnosticSession.refetch();
    }
  };
  const error = targets.error as Error | null;

  return (
    <ManagementPage
      actions={(
        <Button
          leadingIcon={<RefreshCw size={15} />}
          loading={targets.isFetching || snapshot.isFetching || sourceSnapshot.isFetching || runTrace.isFetching || diagnosticSession.isFetching}
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
              <p>诊断 Session 使用全信任运行，加载专用 Skill，可读取原始对话与根目录 / 下文件，并在证据充分时执行最小、可验证的项目修改。</p>
            </div>
            <StatusBadge label="全信任诊断" tone="warning" />
          </header>

          <ManagementSection
            title="选择诊断输入"
            description="可选当前或历史对象。选择 Room 时会把主持 Session、全部行星、子 Agent、WorkItem、公开流转和相关 Trace 一起交给诊断 Agent。"
            trailing={<StatusBadge label={`${visibleItems.length} 个${kind === 'session' ? ' Session' : kind === 'room' ? ' Room' : '运行'} · 已选 ${selectedTargets.length}/${TRACE_AGENT_MAX_TARGETS}`} tone="neutral" />}
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
                    <strong>已保存的工程审计报告</strong>
                    <p>报告正文、八维评分和证据引用独立持久化；诊断 Agent 对话保留完整过程与必要修改记录，报告只呈现已持久化证据。</p>
                  </div>
                  <StatusBadge label={`${persistedReports.length} 份`} tone="neutral" />
                </div>
                <div className="trace-agent-persisted-reports__list" role="list">
                  {persistedReports.map((item) => (
                    <div className="trace-agent-persisted-report" data-status={item.status} key={item.reportId} role="listitem">
                      <div
                        className="trace-agent-persisted-report__icon"
                        aria-hidden="true"
                        style={{ borderColor: item.targets[0] ? traceTargetColorToken(item.targets[0].targetKey) : undefined }}
                      >
                        {item.status === 'failed' ? <TriangleAlert size={15} /> : <CheckCircle2 size={15} />}
                      </div>
                      <div className="trace-agent-persisted-report__copy">
                        <strong>{item.title}</strong>
                        <div className="trace-agent-persisted-report__targets" aria-label="已诊断对象">
                          {item.targets.map((target) => (
                            <span key={target.targetKey} style={{ borderColor: traceTargetColorToken(target.targetKey) }}>
                              {target.title || target.id}
                            </span>
                          ))}
                        </div>
                        <small>Revision {item.revision} · {reportStatusLabel(item.status)} · 修复：{reportRepairStateLabel(item.repairState)} · {formatTime(item.updatedAtMs)}{item.failureReason || item.status === 'failed' ? ` · 失败原因：${item.failureReason || '未知'}` : ''}</small>
                      </div>
                      <Button
                        leadingIcon={<ArrowUpRight size={14} />}
                        onClick={() => openDiagnosticReport(desktop, item.reportId)}
                        size="small"
                        variant="quiet"
                      >
                        打开审计报告
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
                  <strong>诊断已选的 {selectedTargets.length} 个对象</strong>
                  <span>{selected.handoffOnly ? '仅依据结构化交接包 · 不伪造 Session / Room / Run 快照' : selected.kind === 'room' ? '当前 Room 会带入全部行星、WorkItems 和公开流转；当前焦点只负责预览' : selected.kind === 'run' ? '当前运行及关联 Trace 负责预览；启动时会提交所有勾选对象' : '当前焦点用于预览；启动时会把所有勾选对象作为一个冻结诊断范围'}</span>
                </div>
                <Button
                  aria-label={report ? '诊断已启动' : '开始诊断'}
                  disabled={start.isPending || Boolean(report) || selectedTargets.length === 0}
                  leadingIcon={start.isPending ? <LoaderCircle className="ui-spin" size={15} /> : <Sparkles size={15} />}
                  onClick={() => start.mutate(selectedTargets)}
                >
                  {report ? '诊断已启动' : start.isPending ? '正在启动诊断' : `开始诊断 · ${selectedTargets.length}`}
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
            {visibleItems.length ? (
              <>
                <div aria-label="可诊断对象" className="trace-agent-target-list" role="list">
                  {visibleItems.map((item) => {
                    const diagnosedReport = diagnosedByTargetKey.get(item.targetKey);
                    return (
                      <div
                      aria-label={item.title}
                      aria-current={item.targetKey === focusedKey ? 'true' : undefined}
                      className="trace-agent-target"
                      data-active={item.targetKey === focusedKey}
                      data-diagnosed={diagnosedReport ? 'true' : 'false'}
                      data-selected={selectedKeys.includes(item.targetKey)}
                      data-target-key={item.targetKey}
                      key={item.targetKey}
                      onClick={(event) => {
                        if ((event.target as HTMLElement).closest('input,button')) return;
                        toggleSelectedTarget(item);
                      }}
                      onKeyDown={(event) => {
                        if (event.key !== 'Enter' && event.key !== ' ') return;
                        event.preventDefault();
                        toggleSelectedTarget(item);
                      }}
                      role="listitem"
                      tabIndex={0}
                      style={diagnosedReport ? { borderLeftColor: traceTargetColorToken(item.targetKey) } : undefined}
                    >
                      <input
                        aria-label={`选择 ${item.title}`}
                        checked={selectedKeys.includes(item.targetKey)}
                        disabled={!selectedKeys.includes(item.targetKey) && selectedKeys.length >= TRACE_AGENT_MAX_TARGETS}
                        onChange={() => toggleSelectedTarget(item)}
                        onClick={(event) => event.stopPropagation()}
                        type="checkbox"
                      />
                      <span className="trace-agent-target__icon" aria-hidden="true">
                        {item.kind === 'session' ? <MessageSquareText size={16} /> : item.kind === 'room' ? <Network size={16} /> : <Activity size={16} />}
                      </span>
                      <span className="trace-agent-target__copy">
                        <strong>{item.title}</strong>
                        <small>{item.detail}</small>
                      </span>
                      <span className="trace-agent-target__meta">
                        <StatusBadge label={statusLabel(item.status)} tone={statusTone(item.status)} />
                        {diagnosedReport ? (
                          <span className="trace-agent-target__diagnostic-status" data-status={diagnosedReport.status}>
                            已诊断 · {reportStatusLabel(diagnosedReport.status)}
                          </span>
                        ) : null}
                        <small>{formatTime(item.updatedAtMs)}</small>
                        {diagnosedReport ? (
                          <Button
                            leadingIcon={<ArrowUpRight size={12} />}
                            onClick={(event) => {
                              event.stopPropagation();
                              openDiagnosticReport(desktop, diagnosedReport.reportId);
                            }}
                            size="small"
                            variant="quiet"
                          >
                            打开报告
                          </Button>
                        ) : null}
                      </span>
                      </div>
                    );
                  })}
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
                {selected.kind === 'run' && runBinding?.sessionId ? (
                  <Button
                    leadingIcon={<MessageSquareText size={14} />}
                    onClick={() => openPawOsRoute(desktop, `/agent?session=${encodeURIComponent(runBinding.sessionId)}`)}
                    size="small"
                    variant="quiet"
                  >
                    打开关联 Session
                  </Button>
                ) : null}
                {selected.kind === 'run' && runBinding?.roomId ? (
                  <Button
                    leadingIcon={<Network size={14} />}
                    onClick={() => openPawOsRoute(desktop, `/rooms?room=${encodeURIComponent(runBinding.roomId)}`)}
                    size="small"
                    variant="quiet"
                  >
                    打开关联 Room
                  </Button>
                ) : null}
                {selected.kind === 'run' && runBinding?.pending ? (
                  <span aria-live="polite" className="trace-agent-inline-note" role="status">正在验证关联 Session / Room…</span>
                ) : null}
                {selected.kind === 'run' && runBinding?.unavailable ? (
                  <span aria-live="polite" className="trace-agent-inline-note" role="status">无法验证关联 Session / Room，未显示不可靠的回跳。</span>
                ) : null}
              </div>
              {selected.kind !== 'run' ? (
                <TraceSourceTimeline
                  kind={selected.kind}
                  roomId={selected.kind === 'room' ? selected.id : ''}
                  loading={sourceSnapshot.isFetching}
                  source={sourceSnapshot.data}
                />
              ) : (
                <TraceRunTimeline history={runHistory} loading={snapshot.isFetching} runId={selected.id} />
              )}
              {selected.kind === 'run' && runBinding?.conflict ? (
                <p aria-live="polite" className="trace-agent-inline-note" role="status">关联绑定存在冲突，未显示不可靠的 Session / Room 回跳。</p>
              ) : null}
              <TraceEvidence desktop={desktop} evidence={evidence} loading={sourceSnapshot.isFetching || snapshot.isFetching || runHistory.loading} />
              <TraceFailureReasonPanel evidence={evidence} loading={sourceSnapshot.isFetching || snapshot.isFetching || runHistory.loading} />
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
              onRecheck={(handoff) => recheck.mutate({ diagnostic: report, handoff })}
              report={report}
              onRefreshDiagnostic={() => {
                setDiagnosticPollingExpired(false);
                setDiagnosticPollingGeneration((current) => current + 1);
                void diagnosticSession.refetch();
              }}
              diagnosticSession={{
                error: diagnosticSession.error,
                isFetching: diagnosticSession.isFetching,
                source: diagnosticSession.data,
                timedOut: diagnosticPollingExpired,
              }}
              persistedReport={persistedReport.data}
              finalizeError={finalizeReport.error}
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
  onRefreshDiagnostic,
  diagnosticSession,
  persistedReport,
  finalizeError,
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
  onRefreshDiagnostic: () => void;
  diagnosticSession: { error: unknown; isFetching: boolean; source: unknown; timedOut: boolean };
  persistedReport?: TraceDiagnosticReportV1;
  finalizeError: unknown;
}) {
  const [repairConfirmationOpen, setRepairConfirmationOpen] = useState(false);
  const persistedEval = evalReceipt?.evalRun ?? evalList?.items.find((item) => (
    item.mode === 'ai_judge'
    && item.metricAuthority === 'ai_judge_estimate'
    && item.evaluatorDisplayName === 'Trace recheck'
  )) ?? null;
  const sourceTraceId = evalReceipt?.sourceTraceId ?? report.traceId;
  const repairTraceId = evalReceipt?.repairTraceId ?? evalList?.traceId ?? '';
  const diagnosticReady = persistedReport?.status === 'completed';
  const diagnosticFailed = persistedReport?.status === 'failed';
  const diagnosticTimedOut = diagnosticSession.timedOut && !diagnosticReady && !diagnosticSession.error;
  const handleRepairClick = () => {
    setRepairConfirmationOpen(true);
  };
  return (
    <section aria-label="Trace 诊断报告" className="trace-agent-result trace-agent-result--success">
      <div className="trace-agent-result__icon" aria-hidden="true"><CheckCircle2 size={20} /></div>
      <div className="trace-agent-result__body">
        <div className="trace-agent-result__heading">
          <div><span className="trace-agent-kicker">网页报告</span><h2>{diagnosticReady ? '诊断 Agent 已生成证据报告' : diagnosticFailed ? '诊断失败，已保存失败报告' : diagnosticTimedOut ? '诊断报告读取超时' : '诊断 Session 正在生成证据报告'}</h2></div>
          <StatusBadge
            label={diagnosticSession.error || finalizeError ? '读取失败' : diagnosticReady ? '已完成' : diagnosticFailed ? '诊断失败' : diagnosticTimedOut ? '读取超时' : '生成中'}
            tone={diagnosticSession.error || finalizeError || diagnosticFailed || diagnosticTimedOut ? 'danger' : diagnosticReady ? 'success' : 'info'}
          />
        </div>
        <p>它会先按诊断对象和冻结证据选择主诊断域；无关维度标为不适用，未经重放或 Eval 支持的解释保留为候选/假设。</p>
        <div className="trace-agent-report-links">
          <Button leadingIcon={<ArrowUpRight size={14} />} onClick={() => openDiagnosticSession(desktop, report.sessionId)} size="small">打开诊断 Agent 对话</Button>
          {persistedReport ? <Button leadingIcon={<ArrowUpRight size={14} />} onClick={() => openDiagnosticReport(desktop, persistedReport.reportId)} size="small" variant="primary">打开网页报告</Button> : null}
          <Button
            disabled={diagnosticSession.isFetching}
            leadingIcon={diagnosticSession.isFetching ? <LoaderCircle className="ui-spin" size={14} /> : <RefreshCw size={14} />}
            onClick={onRefreshDiagnostic}
            size="small"
            variant="quiet"
          >
            {diagnosticSession.isFetching ? '正在读取诊断报告' : '重新读取诊断报告'}
          </Button>
          <Button leadingIcon={<ArrowUpRight size={14} />} onClick={() => openOriginal(desktop, report.target)} size="small" variant="quiet">回到原{report.target.kind === 'room' ? ' Room' : report.target.kind === 'run' ? '运行记录' : ' Session'}</Button>
          {report.traceId ? <Button leadingIcon={<Activity size={14} />} onClick={() => openTrace(desktop, report.traceId)} size="small" variant="quiet">查看关联 Trace</Button> : null}
          <Button
            data-testid="trace-agent-repair"
            disabled={!diagnosticReady || repairState.isPending || Boolean(repairHandoff)}
            leadingIcon={repairState.isPending ? <LoaderCircle className="ui-spin" size={14} /> : <Wrench size={14} />}
            onClick={handleRepairClick}
            variant="primary"
          >
            {repairHandoff ? (repairHandoff.promptAccepted ? '修复 Agent 已就绪' : '修复授权已保存') : repairState.isPending ? '正在交接修复' : '交给 Agent 修复'}
          </Button>
          <Button leadingIcon={<RefreshCw size={14} />} onClick={onRerun} size="small" variant="quiet">
            {report.traceId ? '回到 Trace 重跑诊断' : '回到原记录重跑诊断'}
          </Button>
        </div>
        <Dialog open={repairConfirmationOpen && !repairHandoff} onOpenChange={setRepairConfirmationOpen}>
          <DialogContent aria-modal="true" className="trace-agent-repair-confirmation" data-testid="trace-agent-repair-confirmation" hideClose>
            <DialogHeader>
              <DialogTitle>确认启动全信任修复 Session？</DialogTitle>
              <DialogDescription className="trace-agent-repair-confirmation__copy">
                <span>修复目标：{report.primaryTarget.title || report.primaryTarget.id}（{report.primaryTarget.kind} · {report.primaryTarget.id}）；其余 {Math.max(0, report.targets.length - 1)} 个对象只作为比较证据。</span>
                <strong>确认后，修复 Session 可以访问完整磁盘（根目录 /）、使用全部 Tools，并自动批准每一次 Tool 操作，不再逐项询问。</strong>
                <span>PAW 不会用来源工作区、路径、审批或哈希门禁阻拦；macOS TCC、Unix 文件权限等操作系统权限仍是最终边界。</span>
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose asChild><Button size="small" variant="quiet">取消</Button></DialogClose>
              <Button onClick={() => { setRepairConfirmationOpen(false); onRepair(); }} size="small" variant="primary">确认交给 Agent 修复</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <TraceSourceTimeline
          ariaLabel="诊断 Agent 对话与报告"
          description="这里直接读取诊断 Session 的权威时间线；工具过程、报告正文与失败状态都留在同一 Trace 页面。"
          heading="诊断 Agent 对话与报告"
          kicker="实时报告"
          kind="session"
          loading={diagnosticSession.isFetching}
          roomId=""
          source={diagnosticSession.source}
        />
        {diagnosticSession.error ? (
          <p aria-live="polite" className="trace-agent-inline-note" role="alert">
            诊断 Agent 对话暂时无法读取：{publicErrorText(diagnosticSession.error, '请稍后重试或打开诊断 Agent 对话。')}
          </p>
        ) : null}
        {finalizeError ? (
          <p aria-live="polite" className="trace-agent-inline-note" role="alert">
            网页报告持久化失败：{publicErrorText(finalizeError, '结构化诊断结果暂时无法保存。')}
          </p>
        ) : null}
        {diagnosticFailed ? (
          <p aria-live="polite" className="trace-agent-inline-note" role="alert">
            诊断 Session 已终止，但没有形成可校验的结构化结果：{persistedReport?.failureReason || '未知原因'}。失败状态已持久化，不能进入修复流程。
          </p>
        ) : null}
        {diagnosticTimedOut ? (
          <p aria-live="polite" className="trace-agent-inline-note" role="status">
            诊断 Agent 在限定时间内没有产生已完成的助手报告；可以重新读取，或打开诊断 Agent 对话查看当前状态。
          </p>
        ) : null}
        {repairState.error ? (
          <div aria-live="polite" className="trace-agent-repair-state trace-agent-repair-state--error" role="alert">
            <TriangleAlert size={15} />
            <span>{publicErrorText(repairState.error, '修复 Agent 暂时无法启动，请稍后重试。')}</span>
          </div>
        ) : null}
        {repairHandoff ? (
          <div
            aria-live="polite"
            className={`trace-agent-repair-state trace-agent-repair-state--${repairHandoff.promptAccepted ? 'success' : 'error'}`}
            data-testid={repairHandoff.promptAccepted ? 'trace-agent-repair-ready' : 'trace-agent-repair-recovery'}
            role="status"
          >
            {repairHandoff.promptAccepted ? <CheckCircle2 size={15} /> : <TriangleAlert size={15} />}
            <span>
              {repairHandoff.promptAccepted
                ? '已创建全信任修复 Agent Session；它可访问完整磁盘并使用全部 Tools，所有 Tool 操作自动批准。操作系统权限仍是最终边界。完成修改后，复检只读取已持久化、不可变的修复 Trace 中已记录的修改与通过测试证据，由 AI Judge 评审；等待的是这些证据与复检，不是逐项审批；此按钮不重跑命令、不进行同案 Trace 回放、不验证 source SHA，也不执行回滚。'
                : '全信任修复授权和原修复 Session 已持久化，但修复任务尚未确认送达。重新发送会复用同一个授权 Session 和幂等消息标识，不会创建冲突 Session。'}
            </span>
            <Button leadingIcon={<ArrowUpRight size={13} />} onClick={() => openDiagnosticSession(desktop, repairHandoff.sessionId)} size="small">
              打开修复 Session
            </Button>
            {repairHandoff.promptAccepted ? (
              <Button
                disabled={recheckState.isPending || Boolean(persistedEval)}
                leadingIcon={recheckState.isPending ? <LoaderCircle className="ui-spin" size={13} /> : <RefreshCw size={13} />}
                onClick={() => onRecheck(repairHandoff)}
                size="small"
                variant="primary"
              >
                {persistedEval ? '复检已持久化' : recheckState.isPending ? '正在复检修复 Trace 证据' : '复检修复 Trace 证据'}
              </Button>
            ) : (
              <Button
                disabled={repairState.isPending}
                leadingIcon={repairState.isPending ? <LoaderCircle className="ui-spin" size={13} /> : <RefreshCw size={13} />}
                onClick={onRepair}
                size="small"
                variant="primary"
              >
                {repairState.isPending ? '正在重新发送修复任务' : '重新发送修复任务'}
              </Button>
            )}
          </div>
        ) : null}
        {recheckState.error ? (
          <div aria-live="polite" className="trace-agent-repair-state trace-agent-repair-state--error" role="alert">
            <TriangleAlert size={15} />
            <span>{traceRecheckErrorText(recheckState.error)}</span>
          </div>
        ) : null}
        {persistedEval ? (
          <div aria-live="polite" className="trace-agent-repair-state trace-agent-repair-state--success" data-testid="trace-agent-eval-receipt" role="status">
            <CheckCircle2 size={15} />
            <span>
              AI Judge 复检已持久化：{persistedEval.evalRunId} · {evalStatusLabel(persistedEval.status)}
            </span>
            <small>{evalReceipt?.repairReceipt.sandboxStatus === 'not_required' ? '已记录的全信任 Session 终态测试证据：passed（未在 Host 沙盒复跑）' : `已记录的 Host 沙盒测试证据：${evalReceipt?.repairReceipt.sandboxStatus || '未知'} · ${evalReceipt?.repairReceipt.sandboxedTestCount ?? 0} 次`} · 诊断 Trace：{sourceTraceId || '未知'} · 修复 Trace：{repairTraceId || '未知'} · AI Judge 仅评审修复 Trace 中已记录的修改与通过测试证据，不伪装成人工验收；此按钮不重跑命令、不进行同案 Trace 回放、不验证 source SHA，也不执行回滚。</small>
          </div>
        ) : null}
        <dl className="trace-agent-report-meta">
          <div><dt>SkillRef</dt><dd>{TRACE_AGENT_SKILL_REF}</dd></div>
          <div><dt>诊断输入</dt><dd>{report.target.kind} · {report.target.id}</dd></div>
          <div><dt>诊断范围</dt><dd>{report.targets.length} 个对象 · {report.traceIds.length} 条 Trace</dd></div>
          <div><dt>修复 owner</dt><dd>{report.primaryTarget.title || report.primaryTarget.id}（{report.primaryTarget.kind} · {report.primaryTarget.id}）；其余对象仅作比较证据</dd></div>
          <div><dt>权限</dt><dd>Trace 诊断为全信任：可读取原始对话与根目录 / 下文件，并自动批准全部 Tools；操作系统权限是最终边界</dd></div>
        </dl>
      </div>
    </section>
  );
}

function reportStatusLabel(value: string): string {
  return ({ generating: '生成中', completed: '已完成', failed: '失败' } as Record<string, string>)[value] ?? value;
}

function reportRepairStateLabel(value: string | undefined): string {
  return ({
    not_recorded: '待授权',
    authorized: '已授权交接',
    verified: '证据已验证',
    failed: '验证失败',
  } as Record<string, string>)[value ?? 'not_recorded'] ?? '待授权';
}

function openDiagnosticReport(desktop: ReturnType<typeof usePawOsDesktop>, reportId: string): void {
  openPawOsRoute(desktop, `/trace-agent?reportId=${encodeURIComponent(reportId)}`);
}

function openReportTarget(
  desktop: ReturnType<typeof usePawOsDesktop>,
  target: { kind: TraceTargetKind; id: string },
): void {
  openOriginal(desktop, {
    kind: target.kind,
    id: target.id,
    targetKey: traceTargetKey(target.kind, target.id),
    title: target.id,
    status: 'idle',
    updatedAtMs: 0,
    detail: '',
    workspaceRoots: [],
  });
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
  code?: string;
};

type TraceTimelineKind = 'user' | 'assistant' | 'reasoning' | 'tool_started' | 'tool_finished' | 'room_event';

type TraceTimelineEntry = {
  id: string;
  kind: TraceTimelineKind;
  label: string;
  summary: string;
  originalText?: string;
  status?: string;
  sequence: number;
  createdAtMs: number;
};

function TraceSourceTimeline({
  ariaLabel = '原始对话时间线',
  description = '按 timelineSequence / sequence 保留原始顺序；摘要辅助浏览，长消息可展开全文。',
  heading,
  kind,
  kicker = '原始记录',
  loading,
  roomId,
  source,
}: {
  ariaLabel?: string;
  description?: string;
  heading?: string;
  kind: 'session' | 'room';
  kicker?: string;
  loading: boolean;
  roomId: string;
  source: unknown;
}) {
  const roomHistory = useRoomTraceHistory(kind === 'room' ? roomId : '', kind === 'room' ? source : undefined);
  const timelineSource = kind === 'room' ? roomHistory.source : source;
  const entries = useMemo(() => sourceTimeline(kind, timelineSource), [kind, timelineSource]);
  const sourceIdentity = timelineSourceIdentity(kind, roomId, timelineSource);
  const [visibleCount, setVisibleCount] = useState(TRACE_TIMELINE_PAGE_SIZE);
  const [visibleBoundaryId, setVisibleBoundaryId] = useState<string | null>(null);
  const [expandedEntries, setExpandedEntries] = useState<ReadonlySet<string>>(() => new Set());
  useEffect(() => {
    setVisibleCount(TRACE_TIMELINE_PAGE_SIZE);
    setVisibleBoundaryId(null);
    setExpandedEntries(new Set());
  }, [kind, sourceIdentity]);
  useEffect(() => {
    if (!visibleBoundaryId) return;
    const boundaryIndex = entries.findIndex((entry) => entry.id === visibleBoundaryId);
    if (boundaryIndex < 0) return;
    setVisibleCount((current) => Math.max(current, entries.length - boundaryIndex));
  }, [entries, visibleBoundaryId]);
  const visibleEntries = entries.slice(-visibleCount);
  const hiddenCount = entries.length - visibleEntries.length;
  const loadEarlierRoomHistory = async () => {
    const result = await roomHistory.loadEarlier();
    if (result.count > 0) {
      setVisibleBoundaryId(result.boundaryId || null);
      setVisibleCount((current) => Math.min(entries.length + result.count, current + result.count));
    }
  };
  return (
    <section
      aria-label={ariaLabel}
      className="trace-agent-timeline"
      data-scrollable={entries.length ? 'true' : 'false'}
    >
      <div className="trace-agent-timeline__heading">
        <div>
          <span className="trace-agent-kicker">{kicker}</span>
          <h3>{heading ?? (kind === 'room' ? 'Room 对话与行动' : 'Session 对话与行动')}</h3>
          <p>{description}</p>
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
                onClick={() => {
                  const next = Math.min(entries.length, visibleCount + TRACE_TIMELINE_PAGE_SIZE);
                  setVisibleBoundaryId(entries[entries.length - next]?.id ?? null);
                  setVisibleCount(next);
                }}
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

function diagnosticReportReady(source: unknown): boolean {
  const payload = asRecord(source);
  const rawMessages = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload.messages)
      ? payload.messages
      : [];
  const assistantMessages = rawMessages
    .map(asRecord)
    .filter((message) => stringValue(message.role) === 'assistant')
    .sort((left, right) => (
      timelinePosition(right, 0) - timelinePosition(left, 0)
    ) || (numberValue(right.createdAtMs) - numberValue(left.createdAtMs)));
  const finalAssistant = assistantMessages[0];
  if (!finalAssistant || stringValue(finalAssistant.status) !== 'completed') return false;
  const blocks = Array.isArray(finalAssistant.blocks) ? finalAssistant.blocks : [];
  const text = blocks.filter((rawBlock) => {
    const block = asRecord(rawBlock);
    if (stringValue(block.status) !== 'completed') return false;
    if (stringValue(block.type) !== 'text') return false;
    return true;
  }).map((rawBlock) => {
    const block = asRecord(rawBlock);
    return firstText(asRecord(block.data), ['text', 'markdown', 'bodyMarkdown', 'content'])
      || firstText(block, ['text', 'markdown', 'bodyMarkdown', 'content']);
  }).filter(Boolean).join('\n');
  if (!text) return false;
  if (diagnosticStructuredTextReady(text)) return true;
  // A completed assistant message alone is not a repair authorization. The
  // report must expose the sections needed to distinguish observed evidence,
  // hypotheses, and a reproducible validation plan.
  return ['现象', '影响', 'Trace', '根因', '置信度', '候选修复', '验证', '回跳']
    .every((marker) => text.includes(marker));
}

function diagnosticStructuredResultReady(source: unknown): boolean {
  const payload = asRecord(source);
  const rawMessages = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload.messages)
      ? payload.messages
      : [];
  return rawMessages
    .map(asRecord)
    .filter((message) => stringValue(message.role) === 'assistant' && stringValue(message.status) === 'completed')
    .some((message) => {
      const blocks = Array.isArray(message.blocks) ? message.blocks : [];
      const text = blocks.map(asRecord)
        .filter((block) => stringValue(block.type) === 'text' && ['completed', 'idle', ''].includes(stringValue(block.status)))
        .map((block) => firstText(asRecord(block.data), ['text', 'content', 'markdown', 'bodyMarkdown']) || firstText(block, ['text', 'content', 'markdown', 'bodyMarkdown']))
        .filter(Boolean)
        .join('\n');
      return diagnosticStructuredTextReady(text);
    });
}

function diagnosticSessionStatus(source: unknown): string {
  const payload = asRecord(source);
  return stringValue(payload.status, stringValue(asRecord(payload.session).status));
}

function diagnosticSessionTerminal(source: unknown): boolean {
  return ['idle', 'completed', 'faulted', 'failed', 'error', 'cancelled', 'canceled', 'archived'].includes(diagnosticSessionStatus(source));
}

function diagnosticSessionTerminalFailure(source: unknown): boolean {
  return ['faulted', 'failed', 'error', 'cancelled', 'canceled'].includes(diagnosticSessionStatus(source));
}

function diagnosticStructuredTextReady(text: string): boolean {
  return text.includes('--- TRACE_DIAGNOSTIC_RESULT_V1 ---') && text.includes('--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---');
}

function timelineSourceIdentity(kind: 'session' | 'room', roomId: string, source: unknown): string {
  if (kind === 'room') return `room:${roomId}`;
  const payload = asRecord(source);
  return `session:${stringValue(payload.sessionId)}`;
}

function TraceRunTimeline({ history, loading, runId }: {
  history: RunObservationHistoryState;
  loading: boolean;
  runId: string;
}) {
  const entries = useMemo(() => runObservationEntries(history.source, runId), [history.source, runId]);
  const historyLoading = loading || history.loading;
  return (
    <section aria-label="运行事件时间线" className="trace-agent-timeline" data-scrollable={entries.length ? 'true' : 'false'}>
      <div className="trace-agent-timeline__heading">
        <div>
          <span className="trace-agent-kicker">权威运行记录</span>
          <h3>运行事件与 Agent 行为</h3>
          <p>按 Observation sequence 展示这个 run 的 Tool、Agent、Context、Memory、Room 与 Runtime 事件；可从上方回跳关联 Session 或 Room。</p>
        </div>
        <StatusBadge label={historyLoading ? '读取中' : `${entries.length} 条`} tone={historyLoading ? 'info' : entries.length ? 'neutral' : 'warning'} />
      </div>
      {entries.length ? (
        <div aria-label="运行事件列表" className="trace-agent-timeline__list" tabIndex={0}>
          {entries.map((entry) => (
            <article
              className={`trace-agent-timeline__entry trace-agent-timeline__entry--${entry.status}`}
              data-sequence={entry.sequence}
              data-testid="trace-agent-run-timeline-entry"
              key={entry.eventId}
            >
              <span className="trace-agent-timeline__icon" aria-hidden="true"><Activity size={14} /></span>
              <div className="trace-agent-timeline__copy">
                <div className="trace-agent-timeline__title">
                  <strong>{observationCategoryLabel(entry.category)} · {entry.name || entry.phase}</strong>
                  <span> · {entry.summary || observationStatusLabel(entry.status)}</span>
                  <small>#{entry.sequence} · {observationStatusLabel(entry.status)}</small>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="trace-agent-timeline__empty">当前运行没有可投影的 Observation；可以打开运行记录继续检查 Trace。</p>
      )}
      {history.hasMore ? (
        <div className="trace-agent-timeline__controls">
          <Button
            disabled={history.loading}
            loading={history.loading}
            onClick={() => void history.loadEarlier()}
            size="small"
            variant="quiet"
          >
            从 Observation 加载更早
          </Button>
        </div>
      ) : null}
      {history.error ? (
        <p aria-live="polite" className="trace-agent-inline-note" role="alert">
          Observation history 暂时无法读取：{publicErrorText(history.error, '请稍后重试。')}
        </p>
      ) : null}
    </section>
  );
}

type RunObservationHistoryState = {
  source: ObservationSnapshotV1 | undefined;
  hasMore: boolean;
  loading: boolean;
  error: unknown;
  loadEarlier: () => Promise<number>;
};

function useRunObservationHistory(
  runId: string,
  source: ObservationSnapshotV1 | undefined,
): RunObservationHistoryState {
  const transport = useControlTransport();
  const [pages, setPages] = useState<ObservationSnapshotV1[]>([]);
  const [nextBeforeSequence, setNextBeforeSequence] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setPages([]);
    setNextBeforeSequence(observationHistoryCursor(source));
    setLoading(false);
    setError(null);
  }, [runId]);

  useEffect(() => {
    if (!runId || pages.length || nextBeforeSequence) return;
    const cursor = observationHistoryCursor(source);
    if (cursor) setNextBeforeSequence(cursor);
  }, [nextBeforeSequence, pages.length, runId, source]);

  const loadEarlier = async (): Promise<number> => {
    if (!runId || loading || !nextBeforeSequence) return 0;
    const requestedBeforeSequence = nextBeforeSequence;
    setLoading(true);
    setError(null);
    try {
      const page = await transport.request<ObservationSnapshotV1>({
        pathId: 'observability.snapshot',
        query: { runId, beforeSequence: requestedBeforeSequence, limit: 100 },
        responseContract: 'observation-snapshot.v1',
      });
      if (page.items.some((item) => item.runId && item.runId !== runId)) {
        throw new Error('Observation history 返回了不属于当前 run 的事件。');
      }
      setPages((current) => [...current, page]);
      const nextCursor = observationHistoryCursor(page);
      setNextBeforeSequence(nextCursor > 0 && nextCursor < requestedBeforeSequence ? nextCursor : 0);
      return page.items.length;
    } catch (requestError) {
      setError(requestError);
      return 0;
    } finally {
      setLoading(false);
    }
  };

  return {
    source: mergeObservationHistory(source, pages),
    hasMore: Boolean(nextBeforeSequence),
    loading,
    error,
    loadEarlier,
  };
}

function observationHistoryCursor(source: ObservationSnapshotV1 | undefined): number {
  if (!source?.truncated) return 0;
  return source.items.reduce((lowest, item) => (
    item.sequence > 0 && (lowest === 0 || item.sequence < lowest) ? item.sequence : lowest
  ), 0);
}

function mergeObservationHistory(
  source: ObservationSnapshotV1 | undefined,
  pages: ObservationSnapshotV1[],
): ObservationSnapshotV1 | undefined {
  if (!source) return undefined;
  const seen = new Set<string>();
  const items = [...source.items, ...pages.flatMap((page) => page.items)].filter((item) => {
    const key = item.eventId || `sequence:${item.sequence}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const lastPage = pages.at(-1);
  return {
    ...source,
    items,
    truncated: lastPage ? lastPage.truncated : source.truncated,
  };
}

function runObservationEntries(source: ObservationSnapshotV1 | undefined, runId: string) {
  return (source?.items ?? [])
    .filter((entry) => entry.runId === runId)
    .sort((left, right) => (left.sequence - right.sequence) || (left.createdAtMs - right.createdAtMs));
}

type RunSourceBinding = {
  sessionId: string;
  roomId: string;
  conflict: boolean;
  pending: boolean;
  unavailable: boolean;
};

type RunSourceBindingState = 'pending' | 'ready' | 'error' | 'unavailable';

function runSourceBinding(
  source: ObservationSnapshotV1 | undefined,
  runId: string,
  detail?: ObservabilityTraceGetV1,
  state: RunSourceBindingState = 'ready',
): RunSourceBinding {
  if (state === 'pending') {
    return { sessionId: '', roomId: '', conflict: false, pending: true, unavailable: false };
  }
  if (state === 'error' || state === 'unavailable') {
    return { sessionId: '', roomId: '', conflict: false, pending: false, unavailable: true };
  }
  const canonicalBinding = detail?.trace?.binding;
  const hasCanonicalBinding = canonicalBinding && Object.values(canonicalBinding).some(Boolean);
  if (hasCanonicalBinding) {
    if (canonicalBinding.runId && canonicalBinding.runId !== runId) {
      return { sessionId: '', roomId: '', conflict: true, pending: false, unavailable: false };
    }
    return {
      sessionId: stringValue(canonicalBinding.sessionId),
      roomId: stringValue(canonicalBinding.roomId),
      conflict: false,
      pending: false,
      unavailable: false,
    };
  }
  const entries = [...runObservationEntries(source, runId)].reverse();
  const sessionIds = [...new Set(entries.map((entry) => entry.sessionId).filter(Boolean))];
  const roomIds = [...new Set(entries.map((entry) => entry.roomId).filter(Boolean))];
  return {
    sessionId: sessionIds.length === 1 ? sessionIds[0] : '',
    roomId: roomIds.length === 1 ? roomIds[0] : '',
    conflict: sessionIds.length > 1 || roomIds.length > 1,
    pending: false,
    unavailable: false,
  };
}

function observationCategoryLabel(category: ObservationSnapshotV1['items'][number]['category']): string {
  return ({
    context: 'Context',
    retrieval: 'Retrieval',
    memory: 'Memory',
    tool: 'Tool',
    agent: 'Agent',
    room: 'Room',
    intercom: 'Intercom',
    approval: 'Approval',
    runtime: 'Runtime',
    system: 'System',
  } as const)[category];
}

function observationStatusLabel(status: ObservationSnapshotV1['items'][number]['status']): string {
  return ({
    queued: '排队中',
    running: '进行中',
    waiting: '等待中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    expired: '已过期',
    info: '记录',
  } as const)[status];
}

type RoomTraceHistoryState = {
  source: unknown;
  hasMore: boolean;
  loading: boolean;
  error: unknown;
  loadEarlier: () => Promise<{ count: number; boundaryId: string }>;
};

function useRoomTraceHistory(roomId: string, source: unknown): RoomTraceHistoryState {
  const transport = useControlTransport();
  const [pages, setPages] = useState<RoomEventPage[]>([]);
  const [nextBeforeSequence, setNextBeforeSequence] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setPages([]);
    setNextBeforeSequence(0);
    setLoading(false);
    setError(null);
  }, [roomId]);

  useEffect(() => {
    if (!roomId || pages.length || nextBeforeSequence) return;
    const cursor = roomHistoryCursor(source);
    if (cursor) setNextBeforeSequence(cursor);
  }, [nextBeforeSequence, pages.length, roomId, source]);

  const loadEarlier = async (): Promise<{ count: number; boundaryId: string }> => {
    if (!roomId || loading || !nextBeforeSequence) return { count: 0, boundaryId: '' };
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
      return {
        count: page.items.length,
        boundaryId: page.items[0] ? `room-event:${page.items[0].eventId}` : '',
      };
    } catch (requestError) {
      setError(requestError);
      return { count: 0, boundaryId: '' };
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
  const entries = new Map<string, TraceTimelineEntry>();
  const add = (entry: TraceTimelineEntry) => {
    const summary = entry.summary.trim();
    if (!summary) return;
    const next = { ...entry, summary };
    const previous = entries.get(entry.id);
    if (!previous || timelineEntryIsNewer(next, previous)) entries.set(entry.id, next);
  };
  if (kind === 'session') sessionTimelineEntries(source, add);
  else roomTimelineEntries(source, add);
  return [...entries.values()].sort((left, right) => (left.sequence - right.sequence) || (left.createdAtMs - right.createdAtMs));
}

function timelineEntryIsNewer(next: TraceTimelineEntry, previous: TraceTimelineEntry): boolean {
  const statusDelta = timelineStatusRank(next.status) - timelineStatusRank(previous.status);
  if (statusDelta !== 0) return statusDelta > 0;
  const positionDelta = next.sequence - previous.sequence;
  if (positionDelta !== 0) return positionDelta > 0;
  const timestampDelta = next.createdAtMs - previous.createdAtMs;
  return timestampDelta >= 0;
}

function timelineStatusRank(status: string | undefined): number {
  return ({
    queued: 1,
    running: 2,
    waiting: 2,
    streaming: 2,
    completed: 3,
    failed: 3,
    aborted: 3,
    cancelled: 3,
  } as Record<string, number>)[status ?? ''] ?? 0;
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
      .map((block) => firstText(asRecord(block.data), ['text', 'content', 'markdown', 'bodyMarkdown']))
      .filter(Boolean)
      .join(' ');
    const summary = text || firstText(message, ['text', 'content', 'message', 'summary']);
    if (summary) {
      add({
        id: `message:${stringValue(message.id, String(index))}`,
        kind: role,
        label: role === 'user' ? '用户' : '助手',
        summary,
        status: stringValue(message.status),
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
        status: stringValue(block.status),
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
      status: stringValue(event.status),
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
      status: stringValue(event.status),
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

  const data = useMemo<TraceTargetCatalog>(() => {
    const sessionTargets = uniqueTargets(sessions.data?.pages.flatMap((page) => page.items) ?? []);
    const sessionById = new Map(sessionTargets.map((target) => [target.id, target]));
    const runTargets = uniqueTargets(runs.data?.pages.flatMap((page) => page.items) ?? [])
      .map((target) => bindRunTargetWorkspace(target, sessionById));
    return {
      sessions: sessionTargets,
      rooms: uniqueTargets(rooms.data?.pages.flatMap((page) => page.items) ?? []),
      runs: runTargets,
      hasMore: {
        session: Boolean(sessions.hasNextPage),
        room: Boolean(rooms.hasNextPage),
        run: Boolean(runs.hasNextPage),
      },
    };
  }, [rooms.data, rooms.hasNextPage, runs.data, runs.hasNextPage, sessions.data, sessions.hasNextPage]);

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

/**
 * URL handoffs intentionally strip machine paths. When the same Session or
 * Room is present in the canonical Runtime catalog, retain its workspace roots
 * only as navigation context; repair authority is always the full-trust policy.
 */
function resolveIncomingTraceTarget(
  incoming: TraceTarget | null,
  canonicalTargets: TraceTarget[],
): TraceTarget | null {
  if (!incoming) return null;
  const canonical = canonicalTargets.find((target) => target.targetKey === incoming.targetKey);
  if (!canonical) return incoming;
  return {
    ...canonical,
    title: incoming.title,
    detail: incoming.detail,
    handoff: incoming.handoff,
    handoffOnly: false,
  };
}

function runItems(value: ObservationSnapshotV1): TraceTarget[] {
  const grouped = new Map<string, {
    latest: ObservationSnapshotV1['items'][number];
    sessionIds: Set<string>;
  }>();
  for (const item of value.items) {
    if (!item.runId) continue;
    const previous = grouped.get(item.runId);
    const latest = !previous || item.sequence > previous.latest.sequence || item.createdAtMs > previous.latest.createdAtMs
      ? item
      : previous.latest;
    const sessionIds = previous?.sessionIds ?? new Set<string>();
    if (item.sessionId) sessionIds.add(item.sessionId);
    grouped.set(item.runId, { latest, sessionIds });
  }
  return [...grouped.values()]
    .sort((left, right) => (right.latest.sequence - left.latest.sequence) || (right.latest.createdAtMs - left.latest.createdAtMs))
    .map(({ latest: item, sessionIds }) => ({
      kind: 'run' as const,
      id: item.runId,
      targetKey: traceTargetKey('run', item.runId),
      title: item.status === 'failed' ? `运行失败 · ${item.name || item.runId}` : item.name || `运行 ${item.runId}`,
      status: item.status,
      updatedAtMs: item.createdAtMs,
      detail: `${item.runId} · ${item.category} · ${item.summary || '关联 Trace 运行'}`,
      workspaceRoots: [],
      sourceSessionId: sessionIds.size === 1 ? [...sessionIds][0] : '',
      workspaceBindingState: sessionIds.size > 1 ? 'conflict' as const : 'unbound' as const,
    }));
}

function bindRunTargetWorkspace(
  target: TraceTarget,
  sessionById: Map<string, TraceTarget>,
): TraceTarget {
  if (target.kind !== 'run' || target.workspaceBindingState === 'conflict' || !target.sourceSessionId) {
    return { ...target, workspaceRoots: [] };
  }
  const sourceSession = sessionById.get(target.sourceSessionId);
  if (!sourceSession?.workspaceRoots.length) {
    return { ...target, workspaceRoots: [], workspaceBindingState: 'unbound' };
  }
  return {
    ...target,
    workspaceRoots: sourceSession.workspaceRoots,
    workspaceBindingState: 'ready',
  };
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
      targetKey: traceTargetKey(kind, id),
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

function terminalRepairTurnTrace(value: unknown): string {
  const snapshot = asRecord(value);
  if (
    snapshot.status !== 'idle'
    || snapshot.partial === true
    || snapshot.truncated === true
    || stringValue(snapshot.snapshotScope).toLowerCase() === 'recent'
  ) return '';
  const items = Array.isArray(snapshot.items) ? snapshot.items.map(asRecord) : [];
  const turnId = items
    .filter((item) => (
      item.role === 'assistant'
      && ['completed', 'failed'].includes(stringValue(item.status))
      && !stringValue(item.turnId).startsWith('history:')
      && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(stringValue(item.turnId))
    ))
    .sort((left, right) => (
      numberValue(right.completedAtMs || right.createdAtMs)
      - numberValue(left.completedAtMs || left.createdAtMs)
    ))
    .map((item) => stringValue(item.turnId))
    .find(Boolean);
  return turnId ? `trace:turn:${turnId}` : '';
}

function traceRepairIdentity(report: TraceAgentReport): TraceRepairIdentity {
  const sourceScope = `${report.target.kind}:${redactTraceAgentText(report.target.id, 180)}`;
  const sourceTraceId = redactTraceAgentText(report.traceId, 180);
  const failureRef = redactTraceAgentText(
    report.target.handoff?.failureRef
      || report.evidence.find((item) => item.id.startsWith('trace:'))?.id
      || report.evidence[0]?.id
      || sourceTraceId,
    180,
  );
  return { sourceScope, sourceTraceId, failureRef };
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
        code: failureCode(asRecord(item.attributes)),
      });
    }
  }
  const payload = asRecord(source);
  const rawMessages = Array.isArray(payload.items) ? payload.items : Array.isArray(payload.messages) ? payload.messages : [];
  for (const rawMessage of rawMessages) {
    const message = asRecord(rawMessage);
    const messageId = stringValue(message.id, `message-${evidence.length}`);
    const blocks = Array.isArray(message.blocks) ? message.blocks : [];
    const directSummary = firstText(message, ['error', 'errorMessage', 'message', 'summary', 'content']);
    if (directSummary && (stringValue(message.status) === 'failed' || /(error|fail|failed|timeout|timed out|validation|失败|错误|超时|验证)/i.test(directSummary))) {
      evidence.push({
        id: `message:${messageId}:summary`,
        source: `Session transcript · ${messageId}`,
        status: stringValue(message.status, 'failed'),
        title: '消息异常',
        summary: directSummary,
        createdAtMs: numberValue(message.createdAtMs),
        code: failureCode(message),
      });
    }
    for (const rawBlock of blocks) {
      const block = asRecord(rawBlock);
      const data = asRecord(block.data);
      const blockType = stringValue(block.type, 'message');
      const blockStatus = stringValue(block.status, stringValue(message.status, 'info'));
      const summary = firstText(data, ['error', 'errorMessage', 'message', 'summary', 'text', 'content', 'markdown', 'bodyMarkdown']);
      if (!summary || (blockStatus !== 'failed' && blockType !== 'error' && !/(error|fail|failed|timeout|timed out|validation|失败|错误|超时|验证)/i.test(summary))) continue;
      evidence.push({
        id: `message:${messageId}:${stringValue(block.id, String(evidence.length))}`,
        source: `Session transcript · ${messageId}`,
        status: blockStatus,
        title: blockType === 'tool_result' ? 'Tool 结果' : blockType === 'error' ? '运行错误' : '消息异常',
        summary,
        createdAtMs: numberValue(message.createdAtMs),
        code: failureCode(data) || failureCode(block) || failureCode(message),
      });
    }
  }
  const rawEvents = Array.isArray(payload.events) ? payload.events : Array.isArray(payload.liveEvents) ? payload.liveEvents : [];
  for (const rawEvent of rawEvents) {
    const event = asRecord(rawEvent);
    const eventPayload = asRecord(event.payload);
    const summary = firstText(eventPayload, ['error', 'errorMessage', 'message', 'summary', 'text', 'content']);
    const eventStatus = stringValue(event.status, stringValue(event.eventType, 'info'));
    if (!summary || (eventStatus !== 'failed' && !/(error|fail|failed|timeout|timed out|validation|失败|错误|超时|验证)/i.test(summary))) continue;
    evidence.push({
      id: `event:${stringValue(event.eventId, String(evidence.length))}`,
      source: `Room event · ${stringValue(event.eventType, 'event')}`,
      status: eventStatus,
      title: stringValue(event.name, stringValue(event.eventType, '协作事件')),
      summary,
      createdAtMs: numberValue(event.createdAtMs),
      code: failureCode(eventPayload) || failureCode(event),
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

function failureCode(value: Record<string, unknown>): string {
  return firstText(value, [
    'causeCode',
    'cause_code',
    'reasonCode',
    'reason_code',
    'errorCode',
    'error_code',
    'failureKind',
    'failure_kind',
  ]);
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

function traceRecheckErrorText(value: unknown): string {
  if (value instanceof TraceRepairValidationError) return value.message;
  return publicErrorText(value, '修复 Session 尚未形成可复检的 Trace。');
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
    targetKey: traceTargetKey(kind, id),
    title: handoff.title,
    status: 'failed',
    updatedAtMs: handoff.occurredAtMs,
    detail: handoff.summary,
    workspaceRoots: handoff.workspaceRoots,
    handoffOnly,
    handoff,
  };
}

function diagnosticPrompt(targets: TraceTarget[], traceId: string, reportId = ''): string {
  const primaryTarget = targets[0];
  const safeTargetId = redactTraceAgentText(primaryTarget.id, 180);
  const safeTargetTitle = redactTraceAgentText(primaryTarget.title, 180);
  const safeTraceId = redactTraceAgentText(traceId, 180);
  const focusHint = diagnosticFocusHint(primaryTarget, targets.length);
  return [
    `先调用 skill_load 加载 name=trace-agent-diagnostics；SkillRef=${TRACE_AGENT_SKILL_REF}。`,
    '',
    '这是一次全信任诊断与修复。可直接读取选定对象的原始对话、Trace 和根目录 / 下文件，无需逐项审批；确认根因后执行最小、可验证的项目修改，不把报告或猜测当成完成。',
    `诊断对象：${primaryTarget.kind} ${safeTargetId}（${safeTargetTitle}）`,
    targets.length > 1 ? `本次冻结范围共 ${targets.length} 个对象：${targets.map((target) => `${target.kind}:${redactTraceAgentText(target.id, 120)}`).join('、')}` : '',
    reportId ? `网页报告 ID：${redactTraceAgentText(reportId, 180)}。诊断完成后必须输出结构化结果标记，供服务端持久化。` : '',
    primaryTarget.handoffOnly
      ? '这是 handoff-only 输入，没有可用的 canonical Session / Room / Run；不要把 entityId 当作 runId，也不要调用 observability.snapshot 伪造查询。'
      : traceId ? `当前已发现的最新 Trace：${safeTraceId}` : '当前尚未发现单一最新 Trace，请从对象范围读取关联 Trace。',
    ...(primaryTarget.handoff ? [
      '',
      '下面是用户从原位置明确送来的结构化诊断输入。它是本次诊断的精确入口；保留所有 ID 和引用，并回跳到 sourceRoute 复核原记录。',
      '--- TRACE_AGENT_HANDOFF ---',
      JSON.stringify(primaryTarget.handoff, null, 2),
      '--- END TRACE_AGENT_HANDOFF ---',
    ] : []),
    '',
    `建议主诊断域：${focusHint}。这只是对象类型给出的起点；调用 trace_diagnostics.inspect 后，必须按冻结证据修正。`,
    '先确定本次 active lanes，再诊断。只分析与用户可见失败、目标产物和首个失败 owner 有直接关系的域。',
    '没有命中条件的诊断域必须标记为 not_applicable：不要为它生成 judgeScore 或 finding；八行展示由确定性网页报告投影负责。',
    'Room / WorkItem / 子 Agent 只在 inspect 返回真实协作绑定时启用；后台 run 没有协作绑定不是缺陷，也不生成“建议补绑定”的 finding。',
    'Memory 维护只检查来源读取、整理产物、冲突/去重、验证和持久化链；不要因为维度名是 Memory/RAG 就自动扩展到 Knowledge 检索与排序。',
    'Context、效率和成本只在存在对应来源清单、token、字节或阶段耗时证据时启用；缺证据只写一次证明边界，不得拆成多个泛化问题。',
    'Findings 只保留 1 个首要根因和至多 3 个直接后果或必要证据缺口；禁止为了填满评分维度而制造 finding。',
    '',
    '报告必须按“现象 → 影响 → Trace/span/run 证据 → 可能根因 → 置信度/未知边界 → 候选修复 → 如何用沙盒或 Eval 验证 → 可回跳的 Trace/Session/Room/文件”输出。不要把模型推测写成事实。',
    'summary、影响、候选修复和下一步必须先用普通用户能看懂的话说明“什么没完成”；Host、settlement、JSONL、Provider、span、schema 和策略版本等内部名称只放在 finding 证据/细节里。',
    '',
    reportId ? `对话中的可见说明最多 6 行，第一行写“网页报告：${redactTraceAgentText(reportId, 180)}”；完整细节只进入下面的结构化结果，由网页报告渲染。` : '对话中的可见说明最多 6 行；完整细节只进入下面的结构化结果，由网页报告渲染。',
    '在简短说明之后，必须追加下面的结构化结果。只允许引用本次 inspect 返回的 evidenceId；没有证据就留空或 unknown，不要编造 ID。',
    'presentation.failureAttribution 必须存在；layers 必须按 tool、skill、template、workflow、model 的固定顺序各出现一次。至多一个 primary；primary、contributing、healthy 必须引用本次 inspect 返回的冻结 evidenceId。',
    '--- TRACE_DIAGNOSTIC_RESULT_V1 ---',
    JSON.stringify({
      schemaVersion: 'rag-ime.trace-diagnostic-result.v1',
      summary: '<简短结论>',
      hardGates: [{ gateId: '<gate>', status: 'unknown', reason: '<依据>', evidenceIds: [] }],
      judgeScores: [{ dimensionId: 'task_completion', score: null, authority: 'ai_judge_estimate', explanation: '<只能是估计>', evidenceIds: [] }],
      requirementAssessments: [{ requirementId: '<inspect 返回的 requirementId>', status: 'unverified', owner: '<owner 或空>', authority: 'ai_judge_estimate', evidenceIds: [], note: '<判断边界>' }],
      causalLinks: [{ linkId: '<stable link id>', fromEvidenceId: '<frozen evidenceId>', toEvidenceId: '<frozen evidenceId>', relation: 'caused', authority: 'ai_judge_estimate', confidence: 'unknown', explanation: '<为什么存在因果而不只是时间相邻>' }],
      findings: [{ findingId: '<finding>', dimensionId: 'tool_runtime', severity: 'medium', observation: '<事实>', hypothesis: '<假设>', conclusion: '<结论或未知>', confidence: 'unknown', evidenceIds: [], candidateRepair: '<候选修复>', verification: '<验证方法>' }],
      presentation: {
        headline: '<普通用户能看懂的结论>',
        impact: '<什么没有完成，以及对用户的影响>',
        primaryFindingId: '<finding>',
        failureAttribution: {
          primaryLayer: 'tool',
          summary: '<用一句话说明主要故障层与共同影响层>',
          layers: [
            { layer: 'tool', verdict: 'primary', explanation: '<为什么 Tool / Runtime 是主要故障层>', evidenceIds: ['<frozen evidenceId>'] },
            { layer: 'skill', verdict: 'healthy', explanation: '<Skill 为什么不是故障来源>', evidenceIds: ['<frozen evidenceId>'] },
            { layer: 'template', verdict: 'unknown', explanation: '<模板提示层还缺什么证据>', evidenceIds: [] },
            { layer: 'workflow', verdict: 'contributing', explanation: '<工作流怎样共同影响失败>', evidenceIds: ['<frozen evidenceId>'] },
            { layer: 'model', verdict: 'not_applicable', explanation: '<为什么本次不涉及模型能力>', evidenceIds: [] },
          ],
        },
        knownFacts: [{ fact: '<已确认事实>', evidenceIds: ['<frozen evidenceId>'] }],
        evidenceGaps: [{ gap: '<未知>', consequence: '<影响>', howToObtain: '<如何补齐>' }],
        causalNodes: [{ label: '<阶段>', detail: '<发生了什么>', status: 'confirmed', evidenceIds: ['<frozen evidenceId>'] }],
        expectedStageCount: 0,
        recordedStageReceiptEvidenceIds: [],
      },
    }, null, 2),
    '--- END_TRACE_DIAGNOSTIC_RESULT_V1 ---',
  ].join('\n');
}

function diagnosticFocusHint(target: TraceTarget, targetCount: number): string {
  const kind = target.handoff?.kind ?? target.kind;
  const targetIdentity = `${target.id} ${target.title}`.toLowerCase();
  const primary = kind === 'memory' || targetIdentity.includes('memory-maintenance')
    ? 'Memory 维护结果与 Runtime 失败链'
    : kind === 'knowledge'
      ? 'Knowledge/RAG 检索链、引用与最终答案质量'
      : ['room', 'planet', 'satellite'].includes(kind)
        ? 'Room 协作、WorkItem owner 与终态传播'
        : kind === 'context'
          ? 'Context 组装、压缩与关键约束保真'
          : ['tool', 'runtime', 'sandbox'].includes(kind)
            ? 'Tool / Provider / Runtime 执行链'
            : kind === 'review'
              ? 'Review 依据、结论与回写终态'
              : kind === 'file'
                ? 'WorkDocument / Artifact 写入、注册与验收链'
                : kind === 'task'
                  ? '任务完成度、owner 与终态证据'
                  : '用户需求完成度与首个失败 owner';
  return targetCount > 1 ? `多对象可比性与 ${primary}` : primary;
}

function repairPrompt(report: TraceAgentReport, identity: TraceRepairIdentity = traceRepairIdentity(report)): string {
  const primaryTarget = report.primaryTarget;
  const handoff = {
    target: {
      kind: primaryTarget.kind,
      id: redactTraceAgentText(primaryTarget.id, 180),
      title: redactTraceAgentText(primaryTarget.title, 180),
      status: primaryTarget.status,
      handoff: primaryTarget.handoff,
    },
    repairOwner: {
      targetKey: primaryTarget.targetKey,
      kind: primaryTarget.kind,
      id: redactTraceAgentText(primaryTarget.id, 180),
    },
    comparisonTargets: report.targets.slice(1).map((target) => ({
      targetKey: target.targetKey,
      kind: target.kind,
      id: redactTraceAgentText(target.id, 180),
      title: redactTraceAgentText(target.title, 180),
    })),
    diagnosticSessionId: redactTraceAgentText(report.sessionId, 180),
    diagnosticReportRef: `agent-session:${redactTraceAgentText(report.sessionId, 180)}`,
    traceId: report.traceId ? redactTraceAgentText(report.traceId, 180) : null,
    repairSessionPolicy: TRACE_DIAGNOSTIC_SESSION_POLICY,
    failedEvidence: report.evidence.map((item) => ({
      id: redactTraceAgentText(item.id, 180),
      source: redactTraceAgentText(item.source, 240),
      status: item.status,
      title: redactTraceAgentText(item.title, 180),
      summary: redactTraceAgentError(item.summary) || redactTraceAgentText(item.summary, 640),
      code: item.code ? redactTraceAgentText(item.code, 120) : null,
      traceId: item.traceId ? redactTraceAgentText(item.traceId, 180) : null,
      createdAtMs: item.createdAtMs,
    })),
  };
  return [
    '这是 Trace Agent 的候选修复交接。你是独立的全信任可写 Agent，请先复核证据和诊断 Session，再完成最小修复。',
    `修复目标是 primary failure：${primaryTarget.kind}:${redactTraceAgentText(primaryTarget.id, 180)}。其余诊断对象只用于比较和定位，不是新的修复目标；这是任务范围，不是文件系统权限限制。`,
    '用户已经在唯一确认中授予根目录 / 的全磁盘权限、全部 Tools 权限，并同意每一个 Tool 和 action 自动批准。不要再询问目录、ENABLE_FULL_TRUST、Tool 批准或任何 PAW 审批。',
    '来源工作区、路径、workspace scope、approval hash 和来源/修复工作区是否相同都不是阻断条件；handoff 中的对象与路径只能作为导航线索，权限边界始终是 /。',
    '只有 macOS TCC、Unix 文件权限和其他操作系统权限仍可能拒绝具体操作；遇到真实的 OS 拒绝时，报告该拒绝，不要把它误写成 PAW 审批问题。',
    '请优先定位根因，给出最小修复；完成后运行与问题直接相关的最小验证，并回报修改文件、实际 Tool 操作、验证结果以及如何回到 Trace 重跑诊断。',
    '',
    '--- TRACE_DIAGNOSTIC_HANDOFF ---',
    JSON.stringify(handoff, null, 2),
    '--- END TRACE_DIAGNOSTIC_HANDOFF ---',
    '',
    '本次修复必须限定在以下原始失败身份：',
    `sourceScope: ${identity.sourceScope}`,
    `sourceTraceId: ${identity.sourceTraceId}`,
    `failureRef: ${identity.failureRef}`,
    '',
    '完成修复与最小验证后，最终回复必须包含下列结构化报告，供界面核对范围；报告中的 ID、testStatus 都只是声明，不能替代实际 Session/Trace 证据：',
    'TRACE_REPAIR_EVIDENCE',
    JSON.stringify({
      sourceScope: identity.sourceScope,
      sourceTraceId: identity.sourceTraceId,
      failureRef: identity.failureRef,
      repairTraceId: '<actual completed repair Trace id>',
      changeEvidence: { files: ['<changed file>'], operations: ['<performed operation>'] },
      testEvidence: { commands: ['<actual verification command>'], results: [{ status: 'completed', exitCode: 0 }] },
      testStatus: 'passed',
    }, null, 2),
    '不要输出 changeReceiptId、testEvidenceId、repairReceiptId；这些 ID 由服务端在证据写入后生成。不要把没有对应已完成工具/span/命令状态的文本描述写入 changeEvidence/testEvidence。',
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
  return ({ active: '进行中', running: '运行中', idle: '已结束', completed: '已完成', archived: '已归档', failed: '失败', stopped: '已停止', expired: '已过期' } as Record<string, string>)[value] ?? value;
}

function statusTone(value: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (['active', 'running'].includes(value)) return 'info';
  if (['failed', 'stopped', 'expired'].includes(value)) return 'danger';
  if (['completed', 'idle'].includes(value)) return 'success';
  return 'neutral';
}

function formatTime(value: number): string {
  return value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '暂无时间';
}

export { TRACE_AGENT_SKILL_REF };
