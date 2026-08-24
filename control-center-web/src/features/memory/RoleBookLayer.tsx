import {
  BookUser,
  ChevronRight,
  FileClock,
  Fingerprint,
  LoaderCircle,
  ShieldCheck,
} from 'lucide-react';
import {
  Fragment,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { Button } from '@/components/primitives';
import { roleItems } from '@/features/agent/types';
import {
  InlineNotice,
  OperationalList,
  StatusBadge,
  arrayRecords,
  asRecord,
  numberValue,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import { useRoleBookLayerQueries } from './api';
import {
  MemoryReferenceDialog,
  type MemoryReferenceSelection,
} from './MemoryReferenceDialog';

interface RoleBookLayerProps {
  enabled: boolean;
  initialReferenceId?: string;
  onOpenGovernance: () => void;
}

const sectionOrder = [
  ['personality', '协作特征'],
  ['capabilities', '能力画像'],
  ['recentWork', '近期工作'],
  ['lessonsAndLimits', '经验与边界'],
  ['activeCommitments', '当前承诺'],
] as const;

export function RoleBookLayer({
  enabled,
  initialReferenceId = '',
  onOpenGovernance,
}: RoleBookLayerProps) {
  const [roleKey, setRoleKey] = useState('');
  const selectedScope = parseRoleKey(roleKey);
  const { roleBook, roles: rolesQuery } = useRoleBookLayerQueries(
    selectedScope.roleId,
    selectedScope.roleVersion,
    enabled,
  );
  const roles = roleItems(rolesQuery.data);

  useEffect(() => {
    if (!enabled || !roles.length) return;
    if (roles.some((role) => roleKey === encodeRoleKey(role.roleId, role.version))) return;
    const linkedRole = roles.find((role) => (
      initialReferenceId === role.roleId
      || initialReferenceId === `${role.roleId}@${role.version}`
    ));
    const next = linkedRole ?? roles[0]!;
    setRoleKey(encodeRoleKey(next.roleId, next.version));
  }, [enabled, initialReferenceId, roleKey, roles]);

  const selectedRole = roles.find((role) => (
    role.roleId === selectedScope.roleId && role.version === selectedScope.roleVersion
  ));

  return (
    <div className="memory-role-book-layer">
      <div className="memory-layer-heading">
        <div>
          <span>长期工作经历</span>
          <h3>伙伴记忆</h3>
          <p>每位伙伴分别保留有来源的工作经历、能力边界和当前承诺。</p>
        </div>
        <Button leadingIcon={<FileClock size={14} />} onClick={onOpenGovernance} size="small" variant="quiet">
          查看待确认内容
        </Button>
      </div>

      {rolesQuery.isPending ? (
        <p className="memory-layer-loading"><LoaderCircle size={15} />正在读取伙伴目录</p>
      ) : null}
      {rolesQuery.error ? (
        <InlineNotice title="伙伴目录暂时无法读取" tone="danger">
          {publicErrorText(rolesQuery.error, '请刷新后重试。')}
        </InlineNotice>
      ) : null}
      {!rolesQuery.isPending && !rolesQuery.error && !roles.length ? (
        <InlineNotice title="还没有伙伴记忆" tone="info">先创建一位伙伴，系统才会为她建立独立的长期工作经历。</InlineNotice>
      ) : null}

      {roles.length ? (
        <div className="memory-layer-workspace memory-role-book-workspace">
          <div className="memory-layer-list" aria-label="伙伴记忆目录">
            <OperationalList items={roles.map((role) => ({
              id: encodeRoleKey(role.roleId, role.version),
              title: role.displayName,
              detail: role.summary,
              meta: `设定版本 ${role.version}`,
              status: <StatusBadge label="独立记忆" tone="info" />,
              onClick: () => setRoleKey(encodeRoleKey(role.roleId, role.version)),
              selected: role.roleId === selectedScope.roleId && role.version === selectedScope.roleVersion,
            }))} />
          </div>
          <div className="memory-layer-detail">
            {selectedRole ? (
              <RoleBookDetail
                catalog={asRecord(roleBook.data)}
                error={roleBook.error}
                initialReferenceId={initialReferenceId}
                isPending={roleBook.isPending}
                roleName={selectedRole.displayName}
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function RoleBookDetail({
  catalog,
  error,
  initialReferenceId,
  isPending,
  roleName,
}: {
  catalog: Record<string, unknown>;
  error: Error | null;
  initialReferenceId: string;
  isPending: boolean;
  roleName: string;
}) {
  const active = asRecord(catalog.active);
  const revisions = useMemo(() => uniqueRevisions(active, arrayRecords(catalog.history)), [active, catalog.history]);
  const [revisionId, setRevisionId] = useState('');
  const [itemKey, setItemKey] = useState('');
  const [reference, setReference] = useState<MemoryReferenceSelection | null>(null);
  const revision = revisions.find((item) => stringValue(item.revisionId) === revisionId)
    ?? revisions[0]
    ?? {};
  const sections = asRecord(revision.sections);
  const items = roleBookSectionItems(sections);
  const draftCount = arrayRecords(catalog.dailyDrafts).filter((draft) => {
    const decision = asRecord(draft.decision);
    return !stringValue(decision.decision);
  }).length;

  useEffect(() => {
    const availableIds = revisions.map((item) => stringValue(item.revisionId)).filter(Boolean);
    setRevisionId((current) => {
      if (initialReferenceId && availableIds.includes(initialReferenceId)) return initialReferenceId;
      return availableIds.includes(current) ? current : availableIds[0] ?? '';
    });
  }, [initialReferenceId, revisions]);

  useEffect(() => {
    setItemKey('');
    setReference(null);
  }, [revisionId]);

  if (isPending) return <p className="memory-layer-loading"><LoaderCircle size={15} />正在读取 {roleName} 的伙伴记忆</p>;
  if (error) {
    return (
      <InlineNotice title="伙伴记忆暂时无法读取" tone="danger">
        {publicErrorText(error, '这位伙伴可能还没有形成长期工作经历。')}
      </InlineNotice>
    );
  }
  if (!Object.keys(active).length) {
    return <InlineNotice title="还没有可用版本" tone="info">这位伙伴还没有可展示的长期工作经历。</InlineNotice>;
  }

  return (
    <section className="memory-role-book-detail" aria-label={`${roleName} 伙伴记忆详情`}>
      <header>
        <span><BookUser size={17} /></span>
        <div>
          <small>当前伙伴记忆</small>
          <h3>{stringValue(revision.displayName, roleName)}</h3>
          <p>{stringValue(revision.mission, '用于让伙伴在不同对话中保持连贯。')}</p>
        </div>
        <StatusBadge
          label={stringValue(revision.status) === 'active' ? '已启用' : '历史版本'}
          tone={stringValue(revision.status) === 'active' ? 'success' : 'info'}
        />
        <Button
          leadingIcon={<Fingerprint size={14} />}
          onClick={() => setReference({
            kind: 'role_book_revision',
            referenceId: stringValue(revision.revisionId),
            label: stringValue(revision.displayName, roleName),
          })}
          size="small"
          variant="quiet"
        >
          查看修订来源
        </Button>
      </header>

      <div className="memory-role-book-revisions" aria-label="伙伴记忆版本">
        {revisions.map((item) => {
          const id = stringValue(item.revisionId);
          return (
            <button aria-current={id === stringValue(revision.revisionId)} key={id} onClick={() => setRevisionId(id)} type="button">
              <strong>第 {numberValue(item.revisionNumber)} 版</strong>
              <small>{stringValue(item.status) === 'active' ? '当前' : formatDate(numberValue(item.createdAtMs))}</small>
            </button>
          );
        })}
      </div>

      <div className="memory-role-book-sections">
        {sectionOrder.map(([section, label]) => {
          const sectionItems = items.filter((item) => item.section === section);
          return (
            <section key={section}>
              <header><strong>{label}</strong><small>{sectionItems.length} 项</small></header>
              {sectionItems.length ? sectionItems.map((item) => {
                const open = item.key === itemKey;
                const disclosureId = roleBookItemDisclosureId(stringValue(revision.revisionId), item.key);
                return (
                  <Fragment key={item.key}>
                    <button
                      aria-controls={disclosureId}
                      aria-expanded={open}
                      onClick={() => {
                        setItemKey((current) => current === item.key ? '' : item.key);
                        setReference(null);
                      }}
                      type="button"
                    >
                      <span>{stringValue(item.value.text, '未命名条目')}</span>
                      <ChevronRight aria-hidden="true" size={14} />
                    </button>
                    <RoleBookItemDisclosure id={disclosureId} open={open}>
                      <RoleBookItemDetail
                        item={item.value}
                        label={item.label}
                        onOpenReference={(evidenceId) => setReference({
                          kind: /^\d+$/u.test(evidenceId) || evidenceId.startsWith('event:') || evidenceId.startsWith('input-memory:')
                            ? 'event'
                            : 'evidence',
                          referenceId: evidenceId,
                          label: stringValue(item.value.text),
                        })}
                      />
                    </RoleBookItemDisclosure>
                  </Fragment>
                );
              }) : <p>当前版本没有这一类记录。</p>}
            </section>
          );
        })}
      </div>

      <footer>
        <span><ShieldCheck size={14} />伙伴记忆只描述经历与边界，不能扩大工具权限或安全范围。</span>
        <small>{draftCount ? `${draftCount} 份每日整理等待确认` : '没有待确认的每日整理'}</small>
      </footer>
      {reference ? (
        <MemoryReferenceDialog
          {...reference}
          onOpenChange={(open) => { if (!open) setReference(null); }}
        />
      ) : null}
    </section>
  );
}

function RoleBookItemDetail({
  item,
  label,
  onOpenReference,
}: {
  item: Record<string, unknown>;
  label: string;
  onOpenReference: (evidenceId: string) => void;
}) {
  const provenance = asRecord(item.provenance);
  const evidenceIds = stringList(item.evidenceIds);
  return (
    <div className="memory-lineage-panel" aria-label={`${label}条目详情`}>
      <div>
        <span>{label}</span>
        <strong>{stringValue(item.text)}</strong>
        <dl>
          <div><dt>来源类型</dt><dd>{roleBookSourceTypeLabel(stringValue(provenance.sourceType))}</dd></div>
          <div><dt>来源对象</dt><dd>{stringValue(provenance.sourceId) ? '已关联' : '未标注'}</dd></div>
          <div><dt>相关来源</dt><dd>{evidenceIds.length} 条</dd></div>
        </dl>
      </div>
      {evidenceIds.length ? (
        <div className="memory-reference-list" aria-label="伙伴记忆相关来源">
          {evidenceIds.map((evidenceId, index) => (
            <button key={evidenceId} onClick={() => onOpenReference(evidenceId)} type="button">
              <Fingerprint size={14} /><span>来源 {index + 1}</span><ChevronRight size={14} />
            </button>
          ))}
        </div>
      ) : <p className="memory-lineage-empty">这条记录没有可展开的来源信息。</p>}
    </div>
  );
}

function RoleBookItemDisclosure({
  children,
  id,
  open,
}: {
  children: ReactNode;
  id: string;
  open: boolean;
}) {
  return (
    <div
      aria-hidden={!open}
      className="memory-role-book-item-disclosure"
      data-open={open ? 'true' : 'false'}
      id={id}
      inert={open ? undefined : true}
    >
      <div>
        <div className="memory-role-book-item-disclosure__content">{children}</div>
      </div>
    </div>
  );
}

function roleBookItemDisclosureId(revisionId: string, itemKey: string): string {
  return `memory-role-book-item-${revisionId}-${itemKey}`.replace(/[^a-zA-Z0-9_-]+/gu, '-');
}

function uniqueRevisions(
  active: Record<string, unknown>,
  history: Record<string, unknown>[],
): Record<string, unknown>[] {
  const values = [active, ...history];
  const seen = new Set<string>();
  return values.filter((item) => {
    const id = stringValue(item.revisionId);
    if (!id || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

function roleBookSourceTypeLabel(value: string): string {
  return ({
    daily_session_summary: '对话总结',
    session_summary: '对话总结',
    agent_memory: '伙伴记录',
    user_input: '用户输入',
  } as Record<string, string>)[value] ?? (value ? '已记录来源' : '未标注');
}

function roleBookSectionItems(sections: Record<string, unknown>) {
  return sectionOrder.flatMap(([section, label]) => arrayRecords(sections[section]).map((value, index) => ({
    key: `${section}:${stringValue(value.itemId, String(index))}`,
    label,
    section,
    value,
  })));
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.flatMap((item) => typeof item === 'string' && item.trim() ? [item.trim()] : [])
    : [];
}

function encodeRoleKey(roleId: string, roleVersion: string): string {
  return JSON.stringify([roleId, roleVersion]);
}

function parseRoleKey(value: string): { roleId: string; roleVersion: string } {
  try {
    const parsed: unknown = JSON.parse(value);
    if (Array.isArray(parsed) && typeof parsed[0] === 'string' && typeof parsed[1] === 'string') {
      return { roleId: parsed[0], roleVersion: parsed[1] };
    }
  } catch {
    // Empty selection is expected before the role catalog arrives.
  }
  return { roleId: '', roleVersion: '' };
}

function formatDate(value: number): string {
  return value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(value) : '历史';
}
