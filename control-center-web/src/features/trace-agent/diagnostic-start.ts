import { agentCommandReceiptFailure } from '@/features/agent/public-error';
import type { ControlTransport } from '@/platform/transport';

export interface TraceDiagnosticPrompt {
  sessionId: string;
  clientMessageId: string;
  message: string;
  retryOfClientMessageId?: string;
  state: 'ready' | 'unknown' | 'rejected' | 'failed' | 'cancelled' | 'accepted';
}

const STORAGE_KEY = 'paw:trace-diagnostic-start:v1';
export interface TraceDiagnosticStartContext<Report> { report: Report; prompt: TraceDiagnosticPrompt }

export function readTraceDiagnosticStart<Report extends { sessionId: string; reportId: string; targets: unknown[]; primaryTarget: unknown; target: unknown }>(): TraceDiagnosticStartContext<Report> | null {
  try {
    const saved = record(JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null'));
    const report = record(saved.report);
    const prompt = record(saved.prompt);
    if (typeof report.reportId !== 'string' || !report.reportId || typeof report.sessionId !== 'string'
      || !Array.isArray(report.targets) || !report.targets.length || !report.primaryTarget || !report.target
      || prompt.sessionId !== report.sessionId || typeof prompt.clientMessageId !== 'string' || !prompt.clientMessageId
      || typeof prompt.message !== 'string' || !prompt.message || !['ready', 'unknown', 'rejected', 'failed', 'cancelled'].includes(String(prompt.state))) return null;
    return saved as unknown as TraceDiagnosticStartContext<Report>;
  } catch { return null; }
}

export function saveTraceDiagnosticStart<Report>(context: TraceDiagnosticStartContext<Report>): void {
  try {
    if (context.prompt.state === 'accepted') sessionStorage.removeItem(STORAGE_KEY);
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(context));
  } catch { /* The mounted workbench still retains the exact attempt. */ }
}

export function clearTraceDiagnosticStart(): void {
  try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* Storage can be unavailable in an embedded host. */ }
}

/** Only exact admission evidence settles an uncertain send; absence never does. */
export function traceDiagnosticPromptAccepted(snapshot: unknown, sessionId: string, clientMessageId: string): boolean {
  const source = record(snapshot);
  if (source.sessionId !== sessionId) return false;
  const ownsIdentity = (value: Record<string, unknown>) => value.clientMessageId === clientMessageId
    && (!value.sessionId || value.sessionId === sessionId);
  const isAcceptedMessage = (value: Record<string, unknown>) => value.role === 'user' && ownsIdentity(value)
    && !(typeof value.id === 'string' && value.id.startsWith('local:'));
  if (rows(source.items ?? source.messages).some(isAcceptedMessage)) return true;
  const queue = record(source.messageQueue);
  if ([...rows(queue.steering), ...rows(queue.followUp)].some(ownsIdentity)) return true;
  return rows(source.liveEvents ?? source.events).some((event) => {
    if (event.sessionId && event.sessionId !== sessionId) return false;
    const payload = record(event.payload);
    const receipt = record(payload.commandReceipt);
    return isAcceptedMessage(record(payload.message))
      || (receipt.state === 'accepted' && ownsIdentity(receipt));
  });
}

export async function deliverTraceDiagnosticPrompt(
  attempt: TraceDiagnosticPrompt,
  transport: Pick<ControlTransport, 'request'>,
  onChange: (next: TraceDiagnosticPrompt) => void,
): Promise<void> {
  let current = attempt;
  const update = (next: TraceDiagnosticPrompt) => { current = next; onChange(next); };
  if (current.state === 'accepted') return;
  if (current.state !== 'ready') {
    let snapshot: unknown;
    try {
      snapshot = await transport.request({ pathId: 'agent.session.snapshot', params: { sessionId: current.sessionId } });
    } catch {
      throw new Error('暂时无法核对原诊断消息是否已接收；报告与诊断对话已保留，请稍后继续核对。');
    }
    if (record(snapshot).sessionId !== current.sessionId || record(snapshot).ok === false) {
      throw new Error('返回的快照无法核对原诊断对话；报告与诊断消息标识已保留。');
    }
    if (traceDiagnosticPromptAccepted(snapshot, current.sessionId, current.clientMessageId)) {
      update({ ...current, state: 'accepted' });
      return;
    }
    if (current.state === 'unknown' || current.state === 'cancelled') {
      throw new Error('原诊断消息仍未获得接收确认。查无记录不能证明未执行；请继续核对原诊断对话。');
    }
    if (current.state === 'failed') {
      // A durable failed receipt cannot be replayed. This explicit retry is
      // its single successor, retained before sending in case the ACK is lost.
      update({ ...current, clientMessageId: `trace-agent:${crypto.randomUUID()}`, retryOfClientMessageId: current.clientMessageId, state: 'ready' });
    }
  }
  update({ ...current, state: 'unknown' });
  let response: unknown;
  try {
    response = await transport.request({
      pathId: 'agent.session.prompt', params: { sessionId: current.sessionId },
      body: { message: current.message, clientMessageId: current.clientMessageId, ...(current.retryOfClientMessageId ? { retryOfClientMessageId: current.retryOfClientMessageId } : {}), delivery: 'prompt' },
    });
  } catch (error) {
    const receipt = agentCommandReceiptFailure(error);
    const status = record(error).status;
    const state = receipt
      ? receipt.clientMessageId === current.clientMessageId && receipt.code === 'AGENT_COMMAND_FAILED' && receipt.state === 'failed' ? 'failed' : 'unknown'
      : typeof status === 'number' && status >= 400 && status < 500 && status !== 408 ? 'rejected' : 'unknown';
    update({ ...current, state });
    throw error;
  }
  const result = record(response);
  if (result.accepted === false || result.cancelled === true || result.admissionCancelled === true) {
    update({ ...current, state: 'cancelled' });
    throw new Error('诊断请求已取消；原报告与诊断对话已保留。');
  }
  if (result.ok === false || (result.clientMessageId && result.clientMessageId !== current.clientMessageId)) {
    throw new Error('返回结果未能确认原诊断消息已接收，请核对启动状态。');
  }
  update({ ...current, state: 'accepted' });
}

function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function rows(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.map(record) : []; }
