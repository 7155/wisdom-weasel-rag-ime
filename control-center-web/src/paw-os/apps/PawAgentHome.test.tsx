import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { SessionSummary } from '@/features/agent/types';
import type { RoomSummary } from '@/features/rooms/room-types';
import { MockControlTransport } from '@/test/mock-transport';
import agentNextCss from '../styles/paw-os-agent-next.css?raw';
import { PawAgentHome } from './PawAgentHome';

afterEach(cleanup);

describe('PAWOS Agent Home 首屏合同', () => {
  it('completes the new-work composer and 继续工作 on one fixed surface without a galaxy landing section', async () => {
    const { container } = renderHome();

    expect(await screen.findByRole('heading', { name: '交给 Agent 一件事。' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '描述你想完成的工作' })).toBeInTheDocument();

    const recent = (screen.getByRole('heading', { name: '继续工作' })).parentElement!;
    expect(within(recent).getByRole('button', { name: /发布检查/ })).toBeInTheDocument();
    expect(within(recent).getByRole('button', { name: /迁移作战室/ })).toBeInTheDocument();

    // 首屏之外没有第二段落地页内容：Room 星系板块已被砍掉。
    expect(screen.queryByText('Room 星系')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Room 星系' })).not.toBeInTheDocument();

    // 继续工作挂在弹性滚动区上，是首屏内唯一的内部滚动面。
    expect(container.querySelector('.an-home-recents .an-recent-list')).not.toBeNull();
  });

  it('owns its viewport like a desktop app: the page never scrolls, only the recent list does', () => {
    // 表面本身钉死在窗口高度上，禁止整页往下翻。
    expect(agentNextCss).toMatch(/\.an-home\s*\{[^}]*height:\s*100%;[^}]*overflow:\s*hidden;/s);
    // 继续工作列表是唯一的内部滚动区。
    expect(agentNextCss).toMatch(/\.an-home-recents \.an-recent-list\s*\{[^}]*overflow:\s*hidden auto;/s);
    // 页脚是钉在底部的状态条，不是文章末尾。
    expect(agentNextCss).toMatch(/\.an-home-foot\s*\{[^}]*margin-top:\s*auto;/s);
    // 固定表面上 Composer 靠近上沿，锚定菜单必须向下展开，避免被表面上缘裁掉。
    expect(agentNextCss).toMatch(/\.an-menu\s*\{[^}]*top:\s*calc\(100% \+ 8px\);/s);
  });
});

function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const transport = new MockControlTransport({
    routes: {
      'configuration.settings': {
        ok: true,
        settings: { agent: { defaults: { modelReference: 'inherit', thinkingLevel: 'high', executionMode: 'per_action' } } },
        runtimeConfig: { runtimeRevision: 7 },
      },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <ControlTransportProvider transport={transport}>
        <TooltipProvider>
          <PawAgentHome
            defaultModel="gpt/gpt-5.6-luna"
            models={[]}
            personas={[]}
            projectRoots={['/work/paw']}
            rooms={[room()]}
            sessions={[session()]}
            onCreated={vi.fn()}
            onOpenRoom={vi.fn()}
            onOpenSession={vi.fn()}
          />
        </TooltipProvider>
      </ControlTransportProvider>
    </QueryClientProvider>,
  );
}

function session(): SessionSummary {
  return {
    id: 'session-1',
    title: '发布检查',
    mode: 'coordinator',
    status: 'idle',
    roleId: '',
    roleVersion: '',
    roleBookRevisionId: '',
    updatedAtMs: 2,
    workspaceRoots: ['/work/paw'],
    lastMessagePreview: '检查构建结果',
    executionMode: 'per_action',
  } as SessionSummary;
}

function room(): RoomSummary {
  return {
    id: 'room-1',
    title: '迁移作战室',
    status: 'active',
    description: '并行迁移与审查',
    routingPolicy: 'parallel',
    moderatorParticipantId: 'p1',
    updatedAtMs: 3,
    workspaceRoots: ['/work/paw'],
    participants: [
      { id: 'p1', sessionId: 's1', roleId: 'builder', roleVersion: '1', displayName: '构建者', status: 'active', ordinal: 0 },
      { id: 'p2', sessionId: 's2', roleId: 'reviewer', roleVersion: '1', displayName: '审阅者', status: 'active', ordinal: 1 },
    ],
  } as RoomSummary;
}
