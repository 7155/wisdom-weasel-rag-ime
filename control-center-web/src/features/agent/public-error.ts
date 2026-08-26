import { publicErrorText } from '@/features/overview/management-ui';

const unavailableModelPattern = /(?:model\s+["']?[^"']+["']?\s+is\s+not\s+supported|unsupported\s+model|model_not_supported|模型.*(?:不支持|不可用))/i;
const providerRequestFailurePattern = /(?:error\s+from\s+provider|upstream\s+request\s+failed|provider[_\s-](?:request|response|error)|模型服务.*(?:失败|异常))/i;
const networkInterruptionPattern = /(?:网络中断|fetch failed|websocket\s+(?:error|failure|closed)|network\s+(?:error|failure)|connection\s+(?:reset|closed|refused)|econn(?:reset|refused)|socket hang up|broken pipe|remote end closed)/i;
const nativeRouteMismatchPattern = /(?:route[_\s-]policy[_\s-]rejected|unexpected\s+(?:request\s+)?body\s+field|body\s+field\s+is\s+not\s+allowlisted|unknown\s+pathid)/i;
export type AgentCommandReceiptState =
  | 'pending'
  | 'accepted'
  | 'failed'
  | 'conflict';

export type AgentCommandReceiptRecoveryState =
  | 'in_flight'
  | 'unresolved';

export interface AgentCommandReceiptFailure {
  code:
    | 'AGENT_COMMAND_PENDING'
    | 'AGENT_COMMAND_FAILED'
    | 'AGENT_COMMAND_CONFLICT';
  state: AgentCommandReceiptState;
  clientMessageId: string;
  causeCode: string;
  recoveryState?: AgentCommandReceiptRecoveryState;
}

export function agentCommandReceiptFailure(
  value: unknown,
): AgentCommandReceiptFailure | undefined {
  const payload = errorPayload(value);
  if (!payload) return undefined;
  const code = payload.code;
  if (
    code !== 'AGENT_COMMAND_PENDING'
    && code !== 'AGENT_COMMAND_FAILED'
    && code !== 'AGENT_COMMAND_CONFLICT'
  ) {
    return undefined;
  }
  const receipt = record(payload.commandReceipt);
  if (!receipt) return undefined;
  const state = receipt?.state;
  if (
    state !== 'pending'
    && state !== 'accepted'
    && state !== 'failed'
    && state !== 'conflict'
  ) {
    return undefined;
  }
  const rawRecoveryState = receipt.recoveryState;
  const recoveryState = (
    rawRecoveryState === 'in_flight'
    || rawRecoveryState === 'unresolved'
  )
    ? rawRecoveryState
    : undefined;
  return {
    code,
    state,
    clientMessageId: stringValue(receipt.clientMessageId),
    causeCode: stringValue(receipt.causeCode),
    ...(recoveryState ? { recoveryState } : {}),
  };
}

export function isAgentCommandPending(value: unknown): boolean {
  return (
    agentCommandReceiptFailure(value)?.code
    === 'AGENT_COMMAND_PENDING'
  );
}

export function isUnresolvedAgentCommandPending(
  value: unknown,
): boolean {
  const failure = agentCommandReceiptFailure(value);
  return (
    failure?.code === 'AGENT_COMMAND_PENDING'
    && failure.recoveryState === 'unresolved'
  );
}

export function isAmbiguousAgentPromptFailure(value: unknown): boolean {
  if (agentCommandReceiptFailure(value)) return false;
  const responseStatus = transportResponseStatus(value);
  if (responseStatus !== undefined) {
    return responseStatus >= 500;
  }
  if (value instanceof DOMException) {
    return (
      value.name === 'AbortError'
      || value.name === 'NetworkError'
      || value.name === 'TimeoutError'
    );
  }
  // fetch rejects network failures as TypeError. Route validation has already
  // succeeded before the transport reaches fetch, so this is an unknown
  // delivery outcome rather than a model rejection.
  return value instanceof TypeError;
}

export function isAgentTurnConflict(value: unknown): boolean {
  return (
    agentCommandReceiptFailure(value)?.causeCode
    === 'AGENT_TURN_CONFLICT'
  );
}

export function isAgentSessionIdleFailure(value: unknown): boolean {
  return (
    agentCommandReceiptFailure(value)?.causeCode
    === 'SESSION_IDLE'
  );
}

export function publicAgentErrorText(
  value: unknown,
  fallback = '本轮没有完成，请重试或切换模型。',
): string {
  const receiptFailure = agentCommandReceiptFailure(value);
  if (receiptFailure?.code === 'AGENT_COMMAND_PENDING') {
    if (receiptFailure.recoveryState === 'unresolved') {
      return (
        '无法确认这条消息是否已执行。为避免重复执行，系统不会自动重试；'
        + '请刷新对话检查结果后，再决定是否发送新的请求。'
      );
    }
    return (
      '服务端仍在确认这条消息是否已接收。系统不会自动重试；'
      + '若后续收到确认事件，会在原消息上更新。'
    );
  }
  if (receiptFailure?.code === 'AGENT_COMMAND_CONFLICT') {
    return '发送标识与原请求不一致，请刷新对话后重新发送。';
  }
  const message = (value instanceof Error ? value.message : String(value ?? '')).trim();
  if (unavailableModelPattern.test(message)) {
    return '当前模型不可用，请切换模型后重试。';
  }
  if (isAgentNetworkInterruption(message)) {
    return '网络中断，模型未能生成最终回复。已完成的结果已保留，请继续或切换模型。';
  }
  if (providerRequestFailurePattern.test(message)) {
    return '模型服务请求失败，请重试或切换模型。';
  }
  if (nativeRouteMismatchPattern.test(message)) {
    return '控制中心组件版本不一致，请更新并重新打开控制中心。';
  }
  return publicErrorText(value, fallback);
}

export function isAgentNetworkInterruption(value: unknown): boolean {
  const message = (value instanceof Error ? value.message : String(value ?? '')).trim();
  return networkInterruptionPattern.test(message);
}

function errorPayload(value: unknown): Record<string, unknown> | undefined {
  return record(record(value)?.payload);
}

function transportResponseStatus(value: unknown): number | undefined {
  if (!(value instanceof Error)) return undefined;
  const status = record(value)?.status;
  return typeof status === 'number' && Number.isInteger(status)
    ? status
    : undefined;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return (
    typeof value === 'object'
    && value !== null
    && !Array.isArray(value)
  )
    ? value as Record<string, unknown>
    : undefined;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
