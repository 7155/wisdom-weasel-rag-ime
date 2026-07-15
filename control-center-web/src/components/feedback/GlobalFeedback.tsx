import { CircleAlert, CloudCog, Info, ShieldAlert, Wifi, WifiOff, X } from 'lucide-react';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { IconButton } from '@/components/primitives';

export type ConnectionState = 'connected' | 'connecting' | 'reconnecting' | 'degraded' | 'offline' | 'mock';
export type ConnectionSnapshot = {
  state: ConnectionState;
  label?: string;
  detail?: string;
};

export type GlobalNoticeTone = 'info' | 'warning' | 'danger';
export type GlobalNotice = {
  id: string;
  title: string;
  message?: string;
  tone: GlobalNoticeTone;
  dismissible?: boolean;
};

export const CONNECTION_EVENT = 'rag-ime-control:connection';
export const NOTICE_EVENT = 'rag-ime-control:notice';
export const DISMISS_NOTICE_EVENT = 'rag-ime-control:dismiss-notice';

type FeedbackContextValue = {
  connection: ConnectionSnapshot;
  notices: GlobalNotice[];
  dismissNotice: (id: string) => void;
  updateConnection: (snapshot: ConnectionSnapshot) => void;
};

const FeedbackContext = createContext<FeedbackContextValue | null>(null);

function initialConnection(): ConnectionSnapshot {
  if (typeof window === 'undefined') return { state: 'connecting' };
  if (!window.navigator.onLine) return { state: 'offline' };
  return document.documentElement.dataset.controlTransport === 'mock'
    ? { state: 'mock', label: '演示数据' }
    : { state: 'connecting' };
}

export function publishConnectionState(snapshot: ConnectionSnapshot): void {
  window.dispatchEvent(new CustomEvent<ConnectionSnapshot>(CONNECTION_EVENT, { detail: snapshot }));
}

export function publishGlobalNotice(notice: GlobalNotice): void {
  window.dispatchEvent(new CustomEvent<GlobalNotice>(NOTICE_EVENT, { detail: notice }));
}

export function dismissGlobalNotice(id: string): void {
  window.dispatchEvent(new CustomEvent<string>(DISMISS_NOTICE_EVENT, { detail: id }));
}

export function GlobalFeedbackProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<ConnectionSnapshot>(initialConnection);
  const [notices, setNotices] = useState<GlobalNotice[]>([]);
  const previousOnlineState = useRef<ConnectionSnapshot>(connection);

  const dismissNotice = useCallback((id: string) => {
    setNotices((current) => current.filter((notice) => notice.id !== id));
  }, []);
  const updateConnection = useCallback((snapshot: ConnectionSnapshot) => {
    previousOnlineState.current = snapshot;
    setConnection(snapshot);
  }, []);

  useEffect(() => {
    const onConnection = (event: Event) => {
      const snapshot = (event as CustomEvent<ConnectionSnapshot>).detail;
      updateConnection(snapshot);
    };
    const onNotice = (event: Event) => {
      const notice = (event as CustomEvent<GlobalNotice>).detail;
      setNotices((current) => [...current.filter((item) => item.id !== notice.id), notice].slice(-3));
    };
    const onDismiss = (event: Event) => dismissNotice((event as CustomEvent<string>).detail);
    const onOffline = () => setConnection({ state: 'offline', label: '网络不可用' });
    const onOnline = () => setConnection(previousOnlineState.current);

    window.addEventListener(CONNECTION_EVENT, onConnection);
    window.addEventListener(NOTICE_EVENT, onNotice);
    window.addEventListener(DISMISS_NOTICE_EVENT, onDismiss);
    window.addEventListener('offline', onOffline);
    window.addEventListener('online', onOnline);
    return () => {
      window.removeEventListener(CONNECTION_EVENT, onConnection);
      window.removeEventListener(NOTICE_EVENT, onNotice);
      window.removeEventListener(DISMISS_NOTICE_EVENT, onDismiss);
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('online', onOnline);
    };
  }, [dismissNotice, updateConnection]);

  const value = useMemo(
    () => ({ connection, notices, dismissNotice, updateConnection }),
    [connection, notices, dismissNotice, updateConnection],
  );

  return <FeedbackContext.Provider value={value}>{children}</FeedbackContext.Provider>;
}

export function useGlobalFeedback(): FeedbackContextValue {
  const context = useContext(FeedbackContext);
  if (!context) throw new Error('useGlobalFeedback must be used inside GlobalFeedbackProvider');
  return context;
}

const connectionCopy: Record<ConnectionState, string> = {
  connected: '已连接',
  connecting: '正在连接',
  reconnecting: '正在重连',
  degraded: '连接受限',
  offline: '离线',
  mock: '演示数据',
};

export function ConnectionIndicator() {
  const { connection } = useGlobalFeedback();
  const label = connection.label ?? connectionCopy[connection.state];
  const Icon = connection.state === 'offline'
    ? WifiOff
    : connection.state === 'connecting' || connection.state === 'reconnecting'
      ? CloudCog
      : Wifi;

  return (
    <div
      className="global-connection"
      data-state={connection.state}
      role="status"
      title={connection.detail}
    >
      <Icon size={14} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

const noticeIcons = {
  info: Info,
  warning: CircleAlert,
  danger: ShieldAlert,
} as const;

export function GlobalNoticeRegion() {
  const { dismissNotice, notices } = useGlobalFeedback();

  if (notices.length === 0) return null;

  return (
    <section className="global-notices" aria-label="全局通知" aria-live="polite">
      {notices.map((notice) => {
        const Icon = noticeIcons[notice.tone];
        return (
          <article className="global-notice" data-tone={notice.tone} key={notice.id}>
            <Icon className="global-notice__icon" size={17} aria-hidden="true" />
            <div className="global-notice__copy">
              <strong>{notice.title}</strong>
              {notice.message ? <span>{notice.message}</span> : null}
            </div>
            {notice.dismissible !== false ? (
              <IconButton
                icon={<X size={15} />}
                label={`关闭${notice.title}`}
                onClick={() => dismissNotice(notice.id)}
                size="small"
              />
            ) : null}
          </article>
        );
      })}
    </section>
  );
}
