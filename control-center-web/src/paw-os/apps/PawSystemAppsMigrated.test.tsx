import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { PawOsAppearanceProvider } from '@/design/paw-os-themes';
import { PawOsAppSurfaceProvider, PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';

vi.mock('@/features/approvals', () => ({ ApprovalsFeature: () => <h1>审批真实界面</h1> }));
vi.mock('@/features/configuration', () => ({ ConfigurationFeature: () => <h1>配置真实界面</h1> }));
vi.mock('@/features/context-debug', () => ({ ContextDebugFeature: () => <h1>上下文真实界面</h1> }));
vi.mock('@/features/diagnostics', () => ({ DiagnosticsFeature: () => <h1>诊断真实界面</h1> }));
vi.mock('@/features/governance', () => ({ GovernanceFeature: () => <h1>治理真实界面</h1> }));
vi.mock('@/features/history', () => ({ HistoryFeature: () => <h1>输入记录真实界面</h1> }));
vi.mock('@/features/input-method', () => ({
  InputLexiconFeature: () => <h1>词库真实界面</h1>,
  InputMethodFeature: () => <h1>输入法真实界面</h1>,
}));
vi.mock('@/features/observability', () => ({ ObservabilityFeature: () => <h1>活动真实界面</h1> }));
vi.mock('@/features/plugins', () => ({ PluginsFeature: () => <h1>Package 生命周期真实界面</h1> }));
vi.mock('@/features/voice', () => ({ VoiceFeature: () => <h1>语音真实界面</h1> }));

import {
  PawSystemAppsMigrated,
  type PawSystemAppId,
} from './PawSystemAppsMigrated';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe('PawSystemAppsMigrated', () => {
  it.each([
    ['input-studio', '/history', '输入记录'],
    ['app-center', '/plugins?view=proposals', '建议'],
    ['system-monitor', '/diagnostics', '诊断'],
    ['system-settings', '/approvals', '审批'],
  ] as const)('keeps %s route %s selected in the migrated App navigation', (appId, route, label) => {
    renderSystemApp(appId, route);

    const navigation = screen.getByRole('navigation', { name: new RegExp('页面$') });
    expect(within(navigation).getByRole('button', { name: label })).toHaveAttribute('aria-current', 'page');
  });

  it('leaves App identity to the shared window chrome instead of repeating it in the rail', () => {
    renderSystemApp('input-studio', '/input');

    const rail = document.querySelector('.paw-system-app__nav');
    expect(rail?.querySelector('.paw-app-icon')).toBeNull();
    expect(rail?.firstElementChild?.tagName).toBe('NAV');
    expect(screen.getByRole('navigation', { name: 'Input Studio页面' })).toBeInTheDocument();
  });

  it('moves between Input Studio pages while retaining the real feature owners', async () => {
    const user = userEvent.setup();
    renderSystemApp('input-studio', '/input');

    expect(screen.getByRole('heading', { name: '输入法真实界面' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '语音' }));
    expect(screen.getByRole('heading', { name: '语音真实界面' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '语音' })).toHaveAttribute('aria-current', 'page');
  });

  it('gives 输入法 and 词库 independent page owners instead of repeating one long page', async () => {
    const user = userEvent.setup();
    renderSystemApp('input-studio', '/input');

    expect(screen.getByRole('heading', { name: '输入法真实界面' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '词库真实界面' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '词库' }));

    expect(screen.getByRole('heading', { name: '词库真实界面' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '输入法真实界面' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '词库' })).toHaveAttribute('aria-current', 'page');
  });

  it('loads the real Agent model catalog without inventing model options', async () => {
    const transport = baseTransport({
      'agent.role.models': {
        ok: true,
        providers: [{
          id: 'openai-codex',
          displayName: 'OpenAI Codex',
          models: [{
            provider: 'openai-codex',
            id: 'gpt-5.6-terra',
            name: 'GPT-5.6 Terra',
            api: 'responses',
            reasoning: true,
            thinkingLevels: ['off', 'medium', 'high'],
            supportsImages: true,
            contextWindow: 128_000,
            maxTokens: 32_000,
          }],
        }],
      },
    });
    renderSystemApp('system-settings', '/configuration?view=agent', transport);

    const model = await screen.findByRole('combobox', { name: 'Agent 模型' });
    expect(model).toHaveTextContent('GPT-5.6 Terra · openai-codex');
    expect(transport.requests.map(({ request }) => request.pathId)).toContain('agent.role.models');
    expect(transport.requests.map(({ request }) => request.pathId)).toContain('configuration.settings');
  });

  it('saves Agent defaults through the governed configuration authority and re-reads them', async () => {
    const user = userEvent.setup();
    let executionMode = 'per_action';
    let settingsReads = 0;
    const payloadSha256 = 'c'.repeat(64);
    const transport = baseTransport({
      'configuration.settings': () => {
        settingsReads += 1;
        return agentPreferenceSettings(executionMode);
      },
      'configuration.settings.preview': {
        schemaVersion: 'rag-ime.management-work-preview.v1',
        ok: true,
        previewToken: 'agent-settings-preview',
        pathId: 'configuration.settings.apply',
        payloadSha256,
        expectedRevision: { runtimeRevision: 7, subjectRevision: 'settings:7' },
        expiresAtMs: Date.now() + 60_000,
        requiredConfirm: 'apply',
        summary: { title: '保存 Agent 默认设置', items: ['更新执行权限'], risk: 'R1' },
      },
      'configuration.settings.apply': (request: ControlRequest) => {
        const changes = (request.body as Record<string, unknown>).changes as Record<string, unknown>;
        executionMode = String(changes['agent.defaults.executionMode']);
        return {
          schemaVersion: 'rag-ime.management-work-receipt.v1',
          ok: true,
          receiptId: 'agent-settings-receipt',
          pathId: 'configuration.settings.apply',
          payloadSha256,
          appliedAtMs: Date.now(),
          rollbackAvailable: true,
          rollbackToken: 'agent-settings-rollback',
        };
      },
    });
    renderSystemApp('system-settings', '/configuration?view=agent', transport);

    const permission = await screen.findByRole('combobox', { name: 'Agent 执行权限' });
    await user.selectOptions(permission, 'read_only');

    await waitFor(() => expect(transport.requests.map(({ request }) => request.pathId)).toEqual(expect.arrayContaining([
      'configuration.settings.preview',
      'configuration.settings.apply',
    ])));
    await waitFor(() => expect(permission).toHaveValue('read_only'));
    expect(settingsReads).toBeGreaterThanOrEqual(2);
  });

  it('keeps Package installation on validate, preview, explicit confirmation, and apply', async () => {
    const user = userEvent.setup();
    const transport = baseTransport({
      'agent.extensions.catalog': {
        ok: true,
        items: [{
          id: 'verified-package',
          displayName: 'Verified Package',
          description: 'Runtime catalog entry',
          publisher: 'Local registry',
          source: { kind: 'local', label: '本机目录' },
          permissions: ['workspace.read'],
          security: { notes: '来源已验证' },
          versions: [{ version: '1.0.0' }],
          latestVersion: '1.0.0',
          installed: false,
          updateAvailable: false,
          actionable: true,
        }],
      },
      'agent.extensions.validate': {
        ok: true,
        validationToken: 'validation-real',
        extension: { id: 'verified-package', displayName: 'Verified Package', version: '1.0.0' },
      },
      'agent.extensions.preview': {
        ok: true,
        previewToken: 'preview-real',
        payloadSha256: 'b'.repeat(64),
        summary: { action: 'install', pluginId: 'verified-package', displayName: 'Verified Package', permissions: ['workspace.read'] },
      },
      'agent.extensions.apply': { ok: true, receiptId: 'receipt-real' },
    });
    renderSystemApp('app-center', '/plugins?view=catalog', transport);

    await user.click(await screen.findByRole('button', { name: '查看安装内容' }));
    expect(await screen.findByText('等待你的确认')).toBeInTheDocument();
    expect(transport.requests.map(({ request }) => request.pathId)).toEqual(expect.arrayContaining([
      'agent.extensions.validate',
      'agent.extensions.preview',
    ]));
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.extensions.apply')).toBe(false);

    await user.click(screen.getByRole('button', { name: '确认更改' }));
    await waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'agent.extensions.apply')).toBe(true));
  });
});

function renderSystemApp(
  appId: PawSystemAppId,
  initialRoute: string,
  transport = baseTransport(),
) {
  return render(<SystemHarness appId={appId} initialRoute={initialRoute} transport={transport} />);
}

function SystemHarness({
  appId,
  initialRoute,
  transport,
}: {
  appId: PawSystemAppId;
  initialRoute: string;
  transport: MockControlTransport;
}) {
  const [route, setRoute] = useState(initialRoute);
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  }));
  return (
    <TooltipProvider delayDuration={0}>
      <QueryClientProvider client={client}>
        <ControlTransportProvider transport={transport}>
          <PawOsAppearanceProvider>
            <PawOsDesktopProvider openRoute={setRoute} openWindow={() => undefined}>
              <PawOsAppSurfaceProvider appId={appId} height={720} width={1_080}>
                <PawSystemAppsMigrated appId={appId} initialRoute={route} />
              </PawOsAppSurfaceProvider>
            </PawOsDesktopProvider>
          </PawOsAppearanceProvider>
        </ControlTransportProvider>
      </QueryClientProvider>
    </TooltipProvider>
  );
}

function baseTransport(overrides: Record<string, unknown> = {}) {
  return new MockControlTransport({
    capabilities: {
      features: { managementWorkContract: true, configurationSettingsWorkContract: true },
    },
    routes: {
    'agent.tools.list': {
      schemaVersion: 'rag-ime.capability-catalog.v1',
      ok: true,
      revision: `sha256:${'a'.repeat(64)}`,
      effectiveAtMs: 1,
      projectScope: { supported: false, identityKind: 'none', reason: 'stable_project_identity_unavailable' },
      items: [],
    },
    'agent.configuration.get': {
      ok: true,
      configuration: {
        revision: 1,
        configuration: {
          sessionDefaults: { capabilityDisclosurePreferences: {} },
          capabilityDisclosure: { projectPreferences: {} },
        },
      },
    },
    'agent.extensions.list': { ok: true, runtimeAvailable: true, items: [] },
    'agent.extensions.catalog': { ok: true, items: [] },
    'agent.extensions.proposals': { ok: true, items: [] },
    'agent.lifecycleHooks.get': { ok: true, policies: [], recentEvents: [] },
    'agent.role.models': { ok: true, providers: [] },
    'configuration.settings': agentPreferenceSettings('per_action'),
    ...overrides,
  } });
}

function agentPreferenceSettings(executionMode: string) {
  return {
    ok: true,
    settings: {
      agent: {
        defaults: {
          modelReference: 'inherit',
          thinkingLevel: 'high',
          executionMode,
        },
      },
    },
    runtimeConfig: { runtimeRevision: 7 },
  };
}
