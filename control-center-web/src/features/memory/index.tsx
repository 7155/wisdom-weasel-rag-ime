import {
  Archive,
  BookOpen,
  BrainCircuit,
  Database,
  EyeOff,
  Network,
  RefreshCw,
  RotateCcw,
  Search,
  Tags,
} from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
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
  SegmentedControl,
  Select,
  Switch,
  Tabs as ViewTabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  TextArea,
} from '@/components/primitives';
import { useControlTransport } from '@/app/control-transport';
import {
  memoryBookArchivePathIds,
  useMemoryBookArchiveBoundary,
  useMemoryQueries,
  type MemoryKind,
} from './api';
import { MemoryRelations } from './MemoryRelations';
import { PersonalKnowledgeWorkbench } from './PersonalKnowledgeWorkbench';
import {
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  PaginationBar,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import {
  ManagementMutationWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import type { JsonValue } from '@/platform/transport';
import './memory.css';

const kinds = [
  { value: 'books', label: '主题书' },
  { value: 'atoms', label: '原子' },
  { value: 'tags', label: '标签' },
  { value: 'phrases', label: '短语' },
  { value: 'evidence', label: '证据' },
  { value: 'groups', label: '分组' },
  { value: 'negative', label: '负反馈' },
] as const;

export function MemoryFeature() {
  const [view, setView] = useState<'catalog' | 'relations' | 'organize'>('catalog');
  const [kind, setKind] = useState<MemoryKind>('books');
  const [draftQuery, setDraftQuery] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [ownerKey, setOwnerKey] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [editOpen, setEditOpen] = useState(false);
  const selectedOwner = parseOwnerKey(ownerKey);
  const { pages, summary } = useMemoryQueries(
    kind,
    query,
    status,
    selectedOwner.ownerKind,
    selectedOwner.ownerId,
  );
  const archiveBoundary = useMemoryBookArchiveBoundary();
  const summaryPayload = asRecord(summary.data);
  const ownerOptions = useMemo(() => [
    { value: '', label: '全部归属' },
    ...arrayRecords(summaryPayload.owners).map((owner) => {
      const ownerKind = stringValue(owner.ownerKind);
      const ownerId = stringValue(owner.ownerId);
      return {
        value: encodeOwnerKey(ownerKind, ownerId),
        label: `${ownerLabel(ownerKind, ownerId)} · ${numberValue(owner.itemCount)} 项`,
      };
    }),
  ], [summaryPayload.owners]);
  const rows = useMemo(() =>
    (pages.data?.pages ?? []).flatMap((page) => arrayRecords(asRecord(page).items)).map(normalizeMemoryRow),
  [pages.data]);
  const selected = rows.find((row) => stringValue(row.id) === selectedId);
  const selectedStatus = stringValue(selected?.status);
  const selectedType = stringValue(selected?.type);
  const archiveDraft = {
    bookId: selectedId,
    archived: selectedStatus !== 'archived',
    reason: selectedStatus === 'archived' ? 'control_center_restore' : 'control_center_archive',
  };
  const archiveAvailability = archiveBoundary.availability(archiveBlockedReason());
  const runtimeRevision = numberValue(summaryPayload.runtimeRevision);
  const error = (pages.error ?? summary.error) as Error | null;
  const pending = pages.isPending || summary.isPending;
  const refresh = () => Promise.all([pages.refetch(), summary.refetch()]);

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={pages.isRefetching} onClick={refresh} size="small">刷新</Button>}
      description="搜索本地记忆，查看已记录的关系，并管理主题记忆的生命周期。"
      eyebrow="知识与记录"
      routeId="memory"
      title="记忆"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="记忆概览">
          <MetricStrip items={[
            { label: '输入记录', value: numberValue(summaryPayload.eventCount), detail: '已记录', icon: Database },
            { label: '记忆项', value: numberValue(summaryPayload.memoryItemCount), detail: '所有状态', icon: BrainCircuit },
            { label: '整理证据', value: numberValue(summaryPayload.evidenceSourceCount), detail: '可追溯', icon: Archive },
            { label: '主题书', value: numberValue(summaryPayload.memoryBookCount), detail: '长期主题', icon: BookOpen },
            { label: '原子', value: numberValue(summaryPayload.memoryAtomCount), detail: '结构化片段', icon: Tags },
            { label: '已遗忘', value: numberValue(summaryPayload.forgottenSourceCount), detail: '不参与整理', icon: EyeOff },
            { label: '待判断', value: numberValue(summaryPayload.needsReviewSourceCount), detail: '每日复查', icon: RefreshCw, tone: numberValue(summaryPayload.needsReviewSourceCount) ? 'warning' : 'success' },
          ]} />
        </ManagementSection>

        <ViewTabs
          className="memory-view-tabs"
          onValueChange={(next) => setView(next === 'relations' || next === 'organize' ? next : 'catalog')}
          value={view}
        >
          <TabsList aria-label="记忆视图">
            <TabsTrigger value="catalog">目录</TabsTrigger>
            <TabsTrigger value="relations">关系图</TabsTrigger>
            <TabsTrigger value="organize">整理</TabsTrigger>
          </TabsList>
          <TabsContent value="catalog">
            <ManagementSection
              title={kind === 'tags' ? '标签节点目录' : '记忆目录'}
              description={kind === 'tags'
                ? '检索和管理图谱中的标签节点；节点关系在标签图谱中呈现。'
                : '按类型、状态和内容查找记忆。'}
              trailing={kind === 'tags' ? (
                <Button leadingIcon={<Network size={14} />} onClick={() => setView('relations')} size="small">
                  查看标签图谱
                </Button>
              ) : undefined}
            >
              <div className="mgmt-stack">
                <SegmentedControl aria-label="记忆类型" items={kinds} onValueChange={(next) => {
                  setKind(next);
                  setStatus('');
                  if (!ownerAwareKind(next)) setOwnerKey('');
                  setSelectedId('');
                  setEditOpen(false);
                }} value={kind} />
                <div className="mgmt-filter-row">
                  <Field htmlFor="memory-search" label="搜索">
                    <Input id="memory-search" onChange={(event) => setDraftQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') runSearch(); }} placeholder="标题、正文或标签" value={draftQuery} />
                  </Field>
                  <Button leadingIcon={<Search size={14} />} onClick={runSearch} size="small">搜索</Button>
                  <Field htmlFor="memory-status-filter" label="状态">
                    <Select
                      id="memory-status-filter"
                      onValueChange={(value) => {
                        setStatus(value);
                        setSelectedId('');
                        setEditOpen(false);
                      }}
                      options={memoryStatusOptions(kind)}
                      value={status}
                    />
                  </Field>
                  {ownerAwareKind(kind) ? (
                    <Field htmlFor="memory-owner-filter" label="归属">
                      <Select
                        id="memory-owner-filter"
                        onValueChange={(value) => {
                          setOwnerKey(value);
                          setSelectedId('');
                          setEditOpen(false);
                        }}
                        options={ownerOptions}
                        value={ownerKey}
                      />
                    </Field>
                  ) : null}
                </div>
              </div>
              {rows.length ? (
                <>
                  <OperationalList items={rows.map((row) => {
                    const id = stringValue(row.id);
                    const rowStatus = stringValue(row.status, 'unknown');
                    return {
                      id,
                      title: stringValue(row.title, '未命名记忆'),
                      detail: stringValue(row.detail, '暂无摘要'),
                      meta: [
                        kindLabel(kind),
                        sourceLabel(stringValue(row.source)),
                        ownerLabel(stringValue(row.ownerKind), stringValue(row.ownerId)),
                      ].filter(Boolean).join(' · '),
                      status: <StatusBadge label={statusLabel(rowStatus)} tone={statusTone(rowStatus)} />,
                      onClick: () => setSelectedId(id),
                      selected: id === selectedId,
                    };
                  })} />
                  <PaginationBar count={rows.length} hasMore={pages.hasNextPage} isFetching={pages.isFetchingNextPage} onLoadMore={() => void pages.fetchNextPage()} />
                </>
              ) : (
                <EmptyState description="当前筛选没有记忆项。" icon={Search} title="没有匹配结果" />
              )}
            </ManagementSection>

            <ManagementSection title="查看与管理" description="从上方目录选择一项；只有可预览、可确认的操作才会开放。">
              {selected ? <MemoryCatalogDetail kind={kind} row={selected} /> : (
                <EmptyState description="从目录中选择一项，查看完整摘要与可用操作。" icon={BookOpen} title="尚未选择记忆" />
              )}
              <div className="mgmt-grid-2">
                {kind === 'evidence' ? (
                  <MemoryEvidenceDispositionAction
                    disabledReason={sourceDispositionBlockedReason()}
                    onChanged={refresh}
                    row={selected}
                  />
                ) : (
                  <>
                    <DirectMemoryEditAction
                      disabledReason={memoryEditBlockedReason()}
                      onClick={() => setEditOpen(true)}
                    />
                    {archiveAvailability.state === 'unsupported' ? (
                      <UnavailableMemoryAction
                        description="归档或恢复主题记忆，并保留原始内容与关系。"
                        reason={archiveAvailability.reason || '安全归档暂未开放。'}
                        risk="R2"
                        title="管理主题记忆"
                      />
                    ) : (
                      <ManagementMutationWorkflow
                        availability={archiveAvailability}
                        description={archiveDraft.archived
                          ? '归档主题记忆，退出日常自动召回；原始内容与关系仍会保留。'
                          : '恢复主题记忆，重新参与日常记忆召回。'}
                        draftKey={JSON.stringify(archiveDraft)}
                        mutationKey={['memory', 'mutation', 'archive']}
                        onApply={async (preview) => parseManagementWorkReceipt(
                          await archiveBoundary.request({
                            pathId: memoryBookArchivePathIds.apply,
                            body: {
                              ...preview.context,
                              expectedRuntimeRevision: preview.expectedRuntimeRevision,
                              previewToken: preview.previewToken,
                              payloadSha256: preview.payloadSha256,
                              confirmText: preview.requiredConfirm,
                            },
                          }),
                          memoryBookArchivePathIds.apply,
                          preview.payloadSha256,
                        )}
                        onApplied={() => refresh()}
                        onPreview={async () => parseManagementWorkPreview(
                          await archiveBoundary.request({
                            pathId: memoryBookArchivePathIds.preview,
                            body: { ...archiveDraft, expectedRuntimeRevision: runtimeRevision },
                          }),
                          memoryBookArchivePathIds.apply,
                          archiveDraft,
                        )}
                        onRollback={async (receipt, preview) => parseManagementWorkReceipt(
                          await archiveBoundary.request({
                            pathId: memoryBookArchivePathIds.rollback,
                            body: {
                              receiptId: receipt.receiptId,
                              rollbackToken: receipt.rollbackToken,
                              payloadSha256: receipt.payloadSha256,
                              confirmText: 'rollback',
                            },
                          }),
                          memoryBookArchivePathIds.rollback,
                          preview.payloadSha256,
                        )}
                        onRolledBack={() => refresh()}
                        risk="R2"
                        title={archiveDraft.archived ? '归档主题记忆' : '恢复主题记忆'}
                      />
                    )}
                  </>
                )}
              </div>
            </ManagementSection>

            <ManagementSection title="维护草案" description="批量整理必须先生成可逐项审阅的草案。">
              <AgentMemoryAction
                description="审阅去重、合并、归档与标签调整。"
                onClick={() => handoffToAgent('请使用记忆工具检查当前记忆库，生成一份去重、合并、归档与标签调整草案。先逐项说明依据和影响，未经我确认不要写入。')}
                safety="逐项确认"
                title="整理记忆"
              />
            </ManagementSection>
          </TabsContent>
          <TabsContent value="relations">
            <MemoryRelations enabled={view === 'relations'} />
          </TabsContent>
          <TabsContent value="organize">
            <PersonalKnowledgeWorkbench />
          </TabsContent>
        </ViewTabs>
        <MemoryEditDialog
          kind={kind}
          onOpenChange={setEditOpen}
          onSaved={refresh}
          open={editOpen && Boolean(selected)}
          row={selected}
        />
      </QueryState>
    </ManagementPage>
  );

  function runSearch() {
    setSelectedId('');
    setEditOpen(false);
    setQuery(draftQuery.trim());
  }

  function handoffToAgent(draft: string) {
    window.location.hash = `/agent?draft=${encodeURIComponent(draft)}`;
  }

  function archiveBlockedReason(): string {
    if (!selected) return '先从上方目录中选择一项。';
    if (kind !== 'books') return '当前只有主题书支持可回滚归档。';
    if (selectedType !== 'topic') return '只有主题书可以手动归档。';
    if (!['active', 'approved', 'archived'].includes(selectedStatus)) {
      return '当前记忆状态不支持归档或恢复。';
    }
    return '';
  }

  function memoryEditBlockedReason(): string {
    if (!selected) return '先从上方目录中选择一项。';
    if (archiveBoundary.capabilities.isPending) return '正在确认本机记忆编辑能力。';
    if (archiveBoundary.capabilities.error) return '无法确认本机记忆编辑能力，请刷新后重试。';
    if (!archiveBoundary.capabilities.data?.routeIds.includes('memory.edit')) {
      return '当前服务尚未开放本机记忆编辑。';
    }
    return '';
  }

  function sourceDispositionBlockedReason(): string {
    if (!selected) return '先从上方目录中选择一条证据。';
    if (archiveBoundary.capabilities.isPending) return '正在确认本机记忆管理能力。';
    if (archiveBoundary.capabilities.error) return '无法确认本机记忆管理能力，请刷新后重试。';
    if (!archiveBoundary.capabilities.data?.routeIds.includes('memory.source.disposition')) {
      return '当前服务尚未开放证据遗忘与恢复。';
    }
    if (
      selectedStatus === 'not_for_memory'
      && selected.sensitive === true
    ) {
      return '敏感输入不能直接恢复；请改为创建一条不含凭据的明确记忆。';
    }
    if (selectedStatus === 'consolidated') {
      return '这条证据已经写入长期记忆，请改为编辑或归档对应的主题书。';
    }
    if (!['pending', 'remember', 'needs_review', 'not_for_memory', 'expired'].includes(selectedStatus)) {
      return '当前证据状态不支持遗忘或恢复。';
    }
    return '';
  }
}

function normalizeMemoryRow(item: Record<string, unknown>): Record<string, unknown> {
  return {
    id: item.id ?? item.bookId ?? item.atomId ?? item.tagId ?? item.groupId ?? item.phraseId,
    title: item.title ?? item.name ?? item.label ?? item.tag ?? item.text ?? item.phrase ?? item.reason ?? item.value,
    detail: item.detail ?? item.summary ?? item.note ?? item.description ?? item.text ?? item.reason ?? item.value ?? item.aliases,
    source: item.source ?? item.sourceType ?? item.project ?? item.kind,
    status: item.status ?? (item.active === false ? 'inactive' : 'active'),
    type: item.type ?? item.bookType ?? item.kind,
    text: item.text ?? item.textPreview ?? item.phrase,
    summary: item.summary,
    note: item.note,
    description: item.description,
    reason: item.reason,
    active: item.active,
    color: item.color ?? item.color_token,
    tags: safeCatalogStringList(item.tags),
    aliases: safeCatalogStringList(item.aliases),
    ownerKind: item.ownerKind ?? item.owner_kind,
    ownerId: item.ownerId ?? item.owner_id,
    disposition: item.disposition,
    dispositionReason: item.dispositionReason,
    trustClass: item.trustClass,
    sensitive: item.sensitive,
    canForget: item.canForget,
    canRestore: item.canRestore,
    updatedAtMs: item.updatedAtMs ?? item.updated_at_ms,
  };
}

function safeCatalogStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== 'string') return [];
    const text = item.trim().slice(0, 64);
    return text ? [text] : [];
  }).slice(0, 64);
}

function MemoryCatalogDetail({ kind, row }: { kind: MemoryKind; row: Record<string, unknown> }) {
  const values = Array.isArray(row.tags)
    ? safeCatalogStringList(row.tags)
    : Array.isArray(row.aliases)
      ? safeCatalogStringList(row.aliases)
      : [];
  return (
    <section className="memory-catalog-detail" aria-label={`${stringValue(row.title, '记忆')} 详情`}>
      <div>
        <span>{kindLabel(kind)}</span>
        <h3>{stringValue(row.title, '未命名记忆')}</h3>
        <p>{stringValue(row.detail, '暂无摘要')}</p>
      </div>
      <dl>
        <div><dt>状态</dt><dd>{statusLabel(stringValue(row.status))}</dd></div>
        <div><dt>来源</dt><dd>{sourceLabel(stringValue(row.source))}</dd></div>
        {stringValue(row.ownerKind) ? (
          <div><dt>归属</dt><dd>{ownerLabel(stringValue(row.ownerKind), stringValue(row.ownerId))}</dd></div>
        ) : null}
        <div><dt>更新</dt><dd>{formatUpdatedAt(numberValue(row.updatedAtMs ?? row.updated_at_ms))}</dd></div>
        <div><dt>关联</dt><dd>{values.length ? `${values.length} 项` : '暂无'}</dd></div>
      </dl>
      {values.length ? <div className="memory-catalog-detail__tags">{values.slice(0, 8).map((value) => <span key={value}>{value}</span>)}</div> : null}
    </section>
  );
}

interface MemoryEditDraft {
  title: string;
  text: string;
  summary: string;
  note: string;
  description: string;
  tags: string;
  aliases: string;
  type: string;
  color: string;
  reason: string;
  active: boolean;
}

function DirectMemoryEditAction({
  disabledReason,
  onClick,
}: {
  disabledReason: string;
  onClick: () => void;
}) {
  return (
    <div className="mgmt-workflow" data-availability={disabledReason ? 'blocked' : 'available'} data-stage="idle">
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">本机写入</span>
          <strong>编辑内容</strong>
          <p>直接编辑当前选中的记忆，不经过 Agent 转述。</p>
        </div>
        <Button disabled={Boolean(disabledReason)} onClick={onClick} size="small">编辑</Button>
      </div>
      <p className="memory-action-unavailable">{disabledReason || '保存只会作用于当前选择的这项记忆。'}</p>
    </div>
  );
}

function MemoryEvidenceDispositionAction({
  disabledReason,
  onChanged,
  row,
}: {
  disabledReason: string;
  onChanged: () => Promise<unknown> | void;
  row: Record<string, unknown> | undefined;
}) {
  const transport = useControlTransport();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const sourceId = stringValue(row?.id);
  const status = stringValue(row?.status);
  const restoring = status === 'not_for_memory' || status === 'expired';
  const action = restoring ? '恢复证据' : '遗忘证据';
  const disposition = restoring ? 'pending' : 'not_for_memory';

  async function submit() {
    if (!sourceId || disabledReason) return;
    setSaving(true);
    setError('');
    try {
      const result = asRecord(await transport.request({
        pathId: 'memory.source.disposition',
        body: { sourceId, disposition },
      }));
      if (result.ok !== true) throw new Error('memory source disposition rejected');
      await onChanged();
    } catch {
      setError('操作失败，证据状态没有改变。');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mgmt-workflow" data-availability={disabledReason ? 'blocked' : 'available'} data-stage="idle">
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">可回滚</span>
          <strong>{action}</strong>
          <p>
            {restoring
              ? '重新放回每日整理队列；原始证据仍不会直接进入检索。'
              : '从长期记忆整理中排除这条噪声，原始输入和审计记录仍保留。'}
          </p>
        </div>
        <Button
          disabled={Boolean(disabledReason)}
          leadingIcon={restoring ? <RotateCcw size={14} /> : <EyeOff size={14} />}
          loading={saving}
          onClick={() => void submit()}
          size="small"
        >
          {restoring ? '恢复' : '遗忘'}
        </Button>
      </div>
      <p className="memory-action-unavailable">
        {error || disabledReason || (restoring ? '恢复后会在下一次整理时重新判断。' : '之后可以从证据目录中恢复。')}
      </p>
    </div>
  );
}

function MemoryEditDialog({
  kind,
  onOpenChange,
  onSaved,
  open,
  row,
}: {
  kind: MemoryKind;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<unknown> | void;
  open: boolean;
  row: Record<string, unknown> | undefined;
}) {
  const transport = useControlTransport();
  const identity = stringValue(row?.id);
  const [draft, setDraft] = useState<MemoryEditDraft>(() => memoryEditDraft(kind, row));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setDraft(memoryEditDraft(kind, row));
    setError('');
  }, [identity, kind, open, row]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = memoryEditValidation(kind, draft);
    if (validation) {
      setError(validation);
      return;
    }
    if (!identity) {
      setError('这项记忆已经不可用，请关闭窗口后重新选择。');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const result = asRecord(await transport.request({
        pathId: 'memory.edit',
        body: memoryEditBody(kind, identity, draft),
      }));
      if (result.ok !== true) throw new Error('memory edit rejected');
      try {
        await onSaved();
      } catch {
        // The write succeeded; a later manual refresh can recover a failed read.
      }
      onOpenChange(false);
    } catch {
      setError('保存失败。草稿已保留，请确认这项记忆仍然存在后重试。');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!saving) onOpenChange(next); }}>
      <DialogContent className="memory-edit-dialog">
        <DialogHeader>
          <DialogTitle>编辑{kindLabel(kind)}</DialogTitle>
          <DialogDescription>修改只会写入当前选中的本机记忆。</DialogDescription>
        </DialogHeader>
        <form className="memory-edit-form" id="memory-edit-form" onSubmit={(event) => void submit(event)}>
          <MemoryEditFields draft={draft} kind={kind} setDraft={setDraft} />
          {error ? <p className="memory-edit-error" role="alert">{error}</p> : null}
        </form>
        <DialogFooter>
          <Button disabled={saving} onClick={() => onOpenChange(false)} variant="quiet">取消</Button>
          <Button form="memory-edit-form" loading={saving} type="submit" variant="primary">保存</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MemoryEditFields({
  draft,
  kind,
  setDraft,
}: {
  draft: MemoryEditDraft;
  kind: MemoryKind;
  setDraft: (draft: MemoryEditDraft) => void;
}) {
  const update = <Key extends keyof MemoryEditDraft>(key: Key, value: MemoryEditDraft[Key]) => {
    setDraft({ ...draft, [key]: value });
  };
  const colorField = (
    <Field htmlFor="memory-edit-color" label="颜色">
      <Select id="memory-edit-color" onValueChange={(value) => update('color', value)} options={[
        { value: 'blue', label: '蓝色' },
        { value: 'teal', label: '青色' },
        { value: 'green', label: '绿色' },
        { value: 'orange', label: '橙色' },
        { value: 'pink', label: '粉色' },
        { value: 'purple', label: '紫色' },
        { value: 'gray', label: '灰色' },
      ]} value={draft.color} />
    </Field>
  );

  if (kind === 'books') {
    return <>
      <Field htmlFor="memory-edit-title" label="标题" required><Input id="memory-edit-title" maxLength={240} onChange={(event) => update('title', event.target.value)} value={draft.title} /></Field>
      <Field htmlFor="memory-edit-summary" label="摘要"><TextArea id="memory-edit-summary" maxLength={4_000} onChange={(event) => update('summary', event.target.value)} rows={4} value={draft.summary} /></Field>
      <ListField id="memory-edit-tags" label="标签" onChange={(value) => update('tags', value)} value={draft.tags} />
    </>;
  }
  if (kind === 'atoms') {
    return <>
      <Field htmlFor="memory-edit-text" label="正文" required><TextArea id="memory-edit-text" maxLength={8_000} onChange={(event) => update('text', event.target.value)} rows={5} value={draft.text} /></Field>
      <ListField id="memory-edit-tags" label="标签" onChange={(value) => update('tags', value)} value={draft.tags} />
    </>;
  }
  if (kind === 'tags') {
    return <>
      <Field htmlFor="memory-edit-title" label="标签名" required><Input id="memory-edit-title" maxLength={120} onChange={(event) => update('title', event.target.value)} value={draft.title} /></Field>
      <Field htmlFor="memory-edit-description" label="说明"><TextArea id="memory-edit-description" maxLength={2_000} onChange={(event) => update('description', event.target.value)} rows={3} value={draft.description} /></Field>
      <div className="memory-edit-form__split">
        <Field htmlFor="memory-edit-type" label="类型"><Input id="memory-edit-type" maxLength={64} onChange={(event) => update('type', event.target.value)} value={draft.type} /></Field>
        {colorField}
      </div>
      <ListField id="memory-edit-aliases" label="别名" onChange={(value) => update('aliases', value)} value={draft.aliases} />
    </>;
  }
  if (kind === 'phrases') {
    return <Field htmlFor="memory-edit-text" label="短语" required><TextArea id="memory-edit-text" maxLength={2_000} onChange={(event) => update('text', event.target.value)} rows={4} value={draft.text} /></Field>;
  }
  if (kind === 'groups') {
    return <>
      <Field htmlFor="memory-edit-title" label="名称"><Input id="memory-edit-title" maxLength={240} onChange={(event) => update('title', event.target.value)} value={draft.title} /></Field>
      <Field htmlFor="memory-edit-note" label="说明"><TextArea id="memory-edit-note" maxLength={4_000} onChange={(event) => update('note', event.target.value)} rows={4} value={draft.note} /></Field>
      {colorField}
    </>;
  }
  return <>
    <Field htmlFor="memory-edit-reason" label="原因" required><TextArea id="memory-edit-reason" maxLength={2_000} onChange={(event) => update('reason', event.target.value)} rows={4} value={draft.reason} /></Field>
    <Switch checked={draft.active} description="关闭后，这条负反馈将不再参与过滤。" label="启用这条负反馈" onCheckedChange={(checked) => update('active', checked)} />
  </>;
}

function ListField({ id, label, onChange, value }: { id: string; label: string; onChange: (value: string) => void; value: string }) {
  return <Field description="用逗号或换行分隔" htmlFor={id} label={label}><TextArea id={id} maxLength={4_000} onChange={(event) => onChange(event.target.value)} rows={3} value={value} /></Field>;
}

function memoryEditDraft(kind: MemoryKind, row: Record<string, unknown> | undefined): MemoryEditDraft {
  const item = row ?? {};
  return {
    title: stringValue(item.title),
    text: stringValue(item.text),
    summary: stringValue(item.summary),
    note: stringValue(item.note),
    description: stringValue(item.description),
    tags: safeCatalogStringList(item.tags).join('，'),
    aliases: safeCatalogStringList(item.aliases).join('，'),
    type: stringValue(item.type, kind === 'tags' ? 'concept' : ''),
    color: stringValue(item.color, 'blue'),
    reason: stringValue(item.reason),
    active: item.active !== false && numberValue(item.active, 1) !== 0,
  };
}

function memoryEditBody(kind: MemoryKind, id: string, draft: MemoryEditDraft): Record<string, JsonValue> {
  if (kind === 'books') return { kind, id, title: draft.title.trim(), summary: draft.summary.trim(), tags: splitList(draft.tags) };
  if (kind === 'atoms') return { kind, id, text: draft.text.trim(), tags: splitList(draft.tags) };
  if (kind === 'tags') return { kind, id, title: draft.title.trim(), description: draft.description.trim(), type: draft.type.trim() || 'concept', aliases: splitList(draft.aliases), color: draft.color };
  if (kind === 'phrases') return { kind, id, text: draft.text.trim() };
  if (kind === 'groups') return { kind, id, title: draft.title.trim(), note: draft.note.trim(), color: draft.color };
  return { kind, id, reason: draft.reason.trim(), active: draft.active };
}

function memoryEditValidation(kind: MemoryKind, draft: MemoryEditDraft): string {
  if ((kind === 'books' || kind === 'tags') && !draft.title.trim()) return '请填写标题。';
  if ((kind === 'atoms' || kind === 'phrases') && !draft.text.trim()) return '请填写内容。';
  if (kind === 'negative' && !draft.reason.trim()) return '请填写原因。';
  return '';
}

function splitList(value: string): string[] {
  return [...new Set(value.split(/[，,\n]/u).map((item) => item.trim()).filter(Boolean))].slice(0, 64);
}

function UnavailableMemoryAction({
  description,
  reason,
  risk,
  title,
}: {
  description: string;
  reason: string;
  risk: 'R1' | 'R2';
  title: string;
}) {
  return (
    <div className="mgmt-workflow" data-availability="unsupported" data-stage="idle">
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{risk === 'R2' ? '谨慎确认' : '需要确认'}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        <Button disabled size="small">暂未开放</Button>
      </div>
      <p className="memory-action-unavailable">{reason}</p>
    </div>
  );
}

function AgentMemoryAction({
  description,
  disabledReason = '',
  onClick,
  safety,
  title,
}: {
  description: string;
  disabledReason?: string;
  onClick: () => void;
  safety: string;
  title: string;
}) {
  return (
    <div className="mgmt-workflow" data-availability={disabledReason ? 'blocked' : 'available'} data-stage="idle">
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{safety}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        <Button disabled={Boolean(disabledReason)} onClick={onClick} size="small">交给智鼬</Button>
      </div>
      <p className="memory-action-unavailable">{disabledReason || '智鼬会先生成可审阅的方案，不会直接修改记忆。'}</p>
    </div>
  );
}

function kindLabel(kind: MemoryKind): string {
  return {
    books: '主题书',
    atoms: '记忆原子',
    tags: '标签',
    phrases: '短语',
    evidence: '整理证据',
    groups: '分组',
    negative: '负反馈',
  }[kind];
}

function memoryStatusOptions(kind: MemoryKind) {
  if (kind === 'evidence') {
    return [
      { value: '', label: '全部' },
      { value: 'pending', label: '待整理' },
      { value: 'remember', label: '值得保留' },
      { value: 'needs_review', label: '待判断' },
      { value: 'not_for_memory', label: '已遗忘' },
      { value: 'consolidated', label: '已归档入书' },
      { value: 'expired', label: '已过期' },
    ];
  }
  return [
    { value: '', label: '全部' },
    { value: 'active', label: '使用中' },
    { value: 'approved', label: '已确认' },
    { value: 'archived', label: '已归档' },
    { value: 'disabled', label: '已暂停' },
    { value: 'suppressed', label: '已抑制' },
  ];
}

function statusLabel(status: string): string {
  return {
    active: '使用中',
    approved: '已确认',
    archived: '已归档',
    disabled: '已暂停',
    suppressed: '已抑制',
    inactive: '未启用',
    tombstoned: '已移除',
    pending: '待整理',
    remember: '值得保留',
    not_for_memory: '已遗忘',
    needs_review: '待判断',
    consolidated: '已归档入书',
    expired: '已过期',
  }[status] ?? '状态未知';
}

function statusTone(status: string): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (status === 'active' || status === 'approved' || status === 'consolidated') return 'success';
  if (status === 'archived' || status === 'inactive' || status === 'not_for_memory' || status === 'expired') return 'info';
  if (status === 'disabled' || status === 'suppressed' || status === 'pending' || status === 'needs_review' || status === 'remember') return 'warning';
  if (status === 'tombstoned') return 'danger';
  return 'neutral';
}

function sourceLabel(source: string): string {
  const normalized = source.toLocaleLowerCase('en-US');
  if (!normalized) return '本地记忆';
  if (normalized.includes('dsv4') || normalized.includes('deepseek')) return '智能整理';
  if (normalized.includes('user')) return '用户编辑';
  if (normalized.includes('import')) return '导入';
  if (normalized.includes('notion')) return 'Notion';
  if (normalized.includes('rime') || normalized.includes('input')) return '输入记录';
  if (normalized.includes('agent') || normalized.includes('pi')) return 'Agent 整理';
  if (normalized.includes('manual')) return '手动整理';
  if (normalized.includes('sqlite') || normalized.includes('memory_')) return '本地记忆';
  return '其他来源';
}

function ownerAwareKind(kind: MemoryKind): boolean {
  return kind === 'books' || kind === 'atoms' || kind === 'phrases' || kind === 'evidence';
}

function encodeOwnerKey(ownerKind: string, ownerId: string): string {
  return ownerKind && ownerId ? JSON.stringify([ownerKind, ownerId]) : '';
}

function parseOwnerKey(value: string): { ownerKind: string; ownerId: string } {
  try {
    const parsed: unknown = JSON.parse(value);
    if (
      Array.isArray(parsed)
      && parsed.length === 2
      && typeof parsed[0] === 'string'
      && typeof parsed[1] === 'string'
    ) {
      return { ownerKind: parsed[0], ownerId: parsed[1] };
    }
  } catch {
    // An empty or stale filter means "all owners".
  }
  return { ownerKind: '', ownerId: '' };
}

function ownerLabel(ownerKind: string, ownerId: string): string {
  if (!ownerKind || !ownerId) return '';
  if (ownerKind === 'user' && ownerId === 'default') return '个人记忆';
  if (ownerKind === 'shared' && ownerId === 'default') return '全局共享';
  if (ownerKind === 'shared') return `项目共享 · ${ownerId}`;
  if (ownerKind === 'agent') return `角色 · ${ownerId}`;
  if (ownerKind === 'session') return `会话 · ${ownerId}`;
  if (ownerKind === 'room') return `房间 · ${ownerId}`;
  return `${ownerKind} · ${ownerId}`;
}

function formatUpdatedAt(value: number): string {
  if (!value) return '暂无';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(value);
}
