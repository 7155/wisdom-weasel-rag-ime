/**
 * 星空 v2 information feed — who is doing what, in user language.
 *
 * Pure projections over real Runtime records: subagent runs for a Session
 * sky, the Room focus projection for a Room sky. No invented events — every
 * feed row points back at a real body (`bodyId`) so tapping a row highlights
 * the matching planet or moon.
 */

import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import {
  isContractInvalid,
  subagentPresentationState,
  subagentStateLabel,
  subagentTemplateLabel,
} from '@/features/agent/status/subagent-presentation';
import { roomFocusStateLabel, type RoomFocusProjection } from '../room-focus-projection';
import { roomBodyMotion, subagentMotion, type StarfieldTone } from './starfield-motion';

export const STARFIELD_FEED_LIMIT = 8;

export interface StarfieldFeedItem {
  id: string;
  /** 0 means "right now" (no better timestamp exists). */
  atMs: number;
  actor: string;
  text: string;
  stateLabel: string;
  tone: StarfieldTone;
  /** Scene body to highlight when the row is tapped. */
  bodyId?: string;
}

/* ------------------------------------------------------------------ */
/* Session feed: the run graph, newest activity first                  */
/* ------------------------------------------------------------------ */

export function buildSessionFeed(
  runs: readonly AgentSubagentRunV1[],
  options: { busy: boolean; sessionTitle: string; nowMs: number },
): StarfieldFeedItem[] {
  const rows: StarfieldFeedItem[] = [];
  if (options.busy) {
    rows.push({
      id: 'session:busy',
      atMs: options.nowMs,
      actor: options.sessionTitle,
      text: '主星正在执行这一轮工作',
      stateLabel: '进行中',
      tone: 'working',
      bodyId: 'center',
    });
  }
  const ordered = [...runs].sort((left, right) => (
    right.updatedAtMs - left.updatedAtMs || left.id.localeCompare(right.id)
  ));
  for (const run of ordered) {
    const state = subagentPresentationState(run);
    rows.push({
      id: `run:${run.id}`,
      atMs: run.updatedAtMs,
      actor: subagentTemplateLabel(run.templateId),
      text: run.task || '未公开任务说明',
      stateLabel: subagentStateLabel(run),
      tone: subagentMotion(state, isContractInvalid(run)).tone,
      bodyId: run.id,
    });
  }
  return rows.slice(0, STARFIELD_FEED_LIMIT);
}

/* ------------------------------------------------------------------ */
/* Room feed: live partner actions first, then real handoffs           */
/* ------------------------------------------------------------------ */

const HANDOFF_STATE_LABEL: Record<RoomFocusProjection['handoffs'][number]['state'], string> = {
  offered: '已提出',
  dispatched: '交接中',
  completed: '已交付',
  failed: '交接失败',
  stopped: '已停止',
};

/** What needs the user first: a blocker outranks a review, then live work. */
const PARTNER_ROW_PRIORITY: Record<string, number> = {
  blocked: 0,
  failed: 0,
  review: 1,
  running: 2,
  waiting: 3,
};

export function buildRoomFeed(
  focus: RoomFocusProjection,
  options: { hosted: boolean } = { hosted: true },
): StarfieldFeedItem[] {
  const nameById = new Map(focus.partners.map((partner) => [partner.participantId, partner.celestialName]));
  const liveStates = new Set(Object.keys(PARTNER_ROW_PRIORITY));
  // The shared objective leads the feed: the sky is about the work, not the
  // scenery. It only points at Sol when a facilitator is actually hosting.
  const goalRow: StarfieldFeedItem = {
    id: 'room:goal',
    atMs: 0,
    actor: options.hosted ? `Sol · ${focus.goal.title}` : focus.goal.title,
    text: focus.goal.description.trim() || '这间 Room 的共同目标',
    stateLabel: roomFocusStateLabel(focus.goal.state),
    tone: roomBodyMotion(focus.goal.state).tone,
    ...(options.hosted ? { bodyId: 'center' } : {}),
  };
  const partnerRows = focus.partners
    .filter((partner) => liveStates.has(partner.state))
    .sort((left, right) => (
      (PARTNER_ROW_PRIORITY[left.state] ?? 9) - (PARTNER_ROW_PRIORITY[right.state] ?? 9)
      || left.celestialName.localeCompare(right.celestialName)
    ))
    .map((partner): StarfieldFeedItem => ({
      id: `partner:${partner.participantId}`,
      atMs: 0,
      actor: partner.celestialName,
      text: partner.currentAction,
      stateLabel: roomFocusStateLabel(partner.state),
      tone: roomBodyMotion(partner.state).tone,
      bodyId: partner.participantId,
    }));
  const handoffRows = [...focus.handoffs]
    .sort((left, right) => right.createdAtMs - left.createdAtMs || left.id.localeCompare(right.id))
    .map((handoff): StarfieldFeedItem => ({
      id: `handoff:${handoff.id}`,
      atMs: handoff.createdAtMs,
      actor: `${nameById.get(handoff.sourceParticipantId) ?? '协作方'} → ${nameById.get(handoff.targetParticipantId) ?? '协作方'}`,
      text: handoff.task || handoff.artifactOrContract || '工作项交接',
      stateLabel: HANDOFF_STATE_LABEL[handoff.state],
      tone: handoff.state === 'failed'
        ? 'attention'
        : handoff.state === 'completed'
          ? 'done'
          : handoff.state === 'stopped'
            ? 'paused'
            : 'working',
      bodyId: handoff.targetParticipantId,
    }));
  return [goalRow, ...partnerRows, ...handoffRows].slice(0, STARFIELD_FEED_LIMIT);
}

/* ------------------------------------------------------------------ */
/* Short, user-facing relative time                                    */
/* ------------------------------------------------------------------ */

export function feedTimeLabel(atMs: number, nowMs: number): string {
  if (atMs <= 0 || atMs > nowMs) return '现在';
  const deltaS = Math.floor((nowMs - atMs) / 1000);
  if (deltaS < 60) return '刚刚';
  if (deltaS < 3600) return `${Math.floor(deltaS / 60)} 分钟前`;
  if (deltaS < 86_400) return `${Math.floor(deltaS / 3600)} 小时前`;
  return `${Math.floor(deltaS / 86_400)} 天前`;
}
