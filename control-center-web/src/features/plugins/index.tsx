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
  ShieldCheck,
  ShieldAlert,
  Sparkles,
  Wrench,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
import { usePluginCatalog } from './api';
import './plugins.css';

type ToolRecord = Record<string, unknown>;
type ModeFilter = 'all' | 'assistant' | 'coordinator';
type AvailabilityFilter = 'all' | 'online' | 'attention';

const modeFilters: readonly { label: string; value: ModeFilter }[] = [
  { label: '全部', value: 'all' },
  { label: '日常对话', value: 'assistant' },
  { label: '运行协调', value: 'coordinator' },
];

const domainLabels: Record<string, string> = {
  agents: 'Agent 协作', browser: '浏览器共驾', configuration: '配置管理', control: '控制中心', input: '输入法',
  knowledge: '知识检索', memory: '记忆', models: '模型', overview: '总览',
  planning: '规划任务', runtime: '诊断', voice: '语音输入', workspace: '工作区',
};

const operationLabels: Record<string, string> = {
  abort: '停止任务', apply_settings: '应用输入设置', artifact: '查看任务产物', audit: '查看审计记录',
  cache_stats: '查看缓存状态', candidate_explain: '解释候选词', capabilities: '查看可用能力', catalog: '浏览目录',
  components: '检查运行组件', dashboard: '查看规划面板', deep_recall: '深度检索', delegate: '委派任务',
  diagnose: '运行诊断', export: '导出备份', export_preview: '预览备份', get_settings: '查看输入设置',
  health: '检查健康状态', history: '查看输入历史', lexicon_apply: '应用词库更新', lexicon_review: '审阅词库建议',
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
  const {
    catalog,
    installed,
    versions,
    proposals,
    lifecycle,
    validate,
    preview,
    apply,
    updateLifecycle,
    refreshAll,
  } = usePluginCatalog();
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<ModeFilter>('all');
  const [availability, setAvailability] = useState<AvailabilityFilter>('all');
  const [selectedId, setSelectedId] = useState('');
  const [enableAfterInstall, setEnableAfterInstall] = useState(true);
  const [validation, setValidation] = useState<Record<string, unknown>>({});
  const [pendingChange, setPendingChange] = useState<Record<string, unknown>>({});
  const [lifecycleError, setLifecycleError] = useState('');
  const [hookError, setHookError] = useState('');
  const items = arrayRecords(asRecord(catalog.data).items);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    return items.filter((item) => {
      const modes = stringArray(item.sessionModes);
      const state = stringValue(item.availability).toLowerCase();
      const haystack = [item.displayName, item.description, domainLabel(item), operationLabelsFor(item).join(' ')]
        .map((value) => stringValue(value).toLocaleLowerCase('zh-CN')).join(' ');
      const matchesAvailability = availability === 'all' || (availability === 'online' ? state === 'online' : state !== 'online');
      return (!needle || haystack.includes(needle)) && (mode === 'all' || modes.includes(mode)) && matchesAvailability;
    });
  }, [availability, items, mode, query]);
  const selected = filtered.find((item) => itemKey(item) === selectedId);
  const installedItems = arrayRecords(asRecord(installed.data).items);
  const proposalItems = arrayRecords(asRecord(proposals.data).items);
  const versionItems = arrayRecords(asRecord(versions.data).items);
  const lifecyclePolicies = arrayRecords(asRecord(lifecycle.data).policies);
  const lifecycleEvents = arrayRecords(asRecord(lifecycle.data).recentEvents);
  const authorizedCount = canonicalCapabilityCount(items, capabilityAuthorizationState, (value) => value === 'authorized');
  const disclosedCount = canonicalCapabilityCount(items, capabilityDisclosureState, (value) => value === 'disclosed');
  const loadedCount = canonicalCapabilityCount(items, capabilityLoadState, (value) => value === 'loaded');
  const invokedCount = canonicalCapabilityCount(items, capabilityInvocationState, (value) => value === 'invoked');
  const revokedCount = canonicalCapabilityCount(items, capabilityRevocationState, (value) => value === 'revoked');
  const pendingSummary = asRecord(pendingChange.summary);
  const lifecyclePending = validate.isPending || preview.isPending || apply.isPending;
  const pluginQueriesPending = installed.isPending || versions.isPending || proposals.isPending;
  const pluginQueryError = firstError(installed.error, versions.error, proposals.error);
  const refreshing = catalog.isFetching || installed.isFetching || versions.isFetching
    || proposals.isFetching || lifecycle.isFetching;

  const previewInstalledAction = async (action: 'enable' | 'disable' | 'rollback', pluginId: string) => {
    setLifecycleError('');
    try {
      setPendingChange(asRecord(await preview.mutateAsync({ action, pluginId })));
    } catch (error) {
      setLifecycleError(errorMessage(error));
    }
  };

  const previewCatalogAction = async (item: ToolRecord) => {
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
      description="统一查看 Skills、Tools、Plugins 与授权边界；能力只在任务需要时渐进披露。"
      eyebrow="CAPABILITIES"
      routeId="plugins"
      title="能力中心"
    >
      <QueryState error={asError(catalog.error)} isPending={catalog.isPending} onRetry={() => void catalog.refetch()}>
        <ManagementSection description="目录可见不等于已经授权或加载。Runtime 必须逐阶段留下可审计状态。" title="能力生命周期">
          <MetricStrip items={[
            { label: 'Available', value: items.length, detail: '目录已发现', icon: Wrench },
            capabilityMetric('Authorized', authorizedCount, '明确授权', ShieldCheck),
            capabilityMetric('Disclosed', disclosedCount, '已向模型披露', Boxes),
            capabilityMetric('Loaded', loadedCount, '定义已加载', PackageCheck),
            capabilityMetric('Invoked', invokedCount, '本会话调用', History),
            capabilityMetric('Revoked', revokedCount, '授权已撤销', Power),
          ]} />
          <div className="capability-stage-legend" aria-label="能力阶段说明"><span><b>available</b>目录可见</span><span><b>authorized</b>策略允许</span><span><b>disclosed</b>已向模型披露</span><span><b>loaded</b>定义已加载</span><span><b>invoked</b>已调用</span><span><b>revoked</b>授权已撤销</span></div>
        </ManagementSection>

        <ManagementSection description="选择一项即可查看用途、可用场景和能力范围。" title="工具目录" trailing={<span className="plugins-count">{filtered.length} 项</span>}>
          <div className="plugins-filters">
            <Field className="plugins-search" htmlFor="plugin-search" label="搜索">
              <Input id="plugin-search" onChange={(event) => setQuery(event.target.value)} placeholder="名称或用途" value={query} />
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
            <div className="plugins-mode-filter"><span>使用方式</span><SegmentedControl aria-label="使用方式筛选" items={modeFilters} onValueChange={setMode} value={mode} /></div>
          </div>

          {filtered.length ? (
            <div className="plugins-browser" data-detail-open={Boolean(selected)}>
              <div aria-label="工具列表" className="plugins-list" role="group">
                {filtered.map((item) => {
                  const id = itemKey(item);
                  const selectedItem = id === selectedId;
                  return (
                    <button aria-pressed={selectedItem} className="plugins-list__item" data-selected={selectedItem || undefined} key={id} onClick={() => setSelectedId(id)} type="button">
                      <span className="plugins-list__copy"><small>{domainLabel(item)}</small><strong>{publicToolName(item)}</strong><span>{publicToolDescription(item)}</span></span>
                      <span className="plugins-list__aside"><StatusBadge {...availabilityBadge(item)} /><ChevronRight aria-hidden="true" size={15} /></span>
                    </button>
                  );
                })}
              </div>
              {selected ? <ToolDetail item={selected} onClose={() => setSelectedId('')} /> : null}
            </div>
          ) : <EmptyState description={items.length ? '没有工具符合当前筛选。' : '本机 Agent 尚未提供可用工具。'} icon={Search} title="没有匹配项" />}
        </ManagementSection>
      </QueryState>

      <ManagementSection
        description="第一方版本来自产品内置目录。目录只负责发现，安装和更新仍必须经过校验、摘要绑定预览和你的明确批准。"
        title="插件版本中心"
        trailing={<StatusBadge label={pluginQueryError ? '状态不可用' : `${installedItems.length} 个已安装`} tone={pluginQueryError ? 'warning' : 'neutral'} />}
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
                      <span><ShieldCheck size={14} />能力声明：{stringArray(item.permissions).join('、') || '无额外能力'}</span>
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
                      >{item.updateAvailable === true ? '预览更新' : item.installed === true ? '已安装' : item.actionable === true ? '预览安装' : '仅供审阅'}</Button>
                    </span>
                  </article>
                );
              })}
            </div>
            <div className="plugin-authoring-callout">
              <span className="plugin-authoring-callout__icon"><Sparkles aria-hidden="true" size={18} /></span>
              <span><strong>让 Agent 制作审阅草稿</strong><small>自定义代码不会直接进入 Pi Runtime；完成源码审查并加入第一方产品目录后，才可在这里安装。</small></span>
              <Button
                leadingIcon={<MessageCircle size={16} />}
                onClick={() => navigate({
                  pathname: '/agent',
                  search: new URLSearchParams({
                    draft: '/skill:rag-ime-plugin-creator 帮我创建一个插件审阅草稿。先询问用途和权限边界，再生成并校验草稿；不要声称它已获准执行，也不要绕过第一方目录审查。',
                  }).toString(),
                })}
              >创建审阅草稿</Button>
            </div>
            <Switch checked={enableAfterInstall} label="目录安装后启用" onCheckedChange={setEnableAfterInstall} />

            {proposalItems.length ? (
              <div className="plugin-lifecycle__proposals">
                <h3>Agent 提议</h3>
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
                    {pluginActionLabel(stringValue(pendingSummary.action))}：{stringValue(pendingSummary.displayName, stringValue(pendingSummary.pluginId))}
                    <small>
                      {stringValue(pendingSummary.version) ? `v${stringValue(pendingSummary.version)} · ` : ''}
                      {stringArray(pendingSummary.permissions).length
                        ? `能力声明：${stringArray(pendingSummary.permissions).join('、')}`
                        : '无额外能力'}
                      {typeof pendingSummary.expectedEnabled === 'boolean'
                        ? ` · 当前${pendingSummary.expectedEnabled ? '已启用' : '已停用'}`
                        : ''}
                      {stringValue(pendingSummary.expectedActiveDigest)
                        ? ` · 摘要 ${shortDigest(stringValue(pendingSummary.expectedActiveDigest))}`
                        : ''}
                    </small>
                  </span>
                  <div>
                    <Button disabled={lifecyclePending} onClick={() => setPendingChange({})} size="small" variant="quiet">取消</Button>
                    <Button leadingIcon={<ShieldCheck size={16} />} loading={apply.isPending} onClick={() => void applyPendingChange()} size="small" variant="primary">批准并应用</Button>
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
                    >回滚</Button>
                  </div>
                </article>
              )) : <EmptyState description="选择一个插件目录开始校验。" icon={PackageCheck} title="还没有受管插件" />}
            </div>
          </div>
        </QueryState>
      </ManagementSection>

      <ManagementSection
        description="Hook 只记录事实和生成下一轮可消费的复盘建议，不会直接写入长期记忆，也不会扩大工具、Plan、Goal 或审批权限。"
        title="生命周期自动化"
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
                    <span><Sparkles size={14} />{Number(policy.tokenLimit || 0)} Token 上限</span>
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
              )) : <EmptyState description="Pi Runtime 上报事件后，幂等审计会显示在这里。" icon={History} title="还没有 Hook 事件" />}
            </div>
            {hookError ? <InlineNotice title="Hook 更新失败" tone="danger">{hookError}</InlineNotice> : null}
          </div>
        </QueryState>
      </ManagementSection>
    </ManagementPage>
  );
}

function ToolDetail({ item, onClose }: { item: ToolRecord; onClose: () => void }) {
  const operations = operationLabelsFor(item); const modes = stringArray(item.sessionModes); const unknownOperationCount = Math.max(0, stringArray(item.operations).length - operations.length);
  const schema = asRecord(item.schema ?? item.inputSchema ?? item.parameters);
  return <aside aria-label="工具详情" className="plugins-detail"><div className="plugins-detail__toolbar"><span>工具详情</span><IconButton icon={<PanelRightClose size={16} />} label="关闭工具详情" onClick={onClose} tooltip /></div><div className="plugins-detail__heading"><span className="plugins-detail__icon"><Wrench aria-hidden="true" size={18} /></span><div><small>{domainLabel(item)}</small><h3>{publicToolName(item)}</h3><p>{publicToolDescription(item)}</p></div><StatusBadge {...availabilityBadge(item)} /></div><dl className="plugins-detail__facts"><div><dt><CheckCircle2 aria-hidden="true" size={15} />当前状态</dt><dd>{availabilityDescription(item)}</dd></div><div><dt><MessageCircle aria-hidden="true" size={15} />可用方式</dt><dd>{modes.length ? modes.map(modeLabel).join('、') : '暂无可用方式'}</dd></div><div><dt><ShieldCheck aria-hidden="true" size={15} />操作确认</dt><dd>{confirmationLabel(stringValue(item.riskLevel, 'R0'))}</dd></div></dl><div className="plugins-detail__capabilities"><h4>可以做什么</h4>{operations.length || unknownOperationCount ? <ul>{operations.map((operation) => <li key={operation}>{operation}</li>)}{unknownOperationCount ? <li>其他 {unknownOperationCount} 项能力</li> : null}</ul> : <p>目录中尚未提供能力说明。</p>}</div><section className="capability-disclosure"><h4>渐进披露</h4><dl><div><dt>Use when</dt><dd>{stringValue(item.useWhen, publicToolDescription(item))}</dd></div><div><dt>Not for</dt><dd>{stringValue(item.notFor, '边界未提供，暂不向模型披露')}</dd></div><div><dt>Output</dt><dd>{stringValue(item.output, '未提供，禁止前端推断')}</dd></div><div><dt>Next</dt><dd>{stringValue(item.next, '未提供，禁止前端推断')}</dd></div></dl>{Object.keys(schema).length ? <details><summary>按需查看 Tool Schema</summary><pre>{JSON.stringify(schema, null, 2)}</pre></details> : <p>Tool Schema 尚未投影；不会用前端猜测结构。</p>}</section></aside>;
}

function capabilityMetric(label: string, value: number | undefined, detail: string, icon: typeof Wrench) {
  return { label, value: value ?? '—', detail: value === undefined ? '未投影' : detail, icon, tone: value === undefined ? 'warning' as const : 'neutral' as const };
}

function canonicalCapabilityCount(items: ToolRecord[], state: (item: ToolRecord) => string | undefined, matches: (value: string) => boolean): number | undefined {
  const values = items.map(state);
  return items.length && values.every((value): value is string => value !== undefined)
    ? values.filter(matches).length
    : undefined;
}

function capabilityAuthorizationState(item: ToolRecord): string | undefined {
  if (typeof item.authorizationState === 'string') return item.authorizationState;
  if (typeof item.authorized === 'boolean') return item.authorized ? 'authorized' : 'denied';
  return undefined;
}
function capabilityDisclosureState(item: ToolRecord): string | undefined {
  if (typeof item.disclosureState === 'string') return item.disclosureState;
  if (typeof item.disclosed === 'boolean') return item.disclosed ? 'disclosed' : 'withheld';
  return undefined;
}
function capabilityLoadState(item: ToolRecord): string | undefined {
  if (typeof item.loadState === 'string') return item.loadState;
  if (item.loadedReceipt !== undefined) return item.loadedReceipt ? 'loaded' : 'not_loaded';
  if (typeof item.loaded === 'boolean') return item.loaded ? 'loaded' : 'not_loaded';
  return undefined;
}
function capabilityInvocationState(item: ToolRecord): string | undefined {
  if (typeof item.invocationCount === 'number') return item.invocationCount > 0 ? 'invoked' : 'not_invoked';
  if (item.lastInvocationReceipt !== undefined) return item.lastInvocationReceipt ? 'invoked' : 'not_invoked';
  return undefined;
}
function capabilityRevocationState(item: ToolRecord): string | undefined {
  if (typeof item.revocationState === 'string') return item.revocationState;
  if (item.revocationReceipt !== undefined) return item.revocationReceipt ? 'revoked' : 'not_revoked';
  if (typeof item.revoked === 'boolean') return item.revoked ? 'revoked' : 'not_revoked';
  return undefined;
}

function itemKey(item: ToolRecord): string { return stringValue(item.id, stringValue(item.displayName)); }
function publicToolName(item: ToolRecord): string { const value = stringValue(item.displayName).trim(); return value && value.length <= 64 && !/pathId|schema|receipt|operation|policy|profile|\/api\/|https?:\/\//i.test(value) ? value : `${domainLabel(item)}工具`; }
function publicToolDescription(item: ToolRecord): string { const value = stringValue(item.description).trim(); return value && value.length <= 180 && /[\u3400-\u9fff]/u.test(value) && !/pathId|schema|receipt|operation|policy|profile|\/api\/|https?:\/\//i.test(value) ? value : `用于${domainLabel(item)}相关工作。`; }
function domainLabel(item: ToolRecord): string { return domainLabels[stringValue(item.domain, stringValue(item.category))] ?? '其他工具'; }
function stringArray(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }
function operationLabelsFor(item: ToolRecord): string[] { return stringArray(item.operations).map((operation) => operationLabels[operation]).filter((operation): operation is string => Boolean(operation)); }
function modeLabel(mode: string): string { if (mode === 'assistant') return '日常对话'; if (mode === 'coordinator') return '运行协调'; return '其他方式'; }
function availabilityBadge(item: ToolRecord): { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' } { switch (stringValue(item.availability).toLowerCase()) { case 'online': return { label: '当前可用', tone: 'success' }; case 'unconfigured': return { label: '待配置', tone: 'warning' }; case 'disabled': return { label: '已停用', tone: 'neutral' }; case 'offline': return { label: '暂时离线', tone: 'danger' }; default: return { label: '状态未知', tone: 'warning' }; } }
function availabilityDescription(item: ToolRecord): string { switch (stringValue(item.availability).toLowerCase()) { case 'online': return '已连接，可以在支持的场景中使用'; case 'unconfigured': return '需要先完成相关服务配置'; case 'disabled': return '当前已停用，不会被 Agent 调用'; case 'offline': return '连接暂时不可用，请稍后刷新'; default: return '尚未取得可靠的可用状态'; } }
function confirmationLabel(riskLevel: string): string { if (riskLevel === 'R0') return '只读能力可以直接使用'; if (riskLevel === 'R1') return '更改内容前会先请你确认'; if (riskLevel === 'R2') return '涉及本机操作，需要你明确授权'; return '敏感操作会额外说明影响并再次确认'; }
function pluginActionLabel(action: string): string { if (action === 'install') return '安装插件'; if (action === 'update') return '更新插件'; if (action === 'enable') return '启用插件'; if (action === 'disable') return '停用插件'; if (action === 'rollback') return '回滚插件'; return '变更插件'; }
function catalogStateBadge(item: ToolRecord): { label: string; tone: 'success' | 'warning' | 'neutral' } { if (item.updateAvailable === true) return { label: '有更新', tone: 'warning' }; if (item.installed === true) return { label: '已是最新', tone: 'success' }; if (item.actionable === true) return { label: '可安装', tone: 'neutral' }; return { label: '仅供审阅', tone: 'neutral' }; }
function lifecycleEventLabel(value: string): string { return ({ session_start: '会话开始', turn_end: '轮次结束', compaction: '上下文压缩', project_complete: '项目完成', tool_failed: '工具失败', idle: '进入空闲' } as Record<string, string>)[value] ?? value; }
function lifecycleActionLabel(value: string): string { return ({ audit_only: '仅审计', context_checkpoint: '下一轮上下文检查点', memory_review_suggestion: '下一轮记忆复盘建议' } as Record<string, string>)[value] ?? value; }
function cooldownLabel(seconds: number): string { if (!seconds) return '无冷却'; if (seconds >= 60) return `${Math.round(seconds / 60)} 分钟冷却`; return `${seconds} 秒冷却`; }
function lifecycleStatusBadge(item: ToolRecord): { label: string; tone: 'success' | 'warning' | 'neutral' } { const status = stringValue(item.status); if (status === 'suggested') return { label: '待下一轮复盘', tone: 'warning' }; if (status === 'recorded') return { label: '已记录', tone: 'success' }; if (status === 'skipped') return { label: '无事实已跳过', tone: 'neutral' }; if (status === 'cooldown') return { label: '冷却中', tone: 'neutral' }; return { label: status === 'disabled' ? '策略停用' : status, tone: 'neutral' }; }
function errorMessage(error: unknown): string { return publicErrorText(error, '插件操作失败，请稍后重试。'); }
function asError(error: unknown): Error | null { return error instanceof Error ? error : error ? new Error('暂时无法读取这部分内容。') : null; }
function firstError(...errors: unknown[]): Error | null { return errors.map(asError).find((error): error is Error => Boolean(error)) ?? null; }
function shortDigest(value: string): string { return value.length > 16 ? `${value.slice(0, 12)}…${value.slice(-4)}` : value; }
