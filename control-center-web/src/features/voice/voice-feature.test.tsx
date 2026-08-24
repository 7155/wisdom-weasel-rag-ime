import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlPathId } from '@/platform/routes';
import type { VoiceProviderId } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { VoiceFeature } from '.';

const hash = 'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee';

afterEach(cleanup);

describe('VoiceFeature', () => {
  it('shows provider response evidence and the independent third-pass result', async () => {
    const user = userEvent.setup();
    renderVoiceWithHotwordWrites();

    await user.click(await screen.findByText('文字定稿状态'));
    expect(await screen.findByText('本次已纠错')).toBeInTheDocument();
    expect(screen.getByText('已完成保守校对')).toBeInTheDocument();
    await user.click(screen.getByText('高级：本次定稿记录', { selector: 'summary' }));
    expect(screen.getByText(/本次处理经过 2 个阶段/)).toBeInTheDocument();
    expect(screen.getByText(/识别到 1 个语句片段/)).toBeInTheDocument();
    expect(screen.getByText(/服务返回了额外信息/)).toBeInTheDocument();
  });

  it('applies provider and hotkey through the settings WorkContract instead of Agent handoff', async () => {
    const user = userEvent.setup();
    const transport = renderVoiceWithHotwordWrites();

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    expect(await screen.findByText('当前：实时听写')).toBeInTheDocument();
    expect(screen.getByText(/边说边显示，说完后补充完整文字/)).toBeInTheDocument();
    expect(screen.queryByText(/让澄确认切换|provider_apply/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: '实时服务' }));
    expect(screen.getByText(/可在高级连接设置中使用自定义服务/)).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Option + 空格' }));
    const workflow = screen.getByText('保存转写引擎与按键', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '保存转写引擎与按键' }));
    await waitFor(() => expect(configurationRequest(transport, 'configuration.settings.preview')).toMatchObject({
      body: {
        changes: {
          'voice.provider': 'realtime_websocket',
          'voice.hotkey': 'option_space',
        },
        expectedRuntimeRevision: 12,
      },
    }));
    await waitFor(() => expect(configurationRequest(transport, 'configuration.settings.apply')).toBeDefined());
  });

  it('selects a real Pi model for independent voice refinement', async () => {
    const user = userEvent.setup();
    const transport = renderVoiceWithHotwordWrites();

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    expect(await screen.findByRole('combobox', { name: '保守校对模型' }))
      .toHaveTextContent('跟随伙伴默认模型');

    await user.click(screen.getByRole('combobox', { name: '保守校对模型' }));
    await user.click(await screen.findByRole('option', { name: /GPT-5.6 Luna/ }));
    await user.click(screen.getByRole('combobox', { name: '校对强度' }));
    await user.click(await screen.findByRole('option', { name: '高' }));

    const workflow = screen.getByText('保存保守校对模型', { selector: 'strong' })
      .closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '保存保守校对模型' }));
    await waitFor(() => expect(configurationRequest(
      transport,
      'configuration.settings.preview',
    )).toMatchObject({
      body: {
        changes: {
          'voice.refinementModel': 'gpt/gpt-5.6-luna',
          'voice.refinementThinkingLevel': 'high',
        },
        expectedRuntimeRevision: 12,
      },
    }));
  });

  it('fails closed outside the native host for Keychain and system actions', async () => {
    const user = userEvent.setup();
    renderVoice(false);

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    expect(await screen.findByText('网页端不能启动听写或打开系统授权；请回到已安装的PAW。')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '听写服务' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '麦克风' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '辅助功能' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '停止听写服务' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '安全保存账号' })).not.toBeInTheDocument();
    await user.click(screen.getByText('配置服务连接', { selector: 'summary' }));
    expect(screen.getByRole('button', { name: '安全保存账号' })).toBeDisabled();
  });

  it('keeps an unreadable runtime truthful and offers a focused retry', async () => {
    const user = userEvent.setup();
    const transport = renderVoice(false, 'native_streaming', ['澄助手'], true);

    expect(await screen.findByText('听写状态读取失败')).toBeInTheDocument();
    expect(screen.getAllByText('状态未知')).toHaveLength(3);
    expect(screen.queryByText('未运行')).not.toBeInTheDocument();
    expect(screen.queryByText('未允许')).not.toBeInTheDocument();

    const before = transport.requests.filter(({ request }) => request.pathId === 'diagnostics.runtime').length;
    await user.click(screen.getByRole('button', { name: '重试听写状态' }));
    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'diagnostics.runtime').length,
    ).toBeGreaterThan(before));
  });

  it('offers only hotwords that are not already in the current draft', async () => {
    const user = userEvent.setup();
    renderVoice(true, 'native_streaming', ['澄助手', '个人计划', '项目名称']);

    const contact = await screen.findByRole('button', { name: '常用联系人' });
    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    expect(screen.queryByRole('button', { name: '澄助手' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '个人计划' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '项目名称' })).not.toBeInTheDocument();

    await user.click(contact);
    expect(screen.queryByRole('button', { name: '常用联系人' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '语音热词' })).toHaveValue('澄助手\n个人计划\n项目名称\n常用联系人');
  });

  it('keeps suggestions local until saving and persists user-facing hotwords', async () => {
    const user = userEvent.setup();
    const transport = renderVoiceWithHotwordWrites();

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    const hotwordSwitch = await screen.findByRole('switch', { name: '启用热词' });
    const editor = await screen.findByRole('textbox', { name: '语音热词' });
    const workflow = screen.getByText('保存热词词表', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    expect(hotwordSwitch).not.toBeChecked();
    expect(editor).toHaveValue('');
    expect(configurationRequest(transport, 'configuration.settings.preview')).toBeUndefined();

    await user.click(screen.getByRole('button', { name: 'GPT-5.6' }));
    await user.click(screen.getByRole('button', { name: '专业名词' }));
    expect(editor).toHaveValue('GPT-5.6\n专业名词');
    expect(hotwordSwitch).not.toBeChecked();
    expect(configurationRequest(transport, 'configuration.settings.preview')).toBeUndefined();

    await user.click(hotwordSwitch);
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '保存热词词表' }));
    await waitFor(() => expect(configurationRequest(transport, 'configuration.settings.preview')).toMatchObject({
      body: {
        changes: {
          'voice.hotwordsEnabled': true,
          'voice.hotwords': ['GPT-5.6', '专业名词'],
        },
        expectedRuntimeRevision: 12,
      },
    }));
    expect(await within(workflow as HTMLElement).findByText('已保存')).toBeInTheDocument();
    expect(configurationRequest(transport, 'configuration.settings.apply')).toMatchObject({
      body: {
        changes: {
          'voice.hotwordsEnabled': true,
          'voice.hotwords': ['GPT-5.6', '专业名词'],
        },
        expectedRuntimeRevision: 12,
        previewToken: 'preview-voice-hotwords',
        payloadSha256: hash,
        confirmText: 'apply',
      },
    });
  });

  it('blocks unsupported hotword characters before any write preview', async () => {
    const user = userEvent.setup();
    const transport = renderVoiceWithHotwordWrites();

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    await user.type(await screen.findByRole('textbox', { name: '语音热词' }), 'bad|word');
    await user.click(screen.getByRole('switch', { name: '启用热词' }));

    expect((await screen.findAllByText('“bad|word”包含当前语音服务不支持的符号。')).length).toBeGreaterThan(0);
    const workflow = screen.getByText('保存热词词表', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    expect(within(workflow as HTMLElement).queryByRole('button', { name: '尚不可预览' })).not.toBeInTheDocument();
    expect(configurationRequest(transport, 'configuration.settings.preview')).toBeUndefined();
  });

  it('names provider APIs accurately and disables unsupported hotword writes', async () => {
    renderVoice(false, 'http_transcription');

    expect(await screen.findByText('当前：上传后转写')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '实时听写' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '实时服务' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: '上传后转写' })).toBeChecked();
    expect(screen.getByText(/松开按键后再转写整段音频/)).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: '启用热词' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: '语音热词' })).toBeDisabled();
    expect(screen.getByText(/不发送热词/)).toBeInTheDocument();
  });
});

function renderVoice(
  toolAvailable: boolean,
  provider: VoiceProviderId = 'native_streaming',
  savedHotwords: string[] = ['澄助手'],
  runtimeFailure = false,
): MockControlTransport {
  const routeIds = [
    'configuration.settings',
    'configuration.schema',
    'diagnostics.runtime',
    'agent.tools.list',
    'agent.session.prompt',
    'agent.role.models',
  ] as ControlPathId[];
  const transport = new MockControlTransport({
    capabilities: { routeIds },
    routes: {
      'configuration.settings': {
        ok: true,
        runtimeRevision: 4,
        settings: {
          voice: {
            provider,
            hotkey: 'Option + Space',
            hotwords: savedHotwords,
            hotwordsEnabled: true,
            tokenConfigured: true,
          },
        },
      },
      'configuration.schema': { ok: true, sections: [] },
      'diagnostics.runtime': runtimeFailure
        ? () => { throw new Error('runtime probe unavailable'); }
        : {
            ok: true,
            components: {
              voiceAgent: { ok: true },
              microphone: { ok: true },
              accessibility: { ok: true },
            },
          },
      'agent.tools.list': {
        ok: true,
        items: toolAvailable ? [{
          id: 'voice',
          domain: 'voice',
          availability: 'online',
          operations: [
            'privacy_policy',
            'provider_status',
            'provider_preview',
            'provider_apply',
            'provider_rollback',
          ],
        }] : [],
      },
      'agent.role.models': voiceModelCatalog(),
    },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MemoryRouter initialEntries={['/voice']}>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}>
            <VoiceFeature />
            <LocationProbe />
          </QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  return transport;
}

function renderVoiceWithHotwordWrites(): MockControlTransport {
  const routeIds = [
    'configuration.settings',
    'configuration.schema',
    'configuration.settings.preview',
    'configuration.settings.apply',
    'configuration.settings.rollback',
    'diagnostics.runtime',
    'agent.tools.list',
    'agent.session.prompt',
    'agent.role.models',
  ] as ControlPathId[];
  const transport = new MockControlTransport({
    capabilities: {
      routeIds,
      features: {
        managementWorkContract: true,
        configurationSettingsWorkContract: true,
      },
    },
    routes: {
      'configuration.settings': {
        ok: true,
        settingsHash: 'sha256:settings',
        runtimeConfig: { runtimeRevision: 12, settingsRevision: 'sha256:settings' },
        settings: {
          voice: {
            provider: 'native_streaming',
            hotkey: 'middle_mouse',
            hotwords: [],
            hotwordsEnabled: false,
            refinementModel: 'inherit',
            refinementThinkingLevel: 'off',
            tokenConfigured: true,
          },
        },
        voiceControl: {
          provider: 'native_streaming',
          hotwords: {
            ok: true,
            count: 0,
            enabled: false,
            words: [],
            applyState: 'next_session',
            inSync: true,
          },
          recognition: {
            deployed: {
              binaryFound: true,
              secondPass: true,
              semanticSmoothing: true,
              fullResultReplacement: true,
              providerResponseMetadata: true,
              thirdPassRefinement: true,
              state: 'ready',
            },
            lastSession: {
              finalReceived: true,
              finalLatencyMs: 116,
              finalRevisedPartial: true,
              providerFinalRevisedPartial: false,
              providerResponseStage: 'nonstream',
              providerResponseStages: ['stream_snapshot', 'nonstream'],
              providerResponseCount: 2,
              providerResponseSequence: -17,
              providerUtteranceMetadata: [{ start_time: '0', end_time: '116' }],
              providerAdditionFields: { duration: '116', result_type: 'nonstream' },
              thirdPassRequested: true,
              thirdPassApplied: true,
              thirdPassChanged: true,
              thirdPassLatencyMs: 842,
              thirdPassModel: 'gpt/gpt-5.6-luna',
            },
          },
        },
      },
      'configuration.schema': { ok: true, sections: [] },
      'configuration.settings.preview': {
        schemaVersion: 'rag-ime.management-work-preview.v1',
        ok: true,
        previewToken: 'preview-voice-hotwords',
        pathId: 'configuration.settings.apply',
        payloadSha256: hash,
        expectedRevision: { runtimeRevision: 12, subjectRevision: 'sha256:before' },
        expiresAtMs: Date.now() + 60_000,
        requiredConfirm: 'apply',
        summary: {
          title: '保存语音热词',
          items: ['启用热词', '保存 2 条词'],
          risk: 'R1',
        },
      },
      'configuration.settings.apply': voiceReceipt(
        'configuration.settings.apply',
        'receipt-voice-hotwords',
        true,
      ),
      'configuration.settings.rollback': voiceReceipt(
        'configuration.settings.rollback',
        'receipt-voice-hotwords-rollback',
        false,
      ),
      'diagnostics.runtime': {
        ok: true,
        components: {
          voiceAgent: { ok: true },
          voiceMicrophone: { ok: true },
          voiceAccessibility: { ok: true },
        },
      },
      'agent.tools.list': {
        ok: true,
        items: [{
          id: 'voice',
          domain: 'voice',
          availability: 'online',
          operations: [
            'privacy_policy',
            'provider_status',
            'provider_preview',
            'provider_apply',
            'provider_rollback',
          ],
        }],
      },
      'agent.role.models': voiceModelCatalog(),
    },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <MemoryRouter initialEntries={['/voice']}>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}>
            <VoiceFeature />
            <LocationProbe />
          </QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  return transport;
}

function voiceReceipt(pathId: string, receiptId: string, rollbackAvailable: boolean) {
  return {
    schemaVersion: 'rag-ime.management-work-receipt.v1',
    ok: true,
    receiptId,
    pathId,
    payloadSha256: hash,
    appliedAtMs: Date.now(),
    auditId: 1,
    rollbackAvailable,
    rollbackToken: rollbackAvailable ? 'rollback-voice-hotwords' : '',
    rollbackAuthority: { settingKeys: ['voice.hotwords', 'voice.hotwordsEnabled'] },
    restartComponents: [],
  };
}

function voiceModelCatalog() {
  return {
    schemaVersion: 'rag-ime.agent-role-model-catalog.v1',
    ok: true,
    selected: { provider: 'deepseek', id: 'deepseek-v4-flash' },
    thinkingLevel: 'off',
    providers: [{
      id: 'deepseek',
      displayName: 'DeepSeek',
      models: [{
        provider: 'deepseek',
        id: 'deepseek-v4-flash',
        name: 'DeepSeek V4 Flash',
        thinkingLevels: ['off', 'high'],
      }],
    }, {
      id: 'gpt',
      displayName: 'GPT',
      models: [{
        provider: 'gpt',
        id: 'gpt-5.6-luna',
        name: 'GPT-5.6 Luna',
        thinkingLevels: ['off', 'low', 'high', 'max'],
      }],
    }],
  };
}

function configurationRequest(transport: MockControlTransport, pathId: string) {
  return transport.requests.find(({ request }) => request.pathId === pathId)?.request;
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
