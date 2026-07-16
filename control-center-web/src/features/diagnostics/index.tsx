import { Activity, Clipboard, Cpu, Keyboard, RefreshCw, ServerCog } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, EmptyState } from '@/components/primitives';
import { useDiagnosticsQueries } from './api';
import { DiagnosticsRuntimeWorkflow, type DiagnosticsRuntimeAction } from './runtime-actions';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  asRecord,
  booleanValue,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import './diagnostics.css';

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
  const runtimeRevision = numberValue(runtime.runtimeRevision, -1);
  const aiEnabled = booleanValue(asRecord(asRecord(runtime.runtimeConfig).postCommit).enabled, true);
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

        <ManagementSection
          title="本机辅助修复"
          description="先预览影响，再确认并追踪执行结果。"
          trailing={(
            <StatusBadge
              label={runtimeRevision < 0 ? '等待后台状态' : canOpenAccessibilitySettings ? '宿主可用' : '仅桌面端可用'}
              tone={runtimeRevision < 0 || !canOpenAccessibilitySettings ? 'warning' : 'success'}
            />
          )}
        >
          {!canOpenAccessibilitySettings ? (
            <InlineNotice title="需要桌面控制中心" tone="warning">
              重启服务、重新部署和打开系统设置由桌面宿主的固定白名单执行；浏览器预览保持只读。
            </InlineNotice>
          ) : runtimeRevision < 0 ? (
            <InlineNotice title="正在等待运行状态" tone="warning">
              后台返回当前运行版本后，修复操作才会开放预览。
            </InlineNotice>
          ) : null}
          <div className="diagnostics-action-list">
            {runtimeActions(aiEnabled).map((item) => (
              <DiagnosticsRuntimeWorkflow
                action={item.action}
                description={item.description}
                key={item.action}
                nativeExternalActions={canOpenAccessibilitySettings}
                onApplied={refresh}
                risk={item.risk}
                runtimeRevision={runtimeRevision}
                title={item.title}
                transport={queries.transport}
              />
            ))}
          </div>
        </ManagementSection>

        <ManagementSection title="高风险操作边界">
          <details className="diagnostics-boundary">
            <summary>查看受保护操作</summary>
            <p>清空历史、清空记忆、恢复默认与卸载不属于快捷修复。执行前必须单独审阅影响范围并再次确认。</p>
          </details>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function runtimeActions(aiEnabled: boolean): readonly {
  action: DiagnosticsRuntimeAction;
  description: string;
  risk: 'R1' | 'R2' | 'R3';
  title: string;
}[] {
  return [
    { action: 'register_input_source', title: '重新注册输入法', description: '刷新当前用户的 Squirrel 输入源注册，不清空用户数据。', risk: 'R2' },
    { action: 'restart_sidecar', title: '重启后台服务', description: '由控制中心宿主重启 Sidecar，避免服务自行终止后丢失执行边界。', risk: 'R2' },
    { action: 'restart_predictor', title: '重启本机模型', description: '重新启动 MLX 预测服务并等待系统返回执行回执。', risk: 'R2' },
    { action: 'redeploy_rime', title: '重新部署 Rime 配置', description: '运行固定的受信任部署脚本，不接受页面提供的路径或命令。', risk: 'R3' },
    { action: 'open_accessibility_settings', title: '打开辅助功能设置', description: '打开 macOS 辅助功能权限页，不自动修改权限。', risk: 'R1' },
    aiEnabled
      ? { action: 'stop_ai', title: '暂停智能候选', description: '暂停提交后的智能候选，基础 Rime 输入保持可用。', risk: 'R1' }
      : { action: 'resume_ai', title: '恢复智能候选', description: '恢复提交后的智能候选，基础 Rime 输入保持可用。', risk: 'R1' },
  ];
}

function componentLabel(id: string): string {
  return ({
    inputMethod: '输入法',
    sidecar: '后台服务',
    predictor: '本机模型',
    foregroundContext: '当前应用识别',
    hybridRag: '知识检索',
    memoryCompiler: '记忆整理',
    sqlite: '本机数据库',
    voiceAgent: '语音代理',
    voiceMicrophone: '麦克风权限',
    voiceAccessibility: '辅助功能权限',
    voiceRecognition: '语音定稿',
    deployment: '安装一致性',
  } as Record<string, string>)[id] ?? '其他服务';
}

function componentDetail(item: Record<string, unknown>): string {
  const detail = stringValue(item.detail).trim();
  if (!detail) return booleanValue(item.ok) ? '运行正常' : '请打开详情继续检查';
  return detail;
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
