import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type {
  WorkDocumentCommandV1,
  WorkDocumentErasePreviewV1,
  WorkDocumentListV1,
  WorkDocumentReceiptV1,
  WorkDocumentV1,
} from '@/contracts/work-documents';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import type { MockControlTransportOptions } from '@/test/mock-transport';
import { WorkDocumentsFeature } from '.';

afterEach(cleanup);

const DOCUMENT_ID_ACTIVE = `workdoc_${'a'.repeat(32)}`;
const DOCUMENT_ID_PENDING = `workdoc_${'b'.repeat(32)}`;
const DOCUMENT_ID_ERROR = `workdoc_${'c'.repeat(32)}`;
const DOCUMENT_ID_ARCHIVE = `workdoc_${'d'.repeat(32)}`;
const DOCUMENT_ID_REPAIR = `workdoc_${'e'.repeat(32)}`;
const DOCUMENT_ID_HISTORY = `workdoc_${'f'.repeat(32)}`;
const DOCUMENT_ID_ERASE = `workdoc_${'0'.repeat(32)}`;
const DOCUMENT_ID_RECONNECT = `workdoc_${'1'.repeat(32)}`;
const DOCUMENT_ID_DEFAULT = `workdoc_${'2'.repeat(32)}`;
const CONTENT_SHA256 = 'c'.repeat(64);
const PAYLOAD_SHA256 = 'd'.repeat(64);
const RECEIPT_ID_ARCHIVE = `workdoc-receipt:${'a'.repeat(32)}`;
const RECEIPT_ID_REPAIR = `workdoc-receipt:${'b'.repeat(32)}`;
const RECEIPT_ID_REOPEN = `workdoc-receipt:${'c'.repeat(32)}`;
const RECEIPT_ID_ERASE = `workdoc-receipt:${'d'.repeat(32)}`;
const RECEIPT_ID_DEFAULT = `workdoc-receipt:${'e'.repeat(32)}`;

describe('WorkDocumentsFeature', () => {
  it('loads the backend active-only default and keeps pending and error states visible', async () => {
    const active = workDocument({ documentId: DOCUMENT_ID_ACTIVE, state: 'active', title: '当前计划' });
    const pending = workDocument({ documentId: DOCUMENT_ID_PENDING, state: 'archive_pending', title: '移动中的记录' });
    const failed = workDocument({ documentId: DOCUMENT_ID_ERROR, state: 'error', title: '索引失败记录', error: 'archive index write failed' });
    const transport = workDocumentTransport({ active: [active, pending, failed] });

    renderFeature(transport);

    expect(await screen.findByText('当前计划')).toBeInTheDocument();
    expect(screen.getByText('移动中的记录')).toBeInTheDocument();
    expect(screen.getByText('索引失败记录')).toBeInTheDocument();
    expect(screen.getByText('正在归档')).toBeInTheDocument();
    expect(screen.getByText('需要修复')).toBeInTheDocument();
    expect(screen.getAllByText('进行中')).toHaveLength(1);

    const listRequest = transport.requests.find((call) => call.request.pathId === 'workDocuments.list');
    expect(listRequest?.request.query).toEqual({ limit: 100 });
    expect(transport.requests.some((call) => call.request.pathId === 'workDocuments.history.search')).toBe(false);
  });

  it('uses keyboard tabs and a separate backend archive search scope', async () => {
    const user = userEvent.setup();
    const archived = workDocument({ documentId: DOCUMENT_ID_HISTORY, state: 'archived', title: '历史验收记录' });
    const transport = workDocumentTransport({
      active: [workDocument({ documentId: DOCUMENT_ID_ACTIVE, state: 'active', title: '仍在进行' })],
      history: [archived],
    });
    renderFeature(transport);

    const activeTab = await screen.findByRole('tab', { name: '活跃文档' });
    activeTab.focus();
    await user.keyboard('{ArrowRight}');
    expect(await screen.findByRole('tab', { name: '历史归档', selected: true })).toBeInTheDocument();
    expect(await screen.findByText('历史验收记录')).toBeInTheDocument();

    await user.type(screen.getByLabelText('检索历史归档'), '验收');
    await user.click(screen.getByRole('button', { name: '搜索历史' }));
    await waitFor(() => {
      const calls = transport.requests.filter((call) => call.request.pathId === 'workDocuments.history.search');
      expect(calls.at(-1)?.request.query).toEqual({ query: '验收', limit: 100 });
    });
    expect(transport.requests.filter((call) => call.request.pathId === 'workDocuments.list')).toHaveLength(1);
  });

  it('archives an active document with the trusted terminal receipt and renders the backend receipt', async () => {
    const user = userEvent.setup();
    const active = workDocument({ documentId: DOCUMENT_ID_ARCHIVE, state: 'active', title: '待归档验收记录' });
    const archive = vi.fn((request: ControlRequest) => commandResponse(
      'archive',
      { ...active, state: 'archive_pending', terminalReceiptId: 'terminal-receipt-1' },
      RECEIPT_ID_ARCHIVE,
    ));
    const transport = workDocumentTransport({
      active: [active],
      extraRoutes: { 'workDocuments.archive': archive },
    });
    renderFeature(transport);

    const archiveButton = await screen.findByRole('button', { name: '归档到历史' });
    expect(archiveButton).toBeDisabled();
    await user.type(screen.getByRole('textbox', { name: '完成凭证编号' }), 'terminal-receipt-1');
    await user.click(archiveButton);

    expect(await screen.findByText(RECEIPT_ID_ARCHIVE)).toBeInTheDocument();
    expect(archive).toHaveBeenCalledWith(expect.objectContaining({
      params: { documentId: DOCUMENT_ID_ARCHIVE },
      body: { terminalReceiptId: 'terminal-receipt-1' },
    }));
    await waitFor(() => {
      expect(transport.requests.filter((call) => call.request.pathId === 'workDocuments.list').length).toBeGreaterThan(1);
      expect(transport.requests.filter((call) => call.request.pathId === 'workDocuments.get').length).toBeGreaterThan(1);
    });
  });

  it('repairs a partially completed document and renders the backend receipt', async () => {
    const user = userEvent.setup();
    const pending = workDocument({ documentId: DOCUMENT_ID_REPAIR, state: 'archive_pending', title: '等待归档修复' });
    const repaired = { ...pending, state: 'active' as const };
    const repair = vi.fn(() => commandResponse('repair', repaired, RECEIPT_ID_REPAIR));
    const transport = workDocumentTransport({
      active: [pending],
      extraRoutes: { 'workDocuments.repair': repair },
    });
    renderFeature(transport);

    await user.click(await screen.findByRole('button', { name: '修复移动或索引' }));
    expect(await screen.findByText(/后端操作收据/)).toBeInTheDocument();
    expect(screen.getByText(RECEIPT_ID_REPAIR)).toBeInTheDocument();
    expect(repair).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(transport.requests.filter((call) => call.request.pathId === 'workDocuments.list').length).toBeGreaterThan(1);
      expect(transport.requests.filter((call) => call.request.pathId === 'workDocuments.get').length).toBeGreaterThan(1);
    });
  });

  it('renders a failed backend receipt as failure instead of inventing success', async () => {
    const user = userEvent.setup();
    const pending = workDocument({ documentId: DOCUMENT_ID_REPAIR, state: 'archive_pending', title: '失败收据记录' });
    const failed = { ...pending, state: 'error' as const, error: 'repair failed' };
    const transport = workDocumentTransport({
      active: [pending],
      extraRoutes: {
        'workDocuments.repair': () => commandResponse('repair', failed, RECEIPT_ID_DEFAULT, 'failed'),
      },
    });
    renderFeature(transport);

    await user.click(await screen.findByRole('button', { name: '修复移动或索引' }));
    const receiptId = await screen.findByText(RECEIPT_ID_DEFAULT);
    expect(screen.getByText('后端操作收据 · 后端拒绝或失败')).toBeInTheDocument();
    expect(receiptId.closest('.work-documents__receipt')).toHaveAttribute('data-tone', 'danger');
  });

  it('reopens an archived document with authority revision and transition receipt', async () => {
    const user = userEvent.setup();
    const archived = workDocument({
      authorityRevision: 8,
      documentId: DOCUMENT_ID_HISTORY,
      state: 'archived',
      terminalReceiptId: 'archive-transition-1',
      title: '已完成目标',
    });
    const reopen = vi.fn((request: ControlRequest) => commandResponse(
      'reopen',
      { ...archived, state: 'reopen_pending' },
      RECEIPT_ID_REOPEN,
    ));
    const transport = workDocumentTransport({
      history: [archived],
      extraRoutes: { 'workDocuments.reopen': reopen },
    });
    renderFeature(transport, '/work-documents?scope=history');

    await user.click(await screen.findByRole('button', { name: '重新打开到活跃区' }));
    expect(await screen.findByText(RECEIPT_ID_REOPEN)).toBeInTheDocument();
    expect(reopen).toHaveBeenCalledWith(expect.objectContaining({
      body: { authorityRevision: 8, transitionReceiptId: 'archive-transition-1' },
    }));
    await waitFor(() => {
      expect(transport.requests.filter((call) => call.request.pathId === 'workDocuments.history.search').length).toBeGreaterThan(1);
      expect(transport.requests.filter((call) => call.request.pathId === 'workDocuments.get').length).toBeGreaterThan(1);
    });
  });

  it('keeps permanent erase behind a confirmation distinct from archive', async () => {
    const user = userEvent.setup();
    const archived = workDocument({
      documentId: DOCUMENT_ID_ERASE,
      state: 'archived',
      terminalReceiptId: 'archive-transition-erase',
      title: '准备清除的历史记录',
    });
    const erase = vi.fn((request: ControlRequest) => commandResponse('erase', archived, RECEIPT_ID_ERASE));
    const preview = vi.fn((): WorkDocumentErasePreviewV1 => ({
      schemaVersion: 'rag-ime.work-document-command.v1',
      ok: true,
      operation: 'erase-preview',
      document: archived,
      approval: { approvalId: 'approval-erase-1' },
      payloadSha256: PAYLOAD_SHA256,
    }));
    const transport = workDocumentTransport({
      history: [archived],
      extraRoutes: {
        'workDocuments.erase.preview': preview,
        'workDocuments.erase': erase,
      },
    });
    renderFeature(transport, '/work-documents?scope=history');

    expect(await screen.findByRole('button', { name: '重新打开到活跃区' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '归档到历史' })).not.toBeInTheDocument();
    const eraseTrigger = screen.getByRole('button', { name: '永久清除…' });
    await user.click(eraseTrigger);
    expect(screen.getByRole('heading', { name: '永久清除工作文档' })).toBeInTheDocument();
    expect(screen.getByText('这不是归档：', { exact: false })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(eraseTrigger).toHaveFocus());
    await user.click(eraseTrigger);

    await user.type(screen.getByRole('textbox', { name: '发起操作的对话编号' }), 'session-erase-1');
    await user.click(screen.getByRole('button', { name: '获取清除审批' }));
    expect(await screen.findByText('approval-erase-1')).toBeInTheDocument();
    const finalButton = screen.getByRole('button', { name: '永久清除，不是归档' });
    expect(finalButton).toBeDisabled();
    await user.type(screen.getByRole('textbox', { name: '永久清除确认' }), '永久清除');
    await user.click(finalButton);

    expect(erase).toHaveBeenCalledWith(expect.objectContaining({
      body: {
        sessionId: 'session-erase-1',
        approvalId: 'approval-erase-1',
        payloadSha256: PAYLOAD_SHA256,
      },
    }));
    expect(await screen.findByText(RECEIPT_ID_ERASE)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '永久清除工作文档' })).not.toBeInTheDocument();
  });

  it('invalidates erase approval when its bound Session changes', async () => {
    const user = userEvent.setup();
    const archived = workDocument({
      documentId: DOCUMENT_ID_ERASE,
      state: 'archived',
      terminalReceiptId: 'archive-transition-erase',
      title: '会话绑定清除记录',
    });
    const transport = workDocumentTransport({
      history: [archived],
      extraRoutes: {
        'workDocuments.erase.preview': (): WorkDocumentErasePreviewV1 => ({
          schemaVersion: 'rag-ime.work-document-command.v1',
          ok: true,
          operation: 'erase-preview',
          document: archived,
          approval: { approvalId: 'approval-session-one' },
          payloadSha256: PAYLOAD_SHA256,
        }),
      },
    });
    renderFeature(transport, '/work-documents?scope=history');

    await user.click(await screen.findByRole('button', { name: '永久清除…' }));
    const sessionInput = screen.getByRole('textbox', { name: '发起操作的对话编号' });
    await user.type(sessionInput, 'session-one');
    await user.click(screen.getByRole('button', { name: '获取清除审批' }));
    expect(await screen.findByText('approval-session-one')).toBeInTheDocument();

    await user.clear(sessionInput);
    await user.type(sessionInput, 'session-two');
    expect(screen.queryByText('approval-session-one')).not.toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: '永久清除确认' }), '永久清除');
    expect(screen.getByRole('button', { name: '永久清除，不是归档' })).toBeDisabled();
  });

  it('fences a late archive receipt away from a newly selected document', async () => {
    const user = userEvent.setup();
    const first = workDocument({ documentId: DOCUMENT_ID_ARCHIVE, title: '第一份活跃文档' });
    const second = workDocument({ documentId: DOCUMENT_ID_ACTIVE, title: '第二份活跃文档' });
    let resolveArchive: (value: WorkDocumentCommandV1) => void = () => undefined;
    const archiveResult = new Promise<WorkDocumentCommandV1>((resolve) => {
      resolveArchive = resolve;
    });
    const transport = workDocumentTransport({
      active: [first, second],
      extraRoutes: { 'workDocuments.archive': () => archiveResult },
    });
    renderFeature(transport);

    await screen.findByRole('heading', { name: '第一份活跃文档' });
    await user.type(screen.getByRole('textbox', { name: '完成凭证编号' }), 'terminal-receipt-late');
    await user.click(screen.getByRole('button', { name: '归档到历史' }));
    await user.click(screen.getByRole('button', { name: /第二份活跃文档/ }));
    expect(await screen.findByRole('heading', { name: '第二份活跃文档' })).toBeInTheDocument();

    await act(async () => {
      resolveArchive(commandResponse(
        'archive',
        { ...first, state: 'archive_pending', terminalReceiptId: 'terminal-receipt-late' },
        RECEIPT_ID_ARCHIVE,
      ));
      await archiveResult;
    });
    await waitFor(() => {
      expect(screen.queryByText(RECEIPT_ID_ARCHIVE)).not.toBeInTheDocument();
      expect(screen.getByRole('heading', { name: '第二份活跃文档' })).toBeInTheDocument();
    });
  });

  it('shows loading and the guided active empty state without inventing a completed item', async () => {
    let resolveList: (value: WorkDocumentListV1) => void = () => undefined;
    const listResult = new Promise<WorkDocumentListV1>((resolve) => {
      resolveList = resolve;
    });
    const transport = workDocumentTransport({ activeHandler: () => listResult });
    renderFeature(transport);

    expect(await screen.findByRole('status', { name: '正在加载' })).toBeInTheDocument();
    await act(async () => {
      resolveList(listResponse([]));
      await listResult;
    });
    expect(await screen.findByRole('heading', { name: '活跃工作区已清理完毕' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重新打开到活跃区' })).not.toBeInTheDocument();
  });

  it('shows retry recovery for a failing backend and an unknown capability state', async () => {
    const user = userEvent.setup();
    const recovered = workDocument({ documentId: DOCUMENT_ID_ERROR, title: '重试后恢复的文档' });
    let attempts = 0;
    const failing = workDocumentTransport({
      activeHandler: () => {
        attempts += 1;
        if (attempts === 1) throw new Error('work document store unavailable');
        return listResponse([recovered]);
      },
      detailHandler: () => detailResponse(recovered),
    });
    const first = renderFeature(failing);
    expect(await screen.findByRole('heading', { name: '读取失败' })).toBeInTheDocument();
    expect(screen.getByText('暂时无法读取这部分内容，请稍后重试。')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('重试后恢复的文档')).toBeInTheDocument();
    expect(attempts).toBe(2);
    first.unmount();

    const unknown = new MockControlTransport({
      capabilities: { features: {} },
    });
    renderFeature(unknown);
    expect(await screen.findByRole('heading', { name: '工作文档暂不可用' })).toBeInTheDocument();
    expect(unknown.requests).toHaveLength(0);
  });

  it('refetches active and detail projections after reconnect', async () => {
    const active = workDocument({ documentId: DOCUMENT_ID_RECONNECT, state: 'active', title: '重连文档' });
    const list = vi.fn(() => listResponse([active]));
    const detail = vi.fn(() => detailResponse(active));
    const transport = workDocumentTransport({
      activeHandler: list,
      detailHandler: detail,
    });
    renderFeature(transport);

    expect(await screen.findByText('重连文档')).toBeInTheDocument();
    await waitFor(() => expect(detail).toHaveBeenCalledTimes(1));
    fireEvent(window, new Event('online'));
    await waitFor(() => {
      expect(list.mock.calls.length).toBeGreaterThan(1);
      expect(detail.mock.calls.length).toBeGreaterThan(1);
    });
  });
});

function renderFeature(
  transport: MockControlTransport,
  initialEntry = '/work-documents',
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ControlTransportProvider transport={transport}>
        <QueryClientProvider client={client}>
          <TooltipProvider>
            <WorkDocumentsFeature />
          </TooltipProvider>
        </QueryClientProvider>
      </ControlTransportProvider>
    </MemoryRouter>,
  );
}

function workDocumentTransport({
  active = [],
  activeHandler,
  detailHandler,
  extraRoutes = {},
  history = [],
}: {
  active?: WorkDocumentV1[];
  activeHandler?: (request: ControlRequest) => unknown;
  detailHandler?: (request: ControlRequest) => unknown;
  extraRoutes?: MockControlTransportOptions['routes'];
  history?: WorkDocumentV1[];
} = {}): MockControlTransport {
  const documents = [...active, ...history];
  return new MockControlTransport({
    capabilities: { features: { workDocuments: true } },
    routes: {
      'workDocuments.list': activeHandler ?? (() => listResponse(active)),
      'workDocuments.history.search': () => listResponse(history),
      'workDocuments.get': detailHandler ?? ((request: ControlRequest) => {
        const documentId = String(request.params?.documentId ?? '');
        const document = documents.find((item) => item.documentId === documentId) ?? active[0] ?? history[0];
        if (!document) throw new Error('work document not found');
        return detailResponse(document);
      }),
      'workDocuments.archive': () => commandResponse('archive', active[0], RECEIPT_ID_DEFAULT),
      'workDocuments.repair': () => commandResponse('repair', active[0], RECEIPT_ID_DEFAULT),
      'workDocuments.reopen': () => commandResponse('reopen', history[0], RECEIPT_ID_DEFAULT),
      'workDocuments.erase.preview': () => ({
        schemaVersion: 'rag-ime.work-document-command.v1',
        ok: true,
        operation: 'erase-preview',
        document: documents[0],
        approval: { approvalId: 'approval-default' },
        payloadSha256: PAYLOAD_SHA256,
      }),
      'workDocuments.erase': () => commandResponse('erase', documents[0], RECEIPT_ID_DEFAULT),
      ...extraRoutes,
    },
  });
}

function listResponse(items: WorkDocumentV1[]) {
  return {
    schemaVersion: 'rag-ime.work-document-list.v1' as const,
    items,
    total: items.length,
  };
}

function detailResponse(document: WorkDocumentV1) {
  return {
    schemaVersion: 'rag-ime.work-document-detail.v1' as const,
    document,
  };
}

function commandResponse(
  operation: WorkDocumentReceiptV1['operation'],
  document: WorkDocumentV1 | undefined,
  receiptId: string,
  status: WorkDocumentReceiptV1['status'] = 'applied',
): WorkDocumentCommandV1 {
  if (!document) throw new Error('fixture document is required');
  return {
    schemaVersion: 'rag-ime.work-document-command.v1',
    ok: true,
    operation,
    document: operation === 'erase' ? null : document,
    receipt: receipt(operation, receiptId, status),
  };
}

function receipt(
  operation: WorkDocumentReceiptV1['operation'],
  receiptId: string,
  status: WorkDocumentReceiptV1['status'],
): WorkDocumentReceiptV1 {
  return {
    receiptId,
    operation,
    status,
    idempotent: false,
    createdAtMs: 2_000,
  };
}

function workDocument(overrides: Partial<WorkDocumentV1> = {}): WorkDocumentV1 {
  return {
    documentId: DOCUMENT_ID_DEFAULT,
    authorityKind: 'session_plan',
    authorityId: 'session-1',
    authorityRevision: 3,
    authorityKey: 'session_plan:session-1:3',
    documentRevision: 2,
    contentSha256: CONTENT_SHA256,
    workspaceRoot: '/workspace',
    path: `/workspace/docs/active/${DOCUMENT_ID_DEFAULT}.md`,
    activePath: `/workspace/docs/active/${DOCUMENT_ID_DEFAULT}.md`,
    archivePath: `/workspace/docs/archive/${DOCUMENT_ID_DEFAULT}.md`,
    state: 'active',
    title: '工作文档',
    terminalReceiptId: '',
    error: '',
    createdAtMs: 1_000,
    updatedAtMs: 2_000,
    ...overrides,
  };
}
