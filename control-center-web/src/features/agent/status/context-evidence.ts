/**
 * context-evidence — 装配阶段到具体捕获原文的共享映射，以及装配顺序。
 *
 * PF-CM-010：上下文检查的每个摘要节点都必须能打开真实内容，而不是停在
 * token 汇总条。Agent 轨迹（PawContextTrace）与上下文管线对话框
 * （ContextRuntimePanel）共用这份映射，保证两个入口对同一装配阶段给出
 * 同一份 debugContext 捕获证据，并按同一个权威顺序排列节点。
 */

import type { AgentContextTraceV1 } from '@/contracts/generated/agent-context-trace.v1';
import type {
  DebugContextRecord,
  DebugModelCall,
} from '@/features/context-debug/model';

/**
 * 装配顺序的权威来源是 contextRuntime 写入的 node.ordinal（1 起、单调递增），
 * createdAtMs 只在 ordinal 相同时决定先后。传输层可能重排数组，因此任何
 * 声称「按装配顺序」的视图都要先过这里，而不是直接用 trace.nodes 的下标。
 */
export function orderContextTraceNodes(
  nodes: AgentContextTraceV1['nodes'] | undefined,
): AgentContextTraceV1['nodes'] {
  return [...nodes ?? []].sort((left, right) => (
    left.ordinal - right.ordinal || left.createdAtMs - right.createdAtMs
  ));
}

export type AssemblyEvidenceValue = {
  label: string;
  value: string;
  kind: 'json' | 'text';
};

export function assemblyStageEvidence(
  stage: string,
  context: DebugContextRecord,
): AssemblyEvidenceValue | undefined {
  const normalized = stage.trim().toLowerCase();
  if (normalized === 'input' || normalized.includes('prompt')) {
    return { label: '本轮用户输入原文', value: context.prompt || '本轮未捕获用户输入。', kind: 'text' };
  }
  if (normalized === 'tools' || normalized.includes('tool')) {
    return { label: '本次模型调用收到的工具 Schema', value: formatEvidenceValue(modelToolSchemas(context)), kind: 'json' };
  }
  if (normalized.includes('message') || normalized.includes('context') || normalized === 'runtime_request') {
    return { label: '按 Provider 顺序装配的上下文消息', value: formatEvidenceValue(modelContextMessages(context)), kind: 'json' };
  }
  if (normalized === 'session' || normalized === 'system' || normalized === 'project') {
    return { label: '本次模型调用收到的系统指令', value: modelSystemPrompt(context) || '本轮未捕获系统指令。', kind: 'text' };
  }
  return undefined;
}

export function modelSystemPrompt(context: DebugContextRecord): string {
  const value = latestModelCall(context)?.providerContext.systemPrompt;
  return typeof value === 'string' ? value : context.systemPrompt;
}

export function modelToolSchemas(context: DebugContextRecord): unknown[] {
  const providerContext = latestModelCall(context)?.providerContext;
  return providerContext && Array.isArray(providerContext.tools) ? providerContext.tools : context.toolSchemas;
}

export function modelContextMessages(context: DebugContextRecord): unknown[] {
  const call = latestModelCall(context);
  if (!call) return [];
  return Array.isArray(call.providerContext.messages) ? call.providerContext.messages : call.contextMessages;
}

export function formatEvidenceValue(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value ?? null, null, 2) ?? String(value ?? '');
  } catch {
    return String(value ?? '');
  }
}

function latestModelCall(context: DebugContextRecord): DebugModelCall | undefined {
  return context.modelCalls.at(-1);
}
