import {
  Bot,
  Check,
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
import type { ReactNode } from 'react';
import { IconButton } from '@/components/primitives';
import type { RoomProjectionState, RoomTurnProjection } from '@/contracts/room-reducer';
import type { RoomSummary, RoomWorkItem } from '.';
import { useAgentLiveStore } from '../agent/state/live-store';
import '../agent/agent.css';

export function RoomStatusPanel({
  room,
  projection,
  open,
  onClose,
}: {
  room?: RoomSummary;
  projection: RoomProjectionState;
  open: boolean;
  onClose: () => void;
}) {
  const turn = latestRoomTurn(projection);
  const activities = turn?.activityIds.map((id) => projection.activitiesById[id]).filter(Boolean) ?? [];
  const messages = turn?.messageIds.map((id) => projection.messagesById[id]).filter(Boolean) ?? [];
  const attachments = new Set(messages.flatMap((message) => message.message?.attachments ?? []));
  const files = messages.flatMap((message) => message.message?.blocks ?? []).filter((block) => block.type === 'file');
  const deliveredArtifacts = messages.flatMap((message) => message.message?.blocks ?? []).filter((block) => block.type === 'diff' || (block.type === 'file' && Boolean(block.data.artifactId ?? block.data.receiptId)));
  const sharedArtifacts = (room?.artifacts ?? []).filter((artifact) => artifact.status === 'active');
  const activeTopics = (room?.topics ?? []).filter((topic) => topic.status === 'active');
  const workItems = room?.workItems ?? [];

  return (
    <aside aria-hidden={!open} aria-label="Room 状态" className="agent-status-panel room-status-panel" data-open={open} inert={open ? undefined : true}>
      <header>
        <span><strong>状态</strong><small>{turn ? roomTurnStatusLabel(turn.status) : '等待新回合'}</small></span>
        <IconButton icon={<PanelRightClose size={17} />} label="收起 Room 状态" onClick={onClose} tooltip />
      </header>
      <div className="agent-status-panel__body">
        <RoomStatusSection count={turn ? 1 : 0} icon={ListChecks} title="当前回合">
          {turn ? (
            <div className="agent-status-turn" data-state={turn.status}>
              <RoomTurnIcon status={turn.status} />
              <span><strong>{roomTurnStatusLabel(turn.status)}</strong><small>{messages.length} 条消息 · {activities.length} 条协作进展</small></span>
            </div>
          ) : <RoomStatusEmpty>还没有可展示的回合状态</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={workItems.filter((work) => !['done', 'failed', 'cancelled'].includes(work.state)).length} icon={ListChecks} title="责任账本">
          {workItems.length ? <div className="room-status-work">{workItems.slice(0, 8).map((work) => <RoomWorkRow key={work.id} room={room} work={work} />)}</div> : <RoomStatusEmpty>当前 Room 还没有责任交接</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={3} icon={ShieldCheck} title="责任边界">
          <div className="agent-status-files">
            <RoomStatusRow detail="普通消息、@ 和询问都不会转移最终责任" icon={ShieldCheck} title="A · 最终验收" />
            <RoomStatusRow detail="只有目标接受正式分派后才切换当前执行者" icon={GitBranch} title="R · 当前执行" />
            <RoomStatusRow detail="责任深度 3 · 根任务分派 6 · 最多返修 2 次" icon={ListChecks} title="防循环上限" />
          </div>
        </RoomStatusSection>

        <RoomStatusSection count={activities.length} icon={GitBranch} title="关键步骤">
          {activities.length ? <div className="room-status-activities">{activities.slice(-8).map((activity) => {
            const participant = room?.participants.find((item) => item.id === activity.participantId);
            return <div className="room-status-activity" data-state={activity.status} key={activity.id}><RoomActivityIcon status={activity.status} /><span><strong>{participant?.displayName ?? '协作成员'}</strong><small>{roomActivitySummary(activity.summary, activity.kind)}</small></span><i>{activity.status === 'running' ? '进行中' : activity.status === 'failed' ? '未完成' : '完成'}</i></div>;
          })}</div> : <RoomStatusEmpty>本轮还没有协作步骤</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={attachments.size + files.length} icon={Paperclip} title="附件与文件">
          {attachments.size || files.length ? <div className="agent-status-files">{attachments.size ? <RoomStatusRow detail="随 Room 消息保存" icon={Paperclip} title={`${attachments.size} 个受管附件`} /> : null}{files.map((block) => <RoomStatusRow detail={text(block.data.mimeType) || '文件'} icon={FileText} key={block.id} title={fileName(block.data)} />)}</div> : <RoomStatusEmpty>当前 Room 没有附件或文件</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={sharedArtifacts.length + deliveredArtifacts.length} icon={FolderKanban} title="共享资料与产物">
          {sharedArtifacts.length || deliveredArtifacts.length ? <div className="agent-status-files">{sharedArtifacts.map((artifact) => <RoomStatusRow detail={`${artifact.mediaType || '共享文件'} · ${pathName(artifact.path)}`} icon={FileText} key={artifact.id} title={artifact.displayName} />)}{deliveredArtifacts.map((block) => <RoomStatusRow detail={block.type === 'diff' ? '变更产物' : '文件产物'} icon={FolderKanban} key={block.id} title={fileName(block.data)} />)}</div> : <RoomStatusEmpty>当前 Room 还没有共享资料或产物</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={activeTopics.length} icon={GitBranch} title="话题">
          {activeTopics.length ? <div className="agent-status-files">{activeTopics.map((topic) => <RoomStatusRow detail={topic.id === room?.activeTopicId ? '当前话题' : topic.summary || '可切换话题'} icon={GitBranch} key={topic.id} title={topic.title} />)}</div> : <RoomStatusEmpty>当前 Room 还没有话题</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={room?.workspaceRoots?.length ?? 0} icon={FolderKanban} title="项目路径">
          {room?.workspaceRoots?.length ? <div className="agent-status-files">{room.workspaceRoots.map((path) => <RoomStatusRow detail={path} icon={FolderKanban} key={path} title={pathName(path)} />)}</div> : <RoomStatusEmpty>{room?.roomKind === 'roleplay' ? '角色群聊不绑定项目路径' : '这个旧 Room 尚未绑定项目路径'}</RoomStatusEmpty>}
        </RoomStatusSection>

        <RoomStatusSection count={room?.participants.filter((participant) => participant.status === 'active').length ?? 0} icon={Bot} title="协作成员上下文">
          {room?.participants.some((participant) => participant.status === 'active') ? <div className="room-status-participants">{room.participants.filter((participant) => participant.status === 'active').map((participant) => <RoomParticipantTelemetry key={participant.id} participant={participant} />)}</div> : <RoomStatusEmpty>当前 Room 还没有协作成员</RoomStatusEmpty>}
        </RoomStatusSection>

        {room ? (
          <a
            className="agent-status-observation-link"
            href={`#/observability?roomId=${encodeURIComponent(room.id)}`}
          >
            <Radar size={16} />
            <span><strong>运行观察</strong><small>查看本 Room 的路由、私信与协作轨迹</small></span>
            <GitBranch size={15} />
          </a>
        ) : null}
      </div>
    </aside>
  );
}

function RoomParticipantTelemetry({ participant }: { participant: NonNullable<RoomSummary['participants']>[number] }) {
  const telemetry = useAgentLiveStore((state) => state.projections[participant.sessionId]?.telemetry);
  if (!telemetry) {
    return <RoomStatusRow detail={`${collaborationRoleLabel(participant.collaborationRole)} · ${participant.status === 'active' ? '已加入' : '暂未参与'}`} icon={Bot} title={participant.displayName} />;
  }
  const context = telemetry.context;
  const cumulative = telemetry.cumulativeUsage;
  const promptTokens = cumulative.input + cumulative.cacheRead + cumulative.cacheWrite;
  const cachePercent = promptTokens > 0 ? Math.round((cumulative.cacheRead / promptTokens) * 100) : 0;
  const percent = context.percent === null ? null : Math.min(100, Math.max(0, context.percent));
  return (
    <article className="room-participant-telemetry" data-compacting={telemetry.isCompacting || undefined}>
      <header>
        <span><strong>{participant.displayName}</strong><small>{telemetry.model.name || telemetry.model.id} · {collaborationRoleLabel(participant.collaborationRole)}</small></span>
        <i data-state={participant.status}>{telemetry.isCompacting ? '压缩中' : participant.status === 'active' ? 'ACTIVE' : 'IDLE'}</i>
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

function RoomStatusSection({ icon: Icon, title, count, children }: { icon: LucideIcon; title: string; count: number; children: ReactNode }) {
  return <section className="agent-status-section"><header><Icon size={15} /><strong>{title}</strong>{count > 0 ? <span>{count}</span> : null}</header>{children}</section>;
}

function RoomStatusRow({ icon: Icon, title, detail }: { icon: LucideIcon; title: string; detail: string }) {
  return <div className="agent-status-row"><Icon size={14} /><span><strong>{title}</strong><small>{detail}</small></span></div>;
}

function RoomWorkRow({ room, work }: { room?: RoomSummary; work: RoomWorkItem }) {
  const ownerId = work.offeredToParticipantId || work.currentOwnerParticipantId;
  const owner = room?.participants.find((participant) => participant.id === ownerId)?.displayName ?? '待接收';
  const accountable = room?.participants.find((participant) => participant.id === work.accountableParticipantId)?.displayName ?? '未指定';
  const blocker = text(work.blocker.reason);
  return <div className="room-status-work__item" data-state={work.state}><RoomWorkIcon work={work} /><span><strong>{work.objective}</strong><small>{roomWorkStateLabel(work.state)} · A 最终负责：{accountable} · R 当前执行：{owner}{work.revision ? ` · 第 ${work.revision} 次修订` : ''}{blocker ? ` · ${blocker}` : ''}</small></span></div>;
}

function RoomStatusEmpty({ children }: { children: ReactNode }) {
  return <p className="agent-status-empty">{children}</p>;
}

function latestRoomTurn(projection: RoomProjectionState): RoomTurnProjection | undefined {
  return [...projection.turnOrder].reverse().map((id) => projection.turnsById[id]).find(Boolean);
}

function RoomTurnIcon({ status }: { status: RoomTurnProjection['status'] }) {
  if (status === 'queued' || status === 'running') return <LoaderCircle size={15} />;
  if (status === 'failed') return <TriangleAlert size={15} />;
  if (status === 'aborted') return <CircleDashed size={15} />;
  return <Check size={15} />;
}

function RoomActivityIcon({ status }: { status: 'running' | 'completed' | 'failed' }) {
  if (status === 'running') return <LoaderCircle size={14} />;
  if (status === 'failed') return <TriangleAlert size={14} />;
  return <Check size={14} />;
}

function RoomWorkIcon({ work }: { work: RoomWorkItem }) {
  if (work.state === 'queued' || work.state === 'active' || work.state === 'review') return <LoaderCircle size={14} />;
  if (work.state === 'blocked' || work.state === 'failed') return <TriangleAlert size={14} />;
  if (work.state === 'cancelled') return <CircleDashed size={14} />;
  return <Check size={14} />;
}

function roomTurnStatusLabel(status: RoomTurnProjection['status']): string {
  return ({ queued: '等待协作', running: '协作中', completed: '已完成', failed: '未完成', aborted: '已停止' } as const)[status];
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
function collaborationRoleLabel(role: string | undefined): string {
  if (role === 'coordinator') return '调控者';
  if (role === 'researcher') return '调研者';
  return '执行者';
}

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
