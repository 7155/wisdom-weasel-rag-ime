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

type BrowserReceiptArea = 'global' | 'permissions' | 'pairing' | 'managed';
type BrowserReceiptState = 'pending' | 'confirmed' | 'waiting' | 'error';
type BrowserActionReceipt = {
  area: BrowserReceiptArea;
  detail: string;
  state: BrowserReceiptState;
  title: string;
};
type BrowserActionRequest = {
  area: BrowserReceiptArea;
  confirmed: (response: Record<string, unknown>) => boolean;
  confirmedDetail: string;
  label: string;
  request: () => Promise<unknown>;
  waitingDetail: string;
};

const modeItems = [
  { label: '只读观察', value: 'observe' },
  { label: '协同操作', value: 'codrive' },
  { label: '托管执行', value: 'managed' },
] as const;

const modeCopy: Record<BrowserMode, string> = {
  observe: '伙伴只能按需读取页面内容，不能操作页面。',
  codrive: '敏感操作会在对话中征求你的同意，并保留完整记录。',
  managed: '操作优先发送到隔离的托管 Chrome，不接管你的日常窗口。',
};

export function BrowserFeature() {
  const identity = useProductIdentity();
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [selectedTabId, setSelectedTabId] = useState(0);
  const [view, setView] = useState<BrowserView>('copilot');
  const [actionReceipt, setActionReceipt] = useState<BrowserActionReceipt | null>(null);
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
  const shellHasData = control.status.data !== undefined || control.permissions.data !== undefined;
  const shellPending = !shellHasData && (control.status.isPending || control.permissions.isPending);
  const shellError = !shellHasData && !shellPending
    ? (control.status.error ?? control.permissions.error) as Error | null
    : null;
  const statusUnavailable = control.status.data === undefined && control.permissions.data !== undefined;
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
      control.pairing.refetch(),
      control.tabs.refetch(),
      control.snapshot.refetch(),
      control.permissions.refetch(),
      control.traces.refetch(),
    ]);
  };
  const performBrowserAction = async ({
    area,
    confirmed,
    confirmedDetail,
    label,
    request,
    waitingDetail,
  }: BrowserActionRequest) => {
    setActionReceipt({
      area,
      detail: '正在把请求交给浏览器服务；页面不会提前改变状态。',
      state: 'pending',
      title: `正在${label}`,
    });
    try {
      const response = asRecord(await request());
      if (response.ok === false) {
        setActionReceipt({
          area,
          detail: '浏览器服务没有接受这次请求；当前页面状态没有改变。请刷新状态后再试。',
          state: 'error',
          title: `${label}未被接受`,
        });
        return;
      }
      const didConfirm = confirmed(response);
      setActionReceipt({
        area,
        detail: didConfirm ? confirmedDetail : waitingDetail,
        state: didConfirm ? 'confirmed' : 'waiting',
        title: didConfirm ? `${label}已确认` : `${label}请求已送达，等待确认`,
      });
    } catch {
      setActionReceipt({
        area,
        detail: '请求未完成；当前页面状态没有改变。请刷新状态后重试。',
        state: 'error',
        title: `${label}失败`,
      });
    }
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
            onClick={() => void performBrowserAction({
              area: 'global',
              confirmed: (response) => Boolean(
                stringValue(response.snapshotId)
                || response.hasScreenshot === true
                || ['completed', 'succeeded'].includes(stringValue(response.status)),
              ),
              confirmedDetail: '浏览器已返回截图回执，最新页面快照正在刷新。',
              label: '获取截图',
              request: () => control.runCommand.mutateAsync({
                action: 'screenshot',
                deviceId: selectedDeviceId,
                tabId: selectedTabId,
                timeoutSeconds: 20,
              }),
              waitingDetail: '请求已送达，但浏览器尚未返回截图回执；当前图片或占位提示保持不变。',
            })}
            size="small"
          >
            获取截图
          </Button>
          <Button
            disabled={runningMutation}
            leadingIcon={<Octagon size={15} />}
            onClick={() => void performBrowserAction({
              area: 'global',
              confirmed: (response) => (
                response.stopped === true
                || response.running === false
                || ['stopped', 'completed'].includes(stringValue(response.status))
              ),
              confirmedDetail: '浏览器已确认停止；在线状态正在刷新。',
              label: '停止浏览器',
              request: () => control.stop.mutateAsync(),
              waitingDetail: '停止请求已送达，但浏览器仍未确认停止；在线状态保持不变。',
            })}
            size="small"
            variant="quiet"
          >
            停止
          </Button>
        </>
      )}
      description="让伙伴在你允许的范围内查看网页、截图和操作。你的日常浏览器与托管浏览器始终分开。"
      eyebrow="一起看网页"
      layout="workbench"
      routeId="browser"
      title="浏览器"
    >
      <QueryState
        error={shellError}
        isPending={shellPending}
        onRetry={refresh}
      >
        <div className="browser-modebar">
          <div className="browser-modebar__status">
            <StatusBadge
              label={connectedCount ? `${connectedCount} 个浏览器在线` : '等待插件连接'}
              tone={connectedCount ? 'success' : 'warning'}
            />
            <span>{statusUnavailable ? '浏览器状态正在恢复，权限请求仍可处理。' : modeCopy[mode]}</span>
          </div>
          <SegmentedControl
            aria-label="浏览器操作方式"
            items={modeItems}
            onValueChange={(next) => void performBrowserAction({
              area: 'global',
              confirmed: (response) => stringValue(response.mode) === next,
              confirmedDetail: `浏览器已确认切换为“${modeItems.find((item) => item.value === next)?.label ?? '所选方式'}”。`,
              label: '切换浏览器操作方式',
              request: () => control.setMode.mutateAsync(next as BrowserMode),
              waitingDetail: '切换请求已送达，但浏览器仍未确认新方式；当前选中项保持不变。',
            })}
            value={mode}
          />
          <BrowserActionNotice receipt={actionReceipt?.area === 'global' ? actionReceipt : null} />
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
                error={control.tabs.error as Error | null}
                isRefreshing={control.tabs.isFetching}
                productName={identity.productName}
                onSelect={(deviceId, tabId) => {
                  setSelectedDeviceId(deviceId);
                  setSelectedTabId(tabId);
                }}
                onRetry={() => void control.tabs.refetch()}
                selectedDeviceId={selectedDeviceId}
                selectedTabId={selectedTabId}
                tabs={tabs}
              />
              <PageWorkspace
                error={control.snapshot.error as Error | null}
                isPending={control.snapshot.isFetching}
                onRetry={() => void control.snapshot.refetch()}
                selectedTab={selectedTab}
                snapshot={pageSnapshot}
                screenshotUrl={screenshotUrl}
              />
            </div>
          </TabsContent>

          <TabsContent value="permissions">
            <PermissionsView
              decisionPending={control.decidePermission.isPending}
              error={control.permissions.error as Error | null}
              isRefreshing={control.permissions.isFetching}
              items={permissions}
              onDecision={(promptId, decision) => void performBrowserAction({
                area: 'permissions',
                confirmed: (response) => (
                  stringValue(response.promptId) === promptId
                  && stringValue(response.decision) === decision
                ),
                confirmedDetail: '浏览器已记录这次权限决定，待处理列表正在刷新。',
                label: ({ allow_once: '允许一次', allow_site: '允许站点', deny: '拒绝权限' } as const)[decision],
                request: () => control.decidePermission.mutateAsync({ promptId, decision }),
                waitingDetail: '决定已送达，但浏览器尚未返回匹配回执；该请求仍显示为待处理。',
              })}
              onRetry={() => void control.permissions.refetch()}
              receipt={actionReceipt?.area === 'permissions' ? actionReceipt : null}
            />
          </TabsContent>

          <TabsContent value="traces">
            <TraceView
              error={control.traces.error as Error | null}
              isRefreshing={control.traces.isFetching}
              items={traces}
              onRetry={() => void control.traces.refetch()}
            />
          </TabsContent>

          <TabsContent value="setup">
            <SetupView
              control={control}
              managed={managed}
              onRotatePairing={() => void performBrowserAction({
                area: 'pairing',
                confirmed: (response) => (
                  (Boolean(stringValue(response.pairingToken)) && stringValue(response.pairingToken) !== stringValue(pairing.pairingToken))
                  || (Boolean(stringValue(response.tokenFingerprint)) && stringValue(response.tokenFingerprint) !== stringValue(pairing.tokenFingerprint))
                ),
                confirmedDetail: '新的配对码已生成；只把它复制给正在配对的本机插件。',
                label: '更换配对码',
                request: () => control.rotatePairing.mutateAsync(),
                waitingDetail: '更换请求已送达，但浏览器尚未返回新的配对信息；现有配对码仍可使用。',
              })}
              onStartManaged={() => void performBrowserAction({
                area: 'managed',
                confirmed: (response) => response.running === true || stringValue(response.status) === 'running',
                confirmedDetail: '浏览器已确认托管进程启动；进程状态正在刷新。',
                label: '启动托管浏览器',
                request: () => control.startManaged.mutateAsync(),
                waitingDetail: '启动请求已送达，但浏览器仍未报告进程；页面继续显示“已停止”。',
              })}
              onStopManaged={() => void performBrowserAction({
                area: 'managed',
                confirmed: (response) => response.running === false || stringValue(response.status) === 'stopped',
                confirmedDetail: '浏览器已确认托管进程停止；进程状态正在刷新。',
                label: '停止托管浏览器',
                request: () => control.stopManaged.mutateAsync(),
                waitingDetail: '停止请求已送达，但浏览器尚未确认进程退出；当前运行状态保持不变。',
              })}
              onRetryPairing={() => void control.pairing.refetch()}
              pairingError={control.pairing.error as Error | null}
              pairingPending={control.rotatePairing.isPending}
              pairingRefreshing={control.pairing.isFetching}
              pairing={pairing}
              receipt={actionReceipt && ['pairing', 'managed'].includes(actionReceipt.area) ? actionReceipt : null}
            />
          </TabsContent>
        </Tabs>
      </QueryState>
    </ManagementPage>
  );
}

function BrowserRail({
  clients,
  error,
  isRefreshing,
  onSelect,
  onRetry,
  productName,
  selectedDeviceId,
  selectedTabId,
  tabs,
}: {
  clients: Record<string, unknown>[];
  error: Error | null;
  isRefreshing: boolean;
  onSelect: (deviceId: string, tabId: number) => void;
  onRetry: () => void;
  productName: string;
  selectedDeviceId: string;
  selectedTabId: number;
  tabs: Record<string, unknown>[];
}) {
  return (
    <aside className="browser-rail" aria-label="浏览器与标签页">
      <header><strong>浏览器</strong><span>{clients.length}</span></header>
      <BrowserQueryIssue
        actionLabel="重新加载标签页"
        description="浏览器连接状态仍然可见。重新加载后再选择需要查看的页面。"
        error={error}
        isRefreshing={isRefreshing}
        onRetry={onRetry}
        title="标签页暂时未同步"
      />
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
  error,
  isPending,
  onRetry,
  screenshotUrl,
  selectedTab,
  snapshot,
}: {
  error: Error | null;
  isPending: boolean;
  onRetry: () => void;
  screenshotUrl: string;
  selectedTab?: Record<string, unknown>;
  snapshot: Record<string, unknown>;
}) {
  const markdown = stringValue(snapshot.markdown);
  const lines = useMemo(() => markdown.split('\n').filter(Boolean).slice(0, 260), [markdown]);
  if (!selectedTab && !snapshot.snapshotId) {
    return (
      <div className="browser-page-empty">
        <BrowserQueryIssue
          actionLabel="重新加载页面快照"
          description="重新加载只会读取当前页面，不会执行点击、输入或跳转。"
          error={error}
          isRefreshing={isPending}
          onRetry={onRetry}
          title="页面快照暂时未同步"
        />
        {!error ? <EmptyState description="选择左侧标签页后查看实时页面结构。" icon={Globe2} title="等待页面" /> : null}
      </div>
    );
  }
  return (
    <section className="browser-page-view" data-query-error={Boolean(error) || undefined}>
      <BrowserQueryIssue
        actionLabel="重新加载页面快照"
        description="上一次加载的页面内容仍可查看。重新加载只会读取当前页面，不会执行操作。"
        error={error}
        isRefreshing={isPending}
        onRetry={onRetry}
        title="页面快照未更新"
      />
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
  decisionPending,
  error,
  isRefreshing,
  items,
  onDecision,
  onRetry,
  receipt,
}: {
  decisionPending: boolean;
  error: Error | null;
  isRefreshing: boolean;
  items: Record<string, unknown>[];
  onDecision: (promptId: string, decision: 'allow_once' | 'allow_site' | 'deny') => void;
  onRetry: () => void;
  receipt: BrowserActionReceipt | null;
}) {
  return (
    <section className="browser-list-view">
      <header><div><h2>页面权限</h2><p>跨站访问或高影响页面操作会在这里等待你的决定。</p></div><StatusBadge label={error ? '状态未知' : `${items.filter((item) => stringValue(item.status) === 'pending').length} 个待处理`} tone={error ? 'warning' : 'neutral'} /></header>
      <BrowserQueryIssue
        actionLabel="重新加载权限请求"
        description="当前列表可能不是最新状态。重新加载只会读取权限请求，不会替你作出决定。"
        error={error}
        isRefreshing={isRefreshing}
        onRetry={onRetry}
        title="权限请求未同步"
      />
      <BrowserActionNotice receipt={receipt} />
      {items.length ? (
        <div className="browser-permission-list">
          {items.map((item) => {
            const pending = stringValue(item.status) === 'pending';
            const promptId = stringValue(item.promptId);
            return (
              <article key={promptId}>
                <span className="browser-list-icon"><KeyRound size={16} /></span>
                <div><strong>{stringValue(item.origin, '未知站点')}</strong><span>{permissionReasonLabel(stringValue(item.action))}</span><small>{formatTime(Number(item.createdAtMs || 0))}</small></div>
                {pending ? (
                  <div className="browser-permission-actions">
                    <Button disabled={decisionPending} onClick={() => onDecision(promptId, 'deny')} size="small" variant="quiet">拒绝</Button>
                    <Button disabled={decisionPending} onClick={() => onDecision(promptId, 'allow_once')} size="small">仅本次</Button>
                    <Button disabled={decisionPending} onClick={() => onDecision(promptId, 'allow_site')} size="small" variant="primary">允许站点</Button>
                  </div>
                ) : <StatusBadge label={permissionDecisionLabel(stringValue(item.decision))} tone={stringValue(item.decision) === 'deny' ? 'danger' : 'success'} />}
              </article>
            );
          })}
        </div>
      ) : error ? null : <EmptyState description="浏览器尚未请求额外站点权限。" icon={ShieldCheck} title="没有待处理权限" />}
    </section>
  );
}

function TraceView({
  error,
  isRefreshing,
  items,
  onRetry,
}: {
  error: Error | null;
  isRefreshing: boolean;
  items: Record<string, unknown>[];
  onRetry: () => void;
}) {
  return (
    <section className="browser-list-view">
      <header><div><h2>执行轨迹</h2><p>伙伴查看网页、获取截图和操作页面时，都会留下状态与耗时。</p></div><StatusBadge label={error ? '状态未知' : `${items.length} 条`} tone={error ? 'warning' : 'neutral'} /></header>
      <BrowserQueryIssue
        actionLabel="重新加载执行轨迹"
        description="已经加载的记录仍可查看。重新加载只会读取最新执行记录。"
        error={error}
        isRefreshing={isRefreshing}
        onRetry={onRetry}
        title="执行轨迹未同步"
      />
      {items.length ? (
        <div className="browser-trace-list">
          {items.map((item) => {
            const ok = stringValue(item.status) === 'completed';
            const result = asRecord(item.result);
            return (
              <article key={stringValue(item.commandId)}>
                <span className="browser-list-icon" data-ok={ok || undefined}>{ok ? <Check size={16} /> : <Activity size={16} />}</span>
                <div><strong>{actionLabel(stringValue(item.action))}</strong><span>{stringValue(result.summary, stringValue(item.failureReason, '等待浏览器返回'))}</span><small>已记录本次操作</small></div>
                <div className="browser-trace-meta"><StatusBadge label={statusLabel(stringValue(item.status))} tone={ok ? 'success' : stringValue(item.status) === 'failed' ? 'danger' : 'neutral'} /><span>{formatDuration(Number(item.durationMs || 0))}</span></div>
              </article>
            );
          })}
        </div>
      ) : error ? null : <EmptyState description="伙伴使用浏览器后，相关记录会出现在这里。" icon={Activity} title="暂无执行轨迹" />}
    </section>
  );
}

function SetupView({
  control,
  managed,
  onRotatePairing,
  onRetryPairing,
  onStartManaged,
  onStopManaged,
  pairingError,
  pairingPending,
  pairingRefreshing,
  pairing,
  receipt,
}: {
  control: ReturnType<typeof useBrowserControl>;
  managed: Record<string, unknown>;
  onRotatePairing: () => void;
  onRetryPairing: () => void;
  onStartManaged: () => void;
  onStopManaged: () => void;
  pairingError: Error | null;
  pairingPending: boolean;
  pairingRefreshing: boolean;
  pairing: Record<string, unknown>;
  receipt: BrowserActionReceipt | null;
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
        <header><div><h2>连接 Chrome</h2><p>首次使用时，在 Chrome 中加载浏览器助手即可连接。</p></div><StatusBadge label={pairingError ? '状态未知' : token ? '配对码已生成' : '等待连接'} tone={token && !pairingError ? 'success' : 'warning'} /></header>
        <BrowserQueryIssue
          actionLabel="重新加载配对信息"
          description="浏览器连接和托管浏览器状态不受影响。重新加载只会读取本机配对信息。"
          error={pairingError}
          isRefreshing={pairingRefreshing}
          onRetry={onRetryPairing}
          title="配对信息未同步"
        />
        <dl>
          <div><dt>浏览器助手</dt><dd>{stringValue(pairing.extensionPath) ? '文件已就绪，等待在 Chrome 中加载' : '尚未安装'}</dd></div>
        </dl>
        <details className="browser-setup__advanced-details">
          <summary>高级连接详情</summary>
          <dl>
            <div><dt>浏览器助手文件</dt><dd>{stringValue(pairing.extensionPath, '尚未安装')}</dd></div>
            <div><dt>本机连接地址</dt><dd>{stringValue(pairing.bridgeUrl, '等待本机服务')}</dd></div>
            <div><dt>配对状态标识</dt><dd>{stringValue(pairing.tokenFingerprint, '未生成')}</dd></div>
          </dl>
        </details>
        <div className="browser-pairing-token">
          <label htmlFor="browser-pairing-token">配对码</label>
          <input aria-describedby="browser-pairing-guidance" autoComplete="off" id="browser-pairing-token" readOnly type="password" value={token} />
          <Button
            disabled={!token}
            leadingIcon={copyState === 'copied' ? <Check size={15} /> : <Clipboard size={15} />}
            onClick={() => void copyToken()}
            size="small"
          >
            {copyState === 'copied' ? '已复制' : '复制'}
          </Button>
          <IconButton
            disabled={pairingPending}
            icon={<RotateCcw size={15} />}
            label="更换配对码"
            onClick={onRotatePairing}
            tooltip
          />
        </div>
        <p className="browser-pairing-guidance" id="browser-pairing-guidance">
          配对码只用于连接这台设备上的浏览器助手。默认隐藏；只复制给正在配对的本机插件，不再使用时请立即更换。
        </p>
        <BrowserActionNotice receipt={receipt?.area === 'pairing' ? receipt : null} />
        {copyState === 'error' ? (
          <InlineNotice title="复制失败" tone="warning">
            当前环境不能直接写入剪贴板，请选中配对码后使用系统复制命令。
          </InlineNotice>
        ) : null}
        <InlineNotice title="加载方式" tone="info">
          展开“高级连接详情”查看浏览器助手文件位置；然后在 Chrome 打开 chrome://extensions，启用开发者模式并加载该文件夹。
        </InlineNotice>
      </div>

      <div className="browser-setup__section">
        <header><div><h2>托管浏览器</h2><p>使用独立的浏览器资料和插件，与日常浏览分开，适合让伙伴进行较长时间的调研。</p></div><StatusBadge label={managed.running === true ? '运行中' : '已停止'} tone={managed.running === true ? 'success' : 'neutral'} /></header>
        <details className="browser-setup__advanced-details">
          <summary>高级运行详情</summary>
          <dl>
            <div><dt>独立浏览数据位置</dt><dd>{stringValue(managed.profilePath, '未创建')}</dd></div>
            <div><dt>运行进程编号</dt><dd>{managed.running === true ? String(Number(managed.pid || 0)) : '无'}</dd></div>
          </dl>
        </details>
        <div className="browser-managed-actions">
          {managed.running === true ? (
            <Button leadingIcon={<Octagon size={15} />} loading={control.stopManaged.isPending} onClick={onStopManaged}>停止托管浏览器</Button>
          ) : (
            <Button leadingIcon={<AppWindow size={15} />} loading={control.startManaged.isPending} onClick={onStartManaged} variant="primary">启动托管浏览器</Button>
          )}
        </div>
        <BrowserActionNotice receipt={receipt?.area === 'managed' ? receipt : null} />
      </div>
    </section>
  );
}

function BrowserActionNotice({ receipt }: { receipt: BrowserActionReceipt | null }) {
  if (!receipt) return null;
  const tone = {
    confirmed: 'success',
    error: 'danger',
    pending: 'info',
    waiting: 'warning',
  }[receipt.state] as 'success' | 'danger' | 'info' | 'warning';
  return (
    <div aria-live="polite" className="browser-action-receipt">
      <InlineNotice title={receipt.title} tone={tone}>{receipt.detail}</InlineNotice>
    </div>
  );
}

function BrowserQueryIssue({
  actionLabel,
  description,
  error,
  isRefreshing,
  onRetry,
  title,
}: {
  actionLabel: string;
  description: string;
  error: Error | null;
  isRefreshing: boolean;
  onRetry: () => void;
  title: string;
}) {
  if (!error) return null;
  return (
    <div className="browser-query-issue" role="alert">
      <div>
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <Button
        leadingIcon={<RefreshCw size={15} />}
        loading={isRefreshing}
        onClick={onRetry}
        size="small"
        variant="quiet"
      >
        {actionLabel}
      </Button>
    </div>
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

function permissionReasonLabel(action: string): string {
  return {
    navigate: '打开此站点',
    screenshot: '读取当前页面',
    click: '操作当前页面',
    type: '在当前页面输入内容',
  }[action] || '浏览器请求访问此站点';
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
