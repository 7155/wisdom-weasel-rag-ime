import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import { isModelCatalog } from '@/features/agent/types';
import { asRecord, stringValue } from '@/features/overview/management-ui';
import { usePageVisibility } from '@/platform/use-page-visibility';
import { PawWindowChromePortal } from '@/paw-os/shell/PawWindowChrome';
import './satellite-model-badge.css';

/** A model belongs to this exact Session, never its parent or the Room label. */
export function SatelliteModelBadge({ sessionId, inline = false }: { sessionId?: string; inline?: boolean }) {
  const transport = useControlTransport();
  const visible = usePageVisibility();
  const query = useQuery({
    queryKey: ['agent', 'satellite-model', sessionId],
    queryFn: async ({ signal }) => {
      const value = await transport.request({ pathId: 'agent.session.models', params: { sessionId: sessionId! }, signal });
      if (!isModelCatalog(value) || value.sessionId !== sessionId) return null;
      const selected = asRecord(value.selected);
      const id = stringValue(selected.id) || stringValue(selected.modelId);
      const provider = stringValue(selected.provider);
      if (!id || !provider) return null;
      const named = value.providers.find((item) => item.id === provider)?.models.find((item) => item.id === id);
      return { id, provider, name: stringValue(selected.name) || named?.name || id };
    },
    enabled: Boolean(sessionId) && visible,
    staleTime: 30_000,
    refetchInterval: visible && sessionId ? 30_000 : false,
    retry: false,
  });
  const model = query.data;
  const label = model?.name || (sessionId && query.isPending ? '读取模型…' : '模型未提供');
  const detail = model ? `${model.provider}/${model.id}${query.isError ? ' · 暂时无法更新' : ''}` : sessionId ? '尚未读取到此 Session 的模型' : '尚无独立 Session 绑定';
  const badge = <span aria-label={`当前模型：${label}`} className="paw-satellite-model" title={detail}>{label}</span>;
  return inline ? badge : <PawWindowChromePortal>{badge}</PawWindowChromePortal>;
}
