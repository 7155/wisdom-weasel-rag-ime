import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { MockControlTransport } from '@/test/mock-transport';
import { KnowledgeJobsPanel } from './document-workspace';
import { KnowledgeFeature } from './index';

vi.mock('react-virtuoso', () => ({ Virtuoso: ({ data, itemContent }: { data: unknown[]; itemContent: (index: number, item: unknown) => ReactNode }) => <div>{data.map((item, index) => <div key={index}>{itemContent(index, item)}</div>)}</div> }));
afterEach(cleanup);

describe('Knowledge processing recovery', () => {
  it('does not report zero jobs before the first response arrives', () => {
    render(<TooltipProvider><KnowledgeJobsPanel cancelError={null} cancellingJobId="" error={null} jobs={[]} loading onCancel={vi.fn()} onRefresh={vi.fn()} /></TooltipProvider>);
    expect(screen.getByText('正在读取处理记录…')).toBeInTheDocument();
    expect(screen.queryByText('0 个进行中 · 0 条记录')).not.toBeInTheDocument();
    expect(screen.queryByText('还没有处理记录')).not.toBeInTheDocument();
  });

  it('distinguishes an unread failed list from an empty history and permits retry', async () => {
    const refresh = vi.fn();
    const user = userEvent.setup();
    render(<TooltipProvider><KnowledgeJobsPanel cancelError={null} cancellingJobId="" error={new Error('jobs unavailable')} jobs={[]} loading={false} onCancel={vi.fn()} onRefresh={refresh} /></TooltipProvider>);
    expect(screen.getByText('任务记录暂不可用')).toBeInTheDocument();
    expect(screen.queryByText('还没有处理记录')).not.toBeInTheDocument();
    expect(screen.queryByText('0 个进行中 · 0 条记录')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '刷新处理记录' }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('releases the submitted reparse state when the authoritative file is ready again', async () => {
    const base = { id: 'kb-secondary', name: '处理资料', documentCount: 1, status: 'ready' };
    const source = { id: 'source-1', baseId: base.id, name: 'source.md', status: 'ready', revision: 4, mimeType: 'text/markdown', chunkCount: 1 };
    const transport = new MockControlTransport({ routes: {
      'knowledgeBases.list': { items: [base] }, 'knowledgeBases.get': { base },
      'knowledgeBases.documents.list': { items: [source] },
      'knowledgeBases.document.get': { document: source, chunks: { items: [], total: 0 } },
      'knowledgeBases.document.retry': { ok: true },
      'knowledgeBases.jobs.list': { items: [] }, 'knowledgeWorker.health': { ok: true, status: 'ready' },
      'knowledgeParsers.list': { items: [] }, 'knowledgeEmbedding.profile': {}, 'configuration.settings': {},
    } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<MemoryRouter initialEntries={['/knowledge?base=kb-secondary&tab=materials']}><TooltipProvider><ControlTransportProvider transport={transport}><QueryClientProvider client={client}><KnowledgeFeature /></QueryClientProvider></ControlTransportProvider></TooltipProvider></MemoryRouter>);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: '重新解析 source.md' }));
    await user.click(within(screen.getByRole('dialog', { name: '重新解析文档' })).getByRole('button', { name: '开始重新解析' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '更多知识库工具' })).toHaveAttribute('data-current-tool', 'jobs'));
    await user.click(screen.getByRole('tab', { name: '资料' }));
    expect(await screen.findByRole('button', { name: '重新解析 source.md' })).toBeEnabled();
    expect(transport.requests.filter(({ request }) => request.pathId === 'knowledgeBases.document.retry')).toHaveLength(1);
  });
});
