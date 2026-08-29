import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UseMutationResult } from '@tanstack/react-query';
import {
  Archive,
  CheckCircle2,
  FileClock,
  FileText,
  History,
  PanelsTopLeft,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  Trash2,
  Wrench,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Disclosure,
  EmptyState,
  Field,
  Input,
  Select,
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
import { sessionItems } from '@/features/agent/types';
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
import { usePawOsDesktop } from '@/features/paw-os/surface-context';
import { TraceAgentHandoffButton } from '@/features/trace-agent/handoff';
import {
  requestWorkDocumentCommand,
  requestWorkDocumentErasePreview,
  useWorkDocumentWorkspace,
  workDocumentQueryKeys,
  type WorkDocumentCommandInput,
  type WorkDocumentAccess,
  type WorkDocumentWorkspace,
  type WorkDocumentScope,
} from './api';
import './work-documents.css';

const ERASE_CONFIRMATION = '永久清除';
const EMPTY_WORK_DOCUMENTS: readonly WorkDocumentV1[] = [];

export function WorkDocumentsFeature() {
  const queryClient = useQueryClient();
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
  const [registerOpen, setRegisterOpen] = useState(false);
  const [authorityKind, setAuthorityKind] = useState<'session_todo' | 'session_goal' | 'room_work_item'>('session_todo');
  const [authorityId, setAuthorityId] = useState('');
  const [authorityRevision, setAuthorityRevision] = useState('');
  const [workspaceRoot, setWorkspaceRoot] = useState('');
  const [sourcePath, setSourcePath] = useState('');
  const [registerTitle, setRegisterTitle] = useState('');
  const registerMutation = useMutation({
    mutationFn: (input: Extract<WorkDocumentCommandInput, { operation: 'register' }>) => (
      requestWorkDocumentCommand(workspace.transport, input)
    ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: workDocumentQueryKeys.root });
    },
  });
  const registrationReady = Boolean(
    authorityId.trim()
    && /^\d+$/.test(authorityRevision)
    && workspaceRoot.trim()
    && sourcePath.trim().startsWith('docs/')
    && sourcePath.trim().endsWith('.md'),
  );

  useEffect(() => {
    if (scope !== 'history' || !workspace.capabilityKnown || workspace.access.history) return;
    const next = new URLSearchParams(searchParams);
    next.delete('scope');
    next.delete('document');
    setSearchParams(next, { replace: true });
  }, [scope, searchParams, setSearchParams, workspace.access.history, workspace.capabilityKnown]);

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
        <>
          {workspace.capabilityKnown && workspace.access.register ? (
            <Button
              leadingIcon={<Plus size={16} />}
              onClick={() => {
                registerMutation.reset();
                setRegisterOpen(true);
              }}
              size="small"
              variant="primary"
            >
              登记工作文档
            </Button>
          ) : null}
          <Button leadingIcon={<RefreshCw size={16} />} loading={workspace.active.isFetching || workspace.history.isFetching} onClick={refresh} size="small">
            刷新
          </Button>
        </>
      )}
      description="查看仍在处理中的文档；归档后也能在历史中找到、恢复或处理异常。"
      eyebrow="工作记录"
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
            description="当前应用还不能读取工作文档列表和详情。升级或重新打开应用后，再回来检查。"
            icon={ShieldAlert}
            title="工作文档暂不可用"
          />
        ) : (
          <Tabs onValueChange={switchScope} value={scope}>
            <TabsList aria-label="工作文档范围">
              <TabsTrigger value="active">活跃文档</TabsTrigger>
              <TabsTrigger disabled={!workspace.access.history} value="history">历史归档</TabsTrigger>
            </TabsList>
            {!workspace.access.register || !workspace.access.archive || !workspace.access.repair || !workspace.access.reopen || !workspace.access.erase ? (
              <InlineNotice title="当前应用以阅读为主" tone="info">
                文档与状态可以正常查看；当前应用未提供的登记、归档、修复、恢复或永久清除操作会保持禁用。
              </InlineNotice>
            ) : null}
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
                access={workspace.access}
              />
            </TabsContent>
            <TabsContent value="history">
              <form className="work-documents__search" onSubmit={submitHistorySearch} role="search">
                <Field htmlFor="work-document-history-query" label="检索历史归档">
                  <Input
                    id="work-document-history-query"
                    onChange={(event) => setHistoryDraft(event.target.value)}
                    placeholder="按标题或来源搜索"
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
                access={workspace.access}
              />
            </TabsContent>
          </Tabs>
        )}
      </QueryState>
      {workspace.access.register ? (
        <Dialog
          onOpenChange={(open) => {
            setRegisterOpen(open);
            if (!open) registerMutation.reset();
          }}
          open={registerOpen}
        >
          <DialogContent className="work-documents__register-dialog">
            <DialogHeader>
              <DialogTitle>登记工作文档</DialogTitle>
              <DialogDescription>
                将已有 Markdown 文件绑定到当前真实任务、目标或 Room WorkItem。登记不会创建第二套任务状态。
              </DialogDescription>
            </DialogHeader>
            <form
              className="work-documents__register-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (!registrationReady) return;
                registerMutation.mutate({
                  operation: 'register',
                  authorityKind,
                  authorityId: authorityId.trim(),
                  authorityRevision: Number(authorityRevision),
                  workspaceRoot: workspaceRoot.trim(),
                  sourcePath: sourcePath.trim(),
                  title: registerTitle.trim(),
                });
              }}
            >
              <Field htmlFor="work-document-register-kind" label="来源类型" required>
                <Select
                  aria-label="来源类型"
                  id="work-document-register-kind"
                  onValueChange={(value) => setAuthorityKind(value as typeof authorityKind)}
                  options={[
                    { label: '对话任务', value: 'session_todo' },
                    { label: '对话目标', value: 'session_goal' },
                    { label: 'Room WorkItem', value: 'room_work_item' },
                  ]}
                  value={authorityKind}
                />
              </Field>
              <div className="work-documents__register-grid">
                <Field htmlFor="work-document-register-authority" label="来源编号" required>
                  <Input id="work-document-register-authority" onChange={(event) => setAuthorityId(event.target.value)} value={authorityId} />
                </Field>
                <Field htmlFor="work-document-register-revision" label="来源版本" required>
                  <Input id="work-document-register-revision" min="0" onChange={(event) => setAuthorityRevision(event.target.value)} type="number" value={authorityRevision} />
                </Field>
              </div>
              <Field htmlFor="work-document-register-root" label="工作区根目录" required>
                <Input id="work-document-register-root" onChange={(event) => setWorkspaceRoot(event.target.value)} placeholder="/path/to/project" value={workspaceRoot} />
              </Field>
              <Field
                description="必须是工作区内 docs/ 下已经存在的 Markdown 文件。"
                htmlFor="work-document-register-source"
                label="Markdown 来源路径"
                required
              >
                <Input id="work-document-register-source" onChange={(event) => setSourcePath(event.target.value)} placeholder="docs/agent/work/current.md" value={sourcePath} />
              </Field>
              <Field htmlFor="work-document-register-title" label="标题（可选）">
                <Input id="work-document-register-title" onChange={(event) => setRegisterTitle(event.target.value)} value={registerTitle} />
              </Field>
              {registerMutation.error ? (
                <InlineNotice title="登记未完成" tone="danger">
                  {publicErrorText(registerMutation.error)} 列表已保持原状，可以核对来源与版本后重试。
                  <TraceAgentHandoffButton handoff={{
                    kind: 'file',
                    entityId: authorityId || sourcePath || 'work-document-registration',
                    title: '工作文档登记失败',
                    summary: publicErrorText(registerMutation.error),
                    error: registerMutation.error instanceof Error ? registerMutation.error.message : String(registerMutation.error),
                    sourceRoute: '/work-documents',
                    workspaceRoots: workspaceRoot ? [workspaceRoot] : [],
                    refs: { authorityKind, authorityId, authorityRevision, sourcePath },
                  }} />
                </InlineNotice>
              ) : null}
              {registerMutation.data?.receipt?.status === 'applied' ? (
                <InlineNotice title="登记完成" tone="success">
                  工作文档已由 Registry 接受，活跃列表正在同步。
                </InlineNotice>
              ) : null}
              {registerMutation.data?.receipt?.status === 'accepted' ? (
                <InlineNotice title="登记已接受" tone="info">
                  Registry 已接受登记请求；活跃列表正在同步。
                </InlineNotice>
              ) : null}
              {registerMutation.data?.receipt?.status === 'failed' ? (
                <InlineNotice title="登记未完成" tone="danger">
                  Registry 返回失败收据；列表已重新同步，请修正来源后重试。
                  <TraceAgentHandoffButton
                    handoff={{
                      kind: 'file',
                      entityId: authorityId || sourcePath || 'work-document-registration',
                      title: '工作文档登记返回失败收据',
                      summary: 'Registry 返回失败收据。',
                      sourceRoute: '/work-documents',
                      workspaceRoots: workspaceRoot ? [workspaceRoot] : [],
                      refs: { authorityKind, authorityId, authorityRevision, sourcePath },
                    }}
                  />
                </InlineNotice>
              ) : null}
              <DialogFooter>
                <Button onClick={() => setRegisterOpen(false)} type="button">取消</Button>
                <Button disabled={!registrationReady || registerMutation.isPending} loading={registerMutation.isPending} type="submit" variant="primary">
                  确认登记
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      ) : null}
    </ManagementPage>
  );
}

type WorkspaceQuery = WorkDocumentWorkspace['detail'];
type WorkspaceTransport = WorkDocumentWorkspace['transport'];
type DetailWorkDocumentCommandInput = Exclude<WorkDocumentCommandInput, { operation: 'register' }>;
type CommandMutationInput = { command: DetailWorkDocumentCommandInput; fence: string };
type CommandMutation = UseMutationResult<WorkDocumentCommandV1, Error, CommandMutationInput>;
type PreviewMutationInput = { documentId: string; fence: string; sessionId: string };
type PreviewMutationResult = { input: PreviewMutationInput; result: WorkDocumentErasePreviewV1 };
type PreviewMutation = UseMutationResult<PreviewMutationResult, Error, PreviewMutationInput>;

function DocumentWorkspace({
  access,
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
  access: WorkDocumentAccess;
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
              title: document.title || '未命名工作文档',
              detail: `来自${authorityLabel(document.authorityKind)}`,
              meta: formatTime(document.updatedAtMs),
              onClick: () => onSelect(document.documentId),
              selected: selectedId === document.documentId,
              status: <StatusBadge label={stateLabel(document.state)} tone={stateTone(document.state)} />,
            }))}
          />
        </ManagementSection>
        <WorkDocumentDetail
          access={access}
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
  access,
  detail,
  selectedId,
  transport,
}: {
  access: WorkDocumentAccess;
  detail: WorkspaceQuery;
  selectedId: string;
  transport: WorkspaceTransport;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const pawOsDesktop = usePawOsDesktop();
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
  const eraseSessions = useQuery({
    enabled: access.erase && eraseOpen,
    queryKey: ['work-documents', 'erase-approval-sessions'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.sessions.list',
      query: { limit: 200 },
      signal,
    }),
    retry: false,
    staleTime: 5_000,
  });
  const eraseSessionOptions = useMemo(
    () => conversationOptions(sessionItems(eraseSessions.data).filter((item) => item.status !== 'archived')),
    [eraseSessions.data],
  );

  useEffect(() => {
    setTerminalReceiptId(document?.terminalReceiptId ?? '');
  }, [document?.documentId, document?.terminalReceiptId]);

  useEffect(() => {
    setReceipt(null);
  }, [document?.documentId]);

  useEffect(() => {
    if (!eraseOpen || eraseSessions.isPending || eraseSessions.error || eraseSessionOptions.length === 0) return;
    if (eraseSessionOptions.some((option) => option.value === eraseSessionId)) return;
    setEraseSessionId(eraseSessionOptions[0].value);
  }, [eraseOpen, eraseSessionId, eraseSessionOptions, eraseSessions.error, eraseSessions.isPending]);

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
        <p>选择后可以查看当前状态和可用操作。</p>
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
                <span className="work-documents__kicker">工作文档</span>
                <h2>{document.title || '未命名工作文档'}</h2>
              </div>
              <div className="work-documents__detail-window-actions">
                {pawOsDesktop ? (
                  <Button
                    leadingIcon={<PanelsTopLeft size={15} />}
                    onClick={() => pawOsDesktop.openWindow({
                      appId: 'project-workbench',
                      target: {
                        kind: 'work-document',
                        id: document.documentId,
                        title: document.title || '未命名工作文档',
                        subtitle: document.path || document.authorityId,
                      },
                    })}
                    size="small"
                    variant="quiet"
                  >
                    独立窗口
                  </Button>
                ) : null}
                <StatusBadge label={stateLabel(document.state)} tone={stateTone(document.state)} />
              </div>
            </header>

            <section className="work-documents__progress" aria-labelledby="work-document-progress-heading">
              <div className="work-documents__section-heading">
                <div>
                  <h3 id="work-document-progress-heading">当前状态</h3>
                  <p>{progressLabel(document.state)}</p>
                </div>
                <StatusBadge label={stateLabel(document.state)} tone={stateTone(document.state)} />
              </div>
              <dl>
                <Fact label="最近更新" value={formatTime(document.updatedAtMs)} />
                <Fact label="错误" value={document.error || '没有报告错误'} wide />
                <Fact label="仍需留意" value={residualRisk(document)} wide />
              </dl>
            </section>

            <Disclosure className="work-documents__technical-details" summary="高级：来源与技术信息">
              <section className="work-documents__facts" aria-labelledby="work-document-authority-heading">
                <h3 id="work-document-authority-heading">记录来源</h3>
                <dl>
                  <Fact label="来源类型" value={authorityLabel(document.authorityKind)} />
                  <Fact label="来源编号" value={document.authorityId} code />
                  <Fact label="来源版本" value={document.authorityRevision} />
                  <Fact label="来源索引" value={document.authorityKey} code />
                  <Fact label="完成记录" value={document.terminalReceiptId || '尚无完成记录'} code wide />
                </dl>
              </section>
              <section className="work-documents__facts" aria-labelledby="work-document-integrity-heading">
                <h3 id="work-document-integrity-heading">文件与完整性</h3>
                <dl>
                  <Fact label="文档修订" value={document.documentRevision} />
                  <Fact label="内容校验值" value={document.contentSha256 || '暂无'} code wide />
                  <Fact label="当前路径" value={document.path || '暂无'} code wide />
                  <Fact label="活跃路径" value={document.activePath || '暂无'} code wide />
                  <Fact label="归档路径" value={document.archivePath || '暂无'} code wide />
                  <Fact label="工作区根目录" value={document.workspaceRoot || '暂无'} code wide />
                </dl>
              </section>
            </Disclosure>

            {receipt && (!eraseOpen || receipt.operation !== 'erase') ? <CommandReceipt receipt={receipt} /> : null}
            {receipt?.status === 'failed' && (!eraseOpen || receipt.operation !== 'erase') ? (
              <TraceAgentHandoffButton
                handoff={{
                  kind: 'file',
                  entityId: document.documentId,
                  title: `工作文档${operationLabel(receipt.operation)}失败`,
                  summary: 'Registry 返回失败收据。',
                  failureRef: receipt.receiptId,
                  sourceRoute: `/work-documents?document=${encodeURIComponent(document.documentId)}`,
                  workspaceRoots: document.workspaceRoot ? [document.workspaceRoot] : [],
                  refs: {
                    operation: receipt.operation,
                    documentRevision: document.documentRevision,
                    authorityRevision: document.authorityRevision,
                  },
                }}
              />
            ) : null}
            {command.error ? (
              <InlineNotice title="操作未完成" tone="danger">
                {publicErrorText(command.error)} 状态重新同步前，请勿假定文件已经移动或清除。
                <TraceAgentHandoffButton
                  handoff={{
                    kind: 'file',
                    entityId: document.documentId,
                    title: '工作文档操作失败',
                    summary: publicErrorText(command.error),
                    error: command.error instanceof Error ? command.error.message : String(command.error),
                    sourceRoute: `/work-documents?document=${encodeURIComponent(document.documentId)}`,
                    workspaceRoots: document.workspaceRoot ? [document.workspaceRoot] : [],
                    refs: {
                      operation: command.variables?.command.operation ?? '',
                      documentRevision: document.documentRevision,
                      authorityRevision: document.authorityRevision,
                    },
                  }}
                />
              </InlineNotice>
            ) : null}

            <section className="work-documents__actions" aria-labelledby="work-document-actions-heading">
              <div className="work-documents__section-heading">
                <div>
                  <h3 id="work-document-actions-heading">归档与恢复</h3>
                  <p>归档或恢复前会核对这份文档是否已完成；仅查看不会改变文档。</p>
                </div>
              </div>
              {document.state === 'active' ? (
                <div className="work-documents__action-row">
                  <Field
                    description="归档前需要提供这份文档已完成的依据。归档不会清除内容。"
                    htmlFor="work-document-terminal-receipt"
                    label="完成依据"
                    required
                  >
                    <Input
                      id="work-document-terminal-receipt"
                      onChange={(event) => setTerminalReceiptId(event.target.value)}
                      value={terminalReceiptId}
                    />
                  </Field>
                  <Button
                    disabled={!access.archive || !terminalReceiptId.trim()}
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
                    {access.archive ? '归档到历史' : '当前宿主不支持归档'}
                  </Button>
                </div>
              ) : null}
              {isRepairableState(document.state) ? (
                <div className="work-documents__action-row work-documents__action-row--compact">
                  <p>重新检查文档是否可正常使用；遇到问题的文档仍会保留在列表中。</p>
                  <Button
                    disabled={!access.repair}
                    leadingIcon={<Wrench size={16} />}
                    loading={command.isPending && command.variables?.command.operation === 'repair'}
                    onClick={() => command.mutate({
                      command: { operation: 'repair', documentId: document.documentId },
                      fence,
                    })}
                  >
                    {access.repair ? '重新检查状态' : '当前应用不支持重新检查'}
                  </Button>
                </div>
              ) : null}
              {document.state === 'archived' ? (
                <div className="work-documents__action-row work-documents__action-row--compact">
                  <p>{reopenGuidance(reopen)}</p>
                  <Button
                    disabled={!access.reopen || !reopen?.eligible}
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
                    {access.reopen ? '重新打开到活跃区' : '当前宿主不支持重新打开'}
                  </Button>
                </div>
              ) : null}
            </section>

            {access.erase ? <section className="work-documents__danger" aria-labelledby="work-document-danger-heading">
              <div>
                <h3 id="work-document-danger-heading">永久清除</h3>
                <p>永久清除与归档不同：它会删除受管记录，且不能恢复。需要明确审批和输入确认词。</p>
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
            </section> : null}

            {access.erase ? <EraseDialog
              command={command}
              confirmation={eraseConfirmation}
              document={document}
              fence={fence}
              onConfirmationChange={setEraseConfirmation}
              onOpenConversation={() => {
                setEraseOpen(false);
                void navigate('/agent');
              }}
              onOpenChange={(open) => {
                setEraseOpen(open);
                if (!open) {
                  setEraseConfirmation('');
                  erasePreview.reset();
                }
              }}
              onSessionIdChange={setEraseSessionId}
              onSessionsRetry={() => void eraseSessions.refetch()}
              open={eraseOpen}
              preview={erasePreview}
              receipt={receipt}
              returnFocusRef={eraseTriggerRef}
              sessionError={eraseSessions.error as Error | null}
              sessionId={eraseSessionId}
              sessionOptions={eraseSessionOptions}
              sessionsPending={eraseSessions.isFetching}
            /> : null}
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
  onOpenConversation,
  onOpenChange,
  onSessionIdChange,
  onSessionsRetry,
  open,
  preview,
  receipt,
  returnFocusRef,
  sessionError,
  sessionId,
  sessionOptions,
  sessionsPending,
}: {
  command: CommandMutation;
  confirmation: string;
  document: WorkDocumentV1;
  fence: string;
  onConfirmationChange: (value: string) => void;
  onOpenConversation: () => void;
  onOpenChange: (open: boolean) => void;
  onSessionIdChange: (value: string) => void;
  onSessionsRetry: () => void;
  open: boolean;
  preview: PreviewMutation;
  receipt: WorkDocumentReceiptV1 | null;
  returnFocusRef: { current: HTMLButtonElement | null };
  sessionError: Error | null;
  sessionId: string;
  sessionOptions: Array<{ label: string; value: string }>;
  sessionsPending: boolean;
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
        className="work-documents__erase-dialog"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocusRef.current?.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>永久清除工作文档</DialogTitle>
          <DialogDescription id="work-document-erase-description">
            这不是归档：批准后会清除“{document.title || '这份工作文档'}”及其受管记录。选择一段对话接收审批，系统会自动完成关联。
          </DialogDescription>
        </DialogHeader>
        <div className="work-documents__erase-form">
          {sessionError ? (
            <InlineNotice title="暂时无法读取可用对话" tone="danger">
              重新读取不会清除任何内容。
              <Button loading={sessionsPending} onClick={onSessionsRetry} size="small" variant="quiet">重新读取</Button>
            </InlineNotice>
          ) : sessionOptions.length ? (
            <Field description="审批请求会出现在这段对话中；列表只显示对话名称。" htmlFor="work-document-erase-session" label="接收审批的对话" required>
              <Select
                aria-label="接收审批的对话"
                id="work-document-erase-session"
                onValueChange={onSessionIdChange}
                options={sessionOptions}
                value={sessionId}
              />
            </Field>
          ) : sessionsPending ? (
            <InlineNotice title="正在读取可用对话" tone="info">读取完成后即可准备清除审批。</InlineNotice>
          ) : (
            <InlineNotice title="没有可用于审批的对话" tone="warning">
              先打开一段伙伴对话，再回来继续永久清除。
              <Button onClick={onOpenConversation} size="small" variant="quiet">打开对话</Button>
            </InlineNotice>
          )}
          <Button
            disabled={command.isPending || sessionsPending || Boolean(sessionError) || !sessionId.trim()}
            loading={preview.isPending}
            onClick={() => preview.mutate({ documentId: document.documentId, fence, sessionId: sessionId.trim() })}
          >
            准备永久清除
          </Button>
          {preview.error ? (
            <InlineNotice title="无法获取清除审批" tone="danger">
              {publicErrorText(preview.error)}
              <TraceAgentHandoffButton
                handoff={{
                  kind: 'file',
                  entityId: document.documentId,
                  title: '工作文档清除审批失败',
                  summary: publicErrorText(preview.error),
                  error: preview.error instanceof Error ? preview.error.message : String(preview.error),
                  sessionId: sessionId.trim() || undefined,
                  sourceRoute: `/work-documents?document=${encodeURIComponent(document.documentId)}`,
                  workspaceRoots: document.workspaceRoot ? [document.workspaceRoot] : [],
                  refs: { operation: 'erase-preview', documentRevision: document.documentRevision },
                }}
              />
            </InlineNotice>
          ) : null}
          {approvalId && payloadSha256 ? (
            <div className="work-documents__approval" role="status" aria-label="清除审批已就绪">
              <CheckCircle2 aria-hidden="true" size={18} />
              <div>
                <strong>清除审批已就绪</strong>
                <span>审批已绑定到这份文档和关联对话。</span>
              </div>
            </div>
          ) : null}
          <Field
            description={`输入“${ERASE_CONFIRMATION}”确认。系统审批仍会独立生效。`}
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
            <InlineNotice title="永久清除未完成" tone="danger">
              {publicErrorText(command.error)}
              <TraceAgentHandoffButton
                handoff={{
                  kind: 'file',
                  entityId: document.documentId,
                  title: '工作文档永久清除失败',
                  summary: publicErrorText(command.error),
                  error: command.error instanceof Error ? command.error.message : String(command.error),
                  sessionId: sessionId.trim() || undefined,
                  sourceRoute: `/work-documents?document=${encodeURIComponent(document.documentId)}`,
                  workspaceRoots: document.workspaceRoot ? [document.workspaceRoot] : [],
                  refs: { operation: 'erase', documentRevision: document.documentRevision },
                }}
              />
            </InlineNotice>
          ) : null}
          {receipt?.operation === 'erase' ? <CommandReceipt receipt={receipt} /> : null}
          {receipt?.operation === 'erase' && receipt.status === 'failed' ? (
            <TraceAgentHandoffButton
              handoff={{
                kind: 'file',
                entityId: document.documentId,
                title: '工作文档永久清除返回失败收据',
                summary: 'Registry 返回失败收据。',
                failureRef: receipt.receiptId,
                sessionId: sessionId.trim() || undefined,
                sourceRoute: `/work-documents?document=${encodeURIComponent(document.documentId)}`,
                workspaceRoots: document.workspaceRoot ? [document.workspaceRoot] : [],
                refs: { operation: 'erase', documentRevision: document.documentRevision },
              }}
            />
          ) : null}
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
      ? '未完成'
      : '已接受，等待完成';
  return (
    <div className="work-documents__receipt" data-tone={tone} role="status" aria-live="polite">
      <Icon aria-hidden="true" size={18} />
      <div>
        <strong>操作结果 · {status}</strong>
        <span>{operationLabel(receipt.operation)}{receipt.idempotent ? ' · 已避免重复执行' : ''}</span>
        <small>结果已记录 · {formatTime(receipt.createdAtMs)}</small>
      </div>
    </div>
  );
}

function operationLabel(value: string): string {
  return ({ archive: '归档文档', reopen: '重新打开文档', erase: '永久清除文档' } as Record<string, string>)[value]
    ?? '文档操作';
}

function authorityLabel(value: string): string {
  return {
    session_todo: '对话任务',
    session_goal: '对话目标',
    room_work_item: '协作任务',
  }[value] ?? '其他来源';
}

function conversationOptions(
  sessions: readonly { id: string; title: string; updatedAtMs: number }[],
): Array<{ label: string; value: string }> {
  const titleCounts = new Map<string, number>();
  sessions.forEach((session) => {
    const rawTitle = session.title.trim();
    const title = rawTitle && rawTitle !== session.id ? rawTitle : '未命名对话';
    titleCounts.set(title, (titleCounts.get(title) ?? 0) + 1);
  });
  return sessions.map((session) => {
    const rawTitle = session.title.trim();
    const title = rawTitle && rawTitle !== session.id ? rawTitle : '未命名对话';
    return {
      label: (titleCounts.get(title) ?? 0) > 1 ? `${title} · ${formatTime(session.updatedAtMs)}` : title,
      value: session.id,
    };
  });
}

function stateLabel(value: string): string {
  return {
    active: '进行中',
    archive_pending: '正在归档',
    archived: '已归档',
    reopen_pending: '正在重新打开',
    error: '需要修复',
  }[value] ?? '状态待确认';
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
    active: '这份文档仍在进行中，可以在完成后归档。',
    archive_pending: '正在归档，完成前会继续显示在活跃文档中。',
    archived: '归档已完成；可从历史归档中查找。',
    reopen_pending: '正在恢复到活跃文档，完成前请稍候。',
    error: '状态检查发现问题；文档仍保留在这里，等待修复。',
  }[value] ?? '暂时无法确认当前状态；这里不会假定操作已经完成。';
}

function residualRisk(document: WorkDocumentV1): string {
  if (document.error) return document.error;
  return {
    active: '文档仍在使用中；只有对应任务明确结束后才能归档。',
    archive_pending: '文件移动或归档索引可能尚未完成；修复前仍显示在当前列表。',
    archived: '目前没有发现残余风险。',
    reopen_pending: '文档返回当前目录或索引更新可能尚未完成；修复前不会显示为进行中。',
    error: '暂时没有可用的失败原因；修复后仍需重新读取状态。',
  }[document.state] ?? '状态待确认；系统没有自动处理。';
}

function reopenGuidance(
  reopen: WorkDocumentDetailV1['reopen'] | undefined,
): string {
  switch (reopen?.reasonCode) {
    case 'ready':
      return '来源已经可以继续；重新打开会按当前状态恢复文档，并保留历史记录。';
    case 'authority_terminal':
      return '来源仍处于已完成或已取消状态。请先在对应任务中恢复或重置，再刷新此页。';
    case 'authority_not_advanced':
      return '来源尚未产生新的可继续版本。请先恢复来源并刷新此页。';
    case 'authority_unavailable':
      return '暂时无法核对来源状态。请刷新，或先修复来源记录。';
    case 'document_not_archived':
      return '只有已归档文档可以重新打开。';
    default:
      return '正在核对来源状态；核对完成前不会重新打开。';
  }
}


function isRepairableState(value: string): value is Extract<WorkDocumentState, 'archive_pending' | 'reopen_pending' | 'error'> {
  return value === 'archive_pending' || value === 'reopen_pending' || value === 'error';
}
