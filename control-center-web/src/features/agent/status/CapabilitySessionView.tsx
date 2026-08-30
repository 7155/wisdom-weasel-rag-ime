import { RefreshCw, Search, Settings2, ShieldCheck, TriangleAlert } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Disclosure,
  Field,
  Input,
  Select,
} from '@/components/primitives';
import {
  capabilityEffectiveLabel,
  capabilityKindLabel,
  capabilityPreferenceOptions,
  capabilityRiskLabel,
  capabilityScopeLabel,
  capabilityStatusLabel,
  preferenceLabel,
  type CapabilityCatalog,
  type CapabilityCatalogItem,
  type CapabilityMutationOutcome,
  type CapabilityPreference,
} from '@/features/plugins/capability-policy';

export function CapabilitySessionView({
  busy,
  catalog,
  error,
  mutation,
  status,
  onPreferenceChange,
  onRetryCatalog,
  onRetryMutation,
}: {
  busy: boolean;
  catalog?: CapabilityCatalog;
  error?: string;
  mutation?: CapabilityMutationOutcome;
  status: 'loading' | 'ready' | 'failed';
  onPreferenceChange: (canonicalId: string, preference: CapabilityPreference) => void;
  onRetryCatalog: () => void;
  onRetryMutation: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const items = catalog?.items ?? [];
  const disclosedCount = items.filter((item) => item.disclosure.effective === 'enabled').length;
  const overrideCount = items.filter((item) => item.disclosure.preference !== 'inherit').length;
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredItems = useMemo(() => (
    normalizedQuery
      ? items.filter((item) => [
        item.displayName,
        item.description,
        item.source.label,
        capabilityKindLabel(item.kind),
        capabilityStatusLabel(item.status),
      ].some((value) => value.toLocaleLowerCase().includes(normalizedQuery)))
      : items
  ), [items, normalizedQuery]);

  if (status === 'loading') {
    return <p className="agent-capability-session__empty" role="status">正在读取当前对话的能力设置…</p>;
  }
  if (status === 'failed' || !catalog?.sessionPolicy) {
    return (
      <div className="agent-capability-session__empty" role="alert">
        <TriangleAlert aria-hidden="true" size={15} />
        <span>{error || '暂时无法读取当前对话的能力设置。'}</span>
        <Button leadingIcon={<RefreshCw size={14} />} onClick={onRetryCatalog} size="small" variant="quiet">
          重试
        </Button>
      </div>
    );
  }

  const policy = catalog.sessionPolicy;
  const mutationLabel = mutation
    ? mutation.status === 'pending'
      ? '正在保存当前对话临时设置'
      : mutation.status === 'succeeded'
        ? '当前对话临时设置已保存'
        : '当前对话临时设置保存失败'
    : '';

  return (
    <div className="agent-capability-session">
      <div className="agent-capability-session__summary">
        <div>
          <strong>当前对话会提供 {disclosedCount} 项能力</strong>
          <small>
            共 {items.length} 项{overrideCount ? ` · ${overrideCount} 项当前对话临时设置` : ' · 全部继承默认'}
          </small>
        </div>
        <span className="agent-capability-session__summary-status" aria-live="polite">
          {mutationLabel || (busy ? '当前响应进行中' : '可调整下一轮')}
        </span>
      </div>

      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          if (!nextOpen) setQuery('');
        }}
      >
        <DialogTrigger asChild>
          <Button
            aria-haspopup="dialog"
            className="agent-capability-session__manage"
            size="small"
            variant="secondary"
          >
            管理当前对话的工具与技能
          </Button>
        </DialogTrigger>
        <DialogContent
          aria-modal="true"
          className="agent-capability-dialog"
          onEscapeKeyDown={(event) => event.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle>管理当前对话的工具与技能</DialogTitle>
            <DialogDescription>
              这里只调整伙伴下一轮会看到哪些能力；披露能力不代表已获得执行授权。
            </DialogDescription>
          </DialogHeader>

          <div className="agent-capability-dialog__owner">
            <ShieldCheck aria-hidden="true" size={16} />
            <p>
              <strong>只影响当前对话</strong>
              <span>当前对话临时设置在下一次打开或下一轮对话时生效，不会停止正在运行的任务。</span>
            </p>
            <Link to={`/plugins?sessionId=${encodeURIComponent(policy.sessionId)}`}>
              <Settings2 aria-hidden="true" size={14} />
              管理所有对话与当前项目默认
            </Link>
          </div>

          {busy ? (
            <p className="agent-capability-dialog__notice" role="status">
              当前响应仍在进行，暂不能调整。正在运行的任务保持可见，也仍可单独停止。
            </p>
          ) : null}

          {mutation ? (
            <div
              className="agent-capability-session__mutation"
              data-status={mutation.status}
              role={mutation.status === 'failed' ? 'alert' : 'status'}
            >
              <span>{mutation.message}</span>
              {mutation.status === 'failed' ? (
                <Button onClick={onRetryMutation} size="small" variant="quiet">重试这项调整</Button>
              ) : null}
            </div>
          ) : null}

          <Field className="agent-capability-dialog__search" htmlFor="agent-capability-search" label="搜索工具、技能或扩展">
            <span className="agent-capability-dialog__search-control">
              <Search aria-hidden="true" size={15} />
              <Input
                id="agent-capability-search"
                aria-label="搜索工具、技能或扩展"
                autoComplete="off"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="按名称、说明、来源或状态搜索"
                type="search"
                value={query}
              />
            </span>
          </Field>

          <div className="agent-capability-dialog__results" aria-live="polite">
            <p className="agent-capability-dialog__result-count">
              {normalizedQuery ? `找到 ${filteredItems.length} 项` : `${items.length} 项能力`}
            </p>
            {filteredItems.length ? (
              <div className="agent-capability-dialog__list">
                {filteredItems.map((item) => (
                  <CapabilityRow
                    busy={busy}
                    item={item}
                    key={item.canonicalId}
                    onPreferenceChange={onPreferenceChange}
                    pending={mutation?.status === 'pending' && mutation.canonicalId === item.canonicalId}
                    policy={policy.disclosurePreferences}
                  />
                ))}
              </div>
            ) : (
              <div className="agent-capability-dialog__no-results">
                <Search aria-hidden="true" size={18} />
                <strong>没有匹配的能力</strong>
                <span>试试搜索名称、来源，或“工具”“技能”“扩展”。</span>
                <Button onClick={() => setQuery('')} size="small" variant="quiet">清除搜索</Button>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CapabilityRow({
  busy,
  item,
  onPreferenceChange,
  pending,
  policy,
}: {
  busy: boolean;
  item: CapabilityCatalogItem;
  onPreferenceChange: (canonicalId: string, preference: CapabilityPreference) => void;
  pending: boolean;
  policy: NonNullable<CapabilityCatalog['sessionPolicy']>['disclosurePreferences'];
}) {
  const preference = policy.session[item.canonicalId] ?? item.disclosure.preference;
  const projectPreference = policy.projectDefault[item.canonicalId] ?? 'inherit';
  const globalPreference = policy.globalDefault[item.canonicalId] ?? 'inherit';
  const fixed = item.alwaysAvailable === true;

  return (
    <article className="agent-capability-session__row">
      <div className="agent-capability-session__identity">
        <div className="agent-capability-session__badges">
          <span>{capabilityKindLabel(item.kind)}</span>
          <span>{capabilityStatusLabel(item.status)}</span>
          <span>{capabilityRiskLabel(item.risk)}</span>
        </div>
        <strong>{item.displayName}</strong>
        <p>{item.description || '后端目录暂未提供说明。'}</p>
      </div>

      {fixed ? (
        <div className="agent-capability-session__fixed">
          <strong>固定加载</strong>
          <small>基础能力，不可关闭</small>
        </div>
      ) : (
        <Select
          aria-label={`${item.displayName}的当前对话临时设置`}
          disabled={busy || pending}
          onValueChange={(value) => onPreferenceChange(item.canonicalId, value)}
          options={capabilityPreferenceOptions}
          value={preference}
        />
      )}

      <div className="agent-capability-session__effective">
        <strong>{capabilityEffectiveLabel(item.disclosure.effective)}</strong>
        <small>{capabilityScopeLabel(item.effectiveScope)}</small>
      </div>

      <Disclosure className="agent-capability-session__details" contentClassName="agent-capability-session__details-content" summary="查看来源、权限和生效依据">
        <dl>
          <div><dt>来源</dt><dd>{item.source.label}</dd></div>
          <div><dt>当前状态</dt><dd>{capabilityStatusLabel(item.status)}</dd></div>
          <div><dt>执行授权</dt><dd>{authorizationLabel(item)}</dd></div>
          <div>
            <dt>所需权限</dt>
            <dd>{item.requiredPermissions.length ? item.requiredPermissions.map(permissionLabel).join('、') : '无需额外权限'}</dd>
          </div>
          {fixed ? (
            <div><dt>加载策略</dt><dd>普通伙伴会话固定加载，不参与披露开关</dd></div>
          ) : (
            <>
              <div><dt>当前对话临时设置</dt><dd>{preferenceLabel(preference)}</dd></div>
              <div><dt>项目默认</dt><dd>{preferenceLabel(projectPreference)}</dd></div>
              <div><dt>所有对话默认</dt><dd>{preferenceLabel(globalPreference)}</dd></div>
            </>
          )}
          <div><dt>生效来源</dt><dd>{capabilityScopeLabel(item.effectiveScope)}</dd></div>
        </dl>
        <p className="agent-capability-session__reason">
          <span>{capabilityReasonLabel(item.disclosure.reason)}。{capabilityReasonLabel(item.authorization.reason)}。</span>
          <small>后端依据代码：<code>{item.disclosure.reason}</code> · <code>{item.authorization.reason}</code></small>
        </p>
      </Disclosure>
    </article>
  );
}

function authorizationLabel(item: CapabilityCatalogItem): string {
  if (item.authorization.state === 'authorized') return '已由现有策略授权';
  if (item.authorization.state === 'denied') return '当前未获执行授权';
  return '当前对话不适用';
}

function permissionLabel(permission: string): string {
  const labels: Record<string, string> = {
    native_approval: '需要逐项确认',
    room_skill_load_receipt: '需要 Room 加载回执',
    workspace_read: '读取已授权工作区',
    workspace_write: '写入已授权工作区',
    network: '访问网络',
  };
  return labels[permission] ?? '由后端策略核对';
}

function capabilityReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    session_preference: '由当前对话临时设置决定',
    inherited_project_default: '继承当前项目默认',
    inherited_global_default: '继承所有对话默认',
    inherited_built_in_default: '继承产品内置默认',
    required_session_tool: '普通伙伴会话固定加载此基础能力',
    existing_session_policy_authorizes_tool: '当前对话的既有工具权限允许执行',
    existing_session_policy_does_not_authorize_tool: '当前对话的既有工具权限不允许执行',
    session_context_required: '进入具体对话后才能核对执行权限',
    room_context_required: '只有真实 Room participant 身份存在时才能使用',
    room_skill_load_receipt_required: '需要 Room 的终端加载回执才能使用',
    installed_extension_enabled: '扩展已安装并启用',
    extension_not_installed_or_enabled: '扩展尚未安装或启用',
    capability_removed_or_unavailable: '能力已移除或暂不可用',
  };
  return labels[reason] ?? '具体依据由后端策略核对';
}
