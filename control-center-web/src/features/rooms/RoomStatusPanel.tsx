import {
  Bot,
  Check,
  ChevronRight,
  CircleDashed,
  FileText,
  FolderKanban,
  GitBranch,
  ListChecks,
  LoaderCircle,
  Paperclip,
  PanelRightClose,
  Radar,
  ShieldCheck,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react';
import { forwardRef, useId, useState, type ReactNode } from 'react';
import { IconButton } from '@/components/primitives';
import type {
  RoomActivityProjection,
  RoomMessageProjection,
  RoomProjectionState,
  RoomTurnProjection,
} from '@/contracts/room-reducer';
import type { RoomSummary, RoomWorkItem } from './room-types';
import { useAgentLiveStore } from '../agent/state/live-store';
import { roomCollaborationRoleLabel } from './room-copy';
import { roomActivityNeedsSessionAction } from './runtime/room-execution-lanes';
import { roomProjection, useRoomLiveStore } from './state/live-store';
import { publicToolName } from '../agent/tool-presentation';
import '../agent/agent.css';

export const RoomStatusPanel = forwardRef<HTMLElement, {
  room?: RoomSummary;
  roomId?: string;
  projection?: RoomProjectionState;
  open: boolean;
  modal?: boolean;
  onClose: () => void;
}>(function RoomStatusPanel({
  room,
  roomId = '',
  projection: providedProjection,
  open,
  modal = false,
  onClose,
}, ref) {
  useRoomLiveStore((state) => (
    open && !providedProjection
      ? state.roomRevisions[roomId || room?.id || ''] ?? 0
      : 0
  ));
  const projection = providedProjection ?? roomProjection(roomId || room?.id || '');
  const turn = latestRoomTurn(projection);
  const activities = turn?.activityIds.map((id) => projection.activitiesById[id]).filter(Boolean) ?? [];
  const messages = turn?.messageIds.map((id) => projection.messagesById[id]).filter(Boolean) ?? [];
  const attachments = new Set(messages.flatMap((message) => message.message?.attachments ?? []));
  const files = messages.flatMap((message) => message.message?.blocks ?? []).filter((block) => block.type === 'file');
  const deliveredArtifacts = messages.flatMap((message) => message.message?.blocks ?? []).filter((block) => block.type === 'diff' || (block.type === 'file' && Boolean(block.data.mediaId ?? block.data.artifactId ?? block.data.receiptId)));
  const sharedArtifacts = (room?.artifacts ?? []).filter((artifact) => artifact.status === 'active');
  const activeTopics = (room?.topics ?? []).filter((topic) => topic.status === 'active');
  const workItems = room?.workItems ?? [];
  const visibleWorkItems = [...workItems]
    .sort((left, right) => roomWorkPriority(left.state) - roomWorkPriority(right.state))
    .slice(0, 8);
  const activityGroups = collapseRoomStatusActivities(activities).slice(-8);
  const publicMessageCount = messages.filter((message) => message.projectionKind !== 'execution').length;

  const projectedStatus = roomProjectedStatus(turn, activities, messages);
  return (
    <aside
      ref={ref}
      aria-hidden={!open}
      aria-label="协作进展"
      aria-modal={modal || undefined}
      className="agent-status-panel room-status-panel"
      data-open={open}
      inert={open ? undefined : true}
      role={modal ? 'dialog' : undefined}
      tabIndex={-1}
    >
      <header>
        <span><strong>协作进展</strong><small>{turn ? roomProjectedStatusLabel(projectedStatus) : '等你开始新一轮'}</small></span>
        <IconButton icon={<PanelRightClose size={17} />} label="收起进展面板" onClick={onClose} tooltip />
      </header>
      <div className="agent-status-panel__body">
        <RoomStatusSection count={turn ? 1 : 0} icon={ListChecks} title="当前回合">
          {turn ? (
            <div className="agent-status-turn" data-state={projectedStatus}>
              <RoomTurnIcon status={projectedStatus} />
              <span>
                <strong>{roomProjectedStatusLabel(projectedStatus)}</strong>
                <small>{publicMessageCount ? `${publicMessageCount} 条公开消息` : '还没有公开消息'}</small>
                <span className="room-status-turn__metrics">
                  <i>{turn.participantIds.length} 位伙伴</i>
                  <i>{activities.length} 个过程步骤</i>
                </span>
              </span>
            </div>
          ) : <RoomStatusEmpty>发出消息后，这里会显示本轮进展</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={workItems.filter((work) => !['done', 'failed', 'cancelled'].includes(work.state)).length} icon={ListChecks} title="任务分工">
          {visibleWorkItems.length
            ? <div className="room-status-work">{visibleWorkItems.map((work) => <RoomWorkRow key={work.id} room={room} work={work} />)}</div>
            : <RoomStatusEmpty>任务开始后，这里会显示谁在做、谁来验收</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={3} defaultOpen={false} icon={ShieldCheck} title="协作规则">
          <div className="agent-status-files">
            <RoomStatusRow detail="普通消息、点名和询问都不会悄悄转移最终责任" icon={ShieldCheck} title="最终验收人保持明确" />
            <RoomStatusRow detail="只有伙伴正式接手任务后，当前执行者才会改变" icon={GitBranch} title="交接必须被接受" />
            <RoomStatusRow detail="最多分派 6 次、深入 3 层、返修 2 次，超出后会停下来求助" icon={ListChecks} title="不会无限循环" />
          </div>
        </RoomStatusSection>

        <RoomStatusSection
          count={activityGroups.length}
          defaultOpen={activities.some((activity) => ['running', 'waiting', 'failed'].includes(roomActivityStatus(activity)))}
          icon={GitBranch}
          title="关键步骤"
        >
          {activityGroups.length ? <div className="room-status-activities">{activityGroups.map((group) => {
            const activity = group.activity;
            const participant = room?.participants.find((item) => item.id === activity.participantId);
            const presentation = roomStatusActivityPresentation(activity);
            const status = roomActivityStatus(activity);
            return <div className="room-status-activity" data-state={status} key={group.key}>
              <RoomActivityIcon status={status} />
              <span>
                <span className="room-status-activity__heading">
                  <strong>{participant?.displayName ?? '协作成员'} · {presentation.title}</strong>
                  <i>{roomActivityStatusLabel(status)}</i>
                </span>
                <small>{presentation.detail}{group.count > 1 ? ` · 合并 ${group.count} 次更新` : ''}</small>
              </span>
            </div>;
          })}</div> : <RoomStatusEmpty>本轮还没有协作步骤</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={attachments.size + files.length} defaultOpen={false} icon={Paperclip} title="附件与文件">
          {attachments.size || files.length ? <div className="agent-status-files">{attachments.size ? <RoomStatusRow detail="随协作消息保存在本机" icon={Paperclip} title={`${attachments.size} 个消息附件`} /> : null}{files.map((block) => <RoomStatusRow detail={text(block.data.mimeType) || '文件'} icon={FileText} key={block.id} title={fileName(block.data)} />)}</div> : <RoomStatusEmpty>还没有分享附件或文件</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={sharedArtifacts.length + deliveredArtifacts.length} defaultOpen={false} icon={FolderKanban} title="共享资料与产物">
          {sharedArtifacts.length || deliveredArtifacts.length ? <div className="agent-status-files">{sharedArtifacts.map((artifact) => <RoomStatusRow detail={`${artifact.mediaType || '共享文件'} · ${pathName(artifact.path)}`} icon={FileText} key={artifact.id} title={artifact.displayName} />)}{deliveredArtifacts.map((block) => <RoomStatusRow detail={block.type === 'diff' ? '变更产物' : '文件产物'} icon={FolderKanban} key={block.id} title={fileName(block.data)} />)}</div> : <RoomStatusEmpty>还没有共享资料或交付物</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={activeTopics.length} defaultOpen={false} icon={GitBranch} title="话题">
          {activeTopics.length ? <div className="agent-status-files">{activeTopics.map((topic) => <RoomStatusRow detail={topic.id === room?.activeTopicId ? '当前话题' : topic.summary || '可切换话题'} icon={GitBranch} key={topic.id} title={topic.title} />)}</div> : <RoomStatusEmpty>还没有单独整理话题</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={room?.workspaceRoots?.length ?? 0} defaultOpen={false} icon={FolderKanban} title="工作目录">
          {room?.workspaceRoots?.length ? <div className="agent-status-files">{room.workspaceRoots.map((path) => <RoomStatusRow detail={path} icon={FolderKanban} key={path} title={pathName(path)} />)}</div> : <RoomStatusEmpty>{room?.roomKind === 'roleplay' ? '一起聊聊不会访问项目目录' : '这个协作空间还没有工作目录'}</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={room?.participants.filter((participant) => participant.status === 'active').length ?? 0} defaultOpen={false} icon={Bot} title="伙伴状态">
          {room?.participants.some((participant) => participant.status === 'active') ? <div className="room-status-participants">{room.participants.filter((participant) => participant.status === 'active').map((participant) => <RoomParticipantTelemetry key={participant.id} participant={participant} />)}</div> : <RoomStatusEmpty>还没有伙伴加入</RoomStatusEmpty>}
        </RoomStatusSection>

        {room ? (
          <a
            className="agent-status-observation-link"
            href={`#/observability?roomId=${encodeURIComponent(room.id)}`}
          >
            <Radar size={16} />
            <span><strong>查看详细运行记录</strong><small>检查消息路由、伙伴通信和任务轨迹</small></span>
            <GitBranch size={15} />
          </a>
        ) : null}
      </div>
    </aside>
  );
});

function RoomParticipantTelemetry({ participant }: { participant: NonNullable<RoomSummary['participants']>[number] }) {
  const telemetry = useAgentLiveStore((state) => state.projections[participant.sessionId]?.telemetry);
  if (!telemetry) {
    return <RoomStatusRow detail={`${roomCollaborationRoleLabel(participant.collaborationRole)} · ${participant.status === 'active' ? '已加入' : '暂未参与'}`} icon={Bot} title={participant.displayName} />;
  }
  const context = telemetry.context;
  const cumulative = telemetry.cumulativeUsage;
  const promptTokens = cumulative.input + cumulative.cacheRead + cumulative.cacheWrite;
  const cachePercent = promptTokens > 0 ? Math.round((cumulative.cacheRead / promptTokens) * 100) : 0;
  const percent = context.percent === null ? null : Math.min(100, Math.max(0, context.percent));
  return (
    <article className="room-participant-telemetry" data-compacting={telemetry.isCompacting || undefined}>
      <header>
        <span><strong>{participant.displayName}</strong><small>{telemetry.model.name || telemetry.model.id} · {roomCollaborationRoleLabel(participant.collaborationRole)}</small></span>
        <i data-state={participant.status}>{telemetry.isCompacting ? '整理上下文' : participant.status === 'active' ? '已加入' : '暂未参与'}</i>
      </header>
      <div className="room-participant-telemetry__numbers">
        <span title="累计提示 Token">{roomTokenCount(promptTokens)} 输入</span>
        <span title="累计输出 Token">{roomTokenCount(cumulative.output)} 输出</span>
        <strong title="累计缓存命中率">缓存 {cachePercent}%</strong>
      </div>
      <div className="room-participant-telemetry__bar" aria-label={percent === null ? '上下文占用待校准' : `上下文已使用 ${Math.round(percent)}%`}>
        <span style={{ width: `${percent ?? 0}%` }} />
        <b>{percent === null ? '待校准' : `${Math.round(percent)}%`}</b>
      </div>
      <p>{context.tokensUntilCompact === null ? '下一轮响应后校准' : `距自动压缩约 ${roomTokenCount(context.tokensUntilCompact)}`}</p>
    </article>
  );
}

function roomTokenCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 100_000 ? 0 : 1)}K`;
  return String(Math.max(0, Math.round(value)));
}

function RoomStatusSection({
  icon: Icon,
  title,
  count,
  children,
  defaultOpen = true,
}: {
  icon: LucideIcon;
  title: string;
  count: number;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();
  return <section className="agent-status-section" data-open={open}>
    <header>
      <button
        aria-controls={contentId}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <Icon size={15} />
        <strong>{title}</strong>
        {count > 0 ? <span>{count}</span> : null}
        <ChevronRight className="agent-status-section__chevron" size={14} />
      </button>
    </header>
    <div
      aria-hidden={!open}
      className="agent-status-section__content"
      id={contentId}
      inert={!open ? true : undefined}
    >
      <div>{children}</div>
    </div>
  </section>;
}

function RoomStatusRow({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail: string }) {
  return <div className="agent-status-row"><Icon size={14} /><span><strong>{title}</strong><small>{detail}</small></span></div>;
}

function RoomWorkRow({ room, work }: { room?: RoomSummary; work: RoomWorkItem }) {
  const ownerId = work.offeredToParticipantId || work.currentOwnerParticipantId;
  const owner = room?.participants.find((participant) => participant.id === ownerId)?.displayName ?? '待接收';
  const accountable = room?.participants.find((participant) => participant.id === work.accountableParticipantId)?.displayName ?? '未指定';
  const blocker = text(work.blocker.reason);
  const showFullObjective = work.objective.trim().length > 180 || work.objective.includes('\n');
  return <article className="room-status-work__item" data-state={work.state}>
    <RoomWorkIcon work={work} />
    <div>
      <header>
        <strong>{work.objective}</strong>
        <em>{roomWorkStateLabel(work.state)}</em>
      </header>
      <div className="room-status-work__owners" aria-label="任务责任">
        <span><small>{work.state === 'queued' ? '接收' : '执行'}</small><b>{owner}</b></span>
        <span><small>验收</small><b>{accountable}</b></span>
      </div>
      {work.expectedOutput ? <p><span>交付</span>{work.expectedOutput}</p> : null}
      {work.acceptanceCriteria.length ? <p><span>验收</span>{work.acceptanceCriteria.length} 项标准</p> : null}
      {work.revision ? <p><span>修订</span>第 {work.revision} 次</p> : null}
      {blocker ? <p className="room-status-work__blocker"><span>阻塞</span>{blocker}</p> : null}
      {showFullObjective ? <details className="room-status-work__full"><summary>查看完整任务</summary><p>{work.objective}</p></details> : null}
    </div>
  </article>;
}

function RoomStatusEmpty({ children }: { children: ReactNode }) {
  return <p className="agent-status-empty">{children}</p>;
}

function latestRoomTurn(projection: RoomProjectionState): RoomTurnProjection | undefined {
  return [...projection.turnOrder].reverse().map((id) => projection.turnsById[id]).find(Boolean);
}

type RoomProjectedStatus =
  | 'queued'
  | 'running'
  | 'waiting_review'
  | 'waiting_select'
  | 'waiting_input'
  | 'blocked'
  | 'completed'
  | 'handed_off'
  | 'waiting'
  | 'aborted'
  | 'idle';

function RoomTurnIcon({ status }: { status: RoomProjectedStatus }) {
  if (status === 'queued' || status === 'running') return <LoaderCircle size={15} />;
  if (status === 'blocked') return <TriangleAlert size={15} />;
  if (status === 'handed_off') return <GitBranch size={15} />;
  if (status === 'aborted' || status === 'waiting' || status.startsWith('waiting_') || status === 'idle') return <CircleDashed size={15} />;
  return <Check size={15} />;
}

function RoomActivityIcon({ status }: { status: RoomActivityProjection['status'] }) {
  if (status === 'running') return <LoaderCircle size={14} />;
  if (status === 'waiting') return <CircleDashed size={14} />;
  if (status === 'failed') return <TriangleAlert size={14} />;
  return <Check size={14} />;
}

function RoomWorkIcon({ work }: { work: RoomWorkItem }) {
  if (work.state === 'queued' || work.state === 'active' || work.state === 'review') return <LoaderCircle size={14} />;
  if (work.state === 'blocked' || work.state === 'failed') return <TriangleAlert size={14} />;
  if (work.state === 'cancelled') return <CircleDashed size={14} />;
  return <Check size={14} />;
}

interface RoomStatusActivityGroup {
  key: string;
  activity: RoomActivityProjection;
  count: number;
}

function collapseRoomStatusActivities(
  activities: RoomActivityProjection[],
): RoomStatusActivityGroup[] {
  const groups: RoomStatusActivityGroup[] = [];
  for (const activity of activities) {
    const toolCallId = text(activity.payload.toolCallId);
    const fingerprint = toolCallId
      ? [activity.participantId, 'tool', toolCallId].join(':')
      : [
          activity.participantId,
          activity.kind,
          text(activity.payload.activityKind),
          roomActivitySummary(activity.summary, activity.kind),
        ].join(':');
    const previous = groups.at(-1);
    if (previous?.key.startsWith(`${fingerprint}:`)) {
      previous.activity = activity;
      previous.count += 1;
      continue;
    }
    groups.push({
      key: `${fingerprint}:${groups.length}`,
      activity,
      count: 1,
    });
  }
  return groups;
}

function roomStatusActivityPresentation(
  activity: RoomActivityProjection,
): { title: string; detail: string } {
  const sourceEventType = text(activity.payload.sourceEventType);
  const summary = roomActivitySummary(activity.summary, activity.kind);
  if (sourceEventType.startsWith('tool_')) {
    const tool = publicToolName(
      text(activity.payload.toolName),
      text(activity.payload.displayName),
    );
    return {
      title: tool,
      detail: summary === '协作进度已经更新' || summary === tool
        ? `${tool}${roomActivityStatus(activity) === 'completed' ? '已返回' : '正在处理'}`
        : summary,
    };
  }
  if (activity.kind === 'route_decision') {
    return { title: '任务已分派', detail: summary };
  }
  if (text(activity.payload.activityKind) === 'intercom') {
    return { title: '伙伴沟通', detail: summary };
  }
  if (text(activity.payload.approvalId)) {
    return { title: '安全审批', detail: summary };
  }
  if (activity.kind === 'participant_status') {
    return { title: '状态同步', detail: summary };
  }
  return { title: '进展更新', detail: summary };
}

function roomActivityStatus(
  activity: RoomActivityProjection,
): RoomActivityProjection['status'] {
  const automatic = activity.payload.automatic === true
    || text(activity.payload.decisionMode) === 'model'
    || text(activity.payload.mode) === 'model';
  const decision = text(activity.payload.decision)
    || text((activity.payload.approvalModelDecision as Record<string, unknown> | undefined)?.decision);
  const state = text(activity.payload.resolutionState || activity.payload.state);
  if (
    automatic
    && !decision
    && !['approved', 'rejected', 'applied', 'resolved', 'cancelled'].includes(state)
  ) return 'running';
  return activity.status;
}

function roomActivityStatusLabel(status: RoomActivityProjection['status']): string {
  return {
    running: '进行中',
    waiting: '等待处理',
    failed: '未完成',
    completed: '完成',
  }[status];
}

function roomWorkPriority(state: RoomWorkItem['state']): number {
  return {
    active: 0,
    review: 1,
    blocked: 2,
    queued: 3,
    failed: 4,
    done: 5,
    cancelled: 6,
  }[state];
}

function roomProjectedStatus(
  turn: RoomTurnProjection | undefined,
  activities: RoomActivityProjection[],
  messages: RoomMessageProjection[],
): RoomProjectedStatus {
  if (!turn) return 'idle';
  const pending = [...activities].reverse().find(roomActivityNeedsSessionAction);
  if (pending) {
    const requestKind = text(pending.payload.requestKind);
    if (
      requestKind === 'plan_review'
      || requestKind === 'memory_review'
      || Boolean(text(pending.payload.approvalId))
    ) return 'waiting_review';
    if (text(pending.payload.method) === 'select' || Array.isArray(pending.payload.options)) {
      return 'waiting_select';
    }
    return 'waiting_input';
  }
  if (turn.status === 'failed') return 'blocked';
  if (turn.status === 'aborted') return 'aborted';
  const outcome = messages.reduce((kind, message) => (
    ['result', 'handoff', 'wait', 'blocked'].includes(message.postKind ?? '')
      ? message.postKind ?? kind
      : kind
  ), '');
  if (outcome === 'result') return 'completed';
  if (outcome === 'handoff') return 'handed_off';
  if (outcome === 'wait') return 'waiting';
  if (outcome === 'blocked') return 'blocked';
  if (activities.some((activity) => activity.status === 'failed')) return 'blocked';
  if (turn.status === 'queued') return 'queued';
  if (turn.status === 'running') return 'running';
  if (turn.status === 'completed') return 'completed';
  return 'idle';
}

function roomProjectedStatusLabel(status: RoomProjectedStatus): string {
  return {
    queued: '等待协作',
    running: '协作中',
    waiting_review: '等待审阅',
    waiting_select: '等待选择',
    waiting_input: '等待回答',
    blocked: '已阻塞',
    completed: '已完成',
    handed_off: '已转交',
    waiting: '等待继续',
    aborted: '已停止',
    idle: '等待后续',
  }[status];
}

function roomActivitySummary(summary: string, kind: string): string {
  const value = summary.trim();
  if (value && value !== kind && !/\b(?:participant|route|tool|turn)_[a-z_]+\b/i.test(value)) return value;
  if (kind === 'route_decision') return '已确定本轮负责角色';
  if (kind === 'participant_status') return '协作状态已经同步';
  return '协作进度已经更新';
}

function fileName(data: Record<string, unknown>): string {
  return text(data.fileName ?? data.name ?? data.title) || '未命名文件';
}

function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
function pathName(path: string): string { return path.split('/').filter(Boolean).at(-1) ?? path; }
function roomWorkStateLabel(state: RoomWorkItem['state']): string {
  return {
    queued: '待接收',
    active: '执行中',
    review: '待验收',
    blocked: '已阻塞',
    done: '已完成',
    failed: '未完成',
    cancelled: '已取消',
  }[state];
}
