import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { PluginsFeature } from '.';

afterEach(cleanup);

describe('PluginsFeature', () => {
  it('opens a readable tool detail without exposing implementation fields', async () => {
    const user = userEvent.setup();
    renderPlugins();

    expect(await screen.findByRole('heading', { name: '插件与工具', level: 1 })).toBeInTheDocument();
    const list = await screen.findByRole('group', { name: '工具列表' });
    expect(within(list).getByRole('button', { name: /记忆与工具书/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('complementary', { name: '工具详情' })).toHaveTextContent('搜索内容');

    await user.click(within(list).getByRole('button', { name: /历史与配置/ }));
    const detail = screen.getByRole('complementary', { name: '工具详情' });
    expect(detail).toHaveTextContent('敏感操作会额外说明影响并再次确认');
    expect(detail).toHaveTextContent('恢复备份');

    expect(document.body).not.toHaveTextContent('ime_configuration');
    expect(document.body).not.toHaveTextContent('restore_apply');
    expect(document.body).not.toHaveTextContent('/api/private/tools');
    expect(document.body).not.toHaveTextContent('R3');
    expect(document.body).not.toHaveTextContent('assistant');
    expect(document.body).not.toHaveTextContent('coordinator');
  });

  it('filters tools by readable purpose, availability and supported mode', async () => {
    const user = userEvent.setup();
    renderPlugins();
    await screen.findByRole('heading', { name: '插件与工具', level: 1 });

    const search = await screen.findByRole('textbox', { name: '搜索' });
    await user.type(search, '语音');
    expect(screen.getByRole('button', { name: /语音输入/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /记忆与工具书/ })).not.toBeInTheDocument();

    await user.clear(search);
    await user.click(screen.getByRole('combobox', { name: '状态' }));
    await user.click(await screen.findByRole('option', { name: '需要处理' }));
    expect(screen.getByRole('button', { name: /工作区读取/ })).toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: '状态' }));
    await user.click(await screen.findByRole('option', { name: '全部状态' }));
    await user.click(screen.getByRole('radio', { name: '日常对话' }));
    expect(screen.queryByRole('button', { name: /工作区读取/ })).not.toBeInTheDocument();
  });

  it('does not advertise plugin writes before the audited lifecycle is connected', async () => {
    renderPlugins();
    expect(await screen.findByText('暂未开放')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '选择插件目录' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批准并应用' })).not.toBeInTheDocument();
  });
});

function renderPlugins() {
  const transport = new MockControlTransport({
    routes: {
      'agent.tools.list': { ok: true, items: toolItems() },
    },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<MemoryRouter initialEntries={['/plugins']}><TooltipProvider delayDuration={0}><ControlTransportProvider transport={transport}><QueryClientProvider client={client}><PluginsFeature /></QueryClientProvider></ControlTransportProvider></TooltipProvider></MemoryRouter>);
  return transport;
}

function toolItems() {
  return [
    tool({ id: 'ime_memory', displayName: '记忆与工具书', description: '搜索与维护长期记忆', domain: 'memory', riskLevel: 'R1', operations: ['search', 'maintenance_apply'], sessionModes: ['assistant', 'coordinator'] }),
    tool({ id: 'ime_configuration', displayName: '历史与配置', description: '查看历史并恢复便携备份', domain: 'configuration', riskLevel: 'R3', operations: ['history', 'restore_apply'], sessionModes: ['assistant', 'coordinator'], privatePath: '/api/private/tools' }),
    tool({ id: 'ime_voice', displayName: '语音输入', description: '查看语音状态与服务连接', domain: 'voice', riskLevel: 'R1', operations: ['provider_status'], sessionModes: ['assistant', 'coordinator'] }),
    tool({ id: 'workspace_read', displayName: '工作区读取', description: '读取已授权工作区中的文本', domain: 'workspace', riskLevel: 'R0', operations: ['read'], sessionModes: ['coordinator'], availability: 'offline' }),
  ];
}

function tool(overrides: Record<string, unknown>) {
  return { category: overrides.domain, operationRisks: {}, resultPresentation: 'tool_result', availability: 'online', version: '1', ...overrides };
}
