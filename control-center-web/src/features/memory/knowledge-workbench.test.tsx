import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
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
import { PersonalKnowledgeWorkbench } from './PersonalKnowledgeWorkbench';

afterEach(cleanup);

describe('Knowledge write boundaries', () => {
  it('visualizes only returned route gates and supports evidence source filtering', async () => {
    const user = userEvent.setup();
    const transport = renderKnowledge();
    expect(await screen.findByRole('region', { name: '知识来源可用状态' })).toBeInTheDocument();
    expect(screen.getByText('回答生成', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getAllByText('未连接').length).toBeGreaterThan(0);
    expect(screen.queryByText('explicit_active_rag_knowledge_provider')).not.toBeInTheDocument();
    expect(screen.queryByText('deepseek-v4')).not.toBeInTheDocument();
    expect(screen.queryByText('worker_url · status_channel')).not.toBeInTheDocument();
    expect(findRequest(transport, 'knowledge.status')).toBeUndefined();

    await user.type(screen.getByPlaceholderText('输入一个明确的知识任务'), '检查知识来源');
    const workflow = screen.getByText('启动知识任务', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '查看任务内容' }));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认任务内容' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '开始整理' }));

    const sourceDistribution = await screen.findByRole('group', { name: '证据来源分布' });
    await user.click(within(sourceDistribution).getByRole('button', { name: /远程笔记1/ }));
    const evidenceList = screen.getByRole('listbox', { name: '知识证据' });
    expect(within(evidenceList).getAllByRole('option')).toHaveLength(1);
    await user.click(within(evidenceList).getByRole('option', { name: /远程规范/ }));
    const detail = screen.getByRole('article', { name: '远程规范 证据详情' });
    expect(within(detail).getByText('Notion')).toBeInTheDocument();
    expect(within(detail).queryByText('notion-page-1')).not.toBeInTheDocument();
    expect(within(detail).getByRole('link', { name: /打开来源/ })).toHaveAttribute('href', 'https://notion.so/example');
  });

  it('starts and cancels a real knowledge session without inventing a receipt', async () => {
    const user = userEvent.setup();
    const transport = renderKnowledge();
    await screen.findByRole('heading', { name: '个人知识整理', level: 2 });
    await user.type(await screen.findByPlaceholderText('输入一个明确的知识任务'), '梳理 Agent ControlTransport 的写入边界');

    const workflow = screen.getByText('启动知识任务', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '查看任务内容' }));
    expect(within(workflow as HTMLElement).getByText(/梳理 Agent ControlTransport/)).toBeInTheDocument();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认任务内容' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '开始整理' }));

    expect(await within(workflow as HTMLElement).findByText('知识任务正在处理')).toBeInTheDocument();
    expect(within(workflow as HTMLElement).queryByText('knowledge:test-session')).not.toBeInTheDocument();
    expect(findRequest(transport, 'knowledge.start')).toMatchObject({
      body: {
        question: '梳理 Agent ControlTransport 的写入边界',
        mode: 'knowledge_answer',
        includeNotion: false,
        clientId: 'control-center-web',
      },
    });
    expect(within(workflow as HTMLElement).queryByText('演练 / 未执行')).not.toBeInTheDocument();

    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '停止整理' }));
    expect(await within(workflow as HTMLElement).findByText('本次知识任务已停止')).toBeInTheDocument();
    expect(findRequest(transport, 'knowledge.cancel')).toMatchObject({ body: { sessionId: 'knowledge:test-session' } });
  });

  it('keeps the task form and accepted session visible when progress polling fails', async () => {
    const user = userEvent.setup();
    renderKnowledge(true);
    await user.type(await screen.findByPlaceholderText('输入一个明确的知识任务'), '保留这项知识任务');
    const workflow = screen.getByText('启动知识任务', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '查看任务内容' }));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认任务内容' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '开始整理' }));

    expect(await screen.findByText('暂时无法更新任务')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('输入一个明确的知识任务')).toHaveValue('保留这项知识任务');
    expect(screen.getByText('知识任务正在处理')).toBeInTheDocument();
    expect(screen.queryByText('GET /api/knowledge/status failed: sessionId')).not.toBeInTheDocument();
  });

});

class KnowledgeTransport implements ControlTransport {
  readonly kind = 'mock' as const;
  readonly requests: ControlRequest[] = [];

  constructor(private readonly failStatus = false) {}

  async capabilities(): Promise<FrontendCapabilities> {
    return {
      schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
      transport: 'mock',
      routeIds: [
        'knowledge.routeStatus',
        'knowledge.status',
        'knowledge.start',
        'knowledge.cancel',
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
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      modes: ['knowledge_answer', 'recall'],
      streaming: { knowledgeWorkbench: true, activeRag: true },
      deepseekRoute: {
        route: 'explicit_active_rag_knowledge_provider',
        remoteReady: true,
        provider: 'deepseek',
        selectedModel: 'deepseek-v4',
        passivePostCommitRemoteAllowed: false,
      },
      notion: {
        submitConfigured: false,
        pollConfigured: false,
        ready: false,
        pollMode: 'none',
        missing: ['worker_url', 'status_channel'],
      },
    } as Response;
    if (pathId === 'knowledge.status') {
      if (this.failStatus) throw new Error('GET /api/knowledge/status failed: sessionId');
      return knowledgeStatus() as Response;
    }
    if (pathId === 'knowledge.start') return { ok: true, sessionId: 'knowledge:test-session', status: 'queued', stage: 'queued' } as Response;
    if (pathId === 'knowledge.cancel') return { ok: true, sessionId: 'knowledge:test-session', status: 'cancelled', stage: 'cancelled' } as Response;
    throw new Error(`Unexpected request: ${pathId}`);
  }

  subscribe<Event = unknown>(_request: ControlSubscription, _observer: ControlEventObserver<Event>): () => void {
    return () => {};
  }
}

function renderKnowledge(failStatus = false): KnowledgeTransport {
  const transport = new KnowledgeTransport(failStatus);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}><PersonalKnowledgeWorkbench /></QueryClientProvider>
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
    evidence: [
      { sourceId: 'atom-1', title: 'ControlTransport 边界', excerpt: '写请求必须绑定允许的 pathId。', sourceType: 'memory_atom', source: 'sqlite', score: .91 },
      { sourceId: 'book-1', title: 'Agent 工程手册', excerpt: '先读取本地证据，再决定是否启用远程生成。', sourceType: 'memory_book', source: 'sqlite', score: .83 },
    ],
    sources: [
      { sourceId: 'notion-page-1', title: '远程规范', excerpt: 'Notion 只在显式知识任务中使用。', sourceType: 'notion', provider: 'Notion', url: 'https://notion.so/example' },
    ],
    result: {},
  };
}
