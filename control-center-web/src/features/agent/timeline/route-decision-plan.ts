import { publicToolOutputText } from './public-tool-result';

/**
 * Concrete dispatch-plan projection for a Room `route_decision` payload
 * (`rag-ime.room-route-decision.v1`). "Earth · 分派 route_decision" used to be
 * an empty label; this view keeps the real plan expandable: who was selected,
 * why (signals and scores per candidate), which phase/wave the dispatch
 * belongs to, and how wide the parallel fan-out is.
 *
 * Pure and reusable: the Session conversation renders it for any activity
 * carrying the schema, and the Room lane (`cursor/room-gravity-flow-4494`)
 * consumes the same view for its gravity/dispatch surfaces.
 */

export interface RouteCandidateView {
  id: string;
  name: string;
  /** Bounded 0..1 weight straight from the routing payload — never invented. */
  score: number;
  selected: boolean;
  signalLabels: string[];
}

export interface RouteDecisionPlanView {
  policyLabel: string;
  reasonLabel: string;
  targetName: string;
  phaseName: string;
  parallelLabel: string;
  workItemLabel: string;
  summary: string;
  candidates: RouteCandidateView[];
}

const routePolicyLabels: Record<string, string> = {
  parallel: '并行分派',
  single: '单人分派',
  broadcast: '广播',
  round_robin: '轮流',
};

const routeSignalLabels: Record<string, string> = {
  facilitator: '主持人',
  partner_delegate: '伙伴委派',
  explicit_invite: '点名邀请',
  mention: '被提及',
  round_robin: '轮流',
  fallback: '兜底',
  capability: '能力匹配',
  workload: '负载均衡',
};

const CANDIDATE_LIMIT = 12;

export function routeDecisionPlanView(value: unknown): RouteDecisionPlanView | null {
  const outer = record(value);
  const inner = record(outer.payload);
  const source = text(inner.schemaVersion) === 'rag-ime.room-route-decision.v1'
    ? inner
    : text(outer.schemaVersion) === 'rag-ime.room-route-decision.v1'
      ? outer
      : null;
  if (!source) return null;

  const targetName = boundedLine(text(source.targetDisplayName), 80);
  const policyLabel = routePolicyLabels[text(source.routingPolicy)] ?? '分派';
  const reasonLabel = routeSignalLabels[text(source.reason)] ?? '';
  const phaseName = boundedLine(text(source.phaseName), 120);
  const parallelIndex = finiteNumber(source.parallelIndex);
  const parallelSize = finiteNumber(source.parallelSize);
  const parallelLabel = parallelSize !== undefined && parallelSize > 1
    ? `并行 ${(parallelIndex ?? 0) + 1} / ${parallelSize}`
    : '';
  const workItemTail = idTail(text(source.workItemId));
  const workItemState = text(source.workItemState);
  const workItemLabel = workItemTail
    ? `任务 #${workItemTail}${workItemState === 'active' ? ' · 进行中' : workItemState === 'settled' ? ' · 已结算' : ''}`
    : '';

  const selectedIds = new Set(
    (Array.isArray(source.selectedParticipantIds) ? source.selectedParticipantIds : [])
      .map((id) => text(id))
      .filter(Boolean),
  );
  const targetId = text(source.targetParticipantId);
  if (targetId) selectedIds.add(targetId);
  const candidates = (Array.isArray(source.candidates) ? source.candidates : [])
    .slice(0, CANDIDATE_LIMIT)
    .map((candidateValue, index): RouteCandidateView => {
      const candidate = record(candidateValue);
      const id = text(candidate.participantId);
      const rawScore = typeof candidate.score === 'number' && Number.isFinite(candidate.score)
        ? candidate.score
        : 0;
      return {
        id: id || `candidate:${index}`,
        name: boundedLine(text(candidate.displayName), 80) || `伙伴 ${index + 1}`,
        score: Math.min(1, Math.max(0, rawScore)),
        selected: Boolean(id && selectedIds.has(id)),
        signalLabels: (Array.isArray(candidate.signals) ? candidate.signals : [])
          .map((signal) => routeSignalLabels[text(signal)] ?? '')
          .filter(Boolean)
          .slice(0, 4),
      };
    });

  const summaryParts = [
    targetName ? `分派给 ${targetName}` : policyLabel,
    reasonLabel,
    parallelLabel,
    phaseName,
  ].filter(Boolean);
  return {
    policyLabel,
    reasonLabel,
    targetName,
    phaseName,
    parallelLabel,
    workItemLabel,
    summary: summaryParts.join(' · '),
    candidates,
  };
}

/** Last 4 characters of an aliased runtime id — enough to correlate rows on
 * screen without printing an identifier wall. */
function idTail(value: string): string {
  const match = /([0-9a-z]{4})[^0-9a-z]*$/iu.exec(value);
  return match?.[1] ?? '';
}

function boundedLine(value: string, limit: number): string {
  const masked = publicToolOutputText(value).replace(/\s+/gu, ' ').trim();
  if (masked.length <= limit) return masked;
  return `${masked.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
