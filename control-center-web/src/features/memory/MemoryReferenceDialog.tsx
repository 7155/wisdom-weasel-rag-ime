import {
  ArrowLeft,
  ChevronRight,
  EyeOff,
  Fingerprint,
  GitBranch,
  LoaderCircle,
  ShieldAlert,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/primitives';
import {
  InlineNotice,
  StatusBadge,
  asRecord,
  numberValue,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import { useMemoryReference, type MemoryReferenceKind } from './api';

export interface MemoryReferenceSelection {
  kind: MemoryReferenceKind;
  referenceId: string;
  label?: string;
}

interface MemoryReferenceDialogProps extends MemoryReferenceSelection {
  onOpenChange: (open: boolean) => void;
}

const maximumReferenceDepth = 6;

export function MemoryReferenceDialog({
  kind,
  label = '',
  onOpenChange,
  referenceId,
}: MemoryReferenceDialogProps) {
  const root = useMemo<MemoryReferenceSelection>(
    () => ({ kind, referenceId, label }),
    [kind, label, referenceId],
  );
  const [stack, setStack] = useState<MemoryReferenceSelection[]>(referenceId ? [root] : []);

  useEffect(() => {
    setStack(referenceId ? [root] : []);
  }, [referenceId, root]);

  const current = stack[stack.length - 1] ?? root;
  const query = useMemoryReference(current.kind, current.referenceId, Boolean(referenceId));
  const payload = asRecord(query.data);
  const directItem = asRecord(payload.item);
  const item = Object.keys(directItem).length ? directItem : asRecord(payload.reference);
  const directSource = asRecord(payload.source);
  const source = Object.keys(directSource).length ? directSource : asRecord(item.source);
  const directRef = asRecord(payload.ref);
  const canonicalRef = Object.keys(directRef).length ? directRef : asRecord(item.ref);
  const references = mergeEvidenceReferences([
    payload.evidenceRefs,
    payload.references,
    payload.sourceRefs,
    item.evidenceRefs,
    item.references,
    item.sourceRefs,
  ], current.kind);
  const disposition = stringValue(
    item.disposition,
    stringValue(payload.disposition, stringValue(item.status, stringValue(canonicalRef.status))),
  );
  const redacted = referenceIsRedacted(payload, item, source);
  const forgotten = ['not_for_memory', 'expired', 'tombstoned', 'forgotten'].includes(disposition);
  const title = referenceTitle(item, current);
  const content = redacted ? '' : referenceContent(item);
  const currentKey = referenceKey(current);
  const visited = new Set(stack.map(referenceKey));

  function openReference(next: MemoryReferenceSelection) {
    const nextKey = referenceKey(next);
    if (visited.has(nextKey) || stack.length >= maximumReferenceDepth) return;
    setStack((currentStack) => [...currentStack, next]);
  }

  return (
    <Dialog open={Boolean(referenceId)} onOpenChange={onOpenChange}>
      <DialogContent className="memory-reference-dialog">
        <DialogHeader>
          <DialogTitle>{title || '记忆引用'}</DialogTitle>
          <DialogDescription>
            {referenceKindLabel(current.kind)} · {current.referenceId}
          </DialogDescription>
        </DialogHeader>

        {query.isPending ? (
          <p className="memory-layer-loading"><LoaderCircle size={15} />正在读取引用详情</p>
        ) : null}
        {query.error ? (
          <InlineNotice title="引用暂时无法读取" tone="danger">
            {publicErrorText(query.error, '引用可能已归档，或当前服务尚未完成投影。')}
          </InlineNotice>
        ) : null}

        {!query.isPending && !query.error ? (
          <div className="memory-reference-view" data-reference-key={currentKey}>
            <div className="memory-reference-view__identity">
              <span><Fingerprint size={16} /></span>
              <div><small>稳定引用</small><strong>{current.referenceId}</strong></div>
              <StatusBadge
                label={referenceStatusLabel(disposition, current.kind)}
                tone={referenceStatusTone(disposition, current.kind)}
              />
            </div>

            {redacted ? (
              <InlineNotice title="内容已脱敏" tone="warning">
                <span className="memory-reference-view__notice"><EyeOff size={14} />正文不会在控制中心显示；稳定引用、来源类别和治理状态仍保留用于审计。</span>
              </InlineNotice>
            ) : null}
            {!redacted && forgotten ? (
              <InlineNotice title="这条来源已退出记忆召回" tone="info">
                遗忘态不会破坏证据链。它不再参与整理或召回，但仍保留最小审计信息，避免下游事实变成无来源记录。
              </InlineNotice>
            ) : null}
            {content ? <p className="memory-reference-view__content">{content}</p> : null}

            <dl className="memory-reference-view__facts">
              <ReferenceFact label="引用类型" value={referenceKindLabel(current.kind)} />
              <ReferenceFact label="来源类别" value={stringValue(source.type, stringValue(source.kind, stringValue(source.sourceKind, stringValue(item.sourceType, '未标注'))))} />
              <ReferenceFact label="来源对象" value={stringValue(source.id, stringValue(source.sourceId, stringValue(canonicalRef.sourceId, '未标注')))} />
              <ReferenceFact label="归属" value={referenceOwner(item)} />
              <ReferenceFact label="时间" value={referenceTime(item)} />
              <ReferenceFact label="下级引用" value={`${references.length} 条`} />
            </dl>

            <section className="memory-reference-view__children" aria-label="来源证据与引用">
              <header><span><GitBranch size={15} /><strong>来源证据与引用</strong></span><small>{references.length} 条</small></header>
              {references.length ? references.map((reference) => {
                const childKey = referenceKey(reference);
                const loop = visited.has(childKey);
                const depthLimited = stack.length >= maximumReferenceDepth;
                return (
                  <button
                    disabled={loop || depthLimited}
                    key={childKey}
                    onClick={() => openReference(reference)}
                    type="button"
                  >
                    <span><small>{referenceKindLabel(reference.kind)}</small><strong>{reference.label || reference.referenceId}</strong><em>{reference.referenceId}</em></span>
                    {loop ? <b>已在路径中</b> : depthLimited ? <b>已到最深层</b> : <ChevronRight size={15} />}
                  </button>
                );
              }) : (
                <p>这是当前证据链的叶子节点，没有更深一层引用。</p>
              )}
            </section>

            {stack.length >= maximumReferenceDepth ? (
              <p className="memory-reference-view__guard"><ShieldAlert size={14} />已达到 {maximumReferenceDepth} 层查看上限，避免异常引用链无限展开。</p>
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          {stack.length > 1 ? (
            <Button leadingIcon={<ArrowLeft size={14} />} onClick={() => setStack((items) => items.slice(0, -1))} variant="quiet">
              返回上一层
            </Button>
          ) : null}
          <Button onClick={() => onOpenChange(false)}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReferenceFact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value || '未标注'}</dd></div>;
}

function parseEvidenceReferences(value: unknown, fallbackKind: MemoryReferenceKind): MemoryReferenceSelection[] {
  if (!Array.isArray(value)) return [];
  const references: MemoryReferenceSelection[] = [];
  const seen = new Set<string>();
  for (const raw of value) {
    const item = asRecord(raw);
    const rawId = typeof raw === 'string'
      ? raw
      : stringValue(item.referenceId, stringValue(item.refId, stringValue(item.id, stringValue(item.sourceId))));
    const rawKind = typeof raw === 'string'
      ? inferReferenceKind(raw, fallbackKind)
      : normalizeReferenceKind(
        stringValue(
          item.kind,
          stringValue(item.referenceKind, stringValue(item.sourceKind, stringValue(item.sourceType))),
        ),
        rawId,
        fallbackKind,
      );
    if (!rawId || !rawKind) continue;
    const reference = {
      kind: rawKind,
      referenceId: rawId,
      label: typeof raw === 'string' ? '' : stringValue(item.label, stringValue(item.title, stringValue(item.textPreview))),
    };
    const key = referenceKey(reference);
    if (seen.has(key)) continue;
    seen.add(key);
    references.push(reference);
  }
  return references.slice(0, 80);
}

function mergeEvidenceReferences(
  values: unknown[],
  fallbackKind: MemoryReferenceKind,
): MemoryReferenceSelection[] {
  const seen = new Set<string>();
  return values.flatMap((value) => parseEvidenceReferences(value, fallbackKind)).filter((reference) => {
    const key = referenceKey(reference);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 80);
}

function referenceIsRedacted(
  payload: Record<string, unknown>,
  item: Record<string, unknown>,
  source: Record<string, unknown>,
): boolean {
  const privacy = stringValue(
    item.privacyDisposition,
    stringValue(item.privacyLevel, stringValue(source.privacyDisposition, stringValue(payload.privacyDisposition))),
  ).toLocaleLowerCase('en-US');
  return payload.redacted === true
    || item.redacted === true
    || item.sensitive === true
    || source.redacted === true
    || source.sensitive === true
    || ['sensitive', 'secret', 'credential', 'redacted'].includes(privacy);
}

function normalizeReferenceKind(
  value: string,
  referenceId: string,
  fallback: MemoryReferenceKind,
): MemoryReferenceKind {
  const normalized = value.trim().toLocaleLowerCase('en-US').replaceAll('-', '_');
  const aliases: Record<string, MemoryReferenceKind> = {
    input_event: 'event',
    event: 'event',
    agent_evidence: 'evidence',
    memory_evidence: 'evidence',
    evidence: 'evidence',
    memory_atom: 'atom',
    atom: 'atom',
    memory_book: 'book',
    book: 'book',
    activity_timeline: 'timeline',
    timeline: 'timeline',
    role_book: 'role_book_revision',
    role_book_revision: 'role_book_revision',
  };
  return aliases[normalized] ?? inferReferenceKind(referenceId, fallback);
}

function inferReferenceKind(referenceId: string, fallback: MemoryReferenceKind): MemoryReferenceKind {
  const normalized = referenceId.toLocaleLowerCase('en-US');
  if (/^\d+$/u.test(normalized) || normalized.startsWith('event:') || normalized.startsWith('input-memory:')) return 'event';
  if (normalized.startsWith('evidence:') || normalized.startsWith('agent-memory:')) return 'evidence';
  if (normalized.startsWith('atom:')) return 'atom';
  if (normalized.startsWith('book:')) return 'book';
  if (normalized.startsWith('timeline:')) return 'timeline';
  if (normalized.startsWith('revision:') || normalized.startsWith('role-book:')) return 'role_book_revision';
  return fallback;
}

function referenceTitle(item: Record<string, unknown>, selection: MemoryReferenceSelection): string {
  return stringValue(
    item.title,
    stringValue(item.displayName, stringValue(item.textPreview, stringValue(item.text, selection.label || selection.referenceId))),
  );
}

function referenceContent(item: Record<string, unknown>): string {
  return stringValue(
    item.detail,
    stringValue(item.summary, stringValue(item.text, stringValue(item.committedText, stringValue(item.note)))),
  );
}

function referenceOwner(item: Record<string, unknown>): string {
  const ownerKind = stringValue(item.ownerKind, stringValue(item.owner_kind));
  const ownerId = stringValue(item.ownerId, stringValue(item.owner_id));
  return ownerKind && ownerId ? `${ownerKind} · ${ownerId}` : '未标注';
}

function referenceTime(item: Record<string, unknown>): string {
  const value = numberValue(item.updatedAtMs, numberValue(item.occurredAtMs, numberValue(item.createdAtMs)));
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(value) : '未标注';
}

function referenceKindLabel(kind: MemoryReferenceKind): string {
  return ({
    event: '原始事件',
    evidence: '对话证据与审计',
    atom: '关于我的事实',
    book: '长期主题',
    timeline: '活动时间线',
    role_book_revision: '伙伴记忆版本',
  } as const)[kind];
}

function referenceStatusLabel(status: string, kind: MemoryReferenceKind): string {
  if (kind === 'evidence' && status === 'active') return '审计保留';
  return ({
    active: '使用中',
    approved: '已确认',
    archived: '已归档',
    superseded: '历史版本',
    tombstoned: '已移除',
    not_for_memory: '已遗忘',
    forgotten: '已遗忘',
    expired: '已过期',
  } as Record<string, string>)[status] ?? '可追溯';
}

function referenceStatusTone(status: string, kind: MemoryReferenceKind): 'success' | 'info' | 'danger' | 'neutral' {
  if (kind === 'evidence' && status === 'active') return 'info';
  if (status === 'active' || status === 'approved') return 'success';
  if (status === 'archived' || status === 'superseded' || status === 'not_for_memory' || status === 'forgotten' || status === 'expired') return 'info';
  if (status === 'tombstoned') return 'danger';
  return 'neutral';
}

function referenceKey(value: MemoryReferenceSelection): string {
  return `${value.kind}\u0000${value.referenceId}`;
}
