import {
  Activity,
  Bot,
  BookOpen,
  CircleAlert,
  Eye,
  Fingerprint,
  FolderCog,
  Gauge,
  History,
  Keyboard,
  LibraryBig,
  LoaderCircle,
  Mic2,
  Network,
  PackageCheck,
  PackageOpen,
  Palette,
  RefreshCw,
  Search,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { Button, EmptyState, Input, SegmentedControl, Switch } from '@/components/primitives';
import { ApprovalsFeature } from '@/features/approvals';
import {
  useAgentPreferencesAuthority,
  type AgentExecutionMode,
} from '@/features/agent/composer/agent-preferences-store';
import {
  parsePiModelCatalogOptions,
  supportedPiThinkingLevels,
} from '@/features/agent/model-catalog-options';
import { ConfigurationFeature } from '@/features/configuration';
import { PawOsAppearanceSettings } from '@/features/configuration/PawOsAppearanceSettings';
import { ContextDebugFeature } from '@/features/context-debug';
import { DiagnosticsFeature } from '@/features/diagnostics';
import { diagnosticsQueryKeys } from '@/features/diagnostics/api';
import { GovernanceFeature } from '@/features/governance';
import { HistoryFeature } from '@/features/history';
import { InputLexiconFeature, InputMethodFeature } from '@/features/input-method';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import { PluginsFeature } from '@/features/plugins';
import { pluginQueryKeys, usePluginCatalog } from '@/features/plugins/api';
import { ObservabilityFeature } from '@/features/observability';
import { VoiceFeature } from '@/features/voice';
import type { PawAppId } from '../runtime/app-registry';
import { pawApp } from '../runtime/app-registry';

export const pawSystemAppIds = [
  'input-studio',
  'app-center',
  'system-monitor',
  'system-settings',
] as const;

export type PawSystemAppId = (typeof pawSystemAppIds)[number];

type SystemPage = {
  id: string;
  label: string;
  icon: LucideIcon;
  route: string;
  group?: string;
};

const systemPages: Record<PawSystemAppId, readonly SystemPage[]> = {
  'input-studio': [
    { id: 'input', label: '输入法', icon: Keyboard, route: '/input' },
    { id: 'lexicon', label: '词库', icon: BookOpen, route: '/input?view=lexicon' },
    { id: 'voice', label: '语音', icon: Mic2, route: '/voice' },
    { id: 'history', label: '输入记录', icon: History, route: '/history' },
  ],
  'app-center': [
    { id: 'installed', label: '已安装', icon: PackageOpen, route: '/plugins' },
    { id: 'catalog', label: '目录', icon: LibraryBig, route: '/plugins?view=catalog' },
    { id: 'proposals', label: '建议', icon: Sparkles, route: '/plugins?view=proposals' },
  ],
  'system-monitor': [
    { id: 'activity', label: '活动', icon: Activity, route: '/observability', group: '实时' },
    { id: 'context', label: '上下文', icon: Network, route: '/context-debug', group: '排查' },
    { id: 'diagnostics', label: '诊断', icon: Gauge, route: '/diagnostics', group: '排查' },
  ],
  'system-settings': [
    { id: 'configuration', label: '配置', icon: Settings2, route: '/configuration', group: '通用' },
    { id: 'appearance', label: '外观', icon: Palette, route: '/appearance', group: '通用' },
    { id: 'agent', label: 'Agent', icon: Bot, route: '/configuration?view=agent', group: 'Agent' },
    { id: 'governance', label: '治理', icon: ShieldCheck, route: '/governance', group: '安全与信任' },
    { id: 'approvals', label: '审批', icon: Fingerprint, route: '/approvals', group: '安全与信任' },
  ],
};

export function isPawSystemAppId(appId: PawAppId): appId is PawSystemAppId {
  return (pawSystemAppIds as readonly string[]).includes(appId);
}

export type PawSystemAppsMigratedProps = {
  appId: PawSystemAppId;
  initialRoute?: string;
};

/**
 * Isolated PAWOS container for the four system-facing Apps.
 *
 * The container owns navigation and presentation only. Every page below keeps
 * its existing transport, guarded mutation, native bridge, and persisted state.
 */
export function PawSystemAppsMigrated({
  appId,
  initialRoute = '',
}: PawSystemAppsMigratedProps) {
  const pages = systemPages[appId];
  const app = pawApp(appId);
  const desktop = usePawOsDesktop();
  const route = initialRoute || app.route || pages[0].route;
  const page = systemPageForRoute(pages, route);
  const railSignals = usePawSystemRailSignals(appId);

  return (
    <div className="paw-system-app" data-page-id={page.id} data-system-app={appId}>
      <aside className="paw-system-app__nav">
        <nav aria-label={`${app.label}页面`}>
          {pages.map((candidate, index) => {
            const Icon = candidate.icon;
            const current = candidate.id === page.id;
            const signal = railSignals[candidate.id];
            const name = signal ? `${candidate.label}（${signal.detail}）` : candidate.label;
            return (
              <Fragment key={candidate.id}>
                {candidate.group && candidate.group !== pages[index - 1]?.group ? (
                  <span aria-hidden="true" className="paw-system-app__nav-group">{candidate.group}</span>
                ) : null}
                <button
                  aria-current={current ? 'page' : undefined}
                  aria-label={name}
                  onClick={() => openPawOsRoute(desktop, candidate.route)}
                  title={name}
                  type="button"
                >
                  <Icon aria-hidden="true" size={16} />
                  <span>{candidate.label}</span>
                  {signal ? (
                    <span aria-hidden="true" className="paw-system-app__nav-badge" data-tone={signal.tone}>
                      {signal.count > 99 ? '99+' : signal.count}
                    </span>
                  ) : null}
                </button>
              </Fragment>
            );
          })}
        </nav>
      </aside>

      <section className="paw-system-app__stage">
        <span aria-hidden="true" className="paw-system-app__page-title">
          {page.group ? `${page.group} · ${page.label}` : page.label}
        </span>
        <MemoryRouter initialEntries={[route]} key={route}>
          <PawSystemRouteReporter expectedRoute={route} />
          <div className="paw-system-app__page" key={`${appId}:${page.id}`}>
            <PawSystemSurface appId={appId} pageId={page.id} />
          </div>
        </MemoryRouter>
      </section>
    </div>
  );
}

type PawSystemRailSignal = {
  count: number;
  /** Spoken consequence, e.g. “2 项待处理”; joins the label in the button name. */
  detail: string;
  /** Filled accent = human decision queue; attention = red; quiet = outline. */
  tone?: 'attention' | 'quiet';
};

/**
 * Truthful rail signals. Every count is read from the route that owns the
 * underlying queue and shares that owner's query key, so deciding an approval,
 * confirming a proposal, or applying an update refreshes the rail without a
 * second request cycle. A route that fails or reports nothing keeps the rail
 * quiet instead of inventing a number.
 */
function usePawSystemRailSignals(appId: PawSystemAppId): Record<string, PawSystemRailSignal> {
  const transport = useControlTransport();
  const approvals = useQuery({
    queryKey: ['approvals', 'all'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.approvals.list',
      query: { limit: 500 },
      signal,
    }),
    enabled: appId === 'system-settings',
    refetchInterval: 60_000,
    retry: false,
  });
  const proposals = useQuery({
    queryKey: pluginQueryKeys.proposals(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.extensions.proposals', signal }),
    enabled: appId === 'app-center',
    refetchInterval: 60_000,
    retry: false,
  });
  const packageVersions = useQuery({
    queryKey: pluginQueryKeys.versions(),
    queryFn: ({ signal }) => transport.request({ pathId: 'agent.extensions.catalog', signal }),
    enabled: appId === 'app-center',
    refetchInterval: 60_000,
    retry: false,
    staleTime: 30_000,
  });
  const runtimeChecks = useQuery({
    queryKey: diagnosticsQueryKeys.runtime(),
    queryFn: ({ signal }) => transport.request({ pathId: 'diagnostics.runtime', signal }),
    enabled: appId === 'system-monitor',
    refetchInterval: 60_000,
    retry: false,
  });

  const signals: Record<string, PawSystemRailSignal> = {};
  if (appId === 'system-settings') {
    const pending = pendingApprovalCount(approvals.data);
    if (pending) signals.approvals = { count: pending, detail: `${pending} 项待处理` };
  }
  if (appId === 'app-center') {
    const pendingProposals = arrayRecords(asRecord(proposals.data).items).length;
    if (pendingProposals) signals.proposals = { count: pendingProposals, detail: `${pendingProposals} 项待确认` };
    const updates = packageUpdateCount(packageVersions.data);
    if (updates) signals.catalog = { count: updates, detail: `${updates} 个可更新`, tone: 'quiet' };
  }
  if (appId === 'system-monitor') {
    const failing = failingRuntimeCheckCount(runtimeChecks.data);
    if (failing) signals.diagnostics = { count: failing, detail: `${failing} 项需要检查`, tone: 'attention' };
  }
  return signals;
}

function PawSystemRouteReporter({ expectedRoute }: { expectedRoute: string }) {
  const desktop = usePawOsDesktop();
  const location = useLocation();
  const route = `${location.pathname}${location.search}${location.hash}`;
  useEffect(() => {
    if (route !== expectedRoute) openPawOsRoute(desktop, route);
  }, [desktop, expectedRoute, route]);
  return null;
}

function PawSystemSurface({ appId, pageId }: { appId: PawSystemAppId; pageId: string }) {
  if (appId === 'input-studio') {
    if (pageId === 'lexicon') return <InputLexiconFeature />;
    if (pageId === 'voice') return <VoiceFeature />;
    if (pageId === 'history') return <HistoryFeature />;
    return <InputMethodFeature />;
  }
  if (appId === 'app-center') {
    if (pageId === 'catalog') return <PawPackageCatalog />;
    return <PluginsFeature />;
  }
  if (appId === 'system-monitor') {
    if (pageId === 'context') return <ContextDebugFeature />;
    if (pageId === 'diagnostics') return <DiagnosticsFeature />;
    return <ObservabilityFeature />;
  }
  if (pageId === 'agent') return <PawAgentSettings />;
  if (pageId === 'appearance') return <PawAppearanceSettings />;
  if (pageId === 'governance') return <GovernanceFeature />;
  if (pageId === 'approvals') return <ApprovalsFeature />;
  return <ConfigurationFeature />;
}

function PawAppearanceSettings() {
  return (
    <ManagementPage
      description="桌面主题、界面动效与 App 身份色。"
      routeId="appearance"
      title="外观"
    >
      <PawOsAppearanceSettings />
    </ManagementPage>
  );
}

/**
 * Execution permission as four honest positions, not a dropdown of jargon.
 * Whatever is chosen, R2/R3 operations still stop at the approvals desk.
 */
const agentExecutionModes: readonly {
  value: AgentExecutionMode;
  title: string;
  detail: string;
  icon: LucideIcon;
  recommended?: boolean;
}[] = [
  { value: 'per_action', title: '按风险确认', detail: '低风险直接做；高风险先停在审批中心问你。', icon: ShieldCheck, recommended: true },
  { value: 'read_only', title: '只读', detail: '只查看、只回答，不改动文件和设置。', icon: Eye },
  { value: 'workspace_managed', title: '工作区托管', detail: '在授权的工作区里自己安排；越界的操作仍会先问你。', icon: FolderCog },
  { value: 'full_trust', title: '全自动', detail: '不再逐项确认，只受本机保护规则约束。', icon: Zap },
];

function PawAgentSettings() {
  const resource = useAgentModelResource();
  const authority = useAgentPreferencesAuthority();
  const preferences = authority.preferences;
  const catalog = parsePiModelCatalogOptions(resource.data);
  const selectedModel = catalog.models.find((model) => model.reference === preferences.modelReference);
  const thinkingLevels = supportedPiThinkingLevels(selectedModel, { includeOff: true });
  const controlsDisabled = authority.saving || Boolean(authority.readError);

  function selectModel(reference: string): void {
    const model = catalog.models.find((candidate) => candidate.reference === reference);
    const levels = supportedPiThinkingLevels(model, { includeOff: true });
    void authority.save({
      modelReference: reference,
      thinking: levels.includes(preferences.thinking) ? preferences.thinking : levels[0] ?? 'off',
    });
  }

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={resource.loading || authority.isPending} onClick={() => { resource.reload(); authority.reload(); }} size="small">刷新</Button>}
      description="决定每个新对话默认用哪个模型、想多深、动手之前要不要先问你。改动只影响之后开始的对话。"
      eyebrow="新对话的起点"
      routeId="agent-settings"
      title="Agent"
    >
      {resource.error ? (
        <div className="paw-system-resource-state" data-state="error" role="alert">
          <CircleAlert aria-hidden="true" size={17} />
          <span>{resource.error}</span>
          <button onClick={resource.reload} type="button">重试</button>
        </div>
      ) : null}
      {authority.readError ? (
        <div className="paw-system-resource-state" data-state="error" role="alert">
          <CircleAlert aria-hidden="true" size={17} />
          <span>{authority.readError}</span>
          <button onClick={authority.reload} type="button">重新读取</button>
        </div>
      ) : null}
      {resource.loading || authority.isPending ? (
        <div className="paw-system-resource-state" data-state="loading" role="status"><LoaderCircle aria-hidden="true" size={17} />正在读取 Agent 默认设置</div>
      ) : (
        <>
          <ManagementSection
            description="清单来自 Runtime 的真实报告，不会显示不可用的选项。"
            title="用哪个模型，想多深"
          >
            <div className="paw-agent-model">
              <label className="paw-agent-model__field">
                <span>模型</span>
                <select aria-label="Agent 模型" disabled={controlsDisabled} onChange={(event) => selectModel(event.target.value)} value={preferences.modelReference}>
                  <option value="">自动选择</option>
                  {catalog.models.map((model) => <option key={model.reference} value={model.reference}>{model.name} · {model.provider}</option>)}
                </select>
                <small>{catalog.models.length ? `${catalog.models.length} 个可用模型` : 'Runtime 没有报告可用模型'}</small>
              </label>
              <div className="paw-agent-model__thinking">
                <span>推理强度</span>
                {selectedModel && thinkingLevels.length ? (
                  <>
                    <SegmentedControl
                      aria-label="Agent 推理强度"
                      disabled={controlsDisabled}
                      items={thinkingLevels.map((level) => ({ value: level, label: thinkingLabel(level) }))}
                      onValueChange={(level) => { void authority.save({ thinking: level }); }}
                      value={thinkingLevels.includes(preferences.thinking) ? preferences.thinking : thinkingLevels[0]}
                    />
                    <small>只显示当前模型明确支持的档位</small>
                  </>
                ) : (
                  <small>选择具体模型后，这里会列出它支持的档位。</small>
                )}
              </div>
            </div>
          </ManagementSection>

          <ManagementSection
            description="无论选哪一档，高风险操作都会先停在审批中心，逐项问过你。"
            title="动手之前，问不问你"
          >
            <div aria-label="Agent 执行权限" className="paw-agent-modes" role="radiogroup">
              {agentExecutionModes.map((mode) => {
                const Icon = mode.icon;
                return (
                  <label className="paw-agent-mode" key={mode.value}>
                    <input
                      aria-label={mode.title}
                      checked={preferences.executionMode === mode.value}
                      disabled={controlsDisabled}
                      name="paw-agent-execution-mode"
                      onChange={() => { void authority.save({ executionMode: mode.value }); }}
                      type="radio"
                      value={mode.value}
                    />
                    <span aria-hidden="true" className="paw-agent-mode__icon"><Icon size={16} /></span>
                    <span className="paw-agent-mode__copy">
                      <strong>{mode.title}{mode.recommended ? <em>推荐</em> : null}</strong>
                      <small>{mode.detail}</small>
                    </span>
                  </label>
                );
              })}
            </div>
          </ManagementSection>
        </>
      )}
      {!authority.isPending && !authority.writesSupported ? (
        <InlineNotice title="当前版本只能读取 Agent 默认设置" tone="warning">本机服务尚未开放安全保存接口；页面不会保留仅存在于前端的修改。</InlineNotice>
      ) : null}
      {authority.saving ? <InlineNotice title="正在保存" tone="info">写入本机设置后会立即重新读取确认。</InlineNotice> : null}
      {authority.saveError ? <InlineNotice title="Agent 默认设置没有保存" tone="danger">{authority.saveError}</InlineNotice> : null}
    </ManagementPage>
  );
}

function PawPackageCatalog() {
  const {
    apply,
    installed,
    preview,
    validate,
    versions,
  } = usePluginCatalog();
  const [query, setQuery] = useState('');
  const [enableAfterInstall, setEnableAfterInstall] = useState(true);
  const [pendingChange, setPendingChange] = useState<Record<string, unknown>>({});
  const [validation, setValidation] = useState<Record<string, unknown>>({});
  const [error, setError] = useState('');
  const versionItems = arrayRecords(asRecord(versions.data).items);
  const installedEnvelope = asRecord(installed.data);
  const runtimeAvailable = installedEnvelope.runtimeAvailable !== false;
  const filteredItems = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    if (!needle) return versionItems;
    return versionItems.filter((item) => [
      stringValue(item.displayName),
      stringValue(item.id),
      stringValue(item.description),
      stringValue(asRecord(item.source).label),
    ].join(' ').toLocaleLowerCase('zh-CN').includes(needle));
  }, [query, versionItems]);
  const pendingSummary = asRecord(pendingChange.summary);
  const busy = validate.isPending || preview.isPending || apply.isPending;
  const queryError = asError(versions.error ?? installed.error);

  async function previewCatalogAction(item: Record<string, unknown>): Promise<void> {
    setError('');
    setValidation({});
    setPendingChange({});
    try {
      const checked = asRecord(await validate.mutateAsync({
        catalogId: stringValue(item.id),
        catalogVersion: stringValue(item.latestVersion),
      }));
      const next = asRecord(await preview.mutateAsync({
        action: item.updateAvailable === true ? 'update' : 'install',
        validationToken: stringValue(checked.validationToken),
        enable: item.installed === true ? item.enabled === true : enableAfterInstall,
      }));
      setValidation(checked);
      setPendingChange(next);
    } catch (catalogError) {
      setError(publicErrorText(catalogError, 'Package 检查没有完成。'));
    }
  }

  async function applyPendingChange(): Promise<void> {
    setError('');
    try {
      await apply.mutateAsync({
        previewToken: stringValue(pendingChange.previewToken),
        payloadSha256: stringValue(pendingChange.payloadSha256),
        confirmText: 'apply',
      });
      setPendingChange({});
      setValidation({});
      await Promise.all([versions.refetch(), installed.refetch()]);
    } catch (catalogError) {
      setError(publicErrorText(catalogError, 'Package 更改没有完成。'));
    }
  }

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={versions.isFetching || installed.isFetching} onClick={() => void Promise.all([versions.refetch(), installed.refetch()])} size="small">刷新</Button>}
      description="每个 Package 先亮出来源、权限和版本；你确认之前，不会安装或更改任何内容。"
      eyebrow="先看清，再安装"
      routeId="plugins-catalog"
      title="Package 目录"
    >
      <QueryState error={queryError} isPending={versions.isPending || installed.isPending} onRetry={() => void Promise.all([versions.refetch(), installed.refetch()])}>
        <ManagementSection
          description="只列出 Runtime 真正注册的 Package，为空就是真的没有。安装或更新都先经过来源检查和内容预览，你确认之前本机不会有任何改动。"
          title="可以安装或更新什么"
          trailing={<StatusBadge label={`${filteredItems.length} 项`} tone="neutral" />}
        >
          {!runtimeAvailable ? <InlineNotice title="Pi Runtime 暂时未连接" tone="warning">目录仍可阅读，但安装和更新要等 Runtime 恢复后再继续。</InlineNotice> : null}
          <div className="paw-system-catalog-tools">
            <label><Search aria-hidden="true" size={15} /><Input aria-label="搜索 Package 目录" onChange={(event) => setQuery(event.target.value)} placeholder="名称、用途或来源" value={query} /></label>
            <Switch checked={enableAfterInstall} label="安装后立即启用" onCheckedChange={setEnableAfterInstall} />
          </div>

          {filteredItems.length ? (
            <div className="paw-system-package-grid" aria-label="受管 Package 目录">
              {filteredItems.map((item) => {
                const id = stringValue(item.id);
                const source = asRecord(item.source);
                const security = asRecord(item.security);
                const permissions = stringArray(item.permissions);
                const actionable = item.actionable === true;
                const upToDate = item.installed === true && item.updateAvailable !== true;
                return (
                  <article className="paw-system-package" key={id}>
                    <header>
                      <span><PackageOpen aria-hidden="true" size={18} /></span>
                      <div><strong>{stringValue(item.displayName, id)}</strong><small>v{stringValue(item.latestVersion, '未声明')} · {stringValue(source.label, stringValue(item.publisher, '来源未声明'))}</small></div>
                      <StatusBadge {...packageCatalogBadge(item)} />
                    </header>
                    <p>{stringValue(item.description, '这个 Package 没有提供说明。')}</p>
                    <dl>
                      <div><dt><ShieldCheck aria-hidden="true" size={13} />权限</dt><dd>{permissions.length ? permissions.join('、') : '无额外权限'}</dd></div>
                      <div><dt><ShieldAlert aria-hidden="true" size={13} />检查</dt><dd>{stringValue(security.notes, '尚无安全说明')}</dd></div>
                    </dl>
                    <footer>
                      <span>{arrayRecords(item.versions).length} 个版本</span>
                      <Button
                        disabled={!runtimeAvailable || !actionable || upToDate || busy}
                        leadingIcon={<PackageCheck size={14} />}
                        loading={(validate.isPending || preview.isPending) && stringValue(validate.variables?.catalogId) === id}
                        onClick={() => void previewCatalogAction(item)}
                        size="small"
                      >
                        {item.updateAvailable === true ? '查看更新内容' : upToDate ? '已安装' : actionable ? '查看安装内容' : '不可安装'}
                      </Button>
                    </footer>
                  </article>
                );
              })}
            </div>
          ) : <EmptyState description={versionItems.length ? '换一个关键词试试。' : 'Runtime 没有返回可安装或可更新的 Package。'} icon={PackageOpen} title={versionItems.length ? '没有匹配的 Package' : '目录为空'} />}

          {validation.validationToken && pendingChange.previewToken ? (
            <InlineNotice title="等待你的确认" tone="warning">
              <div className="paw-system-package-approval">
                <span>
                  <strong>{packageActionLabel(stringValue(pendingSummary.action))}：{stringValue(pendingSummary.displayName, stringValue(pendingSummary.pluginId))}</strong>
                  <small>
                    {stringValue(pendingSummary.version) ? `v${stringValue(pendingSummary.version)} · ` : ''}
                    {stringArray(pendingSummary.permissions).length ? `需要的权限：${stringArray(pendingSummary.permissions).join('、')}` : '无额外权限'}
                    {' · 确认后才会写入本机'}
                  </small>
                </span>
                <div><Button disabled={busy} onClick={() => { setPendingChange({}); setValidation({}); }} size="small" variant="quiet">取消</Button><Button disabled={busy} loading={apply.isPending} onClick={() => void applyPendingChange()} size="small" variant="primary">确认更改</Button></div>
              </div>
            </InlineNotice>
          ) : null}
          {error ? <InlineNotice title="Package 操作未完成" tone="danger">{error}</InlineNotice> : null}
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function useAgentModelResource() {
  const transport = useControlTransport();
  const [data, setData] = useState<Record<string, unknown>>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((current) => current + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void transport.request({ pathId: 'agent.role.models' }).then((response) => {
      if (!active) return;
      setData(asRecord(response));
      setError('');
    }).catch((resourceError) => {
      if (active) setError(publicErrorText(resourceError, '模型目录读取失败。'));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [revision, transport]);

  return { data, error, loading, reload };
}

function pendingApprovalCount(value: unknown): number {
  const items = asRecord(value).items;
  if (!Array.isArray(items)) return 0;
  return items.filter((item) => {
    const approval = asRecord(item);
    return approval.schemaVersion === 'rag-ime.agent-approval.v1' && approval.state === 'pending';
  }).length;
}

function packageUpdateCount(value: unknown): number {
  return arrayRecords(asRecord(value).items)
    .filter((item) => item.updateAvailable === true).length;
}

/**
 * Only components that explicitly report ok=false count as Monitor attention;
 * a missing or unknown report never becomes an invented warning.
 */
function failingRuntimeCheckCount(value: unknown): number {
  return Object.values(asRecord(asRecord(value).components))
    .filter((component) => asRecord(component).ok === false).length;
}

function systemPageForRoute(pages: readonly SystemPage[], route: string): SystemPage {
  const exact = pages.find((page) => page.route === route);
  if (exact) return exact;
  const view = new URLSearchParams(route.split('?', 2)[1] ?? '').get('view');
  if (view) {
    const byView = pages.find((page) => page.id === view);
    if (byView) return byView;
  }
  const path = route.split('?', 1)[0];
  return pages.find((page) => page.route.split('?', 1)[0] === path) ?? pages[0];
}

function thinkingLabel(value: string): string {
  return ({ off: '关闭', minimal: '极低', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高' } as Record<string, string>)[value] ?? value;
}

function packageCatalogBadge(item: Record<string, unknown>): { label: string; tone: 'success' | 'warning' | 'neutral' } {
  if (item.updateAvailable === true) return { label: '有更新', tone: 'warning' };
  if (item.installed === true) return { label: '已安装', tone: 'success' };
  return { label: item.actionable === true ? '可安装' : '仅供审阅', tone: 'neutral' };
}

function packageActionLabel(action: string): string {
  if (action === 'install') return '安装 Package';
  if (action === 'update') return '更新 Package';
  return '更改 Package';
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function asError(error: unknown): Error | null {
  return error instanceof Error ? error : error ? new Error('暂时无法读取这部分内容。') : null;
}
