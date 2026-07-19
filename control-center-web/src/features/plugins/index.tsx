import {
  Boxes,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FolderOpen,
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
  rollback_settings: '撤销输入设置', room_ask: '向协作成员提问', room_mailbox: '查看协作消息', room_reply: '回复协作消息',
  room_send: '发送协作消息', route_status: '检查检索连接', run: '运行受控命令', search: '搜索内容',
  status: '查看当前状态', task_action: '更新任务', trace: '查看来源链路', undo_task_event: '撤销任务更新',
  tabs: '查看浏览器标签页', snapshot: '读取页面快照', screenshot: '获取页面截图', navigate: '打开网页',
  click: '点击页面元素', type: '向页面输入', scroll: '滚动页面', wait: '等待页面内容', stop: '停止浏览器操作',
};

export function PluginsFeature() {
  const navigate = useNavigate();
  const { catalog, installed, versions, proposals, lifecycle, validate, preview, apply, updateLifecycle, transport } = usePluginCatalog();
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<ModeFilter>('all');
  const [availability, setAvailability] = useState<AvailabilityFilter>('all');
  const [selectedId, setSelectedId] = useState('');
  const [pluginSource, setPluginSource] = useState('');
  const [pluginSourceName, setPluginSourceName] = useState('');
  const [enableAfterInstall, setEnableAfterInstall] = useState(true);
  const [validation, setValidation] = useState<Record<string, unknown>>({});
  const [pendingChange, setPendingChange] = useState<Record<string, unknown>>({});
  const [lifecycleError, setLifecycleError] = useState('');
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
  const categories = new Set(items.map(domainLabel).filter(Boolean));
  const confirmationCount = items.filter((item) => stringValue(item.riskLevel, 'R0') !== 'R0').length;
  const installedItems = arrayRecords(asRecord(installed.data).items);
  const proposalItems = arrayRecords(asRecord(proposals.data).items);
  const versionItems = arrayRecords(asRecord(versions.data).items);
  const lifecyclePolicies = arrayRecords(asRecord(lifecycle.data).policies);
  const lifecycleEvents = arrayRecords(asRecord(lifecycle.data).recentEvents);
  const extension = asRecord(validation.extension);
  const pendingSummary = asRecord(pendingChange.summary);
  const lifecyclePending = validate.isPending || preview.isPending || apply.isPending;

  const choosePluginSource = async () => {
    setLifecycleError('');
    if (!transport.pickFiles) {
      setLifecycleError('当前平台不支持选择插件目录。');
      return;
    }
    try {
      const selected = await transport.pickFiles({ purpose: 'plugin-source', selection: 'directory', maxFiles: 1 });
      const source = selected[0];
      if (!source?.path) return;
      setPluginSource(source.path);
      setPluginSourceName(source.name);
      setValidation({});
      setPendingChange({});
    } catch (error) {
      setLifecycleError(errorMessage(error));
    }
  };

  const validatePlugin = async () => {
    setLifecycleError('');
    try {
      setValidation(asRecord(await validate.mutateAsync({ sourcePath: pluginSource })));
      setPendingChange({});
    } catch (error) {
      setLifecycleError(errorMessage(error));
    }
  };

  const previewInstall = async () => {
    setLifecycleError('');
    try {
      setPendingChange(asRecord(await preview.mutateAsync({
        action: 'install',
        validationToken: stringValue(validation.validationToken),
        enable: enableAfterInstall,
      })));
    } catch (error) {
      setLifecycleError(errorMessage(error));
    }
  };

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
      setPluginSource('');
      setPluginSourceName('');
    } catch (error) {
      setLifecycleError(errorMessage(error));
    }
  };
  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={catalog.isFetching} onClick={() => void catalog.refetch()} size="small">刷新</Button>}
      description="查看已经连接到本机 Agent 的工具，以及它们适合的使用方式。"
      eyebrow="TOOLS"
      routeId="plugins"
      title="插件与工具"
    >
      <QueryState error={catalog.error as Error | null} isPending={catalog.isPending} onRetry={() => void catalog.refetch()}>
        <ManagementSection title="目录状态">
          <MetricStrip items={[
            { label: '工具', value: items.length, detail: '已连接', icon: Wrench },
            { label: '可用', value: items.filter((item) => stringValue(item.availability) === 'online').length, detail: '现在可以使用', icon: CheckCircle2, tone: 'success' },
            { label: '分类', value: categories.size, detail: '覆盖的工作领域', icon: Boxes },
            { label: '需确认', value: confirmationCount, detail: '执行更改前会询问你', icon: ShieldCheck, tone: confirmationCount ? 'warning' : 'neutral' },
          ]} />
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

        <ManagementSection
          description="第一方版本来自产品内置目录。目录只负责发现，安装和更新仍必须经过校验、摘要绑定预览和你的明确批准。"
          title="插件版本中心"
          trailing={<StatusBadge label={`${installedItems.length} 个已安装`} tone="neutral" />}
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
                      <span><ShieldCheck size={14} />{stringArray(item.permissions).join('、') || '无需额外权限'}</span>
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
              <span><strong>让 Agent 制作插件</strong><small>插件制作 Skill 会先确认用途和权限，再生成草稿、校验并提交安装提议。</small></span>
              <Button
                leadingIcon={<MessageCircle size={16} />}
                onClick={() => navigate({
                  pathname: '/agent',
                  search: new URLSearchParams({
                    draft: '/skill:rag-ime-plugin-creator 帮我创建一个受管插件。先询问用途和权限边界，再生成草稿、完成校验并提交安装提议；不要绕过控制中心的最终批准。',
                  }).toString(),
                })}
              >交给 Agent 制作</Button>
            </div>
            <div className="plugin-lifecycle__install">
              <div className="plugin-lifecycle__source">
                <Button disabled={lifecyclePending} leadingIcon={<FolderOpen size={16} />} onClick={() => void choosePluginSource()}>选择插件目录</Button>
                <span>{pluginSourceName || '尚未选择'}</span>
              </div>
              <Switch checked={enableAfterInstall} label="安装后启用" onCheckedChange={setEnableAfterInstall} />
              <div className="plugin-lifecycle__steps">
                <Button disabled={!pluginSource || lifecyclePending} leadingIcon={<ShieldCheck size={16} />} loading={validate.isPending} onClick={() => void validatePlugin()} size="small">校验</Button>
                <Button disabled={!validation.validationToken || lifecyclePending} leadingIcon={<PackageCheck size={16} />} loading={preview.isPending} onClick={() => void previewInstall()} size="small">生成安装预览</Button>
              </div>
              {extension.id ? (
                <div className="plugin-lifecycle__validation">
                  <strong>{stringValue(extension.displayName, stringValue(extension.id))}</strong>
                  <span>v{stringValue(extension.version)} · {Number(extension.totalBytes || 0).toLocaleString()} bytes</span>
                  <StatusBadge label="校验通过" tone="success" />
                </div>
              ) : null}
            </div>

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
                  <span>{pluginActionLabel(stringValue(pendingSummary.action))}：{stringValue(pendingSummary.displayName, stringValue(pendingSummary.pluginId))}</span>
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
        </ManagementSection>

        <ManagementSection
          description="Hook 只记录事实和生成下一轮可消费的复盘建议，不会直接写入长期记忆，也不会扩大工具、Plan、Goal 或审批权限。"
          title="生命周期自动化"
          trailing={<StatusBadge label={`${lifecyclePolicies.filter((item) => item.enabled === true).length}/${lifecyclePolicies.length} 已启用`} tone="neutral" />}
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
                    label={policy.enabled === true ? '已启用' : '已停用'}
                    onCheckedChange={(enabled) => void updateLifecycle.mutateAsync({ eventType: stringValue(policy.eventType), enabled })}
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
          </div>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function ToolDetail({ item, onClose }: { item: ToolRecord; onClose: () => void }) {
  const operations = operationLabelsFor(item); const modes = stringArray(item.sessionModes); const unknownOperationCount = Math.max(0, stringArray(item.operations).length - operations.length);
  return <aside aria-label="工具详情" className="plugins-detail"><div className="plugins-detail__toolbar"><span>工具详情</span><IconButton icon={<PanelRightClose size={16} />} label="关闭工具详情" onClick={onClose} tooltip /></div><div className="plugins-detail__heading"><span className="plugins-detail__icon"><Wrench aria-hidden="true" size={18} /></span><div><small>{domainLabel(item)}</small><h3>{publicToolName(item)}</h3><p>{publicToolDescription(item)}</p></div><StatusBadge {...availabilityBadge(item)} /></div><dl className="plugins-detail__facts"><div><dt><CheckCircle2 aria-hidden="true" size={15} />当前状态</dt><dd>{availabilityDescription(item)}</dd></div><div><dt><MessageCircle aria-hidden="true" size={15} />可用方式</dt><dd>{modes.length ? modes.map(modeLabel).join('、') : '暂无可用方式'}</dd></div><div><dt><ShieldCheck aria-hidden="true" size={15} />操作确认</dt><dd>{confirmationLabel(stringValue(item.riskLevel, 'R0'))}</dd></div></dl><div className="plugins-detail__capabilities"><h4>可以做什么</h4>{operations.length || unknownOperationCount ? <ul>{operations.map((operation) => <li key={operation}>{operation}</li>)}{unknownOperationCount ? <li>其他 {unknownOperationCount} 项能力</li> : null}</ul> : <p>目录中尚未提供能力说明。</p>}</div></aside>;
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
function errorMessage(error: unknown): string { return error instanceof Error ? error.message : '插件操作失败。'; }
