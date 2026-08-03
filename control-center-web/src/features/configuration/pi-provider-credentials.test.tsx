import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { PiProviderCredentials } from './PiProviderCredentials';

afterEach(cleanup);

describe('Pi provider credential UI', () => {
  it('previews and confirms API key replacement without rendering the secret', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      capabilities: { features: { piProviderCredentials: true } },
      routes: {
        'agent.providers.get': providerCatalog(),
        'agent.provider.auth.preview': {
          ok: true,
          previewToken: 'preview-provider-key',
          provider: 'gpt',
          providerName: 'GPT',
          action: 'set_api_key',
          requiredConfirm: 'replace',
          expiresAtMs: Date.now() + 60_000,
          summary: ['替换 GPT 的 API Key。', '现有密钥不会读取或显示。'],
          secretPolicy: '密钥仅在确认写入时送往本机 Pi。',
          sessionBoundary: '当前回复不被中断。',
        },
        'agent.provider.auth.apply': {
          ok: true,
          receiptId: 'pi-auth-receipt-1',
          provider: 'gpt',
          action: 'set_api_key',
          receiptState: 'applied',
          requiresAgentRestart: true,
        },
      },
    });
    renderProvider(transport);

    const secret = 'secret-sentinel-ui';
    await user.type(await screen.findByLabelText('API Key'), secret);
    await user.click(screen.getByRole('button', { name: '保存密钥' }));
    expect(await screen.findByRole('heading', { name: '替换 API Key？' })).toBeInTheDocument();
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '确认继续' }));

    expect(await screen.findByText('API Key 已保存')).toBeInTheDocument();
    const apply = transport.requests.find(({ request }) => request.pathId === 'agent.provider.auth.apply');
    expect(apply?.request.body).toEqual({
      previewToken: 'preview-provider-key',
      confirmText: 'replace',
      apiKey: secret,
    });
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    await waitFor(() => expect(
      transport.requests.filter(({ request }) => request.pathId === 'agent.providers.get').length,
    ).toBeGreaterThanOrEqual(2));
  });

  it('uses browser callback OAuth by default and stays pending until completion', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      capabilities: { features: { piProviderCredentials: true } },
      routes: {
        'agent.providers.get': oauthProviderCatalog(),
        'agent.provider.auth.preview': {
          ok: true,
          previewToken: 'preview-oauth',
          requiredConfirm: 'connect',
          provider: 'openai-codex',
          action: 'oauth_browser',
          secretPolicy: '令牌只由 Pi 保存。',
          sessionBoundary: '登录完成后重启运行时。',
        },
        'agent.provider.auth.apply': {
          ok: true,
          receiptId: 'oauth-started',
          provider: 'openai-codex',
          action: 'oauth_browser',
          receiptState: 'login_started',
          requiresAgentRestart: false,
          login: {
            loginId: 'pi-login-1',
            state: 'waiting_for_user',
            loginMethod: 'browser',
            verificationUri: 'https://auth.openai.com/oauth/authorize?client_id=test&state=test',
          },
        },
        'agent.provider.oauth.status': {
          loginId: 'pi-login-1',
          state: 'waiting_for_user',
          loginMethod: 'browser',
          verificationUri: 'https://auth.openai.com/oauth/authorize?client_id=test&state=test',
        },
      },
    });
    renderProvider(transport);

    await user.click(await screen.findByRole('button', { name: '连接 ChatGPT' }));
    await user.click(await screen.findByRole('button', { name: '确认继续' }));

    expect(await screen.findByText('登录流程已启动')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /继续浏览器登录/ })).toHaveAttribute(
      'href',
      'https://auth.openai.com/oauth/authorize?client_id=test&state=test',
    );
    expect(screen.queryByText(/设备码：/)).not.toBeInTheDocument();
    expect(screen.queryByText('操作已完成。结束当前回复后重启 Agent 运行时，新凭据会统一生效。')).not.toBeInTheDocument();
  });

  it('explains how to enable ChatGPT device-code authorization', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      capabilities: { features: { piProviderCredentials: true } },
      routes: {
        'agent.providers.get': oauthProviderCatalog(),
        'agent.provider.auth.preview': {
          ok: true,
          previewToken: 'preview-oauth-disabled',
          requiredConfirm: 'connect',
          provider: 'openai-codex',
          action: 'oauth_device_code',
        },
        'agent.provider.auth.apply': {
          ok: true,
          receiptId: 'oauth-disabled',
          provider: 'openai-codex',
          action: 'oauth_device_code',
          receiptState: 'login_started',
          requiresAgentRestart: false,
          login: {
            loginId: 'pi-login-disabled',
            state: 'failed',
            error: 'Enable device code authorization for Codex in ChatGPT Security Settings, then run "codex login --device-auth" again.',
          },
        },
      },
    });
    renderProvider(transport);

    await user.click(await screen.findByRole('button', { name: '使用设备码' }));
    await user.click(await screen.findByRole('button', { name: '确认继续' }));

    expect(await screen.findByText('登录失败')).toBeInTheDocument();
    expect(screen.getByText('请先在 ChatGPT「设置 → 安全」中开启设备码授权，然后重新连接。'))
      .toBeInTheDocument();
    expect(screen.queryByText(/codex login --device-auth/)).not.toBeInTheDocument();
  });
  it('keeps a configured custom x1top provider and its governed model visible without exposing credentials', async () => {
    const catalog = providerCatalog();
    const transport = new MockControlTransport({
      capabilities: { features: { piProviderCredentials: true } },
      routes: {
        'agent.providers.get': {
          ...catalog,
          providers: [{
            ...catalog.providers[0],
            id: 'x1top',
            name: 'x1top',
            auth: { ...catalog.providers[0].auth, configured: true, type: 'api_key' },
            availableModelCount: 1,
            availableModels: [{
              id: 'x1top-luna',
              name: 'Luna Max',
              reasoning: true,
              imageInput: true,
            }],
          }],
        },
      },
    });

    renderProvider(transport);

    expect(await screen.findByRole('combobox', { name: '模型服务' })).toHaveTextContent('x1top');
    expect(screen.getByText('Luna Max')).toBeInTheDocument();
    expect(screen.getByLabelText('API Key')).toHaveValue('');
    expect(screen.queryByText(/secret|token/i)).not.toBeInTheDocument();
  });

});

function renderProvider(transport: MockControlTransport): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <PiProviderCredentials />
        </QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
}

function providerCatalog() {
  return {
    schemaVersion: 'rag-ime.pi-provider-catalog.v1',
    ok: true,
    available: true,
    providers: [{
      id: 'gpt',
      name: 'GPT',
      auth: {
        configured: false,
        type: '',
        source: '',
        sourceLabel: '',
        oauthSupported: false,
        oauthBrowserSupported: false,
        oauthDeviceCodeSupported: false,
      },
      configuredInCatalog: true,
      modelCount: 3,
      availableModelCount: 0,
      availableModels: [],
      modelsTruncated: false,
    }],
  };
}

function oauthProviderCatalog() {
  const catalog = providerCatalog();
  return {
    ...catalog,
    providers: [{
      ...catalog.providers[0],
      id: 'openai-codex',
      name: 'ChatGPT Plus/Pro',
      auth: {
        ...catalog.providers[0].auth,
        oauthSupported: true,
        oauthBrowserSupported: true,
        oauthDeviceCodeSupported: true,
      },
    }],
  };
}
