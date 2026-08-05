import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { createPreviewTransport } from '@/app/preview-control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlPathId } from '@/platform/routes';
import type { ControlTransport } from '@/platform/transport';
import { MockControlTransport, type MockRouteHandler } from '@/test/mock-transport';
import { PluginsFeature } from '.';

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
});

describe('PluginsFeature', () => {
  it('keeps a stable catalog split while opening and closing capability details', async () => {
    const user = userEvent.setup();
    renderPlugins();

    expect(await screen.findByRole('heading', { name: '工具、技能与扩展', level: 1 })).toBeInTheDocument();
    const list = await screen.findByRole('group', { name: '能力列表' });
    expect(within(list).getByRole('button', { name: /记忆与工具书/ })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('complementary', { name: '能力详情占位' })).toBeInTheDocument();
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'false');

    await user.click(within(list).getByRole('button', { name: /历史与配置/ }));
    const detail = screen.getByRole('complementary', { name: '能力详情' });
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'true');
    expect(detail).toHaveTextContent('受禁区保护');
    expect(detail).toHaveTextContent('native_approval');
    expect(detail).toHaveTextContent('恢复备份');
    expect(detail).toHaveTextContent('执行授权');
    expect(detail).toHaveTextContent('当前披露');
    expect(within(detail).getByRole('combobox', { name: '历史与配置的所有对话默认披露' })).toBeEnabled();

    expect(document.body).not.toHaveTextContent('configuration');
    expect(document.body).not.toHaveTextContent('restore_apply');
    expect(document.body).not.toHaveTextContent('/api/private/tools');
    expect(document.body).not.toHaveTextContent('R3');
    expect(document.body).not.toHaveTextContent('assistant');
    expect(document.body).not.toHaveTextContent('coordinator');

    await user.click(screen.getByRole('button', { name: '关闭能力详情' }));
    expect(screen.queryByRole('complementary', { name: '能力详情' })).not.toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: '能力详情占位' })).toBeInTheDocument();
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'false');
  });

  it('shows fixed base tools without persistent disclosure controls', async () => {
    const user = userEvent.setup();
    const fixedAsk = tool({
      id: 'ask',
      displayName: 'Ask',
      description: '向用户提出仍需其决定的结构化选择',
      domain: 'planning',
      riskLevel: 'R0',
      operations: ['ask'],
      sessionModes: ['assistant', 'coordinator'],
      alwaysAvailable: true,
    });
    const transport = renderPlugins({
      'agent.tools.list': capabilityCatalog([fixedAsk]),
    });

    await user.click(await screen.findByRole('button', { name: /Ask/ }));
    const detail = screen.getByRole('complementary', { name: '能力详情' });
    expect(within(detail).getByRole('region', { name: '固定能力策略' })).toHaveTextContent('固定加载');
    expect(within(detail).queryByRole('combobox', { name: 'Ask的所有对话默认披露' })).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.configuration.update')).toBe(false);
  });

  it('projects historical coding adapters into four tool rows without changing skills or extensions', async () => {
    renderPlugins({
      'agent.tools.list': capabilityCatalog([
        tool({
          id: 'workspace_read',
          displayName: '工作区读取',
          description: '旧工作区适配器',
          domain: 'workspace',
          riskLevel: 'R0',
          operations: ['read_range'],
          effectiveOperations: ['read_range'],
          sessionModes: ['coordinator'],
          enabled: false,
        }),
        tool({
          id: 'read_file',
          displayName: 'Read file',
          description: '旧 Provider 别名',
          domain: 'workspace',
          riskLevel: 'R0',
          operations: ['read'],
          effectiveOperations: ['read'],
          sessionModes: ['coordinator'],
          enabled: true,
        }),
        tool({
          id: 'workspace_search',
          displayName: '工作区搜索',
          description: '旧搜索适配器',
          domain: 'workspace',
          riskLevel: 'R0',
          operations: ['search'],
          effectiveOperations: ['search'],
          sessionModes: ['coordinator'],
        }),
        tool({
          id: 'workspace_list',
          displayName: '工作区浏览',
          description: '旧浏览适配器',
          domain: 'workspace',
          riskLevel: 'R0',
          operations: ['list'],
          effectiveOperations: ['list'],
          sessionModes: ['coordinator'],
        }),
        tool({
          id: 'workspace_lsp',
          displayName: '代码智能',
          description: '旧 LSP 适配器',
          domain: 'workspace',
          riskLevel: 'R0',
          operations: ['symbols'],
          effectiveOperations: ['symbols'],
          sessionModes: ['coordinator'],
        }),
        tool({
          id: 'workspace_edit',
          displayName: '工作区修改',
          description: '旧编辑适配器',
          domain: 'workspace',
          riskLevel: 'R1',
          operations: ['replace'],
          effectiveOperations: ['replace'],
          sessionModes: ['coordinator'],
        }),
        tool({
          id: 'apply_patch',
          displayName: 'Apply patch',
          description: '旧补丁适配器',
          domain: 'workspace',
          riskLevel: 'R1',
          operations: ['patch'],
          effectiveOperations: ['patch'],
          sessionModes: ['coordinator'],
        }),
        tool({
          id: 'workspace_write',
          displayName: '工作区写入',
          description: '旧写入适配器',
          domain: 'workspace',
          riskLevel: 'R1',
          operations: ['create'],
          effectiveOperations: ['create'],
          sessionModes: ['coordinator'],
        }),
        tool({
          id: 'write_file',
          displayName: 'Write file',
          description: '旧 Provider 写入别名',
          domain: 'workspace',
          riskLevel: 'R1',
          operations: ['write'],
          effectiveOperations: ['write'],
          sessionModes: ['coordinator'],
        }),
        tool({
          id: 'workspace_shell',
          displayName: '受控命令',
          description: '旧命令适配器',
          domain: 'workspace',
          riskLevel: 'R2',
          operations: ['run'],
          effectiveOperations: ['run'],
          sessionModes: ['coordinator'],
        }),
        tool({
          id: 'workspace_job',
          displayName: '后台任务',
          description: '旧后台任务适配器',
          domain: 'workspace',
          riskLevel: 'R2',
          operations: ['poll'],
          effectiveOperations: ['poll'],
          sessionModes: ['coordinator'],
        }),
        capability('debugging', 'skill', '调试技能'),
        capability('browser-extension', 'extension', '浏览器扩展'),
      ]),
    });

    const list = await screen.findByRole('group', { name: '能力列表' });
    expect(within(list).getAllByRole('button')).toHaveLength(6);
    for (const name of ['读取文件', '编辑文件', '写入文件', '运行命令', '调试技能', '浏览器扩展']) {
      expect(within(list).getByRole('button', { name: new RegExp(name) })).toBeInTheDocument();
    }
    expect(list).not.toHaveTextContent('工作区读取');
    expect(list).not.toHaveTextContent('工作区搜索');
    expect(list).not.toHaveTextContent('工作区浏览');
    expect(list).not.toHaveTextContent('代码智能');
    expect(list).not.toHaveTextContent('后台任务');
    expect(list).not.toHaveTextContent('Read file');
  });

  it('reports an installed backend catalog version mismatch and never renders legacy items as controls', async () => {
    const user = userEvent.setup();
    const transport = renderPlugins({
      'agent.tools.list': {
        schemaVersion: 'rag-ime.control-tool-list.v1',
        ok: true,
        items: [{ id: 'legacy-tool', displayName: '旧工具' }],
      },
    });

    expect(await screen.findByText(/后端返回 rag-ime\.control-tool-list\.v1/)).toBeVisible();
    expect(screen.queryByRole('button', { name: /旧工具/ })).not.toBeInTheDocument();
    const before = transport.requests.filter((call) => call.request.pathId === 'agent.tools.list').length;
    await user.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(transport.requests.filter((call) => call.request.pathId === 'agent.tools.list')).toHaveLength(before + 1));
  });

  it('opens Agent with a review-only plugin-authoring skill request', async () => {
    const user = userEvent.setup();
    renderPlugins();
    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await user.click(await screen.findByRole('button', { name: '准备扩展草稿' }));

    expect(screen.getByTestId('test-location')).toHaveTextContent('/agent?draft=');
    expect(screen.getByTestId('test-location')).toHaveTextContent('%2Fskill%3Aplugin-creator');
    expect(screen.getByTestId('test-location')).toHaveTextContent('%E4%B8%8D%E8%A6%81%E5%A3%B0%E7%A7%B0%E5%AE%83%E5%B7%B2%E8%8E%B7%E5%87%86%E6%89%A7%E8%A1%8C');
  });

  it('filters capabilities by readable purpose, availability and kind', async () => {
    const user = userEvent.setup();
    renderPlugins();
    await screen.findByRole('heading', { name: '工具、技能与扩展', level: 1 });

    const search = await screen.findByRole('textbox', { name: '搜索' });
    await user.type(search, '语音');
    expect(screen.getByRole('button', { name: /语音输入/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /记忆与工具书/ })).not.toBeInTheDocument();

    await user.clear(search);
    await user.click(screen.getByRole('combobox', { name: '状态' }));
    await user.click(await screen.findByRole('option', { name: '需要处理' }));
    expect(screen.getByRole('button', { name: /读取文件/ })).toBeInTheDocument();
    await user.click(screen.getByRole('combobox', { name: '状态' }));
    await user.click(await screen.findByRole('option', { name: '全部状态' }));
    await user.click(screen.getByRole('radio', { name: '技能' }));
    expect(screen.queryByRole('button', { name: /读取文件/ })).not.toBeInTheDocument();
  });

  it('re-reads the backend catalog and defaults after connectivity returns', async () => {
    let catalogReads = 0;
    let defaultReads = 0;
    renderPlugins({
      'agent.tools.list': () => {
        catalogReads += 1;
        return capabilityCatalog(toolItems());
      },
      'agent.configuration.get': () => {
        defaultReads += 1;
        return capabilityDefaults();
      },
    });

    await waitFor(() => {
      expect(catalogReads).toBe(1);
      expect(defaultReads).toBe(1);
    });
    act(() => onlineManager.setOnline(false));
    act(() => onlineManager.setOnline(true));
    await waitFor(() => {
      expect(catalogReads).toBe(2);
      expect(defaultReads).toBe(2);
    });
  });

  it('persists global disclosure defaults without changing authorization', async () => {
    const user = userEvent.setup();
    const transport = renderPlugins();
    await user.click(await screen.findByRole('button', { name: /记忆与工具书/ }));
    const preference = screen.getByRole('combobox', {
      name: '记忆与工具书的所有对话默认披露',
    });
    await user.click(preference);
    await user.click(await screen.findByRole('option', { name: '不向伙伴披露' }));

    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.configuration.update'
      && typeof call.request.body === 'object'
      && call.request.body !== null
      && !Array.isArray(call.request.body)
      && JSON.stringify(call.request.body).includes('"tool:memory":"disabled"')
    ))).toBe(true));
    expect(screen.getByRole('complementary', { name: '能力详情' })).toHaveTextContent('不适用');
    expect(await screen.findByText('默认设置已保存')).toBeVisible();
    expect(screen.getByText(/后台已确认保存所有对话默认/)).toBeVisible();
  });

  it('loads and persists a project default from an Agent Session context', async () => {
    const user = userEvent.setup();
    const projectId = `workspace-${'b'.repeat(64)}`;
    const transport = renderPlugins({
      'agent.tools.list': capabilityCatalog(toolItems(), {
        supported: true,
        identityKind: 'workspace_scope_sha256',
        projectId,
        reason: 'session_workspace_scope',
      }, 'session-project'),
      'agent.configuration.get': capabilityDefaults({
        [projectId]: { 'tool:memory': 'enabled' },
      }),
    }, '/plugins?sessionId=session-project');

    await user.click(await screen.findByRole('button', { name: /记忆与工具书/ }));
    const projectPreference = screen.getByRole('combobox', {
      name: '记忆与工具书的当前项目默认披露',
    });
    expect(projectPreference).toHaveTextContent('向伙伴披露');
    expect(screen.getByRole('region', { name: '能力披露优先级' })).toHaveTextContent('由当前授权工作区控制 · workspace-bb…bbbb');
    await user.click(projectPreference);
    await user.click(await screen.findByRole('option', { name: '不向伙伴披露' }));

    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.configuration.update'
      && JSON.stringify(call.request.body).includes(`"${projectId}"`)
      && JSON.stringify(call.request.body).includes('"tool:memory":"disabled"')
    ))).toBe(true));
    expect(transport.requests.find((call) => call.request.pathId === 'agent.tools.list')?.request.query)
      .toEqual({ sessionId: 'session-project' });
    expect(await screen.findByText('默认设置已保存')).toBeVisible();
    expect(screen.getByText(/后台已确认保存当前项目默认/)).toBeVisible();
  });

  it('keeps the failed persistent change owner-scoped and retries the same preference', async () => {
    let attempts = 0;
    const user = userEvent.setup();
    const transport = renderPlugins({
      'agent.configuration.update': () => {
        attempts += 1;
        if (attempts === 1) throw new Error('配置修订冲突');
        return { ok: true };
      },
    });

    await user.click(await screen.findByRole('button', { name: /记忆与工具书/ }));
    await user.click(screen.getByRole('combobox', { name: '记忆与工具书的所有对话默认披露' }));
    await user.click(await screen.findByRole('option', { name: '不向伙伴披露' }));
    expect(await screen.findByText('默认设置没有保存')).toBeVisible();
    expect(screen.getAllByText('配置修订冲突').length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole('button', { name: '重试这次更改' })[0]!);
    await waitFor(() => expect(attempts).toBe(2));
    expect(transport.requests.filter((call) => call.request.pathId === 'agent.configuration.update')).toHaveLength(2);
    expect(await screen.findByText('默认设置已保存')).toBeVisible();
  });

  it('validates, previews and explicitly applies a first-party catalog plugin', async () => {
    const user = userEvent.setup();
    const transport = renderPlugins();
    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await user.click(await screen.findByRole('button', { name: '查看安装内容' }));
    expect(transport.filePickCalls).toEqual([]);
    expect(await screen.findByText('等待你的批准')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '确认更改' }));
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.extensions.apply'
      && typeof call.request.body === 'object'
      && call.request.body !== null
      && !Array.isArray(call.request.body)
      && call.request.body.confirmText === 'apply'
      && call.request.body.previewToken === 'preview-token'
    ))).toBe(true));
  });

  it('shows governed versions and lifecycle policies, and can toggle a hook', async () => {
    const user = userEvent.setup();
    const transport = renderPlugins();
    expect(screen.queryByText('Session Review')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    expect(await screen.findByText('Session Review')).toBeInTheDocument();
    expect(screen.getByText('v1.1.0 · 2 个版本')).toBeInTheDocument();
    expect(screen.getByText('为下一轮准备记忆建议')).toBeInTheDocument();
    await user.click(screen.getByRole('switch', { name: '任务完成：已启用' }));
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.lifecycleHooks.update'
      && typeof call.request.body === 'object'
      && call.request.body !== null
      && !Array.isArray(call.request.body)
      && call.request.body.eventType === 'project_complete'
      && call.request.body.enabled === false
    ))).toBe(true));
  });

  it('does not disguise plugin query failures as empty installed or proposal states', async () => {
    const user = userEvent.setup();
    renderPlugins({
      'agent.extensions.catalog': () => {
        throw new Error('catalog unavailable');
      },
    });

    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    expect(await screen.findByText('读取失败')).toBeVisible();
    expect(screen.getByText('暂时无法读取这部分内容，请稍后重试。')).toBeVisible();
    expect(screen.queryByText('还没有受管插件')).not.toBeInTheDocument();
  });

  it('refreshes catalog, installed versions, proposals and lifecycle together', async () => {
    const user = userEvent.setup();
    const transport = renderPlugins();
    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await screen.findByText('Session Review');
    const tracked: ControlPathId[] = [
      'agent.tools.list',
      'agent.extensions.list',
      'agent.extensions.catalog',
      'agent.extensions.proposals',
      'agent.lifecycleHooks.get',
    ];
    const before = new Map(tracked.map((pathId) => [
      pathId,
      transport.requests.filter((call) => call.request.pathId === pathId).length,
    ]));

    await user.click(screen.getByRole('button', { name: '刷新' }));

    await waitFor(() => {
      for (const pathId of tracked) {
        expect(transport.requests.filter((call) => call.request.pathId === pathId).length)
          .toBeGreaterThan(before.get(pathId) ?? 0);
      }
    });
  });

  it('surfaces lifecycle hook mutation failures without hiding the current policy', async () => {
    const user = userEvent.setup();
    renderPlugins({
      'agent.lifecycleHooks.update': () => {
        throw new Error('Hook 更新被拒绝');
      },
    });

    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await user.click(await screen.findByRole('switch', { name: '任务完成：已启用' }));
    expect(await screen.findByText('自动整理设置没有保存')).toBeVisible();
    expect(screen.getByText('Hook 更新被拒绝')).toBeVisible();
    expect(screen.getByText('为下一轮准备记忆建议')).toBeVisible();
  });

  it('shows the reviewed plugin version, capabilities and enabled state before apply', async () => {
    const user = userEvent.setup();
    renderPlugins({
      'agent.extensions.proposals': {
        ok: true,
        items: [{
          proposalId: 'proposal-disable',
          previewToken: 'preview-disable',
          payloadSha256: 'b'.repeat(64),
          summary: {
            action: 'disable',
            pluginId: 'session-review',
            displayName: 'Session Review',
            version: '1.1.0',
            permissions: ['session.read'],
            expectedEnabled: true,
            expectedActiveDigest: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
          },
        }],
      },
    });

    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await user.click(await screen.findByRole('button', { name: /Session Review/ }));
    expect(screen.getByText('v1.1.0 · 需要的权限：session.read · 当前已启用 · 校验标记 0123456789ab…cdef')).toBeVisible();
  });
  it('shows installed display names and disables rollback after the visible version transition', async () => {
    const user = userEvent.setup();
    const transport = createPreviewTransport();
    renderPluginsWithTransport(transport);

    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await screen.findByText('Timeline Inspector');

    await user.click(screen.getByRole('button', { name: '停用' }));
    expect(await screen.findByText('停用插件：Timeline Inspector')).toBeVisible();
    expect(screen.queryByText('停用插件：timeline-inspector')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '取消' }));

    const rollback = screen.getByRole('button', { name: '恢复上一版本' });
    expect(rollback).toBeEnabled();
    await user.click(rollback);
    expect(await screen.findByText('回滚插件：Timeline Inspector')).toBeVisible();
    expect(screen.getByText('v0.9.0 · 无额外权限')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '确认更改' }));

    expect(await screen.findByText('v0.9.0')).toBeVisible();
    expect(screen.getByRole('button', { name: '恢复上一版本' })).toBeDisabled();
  });

});

function renderPlugins(
  overrides: Partial<Record<ControlPathId, MockRouteHandler>> = {},
  initialEntry = '/plugins',
) {
  const transport = new MockControlTransport({
    pickedFiles: [{
      id: 'plugin-source-1',
      name: 'guided-plugin',
      mimeType: 'application/octet-stream',
      byteSize: 0,
      path: '/trusted/guided-plugin',
    }],
    routes: {
      'agent.tools.list': capabilityCatalog(toolItems()),
      'agent.configuration.get': capabilityDefaults(),
      'agent.configuration.update': { ok: true },
      'agent.extensions.list': { ok: true, items: [] },
      'agent.extensions.catalog': {
        ok: true,
        items: [{
          id: 'session-review',
          displayName: 'Session Review',
          description: '基于事实审阅会话结果',
          publisher: 'Personal Agent Workbench',
          source: { kind: 'bundled', label: 'Product bundle' },
          permissions: ['session.read'],
          security: { notes: '只读会话权限' },
          versions: [{ version: '1.1.0' }, { version: '1.0.0' }],
          latestVersion: '1.1.0',
          installed: false,
          updateAvailable: false,
          actionable: true,
        }],
      },
      'agent.extensions.proposals': { ok: true, items: [] },
      'agent.lifecycleHooks.get': {
        ok: true,
        policies: [{ eventType: 'project_complete', enabled: true, action: 'memory_review_suggestion', tokenLimit: 256, cooldownSeconds: 300 }],
        recentEvents: [],
      },
      'agent.lifecycleHooks.update': { ok: true },
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
      ...overrides,
    },
  });
  renderPluginsWithTransport(transport, initialEntry);
  return transport;
}

function renderPluginsWithTransport(
  transport: ControlTransport,
  initialEntry = '/plugins',
): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<MemoryRouter initialEntries={[initialEntry]}><LocationProbe /><TooltipProvider delayDuration={0}><ControlTransportProvider transport={transport}><QueryClientProvider client={client}><PluginsFeature /></QueryClientProvider></ControlTransportProvider></TooltipProvider></MemoryRouter>);
}

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="test-location" hidden>{`${location.pathname}${location.search}`}</span>;
}

function toolItems() {
  return [
    tool({ id: 'memory', displayName: '记忆与工具书', description: '搜索与维护长期记忆', domain: 'memory', riskLevel: 'R1', operations: ['search', 'maintenance_apply'], sessionModes: ['assistant', 'coordinator'] }),
    tool({ id: 'configuration', displayName: '历史与配置', description: '查看历史并恢复便携备份', domain: 'configuration', riskLevel: 'R3', operations: ['history', 'restore_apply'], sessionModes: ['assistant', 'coordinator'], privatePath: '/api/private/tools' }),
    tool({ id: 'voice', displayName: '语音输入', description: '查看语音状态与服务连接', domain: 'voice', riskLevel: 'R1', operations: ['provider_status'], sessionModes: ['assistant', 'coordinator'] }),
    tool({ id: 'workspace_read', displayName: '工作区读取', description: '读取已授权工作区中的文本', domain: 'workspace', riskLevel: 'R0', operations: ['read'], sessionModes: ['coordinator'], availability: 'offline' }),
  ];
}

function tool(overrides: Record<string, unknown>) {
  const id = String(overrides.id);
  const risk = String(overrides.riskLevel ?? 'R0');
  const status = String(overrides.availability ?? 'online');
  return {
    category: overrides.domain,
    operationRisks: {},
    resultPresentation: 'tool_result',
    availability: status,
    version: '1',
    ...overrides,
    canonicalId: `tool:${id}`,
    kind: 'tool' as const,
    source: { kind: 'product', label: 'Personal Agent Workbench' },
    status,
    risk,
    requiredPermissions: [
      ...(risk === 'R0' ? [] : ['native_approval']),
      ...(id.startsWith('workspace_') ? ['workspace_scope'] : []),
    ],
    authorization: { state: 'not_applicable' as const, reason: 'session_context_required' },
    disclosure: {
      preference: 'inherit' as const,
      effective: 'enabled' as const,
      state: 'disclosed' as const,
      reason: 'inherited_built_in_default',
    },
    effectiveScope: 'built_in_default' as const,
    reasons: ['inherited_built_in_default', 'tool_not_authorized_by_existing_session_policy'],
    revision: 'tool-spec:1',
    effectiveAtMs: 1,
  };
}

function capability(
  id: string,
  kind: 'skill' | 'extension',
  displayName: string,
) {
  return {
    ...tool({
      id,
      displayName,
      description: `${displayName}说明`,
      domain: kind,
      riskLevel: 'R0',
      operations: [],
      sessionModes: ['assistant', 'coordinator'],
    }),
    canonicalId: `${kind}:${id}`,
    kind,
  };
}

function capabilityCatalog<T extends {
  canonicalId: string;
  disclosure: { effective: string };
}>(
  items: T[],
  projectScope: Record<string, unknown> = {
    supported: false,
    identityKind: 'none',
    reason: 'stable_project_identity_unavailable',
  },
  sessionId = '',
) {
  return {
    schemaVersion: 'rag-ime.capability-catalog.v1',
    ok: true,
    revision: `sha256:${'a'.repeat(64)}`,
    effectiveAtMs: 1,
    projectScope,
    ...(sessionId ? {
      sessionPolicy: {
        sessionId,
        policyRevision: 1,
        disclosurePreferences: {
          globalDefault: {},
          projectDefault: { 'tool:memory': 'enabled' },
          session: {},
          effective: Object.fromEntries(items.map((item) => [item.canonicalId, item.disclosure.effective])),
        },
        effectiveAtMs: 1,
      },
    } : {}),
    items,
  };
}

function capabilityDefaults(
  projectPreferences: Record<string, Record<string, string>> = {},
) {
  return {
    ok: true,
    configuration: {
      revision: 1,
      configuration: {
        sessionDefaults: { capabilityDisclosurePreferences: {} },
        capabilityDisclosure: { projectPreferences },
      },
    },
  };
}
