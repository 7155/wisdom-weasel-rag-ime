import { FileSearch, Network, RefreshCw, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, Field, SegmentedControl, Switch, TextArea } from '@/components/primitives';
import type { JsonValue } from '@/platform/transport';
import { knowledgeMutationPathIds, useKnowledgeMutationBoundary, useKnowledgeQueries } from './knowledge-workbench-api';
import { KnowledgeSessionWorkflow } from './knowledge-session-workflow';
import {
  KnowledgeEvidenceExplorer,
  KnowledgeRouteVisualization,
  knowledgeStageLabel,
  knowledgeStatusLabel,
  normalizeKnowledgeEvidence,
} from './KnowledgeVisualization';
import {
  InlineNotice,
  ManagementSection,
  MetricStrip,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  booleanValue,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import './knowledge-workbench.css';

const modes = [
  { value: 'knowledge_answer', label: '知识问答' },
  { value: 'long_form', label: '长文生成' },
  { value: 'recall', label: '帮我回忆' },
] as const;

export function PersonalKnowledgeWorkbench() {
  const [sessionId, setSessionId] = useState('');
  const [mode, setMode] = useState<(typeof modes)[number]['value']>('knowledge_answer');
  const [question, setQuestion] = useState('');
  const [context, setContext] = useState('');
  const [includeRemoteNotes, setIncludeRemoteNotes] = useState(false);
  const queries = useKnowledgeQueries(sessionId);
  const route = asRecord(queries.route.data);
  const notion = asRecord(route.notion);
  const session = asRecord(queries.session.data);
  const evidence = arrayRecords(session.evidence);
  const sources = arrayRecords(session.sources);
  const evidenceItems = useMemo(
    () => normalizeKnowledgeEvidence(evidence, sources),
    [evidence, sources],
  );
  const notionReady = booleanValue(notion.ready);
  const remoteNotesEnabled = includeRemoteNotes && notionReady;
  const mutationBoundary = useKnowledgeMutationBoundary();
  const startDraft: Record<string, JsonValue> = {
    question: question.trim(),
    context: context.trim(),
    mode,
    includeNotion: remoteNotesEnabled,
    generation: 1,
    clientId: 'control-center-web',
    project: 'wisdom-weasel-rag-ime',
    app: 'com.rag-ime.control',
    maxChars: mode === 'long_form' ? 8_000 : 4_000,
    latencyBudgetMs: 120_000,
  };
  const error = queries.route.error as Error | null;
  // Session polling is secondary content; do not unmount an active write workflow while a new session key loads.
  const pending = queries.route.isPending;
  const refresh = () => void Promise.all([
    queries.route.refetch(),
    ...(sessionId ? [queries.session.refetch()] : []),
  ]);

  return (
    <div className="memory-knowledge-workbench">
      <div className="memory-knowledge-workbench__header">
        <div><h2>个人知识整理</h2><span>搜索个人记忆，按需补充远程笔记，并审阅整理草案。</span></div>
        <Button leadingIcon={<RefreshCw size={15} />} loading={queries.route.isFetching || queries.session.isFetching} onClick={refresh} size="small">刷新</Button>
      </div>
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="知识来源" description="先使用本机证据；回答生成和远程笔记只在你启动任务时使用。">
          <MetricStrip items={[
            { label: '本机证据', value: '优先使用', detail: '记忆与知识库', icon: FileSearch, tone: 'success' },
            { label: '回答生成', value: booleanValue(route.deepseekReady) ? '可用' : '暂不可用', detail: '仅在明确任务中启用', icon: Sparkles, tone: booleanValue(route.deepseekReady) ? 'success' : 'warning' },
            { label: '远程笔记', value: notionReady ? '可选' : '未连接', detail: notionReady ? '由你逐次开启' : '不会发送请求', icon: Network, tone: notionReady ? 'success' : 'neutral' },
            { label: '当前任务', value: knowledgeStatusLabel(stringValue(session.status)), detail: knowledgeStageLabel(stringValue(session.stage)), icon: RefreshCw, tone: ['ready', 'completed'].includes(stringValue(session.status)) ? 'success' : stringValue(session.status) === 'error' ? 'warning' : 'info' },
          ]} />
          <InlineNotice title="来源边界" tone="info">本机记忆与知识库、远程笔记、回答生成的来源分开呈现。</InlineNotice>
          <KnowledgeRouteVisualization route={route} session={session} />
        </ManagementSection>

        <ManagementSection title="开始知识任务" description="选择任务类型，确认范围后开始；运行中可以随时取消。">
          <div className="mgmt-stack">
            <SegmentedControl aria-label="知识任务模式" items={modes} onValueChange={setMode} value={mode} />
            <div className="mgmt-grid-2">
              <Field htmlFor="knowledge-question" label="问题" required>
                <TextArea id="knowledge-question" onChange={(event) => setQuestion(event.target.value)} placeholder="输入一个明确的知识任务" rows={5} value={question} />
              </Field>
              <Field htmlFor="knowledge-context" label="补充上下文">
                <TextArea id="knowledge-context" onChange={(event) => setContext(event.target.value)} placeholder="可选，例如限定时间、项目或希望覆盖的范围" rows={5} value={context} />
              </Field>
            </div>
            <Switch
              checked={remoteNotesEnabled}
              description={notionReady ? '只在本次任务中补充远程笔记；不会改变后续任务。' : '远程笔记尚未连接，本次任务只使用本机知识。'}
              disabled={!notionReady}
              label="补充远程笔记"
              onCheckedChange={setIncludeRemoteNotes}
            />
            <KnowledgeSessionWorkflow
              availability={mutationBoundary.routeAvailability(
                [knowledgeMutationPathIds.start, knowledgeMutationPathIds.cancel],
                !question.trim()
                  ? '填写明确的问题后才能预览任务。'
                  : !booleanValue(route.deepseekReady)
                    ? '当前知识生成路由尚未就绪。'
                    : '',
              )}
              description="先检查敏感内容，再按所选模式运行检索或生成。"
              draft={startDraft}
              draftKey={JSON.stringify(startDraft)}
              onCancel={(nextSessionId) => mutationBoundary.request({
                pathId: knowledgeMutationPathIds.cancel,
                body: { sessionId: nextSessionId },
              })}
              onSessionStarted={setSessionId}
              onStart={(boundDraft) => mutationBoundary.request({
                pathId: knowledgeMutationPathIds.start,
                body: boundDraft,
              })}
              previewLines={[
                `任务类型：${modes.find((item) => item.value === mode)?.label ?? '知识任务'}`,
                `你的问题：${question.trim() || '未填写'}`,
                `补充上下文：${context.trim() ? `${context.trim().length} 字` : '无'}`,
                remoteNotesEnabled ? '本次会补充远程笔记。' : '本次只使用本机知识与回答生成。',
              ]}
              risk="R1"
              title="启动知识任务"
            />
          </div>
        </ManagementSection>

        <ManagementSection title="当前任务" description="进度、回答和证据会在任务开始后自动更新。" trailing={sessionId ? <Button loading={queries.session.isFetching} onClick={() => void queries.session.refetch()} size="small" variant="quiet">刷新结果</Button> : null}>
          {sessionId ? (
            <div className="mgmt-stack">
              {queries.session.error ? (
                <InlineNotice title="暂时无法更新任务" tone="warning">
                  {publicErrorText(queries.session.error, '当前任务仍然保留；暂时无法取得最新进度，请稍后刷新。')}
                </InlineNotice>
              ) : null}
              <dl className="mgmt-kv">
                <dt>状态</dt><dd><StatusBadge label={knowledgeStatusLabel(stringValue(session.status))} tone={stringValue(session.status) === 'ready' ? 'success' : stringValue(session.status) === 'error' ? 'danger' : 'info'} /></dd>
                <dt>进度</dt><dd>{knowledgeStageLabel(stringValue(session.stage))}</dd>
                <dt>回答</dt><dd>{stringValue(session.answer, stringValue(session.localDraft, queries.session.error ? '上一次内容仍然保留。' : '任务仍在处理中。'))}</dd>
              </dl>
            </div>
          ) : <InlineNotice title="还没有开始任务" tone="info">在上方填写问题并确认后，这里会显示处理进度与回答。</InlineNotice>}
        </ManagementSection>

        <ManagementSection title="召回证据与引用" trailing={<StatusBadge label={`${evidenceItems.length} 条`} tone="info" />}>
          <KnowledgeEvidenceExplorer items={evidenceItems} />
        </ManagementSection>
      </QueryState>
    </div>
  );
}
