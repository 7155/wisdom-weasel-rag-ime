import {
  Activity,
  BrainCircuit,
  Cpu,
  Database,
  Gauge,
  Keyboard,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { Button, EmptyState } from '@/components/primitives';
import { useOverviewQueries } from './api';
import {
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  WorkflowAction,
  arrayRecords,
  asRecord,
  booleanValue,
  numberValue,
  stringValue,
} from './management-ui';

export function OverviewFeature() {
  const queries = useOverviewQueries();
  const overview = asRecord(queries.snapshot.data);
  const memory = asRecord(overview.memory);
  const lastPrediction = asRecord(overview.lastPrediction);
  const runtime = asRecord(queries.agentRuntime.data);
  const modelStatus = asRecord(queries.models.data);
  const knowledgeRoute = asRecord(queries.knowledgeRoute.data);
  const componentEntries = Object.entries(asRecord(overview.components)).map(([id, value]) => ({
    ...asRecord(value),
    id,
  } as Record<string, unknown>));
  const error = [queries.snapshot.error, queries.health.error].find(Boolean) as Error | null;
  const pending = queries.snapshot.isPending || queries.health.isPending;

  const refresh = () => {
    void Promise.all([
      queries.snapshot.refetch(),
      queries.health.refetch(),
      queries.agentRuntime.refetch(),
      queries.models.refetch(),
      queries.knowledgeRoute.refetch(),
    ]);
  };

  return (
    <ManagementPage
      actions={
        <Button leadingIcon={<RefreshCw size={15} />} loading={queries.snapshot.isFetching} onClick={refresh} size="small">
          刷新
        </Button>
      }
      description="输入法、本地预测、个人记忆、知识路由与 Pi Runtime 的实时控制面。"
      eyebrow="WORKSPACE"
      routeId="overview"
      title="今日概览"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection
          title="运行就绪度"
          trailing={
            <StatusBadge
              label={componentEntries.every((item) => booleanValue(item.ok)) ? '全部就绪' : '需要检查'}
              tone={componentEntries.every((item) => booleanValue(item.ok)) ? 'success' : 'warning'}
            />
          }
        >
          {componentEntries.length ? (
            <OperationalList
              items={componentEntries.map((item) => ({
                id: stringValue(item.id),
                title: componentLabel(stringValue(item.id)),
                detail: stringValue(item.detail, stringValue(item.status, '等待状态')),
                meta: stringValue(item.status, 'unknown'),
                status: (
                  <StatusBadge
                    label={booleanValue(item.ok) ? 'ready' : 'degraded'}
                    tone={booleanValue(item.ok) ? 'success' : 'warning'}
                  />
                ),
              }))}
            />
          ) : (
            <EmptyState description="服务已响应，但尚未返回组件状态。" icon={Activity} title="暂无组件快照" />
          )}
        </ManagementSection>

        <ManagementSection title="控制面指标" description="汇总输入、记忆、模型与知识路由状态。">
          <MetricStrip
            items={[
              { label: '输入事件', value: numberValue(memory.eventCount), detail: '近期上下文', icon: Keyboard },
              { label: '可召回文档', value: numberValue(memory.retrievalDocCount), detail: 'BGE / BM25', icon: Database, tone: 'info' },
              { label: '主题记忆', value: numberValue(memory.memoryBookCount), detail: 'Memory Books', icon: BrainCircuit },
              { label: '待整理', value: numberValue(memory.pendingCompileEvents), detail: 'compile queue', icon: Sparkles, tone: numberValue(memory.pendingCompileEvents) ? 'warning' : 'success' },
              { label: 'Pi Runtime', value: stringValue(runtime.status, 'unknown'), detail: stringValue(runtime.driverId, 'driver unknown'), icon: Cpu, tone: booleanValue(runtime.ok, stringValue(runtime.status) === 'ready') ? 'success' : 'warning' },
              { label: '知识路由', value: booleanValue(knowledgeRoute.deepseekReady) ? 'ready' : 'blocked', detail: '显式知识任务', icon: Gauge, tone: booleanValue(knowledgeRoute.deepseekReady) ? 'success' : 'warning' },
            ]}
          />
        </ManagementSection>

        <div className="mgmt-grid-2">
          <ManagementSection title="最近一次前台建议" description="模型、RAG/Memory 和 Rime 来源保持可区分。">
            <dl className="mgmt-kv">
              <dt>可见候选</dt><dd>{stringValue(lastPrediction.visibleCandidate, '暂无候选')}</dd>
              <dt>触发方式</dt><dd>{stringValue(lastPrediction.triggerReason, '等待前台输入')}</dd>
              <dt>上下文来源</dt><dd>{stringValue(lastPrediction.contextSource, 'unknown')}</dd>
              <dt>延迟</dt><dd>{numberValue(lastPrediction.totalLatencyMs) ? `${Math.round(numberValue(lastPrediction.totalLatencyMs))} ms` : '暂无'}</dd>
              <dt>来源 lanes</dt><dd>{arrayRecords(lastPrediction.sourceTypes).length ? '结构化来源' : (Array.isArray(lastPrediction.sourceTypes) ? lastPrediction.sourceTypes.map(String).join(' · ') : '暂无')}</dd>
            </dl>
          </ManagementSection>

          <ManagementSection title="模型与知识路由" description="密钥只呈现可用性，不显示配置值。">
            <dl className="mgmt-kv">
              <dt>预测器</dt><dd>{stringValue(asRecord(modelStatus.predictor).provider, stringValue(asRecord(modelStatus.predictor).status, 'unknown'))}</dd>
              <dt>远程模型</dt><dd>{booleanValue(asRecord(modelStatus.activeRagRoute).remoteReady) ? 'configured' : 'not configured'}</dd>
              <dt>Notion submit</dt><dd>{booleanValue(asRecord(knowledgeRoute.notion).submitConfigured) ? 'configured' : 'not configured'}</dd>
              <dt>Notion poll</dt><dd>{booleanValue(asRecord(knowledgeRoute.notion).pollConfigured) ? 'configured' : 'not configured'}</dd>
            </dl>
          </ManagementSection>
        </div>

        <ManagementSection title="受控操作" description="以下操作当前为演练，不会修改本机状态。">
          <div className="mgmt-grid-2">
            <WorkflowAction
              actionId="overview.pause-ai"
              applyLabel={booleanValue(overview.aiPaused) ? '批准恢复' : '批准暂停'}
              description="暂停或恢复后提交预测，不影响普通 Rime 拼音输入。"
              mutationKey={['overview', 'mutation', 'pause-ai']}
              preview={[
                `当前状态：${booleanValue(overview.aiPaused) ? '已暂停' : '运行中'}`,
                '只改变 AI lane，不停止 Rime 基础候选。',
                '建议接口：runtime.action / stop_ai|resume_ai。',
              ]}
              risk="R1"
              title={booleanValue(overview.aiPaused) ? '恢复 AI lanes' : '暂停 AI lanes'}
            />
            <WorkflowAction
              actionId="overview.profile"
              description="应用标准模式的输入、记忆和 RAG 设置差异。"
              mutationKey={['overview', 'mutation', 'profile']}
              preview={[
                `当前 profile：${stringValue(overview.profile, 'unknown')}`,
                '预览 setting diff 后才允许写入。',
                '运行组件重启需求必须进入收据。',
              ]}
              risk="R1"
              title="切换运行 Profile"
            />
          </div>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function componentLabel(id: string): string {
  return ({
    inputMethod: '鼠须管输入源',
    sidecar: 'Sidecar',
    predictor: '本地预测',
    foregroundContext: '前台上下文',
    hybridRag: 'Hybrid RAG',
    memoryCompiler: '记忆编译',
    sqlite: 'SQLite',
  } as Record<string, string>)[id] ?? id;
}
