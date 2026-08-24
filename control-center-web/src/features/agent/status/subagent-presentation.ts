import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';

export const UNVERIFIED_SUBAGENT_NOTICE = '该结果未经主持会话核验，不代表父任务验收通过';
export const INVALID_SUBAGENT_CONTRACT_NOTICE = '子 Agent 已返回，但交付合同无效；请修复输出或改派该节点';

export type SubagentPresentationState = AgentSubagentRunV1['state'] | 'returned' | 'contract_invalid';

export function subagentPresentationState(
  run: AgentSubagentRunV1,
): SubagentPresentationState {
  if (isContractInvalid(run)) return 'contract_invalid';
  return isUnverifiedReturn(run) ? 'returned' : run.state;
}

export function subagentStateLabel(
  run: AgentSubagentRunV1,
  mode: 'short' | 'result' | 'console' = 'short',
): string {
  if (isContractInvalid(run)) {
    return mode === 'short' ? '合同无效' : '已返回，合同无效';
  }
  if (isUnverifiedReturn(run)) {
    return mode === 'short' ? '已返回' : '结果已返回';
  }
  if (mode === 'console' && run.state === 'running') return '执行中';
  return ({
    queued: '排队中',
    running: '进行中',
    completed: '已完成',
    failed: '失败',
    aborted: '已停止',
    timed_out: '已超时',
  })[run.state];
}

export function isContractInvalid(run: AgentSubagentRunV1): boolean {
  const source = record(run);
  const result = record(run.result);
  const contract = record(source.contract);
  return text(contract.status) === 'invalid'
    || text(result.contractStatus) === 'invalid'
    || text(result.verificationStatus) === 'contract_invalid';
}

export function isUnverifiedReturn(run: AgentSubagentRunV1): boolean {
  if (run.state === 'queued' || run.state === 'running') return false;
  if (isContractInvalid(run)) return false;
  const source = record(run);
  const result = record(run.result);
  const deliveryStatus = text(source.deliveryStatus) || text(result.deliveryStatus);
  const verificationStatus = text(source.verificationStatus) || text(result.verificationStatus);
  return deliveryStatus === 'returned' || verificationStatus === 'unverified';
}

export function subagentTemplateLabel(value: AgentSubagentRunV1['templateId']): string {
  return ({
    researcher: '研究员',
    planner: '规划员',
    worker: '执行者',
    reviewer: '审阅者',
    delegate: '委派者',
  })[value];
}

export function subagentFailurePolicy(run: AgentSubagentRunV1): string {
  const result = record(run.result);
  const failureClass = text(result.failureClass);
  const retryPolicy = record(result.retryPolicy);
  if (!failureClass) return '';
  if (retryPolicy.automaticScheduled === true) {
    return '瞬时运行中断；已安排唯一一次有界自动重试，原尝试和已完成节点都会保留。';
  }
  if (failureClass === 'transient_runtime' && retryPolicy.automaticEligible === true) {
    return '瞬时运行中断；允许一次有界重试，不会重跑已完成节点。';
  }
  if (failureClass === 'contract_invalid' || isContractInvalid(run)) {
    return '交付合同无效；等待修复结构化输出或改派，不会自动重试。';
  }
  if (failureClass === 'tool_error') {
    return '工具或权限错误；等待修复工具输入、工作区边界或改派，不会自动重试。';
  }
  if (run.error.toLowerCase().includes('token budget exceeded')) {
    return 'Token 预算已耗尽；由上级缩小任务、提高预算或改派，不会自动重试。';
  }
  return '逻辑或验收未通过；等待显式修复或改派，不会自动重试。';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
