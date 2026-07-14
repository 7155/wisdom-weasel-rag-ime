import { BookOpenCheck, FileSearch, Network, RefreshCw, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Button, EmptyState, Field, Input, SegmentedControl, TextArea } from '@/components/primitives';
import { useKnowledgeQueries } from './api';
import {
  DataTable,
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  QueryState,
  StatusBadge,
  WorkflowAction,
  arrayRecords,
  asRecord,
  booleanValue,
  configuredLabel,
  stringValue,
} from '@/features/overview/management-ui';

const modes = [
  { value: 'knowledge_answer', label: '知识问答' },
  { value: 'long_form', label: '长文生成' },
  { value: 'recall', label: '帮我回忆' },
  { value: 'organize_database', label: '整理数据库' },
] as const;

export function KnowledgeFeature() {
  const [sessionId, setSessionId] = useState('');
  const [mode, setMode] = useState<(typeof modes)[number]['value']>('knowledge_answer');
  const [question, setQuestion] = useState('');
  const [context, setContext] = useState('');
  const queries = useKnowledgeQueries(sessionId);
  const route = asRecord(queries.route.data);
  const notion = asRecord(route.notion);
  const session = asRecord(queries.session.data);
  const evidence = arrayRecords(session.evidence);
  const sources = arrayRecords(session.sources);
  const result = asRecord(session.result);
  const plan = asRecord(result.plan);
  const error = (queries.route.error ?? queries.session.error) as Error | null;
  const pending = queries.route.isPending || queries.session.isPending;
  const refresh = () => void Promise.all([queries.route.refetch(), queries.session.refetch()]);

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={queries.session.isFetching} onClick={refresh} size="small">刷新</Button>}
      description="搜索本地知识、运行深度任务、查看证据并审阅整理草案。"
      eyebrow="KNOWLEDGE"
      routeId="knowledge"
      title="知识库"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="路由就绪度" description="本地检索可独立工作；远程知识生成只在显式任务中启用。">
          <MetricStrip items={[
            { label: 'DeepSeek', value: booleanValue(route.deepseekReady) ? 'ready' : 'blocked', detail: 'explicit generation', icon: Sparkles, tone: booleanValue(route.deepseekReady) ? 'success' : 'warning' },
            { label: 'Notion submit', value: configuredLabel(notion.submitConfigured), detail: 'remote knowledge', icon: Network, tone: booleanValue(notion.submitConfigured) ? 'success' : 'warning' },
            { label: 'Notion poll', value: configuredLabel(notion.pollConfigured), detail: stringValue(notion.pollMode, 'unknown'), icon: RefreshCw, tone: booleanValue(notion.pollConfigured) ? 'success' : 'warning' },
            { label: '当前任务', value: stringValue(session.status, 'idle'), detail: stringValue(session.stage, 'no stage'), icon: FileSearch, tone: ['ready', 'idle'].includes(stringValue(session.status)) ? 'success' : stringValue(session.status) === 'blocked' ? 'warning' : 'info' },
          ]} />
          <InlineNotice title="来源边界" tone="info">本地 Memory/RAG、Notion 与模型生成来源分开呈现。</InlineNotice>
        </ManagementSection>

        <ManagementSection title="Query Lab 与深度工作台" description="预览查询模式、范围与来源开关；当前启动操作为演练。">
          <div className="mgmt-stack">
            <SegmentedControl aria-label="知识任务模式" items={modes} onValueChange={setMode} value={mode} />
            <div className="mgmt-grid-2">
              <Field htmlFor="knowledge-question" label={mode === 'organize_database' ? '整理指令' : '问题'} required>
                <TextArea id="knowledge-question" onChange={(event) => setQuestion(event.target.value)} placeholder="输入一个明确的知识任务" rows={5} value={question} />
              </Field>
              <Field htmlFor="knowledge-context" label="补充上下文">
                <TextArea id="knowledge-context" onChange={(event) => setContext(event.target.value)} placeholder="可选；敏感字段会被 gate 阻止" rows={5} value={context} />
              </Field>
            </div>
            <WorkflowAction
              actionId="knowledge.start"
              description="先检查敏感内容，再按所选模式运行检索或生成。"
              mutationKey={['knowledge', 'mutation', 'start']}
              preview={[
                `mode：${mode}`,
                `question：${question.trim() || '未填写'}`,
                `context：${context.trim() ? `${context.trim().length} 字` : '无'}`,
                '只有明确选择远程知识时才使用 Notion 或远程生成。',
              ]}
              risk={mode === 'organize_database' ? 'R2' : 'R1'}
              title="启动知识任务"
            />
          </div>
        </ManagementSection>

        <ManagementSection title="任务追踪" description="输入任务 ID 以查看进度、结果与证据来源。">
          <div className="mgmt-input-row">
            <Input aria-label="知识任务 Session ID" onChange={(event) => setSessionId(event.target.value)} placeholder="sessionId" value={sessionId} />
            <Button onClick={() => void queries.session.refetch()} size="small">读取状态</Button>
          </div>
          <dl className="mgmt-kv" style={{ marginTop: 12 }}>
            <dt>Session</dt><dd>{stringValue(session.sessionId, sessionId || '未指定')}</dd>
            <dt>状态</dt><dd><StatusBadge label={stringValue(session.status, 'idle')} tone={stringValue(session.status) === 'ready' ? 'success' : stringValue(session.status) === 'error' ? 'danger' : 'info'} /></dd>
            <dt>阶段</dt><dd>{stringValue(session.stage, '暂无')}</dd>
            <dt>回答</dt><dd>{stringValue(session.answer, stringValue(session.localDraft, '暂无'))}</dd>
          </dl>
        </ManagementSection>

        <ManagementSection title="召回证据与引用" trailing={<StatusBadge label={`${evidence.length + sources.length} 条`} tone="info" />}>
          {evidence.length || sources.length ? (
            <DataTable caption="知识召回证据" columns={[
              { key: 'sourceId', label: 'Source ID', width: '18%' },
              { key: 'title', label: '标题', width: '24%' },
              { key: 'excerpt', label: '证据' },
              { key: 'sourceType', label: '来源', width: '14%' },
            ]} rows={[...evidence, ...sources].map((item, index) => ({
              ...item,
              sourceId: item.sourceId ?? item.id ?? `source-${index + 1}`,
              title: item.title ?? item.label ?? item.url ?? '未命名来源',
              excerpt: item.excerpt ?? item.text ?? item.preview ?? item.summary,
              sourceType: item.sourceType ?? item.kind ?? item.provider ?? 'local',
            }))} />
          ) : <EmptyState description="当前任务没有返回可追溯证据。" icon={BookOpenCheck} title="暂无证据" />}
        </ManagementSection>

        <ManagementSection title="数据库整理草案" description="逐项审阅后再应用，应用结果可回滚。">
          <InlineNotice title="当前整理任务" tone={stringValue(plan.runId) ? 'info' : 'warning'}>
            {stringValue(plan.runId) ? `${stringValue(plan.runId)} · ${stringValue(plan.status, 'draft')}` : '当前没有数据库整理任务。'}
          </InlineNotice>
          <div className="mgmt-grid-2">
            <WorkflowAction
              actionId="knowledge.database.apply"
              description="应用已选择的整理项，写入正式记忆库。"
              mutationKey={['knowledge', 'mutation', 'database-apply']}
              preview={[`任务 ID：${stringValue(plan.runId, '尚未生成')}`, '只应用已选择的整理项。', '完成后显示成功、跳过和失败项目。']}
              risk="R2"
              title="应用整理草案"
            />
            <WorkflowAction
              actionId="knowledge.database.rollback"
              applyLabel="批准回滚"
              description="回滚本次任务已应用的数据库整理。"
              mutationKey={['knowledge', 'mutation', 'database-rollback']}
              preview={[`任务 ID：${stringValue(plan.runId, '尚未生成')}`, '回滚只影响本次任务写入的变更。', '保留历史记录和回滚收据。']}
              risk="R2"
              title="回滚整理任务"
            />
          </div>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}
