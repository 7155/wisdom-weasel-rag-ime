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
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, EmptyState } from '@/components/primitives';
import { useOverviewQueries } from './api';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
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
  const [refreshState, setRefreshState] = useState<'idle' | 'pending' | 'succeeded' | 'failed'>('idle');
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
  const componentCards = componentEntries.map((item) => ({
    item,
    state: componentState(item),
  }));
  const componentIssueCount = componentCards.filter(({ state }) => !state.ready).length;
  const error = [queries.snapshot.error, queries.health.error].find(Boolean) as Error | null;
  const pending = queries.snapshot.isPending || queries.health.isPending;
  const runtimeKnown = queries.agentRuntime.data !== undefined;
  const modelsKnown = queries.models.data !== undefined;
  const knowledgeKnown = queries.knowledgeRoute.data !== undefined;
  const auxiliaryErrors = [
    queries.agentRuntime.error ? '工作助手' : '',
    queries.models.error ? '本机模型与深度回答' : '',
    queries.knowledgeRoute.error ? '知识检索' : '',
  ].filter(Boolean);
  const auxiliaryFetching = queries.agentRuntime.isFetching
    || queries.models.isFetching
    || queries.knowledgeRoute.isFetching;
  const predictorReady = booleanValue(
    modelPredictor.ok,
    ['ready', 'healthy', 'configured', 'running'].includes(stringValue(modelPredictor.status).toLowerCase()),
  );
  const deepAnswerReady = booleanValue(asRecord(modelStatus.activeRagRoute).remoteReady);
  const runtimeReady = booleanValue(runtime.ok, stringValue(runtime.status) === 'ready');
  const knowledgeReady = booleanValue(knowledgeRoute.deepseekReady);
  const pendingReviewCount = numberValue(
    memory.pendingGovernedEvidenceCount,
    numberValue(memory.pendingCompileEvents),
  );
  const needsJudgementCount = numberValue(memory.governedNeedsReviewEvidenceCount);

  const refreshAuxiliary = () => void Promise.all([
    queries.agentRuntime.refetch(),
    queries.models.refetch(),
    queries.knowledgeRoute.refetch(),
  ]);

  const refresh = async () => {
    setRefreshState('pending');
    try {
      const results = await Promise.all([
        queries.snapshot.refetch(),
        queries.health.refetch(),
        queries.agentRuntime.refetch(),
        queries.models.refetch(),
        queries.knowledgeRoute.refetch(),
      ]);
      setRefreshState(results.some((result) => result.isError) ? 'failed' : 'succeeded');
    } catch {
      setRefreshState('failed');
    }
  };

  return (
    <ManagementPage
      actions={
        <>
          <span className="mgmt-sr-only" role="status">
            {refreshState === 'succeeded' ? '状态已更新' : refreshState === 'failed' ? '刷新失败，请重试' : ''}
          </span>
          <Button
            leadingIcon={<RefreshCw size={15} />}
            loading={refreshState === 'pending'
              || queries.snapshot.isFetching
              || queries.health.isFetching
              || auxiliaryFetching}
            onClick={() => void refresh()}
            size="small"
          >
            {refreshState === 'succeeded' ? '已刷新' : refreshState === 'failed' ? '刷新失败' : '刷新'}
          </Button>
        </>
      }
      description="常用入口、服务状态与待处理事项。"
      routeId="overview"
      title="概览"
    >
      <QueryState
        error={error}
        errorAction={<Button onClick={() => navigate('/diagnostics')}>打开问题排查</Button>}
        isPending={pending}
        onRetry={refresh}
      >
        {auxiliaryErrors.length ? (
          <div className="overview-auxiliary-state">
            <InlineNotice title="部分能力状态暂时未更新" tone="warning">
              {auxiliaryErrors.join('、')}没有返回最新状态。没有成功数据的项目会显示为“状态未知”，不会被当作未配置；已有数据会继续显示上次结果。
            </InlineNotice>
            <Button loading={auxiliaryFetching} onClick={refreshAuxiliary} size="small">
              重新检查能力状态
            </Button>
          </div>
        ) : null}

        <ManagementSection title="快捷入口">
          <div className="mgmt-grid-3 overview-primary-actions">
            <Button leadingIcon={<ListChecks size={16} />} onClick={() => navigate('/planning')} variant="primary">查看任务</Button>
            <Button leadingIcon={<MessageCircle size={16} />} onClick={() => navigate('/agent')}>开始对话</Button>
            <Button leadingIcon={<BrainCircuit size={16} />} onClick={() => navigate('/memory')}>整理记忆</Button>
          </div>
        </ManagementSection>

        <ManagementSection
          title="运行状态"
          description="本机输入、检索和记忆服务。"
          trailing={
            <StatusBadge
              label={!componentEntries.length
                ? '尚未读取'
                : componentIssueCount
                  ? `${componentIssueCount} 项需检查`
                  : `${componentEntries.length} 项已就绪`}
              tone={!componentEntries.length ? 'neutral' : componentIssueCount ? 'warning' : 'success'}
            />
          }
        >
          {componentCards.length ? (
            <ul aria-label="运行状态" className="overview-status-matrix">
              {componentCards.map(({ item, state }) => {
                const recovery = componentRecovery(stringValue(item.id));
                return (
                  <li className="overview-status-cell" data-state={state.kind} key={stringValue(item.id)}>
                    <div className="overview-status-cell__header">
                      <strong>{componentLabel(stringValue(item.id))}</strong>
                      <StatusBadge label={state.label} tone={state.tone} />
                    </div>
                    <p>{componentDetail(item)}</p>
                    {!state.ready ? (
                      <Button
                        className="overview-status-cell__action"
                        onClick={() => navigate(recovery.path)}
                        size="small"
                      >
                        {recovery.label}
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState
              action={<Button onClick={() => void refresh()} size="small">重新检查</Button>}
              description="服务已响应，但尚未返回组件状态。请重新检查；若仍无结果，可前往问题排查查看服务状态。"
              icon={Activity}
              title="暂无组件状态"
            />
          )}
        </ManagementSection>

        <ManagementSection title="记忆与知识" description="已保存的记忆、近期记录和检索能力。">
          <MetricStrip
            items={[
              {
                label: '工作助手',
                value: runtimeKnown
                  ? runtimeStatusLabel(stringValue(runtime.status))
                  : queries.agentRuntime.isPending ? '正在检查' : '状态未知',
                detail: runtimeKnown ? '当前状态' : '重新检查后确认',
                icon: Cpu,
                tone: runtimeKnown ? runtimeReady ? 'success' : 'warning' : 'neutral',
              },
              { label: '可用记忆', value: numberValue(memory.retrievalDocCount), detail: '需要时参考', icon: Database, tone: 'info' },
              { label: '长期记忆', value: numberValue(memory.memoryBookCount), detail: '持续整理', icon: BrainCircuit },
              { label: '近期记录', value: numberValue(memory.eventCount), detail: '只在本机', icon: Keyboard },
              { label: '待复核', value: pendingReviewCount, detail: pendingReviewCount ? `${needsJudgementCount} 条需要人工判断` : '无需处理', icon: Sparkles, tone: pendingReviewCount ? 'warning' : 'success' },
              {
                label: '知识检索',
                value: knowledgeKnown
                  ? knowledgeReady ? '可用' : '需配置'
                  : queries.knowledgeRoute.isPending ? '正在检查' : '状态未知',
                detail: knowledgeKnown
                  ? knowledgeReady ? '随时查询' : '配置后可用'
                  : '重新检查后确认',
                icon: Gauge,
                tone: knowledgeKnown ? knowledgeReady ? 'success' : 'warning' : 'neutral',
              },
            ]}
          />
          {(runtimeKnown && !runtimeReady) || pendingReviewCount > 0 || (knowledgeKnown && !knowledgeReady) ? (
            <div className="overview-capability-actions">
              {runtimeKnown && !runtimeReady ? <Button onClick={() => navigate('/diagnostics')} size="small">检查工作助手</Button> : null}
              {pendingReviewCount > 0 ? <Button onClick={() => navigate('/memory')} size="small">处理待复核</Button> : null}
              {knowledgeKnown && !knowledgeReady ? <Button onClick={() => navigate('/configuration')} size="small">配置知识检索</Button> : null}
            </div>
          ) : null}
        </ManagementSection>

        <div className="mgmt-grid-2">
          <ManagementSection title="最近一次输入建议" description="最近出现的建议及响应时间。">
            <dl className="mgmt-kv">
              <dt>建议内容</dt><dd>{stringValue(lastPrediction.visibleCandidate, '暂无建议')}</dd>
              <dt>出现时机</dt><dd>{triggerReasonLabel(stringValue(lastPrediction.triggerReason))}</dd>
              <dt>参考内容</dt><dd>{contextSourceLabel(stringValue(lastPrediction.contextSource))}</dd>
              <dt>响应时间</dt><dd>{numberValue(lastPrediction.totalLatencyMs) ? `${Math.round(numberValue(lastPrediction.totalLatencyMs))} ms` : '暂无'}</dd>
              <dt>来源</dt><dd>{Array.isArray(lastPrediction.sourceTypes) && lastPrediction.sourceTypes.length ? `${lastPrediction.sourceTypes.length} 类` : '暂无'}</dd>
            </dl>
          </ManagementSection>

          <ManagementSection title="模型服务" description="本机补全与深度回答。">
            <dl className="mgmt-kv">
              <dt>本机补全</dt><dd>{modelsKnown
                ? statusLabel(stringValue(modelPredictor.status, predictorReady ? 'ready' : 'unknown'))
                : queries.models.isPending ? '正在检查' : '状态未知'}</dd>
              <dt>深度回答</dt><dd>{modelsKnown
                ? deepAnswerReady ? '可用' : '尚未配置'
                : queries.models.isPending ? '正在检查' : '状态未知'}</dd>
            </dl>
            {modelsKnown && (!predictorReady || !deepAnswerReady) ? (
              <div className="overview-capability-actions">
                {!predictorReady ? <Button onClick={() => navigate('/diagnostics')} size="small">检查本机补全</Button> : null}
                {!deepAnswerReady ? <Button onClick={() => navigate('/configuration')} size="small">配置深度回答</Button> : null}
              </div>
            ) : null}
          </ManagementSection>
        </div>
      </QueryState>
    </ManagementPage>
  );
}

type ComponentState = {
  kind: 'ready' | 'attention' | 'unavailable' | 'disabled' | 'unknown';
  label: string;
  ready: boolean;
  tone: 'success' | 'warning' | 'neutral';
};

function componentState(item: Record<string, unknown>): ComponentState {
  const id = stringValue(item.id);
  const status = stringValue(item.status).trim().toLowerCase();

  if (/degraded|partial|warning/.test(status)) {
    return { kind: 'attention', label: '需检查', ready: false, tone: 'warning' };
  }
  if (/unavailable|blocked|failed|error/.test(status)) {
    if (id === 'voiceRecognition') {
      return { kind: 'unavailable', label: '未安装', ready: false, tone: 'warning' };
    }
    if (id === 'inputMethod') {
      return { kind: 'unavailable', label: '未选择', ready: false, tone: 'warning' };
    }
    if (id === 'foregroundContext') {
      return { kind: 'unknown', label: '未确认', ready: false, tone: 'neutral' };
    }
    if (id === 'deployment') {
      return { kind: 'attention', label: '需检查', ready: false, tone: 'warning' };
    }
    return { kind: 'unavailable', label: '不可用', ready: false, tone: 'warning' };
  }
  if (/disabled|stopped|off/.test(status)) {
    return { kind: 'disabled', label: '已关闭', ready: false, tone: 'neutral' };
  }
  if (/unknown|pending|starting|checking/.test(status)) {
    return { kind: 'unknown', label: '未确认', ready: false, tone: 'neutral' };
  }
  if (booleanValue(item.ok) && (!status || /ready|healthy|configured|running|ok/.test(status))) {
    return { kind: 'ready', label: '已就绪', ready: true, tone: 'success' };
  }
  return { kind: 'attention', label: '需检查', ready: false, tone: 'warning' };
}

function componentDetail(item: Record<string, unknown>): string {
  const id = stringValue(item.id);
  if (componentState(item).ready) {
    const readyDetail = ({
      inputMethod: '已选为当前输入法',
      sidecar: '本机补全服务已连接',
      predictor: '本机模型已载入',
      foregroundContext: '可以读取当前应用授权的上下文',
      assistantCandidateDelivery: '候选已在当前应用中显示',
      hybridRag: '知识检索已连接',
      memoryCompiler: '记忆整理已就绪',
      sqlite: '本机数据可以正常读取',
      deployment: '应用组件与当前版本一致',
      voiceAgent: '语音服务已连接',
      voiceMicrophone: '可以使用麦克风',
      voiceAccessibility: '可以将文字写入当前应用',
      voiceRecognition: '实时转写组件已就绪',
    } as Record<string, string>)[id];
    if (readyDetail) return readyDetail;
  }
  const detail = stringValue(item.detail);
  if (id === 'foregroundContext') {
    if (/尚无可信前台上下文来源证据/.test(detail)) return '尚未确认当前应用的文字读取状态';
    if (/证据已过期|缺少时间戳/.test(detail)) return '当前应用状态需要重新检查';
    if (/尚无上下文成功注入证据/.test(detail)) return '尚未确认当前应用内容已用于输入建议';
    if (/尚无提交文本匹配证据/.test(detail)) return '尚未确认输入内容与当前应用一致';
    if (/仅采集\s*\d+\s*字/.test(detail)) return '已读取少量当前应用文字，建议继续检查';
    if (/Sidecar\s*不可用/i.test(detail)) return '后台连接不可用';
    if (/上下文采集失败/.test(detail)) return '无法读取当前应用文字，请重新检查';
  }
  if (id === 'assistantCandidateDelivery') {
    if (/候选框源码能力不完整/.test(detail)) return '候选窗口尚未准备好';
    if (/已安装\s*Squirrel\s*前端与当前源码不一致/i.test(detail)) return '输入法组件需要更新';
    if (/输入法前端尚未与\s*Sidecar/i.test(detail)) return '输入法尚未连接后台服务';
    if (/尚无近期真实输入请求的候选生成凭证/.test(detail)) return '还没有可核对的近期输入结果';
    if (/候选已生成，但尚无近期前台显示凭证/.test(detail)) return '候选已生成，尚未确认显示成功';
  }
  if (id === 'voiceRecognition' && /未找到语音代理安装包/.test(detail)) {
    return '语音输入组件尚未安装';
  }
  return publicErrorText(detail, booleanValue(item.ok) ? '运行正常' : '请前往对应入口继续处理。');
}

function componentRecovery(id: string): { label: string; path: string } {
  if (id === 'inputMethod') return { label: '检查输入法', path: '/input' };
  if (id === 'hybridRag') return { label: '打开设置', path: '/configuration' };
  if (id === 'memoryCompiler') return { label: '打开记忆', path: '/memory' };
  if (id === 'voiceAgent' || id === 'voiceMicrophone' || id === 'voiceAccessibility' || id === 'voiceRecognition') {
    return { label: '检查语音输入', path: '/voice' };
  }
  if (id === 'foregroundContext') return { label: '查看前台检查', path: '/diagnostics' };
  return { label: '打开问题排查', path: '/diagnostics' };
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
    inputMethod: '输入法',
    sidecar: '后台连接',
    predictor: '本机补全',
    foregroundContext: '前台上下文',
    hybridRag: '知识检索',
    memoryCompiler: '记忆整理',
    sqlite: '本机存储',
    deployment: '安装状态',
    voiceAgent: '语音输入',
    voiceMicrophone: '麦克风权限',
    voiceAccessibility: '辅助功能权限',
    voiceRecognition: '实时转写',
    assistantCandidateDelivery: '候选显示验证',
  } as Record<string, string>)[id] ?? '未命名组件';
}
