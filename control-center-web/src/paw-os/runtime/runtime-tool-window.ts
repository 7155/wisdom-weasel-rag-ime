import type { UiAgentEvent, UiRoomEvent } from '@/contracts/ui-events';
import type { AgentBackgroundJobV1 } from '@/contracts/generated/agent-background-job.v1';
import type { PawOsWindowRequest } from '@/features/paw-os/surface-context';

type RuntimeEvent = Pick<UiAgentEvent, 'eventType' | 'payload'> & Partial<Pick<UiAgentEvent, 'sessionId'>>
  | Pick<UiRoomEvent, 'eventType' | 'payload'> & Partial<Pick<UiRoomEvent, 'roomId' | 'participantId' | 'sourceSessionId'>>;

const processTools = new Set(['bash', 'shell', 'process-terminal', 'process_terminal', 'workspace_job']);
const browserTools = new Set(['browser', 'ego-browser', 'ego_browser', 'egolite']);

export function createRuntimeToolWindowProjector(): (event: RuntimeEvent) => PawOsWindowRequest | null {
  const pendingProcesses: Array<{ command: string; cwd: string; sessionId: string; toolCallId: string }> = [];
  const runBindings = new Map<string, string>();
  return (event) => {
    const request = runtimeToolWindowRequest(event);
    if (!request) return request;
    if (request.target.kind === 'browser-target') {
      const target = request.target;
      if (!target.toolCallId || target.id === target.toolCallId) return request;
      return { ...request, target: { ...target, id: target.toolCallId } };
    }
    if (request.target.kind !== 'process-terminal') return request;
    const target = request.target;
    const sourceEventType = event.eventType === 'participant_activity'
      ? text(event.payload.sourceEventType)
      : event.eventType;
    if (sourceEventType === 'tool_started') {
      pendingProcesses.push({ command: target.command, cwd: target.cwd ?? '', sessionId: target.sessionId, toolCallId: target.toolCallId });
      return request;
    }
    if (target.runId && target.toolCallId !== target.runId) runBindings.set(target.runId, target.toolCallId);
    if (!target.runId || target.id !== target.runId) return request;
    let boundToolCallId = runBindings.get(target.runId);
    for (let index = pendingProcesses.length - 1; !boundToolCallId && index >= 0; index -= 1) {
      const candidate = pendingProcesses[index]!;
      if (
        candidate.sessionId === target.sessionId
        && candidate.command === target.command
        && (!candidate.cwd || !target.cwd || candidate.cwd === target.cwd)
      ) boundToolCallId = candidate.toolCallId;
    }
    if (!boundToolCallId) return request;
    runBindings.set(target.runId, boundToolCallId);
    return { ...request, target: { ...target, id: boundToolCallId, toolCallId: boundToolCallId } };
  };
}

export function runtimeToolWindowRequest(event: RuntimeEvent): PawOsWindowRequest | null {
  const roomEvent = event.eventType === 'participant_activity';
  const payload = roomEvent ? record(event.payload.data) : event.payload;
  const sourceEventType = roomEvent ? text(event.payload.sourceEventType) : event.eventType;
  const backgroundEvent = sourceEventType.startsWith('background_job_');
  const job = backgroundEvent ? record(payload.job) : {};

  const toolName = text(payload.toolName).toLowerCase();
  const args = {
    ...record(payload.arguments),
    ...record(payload.args),
  };
  const toolCallId = text(payload.toolCallId);
  const sessionId = roomEvent ? text('sourceSessionId' in event ? event.sourceSessionId : '') : text('sessionId' in event ? event.sessionId : '');
  const roomId = roomEvent ? text('roomId' in event ? event.roomId : '') : '';
  const participantId = roomEvent ? text('participantId' in event ? event.participantId : '') : '';
  if (!sessionId) return null;

  if (processTools.has(toolName) || backgroundEvent) {
    const result = record(payload.result);
    const terminalId = firstDeepText([payload, args, result, job], new Set(['terminalId']));
    const runId = firstDeepText([payload, args, result, job], new Set(['runId', 'jobId']));
    const id = toolCallId || terminalId || runId;
    if (!id || (!backgroundEvent && !toolCallId)) return null;
    const command = firstText(args.command, payload.command, job.command) || toolName || '后台任务';
    const runStatus = processRunStatus(firstText(job.status, payload.status));
    const causalMetadata = record(job.causalMetadata);
    const roomLineage = record(job.roomLineage);
    const roomBound = causalMetadata.roomBound === true;
    const roomTurnId = firstText(roomLineage.rootId, causalMetadata.turnId);
    const exitCode = finiteNumber(job.exitCode);
    return {
      appId: 'terminal',
      background: true,
      target: {
        kind: 'process-terminal',
        id,
        title: command.length > 72 ? `${command.slice(0, 69)}…` : command,
        sessionId,
        toolCallId: toolCallId || id,
        ...(roomId ? { roomId } : {}),
        ...(participantId ? { participantId } : {}),
        ...(runId ? { runId } : {}),
        ...(terminalId ? { terminalId } : {}),
        command,
        ...(firstText(args.cwd, payload.cwd, job.cwd) ? { cwd: firstText(args.cwd, payload.cwd, job.cwd) } : {}),
        ...(runStatus ? { runStatus } : {}),
        ...(backgroundEvent ? { roomBound } : {}),
        ...(backgroundEvent && roomBound && roomTurnId ? { roomTurnId } : {}),
        ...(exitCode !== undefined ? { exitCode } : {}),
      },
    };
  }

  if (browserTools.has(toolName)) {
    const targetId = firstDeepText([payload, args], new Set(['targetId']));
    const tabId = positiveInteger(payload.tabId) || positiveInteger(args.tabId);
    const commandId = firstText(payload.commandId, args.commandId);
    const id = targetId || toolCallId || commandId;
    if (!id) return null;
    return {
      appId: 'browser',
      background: true,
      target: {
        kind: 'browser-target',
        id,
        title: 'Browser',
        sessionId,
        toolCallId,
        targetId,
        provisional: !targetId,
        ...(roomId ? { roomId } : {}),
        ...(participantId ? { participantId } : {}),
        ...(tabId ? { tabId } : {}),
        ...(commandId ? { commandId } : {}),
      },
    };
  }
  return null;
}

export function backgroundJobWindowRequest(
  job: AgentBackgroundJobV1,
  context: { roomId?: string; participantId?: string } = {},
): PawOsWindowRequest {
  const roomTurnId = firstText(job.roomLineage?.rootId, job.causalMetadata.turnId);
  return {
    appId: 'terminal',
    background: false,
    target: {
      kind: 'process-terminal',
      id: job.jobId,
      title: job.label || job.command || '后台任务',
      sessionId: job.sessionId,
      toolCallId: job.jobId,
      runId: job.jobId,
      command: job.command,
      cwd: job.cwd,
      runStatus: job.status,
      roomBound: job.causalMetadata.roomBound,
      ...(context.roomId ? { roomId: context.roomId } : {}),
      ...(context.participantId ? { participantId: context.participantId } : {}),
      ...(roomTurnId ? { roomTurnId } : {}),
      ...(job.exitCode !== null ? { exitCode: job.exitCode } : {}),
    },
  };
}

/**
 * Runtime events may describe a windowable surface without authorizing a new
 * visible window. Background process projections stay in the Session/Room
 * status surface until the user explicitly asks to inspect that exact run.
 * Browser targets remain visible because the PAW Browser is the shared human
 * and Agent execution surface for that authoritative targetId.
 */
export function shouldAutoOpenRuntimeToolWindow(request: PawOsWindowRequest): boolean {
  return request.target.kind === 'browser-target';
}

function firstDeepText(values: unknown[], keys: Set<string>): string {
  for (const value of values) {
    const found = deepText(value, keys);
    if (found) return found;
  }
  return '';
}

function deepText(value: unknown, keys: Set<string>, depth = 0): string {
  if (!value || typeof value !== 'object' || depth > 6) return '';
  const source = value as Record<string, unknown>;
  for (const [key, candidate] of Object.entries(source)) {
    if (keys.has(key) && text(candidate)) return text(candidate);
  }
  for (const candidate of Object.values(source)) {
    const found = deepText(candidate, keys, depth + 1);
    if (found) return found;
  }
  return '';
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function firstText(...values: unknown[]): string {
  return values.map(text).find(Boolean) ?? '';
}

function positiveInteger(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : undefined;
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function processRunStatus(value: string): Extract<PawOsWindowRequest['target'], { kind: 'process-terminal' }>['runStatus'] {
  return ['queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled', 'orphaned'].includes(value)
    ? value as Extract<PawOsWindowRequest['target'], { kind: 'process-terminal' }>['runStatus']
    : undefined;
}
