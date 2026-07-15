import {
  Activity,
  BrainCircuit,
  Cpu,
  Database,
  Gauge,
  Keyboard,
  ListChecks,
  MessageCircle,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Button, EmptyState } from '@/components/primitives';
import { useOverviewQueries } from './api';
import {
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  asRecord,
  booleanValue,
  numberValue,
  publicErrorText,
  stringValue,
} from './management-ui';

export function OverviewFeature() {
  const navigate = useNavigate();
  const queries = useOverviewQueries();
  const overview = asRecord(queries.snapshot.data);
  const memory = asRecord(overview.memory);
  const lastPrediction = asRecord(overview.lastPrediction);
  const runtime = asRecord(queries.agentRuntime.data);
  const modelStatus = asRecord(queries.models.data);
  const modelPredictor = asRecord(modelStatus.predictor);
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
      description="输入法、陪伴对话、个人记忆与知识检索的实时状态。"
      eyebrow="工作台"
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
                detail: componentDetail(item),
                meta: statusLabel(stringValue(item.status)),
                status: (
                  <StatusBadge
                    label={booleanValue(item.ok) ? '正常' : '需检查'}
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
              { label: '可召回文档', value: numberValue(memory.retrievalDocCount), detail: '本地检索', icon: Database, tone: 'info' },
              { label: '主题记忆', value: numberValue(memory.memoryBookCount), detail: '长期整理', icon: BrainCircuit },
              { label: '待整理', value: numberValue(memory.pendingCompileEvents), detail: '等待归档', icon: Sparkles, tone: numberValue(memory.pendingCompileEvents) ? 'warning' : 'success' },
              { label: '陪伴对话', value: runtimeStatusLabel(stringValue(runtime.status)), detail: '本机 Agent', icon: Cpu, tone: booleanValue(runtime.ok, stringValue(runtime.status) === 'ready') ? 'success' : 'warning' },
              { label: '知识检索', value: booleanValue(knowledgeRoute.deepseekReady) ? '可用' : '需配置', detail: '按需查询', icon: Gauge, tone: booleanValue(knowledgeRoute.deepseekReady) ? 'success' : 'warning' },
            ]}
          />
        </ManagementSection>

        <div className="mgmt-grid-2">
          <ManagementSection title="最近一次前台建议" description="本机模型、知识检索、个人记忆和输入法原生候选分别记录。">
            <dl className="mgmt-kv">
              <dt>可见候选</dt><dd>{stringValue(lastPrediction.visibleCandidate, '暂无候选')}</dd>
              <dt>触发方式</dt><dd>{triggerReasonLabel(stringValue(lastPrediction.triggerReason))}</dd>
              <dt>上下文来源</dt><dd>{contextSourceLabel(stringValue(lastPrediction.contextSource))}</dd>
              <dt>延迟</dt><dd>{numberValue(lastPrediction.totalLatencyMs) ? `${Math.round(numberValue(lastPrediction.totalLatencyMs))} ms` : '暂无'}</dd>
              <dt>信息来源</dt><dd>{Array.isArray(lastPrediction.sourceTypes) && lastPrediction.sourceTypes.length ? `${lastPrediction.sourceTypes.length} 类` : '暂无'}</dd>
            </dl>
          </ManagementSection>

          <ManagementSection title="模型与知识路由" description="密钥只呈现可用性，不显示配置值。">
            <dl className="mgmt-kv">
              <dt>本地预测</dt><dd>{statusLabel(stringValue(modelPredictor.status, booleanValue(modelPredictor.ok) ? 'ready' : 'unknown'))}</dd>
              <dt>远程模型</dt><dd>{booleanValue(asRecord(modelStatus.activeRagRoute).remoteReady) ? '可用' : '未配置'}</dd>
              <dt>Notion 提交</dt><dd>{booleanValue(asRecord(knowledgeRoute.notion).submitConfigured) ? '可用' : '未配置'}</dd>
              <dt>Notion 读取</dt><dd>{booleanValue(asRecord(knowledgeRoute.notion).pollConfigured) ? '可用' : '未配置'}</dd>
            </dl>
          </ManagementSection>
        </div>

        <ManagementSection title="接下来做什么" description="直接进入已经接通本机服务的工作区。">
          <div className="mgmt-grid-3">
            <Button leadingIcon={<ListChecks size={16} />} onClick={() => navigate('/planning')} variant="primary">看看今天的规划</Button>
            <Button leadingIcon={<MessageCircle size={16} />} onClick={() => navigate('/agent')}>继续和智鼬聊</Button>
            <Button leadingIcon={<BrainCircuit size={16} />} onClick={() => navigate('/memory')}>整理长期记忆</Button>
          </div>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function componentDetail(item: Record<string, unknown>): string {
  const detail = stringValue(item.detail);
  return publicErrorText(detail, booleanValue(item.ok) ? '运行正常' : '打开诊断查看原因');
}

function statusLabel(value: string): string {
  return ({
    ready: '可用',
    healthy: '正常',
    configured: '已配置',
    running: '运行中',
    disabled: '已关闭',
    degraded: '需检查',
    blocked: '受阻',
    unavailable: '不可用',
    unknown: '等待状态',
  } as Record<string, string>)[value.toLowerCase()] ?? (value ? '状态已更新' : '等待状态');
}

function runtimeStatusLabel(value: string): string {
  return ({ ready: '可用', busy: '回复中', starting: '启动中', disabled: '已关闭', not_installed: '未安装', needs_configuration: '需配置' } as Record<string, string>)[value] ?? '等待状态';
}

function contextSourceLabel(value: string): string {
  return ({ memory: '个人记忆', rag: '知识检索', recent: '近期输入', none: '未使用额外上下文' } as Record<string, string>)[value.toLowerCase()] ?? (value ? '已使用上下文' : '暂无');
}

function triggerReasonLabel(value: string): string {
  return ({
    post_commit: '完成输入后',
    active_rag: '主动查询',
    manual: '手动请求',
    voice: '语音输入',
  } as Record<string, string>)[value.toLowerCase()] ?? (value ? '由当前输入触发' : '等待前台输入');
}

function componentLabel(id: string): string {
  return ({
    inputMethod: '当前输入法',
    sidecar: '后台服务',
    predictor: '本地预测',
    foregroundContext: '前台上下文',
    hybridRag: '知识检索',
    memoryCompiler: '记忆整理',
    sqlite: '本机数据库',
  } as Record<string, string>)[id] ?? '其他服务';
}
