import { Activity, Clipboard, Cpu, Keyboard, RefreshCw, ServerCog } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, EmptyState } from '@/components/primitives';
import { useDiagnosticsQueries } from './api';
import {
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

export function DiagnosticsFeature() {
  const queries = useDiagnosticsQueries();
  const runtime = asRecord(queries.runtime.data);
  const predictorEnvelope = asRecord(queries.predictor.data);
  const predictor = asRecord(predictorEnvelope.predictor);
  const models = asRecord(queries.models.data);
  const inputSource = asRecord(queries.source.data);
  const components = Object.entries(asRecord(runtime.components)).map(([id, value]) => ({
    ...asRecord(value),
    id,
  } as Record<string, unknown>));
  const [copyStatus, setCopyStatus] = useState('');
  const error = [queries.runtime.error, queries.predictor.error, queries.models.error, queries.source.error].find(Boolean) as Error | null;
  const pending = queries.runtime.isPending || queries.predictor.isPending || queries.models.isPending || queries.source.isPending;
  const refresh = () => void Promise.all([queries.runtime.refetch(), queries.predictor.refetch(), queries.models.refetch(), queries.source.refetch()]);
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
      description="检查输入源、Sidecar、预测器、模型与数据库；修复操作需要本机批准。"
      eyebrow="SYSTEM"
      routeId="diagnostics"
      title="诊断与修复"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        {copyStatus ? <InlineNotice title="诊断导出" tone="info">{copyStatus}</InlineNotice> : null}
        <ManagementSection title="关键探针">
          <MetricStrip items={[
            { label: '输入源', value: booleanValue(inputSource.typingReady) ? 'ready' : 'not ready', detail: stringValue(inputSource.readinessState, 'unknown'), icon: Keyboard, tone: booleanValue(inputSource.typingReady) ? 'success' : 'warning' },
            { label: '预测器', value: stringValue(predictor.status, booleanValue(predictorEnvelope.ok) ? 'ready' : 'unknown'), detail: stringValue(predictor.provider, stringValue(predictor.kind, 'local')), icon: Cpu, tone: booleanValue(predictorEnvelope.ok) ? 'success' : 'warning' },
            { label: '模型维度', value: numberValue(predictor.dimensions, numberValue(asRecord(predictor.capabilities).dimensions)), detail: '当前能力', icon: Activity },
            { label: '本机修复', value: queries.capabilities.data?.native.approvedExternalActions ? 'available' : 'unavailable', detail: '需要本机确认', icon: ServerCog, tone: queries.capabilities.data?.native.approvedExternalActions ? 'success' : 'warning' },
          ]} />
        </ManagementSection>

        <ManagementSection title="组件状态" trailing={<StatusBadge label={`${components.length} components`} tone={components.every((item) => booleanValue(item.ok)) ? 'success' : 'warning'} />}>
          {components.length ? <OperationalList items={components.map((item) => ({
            id: stringValue(item.id),
            title: componentLabel(stringValue(item.id)),
            detail: stringValue(item.detail, '无详情'),
            meta: stringValue(item.status, 'unknown'),
            status: <StatusBadge label={booleanValue(item.ok) ? 'ok' : 'degraded'} tone={booleanValue(item.ok) ? 'success' : 'warning'} />,
          }))} /> : <EmptyState description="服务尚未返回组件状态。" icon={Activity} title="暂无组件状态" />}
        </ManagementSection>

        <div className="mgmt-grid-2">
          <ManagementSection title="预测器快照">
            <dl className="mgmt-kv">
              <dt>Provider</dt><dd>{stringValue(predictor.provider, stringValue(predictor.kind, 'unknown'))}</dd>
              <dt>Model</dt><dd>{stringValue(predictor.model, stringValue(predictor.modelPath, 'unknown'))}</dd>
              <dt>Runtime</dt><dd>{stringValue(predictor.runtime, 'local')}</dd>
              <dt>Cache</dt><dd>{booleanValue(asRecord(predictor.statusCache).hit) ? 'hit' : 'miss / unknown'}</dd>
            </dl>
          </ManagementSection>
          <ManagementSection title="模型路由">
            <dl className="mgmt-kv">
              <dt>Schema</dt><dd>{stringValue(models.schemaVersion, 'unknown')}</dd>
              <dt>本地预测</dt><dd>{booleanValue(models.ok) ? 'available' : 'unknown'}</dd>
              <dt>远程生成</dt><dd>{booleanValue(asRecord(models.activeRagRoute).remoteReady) ? 'configured' : 'not configured'}</dd>
              <dt>阻断原因</dt><dd>{stringValue(asRecord(models.activeRagRoute).skipReason, 'none')}</dd>
            </dl>
          </ManagementSection>
        </div>

        <ManagementSection title="修复与暂停" description="以下修复动作当前为演练，不会修改本机服务。">
          <div className="mgmt-grid-3">
            <WorkflowAction actionId="diagnostics.restart-sidecar" description="重启 Sidecar 并等待运行状态恢复。" mutationKey={['diagnostics', 'mutation', 'restart-sidecar']} preview={['目标：Sidecar。', '先停止接收新的管理操作。', '收据记录退出码与恢复探针。']} risk="R2" title="重启 Sidecar" />
            <WorkflowAction actionId="diagnostics.restart-predictor" description="重启本地预测器并重新检查可用能力。" mutationKey={['diagnostics', 'mutation', 'restart-predictor']} preview={['目标：本地预测器。', '普通 Rime 输入不受影响。', '等待模型就绪后完成。']} risk="R2" title="重启本地模型" />
            <WorkflowAction actionId="diagnostics.pause-ai" description="暂停 AI lanes；保留 Rime 基础输入能力。" mutationKey={['diagnostics', 'mutation', 'pause-ai']} preview={['操作：暂停 AI lanes。', '不终止 Squirrel/Rime。', '回滚时恢复 AI lanes。']} risk="R1" title="暂停 AI" />
            <WorkflowAction actionId="diagnostics.redeploy-rime" description="重新部署 Rime 配置与用户词库。" mutationKey={['diagnostics', 'mutation', 'redeploy-rime']} preview={['目标：Rime 配置与用户词库。', '需要本机批准。', '失败时保留上一版配置。']} risk="R2" title="重新部署 Rime" />
            <WorkflowAction actionId="diagnostics.register-source" description="重新注册 Squirrel 输入源。" mutationKey={['diagnostics', 'mutation', 'register-source']} preview={['检查当前输入源安装位置。', '避免注册重复输入源。', '注册后重新检查前台输入状态。']} risk="R2" title="重新注册输入源" />
          </div>
        </ManagementSection>

        <ManagementSection title="危险操作">
          <InlineNotice title="高风险边界" tone="danger">清空历史、清空记忆、恢复默认与卸载必须先审阅影响范围并明确确认。</InlineNotice>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function componentLabel(id: string): string {
  return ({ inputMethod: '输入法', sidecar: 'Sidecar', predictor: '本地模型', foregroundContext: '前台上下文', hybridRag: 'Hybrid RAG', memoryCompiler: '记忆编译', sqlite: 'SQLite' } as Record<string, string>)[id] ?? id;
}

function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [
    key,
    /token|secret|password|api.?key|authorization|cookie/i.test(key) ? (item ? 'configured' : 'not configured') : redact(item),
  ]));
}
