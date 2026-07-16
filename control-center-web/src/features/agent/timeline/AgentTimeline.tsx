import { ArrowUpRight, BrainCircuit, CircleDashed, GitBranch, LoaderCircle, RefreshCcw, Sparkles, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { useShallow } from 'zustand/react/shallow';
import { Button, IconButton } from '@/components/primitives';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { ActivitySummary } from './ActivitySummary';
import { AgentBlocks } from './BlockRenderer';
import { PersonaAvatar, type PersonaPresence } from './PersonaAvatar';
import { useAgentLiveStore } from '../state/live-store';
import { publicAgentErrorText } from '../public-error';

export function AgentTimeline({
  sessionId,
  persona,
  modelSelectionAvailable,
  onSuggestion,
  onRetryTurn,
  onSwitchModel,
  onApprovalDecision,
  forkAvailable = false,
  forkingEntryId = '',
  onForkFromMessage,
}: {
  sessionId: string;
  persona?: AgentPersonaV1;
  modelSelectionAvailable: boolean;
  onSuggestion: (value: string) => void;
  onRetryTurn: (turnId: string) => void;
  onSwitchModel: () => void;
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  forkAvailable?: boolean;
  forkingEntryId?: string;
  onForkFromMessage?: (entryId: string, message: string) => void;
}) {
  const turnOrder = useAgentLiveStore(useShallow((state) => {
    const projection = state.projections[sessionId];
    if (!projection) return emptyIds;
    return projection.turnOrder.filter((turnId) => {
      const turn = projection.turnsById[turnId];
      return Boolean(turn && (turn.messageIds.length > 0 || turn.activityIds.length > 0));
    });
  }));
  if (turnOrder.length === 0) return <AgentWelcome persona={persona} onSuggestion={onSuggestion} />;
  return (
    <div className="agent-timeline" aria-label="对话时间线">
      <Virtuoso
        key={sessionId}
        data={turnOrder}
        followOutput="smooth"
        initialTopMostItemIndex={{ index: 'LAST', align: 'end' }}
        increaseViewportBy={{ top: 500, bottom: 500 }}
        itemContent={(_index, turnId) => (
          <AgentTurn
            key={turnId}
            sessionId={sessionId}
            turnId={turnId}
            persona={persona}
            modelSelectionAvailable={modelSelectionAvailable}
            onRetryTurn={onRetryTurn}
            onSwitchModel={onSwitchModel}
            onApprovalDecision={onApprovalDecision}
            forkAvailable={forkAvailable}
            forkingEntryId={forkingEntryId}
            onForkFromMessage={onForkFromMessage}
          />
        )}
      />
    </div>
  );
}

export function AgentTurn({
  sessionId,
  turnId,
  persona,
  modelSelectionAvailable = false,
  onRetryTurn,
  onSwitchModel,
  onApprovalDecision,
  forkAvailable = false,
  forkingEntryId = '',
  onForkFromMessage,
}: {
  sessionId: string;
  turnId: string;
  persona?: AgentPersonaV1;
  modelSelectionAvailable?: boolean;
  onRetryTurn?: (turnId: string) => void;
  onSwitchModel?: () => void;
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
  forkAvailable?: boolean;
  forkingEntryId?: string;
  onForkFromMessage?: (entryId: string, message: string) => void;
}) {
  const turn = useAgentLiveStore((state) => state.projections[sessionId]?.turnsById[turnId]);
  const userIds = useAgentLiveStore(useShallow((state) => {
    const projection = state.projections[sessionId];
    return (projection?.turnsById[turnId]?.messageIds ?? []).filter((id) => projection?.messagesById[id]?.role === 'user');
  }));
  const assistantIds = useAgentLiveStore(useShallow((state) => {
    const projection = state.projections[sessionId];
    return (projection?.turnsById[turnId]?.messageIds ?? []).filter((id) => projection?.messagesById[id]?.role === 'assistant');
  }));
  const activities = useAgentLiveStore(useShallow((state) => {
    const projection = state.projections[sessionId];
    return (projection?.turnsById[turnId]?.activityIds ?? []).map((id) => projection?.activitiesById[id]).filter(Boolean);
  }));
  const blockFailure = useAgentLiveStore((state) => {
    const projection = state.projections[sessionId];
    const messageIds = projection?.turnsById[turnId]?.messageIds ?? [];
    for (const messageId of messageIds) {
      const message = projection?.messagesById[messageId];
      if (message?.role !== 'assistant') continue;
      const errorBlock = message.blocks.find((block) => block.type === 'error');
      const messageText = text(errorBlock?.data.message ?? errorBlock?.data.summary);
      if (messageText) return messageText;
    }
    return '';
  });
  if (!turn) return null;
  const rawFailure = turn.failure || blockFailure;
  const failure = turn.status === 'failed' ? publicAgentErrorText(rawFailure) : '';
  const showWorking = turn.status === 'queued' || turn.status === 'running';
  const presence: PersonaPresence = turn.status === 'failed' ? 'warning' : turn.status === 'running' || turn.status === 'waiting' ? 'thinking' : 'done';
  return (
    <article className="agent-turn" data-turn-status={turn.status}>
      {userIds.map((messageId) => <MessageView key={messageId} sessionId={sessionId} messageId={messageId} user forkAvailable={forkAvailable} forking={forkingEntryId === messageId} onForkFromMessage={onForkFromMessage} />)}
      {assistantIds.length > 0 || activities.length > 0 || failure || showWorking ? (
        <div className="agent-assistant-turn">
          <PersonaAvatar persona={persona} presence={showWorking ? 'thinking' : presence} />
          <div className="agent-assistant-turn__body">
            <header><strong>{persona?.displayName ?? '智鼬'}</strong><span>{showWorking ? '正在处理' : turnStatusLabel(turn.status)}</span></header>
            {showWorking ? <AssistantWorkingState activities={activities} startedAtMs={turn.createdAtMs} /> : null}
            <ActivitySummary activities={activities} onApprovalDecision={onApprovalDecision} />
            {assistantIds.map((messageId) => <MessageView key={messageId} sessionId={sessionId} messageId={messageId} />)}
            {failure ? (
              <div className="agent-turn__failure" role="alert">
                <TriangleAlert size={17} />
                <span><strong>本轮未完成</strong><small>{failure}</small></span>
                {onRetryTurn && onSwitchModel ? (
                  <div className="agent-turn__failure-actions">
                    <Button size="small" variant="primary" leadingIcon={<RefreshCcw size={14} />} onClick={() => onRetryTurn(turnId)}>重试本轮</Button>
                    <Button size="small" variant="quiet" leadingIcon={<BrainCircuit size={14} />} disabled={!modelSelectionAvailable} onClick={onSwitchModel}>切换模型</Button>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </article>
  );
}

function AssistantWorkingState({
  activities,
  startedAtMs,
}: {
  activities: AgentActivityProjection[];
  startedAtMs: number;
}) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  const detail = useMemo(() => workingDetail(activities), [activities]);
  return (
    <div className="agent-assistant-pending" role="status" aria-live="polite">
      <CircleDashed aria-hidden="true" size={17} />
      <span><strong>思考中 <time>{formatElapsed(nowMs - startedAtMs)}</time></strong><small>{detail}</small></span>
      <i className="agent-working-dots" aria-hidden="true"><b /><b /><b /></i>
    </div>
  );
}

function MessageView({
  sessionId,
  messageId,
  user = false,
  forkAvailable = false,
  forking = false,
  onForkFromMessage,
}: {
  sessionId: string;
  messageId: string;
  user?: boolean;
  forkAvailable?: boolean;
  forking?: boolean;
  onForkFromMessage?: (entryId: string, message: string) => void;
}) {
  const message = useAgentLiveStore((state) => state.projections[sessionId]?.messagesById[messageId]);
  if (!message) return null;
  const visibleBlocks = user ? message.blocks : message.blocks.filter((block) => block.type !== 'error');
  const messageText = visibleBlocks.map((block) => text(block.data.text)).filter(Boolean).join('\n').trim();
  const canFork = user && forkAvailable && message.status === 'completed' && !messageId.startsWith('local:') && Boolean(messageText) && Boolean(onForkFromMessage);
  return user ? (
    <div className="agent-user-message-shell" data-actions={canFork || undefined}>
      <div className="agent-user-message" data-status={message.status}>
        <AgentBlocks blocks={visibleBlocks} />
        {message.attachments.length ? <small>{message.attachments.length} 个附件</small> : null}
      </div>
      {canFork ? (
        <div className="agent-message-actions">
          <IconButton
            label="从这条消息创建分支"
            icon={forking ? <LoaderCircle className="ui-spin" size={14} /> : <GitBranch size={14} />}
            size="small"
            disabled={forking}
            aria-busy={forking || undefined}
            onClick={() => onForkFromMessage?.(messageId, messageText)}
            tooltip
            tooltipSide="left"
          />
        </div>
      ) : null}
    </div>
  ) : (
    <div className="agent-assistant-message" data-status={message.status}>
      <AgentBlocks blocks={visibleBlocks} />
      {message.status === 'streaming' ? <span className="agent-streaming-cursor" aria-label="正在生成" /> : null}
    </div>
  );
}

function AgentWelcome({ persona, onSuggestion }: { persona?: AgentPersonaV1; onSuggestion: (value: string) => void }) {
  const suggestions = [
    ['回顾今天', '结合近期对话，帮我回顾今天的进展。'],
    ['检查运行状态', '检查输入法、模型、RAG 与 Memory 的当前状态。'],
    ['整理下一步', '根据当前项目上下文，整理三个可以立刻推进的下一步。'],
  ];
  return (
    <div className="agent-welcome">
      <PersonaAvatar persona={persona} size="hero" />
      <div><h2>今天想先从哪里开始？</h2><p>{persona?.tagline ?? '连续对话、检索和整理都从这里开始。'}</p></div>
      <div className="agent-welcome__suggestions">
        {suggestions.map(([title, prompt]) => (
          <Button key={title} variant="quiet" leadingIcon={<Sparkles size={15} />} trailingIcon={<ArrowUpRight size={14} />} onClick={() => onSuggestion(prompt)}>{title}</Button>
        ))}
      </div>
    </div>
  );
}

function turnStatusLabel(status: string): string {
  if (status === 'running') return '正在响应';
  if (status === 'waiting') return '等待确认';
  if (status === 'failed') return '本轮失败';
  if (status === 'queued') return '排队中';
  if (status === 'aborted') return '已停止';
  return '已完成';
}

const emptyIds: string[] = [];

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function workingDetail(activities: AgentActivityProjection[]): string {
  const latest = [...activities].reverse().find((activity) => activity.status === 'running');
  const tool = text(latest?.payload.toolName ?? latest?.payload.toolId).toLowerCase();
  if (tool.includes('memory')) return '正在读取并整理相关记忆，工具明细会实时显示在下方。';
  if (tool.includes('knowledge') || tool.includes('rag')) return '正在检索知识库，工具明细会实时显示在下方。';
  if (tool.includes('planning')) return '正在整理计划与下一步。';
  if (latest) return '正在执行工具，进度和结果会实时显示在下方。';
  return '消息已收到，正在组织本轮响应。';
}

function formatElapsed(durationMs: number): string {
  const seconds = Math.max(0, Math.floor(durationMs / 1_000));
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return minutes > 0 ? `${minutes}分 ${remaining}秒` : `${remaining}秒`;
}
