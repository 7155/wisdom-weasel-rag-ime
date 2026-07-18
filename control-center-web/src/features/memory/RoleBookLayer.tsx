import {
  BookUser,
  ChevronRight,
  FileClock,
  Fingerprint,
  LoaderCircle,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
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
          <span>Role continuity</span>
          <h3>角色书</h3>
          <p>每个角色独立维护经证据支持的工作经历、能力边界和当前承诺。</p>
        </div>
        <Button leadingIcon={<FileClock size={14} />} onClick={onOpenGovernance} size="small" variant="quiet">
          查看治理草案
        </Button>
      </div>

      {rolesQuery.isPending ? (
        <p className="memory-layer-loading"><LoaderCircle size={15} />正在读取角色目录</p>
      ) : null}
      {rolesQuery.error ? (
        <InlineNotice title="角色目录暂时无法读取" tone="danger">
          {publicErrorText(rolesQuery.error, '请刷新后重试。')}
        </InlineNotice>
      ) : null}
      {!rolesQuery.isPending && !rolesQuery.error && !roles.length ? (
        <InlineNotice title="还没有角色书" tone="info">先创建一个角色，系统才会建立独立的角色记忆边界。</InlineNotice>
      ) : null}

      {roles.length ? (
        <div className="memory-layer-workspace memory-role-book-workspace">
          <div className="memory-layer-list" aria-label="角色书目录">
            <OperationalList items={roles.map((role) => ({
              id: encodeRoleKey(role.roleId, role.version),
              title: role.displayName,
              detail: role.summary,
              meta: `角色版本 ${role.version}`,
              status: <StatusBadge label="独立角色书" tone="info" />,
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
  const selectedItem = items.find((item) => item.key === itemKey);
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

  if (isPending) return <p className="memory-layer-loading"><LoaderCircle size={15} />正在读取 {roleName} 的角色书</p>;
  if (error) {
    return (
      <InlineNotice title="角色书暂时无法读取" tone="danger">
        {publicErrorText(error, '当前角色可能还没有建立角色书。')}
      </InlineNotice>
    );
  }
  if (!Object.keys(active).length) {
    return <InlineNotice title="没有启用版本" tone="info">当前角色还没有可展示的角色书修订。</InlineNotice>;
  }

  return (
    <section className="memory-role-book-detail" aria-label={`${roleName} 角色书详情`}>
      <header>
        <span><BookUser size={17} /></span>
        <div>
          <small>当前角色书</small>
          <h3>{stringValue(revision.displayName, roleName)}</h3>
          <p>{stringValue(revision.mission, '用于保持角色在不同会话中的连续性。')}</p>
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

      <div className="memory-role-book-revisions" aria-label="角色书版本记录">
        {revisions.map((item) => {
          const id = stringValue(item.revisionId);
          return (
            <button aria-current={id === stringValue(revision.revisionId)} key={id} onClick={() => setRevisionId(id)} type="button">
              <strong>Revision {numberValue(item.revisionNumber)}</strong>
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
              {sectionItems.length ? sectionItems.map((item) => (
                <button
                  aria-current={item.key === itemKey}
                  key={item.key}
                  onClick={() => { setItemKey(item.key); setReference(null); }}
                  type="button"
                >
                  <span>{stringValue(item.value.text, '未命名条目')}</span>
                  <ChevronRight aria-hidden="true" size={14} />
                </button>
              )) : <p>当前版本没有这一类记录。</p>}
            </section>
          );
        })}
      </div>

      {selectedItem ? (
        <RoleBookItemDetail
          item={selectedItem.value}
          label={selectedItem.label}
          onOpenReference={(evidenceId) => setReference({
            kind: /^\d+$/u.test(evidenceId) || evidenceId.startsWith('event:') || evidenceId.startsWith('input-memory:')
              ? 'event'
              : 'evidence',
            referenceId: evidenceId,
            label: stringValue(selectedItem.value.text),
          })}
        />
      ) : (
        <p className="memory-lineage-empty">选择一条角色记忆，查看它的来源和证据引用。</p>
      )}

      <footer>
        <span><ShieldCheck size={14} />角色书只能描述角色，不能改变工具权限或安全策略。</span>
        <small>{draftCount ? `${draftCount} 份每日草案等待治理` : '没有待处理的每日草案'}</small>
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
          <div><dt>来源类型</dt><dd>{stringValue(provenance.sourceType, '未标注')}</dd></div>
          <div><dt>来源对象</dt><dd>{stringValue(provenance.sourceId, '未标注')}</dd></div>
          <div><dt>证据引用</dt><dd>{evidenceIds.length} 条</dd></div>
        </dl>
      </div>
      {evidenceIds.length ? (
        <div className="memory-reference-list" aria-label="角色书证据引用">
          {evidenceIds.map((evidenceId) => (
            <button key={evidenceId} onClick={() => onOpenReference(evidenceId)} type="button">
              <Fingerprint size={14} /><span>{evidenceId}</span><ChevronRight size={14} />
            </button>
          ))}
        </div>
      ) : <p className="memory-lineage-empty">这条记录没有可展开的证据标识。</p>}
    </div>
  );
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
