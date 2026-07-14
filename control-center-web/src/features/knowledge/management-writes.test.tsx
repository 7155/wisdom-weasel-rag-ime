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
import { KnowledgeFeature } from '.';

const now = 1_784_006_400_000;
const databaseHash = 'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc';

afterEach(cleanup);

describe('Knowledge write boundaries', () => {
  it('starts and cancels a real knowledge session without inventing a receipt', async () => {
    const user = userEvent.setup();
    const transport = renderKnowledge();
    await screen.findByRole('heading', { name: '知识库', level: 1 });
    await user.type(await screen.findByPlaceholderText('输入一个明确的知识任务'), '梳理 Agent ControlTransport 的写入边界');

    const workflow = screen.getByText('启动知识任务', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '预览任务' }));
    expect(within(workflow as HTMLElement).getByText(/梳理 Agent ControlTransport/)).toBeInTheDocument();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '进入确认' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认启动' }));

    expect(await within(workflow as HTMLElement).findByText('knowledge:test-session')).toBeInTheDocument();
    expect(findRequest(transport, 'knowledge.start')).toMatchObject({
      body: {
        question: '梳理 Agent ControlTransport 的写入边界',
        mode: 'knowledge_answer',
        includeNotion: false,
        clientId: 'control-center-web',
      },
    });
    expect(within(workflow as HTMLElement).queryByText('演练 / 未执行')).not.toBeInTheDocument();

    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '取消任务' }));
    expect(await within(workflow as HTMLElement).findByText('已取消')).toBeInTheDocument();
    expect(findRequest(transport, 'knowledge.cancel')).toMatchObject({ body: { sessionId: 'knowledge:test-session' } });
  });

  it('binds database apply preview to its receipt and rollback token', async () => {
    const user = userEvent.setup();
    const transport = renderKnowledge();
    await screen.findByRole('heading', { name: '知识库', level: 1 });
    const workflow = (await screen.findByText('应用整理草案', { selector: 'strong' })).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await waitFor(() => expect(within(workflow as HTMLElement).getByRole('button', { name: '预览操作' })).toBeEnabled());
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '预览操作' }));

    expect(await within(workflow as HTMLElement).findByText('应用数据库整理')).toBeInTheDocument();
    expect(findRequest(transport, 'knowledge.database.apply.preview')).toMatchObject({ body: { runId: 'book-run:1' } });
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '进入确认' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认并应用' }));

    expect(await within(workflow as HTMLElement).findByText('receipt-database-apply')).toBeInTheDocument();
    expect(findRequest(transport, 'knowledge.database.apply')).toMatchObject({
      body: {
        runId: 'book-run:1',
        confirm: 'apply',
        previewToken: 'preview-database-apply',
        payloadSha256: databaseHash,
        expectedRuntimeRevision: 9,
      },
    });
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '回滚' }));
    expect(await within(workflow as HTMLElement).findByText('receipt-database-rollback')).toBeInTheDocument();
    expect(findRequest(transport, 'knowledge.database.rollback')).toMatchObject({
      body: {
        runId: 'book-run:1',
        confirm: 'rollback',
        receiptId: 'receipt-database-apply',
        rollbackToken: 'rollback-database-apply',
        payloadSha256: databaseHash,
      },
    });
  });
});

class KnowledgeTransport implements ControlTransport {
  readonly kind = 'mock' as const;
  readonly requests: ControlRequest[] = [];

  async capabilities(): Promise<FrontendCapabilities> {
    return {
      schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
      transport: 'mock',
      routeIds: [
        'knowledge.routeStatus',
        'knowledge.status',
        'knowledge.start',
        'knowledge.cancel',
        'knowledge.database.apply.preview',
        'knowledge.database.apply',
        'knowledge.database.rollback',
      ] as unknown as ControlPathId[],
      features: { managementWorkContract: true, knowledgeDatabaseWorkContract: true },
      native: { pickFiles: false, managedAgentImageImport: false, revealPath: false, approvedExternalActions: false, keychain: false, tcc: false },
    };
  }

  async request<Response = unknown>(request: ControlRequest): Promise<Response> {
    this.requests.push(request);
    const pathId = String(request.pathId);
    if (pathId === 'knowledge.routeStatus') return {
      ok: true,
      deepseekReady: true,
      notion: { submitConfigured: false, pollConfigured: false, ready: false, pollMode: 'none' },
    } as Response;
    if (pathId === 'knowledge.status') return knowledgeStatus() as Response;
    if (pathId === 'knowledge.start') return { ok: true, sessionId: 'knowledge:test-session', status: 'queued', stage: 'queued' } as Response;
    if (pathId === 'knowledge.cancel') return { ok: true, sessionId: 'knowledge:test-session', status: 'cancelled', stage: 'cancelled' } as Response;
    if (pathId === 'knowledge.database.apply.preview') return {
      schemaVersion: 'rag-ime.management-work-preview.v1',
      ok: true,
      previewToken: 'preview-database-apply',
      pathId: 'knowledge.database.apply',
      payloadSha256: databaseHash,
      expectedRevision: { runtimeRevision: 9, subjectRevision: 'sha256:run-revision' },
      expiresAtMs: Date.now() + 60_000,
      requiredConfirm: 'apply',
      summary: { title: '应用数据库整理', items: ['应用 2 条已选择差异', '重建本地检索索引'], risk: 'R2' },
    } as Response;
    if (pathId === 'knowledge.database.apply') return receipt('knowledge.database.apply', 'receipt-database-apply', 'rollback-database-apply', true) as Response;
    if (pathId === 'knowledge.database.rollback') return receipt('knowledge.database.rollback', 'receipt-database-rollback', '', false) as Response;
    throw new Error(`Unexpected request: ${pathId}`);
  }

  subscribe<Event = unknown>(_request: ControlSubscription, _observer: ControlEventObserver<Event>): () => void {
    return () => {};
  }
}

function renderKnowledge(): KnowledgeTransport {
  const transport = new KnowledgeTransport();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}><KnowledgeFeature /></QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  return transport;
}

function findRequest(transport: KnowledgeTransport, pathId: string): ControlRequest | undefined {
  return transport.requests.find((request) => String(request.pathId) === pathId);
}

function knowledgeStatus() {
  return {
    ok: true,
    sessionId: 'knowledge:existing',
    status: 'ready',
    stage: 'ready',
    evidence: [],
    sources: [],
    result: { plan: { runId: 'book-run:1', status: 'draft' } },
  };
}

function receipt(pathId: string, receiptId: string, rollbackToken: string, rollbackAvailable: boolean) {
  return {
    ok: true,
    receiptId,
    pathId,
    payloadSha256: databaseHash,
    appliedAtMs: now,
    auditId: 12,
    rollbackAvailable,
    rollbackToken,
    restartComponents: [],
  };
}
