export type RetrievalMetric = {
  id: 'ndcg' | 'mrr' | 'recall';
  label: string;
  baseline: number;
  candidate: number;
};

export const retrievalMetrics: readonly RetrievalMetric[] = [
  { id: 'ndcg', label: 'nDCG@10', baseline: 0.612801, candidate: 0.887203 },
  { id: 'mrr', label: 'MRR', baseline: 0.604167, candidate: 0.867188 },
  { id: 'recall', label: 'Recall@10', baseline: 0.671875, candidate: 0.955357 },
] as const;

export const cloudOpsComparison = {
  baseline: {
    ca: 1,
    jra: 0.8333333333333334,
    top3Jra: 0.8333333333333334,
    toolCalls: 98,
    elapsedMs: 1_356_582,
  },
  candidate: {
    ca: 0.8333333333333334,
    jra: 0.8333333333333334,
    top3Jra: 1,
    toolCalls: 189,
    elapsedMs: 996_035,
  },
} as const;

export const traceDefects = [
  {
    id: 'RAG-IFACE-001',
    problem: '评测 runner 仍调用已经移除的 room_skill_policy 接口。',
    change: '改接当前有效的 RAG Skill 与 runner 契约，不再依赖消失的接口。',
    effect: 'Validation 能真正启动；接口漂移会被测试直接拦住。',
  },
  {
    id: 'RAG-ATTEMPT-001',
    problem: '中断后的回答试验缺少权威 attempt、Session、预算和 orphan 生命周期。',
    change: '加入 append-only attempt、checkpoint、预算、孤儿恢复与一次性门禁。',
    effect: '失败不会被重试覆盖，恢复后的结果也不能冒充原始尝试。',
  },
  {
    id: 'RAG-EVIDENCE-001',
    problem: '回答评估把 token 重合或“出现引用”误当成事实证据支持。',
    change: '改为 host-private 的事实 → 来源 → chunk → 原文绑定，并分开计算可回答引用与拒答。',
    effect: '系统暴露出 2/9 的真实逐事实引用覆盖，而不是被“有引用”虚高。',
  },
  {
    id: 'PI-CODEX-WIRE-001',
    problem: 'Pi Codex 请求带入 Provider 不支持的 max_output_tokens 字段。',
    change: '从 Codex 请求线移除不支持字段，并锁定回归测试。',
    effect: 'Provider 不再在最终回答前因协议字段失败。',
  },
  {
    id: 'TRACE-SKILL-ENV-001',
    problem: 'Trace Skill 没有固定报告 envelope 和 confidence 枚举。',
    change: '固定顶层字段、additionalProperties=false 与字符串 confidence 枚举。',
    effect: '诊断报告不再因为多字段或数字 confidence 被后端拒绝。',
  },
  {
    id: 'CLOUDOPS-TRANSPORT-001',
    problem: '第一版私有 Tool transport 无法在受限评测环境中运行。',
    change: '改为 capability-token 约束的 loopback transport，并限制公开观察字段。',
    effect: '三批真实 Session 可以在同一冻结套件上执行 98 次 Tool 调用。',
  },
  {
    id: 'EVAL-MODEL-ID-001',
    problem: '请求的评测模型没有与 Session 实际模型身份 fail-closed 对齐。',
    change: '把 provider、model、thinking 与 runtime manifest 一起冻结并校验。',
    effect: '“说是 Sol、实际跑了别的模型”的结果不能进入正式评分。',
  },
  {
    id: 'CLOUDOPS-HASH-001',
    problem: '盲索引与读取链使用了不同 JSON 序列化，导致相同值 hash 不同。',
    change: '索引、读取与收据统一使用 canonical JSON 序列化。',
    effect: '相同观察值产生同一 hash，证据可以跨环节核对。',
  },
] as const;

export const cacheTurns = [
  { label: '冷启动', inputTokens: 10_647, cacheReadTokens: 0, reduction: null },
  { label: '稳定前缀 · 热轮 1', inputTokens: 941, cacheReadTokens: 9_728, reduction: 1 - 941 / 10_647 },
  { label: '稳定前缀 · 热轮 2', inputTokens: 963, cacheReadTokens: 9_728, reduction: 1 - 963 / 10_647 },
  { label: '改变前缀 · 对照', inputTokens: 10_650, cacheReadTokens: 0, reduction: null },
] as const;

export const evidenceFiles = [
  ['RAG 检索调优', 'enterprise-rag-validation-20260831.v1.json'],
  ['逐事实引用门禁', 'enterprise-rag-answer-evidence-validation-reject-20260901.v1.json'],
  ['Trace 缺陷账本', 'trace-defect-ledger.v1.json'],
  ['CloudOps 基线', 'cloudops-agent-validation-20260901.v1.json'],
  ['CloudOps 搜索候选 Reject', 'cloudops-evidence-search-validation-reject-20260901.v1.json'],
  ['掌柜问数沙盒', 'zhanggui-extension-app-sandbox-20260901.v1.json'],
  ['稳定前缀缓存 canary', 'pi-context-cache-20260830.v1.json'],
] as const;

export function relativeImprovement(baseline: number, candidate: number): number {
  return (candidate - baseline) / baseline;
}

export function percent(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function signedPercent(value: number): string {
  if (value === 0) return '0.00%';
  return `${value > 0 ? '+' : '−'}${percent(Math.abs(value))}`;
}

export function decimal(value: number): string {
  return value.toFixed(4);
}

export function metricTransition(baseline: number, candidate: number): string {
  return `${decimal(baseline)} → ${decimal(candidate)}`;
}

export function duration(valueMs: number): string {
  const totalSeconds = valueMs / 1_000;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds - minutes * 60;
  return `${minutes}分 ${seconds.toFixed(1)}秒`;
}
