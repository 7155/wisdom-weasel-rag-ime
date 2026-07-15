import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { InputMethodFeature } from './index';

const settings = {
  ok: true,
  settings: { interaction: { postCommit: { enabled: true } } },
};

const schema = {
  ok: true,
  sections: [{
    id: 'interaction',
    label: '交互',
    fields: [{
      key: 'interaction.postCommit.enabled',
      type: 'boolean',
      label: '提交后预测',
      description: '提交后调度助手候选',
      applyMode: 'live',
    }],
  }],
};

const emptyReview = {
  schemaVersion: 'rag-ime.rime-lexicon-review.v1',
  ok: true,
  project: 'wisdom-weasel-rag-ime',
  entryCount: 0,
  entries: [],
  reviewToken: 'a'.repeat(64),
  confirmText: 'APPLY_REVIEWED_RIME_LEXICON',
  applySupported: true,
  reviewRequired: true,
};

const review = {
  ...emptyReview,
  entryCount: 1,
  entries: [{
    reviewKey: '表情包\tbiao qing bao',
    text: '表情包',
    pinyin: 'biao qing bao',
    weight: 180,
    positiveCount: 3,
    negativeCount: 0,
    reasons: ['accepted'],
    reviewSource: 'usage',
    reviewReason: '来自真实选词反馈',
    selected: true,
  }],
};

afterEach(cleanup);

describe('InputMethodFeature', () => {
  it('updates the read-only current mode when the live overview arrives asynchronously', async () => {
    let resolveOverview!: (value: unknown) => void;
    const overview = new Promise<unknown>((resolve) => { resolveOverview = resolve; });
    renderFeature(new MockControlTransport({
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': () => overview,
        'configuration.settings': settings,
        'configuration.schema': schema,
        'input.lexicon.review': emptyReview,
      },
    }));

    expect(await screen.findByText('尚未读取到运行模式')).toBeInTheDocument();
    resolveOverview({ ok: true, profile: '安全模式' });

    await waitFor(() => expect(screen.getByText('安全模式')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: '当前不可用' })).toBeDisabled();
  });

  it('does not relabel an unknown live runtime profile as 标准模式', async () => {
    renderFeature(new MockControlTransport({
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: 'foreground-rag-proof' },
        'configuration.settings': settings,
        'configuration.schema': schema,
        'input.lexicon.review': emptyReview,
      },
    }));

    expect(await screen.findByText('自定义模式')).toBeInTheDocument();
    expect(screen.queryByText('foreground-rag-proof')).not.toBeInTheDocument();
  });

  it('humanizes schema labels and enum values instead of exposing implementation fields', async () => {
    renderFeature(new MockControlTransport({
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': { ok: true, settings: { interaction: { postCommit: { numberKeys: 'provider_internal_v3' } } } },
        'configuration.schema': {
          ok: true,
          sections: [{
            id: 'interaction',
            label: 'interaction',
            fields: [{
              key: 'interaction.postCommit.numberKeys',
              type: 'enum',
              label: 'pathId profileVersion',
              description: '/api/internal/schema',
              applyMode: 'live',
            }],
          }],
        },
        'input.lexicon.review': emptyReview,
      },
    }));

    expect(await screen.findByText('预测出现时的数字键')).toBeInTheDocument();
    expect(screen.getByText('自定义设置')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('pathId');
    expect(document.body).not.toHaveTextContent('provider_internal_v3');
    expect(document.body).not.toHaveTextContent('/api/internal/schema');
  });

  it('fails closed when the host does not expose all lexicon pathIds', async () => {
    renderFeature(new MockControlTransport({
      capabilities: {
        routeIds: ['input.source.get', 'overview.get', 'configuration.settings', 'configuration.schema'],
      },
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': settings,
        'configuration.schema': schema,
      },
    }));

    expect(await screen.findByText(/当前版本没有提供完整的审阅、写入与撤销能力/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '预览已选' })).not.toBeInTheDocument();
    expect(screen.queryByText('演练 / 未执行')).not.toBeInTheDocument();
  });

  it('reports a capability read failure instead of presenting it as an empty lexicon', async () => {
    const transport = new MockControlTransport({
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': settings,
        'configuration.schema': schema,
      },
    });
    vi.spyOn(transport, 'capabilities').mockRejectedValue(new Error('能力接口不可用'));
    renderFeature(transport);

    expect(await screen.findByText('无法确认词库能力')).toBeInTheDocument();
    expect(screen.getByText('能力接口不可用')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '预览已选' })).not.toBeInTheDocument();
  });

  it('uses the live review token, renders an unapplied redeploy state, and rolls back by receipt', async () => {
    const user = userEvent.setup();
    const apply = vi.fn(async () => ({
      schemaVersion: 'rag-ime.rime-lexicon-review.v1',
      ok: true,
      applied: true,
      entryCount: 1,
      rollbackId: 'rollback-lexicon-1',
      requiresRedeploy: true,
    }));
    const rollback = vi.fn(async () => ({
      schemaVersion: 'rag-ime.rime-lexicon-review.v1',
      ok: true,
      rolledBack: true,
      rollbackId: 'rollback-lexicon-1',
      requiresRedeploy: true,
    }));
    const transport = new MockControlTransport({
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': settings,
        'configuration.schema': schema,
        'input.lexicon.review': review,
        'input.lexicon.apply': apply,
        'input.lexicon.rollback': rollback,
      },
    });
    renderFeature(transport);

    expect(await screen.findByRole('checkbox', { name: '选择 表情包' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: '预览已选' }));
    expect(screen.getByText('已选 1 条')).toBeInTheDocument();
    expect(screen.getByText(/更新后还需重载输入法/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '进入确认' }));
    await user.click(screen.getByRole('checkbox', { name: /只加入上方 1 条/ }));
    await user.click(screen.getByRole('button', { name: '确认加入词库' }));

    expect(await screen.findByText('已加入 · 等待重载')).toBeInTheDocument();
    expect(screen.getByText('词条已加入用户词库')).toBeInTheDocument();
    expect(screen.getByText(/重载后用实际输入与选词结果确认效果/)).toBeInTheDocument();
    const applyRequest = transport.requests.find((call) => call.request.pathId === 'input.lexicon.apply')?.request;
    expect(applyRequest?.body).toEqual({
      reviewToken: 'a'.repeat(64),
      selectedKeys: ['表情包\tbiao qing bao'],
      confirmText: 'APPLY_REVIEWED_RIME_LEXICON',
      project: 'wisdom-weasel-rag-ime',
      limit: 200,
    });

    await user.click(screen.getByRole('button', { name: '撤销这次更新' }));
    expect(await screen.findByText('已撤销 · 等待重载')).toBeInTheDocument();
    const rollbackRequest = transport.requests.find((call) => call.request.pathId === 'input.lexicon.rollback')?.request;
    expect(rollbackRequest?.body).toEqual({ rollbackId: 'rollback-lexicon-1' });
  });

  it('does not render a write receipt when the server rejects a stale review token', async () => {
    const user = userEvent.setup();
    renderFeature(new MockControlTransport({
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': settings,
        'configuration.schema': schema,
        'input.lexicon.review': review,
        'input.lexicon.apply': {
          schemaVersion: 'rag-ime.rime-lexicon-review.v1',
          ok: false,
          applied: false,
          reason: 'review_token_stale',
        },
        'input.lexicon.rollback': {},
      },
    }));

    await screen.findByRole('checkbox', { name: '选择 表情包' });
    await user.click(screen.getByRole('button', { name: '预览已选' }));
    await user.click(screen.getByRole('button', { name: '进入确认' }));
    await user.click(screen.getByRole('checkbox', { name: /只加入上方 1 条/ }));
    await user.click(screen.getByRole('button', { name: '确认加入词库' }));

    expect(await screen.findByText('词库审阅已变化，请刷新后重新选择并确认。')).toBeInTheDocument();
    expect(screen.queryByText('已加入 · 等待重载')).not.toBeInTheDocument();
  });
});

function renderFeature(transport: MockControlTransport) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <InputMethodFeature />
        </QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
}
