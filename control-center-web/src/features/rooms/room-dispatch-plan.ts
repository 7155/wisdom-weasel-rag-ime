/**
 * Dispatch plan projection (PF-CM-012/013).
 *
 * A `route_decision` event carries the real routing verdict: policy, reason,
 * scored candidates, wave phase and the parallel lane the target now owns.
 * The paper UI reduced all of that to a dead "Earth · 分派 / 已确认本轮分工"
 * label. This module projects the payload into a human plan — how the work
 * was assigned, to whom, against which alternatives — without inventing any
 * fact that is not in the event.
 */

export interface RoomDispatchCandidate {
  participantId: string;
  displayName: string;
  score?: number;
  signals: string[];
  selected: boolean;
}

export interface RoomDispatchPlan {
  policy: string;
  reason: string;
  targetParticipantIds: string[];
  targetDisplayName?: string;
  dispatchId?: string;
  child: boolean;
  phaseName?: string;
  /** 0-based lane index inside the wave, only when the Runtime reported one. */
  parallelIndex?: number;
  parallelSize?: number;
  workItemId?: string;
  workItemState?: string;
  candidates: RoomDispatchCandidate[];
}

const policyLabels: Record<string, string> = {
  parallel: '并行分派',
  single: '单一指派',
  sequential: '顺序指派',
  round_robin: '轮流指派',
  broadcast: '广播全员',
  manual: '手动指派',
};

const reasonLabels: Record<string, string> = {
  facilitator: '主持人接手',
  partner_delegate: '伙伴委派',
  explicit_invite: '点名邀请',
  mention: '@ 点名',
  moderator: '主持人指定',
  user: '用户指定',
  fallback: '兜底路由',
};

const signalLabels: Record<string, string> = {
  facilitator: '主持人',
  explicit_invite: '点名邀请',
  mention: '@ 提及',
  keyword: '关键词匹配',
  recent_speaker: '近期发言',
  round_robin: '轮转',
};

/** Reducer fallbacks that carry no routing information of their own. */
const genericDispatchSummaries = new Set([
  '已确认本轮分工',
  '分派状态已更新',
  '协作进度已更新',
  '路由已更新',
]);

/**
 * Build the plan only when the payload really explains *how* the assignment
 * happened. A bare `targetParticipantId` is not a plan — those events keep
 * their original one-line rendering.
 */
export function roomDispatchPlan(payload: Record<string, unknown>): RoomDispatchPlan | undefined {
  const candidates = candidateRows(payload.candidates);
  const targets = [...new Set([
    ...stringArray(payload.selectedParticipantIds),
    ...(stringValue(payload.targetParticipantId) ? [stringValue(payload.targetParticipantId)] : []),
  ])];
  if (!targets.length) return undefined;
  const policy = stringValue(payload.routingPolicy);
  const reason = stringValue(payload.reason);
  const phaseName = stringValue(payload.phaseName);
  const parallelSize = finiteNumber(payload.parallelSize);
  const explained = Boolean(
    policy
    || candidates.length
    || phaseName
    || parallelSize !== undefined
    || roomDispatchReasonLabel(reason),
  );
  if (!explained) return undefined;
  const parallelIndex = finiteNumber(payload.parallelIndex);
  const workItemState = stringValue(payload.workItemState);
  return {
    policy,
    reason,
    targetParticipantIds: targets,
    ...(stringValue(payload.targetDisplayName) ? { targetDisplayName: stringValue(payload.targetDisplayName) } : {}),
    ...(stringValue(payload.dispatchId) ? { dispatchId: stringValue(payload.dispatchId) } : {}),
    child: payload.child === true,
    ...(phaseName ? { phaseName } : {}),
    ...(parallelIndex !== undefined ? { parallelIndex } : {}),
    ...(parallelSize !== undefined ? { parallelSize } : {}),
    ...(stringValue(payload.workItemId) ? { workItemId: stringValue(payload.workItemId) } : {}),
    ...(workItemState ? { workItemState } : {}),
    candidates: candidates.map((candidate) => ({
      ...candidate,
      selected: targets.includes(candidate.participantId),
    })),
  };
}

export function roomDispatchPolicyLabel(policy: string): string {
  return policyLabels[policy.trim().toLowerCase()] ?? '定向分派';
}

/** Known machine reasons become readable copy; unknown machine tokens are
 * dropped rather than shown raw; human-authored reasons pass through. */
export function roomDispatchReasonLabel(reason: string): string {
  const normalized = reason.trim();
  if (!normalized) return '';
  const mapped = reasonLabels[normalized.toLowerCase()];
  if (mapped) return mapped;
  return /^[a-z0-9][a-z0-9_.:-]*$/iu.test(normalized) ? '' : normalized;
}

export function roomDispatchSignalLabel(signal: string): string {
  const normalized = signal.trim();
  if (!normalized) return '';
  const mapped = signalLabels[normalized.toLowerCase()];
  if (mapped) return mapped;
  return /^[a-z0-9][a-z0-9_.:-]*$/iu.test(normalized) ? '路由信号' : normalized;
}

/** One readable sentence answering "how was this assigned": policy, target,
 * reason, wave phase and parallel lane, in real payload order of authority. */
export function roomDispatchPlanText(
  plan: RoomDispatchPlan,
  nameOf: (participantId: string) => string,
): string {
  const targets = plan.targetParticipantIds
    .map((participantId) => nameOf(participantId) || plan.targetDisplayName || '伙伴');
  const reasonLabel = roomDispatchReasonLabel(plan.reason);
  const parts = [
    `${roomDispatchPolicyLabel(plan.policy)} → ${[...new Set(targets)].join('、')}${reasonLabel ? `（${reasonLabel}）` : ''}`,
  ];
  if (plan.phaseName) parts.push(`阶段「${plan.phaseName}」`);
  if (plan.parallelSize !== undefined && plan.parallelSize > 1) {
    parts.push(plan.parallelIndex !== undefined
      ? `并行第 ${plan.parallelIndex + 1}/${plan.parallelSize} 路`
      : `并行 ${plan.parallelSize} 路`);
  }
  return parts.join(' · ');
}

/** True when the reducer produced only a stock phrase, so the plan text is
 * strictly more informative than the stored summary. */
export function roomDispatchSummaryIsGeneric(summary: string): boolean {
  const normalized = summary.trim();
  return !normalized || genericDispatchSummaries.has(normalized);
}

function candidateRows(value: unknown): Omit<RoomDispatchCandidate, 'selected'>[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) return [];
    const source = item as Record<string, unknown>;
    const participantId = stringValue(source.participantId);
    if (!participantId) return [];
    const score = finiteNumber(source.score);
    return [{
      participantId,
      displayName: stringValue(source.displayName),
      ...(score !== undefined ? { score } : {}),
      signals: stringArray(source.signals),
    }];
  });
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
    : [];
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}
