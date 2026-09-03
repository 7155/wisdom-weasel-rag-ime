import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import type {
  EvalLabRunListV1 as GeneratedEvalLabRunListV1,
  PathSearch as GeneratedEvalLabPathSearch,
  Run as GeneratedEvalLabRun,
  Task as GeneratedEvalLabTask,
} from '@/contracts/generated/eval-lab-run-list.v1';
import type { AgentLabExperimentV1 } from '@/contracts/generated/agent-lab-experiment.v1';
import type { ControlTransport } from '@/platform/transport';

export type EvalLabComparisonResult = 'pass' | 'fail' | 'partial' | 'unknown';
export type EvalLabFailureOwner = null | 'prompt_context' | 'evaluator_gold' | 'agent' | 'unknown';

export type EvalLabRepairPlan = {
  targetLayers?: readonly string[];
  summary?: string;
} | string;

export type EvalLabExperiment = AgentLabExperimentV1;
export type EvalLabPathSearch = GeneratedEvalLabPathSearch;

export type EvalLabExplainableCase = {
  caseId: string;
  businessRequest: {
    normalizedText: string;
  };
  agentOutcome: {
    normalizedSummary: string;
  };
  acceptance: {
    passed: number;
    total: number;
    items: readonly {
      id: string;
      label: string;
      status: EvalLabComparisonResult;
      failureOwner: EvalLabFailureOwner;
      explanation: string;
    }[];
  };
};

export type EvalLabTask = GeneratedEvalLabTask & {
  /** A privacy-safe projection; it must not contain raw transcript/tool data. */
  explanation?: EvalLabExplainableCase;
  /** Distinguishes an intentional report-only task row from a missing transcript. */
  evidenceStatus?: string;
  failedVerifierIndexes?: readonly number[];
  failedVerifierNames?: readonly string[];
  verifierResults?: readonly { index: number; passed: boolean }[];
  failureOwner?: string;
  cleanupStatus?: string;
  runtimeErrorType?: string;
  successfulToolCalls?: number;
};

export type EvalLabRun = Omit<GeneratedEvalLabRun, 'tasks'> & {
  tasks: readonly EvalLabTask[];
  /** Optional backend extensions; the generated v1 contract remains compatible. */
  evaluationKind?: string;
  repairPlan?: EvalLabRepairPlan;
};

export type EvalLabRunListV1 = Omit<GeneratedEvalLabRunListV1, 'items' | 'experiments'> & {
  items: readonly EvalLabRun[];
  experiments: readonly EvalLabExperiment[];
  pathSearches?: readonly EvalLabPathSearch[];
};

export type EvalLabEvidenceTask = {
  taskIndex: number;
  taskLabel: string;
  title: string;
  transcriptAvailable: boolean;
  transcriptSha256: string;
  transcriptBytes: number;
  jsonlLines: number;
  userMessages: number;
  assistantMessages: number;
  toolCalls: number;
  toolFailures: number;
  toolNames: readonly string[];
  externalSessionRef: string;
  model: string;
  thinking: string;
  executionMode: string;
  createdAtMs: number;
  updatedAtMs: number;
  evidenceStatus: string;
  taskSucceeded?: boolean;
  terminalEvent?: string;
  verifierPassed?: number;
  verifierTotal?: number;
  latencyMs?: number;
  failedVerifierIndexes?: readonly number[];
  failedVerifierNames?: readonly string[];
  verifierResults?: readonly { index: number; passed: boolean }[];
  failureOwner?: string;
  cleanupStatus?: string;
  runtimeErrorType?: string;
  successfulToolCalls?: number;
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
};

export type EvalLabEvidenceRun = {
  runId: string;
  title: string;
  family: string;
  sourceId?: string;
  sourceLabel?: string;
  split: string;
  status: string;
  evidenceKind?: 'transcript_and_report' | 'transcript_only' | 'report_only' | 'unavailable' | string;
  reportAvailable: boolean;
  databaseAvailable: boolean;
  reportSha256?: string;
  databaseSha256?: string;
  markerSha256?: string;
  sessionCount: number;
  transcriptCount: number;
  transcriptBytes: number;
  missingTranscriptCount?: number;
  reportOnlyRunCount?: number;
  metrics: Readonly<Record<string, unknown>>;
  environment: EvalLabEvidenceEnvironment;
  tasks: readonly EvalLabEvidenceTask[];
  artifacts?: readonly {
    kind: string;
    label: string;
    available: boolean;
    bytes: number;
    sha256: string;
  }[];
  updatedAtMs: number;
};

export type EvalLabEvidenceSource = {
  sourceId: string;
  label: string;
  available: boolean;
  runCount: number;
  sessionCount: number;
  transcriptCount: number;
  transcriptBytes: number;
  missingTranscriptCount?: number;
  reportOnlyRunCount?: number;
};

export type EvalLabEvidenceEnvironment = {
  provider?: string;
  model?: string;
  thinking?: string;
  workflowProfile?: string;
  suiteRevision?: string;
  split?: string;
  transport?: string;
  timeoutSeconds?: number;
  piVersion?: string;
  runtimeVersion?: string;
  protocolVersion?: string;
  executionModes?: readonly string[];
  workspace?: string;
  network?: string;
  pricingUsage?: string;
  identityHashes?: Readonly<Record<string, string>>;
  tokenUsage?: Readonly<Record<string, number>>;
  usageReceipt?: Readonly<Record<string, unknown>>;
  costEstimate?: Readonly<Record<string, unknown>>;
  billing?: Readonly<Record<string, unknown>>;
  pricingIdentity?: Readonly<Record<string, unknown>>;
  machine?: Readonly<Record<string, unknown>>;
  knowledge?: Readonly<Record<string, unknown>>;
  publicConfig?: Readonly<Record<string, unknown>>;
  traceIds?: readonly string[];
  traceCount?: number;
};

export type EvalLabEvidenceTurn = {
  kind: 'message' | 'tool_call' | 'tool_result' | string;
  role: string;
  text: string;
  toolName?: string;
  status?: string;
  argumentKeys?: readonly string[];
  timestampMs?: number;
  entryRef?: string;
};

export type EvalLabEvidenceDetail = {
  status: string;
  runId: string;
  taskIndex?: number;
  /** Preview fixtures may expose bounded sample turns, never source transcripts. */
  origin?: 'preview' | 'runtime' | string;
  task?: EvalLabEvidenceTask;
  session?: {
    title?: string;
    model?: string;
    thinking?: string;
    executionMode?: string;
    sessionMode?: string;
    messageCount?: number;
  };
  environment?: EvalLabEvidenceEnvironment;
  turns: readonly EvalLabEvidenceTurn[];
  tools: readonly {
    toolName: string;
    status: string;
    text: string;
    timestampMs?: number;
  }[];
  protected?: {
    sourceReadOnly?: boolean;
    thinkingShown?: boolean;
    systemPromptShown?: boolean;
    hiddenGoldShown?: boolean;
    rawSqlShown?: boolean;
    pathsAndCredentialsShown?: boolean;
    redactions?: readonly string[];
  };
  report?: Readonly<Record<string, unknown>>;
  message?: string;
  summary?: EvalLabEvidenceRun;
};

export type EvalLabEvidenceResponse = {
  schemaVersion: 'rag-ime.eval-lab-evidence.v1';
  ok: true;
  source: {
    available: boolean;
    label: string;
    runCount: number;
    sessionCount: number;
    transcriptCount: number;
    transcriptBytes: number;
    missingTranscriptCount?: number;
    reportOnlyRunCount?: number;
    generatedAtMs?: number;
  };
  sources?: readonly EvalLabEvidenceSource[];
  runs: readonly EvalLabEvidenceRun[];
  total: number;
  detail?: EvalLabEvidenceDetail;
};

export const evalLabQueryKeys = {
  runs: ['eval-lab', 'runs'] as const,
  evidence: (runId = '', taskIndex = 0) => ['eval-lab', 'evidence', runId, taskIndex] as const,
};

export function useEvalLabRuns() {
  const transport = useControlTransport();
  return useQuery({
    queryKey: evalLabQueryKeys.runs,
    queryFn: ({ signal }) => requestEvalLabRuns(transport, signal),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function requestEvalLabRuns(
  transport: Pick<ControlTransport, 'request'>,
  signal?: AbortSignal,
): Promise<EvalLabRunListV1> {
  return transport.request<unknown>({
    pathId: 'agent.eval-lab.runs',
    signal,
  }).then(parseEvalLabRunsResponse);
}

export function parseEvalLabRunsResponse(value: unknown): EvalLabRunListV1 {
  if (!isRecord(value)
    || value.schemaVersion !== 'rag-ime.eval-lab-run-list.v1'
    || value.ok !== true
    || !Array.isArray(value.items)
    || typeof value.total !== 'number'
    || !Array.isArray(value.experiments)
    || typeof value.experimentTotal !== 'number') {
    throw new Error('评测回执格式暂不可用。');
  }
  return value as unknown as EvalLabRunListV1;
}

export function useEvalLabEvidenceCatalog(enabled = true) {
  const transport = useControlTransport();
  return useQuery({
    queryKey: evalLabQueryKeys.evidence(),
    queryFn: ({ signal }) => requestEvalLabEvidence(transport, {}, signal),
    enabled,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useEvalLabEvidenceDetail(runId: string, taskIndex: number, enabled = true) {
  const transport = useControlTransport();
  return useQuery({
    queryKey: evalLabQueryKeys.evidence(runId, taskIndex),
    queryFn: ({ signal }) => requestEvalLabEvidence(transport, { runId, taskIndex }, signal),
    // taskIndex=0 addresses a report-only receipt with no public Session.
    enabled: enabled && Boolean(runId) && taskIndex >= 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function requestEvalLabEvidence(
  transport: Pick<ControlTransport, 'request'>,
  params: { runId?: string; taskIndex?: number } = {},
  signal?: AbortSignal,
): Promise<EvalLabEvidenceResponse> {
  const query: Record<string, string> = {};
  if (params.runId) query.runId = params.runId;
  if (params.taskIndex !== undefined && params.taskIndex >= 0) query.taskIndex = String(params.taskIndex);
  return transport.request<unknown>({
    pathId: 'agent.eval-lab.evidence',
    query,
    signal,
  }).then(parseEvalLabEvidenceResponse);
}

export function parseEvalLabEvidenceResponse(value: unknown): EvalLabEvidenceResponse {
  if (!isRecord(value)
    || value.schemaVersion !== 'rag-ime.eval-lab-evidence.v1'
    || value.ok !== true
    || !isRecord(value.source)
    || !Array.isArray(value.runs)
    || typeof value.total !== 'number') {
    throw new Error('评测对话证据格式暂不可用。');
  }
  return value as unknown as EvalLabEvidenceResponse;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
