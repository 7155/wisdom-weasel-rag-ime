export type BrowserRecord = Record<string, unknown>;

export type BrowserPageFailure = {
  code: number;
  description: string;
  url: string;
};

export type HostBrowserTab = {
  commandId?: string;
  crashedReason?: string;
  failure?: BrowserPageFailure | null;
  favicon?: string;
  id: string;
  loading?: boolean;
  canGoBack?: boolean;
  canGoForward?: boolean;
  title: string;
  url: string;
  webContentsId?: number;
};

export type BrowserElement = {
  refId: string;
  tag: string;
  role: string;
  label: string;
  inputType: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

export function record(value: unknown): BrowserRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as BrowserRecord : {};
}

export function rows(value: unknown): BrowserRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

export function text(value: unknown): string { return typeof value === 'string' ? value : ''; }

export function number(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

export function errorText(value: unknown): string {
  return value instanceof Error && value.message ? value.message : '本机浏览器服务没有返回结果。';
}

export function normalizedAddress(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed === 'about:blank') return trimmed;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (/^[\w.-]+\.[a-z]{2,}(?:\/.*)?$/i.test(trimmed)) return `https://${trimmed}`;
  return `https://www.google.com/search?q=${encodeURIComponent(trimmed)}`;
}

export type PawOmniboxIcon = 'search' | 'lock' | 'info';

export function omniboxIconKind(address: string, currentUrl: string): PawOmniboxIcon {
  const committed = currentUrl === 'about:blank' ? '' : currentUrl;
  if (address !== committed) return 'search';
  if (/^https:\/\//i.test(currentUrl)) return 'lock';
  if (/^http:\/\//i.test(currentUrl)) return 'info';
  return 'search';
}

export function omniboxIconTitle(kind: PawOmniboxIcon): string {
  if (kind === 'lock') return '连接已加密';
  if (kind === 'info') return '连接未加密';
  return '搜索或输入网址';
}

const knownFailLoadCodes: Record<string, string> = {
  '-7': '连接超时',
  '-100': '连接已关闭',
  '-101': '连接已重置',
  '-102': '连接被拒绝',
  '-105': '找不到这个网站',
  '-106': '网络已断开',
  '-109': '网站无法访问',
  '-118': '连接超时',
  '-137': '网站响应失败',
};

export function pageFailureText(failure: BrowserPageFailure): { title: string; detail: string } {
  const description = failure.description.trim();
  if (failure.code <= -200 && failure.code >= -299) {
    return { title: '网站证书无效或连接不安全', detail: description || `错误代码 ${failure.code}` };
  }
  const title = knownFailLoadCodes[failure.code];
  if (title) return { title, detail: description || `错误代码 ${failure.code}` };
  return { title: '页面没有打开', detail: description || `错误代码 ${failure.code}` };
}

export function crashReasonText(reason: string): string {
  return ({
    'clean-exit': '页面进程已正常退出',
    'abnormal-exit': '页面进程异常退出',
    killed: '页面进程被系统结束',
    crashed: '页面渲染进程崩溃',
    oom: '页面内存不足',
    'launch-failed': '页面进程启动失败',
    'integrity-failure': '页面进程完整性校验失败',
  } as Record<string, string>)[reason] ?? '页面进程已退出';
}

export function browserElement(value: BrowserRecord): BrowserElement | null {
  const refId = text(value.refId);
  const width = number(value.width);
  const height = number(value.height);
  if (!refId || width <= 0 || height <= 0) return null;
  return {
    refId,
    tag: text(value.tag),
    role: text(value.role),
    label: text(value.label),
    inputType: text(value.inputType),
    x: number(value.x),
    y: number(value.y),
    width,
    height,
  };
}

export function isTextEntry(element: BrowserElement): boolean {
  return element.tag === 'input'
    || element.tag === 'textarea'
    || element.tag === 'select'
    || element.role === 'textbox'
    || element.role === 'searchbox';
}

export function historyTime(value: number): string {
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(value);
}

export function historyDateTime(value: number): string {
  return new Date(value).toISOString();
}

export function historyDayKey(value: number): string {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function historyDayLabel(value: number, now = Date.now()): string {
  const key = historyDayKey(value);
  if (key === historyDayKey(now)) return '今天';
  if (key === historyDayKey(now - 86_400_000)) return '昨天';
  return new Intl.DateTimeFormat('zh-CN', { year: new Date(value).getFullYear() === new Date(now).getFullYear() ? undefined : 'numeric', month: 'long', day: 'numeric', weekday: 'short' }).format(value);
}

export function historyClock(value: number): string {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(value);
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function initialHostTab(): HostBrowserTab {
  return { id: 'paw-tab-1', title: '新标签页', url: 'about:blank' };
}

export function hostTab(url: string, commandId?: string): HostBrowserTab {
  const id = typeof crypto.randomUUID === 'function'
    ? `paw-tab-${crypto.randomUUID()}`
    : `paw-tab-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return { commandId, id, title: url === 'about:blank' ? '新标签页' : url, url };
}

export function knownCount(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return Math.floor(value);
  }
  return null;
}

export function browserActionLabel(action: string): string {
  return ({
    run: '执行网页任务',
    navigate: '打开页面',
    new_tab: '新建标签页',
    close_tab: '关闭标签页',
    reload: '刷新页面',
    back: '后退',
    forward: '前进',
    click: '点击',
    type: '输入',
    scroll: '滚动',
    wait: '等待页面',
    snapshot: '读取页面',
    screenshot: '截取页面',
    read_page: '读取页面',
    hover: '指向',
    drag: '拖动',
    press: '按键',
    select: '选择',
    check: '勾选',
    uncheck: '取消勾选',
    upload: '上传文件',
    switch_tab: '切换标签页',
    task_space: '进入任务空间',
    task_complete: '完成任务空间',
    hand_off: '交给你操作',
    take_over: '接管页面',
    wait_for_control: '等待接管',
  } as Record<string, string>)[action] ?? action;
}
