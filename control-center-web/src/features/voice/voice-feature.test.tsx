import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlPathId } from '@/platform/routes';
import { MockControlTransport } from '@/test/mock-transport';
import { VoiceFeature } from '.';

const hash = 'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee';

afterEach(cleanup);

describe('VoiceFeature', () => {
  it('applies provider and hotkey through the settings WorkContract instead of Agent handoff', async () => {
    const user = userEvent.setup();
    const transport = renderVoiceWithHotwordWrites();

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    expect(await screen.findByText('当前：原生流式')).toBeInTheDocument();
    expect(screen.queryByText(/让智鼬确认切换|provider_apply/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: '实时连接' }));
    await user.click(screen.getByRole('radio', { name: 'Option + 空格' }));
    const workflow = screen.getByText('保存语音服务与快捷键', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '预览操作' }));
    await waitFor(() => expect(configurationRequest(transport, 'configuration.settings.preview')).toMatchObject({
      body: {
        changes: {
          'voice.provider': 'realtime_websocket',
          'voice.hotkey': 'option_space',
        },
        expectedRuntimeRevision: 12,
      },
    }));
    await user.click(await within(workflow as HTMLElement).findByRole('button', { name: '进入确认' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认并应用' }));
    expect(configurationRequest(transport, 'configuration.settings.apply')).toBeDefined();
  });

  it('fails closed outside the native host for Keychain and system actions', async () => {
    renderVoice(false);

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    expect(await screen.findByText('浏览器预览不能启动代理或触发系统授权；请在已安装的智鼬控制中心中操作。')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '语音代理' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '麦克风' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: '辅助功能' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '停止语音代理' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '保存到 Keychain' })).toBeDisabled();
  });

  it('keeps suggestions local until preview and saves technical hotwords through WorkContract', async () => {
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
    await user.click(screen.getByRole('button', { name: 'API Key' }));
    expect(editor).toHaveValue('GPT-5.6\nAPI Key');
    expect(hotwordSwitch).not.toBeChecked();
    expect(configurationRequest(transport, 'configuration.settings.preview')).toBeUndefined();

    await user.click(hotwordSwitch);
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '预览操作' }));
    await waitFor(() => expect(configurationRequest(transport, 'configuration.settings.preview')).toMatchObject({
      body: {
        changes: {
          'voice.hotwordsEnabled': true,
          'voice.hotwords': ['GPT-5.6', 'API Key'],
        },
        expectedRuntimeRevision: 12,
      },
    }));
    await user.click(await within(workflow as HTMLElement).findByRole('button', { name: '进入确认' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认并应用' }));

    expect(await within(workflow as HTMLElement).findByText('本机操作已记录')).toBeInTheDocument();
    expect(configurationRequest(transport, 'configuration.settings.apply')).toMatchObject({
      body: {
        changes: {
          'voice.hotwordsEnabled': true,
          'voice.hotwords': ['GPT-5.6', 'API Key'],
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
    expect(within(workflow as HTMLElement).getByRole('button', { name: '尚不可预览' })).toBeDisabled();
    expect(configurationRequest(transport, 'configuration.settings.preview')).toBeUndefined();
  });
});

function renderVoice(toolAvailable: boolean): MockControlTransport {
  const routeIds = [
    'configuration.settings',
    'configuration.schema',
    'diagnostics.runtime',
    'agent.tools.list',
    'agent.session.prompt',
  ] as ControlPathId[];
  const transport = new MockControlTransport({
    capabilities: { routeIds },
    routes: {
      'configuration.settings': {
        ok: true,
        runtimeRevision: 4,
        settings: {
          voice: {
            provider: 'native_streaming',
            hotkey: 'Option + Space',
            hotwords: ['智鼬'],
            hotwordsEnabled: true,
            tokenConfigured: true,
          },
        },
      },
      'configuration.schema': { ok: true, sections: [] },
      'diagnostics.runtime': {
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
          id: 'ime_voice',
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
            },
            lastSession: { finalReceived: true, finalLatencyMs: 116 },
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
          id: 'ime_voice',
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

function configurationRequest(transport: MockControlTransport, pathId: string) {
  return transport.requests.find(({ request }) => request.pathId === pathId)?.request;
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
