/// <reference types="node" />

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import {
  agentSnapshotFromResponse,
  applyAgentSnapshot,
  createAgentProjection,
  type AgentActivityProjection,
} from '@/contracts/agent-reducer';
import { FxActivityStack, resetActivityDisclosureOverrides } from './ActivitySummary';
import { publicToolResultView } from './public-tool-result';

/**
 * Conversation depth over the real Minecraft harness (PF-CM-007/008/010):
 * every collaboration receipt a satellite or Session row displays must expand
 * to the concrete payload the durable event carries — the posted Room
 * message, the delegated TaskBrief, the goal audit, the WorkDocument
 * authority receipt, and the written file body — instead of an empty card
 * labelled with a raw tool id such as “工具 agents”.
 */
const root = resolve(process.cwd(), 'e2e/fixtures/minecraft-harness-20260825');

const activitiesByRole = new Map<string, AgentActivityProjection[]>();

function harnessActivities(role: string): AgentActivityProjection[] {
  const cached = activitiesByRole.get(role);
  if (cached) return cached;
  const raw = JSON.parse(
    readFileSync(resolve(root, `sessions/${role}.snapshot.json`), 'utf8'),
  ) as Record<string, unknown>;
  const state = applyAgentSnapshot(
    createAgentProjection(String(raw.sessionId)),
    agentSnapshotFromResponse(raw),
  );
  const activities = state.activityOrder
    .map((id) => state.activitiesById[id])
    .filter((activity): activity is AgentActivityProjection => Boolean(activity));
  activitiesByRole.set(role, activities);
  return activities;
}

function harnessToolActivity(
  role: string,
  toolName: string,
  predicate: (activity: AgentActivityProjection) => boolean = () => true,
): AgentActivityProjection {
  const match = harnessActivities(role).find((activity) => (
    activity.kind.startsWith('tool_')
    && (activity.payload.toolName === toolName || activity.payload.toolId === toolName)
    && predicate(activity)
  ));
  expect(match, `harness ${role} should contain a ${toolName} activity`).toBeDefined();
  return match!;
}

function activityOp(activity: AgentActivityProjection): string {
  const args = activity.payload.args as Record<string, unknown> | undefined;
  return typeof args?.op === 'string' ? args.op : '';
}

afterEach(() => {
  cleanup();
  resetActivityDisclosureOverrides();
});

describe('harness collaboration receipts expand to concrete payloads', () => {
  it('projects a room_partner post as the real message that was sent', () => {
    const activity = harnessToolActivity('coordinator', 'room_partner');
    const view = publicToolResultView(activity);

    expect(view.toolLabel).toBe('伙伴协作');
    expect(view.operation).toBe('post');
    expect(view.fields.find((field) => field.id === 'operation')?.value).toBe('发布协作消息');
    expect(view.outputLabel).toBe('发送内容');
    expect(view.output?.text).toContain('当前 Root 已完成并闭环');
    expect(view.fields.find((field) => field.id === 'published')?.value).toBe('已发布到 Room');
    expect(view.request.find((field) => field.id === 'kind')?.value).toBe('结果通报');
  });

  it('projects a room_partner peer_list as the real intercom messages', () => {
    const activity = harnessToolActivity(
      'ui-specialist',
      'room_partner',
      (candidate) => activityOp(candidate) === 'peer_list',
    );
    const view = publicToolResultView(activity);

    expect(view.summary).toMatch(/伙伴消息 \d+ 条/u);
    expect(view.preview?.kind).toBe('collaboration');
    expect(view.preview?.items.length).toBeGreaterThan(0);
    expect(view.preview?.items.some((item) => item.text.includes('已通过验收'))).toBe(true);
    expect(view.preview?.items.some((item) => item.label?.includes('已送达'))).toBe(true);
  });

  it('projects an agents delegation as the real TaskBrief and acceptance criteria', () => {
    const activity = harnessToolActivity(
      'core-specialist',
      'agents',
      (candidate) => activityOp(candidate) === 'delegate',
    );
    const view = publicToolResultView(activity);

    expect(view.toolLabel).toBe('子 Agent');
    expect(view.outputLabel).toBe('任务简报');
    expect(view.output?.text).toContain('Bounded registration repair');
    expect(view.preview?.kind).toBe('delegation');
    expect(view.preview?.items.some((item) => (
      item.label === '验收标准' && item.text.includes('No files under src/**')
    ))).toBe(true);
    expect(view.fields.find((field) => field.id === 'batchState')?.value).toBe('已完成');
    expect(view.request.find((field) => field.id === 'agent')?.value).toBe('worker');
  });

  it('projects an agent_goal completion as the real objective and evidence audit', () => {
    const activity = harnessToolActivity(
      'coordinator',
      'agent_goal',
      (candidate) => activityOp(candidate) === 'complete',
    );
    const view = publicToolResultView(activity);

    expect(view.fields.find((field) => field.id === 'operation')?.value).toBe('标记目标达成');
    expect(view.preview?.kind).toBe('goal');
    expect(view.preview?.description).toContain('方块生存游戏');
    expect(view.preview?.items.some((item) => item.label === '成功标准')).toBe(true);
    expect(view.preview?.items.some((item) => (
      item.label === '测试证据' && item.text.includes('npm test')
    ))).toBe(true);
    expect(view.fields.find((field) => field.id === 'goalStatus')?.value).toBe('已达成');
  });

  it('projects a work_documents receipt as the real authority state', () => {
    const activity = harnessToolActivity('coordinator', 'work_documents');
    const view = publicToolResultView(activity);

    expect(view.fields.find((field) => field.id === 'operation')?.value).toBe('查询文档授权');
    expect(view.request.find((field) => field.id === 'authorityKind')?.value).toBe('会话目标');
    expect(view.fields.find((field) => field.id === 'documentState')?.value).toBe('已完成');
    expect(view.fields.find((field) => field.id === 'authorityRevision')?.value).toBe('第 17 版');
  });

  it('projects a write receipt as the real written body, not an empty change card', () => {
    const activity = harnessToolActivity('coordinator', 'write');
    const view = publicToolResultView(activity);

    expect(view.target).toContain('workdoc_');
    expect(view.outputLabel).toBe('写入内容');
    expect(view.output?.text).toContain('方块生存游戏 Root 工作文档');
    expect(view.change?.additions).toBe(35);
  });
});

describe('FX rows over harness activities', () => {
  it('labels rows with readable names and glyphs, and expands to the sent payload', () => {
    const post = harnessToolActivity('coordinator', 'room_partner');
    const delegation = harnessToolActivity(
      'core-specialist',
      'agents',
      (candidate) => activityOp(candidate) === 'delegate',
    );
    const write = harnessToolActivity('coordinator', 'write');
    const { container } = render(
      <FxActivityStack activities={[post, delegation, write]} />,
    );

    const rows = Array.from(container.querySelectorAll<HTMLButtonElement>('.paw-activity'));
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      const accessibleName = row.getAttribute('aria-label') ?? '';
      expect(accessibleName).not.toMatch(/\broom_partner\b/u);
      expect(accessibleName).not.toMatch(/工具 agents/u);
    }
    expect(screen.getByRole('button', { name: /伙伴协作/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /子 Agent/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /写入文件/ })).toBeInTheDocument();

    const glyphs = Array.from(container.querySelectorAll('.paw-activity__glyph'));
    expect(glyphs).toHaveLength(3);
    expect(glyphs[0]).toHaveAttribute('data-kind', 'collaboration');
    expect(glyphs[1]).toHaveAttribute('data-kind', 'delegation');
    expect(glyphs.every((glyph) => glyph.querySelector('svg'))).toBe(true);

    // Collapsed by default: the concrete payload appears only after a click.
    expect(screen.queryByText(/当前 Root 已完成并闭环/)).not.toBeInTheDocument();
    const postRow = screen.getByRole('button', { name: /伙伴协作/ });
    fireEvent.click(postRow);
    expect(postRow).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/当前 Root 已完成并闭环/)).toBeInTheDocument();
    expect(screen.getByText('发送内容')).toBeInTheDocument();
  });
});
