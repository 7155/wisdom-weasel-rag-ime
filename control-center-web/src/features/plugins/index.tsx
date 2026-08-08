import {
  Boxes,
  CheckCircle2,
  ChevronRight,
  Clock3,
  History,
  MessageCircle,
  PackageCheck,
  PanelRightClose,
  Power,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
  Wrench,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Button,
  EmptyState,
  Field,
  IconButton,
  Input,
  SegmentedControl,
  Select,
  Switch,
} from '@/components/primitives';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import {
  capabilityEffectiveLabel,
  capabilityKindLabel,
  capabilityPreferenceOptions,
  capabilityRiskLabel,
  capabilityScopeLabel,
  capabilityStatusLabel,
  preferenceLabel,
  projectScopeReason,
  type CapabilityCatalogItem,
  type CapabilityDefaultsSnapshot,
  type CapabilityKind,
  type CapabilityMutationOutcome,
  type CapabilityPreference,
} from './capability-policy';
import { usePluginCatalog } from './api';
import { useProductIdentity } from '@/features/identity/product-identity';
import './plugins.css';

type ToolRecord = CapabilityCatalogItem;
type KindFilter = 'all' | CapabilityKind;
type DefaultMutationOutcome = CapabilityMutationOutcome & { scope: 'global' | 'project' };
type AvailabilityFilter = 'all' | 'online' | 'attention';

const kindFilters: readonly { label: string; value: KindFilter }[] = [
  { label: '全部', value: 'all' },
  { label: '工具', value: 'tool' },
  { label: '技能', value: 'skill' },
  { label: '扩展', value: 'extension' },
];


const operationLabels: Record<string, string> = {
  abort: '停止任务', apply_settings: '应用输入设置', artifact: '查看任务产物', audit: '查看审计记录',
  cache_stats: '查看缓存状态', candidate_explain: '解释候选词', capabilities: '查看可用能力', catalog: '浏览目录',
  components: '检查运行组件', dashboard: '查看规划面板', deep_recall: '深度检索', delegate: '委派任务',
  diagnose: '运行诊断', export: '导出备份', export_preview: '预览备份', get_settings: '查看输入设置',
  health: '检查服务状态', history: '查看输入记录', lexicon_apply: '应用词库更新', lexicon_review: '审阅词库建议',
  lexicon_rollback: '撤销词库更新', list: '浏览内容', maintenance_apply: '应用记忆整理',
  curation_prepare: '生成记忆草案', maintenance_preview: '预览记忆整理', maintenance_review: '审阅记忆整理', maintenance_rollback: '撤销记忆整理',
  maintenance_status: '查看整理状态', pause_ai: '暂停智能功能', privacy_policy: '查看隐私保护', probe: '检查模型连接',
  profile: '查看输入方案', profiles: '查看模型方案', profile_apply: '应用模型方案', profile_preview: '预览模型方案',
  profile_rollback: '撤销模型方案', provider_apply: '切换语音服务', provider_preview: '预览语音切换',
  provider_rollback: '撤销语音切换', provider_status: '查看语音服务', read: '读取内容', recall: '检索知识',
  recent: '查看最近内容', recent_activity: '查看最近活动', redeploy_rime: '重新部署输入法', restart_predictor: '重启预测服务',
  restart_sidecar: '重启后台服务', restore_apply: '恢复备份', restore_preview: '预览恢复内容', resume_ai: '恢复智能功能',
  rollback_settings: '撤销输入设置', route_status: '检查检索连接', run: '运行受控命令', search: '搜索内容',
  status: '查看当前状态', task_action: '更新任务', trace: '查看来源链路', undo_task_event: '撤销任务更新',
  tabs: '查看浏览器标签页', snapshot: '读取页面快照', screenshot: '获取页面截图', navigate: '打开网页',
  click: '点击页面元素', type: '向页面输入', scroll: '滚动页面', wait: '等待页面内容', stop: '停止浏览器操作',
};

export function PluginsFeature() {
  const navigate = useNavigate();
  const identity = useProductIdentity();
  const [searchParams] = useSearchParams();
  const sessionContextId = searchParams.get('sessionId')?.trim() ?? '';
  const {
    catalog,
    defaults,
    installed,
    versions,
    proposals,
    lifecycle,
    validate,
    preview,
    apply,
    updateDefaults,
    updateProjectDefaults,
    updateLifecycle,
    refreshAll,
  } = usePluginCatalog(sessionContextId);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState<KindFilter>('all');
  const [availability, setAvailability] = useState<AvailabilityFilter>('all');
  const [selectedId, setSelectedId] = useState('');
  const [enableAfterInstall, setEnableAfterInstall] = useState(true);
  const [validation, setValidation] = useState<Record<string, unknown>>({});
  const [pendingChange, setPendingChange] = useState<Record<string, unknown>>({});
  const [lifecycleError, setLifecycleError] = useState('');
  const [defaultMutation, setDefaultMutation] = useState<DefaultMutationOutcome>();
  const [hookError, setHookError] = useState('');
  const [showMaintenance, setShowMaintenance] = useState(false);
  const items = catalog.data?.items ?? [];
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    return items.filter((item) => {
      const state = item.status.toLowerCase();
      const haystack = [
        item.displayName,
        item.description,
        item.source.label,
        capabilityKindLabel(item.kind),
        ...item.requiredPermissions,
      ].join(' ').toLocaleLowerCase('zh-CN');
      const matchesAvailability = availability === 'all'
        || (availability === 'online' ? state === 'online' || state === 'ready' || state === 'installed' : !['online', 'ready', 'installed'].includes(state));
      return (!needle || haystack.includes(needle))
        && (kind === 'all' || item.kind === kind)
        && matchesAvailability;
    });
  }, [availability, items, kind, query]);
  const selected = filtered.find((item) => itemKey(item) === selectedId);
  const installedItems = arrayRecords(asRecord(installed.data).items);
  const proposalItems = arrayRecords(asRecord(proposals.data).items);
  const versionItems = arrayRecords(asRecord(versions.data).items);
  const lifecyclePolicies = arrayRecords(asRecord(lifecycle.data).policies);
  const lifecycleEvents = arrayRecords(asRecord(lifecycle.data).recentEvents);
  const authorizedCount = items.filter((item) => item.authorization.state === 'authorized').length;
  const disclosedCount = items.filter((item) => item.disclosure.state === 'disclosed').length;
  const hiddenCount = items.filter((item) => item.disclosure.state === 'hidden').length;
  const pendingSummary = asRecord(pendingChange.summary);
  const pendingPluginId = stringValue(pendingSummary.pluginId);
  const pendingSummaryDisplayName = stringValue(pendingSummary.displayName);
  const pendingInstalledPlugin = installedItems.find(
    (plugin) => stringValue(plugin.id) === pendingPluginId,
  );
  const pendingDisplayName = pendingSummaryDisplayName
    || stringValue(pendingInstalledPlugin?.displayName, pendingPluginId);
  const pendingCanonicalEvidence = !pendingSummaryDisplayName
    && pendingDisplayName !== pendingPluginId
    ? `标识：${pendingPluginId} · `
    : '';
  const lifecyclePending = validate.isPending || preview.isPending || apply.isPending;
  const pluginQueriesPending = installed.isPending || versions.isPending || proposals.isPending;
  const pluginQueryError = firstError(installed.error, versions.error, proposals.error);
  const refreshing = catalog.isFetching || installed.isFetching || versions.isFetching
    || proposals.isFetching || lifecycle.isFetching;

  const defaultSettingsPending = updateDefaults.isPending || updateProjectDefaults.isPending;

  const updateDefaultPreference = async (
    item: CapabilityCatalogItem,
    preference: CapabilityPreference,
    snapshot: CapabilityDefaultsSnapshot | undefined = defaults.data,
  ) => {
    if (!snapshot) return;
    setDefaultMutation({
      canonicalId: item.canonicalId,
      preference,
      scope: 'global',
      status: 'pending',
      message: `正在保存 ${item.displayName} 的所有对话默认。`,
    });
    try {
      await updateDefaults.mutateAsync({
        expectedRevision: snapshot.revision,
        preferences: {
          ...snapshot.preferences,
          [item.canonicalId]: preference,
        },
      });
      setDefaultMutation({
        canonicalId: item.canonicalId,
        preference,
        scope: 'global',
        status: 'succeeded',
        message: `后台已确认保存所有对话默认：${preferenceLabel(preference)}。`,
      });
    } catch (error) {
      setDefaultMutation({
        canonicalId: item.canonicalId,
        preference,
        scope: 'global',
        status: 'failed',
        message: publicErrorText(error, '默认设置没有保存，请重新读取后重试。'),
      });
    }
  };
  const updateProjectPreference = async (
    item: CapabilityCatalogItem,
    preference: CapabilityPreference,
    snapshot: CapabilityDefaultsSnapshot | undefined = defaults.data,
  ) => {
    const projectId = catalog.data?.projectScope.projectId;
    if (!snapshot || !projectId) return;
    setDefaultMutation({
      canonicalId: item.canonicalId,
      preference,
      scope: 'project',
      status: 'pending',
      message: `正在保存 ${item.displayName} 的当前项目默认。`,
    });
    try {
      await updateProjectDefaults.mutateAsync({
        expectedRevision: snapshot.revision,
        projectPreferences: {
          ...snapshot.projectPreferences,
          [projectId]: {
            ...snapshot.projectPreferences[projectId],
            [item.canonicalId]: preference,
          },
        },
      });
      setDefaultMutation({
        canonicalId: item.canonicalId,
        preference,
        scope: 'project',
        status: 'succeeded',
        message: `后台已确认保存当前项目默认：${preferenceLabel(preference)}。`,
      });
    } catch (error) {
      setDefaultMutation({
        canonicalId: item.canonicalId,
        preference,
        scope: 'project',
        status: 'failed',
        message: publicErrorText(error, '项目默认没有保存，请重新读取后重试。'),
      });
    }
  };
  const retryDefaultMutation = async () => {
    if (!defaultMutation) return;
    const refreshed = await defaults.refetch();
    if (!refreshed.data) {
      setDefaultMutation({
        ...defaultMutation,
        status: 'failed',
        message: '无法重新读取最新配置；未重发这次更改。',
      });
      return;
    }
    const item = items.find((candidate) => candidate.canonicalId === defaultMutation.canonicalId);
    if (!item) {
      setDefaultMutation({
        ...defaultMutation,
        status: 'failed',
        message: '后端目录已不再包含这项能力；未重发旧设置。',
      });
      return;
    }
    if (defaultMutation.scope === 'global') {
      await updateDefaultPreference(item, defaultMutation.preference, refreshed.data);
      return;
    }
    await updateProjectPreference(item, defaultMutation.preference, refreshed.data);
  };
  const previewInstalledAction = async (action: 'enable' | 'disable' | 'rollback', pluginId: string) => {
    setLifecycleError('');
    try {
      setPendingChange(asRecord(await preview.mutateAsync({ action, pluginId })));
    } catch (error) {
      setLifecycleError(errorMessage(error));
    }
  };

  const previewCatalogAction = async (item: Record<string, unknown>) => {
    setLifecycleError('');
    try {
      const validationResult = asRecord(await validate.mutateAsync({
        catalogId: stringValue(item.id),
        catalogVersion: stringValue(item.latestVersion),
      }));
      setValidation(validationResult);
      setPendingChange(asRecord(await preview.mutateAsync({
        action: item.updateAvailable === true ? 'update' : 'install',
        validationToken: stringValue(validationResult.validationToken),
        enable: item.installed === true ? item.enabled === true : enableAfterInstall,
      })));
    } catch (error) {
      setLifecycleError(errorMessage(error));
    }
  };

  const applyPendingChange = async () => {
    setLifecycleError('');
    try {
      await apply.mutateAsync({
        previewToken: stringValue(pendingChange.previewToken),
        payloadSha256: stringValue(pendingChange.payloadSha256),
        confirmText: 'apply',
      });
      setPendingChange({});
      setValidation({});
    } catch (error) {
      setLifecycleError(errorMessage(error));
    }
  };

  const updateHook = async (eventType: string, enabled: boolean) => {
    setHookError('');
    try {
      await updateLifecycle.mutateAsync({ eventType, enabled });
    } catch (error) {
      setHookError(errorMessage(error));
    }
  };

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={refreshing} onClick={() => void refreshAll()} size="small">刷新</Button>}
      description="查看伙伴可使用的工具、技能和扩展，设置全局或当前项目默认，并核对这次对话的临时设置与最终结果。"
      eyebrow="能力设置"
      routeId="plugins"
      title="工具、技能与扩展"
    >
      <QueryState error={asError(catalog.error)} isPending={catalog.isPending} onRetry={() => void catalog.refetch()}>
        <ManagementSection
          description="这里的开关只决定伙伴是否能看见或加载能力；它不会授予执行权限，也不会绕过审批、工作区授权或多人协作策略。"
          title="能力目录"
        >
          <MetricStrip items={[
            { label: '目录项目', value: items.length, detail: '当前可查看', icon: Wrench },
            { label: '工具', value: items.filter((item) => item.kind === 'tool').length, icon: Wrench },
            { label: '技能', value: items.filter((item) => item.kind === 'skill').length, icon: Sparkles },
            { label: '扩展', value: items.filter((item) => item.kind === 'extension').length, icon: Boxes },
            { label: '已获授权', value: authorizedCount, detail: '独立于披露设置', icon: ShieldCheck },
            { label: '已披露（可见）', value: disclosedCount, detail: `${hiddenCount} 项未披露`, icon: PackageCheck },
          ]} />
          <div className="capability-policy-notices">
            <InlineNotice title="披露不等于授权" tone="info">
              开启后只会让伙伴在下一次打开对话或下一轮开始时看见该能力；危险操作仍按风险、权限和确认流程处理。
            </InlineNotice>
            {catalog.data?.projectScope.supported ? (
              <InlineNotice title="当前项目默认可用" tone="success">
                {projectScopeReason(catalog.data.projectScope.reason)} 当前项目默认优先于所有对话默认，当前对话临时设置仍可覆盖它。
              </InlineNotice>
            ) : null}
            {!catalog.data?.projectScope.supported ? (
              <InlineNotice title="当前页面没有项目上下文" tone="warning">
                {projectScopeReason(catalog.data?.projectScope.reason ?? '')} 所有对话默认和当前对话临时设置仍然可用。
              </InlineNotice>
            ) : null}
            {defaults.error ? (
              <InlineNotice title="默认设置暂时无法读取" tone="danger">
                当前目录仍可查看，但不会猜测默认值，也不会发送修改。
                <Button onClick={() => void defaults.refetch()} size="small" variant="quiet">重试默认设置</Button>
              </InlineNotice>
            ) : null}
            {defaultMutation?.status === 'pending' ? (
              <InlineNotice title="正在保存默认设置" tone="info">{defaultMutation.message}</InlineNotice>
            ) : null}
            {defaultMutation?.status === 'succeeded' ? (
              <InlineNotice title="默认设置已保存" tone="success">{defaultMutation.message}</InlineNotice>
            ) : null}
            {defaultMutation?.status === 'failed' ? (
              <InlineNotice title="默认设置没有保存" tone="danger">
                {defaultMutation.message}
                <Button disabled={defaultSettingsPending} onClick={retryDefaultMutation} size="small" variant="quiet">重试这次更改</Button>
              </InlineNotice>
            ) : null}
          </div>
        </ManagementSection>

        <ManagementSection
          description="选择一项查看来源、安装或在线状态、风险、所需权限，以及授权与披露为什么生效。"
          title="全部能力"
          trailing={<span className="plugins-count">{filtered.length} 项</span>}
        >
          <div className="plugins-filters">
            <Field className="plugins-search" htmlFor="plugin-search" label="搜索">
              <Input id="plugin-search" onChange={(event) => setQuery(event.target.value)} placeholder="名称、用途、来源或权限" value={query} />
            </Field>
            <Field htmlFor="plugin-availability" label="状态">
              <Select
                id="plugin-availability"
                onValueChange={setAvailability}
                options={[
                  { value: 'all', label: '全部状态' },
                  { value: 'online', label: '当前可用' },
                  { value: 'attention', label: '需要处理' },
                ]}
                value={availability}
              />
            </Field>
            <div className="plugins-mode-filter"><span>能力类型</span><SegmentedControl aria-label="能力类型筛选" items={kindFilters} onValueChange={setKind} value={kind} /></div>
          </div>

          {filtered.length ? (
            <div className="plugins-browser" data-detail-open={Boolean(selected)}>
              <div aria-label="能力列表" className="plugins-list" role="group">
                {filtered.map((item) => {
                  const id = itemKey(item);
                  const selectedItem = id === selectedId;
                  return (
                    <button aria-pressed={selectedItem} className="plugins-list__item" data-selected={selectedItem || undefined} key={id} onClick={() => setSelectedId(id)} type="button">
                      <span className="plugins-list__copy">
                        <small>{capabilityKindLabel(item.kind)} · {item.source.label}</small>
                        <strong>{item.displayName}</strong>
                        <span>{item.description}</span>
                      </span>
                      <span className="plugins-list__aside"><StatusBadge {...availabilityBadge(item)} /><ChevronRight aria-hidden="true" size={15} /></span>
                    </button>
                  );
                })}
              </div>
              {selected ? (
                <ToolDetail
                  assistantName={identity.assistantName}
                  defaultPending={defaultSettingsPending}
                  projectPending={defaultSettingsPending}
                  projectPreference={
                    catalog.data?.projectScope.projectId
                      ? defaults.data?.projectPreferences[catalog.data.projectScope.projectId]?.[selected.canonicalId] ?? 'inherit'
                      : 'inherit'
                  }
                  projectAvailable={Boolean(defaults.data && catalog.data?.projectScope.projectId)}
                  projectOwnerId={catalog.data?.projectScope.projectId}
                  defaultPreference={defaults.data?.preferences[selected.canonicalId] ?? 'inherit'}
                  defaultsAvailable={Boolean(defaults.data)}
                  item={selected}
                  sessionOwnerId={catalog.data?.sessionPolicy?.sessionId}
                  sessionPreference={catalog.data?.sessionPolicy?.disclosurePreferences.session[selected.canonicalId] ?? 'inherit'}
                  onClose={() => setSelectedId('')}
                  onDefaultPreferenceChange={(preference) => void updateDefaultPreference(selected, preference)}
                  onProjectPreferenceChange={(preference) => void updateProjectPreference(selected, preference)}
                />
              ) : (
                <aside aria-label="能力详情占位" className="plugins-detail plugins-detail--empty">
                  <Wrench aria-hidden="true" size={20} />
                  <strong>选择一项能力查看详情</strong>
                  <span>这里会显示来源、状态、风险、权限，以及全局和项目默认。</span>
                </aside>
              )}
            </div>
          ) : <EmptyState description={items.length ? '换一个关键词或筛选条件试试。' : '后端目录当前没有返回能力项目。'} icon={Search} title="没有找到能力" />}
        </ManagementSection>
      </QueryState>

      <div className="plugins-maintenance-entry">
        <span>
          <strong>扩展与自动整理</strong>
          <small>安装额外能力，或调整任务完成、上下文整理和工具失败后的自动记录。</small>
        </span>
        <Button
          aria-expanded={showMaintenance}
          leadingIcon={<Settings2 size={15} />}
          onClick={() => setShowMaintenance((current) => !current)}
          size="small"
          variant="quiet"
        >
          {showMaintenance ? '收起维护选项' : '管理扩展与自动整理'}
        </Button>
      </div>

      {showMaintenance ? <ManagementSection
        description="安装、更新或停用额外能力。每次更改都会先说明来源、权限和影响，再由你确认。"
        title="扩展管理"
        trailing={<StatusBadge label={pluginQueryError ? '暂时无法读取' : `${installedItems.length} 个已安装`} tone={pluginQueryError ? 'warning' : 'neutral'} />}
      >
        <QueryState
          error={pluginQueryError}
          isPending={pluginQueriesPending}
          onRetry={() => void Promise.all([installed.refetch(), versions.refetch(), proposals.refetch()])}
        >
          <div className="plugin-lifecycle">
            <div className="plugin-catalog" aria-label="受管插件目录">
              {versionItems.map((item) => {
                const security = asRecord(item.security);
                const source = asRecord(item.source);
                return (
                  <article className="plugin-catalog__row" key={stringValue(item.id)}>
                    <span className="plugin-catalog__identity">
                      <strong>{stringValue(item.displayName, stringValue(item.id))}</strong>
                      <small>{stringValue(item.publisher)} · {stringValue(source.label)}</small>
                      <span>{stringValue(item.description)}</span>
                    </span>
                    <span className="plugin-catalog__facts">
                      <span><ShieldCheck size={14} />需要的权限：{stringArray(item.permissions).join('、') || '无额外权限'}</span>
                      <span><History size={14} />v{stringValue(item.latestVersion, '未发布')} · {arrayRecords(item.versions).length} 个版本</span>
                      <span><ShieldAlert size={14} />{stringValue(security.notes, '尚无安全说明')}</span>
                    </span>
                    <span className="plugin-catalog__action">
                      <StatusBadge {...catalogStateBadge(item)} />
                      <Button
                        disabled={item.actionable !== true || (item.installed === true && item.updateAvailable !== true) || lifecyclePending}
                        leadingIcon={<PackageCheck size={15} />}
                        loading={validate.isPending || preview.isPending}
                        onClick={() => void previewCatalogAction(item)}
                        size="small"
                      >{item.updateAvailable === true ? '查看更新内容' : item.installed === true ? '已安装' : item.actionable === true ? '查看安装内容' : '查看说明'}</Button>
                    </span>
                  </article>
                );
              })}
            </div>
            <div className="plugin-authoring-callout">
              <span className="plugin-authoring-callout__icon"><Sparkles aria-hidden="true" size={18} /></span>
              <span><strong>让{identity.assistantName}准备扩展草稿</strong><small>自定义代码不会直接启用；完成检查并加入可信目录后，才可以安装。</small></span>
              <Button
                leadingIcon={<MessageCircle size={16} />}
                onClick={() => navigate({
                  pathname: '/agent',
                  search: new URLSearchParams({
                    draft: '/skill:plugin-creator 帮我创建一个插件审阅草稿。先询问用途和权限边界，再生成并校验草稿；不要声称它已获准执行，也不要绕过第一方目录审查。',
                  }).toString(),
                })}
              >准备扩展草稿</Button>
            </div>
            <Switch checked={enableAfterInstall} label="安装后立即启用" onCheckedChange={setEnableAfterInstall} />

            {proposalItems.length ? (
              <div className="plugin-lifecycle__proposals">
                <h3>{identity.assistantName}的建议</h3>
                {proposalItems.map((proposal) => {
                  const summary = asRecord(proposal.summary);
                  return (
                    <button className="plugin-proposal" key={stringValue(proposal.proposalId)} onClick={() => setPendingChange(proposal)} type="button">
                      <span><strong>{stringValue(summary.displayName, stringValue(summary.pluginId))}</strong><small>{pluginActionLabel(stringValue(summary.action))}</small></span>
                      <ChevronRight aria-hidden="true" size={16} />
                    </button>
                  );
                })}
              </div>
            ) : null}

            {pendingChange.previewToken ? (
              <InlineNotice title="等待你的批准" tone="warning">
                <div className="plugin-lifecycle__approval">
                  <span>
                    {pluginActionLabel(stringValue(pendingSummary.action))}：{pendingDisplayName}
                    <small>
                      {pendingCanonicalEvidence}
                      {stringValue(pendingSummary.version) ? `v${stringValue(pendingSummary.version)} · ` : ''}
                      {stringArray(pendingSummary.permissions).length
                        ? `需要的权限：${stringArray(pendingSummary.permissions).join('、')}`
                        : '无额外权限'}
                      {typeof pendingSummary.expectedEnabled === 'boolean'
                        ? ` · 当前${pendingSummary.expectedEnabled ? '已启用' : '已停用'}`
                        : ''}
                      {stringValue(pendingSummary.expectedActiveDigest)
                        ? ` · 校验标记 ${shortDigest(stringValue(pendingSummary.expectedActiveDigest))}`
                        : ''}
                    </small>
                  </span>
                  <div>
                    <Button disabled={lifecyclePending} onClick={() => setPendingChange({})} size="small" variant="quiet">取消</Button>
                    <Button leadingIcon={<ShieldCheck size={16} />} loading={apply.isPending} onClick={() => void applyPendingChange()} size="small" variant="primary">确认更改</Button>
                  </div>
                </div>
              </InlineNotice>
            ) : null}

            {lifecycleError ? <InlineNotice title="插件操作未完成" tone="danger">{lifecycleError}</InlineNotice> : null}

            <div className="plugin-lifecycle__installed">
              {installedItems.length ? installedItems.map((plugin) => (
                <article className="installed-plugin" key={stringValue(plugin.id)}>
                  <div><strong>{stringValue(plugin.displayName, stringValue(plugin.id))}</strong><span>v{stringValue(plugin.version)}</span></div>
                  <StatusBadge label={plugin.enabled === true ? '已启用' : '已停用'} tone={plugin.enabled === true ? 'success' : 'neutral'} />
                  <div className="installed-plugin__actions">
                    <Button
                      disabled={lifecyclePending}
                      leadingIcon={<Power size={15} />}
                      onClick={() => void previewInstalledAction(plugin.enabled === true ? 'disable' : 'enable', stringValue(plugin.id))}
                      size="small"
                      variant="quiet"
                    >{plugin.enabled === true ? '停用' : '启用'}</Button>
                    <Button
                      disabled={plugin.rollbackAvailable !== true || lifecyclePending}
                      leadingIcon={<RotateCcw size={15} />}
                      onClick={() => void previewInstalledAction('rollback', stringValue(plugin.id))}
                      size="small"
                      variant="quiet"
                    >恢复上一版本</Button>
                  </div>
                </article>
              )) : <EmptyState description="需要新能力时，可以先查看来源和权限，再决定是否安装。" icon={PackageCheck} title="还没有额外扩展" />}
            </div>
          </div>
        </QueryState>
      </ManagementSection> : null}

      {showMaintenance ? <ManagementSection
        description="在一些关键时刻自动留下检查点或复盘建议。它不会替你写入长期记忆，也不会获得新的权限。"
        title="自动整理与提醒"
        trailing={<StatusBadge label={lifecycle.error ? '状态不可用' : `${lifecyclePolicies.filter((item) => item.enabled === true).length}/${lifecyclePolicies.length} 已启用`} tone={lifecycle.error ? 'warning' : 'neutral'} />}
      >
        <QueryState
          error={asError(lifecycle.error)}
          isPending={lifecycle.isPending}
          onRetry={() => void lifecycle.refetch()}
        >
          <div className="lifecycle-hooks">
            <div className="lifecycle-hooks__policies">
              {lifecyclePolicies.map((policy) => (
                <article className="lifecycle-policy" key={stringValue(policy.eventType)}>
                  <span className="lifecycle-policy__title">
                    <strong>{lifecycleEventLabel(stringValue(policy.eventType))}</strong>
                    <small>{lifecycleActionLabel(stringValue(policy.action))}</small>
                  </span>
                  <span className="lifecycle-policy__limits">
                    <span><Sparkles size={14} />最多 {Number(policy.tokenLimit || 0)} 个模型词元</span>
                    <span><Clock3 size={14} />{cooldownLabel(Number(policy.cooldownSeconds || 0))}</span>
                  </span>
                  <Switch
                    checked={policy.enabled === true}
                    disabled={updateLifecycle.isPending}
                    label={`${lifecycleEventLabel(stringValue(policy.eventType))}：${policy.enabled === true ? '已启用' : '已停用'}`}
                    onCheckedChange={(enabled) => void updateHook(stringValue(policy.eventType), enabled)}
                  />
                </article>
              ))}
            </div>
            <div className="lifecycle-hooks__audit">
              <h3>最近状态</h3>
              {lifecycleEvents.length ? lifecycleEvents.slice(0, 8).map((event) => (
                <div className="lifecycle-audit" key={stringValue(event.eventId)}>
                  <span><strong>{lifecycleEventLabel(stringValue(event.eventType))}</strong><small>{stringValue(event.sessionId)}</small></span>
                  <StatusBadge {...lifecycleStatusBadge(event)} />
                </div>
              )) : <EmptyState description="功能在对话中触发后，运行记录会显示在这里。" icon={History} title="还没有触发记录" />}
            </div>
            {hookError ? <InlineNotice title="自动整理设置没有保存" tone="danger">{hookError}</InlineNotice> : null}
          </div>
        </QueryState>
      </ManagementSection> : null}
    </ManagementPage>
  );
}

function ToolDetail({
  assistantName,
  defaultPending,
  defaultPreference,
  defaultsAvailable,
  item,
  onClose,
  onDefaultPreferenceChange,
  onProjectPreferenceChange,
  projectAvailable,
  projectOwnerId,
  projectPending,
  projectPreference,
  sessionOwnerId,
  sessionPreference,
}: {
  assistantName: string;
  defaultPending: boolean;
  defaultPreference: CapabilityPreference;
  defaultsAvailable: boolean;
  item: ToolRecord;
  onClose: () => void;
  onDefaultPreferenceChange: (preference: CapabilityPreference) => void;
  onProjectPreferenceChange: (preference: CapabilityPreference) => void;
  projectAvailable: boolean;
  projectOwnerId?: string;
  projectPending: boolean;
  projectPreference: CapabilityPreference;
  sessionOwnerId?: string;
  sessionPreference: CapabilityPreference;
}) {
  const operations = operationLabelsFor(item);
  const unknownOperationCount = Math.max(
    0,
    stringArray(item.operations).length - operations.length,
  );
  const schema = asRecord(item.schema ?? item.inputSchema ?? item.parameters);
  const DetailIcon = item.kind === 'skill' ? Sparkles : item.kind === 'extension' ? Boxes : Wrench;
  const fixed = item.alwaysAvailable === true;

  return (
    <aside aria-label="能力详情" className="plugins-detail">
      <div className="plugins-detail__toolbar">
        <span>能力详情</span>
        <IconButton
          icon={<PanelRightClose size={16} />}
          label="关闭能力详情"
          onClick={onClose}
          tooltip
        />
      </div>

      <div className="plugins-detail__heading">
        <span className="plugins-detail__icon">
          <DetailIcon aria-hidden="true" size={18} />
        </span>
        <div>
          <small>{capabilityKindLabel(item.kind)} · {item.source.label}</small>
          <h3>{item.displayName}</h3>
          <p>{item.description}</p>
        </div>
        <StatusBadge {...availabilityBadge(item)} />
      </div>

      <dl className="plugins-detail__facts">
        <div>
          <dt><CheckCircle2 aria-hidden="true" size={15} />安装与在线状态</dt>
          <dd>{capabilityStatusLabel(item.status)}</dd>
        </div>
        <div>
          <dt><ShieldAlert aria-hidden="true" size={15} />风险</dt>
          <dd>{capabilityRiskLabel(item.risk)}</dd>
        </div>
        <div>
          <dt><ShieldCheck aria-hidden="true" size={15} />所需权限</dt>
          <dd>{item.requiredPermissions.length ? item.requiredPermissions.join('、') : '不需要额外权限'}</dd>
        </div>
        <div>
          <dt><ShieldCheck aria-hidden="true" size={15} />执行授权</dt>
          <dd>
            {item.authorization.state === 'authorized' ? '已授权'
              : item.authorization.state === 'denied' ? '未授权' : '不适用'}
            {item.authorization.reason ? ` · ${item.authorization.reason}` : ''}
          </dd>
        </div>
        <div>
          <dt><MessageCircle aria-hidden="true" size={15} />当前披露</dt>
          <dd>
            {item.disclosure.effective === 'enabled' ? `会向${assistantName}披露` : `不会向${assistantName}披露`}
            {item.disclosure.reason ? ` · ${item.disclosure.reason}` : ''}
          </dd>
        </div>
        <div>
          <dt><History aria-hidden="true" size={15} />生效来源</dt>
          <dd>{capabilityScopeLabel(item.effectiveScope)}</dd>
        </div>
      </dl>

      {fixed ? (
        <section aria-label="固定能力策略" className="capability-precedence">
          <header>
            <span>
              <small>产品内置规则</small>
              <strong>固定加载</strong>
            </span>
            <StatusBadge label="基础能力" tone="success" />
          </header>
          <p>
            普通伙伴会话始终加载此能力，不参与当前对话、当前项目或所有对话的披露开关；
            执行权限仍由 Runtime 单独核对。
          </p>
        </section>
      ) : (
        <>
          <section aria-label="能力披露优先级" className="capability-precedence">
            <header>
              <span>
                <small>后端核对的当前结果</small>
                <strong>{capabilityEffectiveLabel(item.disclosure.effective)}</strong>
              </span>
              <StatusBadge
                label={capabilityScopeLabel(item.effectiveScope)}
                tone={item.disclosure.effective === 'enabled' ? 'success' : 'neutral'}
              />
            </header>
            <dl>
              {sessionOwnerId ? (
                <div>
                  <dt>1 · 当前对话临时设置</dt>
                  <dd>{preferenceLabel(sessionPreference)}<small>由当前对话控制 · {shortDigest(sessionOwnerId)}</small></dd>
                </div>
              ) : null}
              {projectAvailable ? (
                <div>
                  <dt>{sessionOwnerId ? '2' : '1'} · 当前项目默认</dt>
                  <dd>{preferenceLabel(projectPreference)}<small>由当前授权工作区控制 · {shortDigest(projectOwnerId ?? '')}</small></dd>
                </div>
              ) : null}
              <div>
                <dt>{sessionOwnerId ? (projectAvailable ? '3' : '2') : (projectAvailable ? '2' : '1')} · 所有对话默认</dt>
                <dd>{preferenceLabel(defaultPreference)}<small>由所有对话设置控制</small></dd>
              </div>
              <div>
                <dt>最后 · 产品内置默认</dt>
                <dd>{item.effectiveScope === 'built_in_default' ? capabilityEffectiveLabel(item.disclosure.effective) : '由后端目录决定'}<small>仅在上层全部继承时使用</small></dd>
              </div>
            </dl>
            <p>按上列顺序取第一个非“继承默认”的值；披露结果不会改变执行授权。</p>
          </section>

          <Field
            className="capability-default-field"
            description="由所有对话设置控制。影响未被当前项目默认或当前对话临时设置覆盖的对话；未在工作的对话会在下一轮重新加载时生效，不会取消运行中任务或授予执行权限。"
            htmlFor={`capability-global-default-${item.canonicalId.replace(/[^a-z0-9_-]/giu, '-')}`}
            label="所有对话默认披露"
          >
            <Select
              aria-label={`${item.displayName}的所有对话默认披露`}
              disabled={!defaultsAvailable || defaultPending}
              id={`capability-global-default-${item.canonicalId.replace(/[^a-z0-9_-]/giu, '-')}`}
              onValueChange={onDefaultPreferenceChange}
              options={capabilityPreferenceOptions}
              value={defaultPreference}
            />
          </Field>
          {projectAvailable ? (
            <Field
              className="capability-default-field"
              description={`由当前授权工作区${projectOwnerId ? `（${shortDigest(projectOwnerId)}）` : ''}控制。优先于所有对话默认；当前对话临时设置仍优先。`}
              htmlFor={`capability-project-default-${item.canonicalId.replace(/[^a-z0-9_-]/giu, '-')}`}
              label="当前项目默认披露"
            >
              <Select
                aria-label={`${item.displayName}的当前项目默认披露`}
                disabled={projectPending}
                id={`capability-project-default-${item.canonicalId.replace(/[^a-z0-9_-]/giu, '-')}`}
                onValueChange={onProjectPreferenceChange}
                options={capabilityPreferenceOptions}
                value={projectPreference}
              />
            </Field>
          ) : null}
        </>
      )}


      {operations.length || unknownOperationCount ? (
        <div className="plugins-detail__capabilities">
          <h4>后端声明的操作</h4>
          <ul>
            {operations.map((operation) => <li key={operation}>{operation}</li>)}
            {unknownOperationCount ? <li>其他 {unknownOperationCount} 项操作</li> : null}
          </ul>
        </div>
      ) : null}

      {item.reasons.length ? (
        <section className="capability-disclosure">
          <h4>为什么得到当前结果</h4>
          <ul>{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </section>
      ) : null}

      {Object.keys(schema).length ? (
        <section className="capability-disclosure">
          <details>
            <summary>查看技术参数</summary>
            <pre>{JSON.stringify(schema, null, 2)}</pre>
          </details>
        </section>
      ) : null}
    </aside>
  );
}


function itemKey(item: ToolRecord): string { return item.canonicalId; }
function stringArray(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }
function operationLabelsFor(item: ToolRecord): string[] { return stringArray(item.operations).map((operation) => operationLabels[operation]).filter((operation): operation is string => Boolean(operation)); }
function availabilityBadge(item: ToolRecord): { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' } {
  const status = item.status.toLowerCase();
  if (status === 'online' || status === 'ready' || status === 'installed') return { label: capabilityStatusLabel(status), tone: 'success' };
  if (status === 'offline') return { label: capabilityStatusLabel(status), tone: 'danger' };
  if (status === 'unconfigured') return { label: capabilityStatusLabel(status), tone: 'warning' };
  return { label: capabilityStatusLabel(status), tone: 'neutral' };
}
function pluginActionLabel(action: string): string { if (action === 'install') return '安装插件'; if (action === 'update') return '更新插件'; if (action === 'enable') return '启用插件'; if (action === 'disable') return '停用插件'; if (action === 'rollback') return '回滚插件'; return '变更插件'; }
function catalogStateBadge(item: Record<string, unknown>): { label: string; tone: 'success' | 'warning' | 'neutral' } { if (item.updateAvailable === true) return { label: '有更新', tone: 'warning' }; if (item.installed === true) return { label: '已是最新', tone: 'success' }; if (item.actionable === true) return { label: '可安装', tone: 'neutral' }; return { label: '仅供审阅', tone: 'neutral' }; }
function lifecycleEventLabel(value: string): string { return ({ session_start: '开始对话', turn_end: '完成一轮回复', compaction: '整理长对话', project_complete: '任务完成', tool_failed: '工具没有成功', idle: '暂时空闲' } as Record<string, string>)[value] ?? value; }
function lifecycleActionLabel(value: string): string { return ({ audit_only: '只记录发生了什么', context_checkpoint: '为下一轮保留上下文', memory_review_suggestion: '为下一轮准备记忆建议' } as Record<string, string>)[value] ?? value; }
function cooldownLabel(seconds: number): string { if (!seconds) return '可以随时触发'; if (seconds >= 60) return `至少间隔 ${Math.round(seconds / 60)} 分钟`; return `至少间隔 ${seconds} 秒`; }
function lifecycleStatusBadge(item: Record<string, unknown>): { label: string; tone: 'success' | 'warning' | 'neutral' } { const status = stringValue(item.status); if (status === 'suggested') return { label: '待下一轮复盘', tone: 'warning' }; if (status === 'recorded') return { label: '已记录', tone: 'success' }; if (status === 'skipped') return { label: '无事实已跳过', tone: 'neutral' }; if (status === 'cooldown') return { label: '冷却中', tone: 'neutral' }; return { label: status === 'disabled' ? '策略停用' : status, tone: 'neutral' }; }
function errorMessage(error: unknown): string { return publicErrorText(error, '插件操作失败，请稍后重试。'); }
function asError(error: unknown): Error | null { return error instanceof Error ? error : error ? new Error('暂时无法读取这部分内容。') : null; }
function firstError(...errors: unknown[]): Error | null { return errors.map(asError).find((error): error is Error => Boolean(error)) ?? null; }
function shortDigest(value: string): string { return value.length > 16 ? `${value.slice(0, 12)}…${value.slice(-4)}` : value; }
