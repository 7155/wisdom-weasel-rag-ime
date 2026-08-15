import { useEffect } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { useGlobalFeedback } from '@/components/feedback';

const CONNECTION_PROBE_INTERVAL_MS = 30_000;

export function ControlConnectionMonitor() {
  const transport = useControlTransport();
  const { updateConnection } = useGlobalFeedback();

  useEffect(() => {
    if (transport.kind === 'mock') {
      updateConnection({ state: 'mock', label: '演示数据' });
      return;
    }

    let active = true;
    let timer: ReturnType<typeof globalThis.setTimeout> | undefined;

    const schedule = () => {
      timer = globalThis.setTimeout(() => void probe(false), CONNECTION_PROBE_INTERVAL_MS);
    };
    const probe = async (announce: boolean) => {
      if (announce) updateConnection({ state: 'connecting' });
      try {
        await transport.capabilities();
        if (!active) return;
        updateConnection({
          state: 'connected',
          label: '已连接',
          detail: transport.kind === 'native' ? '本机原生控制通道可用' : '本机 HTTP 控制通道可用',
        });
      } catch (error) {
        if (!active) return;
        const offline = !window.navigator.onLine;
        updateConnection({
          state: offline ? 'offline' : 'degraded',
          label: offline ? '离线' : '连接受限',
          detail: publicConnectionError(error),
        });
      } finally {
        if (active) schedule();
      }
    };
    const reconnect = () => void probe(true);

    void probe(true);
    window.addEventListener('online', reconnect);
    return () => {
      active = false;
      if (timer !== undefined) globalThis.clearTimeout(timer);
      window.removeEventListener('online', reconnect);
    };
  }, [transport, updateConnection]);

  return null;
}

function publicConnectionError(_error: unknown): string {
  return '暂时无法连接本机控制服务';
}
