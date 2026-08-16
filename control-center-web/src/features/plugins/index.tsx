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
import { useEffect, useMemo, useRef, useState } from 'react';
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
  create_package: '创建 Pi Package', validate: '检查安装来源', propose_install: '提交安装提议',
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
  restart_sidecar: '重新连接本机补全服务', restore_apply: '恢复备份', restore_preview: '预览恢复内容', resume_ai: '恢复智能功能',
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
  const selectedTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [enableAfterInstall, setEnableAfterInstall] = useState(true);
  const [packageSource, setPackageSource] = useState('');
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
  useEffect(() => {
    if (!selectedId) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      setSelectedId('');
      selectedTriggerRef.current?.focus();
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [selectedId]);
  const installedItems = arrayRecords(asRecord(installed.data).items);
  const proposalItems = arrayRecords(asRecord(proposals.data).items);
  const versionItems = arrayRecords(asRecord(versions.data).items);
  const lifecyclePolicies = arrayRecords(asRecord(lifecycle.data).policies);
  const lifecycleEvents = arrayRecords(asRecord(lifecycle.data).recentEvents);
  const availableCount = items.filter((item) => ['online', 'ready', 'installed'].includes(item.status.toLowerCase())).length;
  const disclosedCount = items.filter((item) => item.disclosure.state === 'disclosed').length;
  const hiddenCount = items.filter((item) => item.disclosure.state === 'hidden').length;
  const pendingSummary = asRecord(pendingChange.summary);
  const pendingResources = asRecord(pendingSummary.resources);
  const pendingResourceCount = ['extensions', 'skills', 'prompts', 'themes']
    .reduce((total, resourceKind) => total + stringArray(pendingResources[resourceKind]).length, 0);
  const pendingSource = asRecord(pendingSummary.source);
  const validatedExtension = asRecord(validation.extension);
  const validatedResources = asRecord(validatedExtension.resources);
  const validatedResourceCount = ['extensions', 'skills', 'prompts', 'themes']
    .reduce((total, resourceKind) => total + stringArray(validatedResources[resourceKind]).length, 0);
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
        message: `所有对话默认已保存：${preferenceLabel(preference)}。`,
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
        message: `当前项目默认已保存：${preferenceLabel(preference)}。`,
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
        message: '这项能力已不在可用目录中；旧设置没有再次发送。',
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

  const applyInstalledAction = async (action: 'disable' | 'rollback', pluginId: string) => {
    setLifecycleError('');
    try {
      const next = asRecord(await preview.mutateAsync({ action, pluginId }));
      await apply.mutateAsync({
        previewToken: stringValue(next.previewToken),
        payloadSha256: stringValue(next.payloadSha256),
        confirmText: 'apply',
      });
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

  const previewPackageSource = async () => {
    const source = packageSource.trim();
    setLifecycleError('');
    setValidation({});
    setPendingChange({});
    if (!source) {
      setLifecycleError('请输入 npm 包、Git 地址或本地 Pi Package 目录。');
      return;
    }
    try {
      const validationResult = asRecord(await validate.mutateAsync({ packageSource: source }));
      const extension = asRecord(validationResult.extension);
      const pluginId = stringValue(extension.id);
      const installedPackage = installedItems.find((item) => stringValue(item.id) === pluginId);
      setValidation(validationResult);
      setPendingChange(asRecord(await preview.mutateAsync({
        action: installedPackage ? 'update' : 'install',
        validationToken: stringValue(validationResult.validationToken),
        enable: installedPackage ? installedPackage.enabled === true : enableAfterInstall,
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
      description="选择伙伴在对话中可以使用的技能与工具，并为所有对话或当前项目设置默认范围。"
      eyebrow="伙伴能力"
      routeId="plugins"
      title="技能与工具"
    >
      <QueryState error={asError(catalog.error)} isPending={catalog.isPending} onRetry={() => void catalog.refetch()}>
        <ManagementSection
          description="在这里选择伙伴可以使用哪些能力。涉及文件、账户或其他敏感操作时，仍会在执行前征求你的同意。"
          title="能力概览"
        >
          <MetricStrip items={[
            { label: '可查看', value: items.length, detail: '技能与工具', icon: Wrench },
            { label: '当前可用', value: availableCount, detail: '连接正常', icon: ShieldCheck },
            { label: '伙伴可见', value: disclosedCount, detail: hiddenCount ? `${hiddenCount} 项暂不显示` : '全部可见', icon: PackageCheck },
          ]} />
          <details className="plugins-policy-disclosure">
            <summary>
              <span>
                <strong>能力如何生效</strong>
                <small>{catalog.data?.projectScope.supported ? '当前项目有独立默认设置' : '当前使用所有对话的默认设置'}</small>
              </span>
              <ChevronRight aria-hidden="true" size={16} />
            </summary>
            <div className="capability-policy-notices">
              <InlineNotice title="显示出来，不等于自动执行" tone="info">
                开启后，伙伴会在下一轮对话中知道这项能力；涉及风险的操作仍会按原有规则询问你。
              </InlineNotice>
              {catalog.data?.projectScope.supported ? (
                <InlineNotice title="当前项目默认可用" tone="success">
                  {projectScopeReason(catalog.data.projectScope.reason)} 当前项目默认优先于所有对话默认，当前对话临时设置仍可覆盖它。
                </InlineNotice>
              ) : (
                <InlineNotice title="当前只显示所有对话设置" tone="info">
                  从某个项目的伙伴对话进入后，才能设置该项目的默认范围。所有对话设置仍可正常使用。
                </InlineNotice>
              )}
            </div>
          </details>
          <div className="capability-policy-feedback">
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
          description="选择一项查看它能做什么、当前是否可用，以及由哪一层设置决定伙伴能否使用。"
          title="浏览技能与工具"
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
                    <button aria-pressed={selectedItem} className="plugins-list__item" data-selected={selectedItem || undefined} key={id} onClick={(event) => { selectedTriggerRef.current = event.currentTarget; setSelectedId(id); }} type="button">
                      <span className="plugins-list__copy">
                        <small>{publicCapabilitySourceLabel(item.source.label)} · {capabilityKindLabel(item.kind)}</small>
                        <strong>{publicCapabilityDisplayName(item)}</strong>
                        <span>{publicCapabilityDescription(item)}</span>
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
                  onClose={() => { setSelectedId(''); selectedTriggerRef.current?.focus(); }}
                  onDefaultPreferenceChange={(preference) => void updateDefaultPreference(selected, preference)}
                  onProjectPreferenceChange={(preference) => void updateProjectPreference(selected, preference)}
                />
              ) : (
                <aside aria-label="能力详情占位" className="plugins-detail plugins-detail--empty">
                  <Wrench aria-hidden="true" size={20} />
                  <strong>选择一项能力查看详情</strong>
                  <span>这里会显示用途、可用状态、风险提示，以及对话和项目设置。</span>
                </aside>
              )}
            </div>
          ) : <EmptyState description={items.length ? '换一个关键词或筛选条件试试。' : '当前没有可用的技能或工具。'} icon={Search} title="没有找到能力" />}
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
        description="安装或启用新能力前会先说明来源、权限和影响；停用与恢复上一版本会直接生效。"
        title="扩展管理"
        trailing={<StatusBadge label={pluginQueryError ? '暂时无法读取' : `${installedItems.length} 个已安装`} tone={pluginQueryError ? 'warning' : 'neutral'} />}
      >
        <QueryState
          error={pluginQueryError}
          isPending={pluginQueriesPending}
          onRetry={() => void Promise.all([installed.refetch(), versions.refetch(), proposals.refetch()])}
        >
          <div className="plugin-lifecycle">
            <div className="plugin-lifecycle__install">
              <Field htmlFor="pi-package-source" label="Pi Package 来源">
                <Input
                  id="pi-package-source"
                  onChange={(event) => setPackageSource(event.target.value)}
                  placeholder="npm:@scope/package@1.2.3、Git URL 或本地目录"
                  value={packageSource}
                />
              </Field>
              <Switch checked={enableAfterInstall} label="安装后立即启用" onCheckedChange={setEnableAfterInstall} />
              <Button
                disabled={!packageSource.trim() || lifecyclePending}
                leadingIcon={<PackageCheck size={15} />}
                loading={validate.isPending || preview.isPending}
                onClick={() => void previewPackageSource()}
                size="small"
              >检查并预览</Button>
              {validatedExtension.id ? (
                <div className="plugin-lifecycle__validation">
                  <StatusBadge label="Pi 已解析" tone="success" />
                  <strong>{publicPluginDisplayName(stringValue(validatedExtension.displayName, stringValue(validatedExtension.id)))}</strong>
                  <span>v{stringValue(validatedExtension.version)} · {validatedResourceCount} 项资源 · 新对话加载 Skill、Prompt 与主题</span>
                </div>
              ) : null}
            </div>
            <div className="plugin-catalog" aria-label="受管插件目录">
              {versionItems.map((item) => {
                const security = asRecord(item.security);
                const source = asRecord(item.source);
                return (
                  <article className="plugin-catalog__row" key={stringValue(item.id)}>
                    <span className="plugin-catalog__identity">
                      <strong>{publicPluginDisplayName(stringValue(item.displayName, stringValue(item.id)))}</strong>
                      <small>{publicPluginSourceLabel(stringValue(item.publisher))} · {publicPluginSourceLabel(stringValue(source.label))}</small>
                      <span>{stringValue(item.description)}</span>
                    </span>
                    <span className="plugin-catalog__facts">
                      <span><ShieldCheck size={14} />需要的权限：{stringArray(item.permissions).map(publicPluginPermissionLabel).join('、') || '无额外权限'}</span>
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
              <span><strong>让{identity.assistantName}查找或创造新能力</strong><small>先搜索现有 Pi Package；没有合适能力时，再制作最小 Package。安装仍会停在上面的确认卡。</small></span>
              <Button
                leadingIcon={<MessageCircle size={16} />}
                onClick={() => navigate({
                  pathname: '/agent',
                  search: new URLSearchParams({
                    draft: '/skill:plugin-creator 我需要一个新能力。先搜索市场和已安装 Pi Package；只有没有合适能力且值得复用时才创建最小 Package。完成来源检查并提交安装预览后停下，等待我的产品内确认；不要声称已经安装。',
                  }).toString(),
                })}
              >获取或制作能力</Button>
            </div>

            {proposalItems.length ? (
              <div className="plugin-lifecycle__proposals">
                <h3>{identity.assistantName}的建议</h3>
                {proposalItems.map((proposal) => {
                  const summary = asRecord(proposal.summary);
                  return (
                    <button className="plugin-proposal" key={stringValue(proposal.proposalId)} onClick={() => setPendingChange(proposal)} type="button">
                      <span><strong>{publicPluginDisplayName(stringValue(summary.displayName, stringValue(summary.pluginId)))}</strong><small>{pluginActionLabel(stringValue(summary.action))}</small></span>
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
                    {pluginActionLabel(stringValue(pendingSummary.action))}：{publicPluginDisplayName(pendingDisplayName)}
                    <small>
                      {pendingCanonicalEvidence}
                      {stringValue(pendingSummary.version) ? `v${stringValue(pendingSummary.version)} · ` : ''}
                      {stringArray(pendingSummary.permissions).length
                        ? `需要的权限：${stringArray(pendingSummary.permissions).map(publicPluginPermissionLabel).join('、')}`
                        : '无额外权限'}
                      {pendingResourceCount ? ` · ${pendingResourceCount} 项 Pi 资源` : ''}
                      {stringValue(pendingSource.kind) ? ` · 来源：${publicPluginSourceLabel(stringValue(pendingSource.kind))}` : ''}
                      {typeof pendingSummary.expectedEnabled === 'boolean'
                        ? ` · 当前${pendingSummary.expectedEnabled ? '已启用' : '已停用'}`
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
                  <div><strong>{publicPluginDisplayName(stringValue(plugin.displayName, stringValue(plugin.id)))}</strong><span>v{stringValue(plugin.version)}</span></div>
                  <StatusBadge label={plugin.enabled === true ? '已启用' : '已停用'} tone={plugin.enabled === true ? 'success' : 'neutral'} />
                  <div className="installed-plugin__actions">
                    <Button
                      disabled={lifecyclePending}
                      leadingIcon={<Power size={15} />}
                      onClick={() => void (plugin.enabled === true
                        ? applyInstalledAction('disable', stringValue(plugin.id))
                        : previewInstalledAction('enable', stringValue(plugin.id)))}
                      size="small"
                      variant="quiet"
                    >{plugin.enabled === true ? '停用' : '启用'}</Button>
                    <Button
                      disabled={plugin.rollbackAvailable !== true || lifecyclePending}
                      leadingIcon={<RotateCcw size={15} />}
                      onClick={() => void applyInstalledAction('rollback', stringValue(plugin.id))}
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
                    <span><Sparkles size={14} />摘要长度：{Number(policy.tokenLimit || 0) > 320 ? '标准' : '简短'}</span>
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
                  <span><strong>{lifecycleEventLabel(stringValue(event.eventType))}</strong><small>最近一次对话</small></span>
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
          <small>{publicCapabilitySourceLabel(item.source.label)} · {capabilityKindLabel(item.kind)}</small>
          <h3>{publicCapabilityDisplayName(item)}</h3>
          <p>{publicCapabilityDescription(item)}</p>
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
          <dt><MessageCircle aria-hidden="true" size={15} />伙伴可见范围</dt>
          <dd>
            {item.disclosure.effective === 'enabled' ? `会向${assistantName}显示` : `暂不向${assistantName}显示`}
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
              <small>可用范围</small>
              <strong>默认可用</strong>
            </span>
            <StatusBadge label="基础能力" tone="success" />
          </header>
          <p>
            这项基础能力始终可用；实际执行前仍会检查当前权限。
          </p>
        </section>
      ) : (
        <>
          <section aria-label="能力可见范围" className="capability-precedence">
            <header>
              <span>
              <small>当前生效的设置</small>
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
                  <dt>当前对话</dt>
                  <dd>{preferenceLabel(sessionPreference)}<small>仅影响当前对话</small></dd>
                </div>
              ) : null}
              {projectAvailable ? (
                <div>
                  <dt>当前项目</dt>
                  <dd>{preferenceLabel(projectPreference)}<small>影响此项目的新对话</small></dd>
                </div>
              ) : null}
              <div>
                <dt>所有对话</dt>
                <dd>{preferenceLabel(defaultPreference)}<small>由所有对话设置控制</small></dd>
              </div>
              <div>
                <dt>默认设置</dt>
                <dd>{item.effectiveScope === 'built_in_default' ? capabilityEffectiveLabel(item.disclosure.effective) : '由可用能力决定'}<small>仅在上层全部继承时使用</small></dd>
              </div>
            </dl>
            <p>对话中的选择优先于项目和全局设置；可见范围不会改变执行权限。</p>
          </section>

          <Field
            className="capability-default-field"
            description="用于没有项目或临时设置的对话；正在进行的任务不会因此中断或获得额外权限。"
            htmlFor={`capability-global-default-${item.canonicalId.replace(/[^a-z0-9_-]/giu, '-')}`}
            label="所有对话默认可见范围"
          >
            <Select
              aria-label={`${item.displayName}的所有对话默认可见范围`}
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
              description="当前项目会优先采用这里的选择；当前对话的临时选择仍优先。"
              htmlFor={`capability-project-default-${item.canonicalId.replace(/[^a-z0-9_-]/giu, '-')}`}
              label="当前项目默认可见范围"
            >
              <Select
                aria-label={`${item.displayName}的当前项目默认可见范围`}
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
          <h4>支持的操作</h4>
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
function publicCapabilityDisplayName(item: ToolRecord): string {
  return ({ Ask: '向你提问', Todo: '任务清单' } as Record<string, string>)[item.displayName] ?? item.displayName;
}
function publicCapabilityDescription(item: ToolRecord): string {
  const exact = ({
    '维护当前 Session 的分阶段执行清单': '维护当前对话的分阶段任务清单',
    '查看语音状态，并在批准后切换已配置的语音 Provider': '查看语音状态，并在你同意后切换已配置的语音服务',
    '通过工作区语言服务器读取语义信息，并在审批后执行重命名或代码动作': '读取代码定义与引用，并在你同意后执行重命名等代码操作',
  } as Record<string, string>)[item.description];
  return exact ?? item.description
    .replaceAll('Session', '对话')
    .replaceAll('Provider', '服务')
    .replaceAll('Agent', '伙伴');
}
function publicCapabilitySourceLabel(label: string): string {
  return label === 'Personal Agent Workbench' ? '系统内置' : label;
}
function publicPluginDisplayName(label: string): string {
  return ({
    'Session Review': '对话复盘',
    'Timeline Inspector': '时间线检查',
  } as Record<string, string>)[label] ?? label;
}
function publicPluginSourceLabel(label: string): string {
  return ({
    'Personal Agent Workbench': '系统内置',
    'Product bundle': '随产品提供',
    npm: 'npm 包',
    git: 'Git 仓库',
    local: '本地目录',
  } as Record<string, string>)[label] ?? label;
}
function publicPluginPermissionLabel(permission: string): string {
  return ({
    'session.read': '读取对话内容',
    'memory.review': '提交记忆复盘建议',
  } as Record<string, string>)[permission] ?? permission;
}
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
