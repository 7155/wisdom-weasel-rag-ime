import { Activity, Clipboard, Cpu, Keyboard, RefreshCw, ServerCog } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, EmptyState } from '@/components/primitives';
import { useDiagnosticsQueries } from './api';
import {
  type ActionReceipt,
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  WorkflowAction,
  asRecord,
  booleanValue,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';

const accessibilityAction = 'open_accessibility_settings' as const;
const accessibilityPayloadSha256 = 'a167f4745ab72a49c87c1bc8f91501d1936a762e738b04c25d970f75b7d5ee46';
const accessibilityCommandSha256 = '7ad3fe3906a8de6bd55af7e36684a09df082fe43cf031277684ce09c605c1172';

export function DiagnosticsFeature() {
  const queries = useDiagnosticsQueries();
  const runtime = asRecord(queries.runtime.data);
  const predictorEnvelope = asRecord(queries.predictor.data);
  const predictor = asRecord(predictorEnvelope.predictor);
  const predictorCapabilities = asRecord(predictor.capabilities);
  const predictorModelInfo = asRecord(predictor.modelInfo);
  const predictorProvider = stringValue(
    predictor.provider,
    stringValue(predictor.providerName, stringValue(predictor.kind, 'local')),
  );
  const predictorDimensions = numberValue(
    predictor.dimensions,
    numberValue(predictorCapabilities.dimensions, numberValue(predictorModelInfo.hiddenSize)),
  );
  const models = asRecord(queries.models.data);
  const inputSource = asRecord(queries.source.data);
  const components = Object.entries(asRecord(runtime.components)).map(([id, value]) => ({
    ...asRecord(value),
    id,
  } as Record<string, unknown>));
  const [copyStatus, setCopyStatus] = useState('');
  const canOpenAccessibilitySettings = Boolean(
    queries.capabilities.data?.native.approvedExternalActions
      && queries.transport.runApprovedExternalAction,
  );
  const error = [queries.runtime.error, queries.predictor.error, queries.models.error, queries.source.error].find(Boolean) as Error | null;
  const pending = queries.runtime.isPending || queries.predictor.isPending || queries.models.isPending || queries.source.isPending;
  const refresh = () => void Promise.all([
    queries.runtime.refetch(),
    queries.predictor.refetch(),
    queries.models.refetch(),
    queries.source.refetch(),
    queries.capabilities.refetch(),
  ]);
  const report = useMemo(() => JSON.stringify({
    runtime: redact(runtime),
    predictor: redact(predictorEnvelope),
    models: redact(models),
    inputSource: redact(inputSource),
  }, null, 2), [inputSource, models, predictorEnvelope, runtime]);

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopyStatus('诊断快照已复制');
    } catch {
      setCopyStatus('当前环境不支持复制');
    }
  };

  const openAccessibilitySettings = async (): Promise<ActionReceipt> => {
    if (!queries.transport.runApprovedExternalAction) {
      throw new Error('当前应用不支持打开系统设置。');
    }
    const receipt = await queries.transport.runApprovedExternalAction({
      action: accessibilityAction,
      receiptId: `diagnostics:${accessibilityAction}:${Date.now()}`,
      payloadSha256: accessibilityPayloadSha256,
      commandSha256: accessibilityCommandSha256,
    });
    if (!receipt.accepted || !receipt.completed || (receipt.exitCode ?? 0) !== 0) {
      throw new Error(receipt.error || 'macOS 辅助功能设置未能打开。');
    }
    return {
      receiptId: receipt.receiptId,
      status: 'applied',
      message: 'macOS 辅助功能设置已打开。',
      at: new Date().toLocaleString('zh-CN'),
      rollbackAvailable: false,
    };
  };

  return (
    <ManagementPage
      actions={
        <>
          <Button leadingIcon={<Clipboard size={15} />} onClick={() => void copyReport()} size="small">复制诊断</Button>
          <Button leadingIcon={<RefreshCw size={15} />} loading={queries.runtime.isFetching} onClick={refresh} size="small">刷新</Button>
        </>
      }
      description="检查输入法、后台服务、模型与本机数据是否可以正常工作。"
      eyebrow="系统"
      routeId="diagnostics"
      title="诊断与修复"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        {copyStatus ? <InlineNotice title="诊断导出" tone="info">{copyStatus}</InlineNotice> : null}
        <ManagementSection title="关键探针">
          <MetricStrip items={[
            { label: '输入法', value: booleanValue(inputSource.typingReady) ? '可以输入' : '需要检查', detail: inputReadinessLabel(stringValue(inputSource.readinessState)), icon: Keyboard, tone: booleanValue(inputSource.typingReady) ? 'success' : 'warning' },
            { label: '本机预测', value: booleanValue(predictorEnvelope.ok) ? '运行正常' : '需要检查', detail: predictorServiceLabel(predictorProvider), icon: Cpu, tone: booleanValue(predictorEnvelope.ok) ? 'success' : 'warning' },
            { label: '模型维度', value: predictorDimensions, detail: '当前能力', icon: Activity },
            { label: '系统设置', value: canOpenAccessibilitySettings ? '可以打开' : '当前不可用', detail: 'macOS 辅助功能', icon: ServerCog, tone: canOpenAccessibilitySettings ? 'success' : 'warning' },
          ]} />
        </ManagementSection>

        <ManagementSection title="服务状态" trailing={<StatusBadge label={`${components.length} 项`} tone={components.every((item) => booleanValue(item.ok)) ? 'success' : 'warning'} />}>
          {components.length ? <OperationalList items={components.map((item) => ({
            id: stringValue(item.id),
            title: componentLabel(stringValue(item.id)),
            detail: componentDetail(item),
            meta: serviceStatusLabel(stringValue(item.status)),
            status: <StatusBadge label={booleanValue(item.ok) ? '正常' : '需要检查'} tone={booleanValue(item.ok) ? 'success' : 'warning'} />,
          }))} /> : <EmptyState description="后台尚未返回服务状态。" icon={Activity} title="暂无服务状态" />}
        </ManagementSection>

        <div className="mgmt-grid-2">
          <ManagementSection title="本机预测">
            <dl className="mgmt-kv">
              <dt>服务方式</dt><dd>{predictorServiceLabel(predictorProvider)}</dd>
              <dt>当前模型</dt><dd>{displayModelName(predictor)}</dd>
              <dt>运行位置</dt><dd>{runtimeLabel(stringValue(predictor.runtime, 'local'))}</dd>
              <dt>缓存状态</dt><dd>{booleanValue(asRecord(predictor.statusCache).hit) ? '已命中' : '暂无命中'}</dd>
            </dl>
          </ManagementSection>
          <ManagementSection title="模型路由">
            <dl className="mgmt-kv">
              <dt>本机预测</dt><dd>{booleanValue(models.ok) ? '可用' : '需要检查'}</dd>
              <dt>深度生成</dt><dd>{booleanValue(asRecord(models.activeRagRoute).remoteReady) ? '已连接' : '尚未连接'}</dd>
              <dt>当前状态</dt><dd>{routeStateLabel(stringValue(asRecord(models.activeRagRoute).skipReason))}</dd>
            </dl>
          </ManagementSection>
        </div>

        <ManagementSection title="本机辅助修复" description="这里只显示当前应用确实可以执行的操作。">
          {canOpenAccessibilitySettings ? (
            <WorkflowAction
              actionId="diagnostics.open-accessibility-settings"
              applyLabel="打开系统设置"
              description="打开 macOS 辅助功能权限页，不重启后台服务，也不修改输入法。"
              mutationKey={['diagnostics', 'mutation', 'open-accessibility-settings']}
              onApply={openAccessibilitySettings}
              preview={[
                '目标：macOS 隐私与安全性 > 辅助功能。',
                '仅打开系统设置，不自动修改权限。',
                '此动作不改变服务状态，因此不需要撤销。',
              ]}
              risk="R1"
              title="打开辅助功能设置"
            />
          ) : (
            <InlineNotice title="本机操作不可用" tone="warning">当前应用无法直接打开辅助功能设置，请从 macOS 系统设置中进入。</InlineNotice>
          )}
          <InlineNotice title="其余修复暂不可执行" tone="info">后台服务重启、暂停智能候选、重新部署词表与注册输入法还不能从这里安全执行，因此暂不提供按钮。</InlineNotice>
        </ManagementSection>

        <ManagementSection title="危险操作">
          <InlineNotice title="高风险边界" tone="danger">清空历史、清空记忆、恢复默认与卸载必须先审阅影响范围并明确确认。</InlineNotice>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function componentLabel(id: string): string {
  return ({ inputMethod: '输入法', sidecar: '后台服务', predictor: '本机模型', foregroundContext: '当前应用识别', hybridRag: '知识检索', memoryCompiler: '记忆整理', sqlite: '本机数据库' } as Record<string, string>)[id] ?? '其他服务';
}

function componentDetail(item: Record<string, unknown>): string {
  const detail = stringValue(item.detail).trim();
  if (!detail) return booleanValue(item.ok) ? '运行正常' : '请打开详情继续检查';
  return /ready|running|healthy|ok/i.test(detail) ? '运行正常' : /disabled|stopped/i.test(detail) ? '当前未启用' : '已返回运行信息';
}

function serviceStatusLabel(value: string): string {
  if (/ready|running|healthy|ok/i.test(value)) return '运行中';
  if (/disabled|stopped|off/i.test(value)) return '未启用';
  return value ? '状态已更新' : '等待状态';
}

function inputReadinessLabel(value: string): string {
  return ({ not_selected: '尚未选为当前输入法', ready: '已准备好', unavailable: '当前不可用' } as Record<string, string>)[value] ?? '等待系统状态';
}

function predictorServiceLabel(value: string): string {
  if (/mlx|local/i.test(value)) return '本机模型';
  if (/remote|cloud/i.test(value)) return '远程模型';
  return value ? '已连接模型服务' : '等待模型服务';
}

function displayModelName(predictor: Record<string, unknown>): string {
  const model = stringValue(predictor.model).trim();
  return model && !model.includes('/') ? model : '由本机配置决定';
}

function runtimeLabel(value: string): string {
  return /local|native|mlx/i.test(value) ? '本机' : value ? '已连接环境' : '等待状态';
}

function routeStateLabel(value: string): string {
  if (!value || value === 'none') return '可以使用';
  if (/not.?configured|missing|unavailable/i.test(value)) return '需要完成模型配置';
  if (/disabled|off/i.test(value)) return '当前未启用';
  return '暂不可用，请查看诊断报告';
}

function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (typeof value === 'string') {
    if (/^(?:sha256:|https?:\/\/|file:|\/)/i.test(value)) return '已隐藏';
    return value;
  }
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).flatMap(([key, item]) => {
    if (/schema(?:Version)?|pathId|operation(?:Id)?|receipt(?:Id)?|rollbackToken|payloadSha|runtimeRevision|previewToken|policy(?:Id)?|profile(?:Id|Version)?/i.test(key)) return [];
    return [[
      key,
      /token|secret|password|api.?key|authorization|cookie/i.test(key) ? (item ? 'configured' : 'not configured') : redact(item),
    ]];
  }));
}
