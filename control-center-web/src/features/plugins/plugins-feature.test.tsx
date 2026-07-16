import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { PluginsFeature } from '.';

afterEach(cleanup);

describe('PluginsFeature', () => {
  it('keeps the catalog full width until a tool is selected, then opens a closable detail', async () => {
    const user = userEvent.setup();
    renderPlugins();

    expect(await screen.findByRole('heading', { name: '插件与工具', level: 1 })).toBeInTheDocument();
    const list = await screen.findByRole('group', { name: '工具列表' });
    expect(within(list).getByRole('button', { name: /记忆与工具书/ })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByRole('complementary', { name: '工具详情' })).not.toBeInTheDocument();
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'false');

    await user.click(within(list).getByRole('button', { name: /历史与配置/ }));
    const detail = screen.getByRole('complementary', { name: '工具详情' });
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'true');
    expect(detail).toHaveTextContent('敏感操作会额外说明影响并再次确认');
    expect(detail).toHaveTextContent('恢复备份');

    expect(document.body).not.toHaveTextContent('ime_configuration');
    expect(document.body).not.toHaveTextContent('restore_apply');
    expect(document.body).not.toHaveTextContent('/api/private/tools');
    expect(document.body).not.toHaveTextContent('R3');
    expect(document.body).not.toHaveTextContent('assistant');
    expect(document.body).not.toHaveTextContent('coordinator');

    await user.click(screen.getByRole('button', { name: '关闭工具详情' }));
    expect(screen.queryByRole('complementary', { name: '工具详情' })).not.toBeInTheDocument();
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'false');
  });

  it('opens Agent with a bounded plugin-authoring skill request', async () => {
    const user = userEvent.setup();
    renderPlugins();
    await user.click(await screen.findByRole('button', { name: '交给 Agent 制作' }));

    expect(screen.getByTestId('test-location')).toHaveTextContent('/agent?draft=');
    expect(screen.getByTestId('test-location')).toHaveTextContent('%2Fskill%3Arag-ime-plugin-creator');
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

  it('validates, previews and explicitly applies a selected plugin directory', async () => {
    const user = userEvent.setup();
    const transport = renderPlugins();
    await user.click(await screen.findByRole('button', { name: '选择插件目录' }));
    expect(transport.filePickCalls).toEqual([{ purpose: 'plugin-source', selection: 'directory', maxFiles: 1 }]);
    await user.click(screen.getByRole('button', { name: '校验' }));
    expect(await screen.findByText('校验通过')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '生成安装预览' }));
    expect(await screen.findByText('等待你的批准')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '批准并应用' }));
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.extensions.apply'
      && typeof call.request.body === 'object'
      && call.request.body !== null
      && !Array.isArray(call.request.body)
      && call.request.body.confirmText === 'apply'
      && call.request.body.previewToken === 'preview-token'
    ))).toBe(true));
  });
});

function renderPlugins() {
  const transport = new MockControlTransport({
    pickedFiles: [{
      id: 'plugin-source-1',
      name: 'guided-plugin',
      mimeType: 'application/octet-stream',
      byteSize: 0,
      path: '/trusted/guided-plugin',
    }],
    routes: {
      'agent.tools.list': { ok: true, items: toolItems() },
      'agent.extensions.list': { ok: true, items: [] },
      'agent.extensions.proposals': { ok: true, items: [] },
      'agent.extensions.validate': {
        ok: true,
        validationToken: 'validation-token',
        extension: { id: 'guided-plugin', displayName: 'Guided Plugin', version: '1.0.0', totalBytes: 128 },
      },
      'agent.extensions.preview': {
        ok: true,
        previewToken: 'preview-token',
        payloadSha256: 'a'.repeat(64),
        summary: { action: 'install', pluginId: 'guided-plugin', displayName: 'Guided Plugin' },
      },
      'agent.extensions.apply': { ok: true, receipt: { receiptId: 'plugin:install:test' } },
    },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<MemoryRouter initialEntries={['/plugins']}><LocationProbe /><TooltipProvider delayDuration={0}><ControlTransportProvider transport={transport}><QueryClientProvider client={client}><PluginsFeature /></QueryClientProvider></ControlTransportProvider></TooltipProvider></MemoryRouter>);
  return transport;
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="test-location" hidden>{`${location.pathname}${location.search}`}</span>;
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
