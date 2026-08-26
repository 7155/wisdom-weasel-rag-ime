import { LayoutTemplate, RotateCcw, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, EmptyState } from '@/components/primitives';
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
import { useControlTransport } from '@/app/control-transport';
import { landingFormFromPayload, type LandingFormSummary } from '@/features/paw-os/active-form';
import { useProductIdentity } from '@/features/identity/product-identity';
import { usePawOsAppSurface } from '@/features/paw-os/surface-context';
import type { ControlTransport, JsonValue } from '@/platform/transport';

type CatalogItem = {
  id: string;
  displayName: string;
  description: string;
  installState: string;
  actionable: boolean;
  latestVersion: string;
};

type LifecycleNotice = { tone: 'success' | 'danger' | 'info'; summary: string };
type JsonObject = { [key: string]: JsonValue };

function asError(error: unknown): Error | null {
  if (!error) return null;
  if (error instanceof Error) return error;
  return new Error(publicErrorText(error) || '请求失败');
}

async function applyFormAction(
  transport: ControlTransport,
  previewBody: JsonObject,
): Promise<{ receiptId: string; action: string }> {
  const preview = asRecord(await transport.request({
    pathId: 'agent.forms.preview',
    body: previewBody,
  }));
  const applied = asRecord(await transport.request({
    pathId: 'agent.forms.apply',
    body: {
      previewToken: stringValue(preview.previewToken),
      payloadSha256: stringValue(preview.payloadSha256),
      confirmText: 'apply',
    },
  }));
  const receipt = asRecord(applied.receipt);
  return {
    receiptId: stringValue(receipt.receiptId),
    action: stringValue(receipt.action),
  };
}

export function LandingFormsFeature() {
  const transport = useControlTransport();
  const identity = useProductIdentity();
  const surface = usePawOsAppSurface();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<LifecycleNotice | null>(null);

  const catalogQuery = useQuery({
    queryKey: ['agent.forms.catalog'],
    queryFn: async ({ signal }) => asRecord(await transport.request({ pathId: 'agent.forms.catalog', signal })),
  });
  const activeQuery = useQuery({
    queryKey: ['agent.forms.active'],
    queryFn: async ({ signal }) => asRecord(await transport.request({ pathId: 'agent.forms.active', signal })),
  });
  const listQuery = useQuery({
    queryKey: ['agent.forms.list'],
    queryFn: async ({ signal }) => asRecord(await transport.request({ pathId: 'agent.forms.list', signal })),
  });

  const activeForm = useMemo(
    () => landingFormFromPayload(asRecord(activeQuery.data).form),
    [activeQuery.data],
  );
  const catalogItems = useMemo((): CatalogItem[] => {
    return arrayRecords(asRecord(catalogQuery.data).items).map((item) => ({
      id: stringValue(item.id),
      displayName: stringValue(item.displayName) || stringValue(item.id),
      description: stringValue(item.description),
      installState: stringValue(item.installState) || 'available',
      actionable: item.actionable === true,
      latestVersion: stringValue(item.latestVersion),
    }));
  }, [catalogQuery.data]);

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['agent.forms.catalog'] }),
      queryClient.invalidateQueries({ queryKey: ['agent.forms.active'] }),
      queryClient.invalidateQueries({ queryKey: ['agent.forms.list'] }),
    ]);
  };

  const activateMutation = useMutation({
    mutationFn: async (item: CatalogItem) => {
      const body: JsonObject = { catalogId: item.id };
      if (item.latestVersion) body.catalogVersion = item.latestVersion;
      const validation = asRecord(await transport.request({
        pathId: 'agent.forms.validate',
        body,
      }));
      await applyFormAction(transport, {
        action: 'install',
        validationToken: stringValue(validation.validationToken),
      });
      return applyFormAction(transport, {
        action: 'activate',
        formId: item.id,
        version: item.latestVersion,
      });
    },
    onSuccess: async (receipt) => {
      setNotice({ tone: 'success', summary: `已切换落地形态（${receipt.receiptId}）` });
      await invalidate();
    },
    onError: (error) => {
      setNotice({ tone: 'danger', summary: publicErrorText(error) || '切换失败' });
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: async () => applyFormAction(transport, { action: 'deactivate' }),
    onSuccess: async (receipt) => {
      setNotice({ tone: 'info', summary: `已恢复默认 Dock（${receipt.receiptId}）` });
      await invalidate();
    },
    onError: (error) => {
      setNotice({ tone: 'danger', summary: publicErrorText(error) || '停用失败' });
    },
  });

  const busy = activateMutation.isPending || deactivateMutation.isPending;
  const isPending = catalogQuery.isPending || activeQuery.isPending || listQuery.isPending;
  const error = asError(catalogQuery.error || activeQuery.error || listQuery.error);
  const onRetry = () => {
    void catalogQuery.refetch();
    void activeQuery.refetch();
    void listQuery.refetch();
  };

  const body = (
    <>
      {notice ? (
        <InlineNotice title="落地形态" tone={notice.tone}>
          {notice.summary}
        </InlineNotice>
      ) : null}
      <ManagementSection
        description="Form 绑定 Persona、Knowledge 范围、策略预设与 Dock/App 可见性；切换走 preview → confirm → apply → receipt。"
        title="当前形态"
      >
        {activeForm ? (
          <ActiveFormCard busy={busy} form={activeForm} onDeactivate={() => deactivateMutation.mutate()} />
        ) : (
          <EmptyState
            description="未激活落地形态时，Dock 与 Launchpad 使用完整十一 App 默认集合。"
            icon={LayoutTemplate}
            title="默认 PAW 工作台"
          />
        )}
      </ManagementSection>
      <ManagementSection
        description={`${identity.productName} 自举可安装的落地形态目录。`}
        title="形态目录"
      >
        {catalogItems.length === 0 ? (
          <EmptyState description="目录为空。" icon={Sparkles} title="暂无可用形态" />
        ) : (
          <ul className="plugins-native-grid" data-testid="landing-form-catalog">
            {catalogItems.map((item) => (
              <li key={item.id}>
                <article>
                  <header>
                    <strong>{item.displayName}</strong>
                    <StatusBadge
                      label={installStateLabel(item.installState)}
                      tone={item.installState === 'active' ? 'success' : 'neutral'}
                    />
                  </header>
                  <p>{item.description || '—'}</p>
                  <footer>
                    <span>{item.latestVersion ? `v${item.latestVersion}` : '—'}</span>
                    <Button
                      disabled={!item.actionable || busy || item.installState === 'active'}
                      onClick={() => activateMutation.mutate(item)}
                      size="small"
                    >
                      {item.installState === 'active' ? '使用中' : '切换到此形态'}
                    </Button>
                  </footer>
                </article>
              </li>
            ))}
          </ul>
        )}
      </ManagementSection>
    </>
  );

  if (surface?.appId === 'app-center') {
    return (
      <QueryState error={error} isPending={isPending} onRetry={onRetry}>
        {body}
      </QueryState>
    );
  }

  return (
    <ManagementPage
      description="创建、安装、切换与回滚落地形态；Shell 会按 active Form 过滤 Dock 与 Launchpad。"
      routeId="plugins"
      title="落地形态"
    >
      <QueryState error={error} isPending={isPending} onRetry={onRetry}>
        {body}
      </QueryState>
    </ManagementPage>
  );
}

function ActiveFormCard({
  form,
  onDeactivate,
  busy,
}: {
  form: LandingFormSummary;
  onDeactivate: () => void;
  busy: boolean;
}) {
  return (
    <article className="plugins-native-grid" data-testid="landing-form-active">
      <header>
        <strong>{form.displayName}</strong>
        <StatusBadge label="使用中" tone="success" />
      </header>
      <p>{form.tagline || form.description || '—'}</p>
      <p>
        Dock：{form.dockAppIds.join(' · ') || '—'}
        <br />
        默认入口：{form.defaultLandingAppId || '—'}
      </p>
      <footer>
        <Button
          disabled={busy}
          leadingIcon={<RotateCcw aria-hidden="true" size={14} />}
          onClick={onDeactivate}
          size="small"
          variant="quiet"
        >
          恢复默认
        </Button>
      </footer>
    </article>
  );
}

function installStateLabel(state: string): string {
  switch (state) {
    case 'active':
      return '使用中';
    case 'installed':
      return '已安装';
    case 'update_available':
      return '可更新';
    default:
      return '可安装';
  }
}
