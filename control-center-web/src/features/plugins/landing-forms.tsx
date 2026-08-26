import { LayoutTemplate, MessageCircle, PackageCheck, RotateCcw, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
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
import './plugins.css';

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

const DEFAULT_BOOTSTRAP_DRAFT = '/skill:landing-app-builder 用户要一个可安装的垂直助手。先澄清场景与验收，再搜索市场；没有合适 Package 时写最小 Skill（必要时加 prompt/theme），走 create_package → validate → propose_install，然后停下。不要声称已安装。示例：智能调研助手。';

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
  const navigate = useNavigate();
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
  const proposalsQuery = useQuery({
    queryKey: ['agent.extensions.proposals', 'landing-forms'],
    queryFn: async ({ signal }) => asRecord(await transport.request({ pathId: 'agent.extensions.proposals', signal })),
    refetchInterval: 8_000,
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
  const proposalCount = arrayRecords(asRecord(proposalsQuery.data).items).length;

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

  const openBootstrap = () => {
    const draft = (activeForm?.bootstrapPrompt || DEFAULT_BOOTSTRAP_DRAFT).trim();
    navigate({
      pathname: '/agent',
      search: new URLSearchParams({ draft }).toString(),
    });
  };

  const busy = activateMutation.isPending || deactivateMutation.isPending;
  const isPending = catalogQuery.isPending || activeQuery.isPending || listQuery.isPending;
  const error = asError(catalogQuery.error || activeQuery.error || listQuery.error);
  const onRetry = () => {
    void catalogQuery.refetch();
    void activeQuery.refetch();
    void listQuery.refetch();
  };

  const body = (
    <div className="landing-forms" data-testid="landing-forms">
      {notice ? (
        <InlineNotice title="落地形态" tone={notice.tone}>
          {notice.summary}
        </InlineNotice>
      ) : null}

      {proposalCount > 0 ? (
        <InlineNotice title="可以安装了" tone="success">
          {identity.assistantName} 已提交 {proposalCount} 个 Package 安装预览。到「建议」确认后，Launchpad 会出现对应图标。
          <div className="landing-forms__notice-actions">
            <Button
              leadingIcon={<PackageCheck size={14} />}
              onClick={() => navigate('/plugins?view=proposals')}
              size="small"
            >
              去确认安装
            </Button>
          </div>
        </InlineNotice>
      ) : null}

      <ManagementSection
        description="描述需求 → 分析并写 Skill/Package → propose_install → 你在产品内确认。安装后 Launchpad 出现图标；主题可改变氛围，可执行 UI 仍属第一方。"
        title="自举造 App"
        trailing={(
          <Button leadingIcon={<MessageCircle size={14} />} onClick={openBootstrap} size="small">
            开始造 App
          </Button>
        )}
      >
        <p className="landing-forms__hint">
          当前形态技能：{(activeForm?.skillRefs?.length ? activeForm.skillRefs : ['landing-app-builder', 'plugin-creator']).join(' · ')}
        </p>
      </ManagementSection>

      <ManagementSection
        description="Form 绑定 Persona、Knowledge 范围、策略预设与 Dock/App 可见性；切换走 preview → confirm → apply → receipt。"
        title="当前形态"
      >
        {activeForm ? (
          <ActiveFormCard busy={busy} form={activeForm} onDeactivate={() => deactivateMutation.mutate()} onBootstrap={openBootstrap} />
        ) : (
          <EmptyState
            action={(
              <Button onClick={openBootstrap} size="small" variant="quiet">
                先造一个垂直 App
              </Button>
            )}
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
          <ul className="landing-forms__catalog" data-testid="landing-form-catalog">
            {catalogItems.map((item) => (
              <li key={item.id}>
                <article className="landing-forms__card">
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
    </div>
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
      description="创建、安装、切换与回滚落地形态；造完 Package 后可在「建议」确认安装。"
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
  onBootstrap,
  busy,
}: {
  form: LandingFormSummary;
  onDeactivate: () => void;
  onBootstrap: () => void;
  busy: boolean;
}) {
  return (
    <article className="landing-forms__card" data-testid="landing-form-active">
      <header>
        <strong>{form.displayName}</strong>
        <StatusBadge label="使用中" tone="success" />
      </header>
      <p>{form.tagline || form.description || '—'}</p>
      <p className="landing-forms__meta">
        Dock：{form.dockAppIds.join(' · ') || '—'}
        <br />
        默认入口：{form.defaultLandingAppId || '—'}
        {form.skillRefs.length ? (
          <>
            <br />
            技能：{form.skillRefs.join(' · ')}
          </>
        ) : null}
      </p>
      <footer>
        <Button
          disabled={busy}
          leadingIcon={<MessageCircle aria-hidden="true" size={14} />}
          onClick={onBootstrap}
          size="small"
        >
          造 App
        </Button>
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
