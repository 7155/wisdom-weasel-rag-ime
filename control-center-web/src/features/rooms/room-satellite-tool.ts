import {
  publicToolResultView,
  type PublicToolResultView,
} from '@/features/agent/timeline/public-tool-result';
import { publicToolName } from '@/features/agent/tool-presentation';
import { roomPublicToolResultView } from './timeline/room-tool-presentation';

/**
 * Satellite windows must not show opaque "工具 agents" chips (PF-CM-012/013).
 * A Room tool activity is projected through the Agent App's public tool
 * disclosure — the same view the full Session renders — then sanitized by the
 * Room presentation rules. When the payload carries nothing beyond the tool
 * identity, `hasDetail` stays false and the caller keeps its plain-text seam.
 */
export interface RoomSatelliteToolContent {
  /** Human tool identity, e.g. `agents` → 「多人协作」. */
  label: string;
  /** Human operation, e.g. `delegate` → 「委派协作任务」; '' when unknown. */
  operation: string;
  /** Sanitized Agent disclosure for the expandable detail body. */
  view: PublicToolResultView;
  /** True when the disclosure holds real content worth expanding. */
  hasDetail: boolean;
}

/** Room-only tools the shared Agent name map does not know. Kept here so the
 * sibling `features/agent` branch stays untouched. */
const roomToolNames: Record<string, string> = {
  room_partner: '伙伴协作',
  tool_search: '搜索可用工具',
  skill_search: '搜索技能',
  agent_goal: '目标管理',
  workspace_job: '项目后台任务',
};

export function roomSatelliteToolContent(activity: {
  kind: string;
  status: string;
  payload: Record<string, unknown>;
}): RoomSatelliteToolContent | undefined {
  const payload = activity.payload;
  const toolId = text(payload.toolName) || text(payload.toolId) || text(payload.tool);
  if (!toolId) return undefined;
  /* Room events carry the op inside `arguments.op` (started) or
   * `result.operation` (finished); the Agent view reads `operation`. */
  const operation = text(payload.operation)
    || text(record(payload.result).operation)
    || text(record(payload.arguments).op);
  const view = roomPublicToolResultView(publicToolResultView({
    kind: text(payload.sourceEventType) || activity.kind,
    status: toolViewStatus(activity.status),
    payload: operation && !text(payload.operation) ? { ...payload, operation } : payload,
  }));
  const operationLabel = view.fields.find((field) => field.id === 'operation')?.value ?? '';
  const facts = view.fields.filter((field) => field.id !== 'status');
  return {
    label: view.toolLabel !== '工具操作'
      ? view.toolLabel
      : roomToolNames[toolId.toLowerCase()] ?? publicToolName(toolId),
    operation: operationLabel === '受控操作' ? '' : operationLabel,
    view,
    hasDetail: Boolean(
      facts.length
      || view.request.length
      || view.resultItems.length
      || view.output?.text
      || view.error,
    ),
  };
}

/** One readable line for a satellite tool row: the real operation when the
 * Runtime declared one, otherwise the tool identity with its run state. */
export function roomSatelliteToolMessage(content: RoomSatelliteToolContent, status: string): string {
  const active = ['queued', 'running', 'waiting', 'pending'].includes(status);
  if (content.operation) {
    if (active) return `正在${content.operation}`;
    if (status === 'failed') return `${content.operation} · 未成功`;
    if (['aborted', 'cancelled', 'stopped'].includes(status)) return `${content.operation} · 已停止`;
    return `${content.operation} · 已完成`;
  }
  if (active) return `正在使用「${content.label}」`;
  if (status === 'failed') return `「${content.label}」执行失败`;
  if (['aborted', 'cancelled', 'stopped'].includes(status)) return `「${content.label}」已停止`;
  return `「${content.label}」已返回`;
}

function toolViewStatus(status: string): 'running' | 'waiting' | 'completed' | 'failed' | 'aborted' {
  if (['queued', 'running', 'streaming', 'pending', 'claimed'].includes(status)) return 'running';
  if (status === 'waiting') return 'waiting';
  if (['failed', 'timed_out', 'orphaned'].includes(status)) return 'failed';
  if (['aborted', 'cancelled', 'stopped'].includes(status)) return 'aborted';
  return 'completed';
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
