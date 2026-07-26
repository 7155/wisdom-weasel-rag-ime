import {
  Activity,
  AppWindow,
  Camera,
  Check,
  Clipboard,
  Eye,
  Globe2,
  KeyRound,
  MonitorCog,
  MousePointer2,
  Octagon,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  SquareArrowOutUpRight,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  EmptyState,
  IconButton,
  SegmentedControl,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/primitives';
import {
  InlineNotice,
  ManagementPage,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  stringValue,
} from '@/features/overview/management-ui';
import { useProductIdentity } from '@/features/identity/product-identity';
import { useBrowserControl } from './api';
import './browser.css';

type BrowserMode = 'observe' | 'codrive' | 'managed';
type BrowserView = 'copilot' | 'permissions' | 'traces' | 'setup';

const modeItems = [
  { label: '只读观察', value: 'observe' },
  { label: '协同操作', value: 'codrive' },
  { label: '托管执行', value: 'managed' },
] as const;

const modeCopy: Record<BrowserMode, string> = {
  observe: 'Agent 只能读取按需快照，不能操作页面。',
  codrive: '页面操作先在对话中确认，并保留完整执行轨迹。',
  managed: '操作优先发送到隔离的托管 Chrome，不接管你的日常窗口。',
};

export function BrowserFeature() {
  const identity = useProductIdentity();
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [selectedTabId, setSelectedTabId] = useState(0);
  const [view, setView] = useState<BrowserView>('copilot');
  const control = useBrowserControl(selectedDeviceId, selectedTabId);
  const status = asRecord(control.status.data);
  const pairing = asRecord(control.pairing.data);
  const tabs = arrayRecords(asRecord(control.tabs.data).items);
  const snapshot = asRecord(control.snapshot.data);
  const permissions = arrayRecords(asRecord(control.permissions.data).items);
  const traces = arrayRecords(asRecord(control.traces.data).items);
  const clients = arrayRecords(status.clients);
  const mode = (stringValue(status.mode, 'observe') as BrowserMode);
  const connectedCount = clients.filter((client) => client.connected === true).length;
  const pendingPermissions = permissions.filter((item) => stringValue(item.status) === 'pending');
  const managed = asRecord(status.managedBrowser);
  const selectedTab = tabs.find(
    (item) => stringValue(item.deviceId) === selectedDeviceId && Number(item.tabId) === selectedTabId,
  );
  const pageSnapshot = Object.keys(snapshot).length ? snapshot : asRecord(status.latestSnapshot);
  const snapshotId = stringValue(pageSnapshot.snapshotId);
  const screenshotUrl = pageSnapshot.hasScreenshot === true && snapshotId
    ? control.snapshotImageUrl(snapshotId)
    : '';

  useEffect(() => {
    if (!tabs.length) return;
    const stillExists = tabs.some(
      (item) => stringValue(item.deviceId) === selectedDeviceId && Number(item.tabId) === selectedTabId,
    );
    if (stillExists) return;
    setSelectedDeviceId(stringValue(tabs[0].deviceId));
    setSelectedTabId(Number(tabs[0].tabId || 0));
  }, [selectedDeviceId, selectedTabId, tabs]);

  const refresh = () => {
    void Promise.all([
      control.status.refetch(),
      control.tabs.refetch(),
      control.snapshot.refetch(),
      control.permissions.refetch(),
      control.traces.refetch(),
    ]);
  };
  const runningMutation = (
    control.setMode.isPending
    || control.runCommand.isPending
    || control.stop.isPending
    || control.startManaged.isPending
    || control.stopManaged.isPending
  );

  return (
    <ManagementPage
      actions={(
        <>
          <IconButton icon={<RefreshCw size={16} />} label="刷新浏览器状态" onClick={refresh} tooltip />
          <Button
            disabled={!selectedTabId || runningMutation}
            leadingIcon={<Camera size={15} />}
            loading={control.runCommand.isPending}
            onClick={() => void control.runCommand.mutateAsync({
              action: 'screenshot',
              deviceId: selectedDeviceId,
              tabId: selectedTabId,
              timeoutSeconds: 20,
            })}
            size="small"
          >
            获取截图
          </Button>
          <Button
            disabled={runningMutation}
            leadingIcon={<Octagon size={15} />}
            onClick={() => void control.stop.mutateAsync()}
            size="small"
            variant="quiet"
          >
            停止
          </Button>
        </>
      )}
      description="让伙伴在你允许的范围内查看网页、截图和操作。你的日常浏览器与托管浏览器始终分开。"
      eyebrow="一起看网页"
      routeId="browser"
      title="浏览器"
    >
      <QueryState
        error={control.status.error as Error | null}
        isPending={control.status.isPending}
        onRetry={refresh}
      >
        <div className="browser-modebar">
          <div className="browser-modebar__status">
            <StatusBadge
              label={connectedCount ? `${connectedCount} 个浏览器在线` : '等待插件连接'}
              tone={connectedCount ? 'success' : 'warning'}
            />
            <span>{modeCopy[mode]}</span>
          </div>
          <SegmentedControl
            aria-label="浏览器操作方式"
            items={modeItems}
            onValueChange={(next) => void control.setMode.mutateAsync(next as BrowserMode)}
            value={mode}
          />
        </div>

        <Tabs className="browser-tabs" onValueChange={(next) => setView(next as BrowserView)} value={view}>
          <TabsList>
            <TabsTrigger value="copilot"><MousePointer2 size={14} />协作</TabsTrigger>
            <TabsTrigger value="permissions"><ShieldCheck size={14} />权限{pendingPermissions.length ? ` ${pendingPermissions.length}` : ''}</TabsTrigger>
            <TabsTrigger value="traces"><Activity size={14} />轨迹</TabsTrigger>
            <TabsTrigger value="setup"><MonitorCog size={14} />连接</TabsTrigger>
          </TabsList>

          <TabsContent value="copilot">
            <div className="browser-workbench">
              <BrowserRail
                clients={clients}
                productName={identity.productName}
                onSelect={(deviceId, tabId) => {
                  setSelectedDeviceId(deviceId);
                  setSelectedTabId(tabId);
                }}
                selectedDeviceId={selectedDeviceId}
                selectedTabId={selectedTabId}
                tabs={tabs}
              />
              <PageWorkspace
                isPending={control.snapshot.isFetching}
                selectedTab={selectedTab}
                snapshot={pageSnapshot}
                screenshotUrl={screenshotUrl}
              />
            </div>
          </TabsContent>

          <TabsContent value="permissions">
            <PermissionsView
              isPending={control.decidePermission.isPending}
              items={permissions}
              onDecision={(promptId, decision) => void control.decidePermission.mutateAsync({ promptId, decision })}
            />
          </TabsContent>

          <TabsContent value="traces">
            <TraceView items={traces} />
          </TabsContent>

          <TabsContent value="setup">
            <SetupView
              control={control}
              managed={managed}
              pairing={pairing}
            />
          </TabsContent>
        </Tabs>
      </QueryState>
    </ManagementPage>
  );
}

function BrowserRail({
  clients,
  onSelect,
  productName,
  selectedDeviceId,
  selectedTabId,
  tabs,
}: {
  clients: Record<string, unknown>[];
  onSelect: (deviceId: string, tabId: number) => void;
  productName: string;
  selectedDeviceId: string;
  selectedTabId: number;
  tabs: Record<string, unknown>[];
}) {
  return (
    <aside className="browser-rail" aria-label="浏览器与标签页">
      <header><strong>浏览器</strong><span>{clients.length}</span></header>
      {clients.length ? clients.map((client) => {
        const deviceId = stringValue(client.deviceId);
        const deviceTabs = tabs.filter((item) => stringValue(item.deviceId) === deviceId);
        return (
          <section key={deviceId}>
            <div className="browser-device">
              <AppWindow aria-hidden="true" size={16} />
              <span><strong>{stringValue(client.displayName, 'Chrome')}</strong><small>{client.connected === true ? '已连接' : '已离线'}</small></span>
              <i data-online={client.connected === true || undefined} />
            </div>
            <div className="browser-tab-list">
              {deviceTabs.map((tab) => {
                const tabId = Number(tab.tabId || 0);
                const selected = deviceId === selectedDeviceId && tabId === selectedTabId;
                return (
                  <button
                    aria-pressed={selected}
                    data-selected={selected || undefined}
                    key={`${deviceId}:${tabId}`}
                    onClick={() => onSelect(deviceId, tabId)}
                    type="button"
                  >
                    <Globe2 aria-hidden="true" size={14} />
                    <span><strong>{stringValue(tab.title, '未命名页面')}</strong><small>{hostname(stringValue(tab.url)) || '本地页面'}</small></span>
                  </button>
                );
              })}
            </div>
          </section>
        );
      }) : <EmptyState description={`在 Chrome 中加载并打开 ${productName} 浏览器助手。`} icon={AppWindow} title="尚未连接" />}
    </aside>
  );
}

function PageWorkspace({
  isPending,
  screenshotUrl,
  selectedTab,
  snapshot,
}: {
  isPending: boolean;
  screenshotUrl: string;
  selectedTab?: Record<string, unknown>;
  snapshot: Record<string, unknown>;
}) {
  const markdown = stringValue(snapshot.markdown);
  const lines = useMemo(() => markdown.split('\n').filter(Boolean).slice(0, 260), [markdown]);
  if (!selectedTab && !snapshot.snapshotId) {
    return <div className="browser-page-empty"><EmptyState description="选择左侧标签页后查看实时页面结构。" icon={Globe2} title="等待页面" /></div>;
  }
  return (
    <section className="browser-page-view">
      <header className="browser-page-view__header">
        <div>
          <span>{hostname(stringValue(snapshot.url || selectedTab?.url))}</span>
          <h2>{stringValue(snapshot.title || selectedTab?.title, '未命名页面')}</h2>
          <p>{stringValue(snapshot.url || selectedTab?.url)}</p>
        </div>
        <div className="browser-page-view__meta">
          <span>{Number(snapshot.interactiveCount || 0)} 个可交互元素</span>
          <span>{formatTime(Number(snapshot.createdAtMs || 0))}</span>
          {isPending ? <RefreshCw className="browser-spin" aria-label="正在同步" size={14} /> : <Check aria-label="已同步" size={14} />}
        </div>
      </header>
      <div className="browser-page-view__content">
        <figure className="browser-screenshot">
          <figcaption><Eye size={14} />页面视觉</figcaption>
          {screenshotUrl ? (
            <img alt={`浏览器页面截图：${stringValue(snapshot.title, '当前页面')}`} src={screenshotUrl} />
          ) : (
            <div className="browser-screenshot__empty">
              <Camera size={28} />
              <strong>尚未获取截图</strong>
              <span>点击页面右上角“获取截图”。</span>
            </div>
          )}
        </figure>
        <section className="browser-structure">
          <header><SquareArrowOutUpRight size={14} /><strong>结构化页面</strong><span>需要时提供给伙伴</span></header>
          {lines.length ? (
            <div className="browser-markdown" aria-label="结构化页面快照">
              {lines.map((line, index) => (
                <p data-kind={markdownLineKind(line)} key={`${index}:${line.slice(0, 40)}`}>{line}</p>
              ))}
            </div>
          ) : <EmptyState description="插件下一次同步后，这里会显示页面正文和元素引用。" icon={Eye} title="暂无结构快照" />}
        </section>
      </div>
    </section>
  );
}

function PermissionsView({
  isPending,
  items,
  onDecision,
}: {
  isPending: boolean;
  items: Record<string, unknown>[];
  onDecision: (promptId: string, decision: 'allow_once' | 'allow_site' | 'deny') => void;
}) {
  return (
    <section className="browser-list-view">
      <header><div><h2>页面权限</h2><p>跨站访问或高影响页面操作会在这里等待你的决定。</p></div><StatusBadge label={`${items.filter((item) => stringValue(item.status) === 'pending').length} 个待处理`} tone="neutral" /></header>
      {items.length ? (
        <div className="browser-permission-list">
          {items.map((item) => {
            const pending = stringValue(item.status) === 'pending';
            const promptId = stringValue(item.promptId);
            return (
              <article key={promptId}>
                <span className="browser-list-icon"><KeyRound size={16} /></span>
                <div><strong>{stringValue(item.origin, '未知站点')}</strong><span>{stringValue(item.reason, stringValue(item.action))}</span><small>{formatTime(Number(item.createdAtMs || 0))}</small></div>
                {pending ? (
                  <div className="browser-permission-actions">
                    <Button disabled={isPending} onClick={() => onDecision(promptId, 'deny')} size="small" variant="quiet">拒绝</Button>
                    <Button disabled={isPending} onClick={() => onDecision(promptId, 'allow_once')} size="small">仅本次</Button>
                    <Button disabled={isPending} onClick={() => onDecision(promptId, 'allow_site')} size="small" variant="primary">允许站点</Button>
                  </div>
                ) : <StatusBadge label={permissionDecisionLabel(stringValue(item.decision))} tone={stringValue(item.decision) === 'deny' ? 'danger' : 'success'} />}
              </article>
            );
          })}
        </div>
      ) : <EmptyState description="浏览器尚未请求额外站点权限。" icon={ShieldCheck} title="没有待处理权限" />}
    </section>
  );
}

function TraceView({ items }: { items: Record<string, unknown>[] }) {
  return (
    <section className="browser-list-view">
      <header><div><h2>执行轨迹</h2><p>每次 Agent 浏览、截图和页面操作都保留状态与耗时。</p></div><StatusBadge label={`${items.length} 条`} tone="neutral" /></header>
      {items.length ? (
        <div className="browser-trace-list">
          {items.map((item) => {
            const ok = stringValue(item.status) === 'completed';
            const result = asRecord(item.result);
            return (
              <article key={stringValue(item.commandId)}>
                <span className="browser-list-icon" data-ok={ok || undefined}>{ok ? <Check size={16} /> : <Activity size={16} />}</span>
                <div><strong>{actionLabel(stringValue(item.action))}</strong><span>{stringValue(result.summary, stringValue(item.failureReason, '等待浏览器返回'))}</span><small>{stringValue(item.commandId)}</small></div>
                <div className="browser-trace-meta"><StatusBadge label={statusLabel(stringValue(item.status))} tone={ok ? 'success' : stringValue(item.status) === 'failed' ? 'danger' : 'neutral'} /><span>{formatDuration(Number(item.durationMs || 0))}</span></div>
              </article>
            );
          })}
        </div>
      ) : <EmptyState description="Agent 调用浏览器工具后，轨迹会出现在这里。" icon={Activity} title="暂无执行轨迹" />}
    </section>
  );
}

function SetupView({
  control,
  managed,
  pairing,
}: {
  control: ReturnType<typeof useBrowserControl>;
  managed: Record<string, unknown>;
  pairing: Record<string, unknown>;
}) {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const token = stringValue(pairing.pairingToken);
  const copyToken = async () => {
    try {
      await copyText(token);
      setCopyState('copied');
      window.setTimeout(() => setCopyState('idle'), 1_600);
    } catch {
      setCopyState('error');
    }
  };
  return (
    <section className="browser-setup">
      <div className="browser-setup__section">
        <header><div><h2>Chrome 插件</h2><p>插件目录随产品安装，Chrome 首次需要手动加载一次。</p></div><StatusBadge label={token ? '凭据已生成' : '等待运行时'} tone={token ? 'success' : 'warning'} /></header>
        <dl>
          <div><dt>插件目录</dt><dd>{stringValue(pairing.extensionPath, '尚未安装')}</dd></div>
          <div><dt>桥接地址</dt><dd>{stringValue(pairing.bridgeUrl, '等待运行时')}</dd></div>
          <div><dt>凭据指纹</dt><dd>{stringValue(pairing.tokenFingerprint, '未生成')}</dd></div>
        </dl>
        <div className="browser-pairing-token">
          <label htmlFor="browser-pairing-token">配对凭据</label>
          <input id="browser-pairing-token" readOnly type="password" value={token} />
          <Button
            disabled={!token}
            leadingIcon={copyState === 'copied' ? <Check size={15} /> : <Clipboard size={15} />}
            onClick={() => void copyToken()}
            size="small"
          >
            {copyState === 'copied' ? '已复制' : '复制'}
          </Button>
          <IconButton
            icon={<RotateCcw size={15} />}
            label="轮换配对凭据"
            onClick={() => void control.rotatePairing.mutateAsync()}
            tooltip
          />
        </div>
        {copyState === 'error' ? (
          <InlineNotice title="复制失败" tone="warning">
            当前宿主没有授予剪贴板权限，请选中凭据后使用系统复制命令。
          </InlineNotice>
        ) : null}
        <InlineNotice title="加载方式" tone="info">
          在 Chrome 打开 chrome://extensions，启用开发者模式，然后加载上面的插件目录。
        </InlineNotice>
      </div>

      <div className="browser-setup__section">
        <header><div><h2>托管浏览器</h2><p>使用独立 Profile 和插件实例，适合未来角色主持的长时调研。</p></div><StatusBadge label={managed.running === true ? '运行中' : '已停止'} tone={managed.running === true ? 'success' : 'neutral'} /></header>
        <dl>
          <div><dt>隔离 Profile</dt><dd>{stringValue(managed.profilePath, '未创建')}</dd></div>
          <div><dt>进程</dt><dd>{managed.running === true ? `PID ${Number(managed.pid || 0)}` : '无'}</dd></div>
        </dl>
        <div className="browser-managed-actions">
          {managed.running === true ? (
            <Button leadingIcon={<Octagon size={15} />} loading={control.stopManaged.isPending} onClick={() => void control.stopManaged.mutateAsync()}>停止托管浏览器</Button>
          ) : (
            <Button leadingIcon={<AppWindow size={15} />} loading={control.startManaged.isPending} onClick={() => void control.startManaged.mutateAsync()} variant="primary">启动托管浏览器</Button>
          )}
        </div>
      </div>
    </section>
  );
}

function hostname(value: string): string {
  try {
    return new URL(value).hostname;
  } catch {
    return '';
  }
}

function markdownLineKind(line: string): string {
  if (line.startsWith('#')) return 'heading';
  if (line.startsWith('- [')) return 'interactive';
  if (line.startsWith('URL:')) return 'url';
  return 'text';
}

function formatTime(value: number): string {
  if (!value) return '暂无时间';
  return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDuration(value: number): string {
  if (!value) return '0 ms';
  return value < 1_000 ? `${value} ms` : `${(value / 1_000).toFixed(1)} s`;
}

function actionLabel(value: string): string {
  return {
    screenshot: '获取页面截图',
    snapshot: '读取页面快照',
    navigate: '打开网页',
    click: '点击页面元素',
    type: '输入页面文本',
    scroll: '滚动页面',
    wait: '等待页面内容',
  }[value] || value || '浏览器操作';
}

function statusLabel(value: string): string {
  return { queued: '排队中', claimed: '执行中', completed: '已完成', failed: '失败', cancelled: '已停止' }[value] || value;
}

function permissionDecisionLabel(value: string): string {
  return { allow_once: '已允许一次', allow_site: '已允许站点', deny: '已拒绝' }[value] || '已处理';
}

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // WKWebView may expose Clipboard API while denying it; use the local selection fallback.
    }
  }
  const field = document.createElement('textarea');
  field.value = value;
  field.setAttribute('readonly', '');
  field.style.position = 'fixed';
  field.style.opacity = '0';
  document.body.append(field);
  field.select();
  const copied = document.execCommand('copy');
  field.remove();
  if (!copied) throw new Error('clipboard unavailable');
}
