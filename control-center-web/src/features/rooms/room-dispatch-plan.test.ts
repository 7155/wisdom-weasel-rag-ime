/// <reference types="node" />

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { createRoomProjection, reduceRoomEvents } from '@/contracts/room-reducer';
import { parseRoomEvent } from '@/contracts/validators';
import {
  roomDispatchPlan,
  roomDispatchPlanText,
  roomDispatchReasonLabel,
  roomDispatchSignalLabel,
  roomDispatchSummaryIsGeneric,
} from './room-dispatch-plan';

describe('roomDispatchPlan', () => {
  it('does not invent a plan from a bare routing target or a target-less policy', () => {
    expect(roomDispatchPlan({ targetParticipantId: 'p-a' })).toBeUndefined();
    expect(roomDispatchPlan({ routingPolicy: 'parallel' })).toBeUndefined();
  });

  it('projects the full routing verdict with selected candidates and the parallel lane', () => {
    const plan = roomDispatchPlan({
      routingPolicy: 'parallel',
      selectedParticipantIds: ['p-b'],
      targetParticipantId: 'p-b',
      targetDisplayName: 'Agent 2',
      reason: 'partner_delegate',
      child: true,
      phaseName: '实现',
      parallelIndex: 1,
      parallelSize: 3,
      dispatchId: 'room-child:1',
      candidates: [
        { participantId: 'p-a', displayName: 'Agent 1', score: 0, signals: [] },
        { participantId: 'p-b', displayName: 'Agent 2', score: 1, signals: ['explicit_invite'] },
      ],
    });

    expect(plan).toMatchObject({
      policy: 'parallel',
      reason: 'partner_delegate',
      targetParticipantIds: ['p-b'],
      child: true,
      phaseName: '实现',
      parallelIndex: 1,
      parallelSize: 3,
      dispatchId: 'room-child:1',
    });
    expect(plan?.candidates.map((candidate) => [candidate.participantId, candidate.selected])).toEqual([
      ['p-a', false],
      ['p-b', true],
    ]);
    expect(roomDispatchPlanText(plan!, (participantId) => (participantId === 'p-b' ? 'Mars' : '')))
      .toBe('并行分派 → Mars（伙伴委派） · 阶段「实现」 · 并行第 2/3 路');
  });

  it('keeps human-authored reasons, translates known machine reasons, hides unknown tokens', () => {
    expect(roomDispatchReasonLabel('facilitator')).toBe('主持人接手');
    expect(roomDispatchReasonLabel('需要浏览器权限的伙伴')).toBe('需要浏览器权限的伙伴');
    expect(roomDispatchReasonLabel('some_internal_code')).toBe('');
    expect(roomDispatchSignalLabel('keyword')).toBe('关键词匹配');
    expect(roomDispatchSignalLabel('weird_machine_signal')).toBe('路由信号');
    expect(roomDispatchSummaryIsGeneric('已确认本轮分工')).toBe(true);
    expect(roomDispatchSummaryIsGeneric('把依赖投影交给 Mars 实现')).toBe(false);
  });

  it('projects every reduced Minecraft harness route_decision into a legible plan', () => {
    const root = resolve(process.cwd(), 'e2e/fixtures/minecraft-harness-20260825');
    const events = readFileSync(resolve(root, 'room/history.jsonl'), 'utf8')
      .trim().split('\n').map((line) => parseRoomEvent(JSON.parse(line)));
    const projection = reduceRoomEvents(createRoomProjection(events[0]!.roomId), events);
    const dispatches = projection.activityOrder
      .map((activityId) => projection.activitiesById[activityId])
      .filter((activity) => activity?.kind === 'route_decision');

    expect(dispatches.length).toBeGreaterThan(0);
    const plans = dispatches.map((activity) => roomDispatchPlan(activity!.payload));
    for (const plan of plans) {
      expect(plan).toBeDefined();
      expect(plan!.candidates.length).toBeGreaterThan(0);
      expect(plan!.candidates.some((candidate) => candidate.selected)).toBe(true);
      const text = roomDispatchPlanText(plan!, () => '');
      // Legible: names the policy and a human target, exposes no machine ids.
      expect(text).toMatch(/^并行分派 → Agent \d/u);
      expect(text).not.toContain('participant:');
      expect(text).not.toContain('parallel');
    }
    // The real harness run carries both wave metadata and delegated children.
    expect(plans.some((plan) => plan?.parallelSize !== undefined)).toBe(true);
    expect(plans.some((plan) => plan?.child && plan.reason === 'partner_delegate')).toBe(true);
  });
});
