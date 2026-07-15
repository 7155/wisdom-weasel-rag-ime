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

    expect(await screen.findByText('正在读取模式')).toBeInTheDocument();
    resolveOverview({ ok: true, profile: '安全模式' });

    await waitFor(() => expect(screen.getByText('安全模式')).toBeInTheDocument());
    expect(screen.getByText('切换运行模式')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '当前不可用' })).not.toBeInTheDocument();
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
    expect(screen.getAllByText('自定义设置').length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent('pathId');
    expect(document.body).not.toHaveTextContent('provider_internal_v3');
    expect(document.body).not.toHaveTextContent('/api/internal/schema');
  });

  it('groups settings by backend schema responsibility and keeps controls disabled without the write contract', async () => {
    renderFeature(new MockControlTransport({
      routes: {
        'input.source.get': {
          ok: true,
          inputSourceId: 'im.rime.inputmethod.Squirrel.Hans',
          selected: true,
          typingReady: true,
          readinessState: 'ready',
        },
        'overview.get': {
          ok: true,
          profile: '标准模式',
          components: {
            sidecar: { ok: true, status: 'ready', detail: '后台服务已连接' },
            predictor: { ok: true, status: 'ready', detail: '本机模型已加载' },
            foregroundContext: { ok: false, status: 'degraded', detail: '等待前台应用' },
          },
        },
        'configuration.settings': {
          ok: true,
          settings: {
            interaction: { postCommit: { enabled: true } },
            display: { maxPostCommitCandidates: 5 },
          },
        },
        'configuration.schema': {
          ok: true,
          sections: [
            schema.sections[0],
            {
              id: 'display',
              label: '显示',
              fields: [{
                key: 'display.maxPostCommitCandidates',
                type: 'integer',
                label: '续写候选数量',
                description: '限制输入完成后显示的候选数',
                applyMode: 'reload',
              }],
            },
          ],
        },
        'input.lexicon.review': emptyReview,
      },
    }));

    expect(await screen.findByRole('heading', { level: 3, name: '输入体验' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '候选界面' })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: '输入法运行链状态' }).children).toHaveLength(4);
    expect(screen.getByText('本机模型已加载')).toBeInTheDocument();
    expect(screen.getByText('降级')).toBeInTheDocument();
    expect(screen.getByLabelText('续写候选数量')).toHaveValue(5);
    expect(screen.getByLabelText('续写候选数量').closest('.input-setting-editor-row')).not.toBeNull();
    expect(screen.getByText(/需重新载入/)).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: '提交后预测' })).toBeDisabled();
    expect(screen.getAllByRole('button', { name: '尚不可预览' }).every((button) => button.hasAttribute('disabled'))).toBe(true);
  });

  it('switches runtime mode only after preview and explicit approval, then supports rollback', async () => {
    const user = userEvent.setup();
    const payloadSha256 = 'c'.repeat(64);
    const transport = new MockControlTransport({
      capabilities: {
        features: {
          managementWorkContract: true,
          configurationSettingsWorkContract: true,
        },
      },
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: 'v1-proof' },
        'configuration.settings': {
          ok: true,
          runtimeRevision: 9,
          settings: {
            interaction: { postCommit: { enabled: true } },
            memory: { enabled: true },
            activeRag: { allowRemoteModel: true },
            rag: { lanes: { tagMemo: true, timeDailyBook: true } },
          },
        },
        'configuration.schema': { ok: true, sections: [] },
        'configuration.settings.preview': {
          ok: true,
          pathId: 'configuration.settings.apply',
          previewToken: 'preview-safe-mode',
          payloadSha256,
          requiredConfirm: 'apply',
          expiresAtMs: Date.now() + 60_000,
          expectedRevision: { runtimeRevision: 9 },
          summary: { title: '应用控制中心设置', items: ['更新运行模式'], risk: 'R2' },
        },
        'configuration.settings.apply': {
          ok: true,
          pathId: 'configuration.settings.apply',
          receiptId: 'receipt-safe-mode',
          payloadSha256,
          appliedAtMs: Date.now(),
          rollbackAvailable: true,
          rollbackToken: 'rollback-safe-mode',
        },
        'configuration.settings.rollback': {
          ok: true,
          pathId: 'configuration.settings.rollback',
          receiptId: 'receipt-safe-mode-rollback',
          payloadSha256,
          appliedAtMs: Date.now(),
          rollbackAvailable: false,
          rollbackToken: '',
        },
        'input.lexicon.review': emptyReview,
      },
    });
    renderFeature(transport);

    await user.click(await screen.findByRole('radio', { name: '安全' }));
    expect(screen.getByText('3 项设置将发生变化')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '预览操作' }));

    expect(await screen.findByText('切换到安全模式？')).toBeInTheDocument();
    const previewRequest = transport.requests.find(({ request }) => request.pathId === 'configuration.settings.preview')?.request;
    expect(previewRequest?.body).toEqual({
      changes: {
        'interaction.postCommit.enabled': false,
        'memory.enabled': false,
        'activeRag.allowRemoteModel': false,
      },
      expectedRuntimeRevision: 9,
    });

    await user.click(screen.getByRole('button', { name: '进入确认' }));
    await user.click(screen.getByRole('checkbox', { name: '只执行上方已绑定的变更' }));
    await user.click(screen.getByRole('button', { name: '确认并应用' }));

    expect(await screen.findByText('本机操作已记录')).toBeInTheDocument();
    const applyRequest = transport.requests.find(({ request }) => request.pathId === 'configuration.settings.apply')?.request;
    expect(applyRequest?.body).toEqual({
      changes: {
        'interaction.postCommit.enabled': false,
        'memory.enabled': false,
        'activeRag.allowRemoteModel': false,
      },
      expectedRuntimeRevision: 9,
      previewToken: 'preview-safe-mode',
      payloadSha256,
      confirmText: 'apply',
    });

    await user.click(screen.getByRole('button', { name: '撤销这次操作' }));
    expect(await screen.findByText('已恢复到操作前')).toBeInTheDocument();
    const rollbackRequest = transport.requests.find(({ request }) => request.pathId === 'configuration.settings.rollback')?.request;
    expect(rollbackRequest?.body).toEqual({
      receiptId: 'receipt-safe-mode',
      rollbackToken: 'rollback-safe-mode',
      payloadSha256,
      confirmText: 'rollback',
    });
  });

  it('previews, explicitly approves, applies, and rolls back common input settings through the real settings routes', async () => {
    const user = userEvent.setup();
    const payloadSha256 = 'b'.repeat(64);
    const editableSchema = {
      ok: true,
      sections: [
        {
          id: 'interaction',
          fields: [{
            key: 'interaction.postCommit.numberKeys',
            type: 'enum',
            label: 'Post-commit 数字键',
            options: ['pass_through', 'select_prediction'],
            applyMode: 'live',
          }],
        },
        {
          id: 'display',
          fields: [{
            key: 'display.maxPostCommitCandidates',
            type: 'integer',
            label: 'Post-commit 候选数量',
            min: 1,
            max: 8,
            applyMode: 'restart_input_method',
          }],
        },
      ],
    };
    const transport = new MockControlTransport({
      capabilities: {
        features: {
          managementWorkContract: true,
          configurationSettingsWorkContract: true,
        },
      },
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': {
          ok: true,
          runtimeRevision: 7,
          settings: {
            interaction: { postCommit: { numberKeys: 'pass_through' } },
            display: { maxPostCommitCandidates: 5 },
          },
        },
        'configuration.schema': editableSchema,
        'configuration.settings.preview': {
          ok: true,
          pathId: 'configuration.settings.apply',
          previewToken: 'preview-input-settings',
          payloadSha256,
          requiredConfirm: 'apply',
          expiresAtMs: Date.now() + 60_000,
          expectedRevision: { runtimeRevision: 7 },
          summary: { title: '应用控制中心设置', items: ['更新输入设置'], risk: 'R2' },
        },
        'configuration.settings.apply': {
          ok: true,
          pathId: 'configuration.settings.apply',
          receiptId: 'receipt-input-settings',
          payloadSha256,
          appliedAtMs: Date.now(),
          rollbackAvailable: true,
          rollbackToken: 'rollback-input-settings',
        },
        'configuration.settings.rollback': {
          ok: true,
          pathId: 'configuration.settings.rollback',
          receiptId: 'receipt-input-settings-rollback',
          payloadSha256,
          appliedAtMs: Date.now(),
          rollbackAvailable: false,
          rollbackToken: '',
        },
        'input.lexicon.review': emptyReview,
      },
    });
    renderFeature(transport);

    await user.selectOptions(
      await screen.findByLabelText('预测出现时的数字键'),
      'select_prediction',
    );
    const candidateCount = screen.getByLabelText('续写候选数量');
    await user.clear(candidateCount);
    await user.type(candidateCount, '6');
    await user.click(screen.getByRole('button', { name: '预览操作' }));

    await screen.findByText('应用这些输入设置？');
    const previewRequest = transport.requests.find(({ request }) => request.pathId === 'configuration.settings.preview')?.request;
    expect(previewRequest?.body).toEqual({
      changes: {
        'interaction.postCommit.numberKeys': 'select_prediction',
        'display.maxPostCommitCandidates': 6,
      },
      expectedRuntimeRevision: 7,
    });

    await user.click(screen.getByRole('button', { name: '进入确认' }));
    const approve = screen.getByRole('checkbox', { name: '只执行上方已绑定的变更' });
    expect(screen.getByRole('button', { name: '确认并应用' })).toBeDisabled();
    await user.click(approve);
    await user.click(screen.getByRole('button', { name: '确认并应用' }));

    expect(await screen.findByText('本机操作已记录')).toBeInTheDocument();
    const applyRequest = transport.requests.find(({ request }) => request.pathId === 'configuration.settings.apply')?.request;
    expect(applyRequest?.body).toEqual({
      changes: {
        'interaction.postCommit.numberKeys': 'select_prediction',
        'display.maxPostCommitCandidates': 6,
      },
      expectedRuntimeRevision: 7,
      previewToken: 'preview-input-settings',
      payloadSha256,
      confirmText: 'apply',
    });

    await user.click(screen.getByRole('button', { name: '撤销这次操作' }));
    expect(await screen.findByText('已恢复到操作前')).toBeInTheDocument();
    const rollbackRequest = transport.requests.find(({ request }) => request.pathId === 'configuration.settings.rollback')?.request;
    expect(rollbackRequest?.body).toEqual({
      receiptId: 'receipt-input-settings',
      rollbackToken: 'rollback-input-settings',
      payloadSha256,
      confirmText: 'rollback',
    });
  });

  it('does not enable input setting writes when any settings work-contract route is missing', async () => {
    renderFeature(new MockControlTransport({
      capabilities: {
        features: {
          managementWorkContract: true,
          configurationSettingsWorkContract: true,
        },
        routeIds: [
          'input.source.get',
          'overview.get',
          'configuration.settings',
          'configuration.schema',
          'configuration.settings.preview',
          'configuration.settings.apply',
        ],
      },
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': {
          ok: true,
          runtimeRevision: 4,
          settings: { interaction: { postCommit: { numberKeys: 'pass_through' } } },
        },
        'configuration.schema': {
          ok: true,
          sections: [{
            id: 'interaction',
            fields: [{
              key: 'interaction.postCommit.numberKeys',
              type: 'enum',
              options: ['pass_through', 'select_prediction'],
            }],
          }],
        },
      },
    }));

    expect(await screen.findByLabelText('预测出现时的数字键')).toBeDisabled();
    expect(screen.getByRole('radio', { name: '安全' })).toBeDisabled();
    expect(screen.getAllByText(/没有提供完整的设置预览、应用与撤销能力/)).toHaveLength(2);
    expect(screen.getAllByRole('button', { name: '尚不可预览' }).every((button) => button.hasAttribute('disabled'))).toBe(true);
  });

  it('keeps settings visible when the input source query fails', async () => {
    renderFeature(new MockControlTransport({
      routes: {
        'input.source.get': () => { throw new Error('source probe unavailable'); },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': settings,
        'configuration.schema': schema,
        'input.lexicon.review': emptyReview,
      },
    }));

    expect(await screen.findByText('读取失败')).toBeInTheDocument();
    expect(screen.getByText('提交后预测')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: '提交后预测' })).toBeChecked();
  });

  it('refreshes every page query through the live transport', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'input.source.get': { ok: true, typingReady: true, readinessState: 'ready' },
        'overview.get': { ok: true, profile: '标准模式' },
        'configuration.settings': settings,
        'configuration.schema': schema,
        'input.lexicon.review': emptyReview,
      },
    });
    renderFeature(transport);

    await screen.findByText('暂无待审词条');
    const before = new Map(
      ['input.source.get', 'overview.get', 'configuration.settings', 'configuration.schema', 'input.lexicon.review']
        .map((pathId) => [pathId, transport.requests.filter((call) => call.request.pathId === pathId).length]),
    );
    await user.click(screen.getByRole('button', { name: '刷新' }));

    await waitFor(() => {
      for (const [pathId, count] of before) {
        expect(transport.requests.filter((call) => call.request.pathId === pathId).length).toBeGreaterThan(count);
      }
    });
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
