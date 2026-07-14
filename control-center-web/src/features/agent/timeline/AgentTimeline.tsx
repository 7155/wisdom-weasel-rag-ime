import { ArrowUpRight, Sparkles } from 'lucide-react';
import { Virtuoso } from 'react-virtuoso';
import { useShallow } from 'zustand/react/shallow';
import { Button } from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { ActivitySummary } from './ActivitySummary';
import { AgentBlocks } from './BlockRenderer';
import { PersonaAvatar, type PersonaPresence } from './PersonaAvatar';
import { useAgentLiveStore } from '../state/live-store';

export function AgentTimeline({
  sessionId,
  persona,
  onSuggestion,
  onApprovalDecision,
}: {
  sessionId: string;
  persona?: AgentPersonaV1;
  onSuggestion: (value: string) => void;
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
}) {
  const turnOrder = useAgentLiveStore((state) => state.projections[sessionId]?.turnOrder ?? emptyIds);
  if (turnOrder.length === 0) return <AgentWelcome persona={persona} onSuggestion={onSuggestion} />;
  return (
    <div className="agent-timeline" aria-label="对话时间线">
      <Virtuoso
        data={turnOrder}
        followOutput="smooth"
        increaseViewportBy={{ top: 500, bottom: 500 }}
        itemContent={(_index, turnId) => (
          <AgentTurn
            key={turnId}
            sessionId={sessionId}
            turnId={turnId}
            persona={persona}
            onApprovalDecision={onApprovalDecision}
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
  onApprovalDecision,
}: {
  sessionId: string;
  turnId: string;
  persona?: AgentPersonaV1;
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
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
  if (!turn) return null;
  const presence: PersonaPresence = turn.status === 'failed' ? 'warning' : turn.status === 'running' || turn.status === 'waiting' ? 'thinking' : 'done';
  return (
    <article className="agent-turn" data-turn-status={turn.status}>
      {userIds.map((messageId) => <MessageView key={messageId} sessionId={sessionId} messageId={messageId} user />)}
      {assistantIds.length > 0 || activities.length > 0 ? (
        <div className="agent-assistant-turn">
          <PersonaAvatar persona={persona} presence={presence} />
          <div className="agent-assistant-turn__body">
            <header><strong>{persona?.displayName ?? '智鼬'}</strong><span>{turnStatusLabel(turn.status)}</span></header>
            <ActivitySummary activities={activities} onApprovalDecision={onApprovalDecision} />
            {assistantIds.map((messageId) => <MessageView key={messageId} sessionId={sessionId} messageId={messageId} />)}
            {turn.failure ? <p className="agent-turn__failure">{turn.failure}</p> : null}
          </div>
        </div>
      ) : null}
    </article>
  );
}

function MessageView({ sessionId, messageId, user = false }: { sessionId: string; messageId: string; user?: boolean }) {
  const message = useAgentLiveStore((state) => state.projections[sessionId]?.messagesById[messageId]);
  if (!message) return null;
  return user ? (
    <div className="agent-user-message" data-status={message.status}>
      <AgentBlocks blocks={message.blocks} />
      {message.attachments.length ? <small>{message.attachments.length} 个附件</small> : null}
    </div>
  ) : (
    <div className="agent-assistant-message" data-status={message.status}>
      <AgentBlocks blocks={message.blocks} />
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
