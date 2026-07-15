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
  it('hands a supported provider change to the real Agent approval flow without writing directly', async () => {
    const user = userEvent.setup();
    const transport = renderVoice(true);

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    expect(await screen.findByText('当前：原生流式')).toBeInTheDocument();
    expect(screen.queryByText(/configured|not configured|voice\.provider|provider_apply|control-center/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /演练流程|真实写入尚未接入/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: '实时连接' }));
    await user.click(screen.getByRole('button', { name: '让智鼬确认切换' }));

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/agent?'));
    const location = screen.getByTestId('location').textContent ?? '';
    const draft = new URLSearchParams(location.split('?')[1]).get('draft') ?? '';
    expect(draft).toContain('实时连接');
    expect(draft).toContain('等待我确认');
    expect(draft).not.toMatch(/ime_voice|provider_apply|pathId|policy|version/i);
    expect(transport.requests.some(({ request }) => request.pathId.startsWith('configuration.settings.'))).toBe(false);
    expect(transport.requests.some(({ request }) => request.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('fails closed when the voice management tool is unavailable', async () => {
    const user = userEvent.setup();
    renderVoice(false);

    await screen.findByRole('heading', { name: '语音输入', level: 1 });
    expect(await screen.findByText('当前没有可验证的语音管理能力。选择服务只会停留在本页，不会写入任何设置。')).toBeInTheDocument();
    const action = screen.getByRole('button', { name: '当前不可切换' });
    expect(action).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: 'HTTP 转写' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/voice');
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
            hotkey: 'Middle Mouse',
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
