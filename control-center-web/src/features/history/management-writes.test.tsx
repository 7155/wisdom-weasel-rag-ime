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
import { HistoryFeature } from '.';

const hash = 'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';

afterEach(cleanup);

describe('History WorkContract UI', () => {
  it('renders the history filters as one responsive search toolbar', async () => {
    renderHistory();

    const toolbar = await screen.findByRole('search', { name: '筛选输入记录' });
    expect(toolbar).toHaveClass('history-filter-toolbar');
    expect(within(toolbar).getByRole('textbox', { name: '搜索' })).toBeInTheDocument();
    expect(within(toolbar).getByRole('combobox', { name: '来源' })).toBeInTheDocument();
    expect(within(toolbar).getByRole('button', { name: '搜索' })).toBeInTheDocument();
  });

  it('opens a real full-text detail from the keyboard and exposes only verified server state', async () => {
    const user = userEvent.setup();
    const transport = renderHistory();
    const openDetail = await screen.findByRole('button', { name: /查看 .* 的输入详情/ });

    openDetail.focus();
    await user.keyboard('{Enter}');

    const dialog = await screen.findByRole('dialog', { name: '输入详情' });
    expect(within(dialog).getByText('这是服务端按事件读取的完整输入，不是列表摘要。')).toBeInTheDocument();
    expect(within(dialog).getByText('豆包语音')).toBeInTheDocument();
    expect(within(dialog).getAllByText('采用')).toHaveLength(2);
    expect(within(dialog).getByText('2 次')).toBeInTheDocument();
    expect(within(dialog).getByText('1 次')).toBeInTheDocument();
    expect(within(dialog).getByText('澄')).toBeInTheDocument();
    expect(within(dialog).getByRole('heading', { name: '辅助上下文' })).toBeInTheDocument();
    expect(within(dialog).getByText('前面正在核对来源筛选，随后完成了当前输入。')).toBeInTheDocument();
    expect(within(dialog).getByText('辅助功能读取')).toBeInTheDocument();
    expect(within(dialog).getByText('未关联')).toBeInTheDocument();
    expect(within(dialog).queryByText('wisdom-weasel-rag-ime')).not.toBeInTheDocument();
    expect(findRequest(transport, 'history.detail')).toMatchObject({ query: { eventId: 81 } });
    await user.keyboard('{Escape}');
    await waitFor(() => expect(openDetail).toHaveFocus());
    expect(historyPage().items[0]).not.toHaveProperty('text');
  });

  it('binds a selected event to tombstone apply and rollback receipts', async () => {
    const user = userEvent.setup();
    const transport = renderHistory();
    await screen.findByRole('heading', { name: '输入记录', level: 1 });
    await user.click(await screen.findByRole('combobox', { name: '选择记录' }));
    await user.click(await screen.findByRole('option', { name: /完成了/ }));
    const workflow = screen.getByText('不再用于记忆', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();

    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '查看影响' }));
    await waitFor(() => expect(findRequest(transport, 'history.tombstone.preview')).toMatchObject({
      body: {
        eventId: 81,
        reason: 'control-center-history',
        expectedRuntimeRevision: 9,
      },
    }));
    expect(await within(workflow as HTMLElement).findByText('隐藏输入历史记录')).toBeInTheDocument();
    expect(within(workflow as HTMLElement).queryByText('记录 ID: 81')).not.toBeInTheDocument();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认这些更改' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认执行' }));

    expect(await within(workflow as HTMLElement).findByText('这次更改已安全记录')).toBeInTheDocument();
    expect(findRequest(transport, 'history.tombstone.apply')).toMatchObject({
      body: {
        eventId: 81,
        previewToken: 'preview-history-hide',
        payloadSha256: hash,
        confirmText: 'apply',
      },
    });
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '撤销这次更改' }));
    expect(await within(workflow as HTMLElement).findByText('已恢复到更改前')).toBeInTheDocument();
    expect(findRequest(transport, 'history.tombstone.rollback')).toMatchObject({
      body: {
        receiptId: 'receipt-history-hide',
        rollbackToken: 'rollback-history-hide',
        payloadSha256: hash,
        confirmText: 'rollback',
      },
    });
  });

  it('does not offer a fake negative-feedback mutation', async () => {
    renderHistory();
    expect(await screen.findByText('选择一条记录后，可以让它退出后续召回。原始记录仍会保留，操作也可以撤销。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '演练流程' })).not.toBeInTheDocument();
  });
});

class HistoryTransport implements ControlTransport {
  readonly kind = 'mock' as const;
  readonly requests: ControlRequest[] = [];

  async capabilities(): Promise<FrontendCapabilities> {
    return {
      schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
      transport: 'mock',
      routeIds: [
        'history.page',
        'history.detail',
        'history.tombstone.preview',
        'history.tombstone.apply',
        'history.tombstone.rollback',
      ] as ControlPathId[],
      features: { managementWorkContract: true, historyWorkContract: true },
      native: { pickFiles: false, managedAgentImageImport: false, revealPath: false, approvedExternalActions: false, keychain: false, tcc: false },
    };
  }

  async request<Response = unknown>(request: ControlRequest): Promise<Response> {
    this.requests.push(request);
    if (request.pathId === 'history.page') return historyPage() as Response;
    if (request.pathId === 'history.detail') return historyDetail() as Response;
    if (request.pathId === 'history.tombstone.preview') return {
      schemaVersion: 'rag-ime.management-work-preview.v1',
      ok: true,
      previewToken: 'preview-history-hide',
      pathId: 'history.tombstone.apply',
      payloadSha256: hash,
      expectedRevision: { runtimeRevision: 9, subjectRevision: 'sha256:before' },
      expiresAtMs: Date.now() + 60_000,
      requiredConfirm: 'apply',
      summary: {
        title: '隐藏输入历史记录',
        items: ['记录 ID: 81', '停止参与后续召回。'],
        risk: 'R2',
      },
    } as Response;
    if (request.pathId === 'history.tombstone.apply') return receipt(
      'history.tombstone.apply',
      'receipt-history-hide',
      'rollback-history-hide',
      true,
    ) as Response;
    if (request.pathId === 'history.tombstone.rollback') return receipt(
      'history.tombstone.rollback',
      'receipt-history-rollback',
      '',
      false,
    ) as Response;
    throw new Error(`Unexpected request: ${request.pathId}`);
  }

  subscribe<Event = unknown>(_request: ControlSubscription, _observer: ControlEventObserver<Event>): () => void {
    return () => {};
  }
}

function renderHistory(): HistoryTransport {
  const transport = new HistoryTransport();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}><HistoryFeature /></QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  return transport;
}

function findRequest(transport: HistoryTransport, pathId: string): ControlRequest | undefined {
  return transport.requests.find((request) => String(request.pathId) === pathId);
}

function historyPage() {
  return {
    ok: true,
    runtimeRevision: 9,
    items: [{
      id: 81,
      createdAtMs: 1_784_006_400_000,
      source: 'rime_commit',
      app: 'TextEdit',
      project: 'wisdom-weasel-rag-ime',
      textPreview: '完成了...',
      textChars: 6,
      contextHash: 'sha256:test',
    }],
    nextCursor: '',
    limit: 50,
    rawTextVisible: false,
  };
}

function historyDetail() {
  return {
    ok: true,
    runtimeRevision: 9,
    rawTextVisible: true,
    item: {
      id: 81,
      createdAtMs: 1_784_006_400_000,
      source: 'voice',
      text: '这是服务端按事件读取的完整输入，不是列表摘要。',
      textChars: 23,
      app: 'TextEdit',
      project: 'wisdom-weasel-rag-ime',
      provider: 'volcengine-asr',
      candidateRank: 1,
      groupId: 'document:test',
      groupLevel: 'document',
      auxiliaryContext: {
        available: true,
        text: '前面正在核对来源筛选，随后完成了当前输入。',
        textChars: 22,
        truncated: false,
        hasAdditionalText: true,
        captureSource: 'accessibility',
        captureMode: 'accessibility_semantics',
        fallbackReason: '',
        fieldContextChars: 22,
        imeBufferChars: 8,
        modelRequestLinked: false,
      },
      status: 'active',
      feedback: {
        available: true,
        acceptedCount: 2,
        skippedCount: 1,
        pinned: false,
        downranked: false,
        deleted: false,
        updatedAtMs: 1_784_006_400_000,
        latestAction: 'accept',
        latestActionAtMs: 1_784_006_400_000,
      },
    },
  };
}

function receipt(pathId: string, receiptId: string, rollbackToken: string, rollbackAvailable: boolean) {
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
    rollbackAuthority: { eventId: 81 },
    restartComponents: [],
  };
}
