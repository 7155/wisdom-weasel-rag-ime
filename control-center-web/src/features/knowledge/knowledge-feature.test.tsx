import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { KnowledgeFeature } from './index';

vi.mock('react-virtuoso', () => ({
  Virtuoso: ({ data, itemContent }: { data: unknown[]; itemContent: (index: number, item: unknown) => ReactNode }) => (
    <div data-testid="virtuoso-list">{data.map((item, index) => <div key={index}>{itemContent(index, item)}</div>)}</div>
  ),
}));

beforeEach(() => {
  vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => blob instanceof Blob && blob.type === 'application/pdf' ? 'blob:knowledge-source' : 'blob:knowledge-asset');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('document knowledge library', () => {
  it('keeps document retrieval separate from personal memory and exposes citations', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderKnowledge(transport);

    expect(await screen.findByRole('heading', { name: '知识库', level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Agent Runtime 资料', level: 2 })).toBeInTheDocument();
    expect((await screen.findAllByText('runtime.pdf')).length).toBeGreaterThan(0);
    expect(transport.requests.some((call) => call.request.pathId.startsWith('memory.'))).toBe(false);
    expect(transport.requests.some((call) => call.request.pathId === 'knowledge.routeStatus')).toBe(false);

    await user.click(screen.getByRole('tab', { name: '检索测试' }));
    await user.type(screen.getByRole('textbox', { name: '检索测试' }), '工具如何注册');
    await user.click(screen.getByRole('button', { name: '检索' }));
    expect(await screen.findByRole('option', { name: /Tool 注册/ })).toBeInTheDocument();
    expect(screen.getByText('第 12 页')).toBeInTheDocument();
    expect(screen.getByText('Agent Loop > Tools')).toBeInTheDocument();
    const search = request(transport, 'knowledgeBases.search');
    expect(search?.params).toEqual({ kbId: 'kb-runtime' });
    expect(search?.body).toEqual({ query: '工具如何注册', topK: 10, mode: 'hybrid', threshold: 0.2 });

    await user.click(screen.getByRole('button', { name: '打开来源' }));
    await waitFor(() => expect(transport.requests.find((call) => call.request.pathId === 'knowledgeBases.open' && call.request.query?.chunkId === 'chunk-tool')?.request).toMatchObject({
      params: { kbId: 'kb-runtime', fileId: 'file-runtime' },
      query: { chunkId: 'chunk-tool', page: 12, lines: 80 },
    }));
    expect(screen.getByRole('tab', { name: '材料查看' })).toHaveAttribute('data-state', 'active');
    expect(await screen.findByText(/已定位检索命中/)).toBeInTheDocument();
    expect(screen.getByText('Agent 启动时注册 ime_knowledge。').closest('article')).toHaveAttribute('data-focused', 'true');
  });

  it('imports through the typed transport and updates Agent/parser settings with revisions', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderKnowledge(transport);

    expect((await screen.findAllByText('runtime.pdf')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: '导入文件' }));
    await waitFor(() => expect(transport.knowledgeImportCalls).toEqual([{
      kbId: 'kb-runtime',
      parserProvider: 'auto',
      maxFiles: 20,
    }]));
    expect(await screen.findByRole('region', { name: '上传队列' })).toHaveTextContent('new.pdf');
    expect(screen.getByText('已进入解析')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: '设置' }));
    const agentSwitch = screen.getByRole('switch', { name: '允许 Agent 使用' });
    expect(agentSwitch).not.toBeChecked();
    await user.click(agentSwitch);
    await waitFor(() => expect(request(transport, 'knowledgeBases.update')?.body).toMatchObject({
      agentEnabled: true,
      expectedRevision: 8,
    }));

    await user.selectOptions(screen.getByRole('combobox', { name: 'Provider' }), 'mineru');
    await waitFor(() => expect(transport.requests.filter((call) => call.request.pathId === 'knowledgeBases.update').at(-1)?.request.body).toMatchObject({
      parserProvider: 'mineru_local_http',
      expectedRevision: 8,
    }));
    expect(screen.getByText('已连接')).toBeInTheDocument();

    const chunkSize = screen.getByRole('spinbutton', { name: '大小' });
    await user.clear(chunkSize);
    await user.type(chunkSize, '1400');
    await user.click(screen.getByRole('button', { name: '保存切分设置' }));
    await waitFor(() => expect(transport.requests.filter((call) => call.request.pathId === 'knowledgeBases.update').at(-1)?.request.body).toMatchObject({
      chunkingConfig: { strategy: 'markdown', size: 1_400, overlap: 160, respectHeadings: true, respectPageBoundaries: true },
      expectedRevision: 8,
    }));

    const denseWeight = screen.getByRole('spinbutton', { name: 'Dense 权重' });
    await user.clear(denseWeight);
    await user.type(denseWeight, '1.5');
    await user.click(screen.getByRole('button', { name: '保存检索设置' }));
    await waitFor(() => expect(transport.requests.filter((call) => call.request.pathId === 'knowledgeBases.update').at(-1)?.request.body).toMatchObject({
      retrievalConfig: { mode: 'hybrid', topK: 10, threshold: .2, lexicalWeight: 1, denseWeight: 1.5, rrfK: 60, candidateMultiplier: 4 },
      expectedRevision: 8,
    }));
    expect(screen.getByDisplayValue('local-hash:96:v1')).toBeDisabled();
    expect(screen.getByDisplayValue('42')).toBeDisabled();

    await user.click(screen.getByRole('button', { name: '预览重建' }));
    expect(await screen.findByText('预计片段')).toBeInTheDocument();
    expect(screen.getByText('48')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '确认重建' }));
    await waitFor(() => expect(request(transport, 'knowledgeBases.rebuild')?.body).toEqual({
      previewToken: 'preview-reindex', payloadSha256: 'sha256:reindex', expectedRevision: 8, confirmText: 'REBUILD',
    }));
    expect(screen.getByRole('tab', { name: '索引任务' })).toHaveAttribute('data-state', 'active');
  });

  it('retries a failed document and confirms deletion without leaking storage paths', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderKnowledge(transport);

    expect((await screen.findAllByText('runtime.pdf')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: '重新解析 runtime.pdf' }));
    const reparseDialog = screen.getByRole('dialog', { name: '重新解析文档' });
    await user.selectOptions(within(reparseDialog).getByRole('combobox', { name: '解析方式' }), 'mineru');
    await user.click(within(reparseDialog).getByRole('button', { name: '开始重新解析' }));
    await waitFor(() => expect(request(transport, 'knowledgeBases.document.retry')).toMatchObject({
      params: { kbId: 'kb-runtime', fileId: 'file-runtime' },
      body: { stage: 'parse', parserProvider: 'mineru_local_http', expectedRevision: 3 },
    }));

    await user.click(screen.getByRole('button', { name: '删除 runtime.pdf' }));
    const dialog = screen.getByRole('dialog', { name: '删除文档' });
    expect(within(dialog).getByText(/runtime.pdf/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: '确认删除' }));
    await waitFor(() => expect(request(transport, 'knowledgeBases.document.delete')?.params).toEqual({ kbId: 'kb-runtime', fileId: 'file-runtime' }));
    expect(document.body).not.toHaveTextContent('/Users/private/Knowledge');
  });

  it('opens source, markdown, chunks, image and table artifacts from the file row', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderKnowledge(transport);

    await user.click(await screen.findByRole('button', { name: '查看 runtime.pdf' }));
    expect(await screen.findByRole('tab', { name: '源文件' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Markdown' })).toHaveAttribute('data-state', 'active');
    expect(screen.getByRole('heading', { name: 'Agent Loop' })).toBeInTheDocument();
    expect(screen.getByText('图片引用已隔离：远程图')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: '远程图' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: '源文件' }));
    expect(await screen.findByTitle('runtime.pdf 源文件')).toHaveAttribute('src', 'blob:knowledge-source');
    expect(transport.knowledgeDocumentSourceCalls[0]).toMatchObject({ kbId: 'kb-runtime', fileId: 'file-runtime' });
    await user.click(screen.getByRole('tab', { name: 'Chunks' }));
    expect(screen.getByText('Agent 启动时注册 ime_knowledge。')).toBeInTheDocument();
    expect(screen.getByText('Agent Loop > Tools')).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: '解析产物' }));
    expect(await screen.findByRole('img', { name: '工具流程图' })).toHaveAttribute('src', 'blob:knowledge-asset');
    expect(screen.getByRole('link', { name: '查看 tool-flow.png' })).toHaveAttribute('href', 'blob:knowledge-asset');
    expect(screen.getByRole('link', { name: '下载 tool-flow.png' })).toHaveAttribute('download', 'tool-flow.png');
    expect(transport.knowledgeAssetCalls[0]).toMatchObject({ kbId: 'kb-runtime', fileId: 'file-runtime', assetId: 'd'.repeat(64) });
    expect(screen.getByRole('columnheader', { name: '字段' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'ime_knowledge' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '加载更多' }));
    expect(screen.getByRole('cell', { name: 'value-21' })).toBeInTheDocument();
  });

  it('keeps all RAG workspace tabs reachable at a narrow viewport', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    window.dispatchEvent(new Event('resize'));
    const transport = createTransport();
    const user = userEvent.setup();
    renderKnowledge(transport);

    expect((await screen.findAllByText('runtime.pdf')).length).toBeGreaterThan(0);
    for (const name of ['材料查看', '检索测试', '索引任务', '设置']) {
      await user.click(screen.getByRole('tab', { name }));
      expect(screen.getByRole('tab', { name })).toHaveAttribute('data-state', 'active');
    }
    expect(screen.getByRole('button', { name: '保存切分设置' })).toBeInTheDocument();
  });

  it('paginates Markdown and chunks without hiding content after the first window', async () => {
    const transport = createTransport({ pagedDetail: true });
    const user = userEvent.setup();
    renderKnowledge(transport);

    await user.click(await screen.findByRole('button', { name: '查看 runtime.pdf' }));
    expect(await screen.findByRole('heading', { name: '第一段' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '继续加载 Markdown' }));
    expect(await screen.findByRole('heading', { name: '第二段' })).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Chunks' }));
    expect(screen.getByText('第一个片段')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '加载更多' }));
    expect(await screen.findByText('第二个片段')).toBeInTheDocument();
    expect(screen.getByText('已加载全部 2 个片段。')).toBeInTheDocument();
  });

  it('maps succeeded jobs to completed and exposes task details', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderKnowledge(transport);

    await user.click(await screen.findByRole('tab', { name: '索引任务' }));
    expect(screen.getAllByText('已完成').length).toBeGreaterThan(0);
    expect(screen.queryByText('处理中')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /runtime.pdf/ }));
    expect(screen.getByText('job-1')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: '任务阶段记录' })).toBeInTheDocument();
  });

  it('previews all server chunking strategies without writing the index', async () => {
    const transport = createTransport();
    const user = userEvent.setup();
    renderKnowledge(transport);

    await user.click(await screen.findByRole('tab', { name: '设置' }));
    const strategy = screen.getByRole('combobox', { name: '策略' });
    expect(within(strategy).getAllByRole('option')).toHaveLength(7);
    await user.selectOptions(strategy, 'laws');
    await user.click(screen.getByRole('button', { name: '预览切分' }));

    await waitFor(() => expect(request(transport, 'knowledgeBases.chunkPreview')).toMatchObject({
      params: { kbId: 'kb-runtime', fileId: 'file-runtime' },
      body: { chunkingConfig: { strategy: 'laws' }, limit: 12 },
    }));
    expect(await screen.findByText('2 个片段')).toBeInTheDocument();
    expect(screen.getByText('第一条预览')).toBeInTheDocument();
  });

  it('cancels an active indexing job from the jobs workspace', async () => {
    const transport = createTransport({ activeJob: true });
    const user = userEvent.setup();
    renderKnowledge(transport);

    await user.click(await screen.findByRole('tab', { name: '索引任务' }));
    await user.click(screen.getByRole('button', { name: '取消任务' }));

    await waitFor(() => expect(request(transport, 'knowledgeBases.job.cancel')).toMatchObject({
      params: { kbId: 'kb-runtime', jobId: 'job-1' },
      body: {},
    }));
  });

  it('keeps failed uploads in the queue and retries them visibly', async () => {
    const transport = createTransport();
    vi.spyOn(transport, 'importKnowledgeDocuments')
      .mockRejectedValueOnce(new Error('上传连接中断'))
      .mockResolvedValueOnce([{ kbId: 'kb-runtime', documentId: 'file-retry', fileName: 'retry.pdf', mimeType: 'application/pdf', byteSize: 100, sha256: 'e'.repeat(64), status: 'queued' }]);
    const user = userEvent.setup();
    renderKnowledge(transport);

    await user.click(await screen.findByRole('button', { name: '导入文件' }));
    expect((await screen.findAllByText('上传连接中断')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: '重试上传 本机文件导入' }));
    expect(await screen.findByText('retry.pdf')).toBeInTheDocument();
    expect(screen.getByText('已进入解析')).toBeInTheDocument();
  });
});

function renderKnowledge(transport: MockControlTransport) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <TooltipProvider delayDuration={0}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}><KnowledgeFeature /></QueryClientProvider>
      </ControlTransportProvider>
    </TooltipProvider>,
  );
}

function createTransport(options: { activeJob?: boolean; pagedDetail?: boolean } = {}): MockControlTransport {
  return new MockControlTransport({
    knowledgeAsset: (input) => ({ ...input, mimeType: 'image/png', byteSize: 3, sha256: input.assetId, blob: new Blob(['png'], { type: 'image/png' }) }),
    knowledgeDocumentSource: (input) => ({ ...input, mimeType: 'application/pdf', byteSize: 3, sha256: 'b'.repeat(64), blob: new Blob(['pdf'], { type: 'application/pdf' }) }),
    knowledgeImportReceipts: [{
      kbId: 'kb-runtime', documentId: 'file-new', fileName: 'new.pdf', mimeType: 'application/pdf',
      byteSize: 2_048, sha256: 'a'.repeat(64), status: 'queued',
    }],
    routes: {
      'knowledgeBases.list': { items: [knowledgeBase()] },
      'knowledgeBases.get': { base: knowledgeBase() },
      'knowledgeBases.documents.list': { items: [knowledgeDocument()] },
      'knowledgeBases.jobs.list': { items: [{ id: 'job-1', fileId: 'file-runtime', fileName: 'runtime.pdf', kind: 'reindex', parserMode: 'builtin', status: options.activeJob ? 'running' : 'succeeded', stage: options.activeJob ? 'indexing' : 'ready', progress: options.activeJob ? .8 : 1, cancellable: options.activeJob, revision: 3, createdAtMs: Date.now() - 2_000, startedAtMs: Date.now() - 1_500, finishedAtMs: options.activeJob ? 0 : Date.now() - 500, updatedAtMs: Date.now() - 500 }] },
      'knowledgeWorker.health': { ok: true, status: 'ready', dense: { available: true, degraded: false, kind: 'sqlite-vector-projection', fingerprint: 'local-hash:96:v1', vectorCount: 42 } },
      'knowledgeParsers.list': { items: [{ id: 'mineru_local_http', enabled: true, ready: true, status: 'ready' }] },
      'knowledgeBases.search': {
        hits: [{
          id: 'chunk-tool', documentId: 'file-runtime', documentName: 'runtime.pdf', title: 'Tool 注册',
          excerpt: 'Agent 启动时注册 ime_knowledge。', score: .92, page: 12, heading: 'Agent Loop > Tools',
        }],
      },
      'knowledgeBases.document.get': options.pagedDetail ? pagedKnowledgeDetail : knowledgeDetail(),
      'knowledgeBases.open': { ok: true, content: '工具原文' },
      'knowledgeBases.update': { base: knowledgeBase() },
      'knowledgeBases.document.retry': { ok: true },
      'knowledgeBases.document.delete': { ok: true },
      'knowledgeBases.reindexPreview': { previewToken: 'preview-reindex', payloadSha256: 'sha256:reindex', expectedRevision: 8, summary: { documentCount: 1, staleDocumentCount: 1, estimatedChunkCount: 48 } },
      'knowledgeBases.rebuild': { ok: true },
      'knowledgeBases.job.cancel': { ok: true, job: { id: 'job-1', status: 'cancelled' } },
      'knowledgeBases.chunkPreview': { ok: true, fileId: 'file-runtime', total: 2, truncated: false, items: [{ chunkId: 'preview-1', ordinal: 0, content: '第一条预览', page: 1 }, { chunkId: 'preview-2', ordinal: 1, content: '第二条预览', page: 2 }] },
    },
  });
}

function knowledgeBase() {
  return {
    id: 'kb-runtime', name: 'Agent Runtime 资料', description: '只包含外部文档', documentCount: 1,
    chunkCount: 42, status: 'ready', agentEnabled: false, parserProvider: 'auto', updatedAtMs: Date.now(), revision: 8,
    chunkingConfig: { strategy: 'markdown', size: 1_200, overlap: 160, separator: '\n\n', respectHeadings: true, respectPageBoundaries: true },
    retrievalConfig: { mode: 'hybrid', topK: 10, threshold: .2, lexicalWeight: 1, denseWeight: 1, rrfK: 60, candidateMultiplier: 4 },
  };
}

function knowledgeDocument() {
  return {
    id: 'file-runtime', baseId: 'kb-runtime', name: 'runtime.pdf', mimeType: 'application/pdf', byteSize: 4_096,
    status: 'failed', stage: 'parse', progress: .4, error: '扫描文本质量不足', chunkCount: 0, parserProvider: 'builtin',
    updatedAtMs: Date.now(), revision: 3, sha256: 'b'.repeat(64), pageCount: 12, tokenCount: 3_200,
    parserVersion: 'builtin-1', indexedConfigRevision: 8, sourceReadPath: '/api/knowledge-bases/kb-runtime/documents/file-runtime/source',
  };
}

function pagedKnowledgeDetail(request: ControlRequest) {
  const chunkOffset = Number(request.query?.offset ?? 0);
  const lineOffset = Number(request.query?.lineOffset ?? 0);
  const contentRequest = Number(request.query?.lineLimit ?? 0) === 200;
  const chunks = contentRequest
    ? [{ chunkId: 'chunk-1', ordinal: 0, content: '第一个片段', page: 1, tokenCount: 4 }]
    : chunkOffset === 0
      ? [{ chunkId: 'chunk-1', ordinal: 0, content: '第一个片段', page: 1, tokenCount: 4 }]
      : [{ chunkId: 'chunk-2', ordinal: 1, content: '第二个片段', page: 2, tokenCount: 4 }];
  return {
    ...knowledgeDetail(),
    chunks: { items: chunks, total: 2, hasMore: !contentRequest && chunkOffset === 0 },
    artifact: { available: true, format: 'markdown', mimeType: 'text/markdown', byteSize: 120, lineCount: 4, sha256: 'c'.repeat(64) },
    contentWindow: contentRequest
      ? { items: lineOffset === 0 ? [{ lineNumber: 1, content: '# 第一段' }, { lineNumber: 2, content: '正文一' }] : [{ lineNumber: 3, content: '# 第二段' }, { lineNumber: 4, content: '正文二' }], total: 4, hasMore: lineOffset === 0 }
      : { items: [{ lineNumber: 1, content: '# 第一段' }], total: 4, hasMore: true },
  };
}

function knowledgeDetail() {
  return {
    document: knowledgeDocument(),
    chunks: { items: [{ chunkId: 'chunk-tool', ordinal: 0, content: 'Agent 启动时注册 ime_knowledge。', page: 12, heading: 'Agent Loop > Tools', tokenCount: 12 }], total: 1, hasMore: false },
    pages: [{ page: 12, chunkCount: 1 }],
    artifact: { available: true, format: 'markdown', mimeType: 'text/markdown', byteSize: 96, lineCount: 3, sha256: 'c'.repeat(64) },
    contentWindow: { items: [{ lineNumber: 1, content: '# Agent Loop' }, { lineNumber: 2, content: 'Agent 启动时注册 ime_knowledge。' }, { lineNumber: 3, content: '![远程图](https://example.invalid/remote.png)' }], total: 3, hasMore: false },
    assets: [{ assetId: 'd'.repeat(64), name: 'tool-flow.png', mimeType: 'image/png', byteSize: 1_024, sha256: 'd'.repeat(64), readPath: `/api/knowledge-bases/kb-runtime/documents/file-runtime/assets/${'d'.repeat(64)}`, page: 12, caption: '工具流程图' }],
    tables: [{ tableId: 'table-tools', title: '工具表', page: 12, columns: ['字段', '值'], rows: [['工具', 'ime_knowledge'], ...Array.from({ length: 21 }, (_value, index) => [`field-${index + 1}`, `value-${index + 1}`])] }],
  };
}

function request(transport: MockControlTransport, pathId: string): ControlRequest | undefined {
  return transport.requests.find((call) => call.request.pathId === pathId)?.request;
}
