import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlPathId } from '@/platform/routes';
import type {
  ControlEventObserver,
  ControlRequest,
  ControlSubscription,
  ControlTransport,
  FrontendCapabilities,
} from '@/platform/transport';
import { ConfigurationFeature } from '.';
import { configurationMutationPathIds, requestConfigurationMutation } from './api';

const hash = 'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd';

afterEach(cleanup);

describe('Configuration settings WorkContract UI', () => {
  it('binds field changes to preview, apply, refresh, and rollback receipts', async () => {
    const user = userEvent.setup();
    const transport = renderConfiguration(true);
    await screen.findByRole('heading', { name: '配置与迁移', level: 1 });
    const input = await screen.findByRole('spinbutton', { name: '最大宽度' });
    expect(document.querySelector('.configuration-editor')).not.toBeNull();
    expect(document.querySelector('.configuration-portability')).not.toBeNull();
    await user.clear(input);
    await user.type(input, '620');
    const workflow = screen.getByText('应用设置差异', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();

    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '预览操作' }));
    await waitFor(() => expect(findRequest(transport, 'configuration.settings.preview')).toMatchObject({
      body: {
        changes: { 'display.maxWidth': 620 },
        expectedRuntimeRevision: 12,
      },
    }));
    expect(await within(workflow as HTMLElement).findByText('应用这些设置？')).toBeInTheDocument();
    expect(within(workflow as HTMLElement).getByText('最大宽度：560 → 620（重新载入输入法）')).toBeInTheDocument();
    expect(within(workflow as HTMLElement).queryByText(/display\.maxWidth|squirrel|R2/)).not.toBeInTheDocument();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '进入确认' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认并应用' }));

    expect(await within(workflow as HTMLElement).findByText('本机操作已记录')).toBeInTheDocument();
    expect(findRequest(transport, 'configuration.settings.apply')).toMatchObject({
      body: {
        changes: { 'display.maxWidth': 620 },
        expectedRuntimeRevision: 12,
        previewToken: 'preview-configuration-settings',
        payloadSha256: hash,
        confirmText: 'apply',
      },
    });
    await waitFor(() => expect(transport.settingsReads).toBeGreaterThanOrEqual(2));
    expect(await screen.findByText('没有待应用变更')).toBeInTheDocument();

    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '撤销这次操作' }));
    expect(await within(workflow as HTMLElement).findByText('已恢复到操作前')).toBeInTheDocument();
    expect(findRequest(transport, 'configuration.settings.rollback')).toMatchObject({
      body: {
        receiptId: 'receipt-configuration-apply',
        rollbackToken: 'rollback-configuration-settings',
        payloadSha256: hash,
        confirmText: 'rollback',
      },
    });
    await waitFor(() => expect(transport.settingsReads).toBeGreaterThanOrEqual(3));
  });

  it('fails closed when the settings WorkContract capability is absent', async () => {
    const user = userEvent.setup();
    const transport = renderConfiguration(false);
    await screen.findByRole('heading', { name: '配置与迁移', level: 1 });
    const input = await screen.findByRole('spinbutton', { name: '最大宽度' });
    await user.clear(input);
    await user.type(input, '620');
    const workflow = screen.getByText('应用设置差异', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();

    expect(await within(workflow as HTMLElement).findByText(/当前版本还不能安全应用设置/)).toBeInTheDocument();
    expect(within(workflow as HTMLElement).queryByRole('button', { name: '尚不可预览' })).not.toBeInTheDocument();
    expect(findRequest(transport, 'configuration.settings.preview')).toBeUndefined();
  });

  it('keeps secret fields read-only when no dedicated secure flow exists', async () => {
    const transport = renderConfiguration(true);
    await screen.findByRole('heading', { name: '配置与迁移', level: 1 });
    const secretInput = await screen.findByLabelText('管理令牌');
    expect(secretInput).toBeDisabled();
    expect(screen.getByText('请使用上方模型账号或对应安全功能修改。')).toBeInTheDocument();
    const workflow = screen.getByText('应用设置差异', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();

    expect(await within(workflow as HTMLElement).findByText(/修改至少一个非敏感设置/)).toBeInTheDocument();
    expect(within(workflow as HTMLElement).queryByRole('button', { name: '尚不可预览' })).not.toBeInTheDocument();
    expect(findRequest(transport, 'configuration.settings.preview')).toBeUndefined();
  });

  it('rejects secret-shaped settings before the general transport boundary', async () => {
    const transport = new ConfigurationTransport(true);
    expect(() => requestConfigurationMutation(transport, {
      pathId: configurationMutationPathIds.preview,
      body: {
        changes: { 'managementSecurity.token': 'secret-sentinel' },
        expectedRuntimeRevision: 12,
      },
    })).toThrow('秘密设置必须通过专用安全流程修改；本次请求未发送。');
    expect(findRequest(transport, 'configuration.settings.preview')).toBeUndefined();

    await expect(requestConfigurationMutation(transport, {
      pathId: configurationMutationPathIds.preview,
      body: {
        changes: { 'context.tokenBudget': 4096 },
        expectedRuntimeRevision: 12,
      },
    })).resolves.toMatchObject({ ok: true });
    expect(findRequest(transport, 'configuration.settings.preview')?.body).toMatchObject({
      changes: { 'context.tokenBudget': 4096 },
    });
  });

  it('reads the stateless lightning model and bounded thinking choices from the live Pi catalog', async () => {
    const user = userEvent.setup();
    const transport = renderConfiguration(true, true);
    await screen.findByRole('heading', { name: '配置与迁移', level: 1 });
    await waitFor(() => expect(findRequest(transport, 'agent.role.models')).toBeDefined());

    await user.click(screen.getByRole('combobox', { name: '设置分组' }));
    await user.click(await screen.findByRole('option', { name: '深度生成' }));

    expect(await screen.findByRole('combobox', { name: '闪电生成模型' })).toHaveTextContent('DeepSeek V4 Flash');
    expect(screen.getByRole('combobox', { name: '闪电生成思考' })).toHaveTextContent('高');

    await user.click(screen.getByRole('combobox', { name: '闪电生成思考' }));
    expect(await screen.findByRole('option', { name: '高' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '最高' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: '关闭' })).not.toBeInTheDocument();
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('combobox', { name: '看图模型' })).not.toBeInTheDocument();
  });
});

class ConfigurationTransport implements ControlTransport {
  readonly kind = 'mock' as const;
  readonly requests: ControlRequest[] = [];
  settingsReads = 0;

  constructor(
    private readonly writesAvailable: boolean,
    private readonly modelCatalogAvailable = false,
  ) {}

  async capabilities(): Promise<FrontendCapabilities> {
    const routeIds: ControlPathId[] = [
      'configuration.settings',
      'configuration.schema',
      ...(this.modelCatalogAvailable ? ['agent.role.models'] as ControlPathId[] : []),
      ...(this.writesAvailable ? [
        'configuration.settings.preview',
        'configuration.settings.apply',
        'configuration.settings.rollback',
      ] as ControlPathId[] : []),
    ];
    return {
      schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
      transport: 'mock',
      routeIds,
      features: {
        managementWorkContract: this.writesAvailable,
        configurationSettingsWorkContract: this.writesAvailable,
      },
      native: {
        pickFiles: false,
        managedAgentImageImport: false,
        revealPath: false,
        approvedExternalActions: false,
        keychain: false,
        tcc: false,
      },
    };
  }

  async request<Response = unknown>(request: ControlRequest): Promise<Response> {
    this.requests.push(request);
    if (request.pathId === 'configuration.settings') {
      this.settingsReads += 1;
      return settingsPayload() as Response;
    }
    if (request.pathId === 'configuration.schema') return schemaPayload() as Response;
    if (request.pathId === 'agent.role.models') return modelCatalogPayload() as Response;
    if (request.pathId === 'configuration.settings.preview') return {
      schemaVersion: 'rag-ime.management-work-preview.v1',
      ok: true,
      previewToken: 'preview-configuration-settings',
      pathId: 'configuration.settings.apply',
      payloadSha256: hash,
      expectedRevision: { runtimeRevision: 12, subjectRevision: 'sha256:before' },
      expiresAtMs: Date.now() + 60_000,
      requiredConfirm: 'apply',
      summary: {
        title: '应用控制中心设置',
        items: ['更新 display.maxWidth', '需要重载: squirrel'],
        risk: 'R2',
      },
    } as Response;
    if (request.pathId === 'configuration.settings.apply') return receipt(
      'configuration.settings.apply',
      'receipt-configuration-apply',
      'rollback-configuration-settings',
      true,
    ) as Response;
    if (request.pathId === 'configuration.settings.rollback') return receipt(
      'configuration.settings.rollback',
      'receipt-configuration-rollback',
      '',
      false,
    ) as Response;
    throw new Error(`Unexpected request: ${request.pathId}`);
  }

  subscribe<Event = unknown>(
    _request: ControlSubscription,
    _observer: ControlEventObserver<Event>,
  ): () => void {
    return () => {};
  }
}

function renderConfiguration(
  writesAvailable: boolean,
  modelCatalogAvailable = false,
): ConfigurationTransport {
  const transport = new ConfigurationTransport(writesAvailable, modelCatalogAvailable);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}>
            <ConfigurationFeature />
          </QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  return transport;
}

function findRequest(
  transport: ConfigurationTransport,
  pathId: string,
): ControlRequest | undefined {
  return transport.requests.find((request) => String(request.pathId) === pathId);
}

function settingsPayload() {
  return {
    ok: true,
    settingsHash: 'sha256:settings',
    settings: {
      display: { maxWidth: 560 },
      activeRag: {
        quickModel: 'deepseek/deepseek-v4-flash',
        quickThinkingLevel: 'high',
      },
    },
    runtimeConfig: { runtimeRevision: 12, settingsRevision: 'sha256:settings' },
  };
}

function schemaPayload() {
  return {
    ok: true,
    schemaVersion: 'rag-ime.management-settings-schema.v3',
    sections: [{
      id: 'display',
      label: '显示',
      fields: [{
        key: 'display.maxWidth',
        type: 'integer',
        label: '最大宽度',
        description: '候选窗口最大宽度',
        min: 320,
        max: 760,
        step: 20,
        applyMode: 'restart_input_method',
        restartComponent: 'squirrel',
      }, {
        key: 'managementSecurity.token',
        type: 'password',
        label: '管理令牌',
        description: '只允许通过安全存储修改',
        applyMode: 'restart_sidecar',
        restartComponent: 'sidecar',
      }],
    }, {
      id: 'activeRag',
      label: 'Active RAG',
      fields: [{
        key: 'activeRag.quickModel',
        type: 'pi-model',
        label: '闪电生成模型',
        description: '来自 Pi 实时模型目录',
      }, {
        key: 'activeRag.quickThinkingLevel',
        type: 'pi-thinking',
        label: '闪电生成思考',
        description: '必须启用模型支持的思考档',
        modelKey: 'activeRag.quickModel',
      }],
    }],
  };
}

function modelCatalogPayload() {
  return {
    ok: true,
    providers: [{
      id: 'deepseek',
      models: [{
        provider: 'deepseek',
        id: 'deepseek-v4-flash',
        name: 'DeepSeek V4 Flash',
        thinkingLevels: ['off', 'high', 'max'],
        supportsImages: false,
      }],
    }, {
      id: 'gpt',
      models: [{
        provider: 'gpt',
        id: 'gpt-5.6-luna',
        name: 'GPT-5.6 Luna',
        thinkingLevels: ['off', 'minimal', 'low', 'high'],
        supportsImages: true,
      }],
    }],
  };
}

function receipt(
  pathId: string,
  receiptId: string,
  rollbackToken: string,
  rollbackAvailable: boolean,
) {
  return {
    schemaVersion: 'rag-ime.management-work-receipt.v1',
    ok: true,
    receiptId,
    pathId,
    payloadSha256: hash,
    appliedAtMs: Date.now(),
    auditId: 1,
    rollbackAvailable,
    rollbackToken,
    rollbackAuthority: { settingKeys: ['display.maxWidth'] },
    restartComponents: ['squirrel'],
  };
}
