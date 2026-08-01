import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseMutationResult } from '@tanstack/react-query';
import {
  Archive,
  CheckCircle2,
  FileClock,
  FileText,
  History,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  Trash2,
  Wrench,
} from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Field,
  Input,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/primitives';
import type {
  WorkDocumentDetailV1,
  WorkDocumentCommandV1,
  WorkDocumentErasePreviewV1,
  WorkDocumentReceiptV1,
  WorkDocumentState,
  WorkDocumentV1,
} from '@/contracts/work-documents';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  OperationalList,
  QueryState,
  StatusBadge,
  formatTime,
  publicErrorText,
} from '@/features/overview/management-ui';
import {
  requestWorkDocumentCommand,
  requestWorkDocumentErasePreview,
  useWorkDocumentWorkspace,
  workDocumentQueryKeys,
  type WorkDocumentCommandInput,
  type WorkDocumentWorkspace,
  type WorkDocumentScope,
} from './api';
import './work-documents.css';

const ERASE_CONFIRMATION = '永久清除';
const EMPTY_WORK_DOCUMENTS: readonly WorkDocumentV1[] = [];

export function WorkDocumentsFeature() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scope: WorkDocumentScope = searchParams.get('scope') === 'history' ? 'history' : 'active';
  const requestedDocumentId = searchParams.get('document') ?? '';
  const [historyDraft, setHistoryDraft] = useState(searchParams.get('query') ?? '');
  const historyQuery = searchParams.get('query')?.trim() ?? '';
  const workspace = useWorkDocumentWorkspace(scope, historyQuery, requestedDocumentId);
  const activeItems = workspace.active.data?.items ?? EMPTY_WORK_DOCUMENTS;
  const historyItems = workspace.history.data?.items ?? EMPTY_WORK_DOCUMENTS;
  const items = scope === 'history' ? historyItems : activeItems;
  const listPending = scope === 'history' ? workspace.history.isPending : workspace.active.isPending;
  const listError = scope === 'history' ? workspace.history.error : workspace.active.error;

  useEffect(() => {
    if (listPending || listError) return;
    const selectionExists = items.some((document) => document.documentId === requestedDocumentId);
    if ((requestedDocumentId && selectionExists) || (!requestedDocumentId && items.length === 0)) return;
    const next = new URLSearchParams(searchParams);
    if (items[0]) next.set('document', items[0].documentId);
    else next.delete('document');
    setSearchParams(next, { replace: true });
  }, [items, listError, listPending, requestedDocumentId, searchParams, setSearchParams]);

  const switchScope = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value === 'history') next.set('scope', 'history');
    else next.delete('scope');
    next.delete('document');
    setSearchParams(next);
  };

  const selectDocument = (documentId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('document', documentId);
    setSearchParams(next);
  };

  const submitHistorySearch = (event: FormEvent) => {
    event.preventDefault();
    const next = new URLSearchParams(searchParams);
    next.set('scope', 'history');
    if (historyDraft.trim()) next.set('query', historyDraft.trim());
    else next.delete('query');
    next.delete('document');
    setSearchParams(next);
  };

  const refresh = () => {
    if (scope === 'history') void workspace.history.refetch();
    else void workspace.active.refetch();
    if (requestedDocumentId) void workspace.detail.refetch();
  };

  return (
    <ManagementPage
      actions={(
        <Button leadingIcon={<RefreshCw size={16} />} loading={workspace.active.isFetching || workspace.history.isFetching} onClick={refresh} size="small">
          刷新
        </Button>
      )}
      description="这里先显示仍需处理的工作文档。完成归档后，仍可在历史中查找、修复或重新打开。"
      eyebrow="有据可查的工作记录"
      routeId="work-documents"
      title="工作文档"
    >
      <QueryState
        error={workspace.capabilities.error as Error | null}
        isPending={workspace.capabilities.isPending}
        onRetry={() => void workspace.capabilities.refetch()}
      >
        {workspace.capabilityKnown && !workspace.supported ? (
          <EmptyState
            action={<Button onClick={() => void workspace.capabilities.refetch()}>重新检查</Button>}
            description="当前版本还没有提供完整的工作文档能力。控制中心不会猜测文档状态，也不会替你执行操作。"
            icon={ShieldAlert}
            title="工作文档暂不可用"
          />
        ) : (
          <Tabs onValueChange={switchScope} value={scope}>
            <TabsList aria-label="工作文档范围">
              <TabsTrigger value="active">活跃文档</TabsTrigger>
              <TabsTrigger value="history">历史归档</TabsTrigger>
            </TabsList>
            <TabsContent value="active">
              <DocumentWorkspace
                detail={workspace.detail}
                items={activeItems}
                listError={listError as Error | null}
                listPending={listPending}
                onRefresh={refresh}
                onSelect={selectDocument}
                scope="active"
                selectedId={requestedDocumentId}
                transport={workspace.transport}
              />
            </TabsContent>
            <TabsContent value="history">
              <form className="work-documents__search" onSubmit={submitHistorySearch} role="search">
                <Field htmlFor="work-document-history-query" label="检索历史归档">
                  <Input
                    id="work-document-history-query"
                    onChange={(event) => setHistoryDraft(event.target.value)}
                    placeholder="按标题、来源或文档标识检索"
                    type="search"
                    value={historyDraft}
                  />
                </Field>
                <Button leadingIcon={<Search size={16} />} type="submit" variant="primary">搜索历史</Button>
              </form>
              <DocumentWorkspace
                detail={workspace.detail}
                items={historyItems}
                listError={listError as Error | null}
                listPending={listPending}
                onRefresh={refresh}
                onSelect={selectDocument}
                scope="history"
                selectedId={requestedDocumentId}
                transport={workspace.transport}
              />
            </TabsContent>
          </Tabs>
        )}
      </QueryState>
    </ManagementPage>
  );
}

type WorkspaceQuery = WorkDocumentWorkspace['detail'];
type WorkspaceTransport = WorkDocumentWorkspace['transport'];
type CommandMutationInput = { command: WorkDocumentCommandInput; fence: string };
type CommandMutation = UseMutationResult<WorkDocumentCommandV1, Error, CommandMutationInput>;
type PreviewMutationInput = { documentId: string; fence: string; sessionId: string };
type PreviewMutationResult = { input: PreviewMutationInput; result: WorkDocumentErasePreviewV1 };
type PreviewMutation = UseMutationResult<PreviewMutationResult, Error, PreviewMutationInput>;

function DocumentWorkspace({
  detail,
  items,
  listError,
  listPending,
  onRefresh,
  onSelect,
  scope,
  selectedId,
  transport,
}: {
  detail: WorkspaceQuery;
  items: readonly WorkDocumentV1[];
  listError: Error | null;
  listPending: boolean;
  onRefresh: () => void;
  onSelect: (documentId: string) => void;
  scope: WorkDocumentScope;
  selectedId: string;
  transport: WorkspaceTransport;
}) {
  return (
    <QueryState
      empty={(
        <EmptyState
          description={scope === 'history'
            ? '调整检索词，或先确认文档已经完成归档。'
            : '这里还没有需要继续处理的文档。归档尚未完成或出现错误时，文档仍会留在这里。'}
          icon={scope === 'history' ? History : FileText}
          title={scope === 'history' ? '没有匹配的历史文档' : '活跃工作区已清理完毕'}
        />
      )}
      error={listError}
      isEmpty={items.length === 0}
      isPending={listPending}
      onRetry={onRefresh}
    >
      <div className="work-documents__workspace">
        <ManagementSection
          description={scope === 'history'
            ? '这里只显示已经完成归档的文档。'
            : '正在处理、归档中或需要修复的文档都会留在这里，不会藏起未完成的操作。'}
          title={scope === 'history' ? '历史结果' : '当前活跃'}
          trailing={<StatusBadge label={`${items.length} 条`} tone="info" />}
        >
          <OperationalList
            items={items.map((document) => ({
              id: document.documentId,
              title: document.title || document.documentId,
              detail: `${authorityLabel(document.authorityKind)} · ${document.authorityId} · 修订 ${document.authorityRevision}`,
              meta: formatTime(document.updatedAtMs),
              onClick: () => onSelect(document.documentId),
              selected: selectedId === document.documentId,
              status: <StatusBadge label={stateLabel(document.state)} tone={stateTone(document.state)} />,
            }))}
          />
        </ManagementSection>
        <WorkDocumentDetail
          key={selectedId || 'empty'}
          detail={detail}
          selectedId={selectedId}
          transport={transport}
        />
      </div>
    </QueryState>
  );
}

function WorkDocumentDetail({
  detail,
  selectedId,
  transport,
}: {
  detail: WorkspaceQuery;
  selectedId: string;
  transport: WorkspaceTransport;
}) {
  const queryClient = useQueryClient();
  const eraseTriggerRef = useRef<HTMLButtonElement>(null);
  const document = detail.data?.document;
  const reopen = detail.data?.reopen;
  const fence = document
    ? `${document.documentId}:${document.authorityRevision}:${document.documentRevision}:${reopen?.authorityRevision ?? 0}:${reopen?.transitionReceiptId ?? ''}`
    : `selection:${selectedId}`;
  const activeFenceRef = useRef(fence);
  activeFenceRef.current = fence;
  const [terminalReceiptId, setTerminalReceiptId] = useState('');
  const [receipt, setReceipt] = useState<WorkDocumentReceiptV1 | null>(null);
  const [eraseOpen, setEraseOpen] = useState(false);
  const [eraseSessionId, setEraseSessionId] = useState('');
  const [eraseConfirmation, setEraseConfirmation] = useState('');

  useEffect(() => {
    setTerminalReceiptId(document?.terminalReceiptId ?? '');
  }, [document?.documentId, document?.terminalReceiptId]);

  useEffect(() => {
    setReceipt(null);
  }, [document?.documentId]);

  const command = useMutation({
    mutationFn: ({ command: input }: CommandMutationInput) => requestWorkDocumentCommand(transport, input),
    onMutate: (input) => {
      if (input.fence === activeFenceRef.current && input.command.documentId === selectedId) {
        setReceipt(null);
      }
    },
    onSuccess: (result, input) => {
      if (input.fence !== activeFenceRef.current || input.command.documentId !== selectedId) return;
      if (result.receipt) setReceipt(result.receipt);
      if (input.command.operation === 'erase' && result.receipt?.status === 'applied') {
        setEraseOpen(false);
        setEraseConfirmation('');
      }
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: workDocumentQueryKeys.root });
    },
  });
  const erasePreview = useMutation({
    mutationFn: async (input: PreviewMutationInput): Promise<PreviewMutationResult> => ({
      input,
      result: await requestWorkDocumentErasePreview(transport, input.documentId, input.sessionId),
    }),
  });

  if (!selectedId) {
    return (
      <section aria-label="工作文档详情" className="work-documents__detail work-documents__detail--empty">
        <FileClock aria-hidden="true" size={24} />
        <h2>选择一份文档</h2>
        <p>选择后可以查看完整状态、来源和操作记录。</p>
      </section>
    );
  }

  return (
    <section aria-label="工作文档详情" className="work-documents__detail">
      <QueryState
        error={detail.error as Error | null}
        isPending={detail.isPending}
        onRetry={() => void detail.refetch()}
      >
        {document ? (
          <>
            <header className="work-documents__detail-header">
              <div>
                <span className="work-documents__kicker">记录编号 · {document.documentId}</span>
                <h2>{document.title || document.documentId}</h2>
              </div>
              <StatusBadge label={stateLabel(document.state)} tone={stateTone(document.state)} />
            </header>

            <section className="work-documents__facts" aria-labelledby="work-document-authority-heading">
              <h3 id="work-document-authority-heading">记录来源</h3>
              <dl>
                <Fact label="来源类型" value={authorityLabel(document.authorityKind)} />
                <Fact label="来源编号" value={document.authorityId} code />
                <Fact label="来源版本" value={document.authorityRevision} />
                <Fact label="来源索引" value={document.authorityKey} code />
              </dl>
            </section>

            <section className="work-documents__facts" aria-labelledby="work-document-integrity-heading">
              <h3 id="work-document-integrity-heading">文件与完整性</h3>
              <dl>
                <Fact label="文档修订" value={document.documentRevision} />
                <Fact label="内容 SHA-256" value={document.contentSha256 || '后端未提供'} code wide />
                <Fact label="当前路径" value={document.path || '后端未提供'} code wide />
                <Fact label="活跃路径" value={document.activePath || '后端未提供'} code wide />
                <Fact label="归档路径" value={document.archivePath || '后端未提供'} code wide />
                <Fact label="工作区根目录" value={document.workspaceRoot || '后端未提供'} code wide />
              </dl>
            </section>

            <section className="work-documents__progress" aria-labelledby="work-document-progress-heading">
              <div className="work-documents__section-heading">
                <div>
                  <h3 id="work-document-progress-heading">移动与索引状态</h3>
                  <p>{progressLabel(document.state)}</p>
                </div>
                <StatusBadge label={stateLabel(document.state)} tone={stateTone(document.state)} />
              </div>
              <dl>
                <Fact label="完成凭证" value={document.terminalReceiptId || '尚无完成凭证'} code wide />
                <Fact label="最近更新" value={formatTime(document.updatedAtMs)} />
                <Fact label="错误" value={document.error || '没有报告错误'} wide />
                <Fact label="仍需留意" value={residualRisk(document)} wide />
              </dl>
            </section>

            {receipt && (!eraseOpen || receipt.operation !== 'erase') ? <CommandReceipt receipt={receipt} /> : null}
            {command.error ? (
              <InlineNotice title="操作未完成" tone="danger">
                {publicErrorText(command.error)} 状态已重新从后端读取前，请勿假定文件已经移动或清除。
              </InlineNotice>
            ) : null}

            <section className="work-documents__actions" aria-labelledby="work-document-actions-heading">
              <div className="work-documents__section-heading">
                <div>
                  <h3 id="work-document-actions-heading">归档与恢复</h3>
                  <p>每次操作都会核对当前版本与完成凭证；查看文档不会自动获得修改权限。</p>
                </div>
              </div>
              {document.state === 'active' ? (
                <div className="work-documents__action-row">
                  <Field
                    description="只有系统签发的完成凭证可以归档。归档只会移动文档并更新目录，不会清除内容。"
                    htmlFor="work-document-terminal-receipt"
                    label="完成凭证编号"
                    required
                  >
                    <Input
                      id="work-document-terminal-receipt"
                      onChange={(event) => setTerminalReceiptId(event.target.value)}
                      value={terminalReceiptId}
                    />
                  </Field>
                  <Button
                    disabled={!terminalReceiptId.trim()}
                    leadingIcon={<Archive size={16} />}
                    loading={command.isPending && command.variables?.command.operation === 'archive'}
                    onClick={() => command.mutate({
                      command: {
                        operation: 'archive',
                        documentId: document.documentId,
                        terminalReceiptId: terminalReceiptId.trim(),
                      },
                      fence,
                    })}
                  >
                    归档到历史
                  </Button>
                </div>
              ) : null}
              {isRepairableState(document.state) ? (
                <div className="work-documents__action-row work-documents__action-row--compact">
                  <p>让后端重新对账文件移动与索引；失败文档会继续留在可发现范围。</p>
                  <Button
                    leadingIcon={<Wrench size={16} />}
                    loading={command.isPending && command.variables?.command.operation === 'repair'}
                    onClick={() => command.mutate({
                      command: { operation: 'repair', documentId: document.documentId },
                      fence,
                    })}
                  >
                    修复移动或索引
                  </Button>
                </div>
              ) : null}
              {document.state === 'archived' ? (
                <div className="work-documents__action-row work-documents__action-row--compact">
                  <p>{reopenGuidance(reopen)}</p>
                  <Button
                    disabled={!reopen?.eligible}
                    leadingIcon={<RotateCcw size={16} />}
                    loading={command.isPending && command.variables?.command.operation === 'reopen'}
                    onClick={() => {
                      if (!reopen?.eligible) return;
                      command.mutate({
                        command: {
                          operation: 'reopen',
                          documentId: document.documentId,
                          authorityRevision: reopen.authorityRevision,
                          transitionReceiptId: reopen.transitionReceiptId,
                        },
                        fence,
                      });
                    }}
                  >
                    重新打开到活跃区
                  </Button>
                </div>
              ) : null}
            </section>

            <section className="work-documents__danger" aria-labelledby="work-document-danger-heading">
              <div>
                <h3 id="work-document-danger-heading">永久清除</h3>
                <p>永久清除与归档是两个独立操作。永久清除需要当前对话、明确审批和内容校验，不能用“归档”替代。</p>
              </div>
              <Button
                ref={eraseTriggerRef}
                disabled={command.isPending}
                leadingIcon={<Trash2 size={16} />}
                onClick={() => setEraseOpen(true)}
                variant="danger"
              >
                永久清除…
              </Button>
            </section>

            <EraseDialog
              command={command}
              confirmation={eraseConfirmation}
              document={document}
              fence={fence}
              onConfirmationChange={setEraseConfirmation}
              onOpenChange={(open) => {
                setEraseOpen(open);
                if (!open) {
                  setEraseConfirmation('');
                  erasePreview.reset();
                }
              }}
              onSessionIdChange={setEraseSessionId}
              open={eraseOpen}
              preview={erasePreview}
              receipt={receipt}
              returnFocusRef={eraseTriggerRef}
              sessionId={eraseSessionId}
            />
          </>
        ) : null}
      </QueryState>
    </section>
  );
}

function EraseDialog({
  command,
  confirmation,
  document,
  fence,
  onConfirmationChange,
  onOpenChange,
  onSessionIdChange,
  open,
  preview,
  receipt,
  returnFocusRef,
  sessionId,
}: {
  command: CommandMutation;
  confirmation: string;
  document: WorkDocumentV1;
  fence: string;
  onConfirmationChange: (value: string) => void;
  onOpenChange: (open: boolean) => void;
  onSessionIdChange: (value: string) => void;
  open: boolean;
  preview: PreviewMutation;
  receipt: WorkDocumentReceiptV1 | null;
  returnFocusRef: { current: HTMLButtonElement | null };
  sessionId: string;
}) {
  const approvedPreview = !preview.isPending && !preview.error && preview.data
    && preview.data.input.documentId === document.documentId
    && preview.data.input.fence === fence
    && preview.data.input.sessionId === sessionId.trim()
      ? preview.data.result
      : null;
  const approvalId = approvedPreview?.approval.approvalId ?? '';
  const payloadSha256 = approvedPreview?.payloadSha256 ?? '';
  const eraseAccepted = receipt?.operation === 'erase' && receipt.status === 'accepted';
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent
        aria-describedby="work-document-erase-description"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocusRef.current?.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>永久清除工作文档</DialogTitle>
          <DialogDescription id="work-document-erase-description">
            这不是归档：批准后会清除“{document.title || document.documentId}”及其受管记录。先选择发起操作的对话，系统会把审批与这次操作内容绑定。
          </DialogDescription>
        </DialogHeader>
        <div className="work-documents__erase-form">
          <Field htmlFor="work-document-erase-session" label="发起操作的对话编号" required>
            <Input
              id="work-document-erase-session"
              onChange={(event) => onSessionIdChange(event.target.value)}
              value={sessionId}
            />
          </Field>
          <Button
            disabled={command.isPending || !sessionId.trim()}
            loading={preview.isPending}
            onClick={() => preview.mutate({ documentId: document.documentId, fence, sessionId: sessionId.trim() })}
          >
            获取清除审批
          </Button>
          {preview.error ? (
            <InlineNotice title="无法获取清除审批" tone="danger">{publicErrorText(preview.error)}</InlineNotice>
          ) : null}
          {approvalId && payloadSha256 ? (
            <div className="work-documents__approval" role="status" aria-label="清除审批已就绪">
              <CheckCircle2 aria-hidden="true" size={18} />
              <div>
                <strong>清除审批已就绪</strong>
                <span>审批 ID</span><code>{approvalId}</code>
                <span>载荷 SHA-256</span><code>{payloadSha256}</code>
              </div>
            </div>
          ) : null}
          <Field
            description={`输入“${ERASE_CONFIRMATION}”确认。此确认不会替代后端审批。`}
            htmlFor="work-document-erase-confirmation"
            label="永久清除确认"
            required
          >
            <Input
              autoComplete="off"
              id="work-document-erase-confirmation"
              onChange={(event) => onConfirmationChange(event.target.value)}
              value={confirmation}
            />
          </Field>
          {command.error ? (
            <InlineNotice title="永久清除未完成" tone="danger">{publicErrorText(command.error)}</InlineNotice>
          ) : null}
          {receipt?.operation === 'erase' ? <CommandReceipt receipt={receipt} /> : null}
        </div>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)} variant="quiet">取消</Button>
          <Button
            disabled={eraseAccepted || confirmation !== ERASE_CONFIRMATION || !approvalId || !payloadSha256}
            loading={command.isPending && command.variables?.command.operation === 'erase'}
            onClick={() => command.mutate({
              command: {
                operation: 'erase',
                documentId: document.documentId,
                sessionId: sessionId.trim(),
                approvalId,
                payloadSha256,
              },
              fence,
            })}
            variant="danger"
          >
            永久清除，不是归档
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Fact({
  code = false,
  label,
  value,
  wide = false,
}: {
  code?: boolean;
  label: string;
  value: string | number;
  wide?: boolean;
}) {
  return (
    <div data-wide={wide || undefined}>
      <dt>{label}</dt>
      <dd>{code ? <code>{value}</code> : value}</dd>
    </div>
  );
}

function CommandReceipt({ receipt }: { receipt: WorkDocumentReceiptV1 }) {
  const tone = receipt.status === 'applied' ? 'success' : receipt.status === 'failed' ? 'danger' : 'info';
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'danger' ? ShieldAlert : FileClock;
  const status = receipt.status === 'applied'
    ? '已应用'
    : receipt.status === 'failed'
      ? '后端拒绝或失败'
      : '已接受，等待后端完成';
  return (
    <div className="work-documents__receipt" data-tone={tone} role="status" aria-live="polite">
      <Icon aria-hidden="true" size={18} />
      <div>
        <strong>后端操作收据 · {status}</strong>
        <span>{receipt.operation} · {receipt.status}{receipt.idempotent ? ' · 幂等重放' : ''}</span>
        <code>{receipt.receiptId}</code>
        <small>{formatTime(receipt.createdAtMs)}</small>
      </div>
    </div>
  );
}

function authorityLabel(value: string): string {
  return {
    session_plan: '对话计划',
    session_goal: '对话目标',
    room_work_item: '协作任务',
  }[value] ?? `未知来源 · ${value || '未提供'}`;
}

function stateLabel(value: string): string {
  return {
    active: '进行中',
    archive_pending: '正在归档',
    archived: '已归档',
    reopen_pending: '正在重新打开',
    error: '需要修复',
  }[value] ?? `未知状态 · ${value || '未提供'}`;
}

function stateTone(value: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (value === 'archived') return 'success';
  if (value === 'archive_pending' || value === 'reopen_pending') return 'warning';
  if (value === 'error') return 'danger';
  if (value === 'active') return 'info';
  return 'warning';
}

function progressLabel(value: string): string {
  return {
    active: '文档仍在当前工作区，暂时没有归档操作。',
    archive_pending: '归档移动或历史目录更新尚未完成。',
    archived: '归档已完成；可从历史归档中查找。',
    reopen_pending: '正在重新打开文档，当前目录尚未更新完成。',
    error: '对账发现问题；文档仍保留在这里，等待修复。',
  }[value] ?? '系统返回了暂时无法识别的状态；这里不会猜测操作已经完成。';
}

function residualRisk(document: WorkDocumentV1): string {
  if (document.error) return document.error;
  return {
    active: '仍是活跃上下文；只有可信终态收据可以启动归档。',
    archive_pending: '文件移动或历史索引可能部分完成；修复前仍显示在活跃列表。',
    archived: '后端未报告残余风险。',
    reopen_pending: '文件回迁或活跃索引可能部分完成；修复前不会显示为 active。',
    error: '后端未提供失败原因；修复后仍需重新读取状态。',
  }[document.state] ?? '状态未知；未执行任何自动操作。';
}

function reopenGuidance(
  reopen: WorkDocumentDetailV1['reopen'] | undefined,
): string {
  switch (reopen?.reasonCode) {
    case 'ready':
      return '来源已进入新的可继续版本；重新打开会按当前版本与过渡凭证回迁文档，并保留历史证据。';
    case 'authority_terminal':
      return '来源仍处于已完成或已取消状态。请先在对应任务中恢复或重置，再刷新此页。';
    case 'authority_not_advanced':
      return '来源尚未产生新的可继续版本。请先恢复来源并刷新此页。';
    case 'authority_unavailable':
      return '暂时无法核对来源状态。请刷新，或先修复来源记录。';
    case 'document_not_archived':
      return '只有已归档文档可以重新打开。';
    default:
      return '正在核对来源版本与过渡凭证；核对完成前不会重新打开。';
  }
}


function isRepairableState(value: string): value is Extract<WorkDocumentState, 'archive_pending' | 'reopen_pending' | 'error'> {
  return value === 'archive_pending' || value === 'reopen_pending' || value === 'error';
}
