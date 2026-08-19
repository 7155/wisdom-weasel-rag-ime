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

    expect(await screen.findByRole('heading', { name: '插件管理', level: 1 })).toBeInTheDocument();
    const list = await screen.findByRole('group', { name: '能力列表' });
    const descriptions = Array.from(list.querySelectorAll<HTMLElement>('.plugins-list__copy > span'));
    expect(descriptions).toHaveLength(4);
    expect(descriptions.every((description) => {
      const style = getComputedStyle(description);
      return style.display === 'block'
        && style.overflow !== 'hidden'
        && style.webkitLineClamp !== '2';
    })).toBe(true);
    expect(within(list).getByRole('button', { name: /记忆与工具书/ })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('complementary', { name: '能力详情占位' })).toBeInTheDocument();
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'false');

    const detailTrigger = within(list).getByRole('button', { name: /历史与配置/ });
    await user.click(detailTrigger);
    const detail = screen.getByRole('complementary', { name: '能力详情' });
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'true');
    expect(detail).toHaveTextContent('受禁区保护');
    expect(detail).toHaveTextContent('native_approval');
    expect(detail).toHaveTextContent('恢复备份');
    expect(detail).toHaveTextContent('执行授权');
    expect(detail).toHaveTextContent('伙伴可见范围');
    expect(within(detail).getByRole('combobox', { name: '历史与配置的所有对话默认可见范围' })).toBeEnabled();

    expect(document.body).not.toHaveTextContent('configuration');
    expect(document.body).not.toHaveTextContent('restore_apply');
    expect(document.body).not.toHaveTextContent('/api/private/tools');
    expect(document.body).not.toHaveTextContent('R3');
    expect(document.body).not.toHaveTextContent('assistant');
    expect(document.body).not.toHaveTextContent('coordinator');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('complementary', { name: '能力详情' })).not.toBeInTheDocument();
    expect(detailTrigger).toHaveFocus();

    await user.click(detailTrigger);
    await user.click(screen.getByRole('button', { name: '关闭能力详情' }));
    expect(screen.queryByRole('complementary', { name: '能力详情' })).not.toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: '能力详情占位' })).toBeInTheDocument();
    expect(list.parentElement).toHaveAttribute('data-detail-open', 'false');
  });

  it('renders the complete management surface as a section inside model settings', async () => {
    renderPlugins({}, '/roles', true);

    expect(await screen.findByRole('heading', { name: '插件与工具', level: 2 })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '插件管理', level: 1 })).not.toBeInTheDocument();
    expect(document.querySelector('section.mgmt-page--embedded[data-route-id="plugins"]')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '审批中心' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新' })).toBeInTheDocument();
    expect(await screen.findByRole('group', { name: '能力列表' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '管理扩展与自动整理' })).toBeInTheDocument();
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

    await user.click(await screen.findByRole('button', { name: /向你提问/ }));
    const detail = screen.getByRole('complementary', { name: '能力详情' });
    expect(within(detail).getByRole('region', { name: '固定能力策略' })).toHaveTextContent('默认可用');
    expect(within(detail).queryByRole('combobox', { name: 'Ask的所有对话默认可见范围' })).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.configuration.update')).toBe(false);
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

  it('opens the project Pi skill with a search-first create-if-missing request', async () => {
    const user = userEvent.setup();
    renderPlugins();
    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await user.click(await screen.findByRole('button', { name: '获取或制作能力' }));

    expect(screen.getByTestId('test-location')).toHaveTextContent('/agent?draft=');
    expect(screen.getByTestId('test-location')).toHaveTextContent('%2Fskill%3Aplugin-creator');
    expect(screen.getByTestId('test-location')).toHaveTextContent('%E5%85%88%E6%90%9C%E7%B4%A2%E5%B8%82%E5%9C%BA');
    expect(screen.getByTestId('test-location')).toHaveTextContent('%E4%B8%8D%E8%A6%81%E5%A3%B0%E7%A7%B0%E5%B7%B2%E7%BB%8F%E5%AE%89%E8%A3%85');
  });

  it('resolves an npm Pi Package and stops at the product confirmation card', async () => {
    const user = userEvent.setup();
    const transport = renderPlugins({
      'agent.extensions.validate': {
        ok: true,
        validationToken: 'package-validation-token',
        distribution: 'pi_package',
        extension: {
          id: 'example.context-helper',
          displayName: 'Context Helper',
          version: '1.2.3',
          resources: {
            extensions: [],
            skills: ['skills/context-helper/SKILL.md'],
            prompts: ['prompts/context.md'],
            themes: [],
          },
          source: { kind: 'npm', requested: 'npm:@example/context-helper@1.2.3' },
        },
      },
      'agent.extensions.preview': {
        ok: true,
        previewToken: 'package-preview-token',
        payloadSha256: 'c'.repeat(64),
        summary: {
          action: 'install',
          pluginId: 'example.context-helper',
          displayName: 'Context Helper',
          version: '1.2.3',
          resources: {
            extensions: [],
            skills: ['skills/context-helper/SKILL.md'],
            prompts: ['prompts/context.md'],
            themes: [],
          },
        },
      },
    });

    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await user.type(
      screen.getByRole('textbox', { name: 'Pi Package 来源' }),
      'npm:@example/context-helper@1.2.3',
    );
    const inspectPackage = screen.getByRole('button', { name: '检查并预览' });
    expect(inspectPackage).toBeEnabled();
    await user.click(inspectPackage);

    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.extensions.validate'
    ))).toBe(true));
    expect(transport.requests.find((call) => (
      call.request.pathId === 'agent.extensions.validate'
    ))?.request.body).toEqual({ packageSource: 'npm:@example/context-helper@1.2.3' });
    expect(await screen.findByText('Pi 已解析')).toBeVisible();
    expect(screen.getByText(/2 项资源/)).toBeVisible();
    expect(screen.getByText('等待你的批准')).toBeVisible();
    expect(transport.requests.some((call) => (
      call.request.pathId === 'agent.extensions.preview'
      && JSON.stringify(call.request.body).includes('package-validation-token')
    ))).toBe(true);
    expect(transport.requests.some((call) => call.request.pathId === 'agent.extensions.apply')).toBe(false);
  });

  it('filters capabilities by readable purpose, availability and kind', async () => {
    const user = userEvent.setup();
    renderPlugins();
    await screen.findByRole('heading', { name: '插件管理', level: 1 });

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
    await user.click(screen.getByRole('radio', { name: '技能' }));
    expect(screen.queryByRole('button', { name: /工作区读取/ })).not.toBeInTheDocument();
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
      name: '记忆与工具书的所有对话默认可见范围',
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
    expect(screen.getByText(/所有对话默认已保存/)).toBeVisible();
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
      name: '记忆与工具书的当前项目默认可见范围',
    });
    expect(projectPreference).toHaveTextContent('向伙伴披露');
    expect(screen.getByRole('region', { name: '能力可见范围' })).toHaveTextContent('影响此项目的新对话');
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
    expect(screen.getByText(/当前项目默认已保存/)).toBeVisible();
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
    await user.click(screen.getByRole('combobox', { name: '记忆与工具书的所有对话默认可见范围' }));
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
    expect(screen.queryByText('对话复盘')).not.toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    expect(await screen.findByText('对话复盘')).toBeInTheDocument();
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

  it('shows a recoverable Pi disconnect instead of an empty installed state', async () => {
    const user = userEvent.setup();
    renderPlugins({
      'agent.extensions.list': {
        schemaVersion: 'rag-ime.plugin-inventory.v1',
        ok: true,
        runtimeAvailable: false,
        items: [],
      },
    });

    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    expect(await screen.findByText('Pi Runtime 暂时未连接')).toBeVisible();
    expect(screen.getByText('Pi 未连接')).toBeVisible();
    expect(screen.getByText(/不会再把断连伪装成“0 个已安装”/)).toBeVisible();
  });

  it('refreshes catalog, installed versions, proposals and lifecycle together', async () => {
    const user = userEvent.setup();
    const transport = renderPlugins();
    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await screen.findByText('对话复盘');
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
    await user.click(await screen.findByRole('button', { name: /对话复盘/ }));
    expect(screen.getByText('v1.1.0 · 需要的权限：读取对话内容 · 当前已启用')).toBeVisible();
  });
  it('shows installed display names and disables rollback after the visible version transition', async () => {
    const user = userEvent.setup();
    const transport = createPreviewTransport();
    renderPluginsWithTransport(transport);

    await user.click(await screen.findByRole('button', { name: '管理扩展与自动整理' }));
    await screen.findByText('时间线检查');

    await user.click(screen.getByRole('button', { name: '停用' }));
    await waitFor(() => expect(transport.requests.filter((call) => call.request.pathId === 'agent.extensions.apply')).toHaveLength(1));

    const rollback = screen.getByRole('button', { name: '恢复上一版本' });
    expect(rollback).toBeEnabled();
    await user.click(rollback);
    await waitFor(() => expect(transport.requests.filter((call) => call.request.pathId === 'agent.extensions.apply')).toHaveLength(2));

    expect(await screen.findByText('v0.9.0')).toBeVisible();
    expect(screen.getByRole('button', { name: '恢复上一版本' })).toBeDisabled();
  });

});

function renderPlugins(
  overrides: Partial<Record<ControlPathId, MockRouteHandler>> = {},
  initialEntry = '/plugins',
  embedded = false,
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
  renderPluginsWithTransport(transport, initialEntry, embedded);
  return transport;
}

function renderPluginsWithTransport(
  transport: ControlTransport,
  initialEntry = '/plugins',
  embedded = false,
): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<MemoryRouter initialEntries={[initialEntry]}><LocationProbe /><TooltipProvider delayDuration={0}><ControlTransportProvider transport={transport}><QueryClientProvider client={client}><PluginsFeature embedded={embedded} /></QueryClientProvider></ControlTransportProvider></TooltipProvider></MemoryRouter>);
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

function capabilityCatalog(
  items: ReturnType<typeof toolItems>,
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
