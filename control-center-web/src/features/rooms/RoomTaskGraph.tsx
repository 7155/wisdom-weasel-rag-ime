import {
  Bot,
  ChevronDown,
  CircleAlert,
  CircleCheck,
  Clock3,
  ExternalLink,
  FileText,
  GitBranch,
  ListChecks,
  MessageSquareText,
  Network,
  ShieldCheck,
  Sparkles,
  Wrench,
} from 'lucide-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import type {
  RoomActivityProjection,
  RoomMessageProjection,
  RoomProjectionState,
} from '@/contracts/room-reducer';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import { SubagentLaunchPanel } from '@/features/agent/delegation/SubagentLaunchPanel';
import type { AgentWorkflowStateV1 } from '@/contracts/generated/agent-workflow-state.v1';
import type { WorkDocumentV1 } from '@/contracts/work-documents';
import { MarkdownBody } from '@/features/agent/timeline/MarkdownRenderer';
import { SmoothDisclosureReveal } from '@/features/agent/timeline/SmoothDisclosureReveal';
import { toggleDisclosurePreservingAnchor } from '@/features/agent/timeline/disclosure-anchor';
import { publicToolName } from '@/features/agent/tool-presentation';
import {
  isContractInvalid,
  subagentFailurePolicy,
  subagentStateLabel,
  subagentTemplateLabel,
} from '@/features/agent/status/subagent-presentation';
import type { RoomExecutionOverviewItem } from './runtime/room-execution-lanes';
import {
  selectRoomTurnExecution,
  type RoomExecutionLane,
} from './runtime/room-execution-lanes';
import type { RoomArtifact, RoomSummary, RoomWorkItem, RoomWorkState } from './room-types';
import {
  type RoomTaskSessionFact,
  useRoomTaskSessionFacts,
} from './use-room-task-session-facts';
import { RoomModulePanel } from './RoomModulePanel';
import { roomCollaborationRoleLabel, roomPlanetName } from './room-copy';
import { useRoomSurfaceModules } from './room-surface-modules';
import {
  useRoomNavigationDocuments,
  type RoomNavigationDocuments,
} from './use-room-navigation-documents';

type CockpitState = 'waiting' | 'active' | 'review' | 'complete' | 'attention' | 'contract' | 'recovery' | 'cancelled';

interface WorkRecoveryProjection {
  kind: 'sealed' | 'acceptance' | 'receipt' | 'repair';
  label: string;
  detail: string;
}

interface PartnerProjection {
  participantId: string;
  name: string;
  sessionId: string;
  assignment: string;
  state: CockpitState;
  activities: RoomActivityProjection[];
  lanes: RoomExecutionLane[];
  messages: RoomMessageProjection[];
  workItems: RoomWorkItem[];
}

interface PlanProjection {
  label: string;
  completed: number;
  total: number;
  tasks: Array<{
    id: string;
    phase: string;
    content: string;
    state: CockpitState;
    stateLabel: string;
  }>;
}

interface RoomChildDelegationProjection {
  id: string;
  parentParticipantId: string;
  targetParticipantId: string;
  targetName: string;
  task: string;
  expectedOutput: string;
  acceptanceCriteria: string[];
  waveId: string;
  phaseName: string;
  parallelIndex?: number;
  parallelSize?: number;
  summary: string;
  state: CockpitState;
}

export interface RoomPeerRelation {
  id: string;
  sourceParticipantId: string;
  sourceName: string;
  targetParticipantId: string;
  targetName: string;
  kind: 'send' | 'ask' | 'reply';
  state: CockpitState;
  content: string;
  replyTo: string;
}

interface FlowTaskItem {
  id: string;
  objective: string;
  partner: PartnerProjection;
  state: CockpitState;
  lane?: RoomExecutionLane;
  expectedOutput?: string;
  acceptanceCriteria?: string[];
  resultSummary?: string;
  workItem?: RoomWorkItem;
  document?: WorkDocumentV1;
}

interface FlowStage {
  id: string;
  label: string;
  parallel: boolean;
  waveId?: string;
  items: FlowTaskItem[];
}

const EMPTY_NAVIGATION_DOCUMENTS: RoomNavigationDocuments = {
  items: [],
  status: 'idle',
};

export function ConnectedRoomTaskGraph(props: {
  room: RoomSummary;
  runtimeWorkItems: readonly RoomExecutionOverviewItem[];
  projection?: RoomProjectionState;
}) {
  const navigationDocuments = useRoomNavigationDocuments(props.room);
  return <RoomTaskGraph {...props} navigationDocuments={navigationDocuments} />;
}

export function RoomTaskGraph({
  room,
  runtimeWorkItems,
  projection,
  navigationDocuments = EMPTY_NAVIGATION_DOCUMENTS,
}: {
  room: RoomSummary;
  runtimeWorkItems: readonly RoomExecutionOverviewItem[];
  projection?: RoomProjectionState;
  navigationDocuments?: RoomNavigationDocuments;
}) {
  const runtime = runtimeWorkItems.at(0);
  const turn = runtime && projection ? projection.turnsById[runtime.id] : undefined;
  const rootId = turn?.rootId || runtime?.id || latestRoomWorkItem(room)?.rootTurnId || '';
  const execution = runtime && projection
    ? selectRoomTurnExecution(projection, runtime.id)
    : undefined;
  const partners = buildPartnerProjections(room, runtime, execution?.lanes ?? [], projection);
  const childDelegations = roomChildDelegations(execution?.activities ?? [], room);
  const peerRelations = projection
    ? roomPeerRelationsFromProjection(projection, room)
    : roomPeerRelations(execution?.activities ?? [], room);
  const sessionFacts = useRoomTaskSessionFacts(partners.map((partner) => partner.sessionId));
  const plan = roomPlan(sessionFacts, room.id, rootId);
  const goal = roomGoal(room, runtime, sessionFacts, rootId);
  const rootReply = findRootReply(projection, runtime?.id, room.moderatorParticipantId);
  const completedPartners = partners.filter((partner) => partner.state === 'complete').length;
  const overallState = roomOverallState(partners, rootReply, runtime?.status);
  const modules = useRoomSurfaceModules();
  const knowledgeRefs = roomKnowledgeRefs(room);

  return <div className="room-cockpit" data-state={overallState}>
    <main className="room-cockpit__document">
      <section className="room-cockpit__goal" id="room-goal">
        <div className="room-cockpit__goal-heading">
          <h1>{goal}</h1>
          <StatePill state={overallState} />
          <RoomModulePanel
            definitions={modules.definitions}
            isMounted={modules.isMounted}
            onReset={modules.reset}
            onSetMounted={modules.setMounted}
          />
        </div>
        <p>{room.description?.trim() || 'Room 会把运行事实整理成目标、分工、流转和公开交付。'}</p>
      </section>

      {modules.isMounted('participant-rail') ? <RoomQuickIndex
        hasNavigation={modules.isMounted('plan') && Boolean(plan || navigationDocuments.items.length || room.artifacts?.length || knowledgeRefs.length)}
        navigationCount={navigationDocuments.items.length + (room.artifacts?.length ?? 0) + knowledgeRefs.length}
        partners={partners}
        plan={plan}
        rootReply={rootReply}
        showAssignments={modules.isMounted('assignments')}
        showFlow={modules.isMounted('flow')}
        showPartnerWork={modules.isMounted('partner-work')}
      /> : null}

      {modules.isMounted('plan') && (plan || navigationDocuments.items.length || room.artifacts?.length || knowledgeRefs.length || navigationDocuments.status === 'unavailable')
        ? <NavigationSection
            artifacts={room.artifacts ?? []}
            documents={navigationDocuments}
            plan={plan}
            knowledgeRefs={knowledgeRefs}
          />
        : null}

      {modules.isMounted('assignments') ? <section className="room-cockpit__section" id="room-assignments">
        <SectionHeading
          icon={<GitBranch size={16} />}
          title="分工与 @"
          detail={partners.length ? `${partners.length} 位伙伴已进入当前执行线` : '等待实际分派'}
        />
        <AssignmentOverview partners={partners} room={room} />
        <SubagentLaunchPanel
          collapsible
          parents={roomSubagentParents(room)}
          surface="room"
        />
      </section> : null}

      {modules.isMounted('flow') ? <section className="room-cockpit__section" id="room-flow">
        <SectionHeading
          icon={<Network size={16} />}
          title="任务 Workflow"
          detail={partners.length
            ? `${completedPartners}/${partners.length} 位伙伴完成当前分工 · ${navigationDocuments.items.length} 份活动工作文档`
            : '等待真实 WorkItem 或 Session 分派'}
        />
        <TaskFlow
          coordinatorParticipantId={room.moderatorParticipantId}
          documents={navigationDocuments.items}
          facts={sessionFacts}
          goal={goal}
          partners={partners}
          childDelegations={childDelegations}
          roomId={room.id}
          rootId={rootId}
          rootReply={rootReply}
        />
        <RoomSmoothDisclosure className="room-cockpit__peer-evidence" defaultOpen summary={(
          <>
            <span><MessageSquareText size={14} /><strong>直接 @ 通信证据</strong></span>
            <small>{peerRelations.length} 条 · 不参与任务依赖计算</small>
            <ChevronDown className="room-cockpit__chevron" size={14} />
          </>
        )}>
          <PeerRelationGraph relations={peerRelations} participants={roomPeerParticipants(room, partners)} />
        </RoomSmoothDisclosure>
      </section> : null}

      {modules.isMounted('partner-work') ? <section className="room-cockpit__section room-cockpit__assignments" id="room-partner-work">
        <SectionHeading
          icon={<Sparkles size={16} />}
          title="伙伴工作与公开回复"
          detail="思维与工具在公开回复之前；伙伴调用的子 Agent 保留在父伙伴下面。"
        />
        {partners.length ? partners.map((partner) => (
          <PartnerSection
            fact={sessionFacts.get(partner.sessionId)}
            facts={sessionFacts}
            key={`${partner.participantId}:${partner.sessionId}`}
            partner={partner}
            roomChildren={childDelegations.filter((item) => item.parentParticipantId === partner.participantId)}
            roomId={room.id}
            rootReplyId={rootReply?.id}
            rootId={rootId}
          />
        )) : <div className="room-cockpit__quiet-empty">
          <GitBranch size={18} />
          <span><strong>还没有伙伴工作记录</strong><small>分工开始后，思维、工具、子 Agent 和公开回复会依次出现在这里。</small></span>
        </div>}
      </section> : null}

      <section className="room-cockpit__root" id="room-root-reply" data-state={rootReply ? 'ready' : 'waiting'}>
        <SectionHeading
          icon={<MessageSquareText size={16} />}
          title="Root 最终答复"
          detail={rootReply ? '已汇总伙伴公开交付' : '等待伙伴工作汇合'}
        />
        {rootReply
          ? <MarkdownBody text={rootReply.text} />
          : <p>最终答复只在 Root 完成集成后出现；单个子 Agent 失败不会把整个 Room 判成失败。</p>}
      </section>
    </main>
  </div>;
}

function RoomQuickIndex({
  hasNavigation,
  navigationCount,
  partners,
  plan,
  rootReply,
  showAssignments,
  showFlow,
  showPartnerWork,
}: {
  hasNavigation: boolean;
  navigationCount: number;
  partners: PartnerProjection[];
  plan?: PlanProjection;
  rootReply?: RoomMessageProjection;
  showAssignments: boolean;
  showFlow: boolean;
  showPartnerWork: boolean;
}) {
  const active = partners.find((partner) => partner.state === 'active')
    ?? partners.find((partner) => partner.state === 'review' || partner.state === 'attention')
    ?? partners[0];
  return <nav aria-label="任务快速导航" className="room-cockpit__quick-index">
    {hasNavigation ? <RoomQuickIndexTarget detail={plan ? `${plan.completed}/${plan.total}` : `${navigationCount}`} label={plan ? '计划' : '文档'} targetId="room-plan" /> : null}
    {showAssignments ? <RoomQuickIndexTarget detail={`${partners.length}`} label="分工" targetId="room-assignments" /> : null}
    {showFlow ? <RoomQuickIndexTarget detail={active ? `@ ${active.name}` : '待开始'} label="Workflow" primary targetId="room-flow" /> : null}
    {showPartnerWork ? <RoomQuickIndexTarget detail={`${partners.length}`} label="伙伴交付" targetId="room-partner-work" /> : null}
    <RoomQuickIndexTarget detail={rootReply ? '已形成' : '待汇合'} label="Root" targetId="room-root-reply" />
  </nav>;
}

function RoomQuickIndexTarget({
  detail,
  label,
  primary = false,
  targetId,
}: {
  detail: string;
  label: string;
  primary?: boolean;
  targetId: string;
}) {
  return <button
    aria-controls={targetId}
    data-primary={primary || undefined}
    onClick={() => document.getElementById(targetId)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })}
    type="button"
  >
    <span>{label}</span><small>{detail}</small>
  </button>;
}

function AssignmentOverview({ partners, room }: { partners: PartnerProjection[]; room: RoomSummary }) {
  if (!partners.length) return <div className="room-cockpit__quiet-empty">
    <GitBranch size={18} />
    <span><strong>还没有实际分工</strong><small>发送目标后，真实的 dispatch / WorkItem 会出现在这里。</small></span>
  </div>;
  return <div className="room-cockpit__assignment-list">
    {partners.map((partner) => <article data-state={partner.state} key={`${partner.participantId}:${partner.sessionId}`}>
      <header>
        <span><small>@ {partner.name}</small><strong>{partner.assignment}</strong></span>
        <StatePill state={partner.state} />
      </header>
      {partner.workItems.map((workItem) => <RoomSmoothDisclosure className="room-cockpit__work-facts" key={workItem.id} summary={<><span>查看分工依据与验收条件</span><ChevronDown className="room-cockpit__chevron" size={14} /></>}>
        <dl>
          <div><dt>执行人</dt><dd>@ {roomParticipantName(room, workItem.currentOwnerParticipantId)}</dd></div>
          {workItem.accountableParticipantId && workItem.accountableParticipantId !== workItem.currentOwnerParticipantId
            ? <div><dt>复核人</dt><dd>@ {roomParticipantName(room, workItem.accountableParticipantId)}</dd></div>
            : null}
          {workItem.expectedOutput ? <div><dt>预期交付</dt><dd>{workItem.expectedOutput}</dd></div> : null}
          <div><dt>修订</dt><dd>第 {workItem.revision} 次修订</dd></div>
          {room.workspaceRoots?.length ? <div><dt>工作目录</dt><dd>{room.workspaceRoots.join(' · ')}</dd></div> : null}
        </dl>
        {workItem.acceptanceCriteria.length ? <section><strong>验收条件</strong><ul>{workItem.acceptanceCriteria.map((item) => <li key={item}>{item}</li>)}</ul></section> : null}
        {workItem.resultSummary ? <p><b>当前交付：</b>{workItem.resultSummary}</p> : null}
        {[...workItem.evidenceRefs, ...workItem.artifactRefs].length ? <p><b>证据与产物：</b>{[...workItem.evidenceRefs, ...workItem.artifactRefs].join(' · ')}</p> : null}
        <WorkRecovery workItem={workItem} />
      </RoomSmoothDisclosure>)}
      {partner.sessionId ? <a href={`#/agent?session=${encodeURIComponent(partner.sessionId)}`}>打开{partner.name}的对话 <ExternalLink size={12} /></a> : null}
    </article>)}
  </div>;
}

function roomSubagentParents(room: RoomSummary) {
  const writableRoom = room.executionMode !== 'read_only' && Boolean(room.workspaceRoots?.length);
  return room.participants
    .filter((participant) => participant.status === 'active' && participant.sessionId)
    .sort((left, right) => {
      if (left.id === room.moderatorParticipantId) return -1;
      if (right.id === room.moderatorParticipantId) return 1;
      return left.ordinal - right.ordinal;
    })
    .map((participant) => ({
      sessionId: participant.sessionId,
      label: roomPlanetName(participant.ordinal),
      detail: participant.id === room.moderatorParticipantId
        ? 'Root 主持'
        : roomCollaborationRoleLabel(participant.collaborationRole),
      canWrite: writableRoom && participant.collaborationRole !== 'reviewer',
      workspaceRoots: room.workspaceRoots ?? [],
    }));
}

function NavigationSection({
  artifacts,
  documents,
  knowledgeRefs,
  plan,
}: {
  artifacts: readonly RoomArtifact[];
  documents: RoomNavigationDocuments;
  knowledgeRefs: string[];
  plan?: PlanProjection;
}) {
  const progress = plan?.total ? Math.round(plan.completed / plan.total * 100) : 0;
  const documentCount = documents.items.length + artifacts.length + knowledgeRefs.length;
  return <RoomSmoothDisclosure className="room-cockpit__plan" contentId="room-plan" defaultOpen summary={(
    <>
      <ListChecks size={16} />
      <span>
        <strong>{plan?.label || '持久化文档导航'}</strong>
        <small>
          {plan ? `${plan.completed}/${plan.total} 已完成` : '未启用结构化 Todo'}
          {documentCount ? ` · ${documentCount} 份材料` : ''}
        </small>
      </span>
      <span className="room-cockpit__plan-track"><i style={{ transform: `scaleX(${progress / 100})` }} /></span>
      <ChevronDown className="room-cockpit__chevron" size={15} />
    </>
  )}>
    {plan ? <ol>
      {plan.tasks.map((task) => <li data-state={task.state} key={task.id}>
        <span aria-hidden="true" />
        <div><strong>{task.content}</strong><small>{task.phase}</small></div>
        <em>{task.stateLabel}</em>
      </li>)}
    </ol> : null}
    {documentCount || documents.status === 'loading' || documents.status === 'unavailable' ? <section className="room-cockpit__navigation-documents">
      <header><FileText size={14} /><strong>文档与 Knowledge 导航</strong><small>持久化，可恢复，不扩散成零散 Todo</small></header>
      {documents.status === 'loading' ? <p>正在读取 Room WorkItem 对应的文档…</p> : null}
      {documents.status === 'unavailable' ? <p data-state="unavailable">文档索引暂时不可用；任务运行事实仍正常显示。</p> : null}
      <div>
        {documents.items.map((document) => <DocumentLink document={document} key={document.documentId} />)}
        {artifacts.map((artifact) => <span key={artifact.id}><FileText size={13} /><span><strong>{artifact.displayName}</strong><small>{artifact.mediaType || 'Room 产物'}</small></span></span>)}
        {knowledgeRefs.map((reference) => <a href="#/knowledge" key={reference}><FileText size={13} /><span><strong>{knowledgeReferenceLabel(reference)}</strong><small>Knowledge 证据 · 打开资料库定位来源</small></span><ExternalLink size={12} /></a>)}
      </div>
    </section> : null}
  </RoomSmoothDisclosure>;
}

function DocumentLink({ document }: { document: WorkDocumentV1 }) {
  const scope = document.state === 'archived' ? '&scope=history' : '';
  return <a href={`#/work-documents?document=${encodeURIComponent(document.documentId)}${scope}`}>
    <FileText size={13} />
    <span><strong>{document.title || '未命名工作文档'}</strong><small>WorkItem 文档 · r{document.documentRevision}</small></span>
    <ExternalLink size={12} />
  </a>;
}

function SessionConversationLink({
  children,
  className,
  sessionId,
}: {
  children: ReactNode;
  className?: string;
  sessionId: string;
}) {
  if (!sessionId.trim()) return null;
  return <a className={className} href={`#/agent?session=${encodeURIComponent(sessionId)}`}>
    <MessageSquareText aria-hidden="true" size={12} />
    <span>{children}</span>
    <ExternalLink aria-hidden="true" size={11} />
  </a>;
}

function TaskFlow({
  childDelegations,
  coordinatorParticipantId,
  documents,
  facts,
  goal,
  partners,
  roomId,
  rootId,
  rootReply,
}: {
  childDelegations: RoomChildDelegationProjection[];
  coordinatorParticipantId: string;
  documents: WorkDocumentV1[];
  facts: ReadonlyMap<string, RoomTaskSessionFact>;
  goal: string;
  partners: PartnerProjection[];
  roomId: string;
  rootId: string;
  rootReply?: RoomMessageProjection;
}) {
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null);
  if (!partners.length) return <div className="room-cockpit__quiet-empty">
    <Network size={18} />
    <span><strong>还没有实际流转</strong><small>只有产生真实 dispatch / WorkItem 后，Room 才会绘制节点与关系。</small></span>
  </div>;
  const documentByWorkItem = new Map(
    documents
      .filter((document) => document.authorityKind === 'room_work_item')
      .map((document) => [document.authorityId, document]),
  );
  const stages = taskFlowStages(partners, coordinatorParticipantId).map((stage) => ({
    ...stage,
    items: stage.items.map((item) => ({
      ...item,
      document: item.workItem ? documentByWorkItem.get(item.workItem.id) : undefined,
    })),
  }));
  const flowItems = stages.flatMap((stage) => stage.items.map((item) => ({ item, stage })));
  const selected = flowItems.find(({ item }) => item.id === selectedBranch)
    ?? flowItems.find(({ item }) => item.state === 'active')
    ?? flowItems[0];
  return <div className="room-cockpit__flow-board">
    <div className="room-cockpit__flow-legend">
      <span><i data-state="active" />执行中</span>
      <span><i data-state="complete" />已完成</span>
      <span><i data-state="review" />复核中</span>
      <span><i data-state="contract" />合同待修复</span>
      <small>只有同一真实 waveId 的节点标记并行；其他分工按依赖与事件事实展示。</small>
      <RoomSmoothDisclosure className="room-cockpit__flow-policy" summary={<><ShieldCheck size={12} />恢复策略<ChevronDown className="room-cockpit__chevron" size={12} /></>}>
        <p>已完成节点不重跑；只读节点可恢复；写文件、命令和外部操作先核对原 Tool 回执。</p>
      </RoomSmoothDisclosure>
    </div>
    <section className="room-cockpit__workflow-graph" aria-label="当前任务 Workflow 图">
      <header>
        <span><GitBranch size={15} /><strong>当前任务 Workflow</strong></span>
        <small>实线箭头来自真实 WorkItem 父子依赖；无父节点的工作从目标直接分派。</small>
      </header>
      <TaskDag goal={goal} rootReady={Boolean(rootReply)} stages={stages} />
    </section>
    <ol aria-label="目标到 Root 的流转路径" className="room-cockpit__flow-route room-cockpit__flow-route--accessible">
      <li data-state="complete" title={goal}>
        <span>00</span>
        <span><strong>目标</strong><small>已确认</small></span>
      </li>
      {stages.map((stage, stageIndex) => {
        const completed = stage.items.filter((item) => item.state === 'complete').length;
        return <li data-state={flowStageState(stage.items)} key={stage.id}>
          <span>{String(stageIndex + 1).padStart(2, '0')}</span>
          <span><strong>{stage.label}</strong><small>{stage.parallel ? `${stage.items.length} 路并行` : `${stage.items.length} 项`} · {completed} 完成</small></span>
        </li>;
      })}
      <li data-state={rootReply ? 'complete' : 'waiting'}>
        <span>{String(stages.length + 1).padStart(2, '0')}</span>
        <span><strong>Root 汇合</strong><small>{rootReply ? '已形成答复' : '等待交付'}</small></span>
      </li>
    </ol>
    <div className="room-cockpit__flow-sequence">
      {stages.map((stage, stageIndex) => {
        const stageState = flowStageState(stage.items);
        const completed = stage.items.filter((item) => item.state === 'complete').length;
        return <section className="room-cockpit__flow-phase" data-parallel={stage.parallel} data-state={stageState} key={stage.id}>
          <header>
            <span>{String(stageIndex + 1).padStart(2, '0')}</span>
            <span><strong>{stage.label}</strong><small>{stage.parallel ? '同一 Room 波次同时释放' : stageIndex === 0 ? '由 Root 分派' : '承接上一阶段交付'}</small></span>
            <span><b>{stage.parallel ? `${stage.items.length} 路并行` : stage.items.length > 1 ? `${stage.items.length} 项分工` : '单路执行'}</b><small>{completed}/{stage.items.length} 已完成</small></span>
          </header>
          <div className="room-cockpit__flow-branches">
            {stage.items.map((item) => {
              const batches = visibleSubagentBatches(
                facts.get(item.partner.sessionId),
                roomId,
                rootId,
              );
              const childRuns = batches.flatMap((batch) => batch.runs);
              const roomChildren = childDelegations.filter(
                (child) => child.parentParticipantId === item.partner.participantId,
              );
              const recovery = item.workItem ? workRecoveryProjection(item.workItem) : undefined;
              const childCount = roomChildren.length + childRuns.length;
              return <button
                aria-current={selected?.item.id === item.id ? 'step' : undefined}
                aria-label={`查看 @ ${item.partner.name} 的执行节点：${item.objective}`}
                className="room-cockpit__flow-branch"
                data-selected={selected?.item.id === item.id || undefined}
                data-state={item.state}
                key={item.id}
                onClick={() => setSelectedBranch(item.id)}
                type="button"
              >
                <span className="room-cockpit__flow-branch-copy">
                  <small>@ {item.partner.name}{item.workItem?.parentWorkId ? ' · 接续节点' : ''}</small>
                  <strong>{item.objective}</strong>
                </span>
                <span className="room-cockpit__flow-branch-meta">
                  <StatePill state={item.state} />
                  <small>{item.workItem
                    ? `WorkItem · r${item.workItem.revision}`
                    : stage.parallel && item.lane?.parallelSize
                      ? `波次 ${Number(item.lane.parallelIndex ?? 0) + 1}/${item.lane.parallelSize}`
                      : '运行事实'}</small>
                </span>
                {childCount ? <span className="room-cockpit__flow-child-summary">
                  {roomChildren.map((child) => <span data-state={child.state} key={child.id}>
                    <GitBranch size={11} />Partner → @ {child.targetName}
                  </span>)}
                  {childRuns.map((run) => <span data-state={subagentCockpitState(run)} key={run.id}>
                    <Bot size={11} />{run.depth > 1 ? 'Pattern 子调用' : '子 Agent'} · {subagentTemplateLabel(run.templateId)}
                  </span>)}
                </span> : null}
                {recovery ? <span className="room-cockpit__flow-branch-recovery" data-kind={recovery.kind}>
                  <ShieldCheck size={11} />{recovery.label}
                </span> : null}
              </button>;
            })}
          </div>
        </section>;
      })}
    </div>
    {selected ? <FlowBranchInspector item={selected.item} stage={selected.stage} /> : null}
  </div>;
}

interface TaskDagNode {
  id: string;
  x: number;
  y: number;
  label: string;
  detail: string;
  document: string;
  state: CockpitState;
  kind: 'goal' | 'task' | 'root';
  workItemId?: string;
}

function TaskDag({
  goal,
  rootReady,
  stages,
}: {
  goal: string;
  rootReady: boolean;
  stages: FlowStage[];
}) {
  const markerPrefix = useId().replace(/:/g, '');
  const arrowMarkerId = `${markerPrefix}-room-task-dag-arrow`;
  const nodeWidth = 214;
  const nodeHeight = 88;
  const columnWidth = 286;
  const width = Math.max(660, (stages.length + 2) * columnWidth);
  const maxRows = Math.max(1, ...stages.map((stage) => stage.items.length));
  const height = Math.max(310, maxRows * 122 + 110);
  const centerY = height / 2 + 10;
  const stageNodes: TaskDagNode[][] = stages.map((stage, stageIndex) => (
    stage.items.map((item, itemIndex) => ({
      id: item.id,
      x: columnWidth * (stageIndex + 1) + columnWidth / 2,
      y: stage.items.length === 1
        ? centerY
        : 82 + itemIndex * ((height - 150) / Math.max(1, stage.items.length - 1)),
      label: compactGraphText(item.objective),
      detail: `@ ${item.partner.name}${item.workItem ? ` · WorkItem r${item.workItem.revision}` : ' · Session 运行'}`,
      document: item.document
        ? `文档 · ${compactGraphText(item.document.title || item.document.path)}`
        : item.workItem
          ? '文档 · 尚未登记'
          : '文档 · 无结构化 WorkItem',
      state: item.state,
      kind: 'task' as const,
      workItemId: item.workItem?.id,
    }))
  ));
  const goalNode: TaskDagNode = {
    id: 'goal', x: columnWidth / 2, y: centerY,
    label: '共同目标', detail: compactGraphText(goal), document: '入口 · 用户请求', state: 'complete', kind: 'goal',
  };
  const rootNode: TaskDagNode = {
    id: 'root', x: columnWidth * (stages.length + 1) + columnWidth / 2, y: centerY,
    label: 'Root 汇合', detail: rootReady ? '已形成最终答复' : '等待所有支线汇合',
    document: rootReady ? '验收 · 已交付' : '验收 · 等待证据',
    state: rootReady ? 'complete' : 'waiting', kind: 'root',
  };
  const edges: Array<{ id: string; source: TaskDagNode; target: TaskDagNode; label: string; state: CockpitState }> = [];
  const taskNodes = stageNodes.flat();
  const taskNodeByWorkItem = new Map<string, TaskDagNode>();
  for (const node of taskNodes) {
    if (node.workItemId) taskNodeByWorkItem.set(node.workItemId, node);
  }
  const dependencySources = new Set<string>();
  stages.forEach((stage, stageIndex) => stage.items.forEach((item, itemIndex) => {
    const target = stageNodes[stageIndex]?.[itemIndex];
    if (!target) return;
    const parent = item.workItem?.parentWorkId
      ? taskNodeByWorkItem.get(item.workItem.parentWorkId)
      : undefined;
    const source = parent ?? goalNode;
    if (parent) dependencySources.add(parent.id);
    edges.push({
      id: `${source.id}:${target.id}`,
      source,
      target,
      label: parent ? '依赖' : '分派',
      state: target.state,
    });
  }));
  const leaves = taskNodes.filter((node) => !dependencySources.has(node.id));
  leaves.forEach((source) => edges.push({
    id: `${source.id}:root`, source, target: rootNode, label: '汇合',
    state: source.state === 'attention' ? 'attention' : rootNode.state,
  }));
  const nodes = [goalNode, ...stageNodes.flat(), rootNode];
  return <div className="room-cockpit__task-dag-scroll">
    <svg
      aria-label={`${nodes.length} 个节点、${edges.length} 条任务关系的有向图`}
      className="room-cockpit__task-dag"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      style={stages.length > 2 ? { minWidth: width + 'px' } : undefined}
      viewBox={`0 0 ${width} ${height}`}
    >
      <title>目标、分派、依赖、并行与 Root 汇合关系图</title>
      <defs>
        <marker id={arrowMarkerId} markerHeight="7" markerWidth="7" orient="auto" refX="6" refY="3.5" viewBox="0 0 7 7">
          <path d="M0,0 L7,3.5 L0,7 z" />
        </marker>
      </defs>
      {stages.map((stage, index) => <text className="room-cockpit__task-dag-stage" key={stage.id} textAnchor="middle" x={columnWidth * (index + 1) + columnWidth / 2} y="30">
        {stage.label}{stage.parallel ? ` · ${stage.items.length} 路并行` : ''}
      </text>)}
      <g className="room-cockpit__task-dag-edges">
        {edges.map((edge) => {
          const sourceX = edge.source.x + nodeWidth / 2;
          const targetX = edge.target.x - nodeWidth / 2;
          const midX = (sourceX + targetX) / 2;
          return <g data-state={edge.state} key={edge.id}>
            <path d={`M ${sourceX} ${edge.source.y} C ${midX} ${edge.source.y}, ${midX} ${edge.target.y}, ${targetX} ${edge.target.y}`} markerEnd={`url(#${arrowMarkerId})`} />
            <text textAnchor="middle" x={midX} y={(edge.source.y + edge.target.y) / 2 - 6}>{edge.label}</text>
          </g>;
        })}
      </g>
      <g className="room-cockpit__task-dag-nodes">
        {nodes.map((node) => <g
          data-kind={node.kind}
          data-state={node.state}
          key={node.id}
          transform={`translate(${node.x - nodeWidth / 2} ${node.y - nodeHeight / 2})`}
        >
          <title>{node.label}：{node.detail}</title>
          <rect height={nodeHeight} rx="12" width={nodeWidth} />
          <circle cx="22" cy="24" r="9" />
          <text className="room-cockpit__task-dag-label" x="40" y="27">{node.label}</text>
          <text className="room-cockpit__task-dag-detail" x="14" y="50">{node.detail}</text>
          <text className="room-cockpit__task-dag-document" x="14" y="67">{node.document}</text>
          <text className="room-cockpit__task-dag-state" x="14" y="81">{stateLabel(node.state)}</text>
        </g>)}
      </g>
    </svg>
  </div>;
}

function FlowBranchInspector({ item, stage }: { item: FlowTaskItem; stage: FlowStage }) {
  const workItem = item.workItem;
  const expectedOutput = item.expectedOutput || workItem?.expectedOutput || '';
  const acceptanceCriteria = item.acceptanceCriteria?.length
    ? item.acceptanceCriteria
    : workItem?.acceptanceCriteria ?? [];
  const resultSummary = item.resultSummary || workItem?.resultSummary || '';
  const hasContract = Boolean(expectedOutput || acceptanceCriteria.length || resultSummary || workItem);
  return <section aria-label={`@ ${item.partner.name} 的节点详情`} className="room-cockpit__flow-inspector">
    <header>
      <span><small>{stage.label} · 选中支线</small><h3>@ {item.partner.name}</h3></span>
      <StatePill state={item.state} />
    </header>
    <p>{item.objective}</p>
    {hasContract ? <div className="room-cockpit__flow-contract">
      <section>
        <strong>交付合同</strong>
        <dl>
          <div><dt>预期交付</dt><dd>{expectedOutput || '等待明确交付形态'}</dd></div>
          {workItem ? <div><dt>修订</dt><dd>r{workItem.revision}</dd></div> : null}
          {stage.waveId ? <div><dt>并行波次</dt><dd>{stage.label}</dd></div> : null}
        </dl>
      </section>
      <section>
        <strong>验收条件</strong>
        {acceptanceCriteria.length
          ? <ul>{acceptanceCriteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul>
          : <p>尚未记录结构化验收条件。</p>}
      </section>
      {resultSummary ? <section><strong>当前交付</strong><p>{resultSummary}</p></section> : null}
    </div> : <p className="room-cockpit__flow-inspector-empty">当前节点只有运行事实，尚未形成结构化 WorkItem。</p>}
    {item.document ? <a
      className="room-cockpit__workflow-document-link"
      href={`#/work-documents?document=${encodeURIComponent(item.document.documentId)}${item.document.state === 'archived' ? '&scope=history' : ''}`}
    >
      <FileText size={14} />
      <span><strong>{item.document.title || '未命名工作文档'}</strong><small>{item.document.path} · 对应 Session {item.partner.sessionId}</small></span>
      <ExternalLink size={12} />
    </a> : workItem ? <p className="room-cockpit__workflow-document-missing">
      <FileText size={13} />此 WorkItem 尚未登记活动文档；伙伴仍可从 Room 工作区 docs/ 创建并注册。
    </p> : null}
    {workItem ? <WorkRecovery workItem={workItem} /> : null}
    <SessionConversationLink className="room-cockpit__conversation-link" sessionId={item.partner.sessionId}>
      打开 @ {item.partner.name} 对话
    </SessionConversationLink>
  </section>;
}

function PartnerSection({
  fact,
  facts,
  partner,
  roomChildren,
  roomId,
  rootReplyId,
  rootId,
}: {
  fact?: RoomTaskSessionFact;
  facts: ReadonlyMap<string, RoomTaskSessionFact>;
  partner: PartnerProjection;
  roomChildren: RoomChildDelegationProjection[];
  roomId: string;
  rootReplyId?: string;
  rootId: string;
}) {
  const reasoning = reasoningSummaries(partner.activities);
  const tools = toolSteps(partner.activities);
  const batches = visibleSubagentBatches(fact, roomId, rootId);
  const replies = partner.messages.filter((message) => message.id !== rootReplyId && message.text.trim());
  return <article
    className="room-cockpit__partner"
    data-state={partner.state}
    id={`room-partner-${safeId(partner.participantId || partner.sessionId)}`}
  >
    <header>
      <span><small>@ {partner.name}</small><strong>{partner.assignment}</strong></span>
      <StatePill state={partner.state} />
    </header>
    <RoomSmoothDisclosure active={partner.state === 'active' || partner.state === 'attention'} className="room-cockpit__thinking" summary={(
      <>
        <Sparkles size={14} /><strong>思维与工具</strong>
        <small>{reasoning.length} 条摘要 · {tools.length} 个工具步骤</small>
        <ChevronDown className="room-cockpit__chevron" size={14} />
      </>
    )}>
      <div>
        {reasoning.length ? <section><h4>公开思考摘要</h4><ol>{reasoning.map((item, index) => <li key={`${partner.sessionId}:reasoning:${index}`}>{item}</li>)}</ol></section> : null}
        {tools.length ? <section><h4>工具</h4><ul>{tools.map((tool) => <li data-state={tool.state} key={tool.id}><Wrench size={13} /><span><strong>{tool.name}</strong><small>{tool.summary}</small></span><em>{stateLabel(tool.state)}</em></li>)}</ul></section> : null}
        {!reasoning.length && !tools.length ? <p>尚未收到可公开的思考摘要或工具事件。</p> : null}
      </div>
    </RoomSmoothDisclosure>
    {roomChildren.length ? <section className="room-cockpit__partner-children">
      <h3><GitBranch size={15} />Partner 调用 <small>{roomChildren.length}</small></h3>
      {roomChildren.map((child) => <article data-state={child.state} key={child.id}>
        <span><small>@ {partner.name} → @ {child.targetName}</small><strong>{child.task}</strong></span>
        <StatePill state={child.state} />
        {child.summary ? <p>{child.summary}</p> : null}
      </article>)}
    </section> : null}
    {batches.length ? <section className="room-cockpit__subagents">
      <h3><Bot size={15} />委派的子 Agent <small>{batches.reduce((total, batch) => total + batch.runs.length, 0)}</small></h3>
      {batches.map((batch) => <div className="room-cockpit__subagent-batch" key={batch.id}>
        <header><span>由 @ {partner.name} 调用</span><small>深度 {batch.depth}/{batch.maxDepth} · {batch.resultDeliveryMode === 'next_turn' ? '下一轮回传' : '本轮回传'}</small></header>
        {batch.runs.map((run) => <SubagentRun facts={facts} key={run.id} roomId={roomId} rootId={rootId} run={run} />)}
      </div>)}
    </section> : null}
    <div className="room-cockpit__handoff"><span />回传给 @ {partner.name}</div>
    <section className="room-cockpit__reply">
      <h3><MessageSquareText size={15} />伙伴公开回复</h3>
      {replies.length ? replies.map((message) => <div key={message.id}><MarkdownBody text={message.text} /></div>) : <p>等待伙伴发布可见交付。</p>}
    </section>
  </article>;
}

function SubagentRun({
  facts,
  run,
  roomId,
  rootId,
  depth = 0,
}: {
  facts: ReadonlyMap<string, RoomTaskSessionFact>;
  run: AgentSubagentRunV1;
  roomId: string;
  rootId: string;
  depth?: number;
}) {
  const state = subagentCockpitState(run);
  const result = subagentResultText(run);
  const childBatches = depth < 2
    ? visibleSubagentBatches(facts.get(run.childSessionId), roomId, rootId)
    : [];
  return <RoomSmoothDisclosure active={state === 'active' || state === 'attention' || state === 'contract'} className="room-cockpit__subagent" dataState={state} summary={(
    <>
      <Bot size={15} />
      <span><strong>{run.task}</strong><small>{run.templateId} · 尝试 {run.attemptNumber} · {run.usage.toolCount} 工具 · {run.usage.turnCount} 轮</small></span>
      <em>{subagentStateLabel(run)}</em>
      <ChevronDown className="room-cockpit__chevron" size={14} />
    </>
  )}>
    <div>
      {run.expectedOutput ? <p><b>预期：</b>{run.expectedOutput}</p> : null}
      {run.error ? <p className="room-cockpit__local-error"><CircleAlert size={14} /><span><b>局部失败：</b>{run.error}</span></p> : null}
      {isContractInvalid(run) ? <p className="room-cockpit__contract-error"><CircleAlert size={14} /><span><b>已返回但交付合同无效：</b>{run.contract.error || '等待修复输出或改派节点'}</span></p> : null}
      {subagentFailurePolicy(run) ? <p className="room-cockpit__recovery-policy"><ShieldCheck size={14} /><span>{subagentFailurePolicy(run)}</span></p> : null}
      {result ? <p><b>回传：</b>{result}</p> : null}
      <small>
        node {shortId(run.nodeId)} · {run.launchDigest.contextMode} · {run.launchDigest.modelProfile}
        {' · '}{run.launchDigest.tools.length} 个启动工具 · 此状态只属于该子 Agent。
      </small>
      <SessionConversationLink className="room-cockpit__conversation-link" sessionId={run.childSessionId}>
        打开“{run.task}”子 Agent 对话
      </SessionConversationLink>
      {childBatches.length ? <section className="room-cockpit__subagent-children">
        <h4>此子 Agent 再委派</h4>
        {childBatches.flatMap((batch) => batch.runs).map((childRun) => <SubagentRun
          depth={depth + 1}
          facts={facts}
          key={childRun.id}
          roomId={roomId}
          rootId={rootId}
          run={childRun}
        />)}
      </section> : null}
    </div>
  </RoomSmoothDisclosure>;
}

function SectionHeading({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <header className="room-cockpit__section-heading"><span>{icon}<h2>{title}</h2></span><small>{detail}</small></header>;
}

function RoomSmoothDisclosure({
  active = false,
  children,
  className,
  contentId,
  dataState,
  defaultOpen = false,
  summary,
}: {
  active?: boolean;
  children: ReactNode;
  className: string;
  contentId?: string;
  dataState?: string;
  defaultOpen?: boolean;
  summary: ReactNode;
}) {
  const generatedId = useId().replace(/:/gu, '');
  const revealId = contentId || `room-disclosure-${generatedId}`;
  const [open, setOpen] = useState(defaultOpen || active);
  const manuallyToggled = useRef(false);
  const wasActive = useRef(active);
  useEffect(() => {
    if (active && !wasActive.current && !manuallyToggled.current) setOpen(true);
    wasActive.current = active;
  }, [active]);
  return <section className={`${className} room-cockpit__smooth-disclosure`} data-open={open || undefined} data-state={dataState}>
    <button
      aria-controls={revealId}
      aria-expanded={open}
      className="room-cockpit__disclosure-summary"
      onClick={(event) => {
        manuallyToggled.current = true;
        toggleDisclosurePreservingAnchor(event, setOpen);
      }}
      type="button"
    >
      {summary}
    </button>
    <SmoothDisclosureReveal className="room-cockpit__disclosure-reveal" id={revealId} innerClassName="room-cockpit__disclosure-inner" open={open}>
      {children}
    </SmoothDisclosureReveal>
  </section>;
}

function StatePill({ state }: { state: CockpitState }) {
  return <i className="room-cockpit__state" data-state={state}>{stateIcon(state)}{stateLabel(state)}</i>;
}

function WorkRecovery({
  compact = false,
  workItem,
}: {
  compact?: boolean;
  workItem: RoomWorkItem;
}) {
  const recovery = workRecoveryProjection(workItem);
  if (!recovery) return null;
  return <p className="room-cockpit__work-recovery" data-compact={compact} data-kind={recovery.kind}>
    <ShieldCheck size={12} />
    <span><b>{recovery.label}</b>{compact ? null : <small>{recovery.detail}</small>}</span>
  </p>;
}

function buildPartnerProjections(
  room: RoomSummary,
  runtime: RoomExecutionOverviewItem | undefined,
  lanes: readonly RoomExecutionLane[],
  projection?: RoomProjectionState,
): PartnerProjection[] {
  const result = new Map<string, PartnerProjection>();
  const relevantWorkItems = room.workItems?.filter((item) => !runtime || item.rootTurnId === runtime.id || item.rootWorkId === runtime.id) ?? [];
  for (const lane of lanes) {
    const participant = room.participants.find((item) => item.id === lane.participantId)
      ?? room.participants.find((item) => item.sessionId === lane.sourceSessionId);
    if (!participant) continue;
    const workItems = relevantWorkItems.filter((item) => [item.currentOwnerParticipantId, item.offeredToParticipantId].includes(participant.id));
    const messages = lane.messageIds.map((id) => projection?.messagesById[id]).filter((item): item is RoomMessageProjection => Boolean(item));
    const existing = result.get(participant.id);
    const activities = [...(existing?.activities ?? []), ...lane.activities];
    const partnerLanes = [...(existing?.lanes ?? []), lane];
    const combinedMessages = [...(existing?.messages ?? []), ...messages];
    result.set(participant.id, {
      participantId: participant.id,
      name: roomPlanetName(participant.ordinal),
      sessionId: participant.sessionId || lane.sourceSessionId,
      assignment: participant.id === room.moderatorParticipantId
        ? 'Root 汇合与最终答复'
        : existing?.assignment || partnerAssignment(workItems, lane.activities, runtime?.objective),
      state: partnerState(workItems, activities, combinedMessages, runtime?.status),
      activities,
      lanes: partnerLanes,
      messages: combinedMessages,
      workItems,
    });
  }
  for (const workItem of relevantWorkItems) {
    const participantId = workItem.currentOwnerParticipantId || workItem.accountableParticipantId || workItem.offeredToParticipantId;
    if (!participantId) continue;
    const existing = result.get(participantId);
    if (existing) {
      const workItems = [...existing.workItems];
      if (!workItems.some((item) => item.id === workItem.id)) workItems.push(workItem);
      result.set(participantId, {
        ...existing,
        assignment: partnerAssignment(workItems, existing.activities, runtime?.objective),
        state: partnerState(workItems, existing.activities, existing.messages, runtime?.status),
        workItems,
      });
      continue;
    }
    const participant = room.participants.find((item) => item.id === participantId);
    if (!participant) continue;
    result.set(participantId, {
      participantId,
      name: roomPlanetName(participant.ordinal),
      sessionId: participant.sessionId,
      assignment: workItem.objective,
      state: workItemState(workItem.state),
      activities: [],
      lanes: [],
      messages: [],
      workItems: [workItem],
    });
  }
  return [...result.values()].sort((left, right) => {
    const leftOrdinal = room.participants.find((item) => item.id === left.participantId)?.ordinal ?? 99;
    const rightOrdinal = room.participants.find((item) => item.id === right.participantId)?.ordinal ?? 99;
    return leftOrdinal - rightOrdinal;
  });
}

function taskFlowStages(
  partners: PartnerProjection[],
  coordinatorParticipantId: string,
): FlowStage[] {
  const workById = new Map<string, { partner: PartnerProjection; workItem: RoomWorkItem }>();
  for (const partner of partners) {
    for (const workItem of partner.workItems) {
      const owner = partners.find((candidate) => (
        candidate.participantId === workItem.currentOwnerParticipantId
        || candidate.participantId === workItem.accountableParticipantId
      )) ?? partner;
      const existing = workById.get(workItem.id);
      if (!existing || owner.participantId === workItem.currentOwnerParticipantId) {
        workById.set(workItem.id, { partner: owner, workItem });
      }
    }
  }
  const usedWorkItemIds = new Set<string>();
  const usedLaneKeys = new Set<string>();
  const runtimeLanes = partners.flatMap((partner) => partner.lanes.map((lane) => ({
    lane,
    partner,
  })));
  const waveGroups = new Map<string, typeof runtimeLanes>();
  for (const entry of runtimeLanes) {
    if (!entry.lane.waveId || (entry.lane.parallelSize ?? 0) < 2) continue;
    const values = waveGroups.get(entry.lane.waveId) ?? [];
    values.push(entry);
    waveGroups.set(entry.lane.waveId, values);
  }
  const waveStages: Array<FlowStage & { order: number }> = [];
  for (const [waveId, rawEntries] of waveGroups) {
    const byParticipant = new Map<string, (typeof rawEntries)[number]>();
    for (const entry of rawEntries) {
      const key = entry.partner.participantId || entry.partner.sessionId;
      const previous = byParticipant.get(key);
      if (!previous || laneOrder(entry.lane) < laneOrder(previous.lane)) {
        byParticipant.set(key, entry);
      }
    }
    const entries = [...byParticipant.values()].sort((left, right) => (
      Number(left.lane.parallelIndex ?? Number.MAX_SAFE_INTEGER)
      - Number(right.lane.parallelIndex ?? Number.MAX_SAFE_INTEGER)
      || laneOrder(left.lane) - laneOrder(right.lane)
      || left.partner.name.localeCompare(right.partner.name, 'zh-CN')
    ));
    if (entries.length < 2) continue;
    const items = entries.map(({ lane, partner }) => {
      usedLaneKeys.add(lane.key);
      const availableWorkItems = partner.workItems.filter((item) => !usedWorkItemIds.has(item.id));
      const workItem = availableWorkItems.length === 1 ? availableWorkItems[0] : undefined;
      if (workItem) usedWorkItemIds.add(workItem.id);
      const messages = partner.messages.filter((message) => lane.messageIds.includes(message.id));
      return {
        id: `lane:${lane.key}`,
        objective: laneTask(lane) || workItem?.objective || partner.assignment,
        partner,
        state: laneCockpitState(lane, messages, workItem, partner.state),
        lane,
        expectedOutput: laneExpectedOutput(lane) || workItem?.expectedOutput,
        acceptanceCriteria: laneAcceptanceCriteria(lane).length
          ? laneAcceptanceCriteria(lane)
          : workItem?.acceptanceCriteria,
        resultSummary: laneResultSummary(lane, messages) || workItem?.resultSummary,
        workItem,
      } satisfies FlowTaskItem;
    });
    waveStages.push({
      id: `wave:${waveId}`,
      label: entries.map((entry) => entry.lane.phaseName.trim()).find(Boolean) || '并行执行',
      parallel: true,
      waveId,
      items,
      order: Math.min(...entries.map((entry) => laneOrder(entry.lane))),
    });
  }

  const depthCache = new Map<string, number>();
  const workDepth = (id: string, ancestors = new Set<string>()): number => {
    const cached = depthCache.get(id);
    if (cached !== undefined) return cached;
    const entry = workById.get(id);
    if (!entry || ancestors.has(id)) return 0;
    const parentId = entry.workItem.parentWorkId;
    const fallback = Math.max(0, Math.min(4, Number(entry.workItem.depth || 1) - 1));
    const depth = parentId && workById.has(parentId)
      ? Math.min(4, workDepth(parentId, new Set(ancestors).add(id)) + 1)
      : fallback;
    depthCache.set(id, depth);
    return depth;
  };
  const grouped = new Map<number, FlowTaskItem[]>();
  for (const { partner, workItem } of workById.values()) {
    if (usedWorkItemIds.has(workItem.id)) continue;
    const depth = workDepth(workItem.id);
    const items = grouped.get(depth) ?? [];
    items.push({
      id: workItem.id,
      objective: workItem.objective || partner.assignment,
      partner,
      state: workItemState(workItem.state),
      expectedOutput: workItem.expectedOutput,
      acceptanceCriteria: workItem.acceptanceCriteria,
      resultSummary: workItem.resultSummary,
      workItem,
    });
    grouped.set(depth, items);
  }
  const workStages: FlowStage[] = [...grouped.entries()]
    .sort(([left], [right]) => left - right)
    .map(([depth, items], index) => ({
      id: `work-stage:${depth}`,
      label: index === 0
        ? (items.length > 1 ? '分工' : '执行')
        : items.some((item) => item.state === 'review')
          ? '接续 / 复核'
          : '接续执行',
      parallel: false,
      items: items.sort((left, right) => left.partner.name.localeCompare(right.partner.name, 'zh-CN')),
    }));

  const stages: FlowStage[] = [
    ...waveStages.sort((left, right) => left.order - right.order),
    ...workStages,
  ];
  if (stages.length) return stages;

  const nonCoordinatorRuntime = runtimeLanes.filter(({ lane, partner }) => (
    !usedLaneKeys.has(lane.key)
    && partner.participantId !== coordinatorParticipantId
  ));
  const runtimeEntries = nonCoordinatorRuntime.length
    ? nonCoordinatorRuntime
    : runtimeLanes.filter(({ lane }) => !usedLaneKeys.has(lane.key));
  if (runtimeEntries.length) {
    return [{
      id: 'runtime-stage',
      label: runtimeEntries.length > 1 ? '执行记录' : '执行',
      parallel: false,
      items: runtimeEntries
        .sort((left, right) => laneOrder(left.lane) - laneOrder(right.lane))
        .map(({ lane, partner }) => {
          const messages = partner.messages.filter((message) => lane.messageIds.includes(message.id));
          return {
            id: `lane:${lane.key}`,
            objective: laneTask(lane) || partner.assignment,
            partner,
            state: laneCockpitState(lane, messages, undefined, partner.state),
            lane,
            expectedOutput: laneExpectedOutput(lane),
            acceptanceCriteria: laneAcceptanceCriteria(lane),
            resultSummary: laneResultSummary(lane, messages),
          };
        }),
    }];
  }
  return [{
    id: 'runtime-stage',
    label: partners.length > 1 ? '分工' : '执行',
    parallel: false,
    items: partners.map((partner) => ({
      id: `runtime:${partner.participantId || partner.sessionId}`,
      objective: partner.assignment,
      partner,
      state: partner.state,
    })),
  }];
}

function laneOrder(lane: RoomExecutionLane): number {
  const sequences = lane.activities.flatMap((activity) => (
    activity.sequence === undefined ? [] : [activity.sequence]
  ));
  if (sequences.length) return Math.min(...sequences);
  const times = lane.activities.map((activity) => activity.createdAtMs);
  return times.length ? Math.min(...times) : Number.MAX_SAFE_INTEGER;
}

function laneTask(lane: RoomExecutionLane): string {
  return lane.activities.map((activity) => text(activity.payload.task)).find(Boolean) || '';
}

function laneExpectedOutput(lane: RoomExecutionLane): string {
  return lane.activities.map((activity) => text(activity.payload.expectedOutput)).find(Boolean) || '';
}

function laneAcceptanceCriteria(lane: RoomExecutionLane): string[] {
  for (const activity of lane.activities) {
    const criteria = activity.payload.acceptanceCriteria;
    if (Array.isArray(criteria)) return unique(criteria.map(text).filter(Boolean));
  }
  return [];
}

function laneResultSummary(
  lane: RoomExecutionLane,
  messages: RoomMessageProjection[],
): string {
  const publicResult = [...messages].reverse().find((message) => (
    ['result', 'work_result', 'review_result', 'handoff'].includes(message.postKind ?? '')
    && message.text.trim()
  ));
  if (publicResult) return publicResult.text.trim();
  return [...lane.activities].reverse().map((activity) => {
    const phase = text(activity.payload.phase);
    return ['completed', 'failed', 'aborted'].includes(phase)
      ? activity.summary.trim() || text(activity.payload.summary) || text(activity.payload.error)
      : '';
  }).find(Boolean) || '';
}

function laneCockpitState(
  lane: RoomExecutionLane,
  messages: RoomMessageProjection[],
  workItem: RoomWorkItem | undefined,
  fallback: CockpitState,
): CockpitState {
  if (workItem) {
    const state = workItemState(workItem.state);
    if (state !== 'waiting') return state;
  }
  if (messages.some((message) => message.postKind === 'blocked')) return 'attention';
  if (lane.activities.some((activity) => activity.status === 'failed')) return 'attention';
  if (lane.activities.some((activity) => activity.status === 'aborted')) return 'cancelled';
  if (messages.some((message) => ['result', 'work_result', 'review_result', 'handoff'].includes(message.postKind ?? ''))) return 'complete';
  if (lane.activities.some((activity) => text(activity.payload.phase) === 'completed')) return 'complete';
  if (lane.activities.some((activity) => activity.status === 'running')) return 'active';
  return fallback;
}

function flowStageState(items: FlowTaskItem[]): CockpitState {
  if (items.some((item) => item.state === 'contract')) return 'contract';
  if (items.some((item) => item.state === 'attention')) return 'attention';
  if (items.some((item) => item.state === 'active')) return 'active';
  if (items.some((item) => item.state === 'review')) return 'review';
  if (items.some((item) => item.state === 'recovery')) return 'recovery';
  if (items.length && items.every((item) => item.state === 'complete')) return 'complete';
  if (items.some((item) => item.state === 'cancelled')) return 'cancelled';
  return 'waiting';
}

function roomChildDelegations(
  activities: readonly RoomActivityProjection[],
  room: RoomSummary,
): RoomChildDelegationProjection[] {
  const byId = new Map<string, RoomChildDelegationProjection>();
  for (const activity of activities) {
    if (text(activity.payload.activityKind) !== 'child') continue;
    const id = text(activity.payload.childDispatchId)
      || text(activity.payload.dispatchId)
      || activity.id;
    const previous = byId.get(id);
    const phase = text(activity.payload.phase);
    const targetParticipantId = text(activity.payload.targetParticipantId)
      || previous?.targetParticipantId
      || (phase !== 'started' ? activity.participantId ?? '' : '');
    const parentParticipantId = text(activity.payload.parentParticipantId)
      || previous?.parentParticipantId
      || (phase === 'started' ? activity.participantId ?? '' : '');
    const state: CockpitState = phase === 'completed'
      ? 'complete'
      : phase === 'failed'
        ? 'attention'
        : phase === 'aborted'
          ? 'cancelled'
          : 'active';
    byId.set(id, {
      id,
      parentParticipantId,
      targetParticipantId,
      targetName: roomParticipantName(room, targetParticipantId),
      task: text(activity.payload.task) || previous?.task || '伙伴子调度',
      expectedOutput: text(activity.payload.expectedOutput) || previous?.expectedOutput || '',
      acceptanceCriteria: Array.isArray(activity.payload.acceptanceCriteria)
        ? unique(activity.payload.acceptanceCriteria.map(text).filter(Boolean))
        : previous?.acceptanceCriteria ?? [],
      waveId: text(activity.payload.waveId) || previous?.waveId || '',
      phaseName: text(activity.payload.phaseName) || previous?.phaseName || '',
      parallelIndex: typeof activity.payload.parallelIndex === 'number'
        ? activity.payload.parallelIndex
        : previous?.parallelIndex,
      parallelSize: typeof activity.payload.parallelSize === 'number'
        ? activity.payload.parallelSize
        : previous?.parallelSize,
      summary: activity.summary.trim()
        || text(activity.payload.summary)
        || text(activity.payload.error)
        || previous?.summary
        || '',
      state,
    });
  }
  return [...byId.values()];
}

export function roomPeerRelations(
  activities: readonly RoomActivityProjection[],
  room: RoomSummary,
): RoomPeerRelation[] {
  const byId = new Map<string, RoomPeerRelation>();
  for (const activity of activities) {
    if (text(activity.payload.activityKind) !== 'intercom') continue;
    const raw = activity.payload.message;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue;
    const message = raw as Record<string, unknown>;
    const sourceParticipantId = text(message.sourceParticipantId);
    const targetParticipantId = text(message.targetParticipantId);
    const kind = text(message.kind);
    if (!sourceParticipantId || !targetParticipantId || !['send', 'ask', 'reply'].includes(kind)) continue;
    const id = text(message.id) || activity.id;
    const state = intercomCockpitState(text(message.status) || text(activity.payload.phase));
    byId.set(id, {
      id,
      sourceParticipantId,
      sourceName: roomParticipantName(room, sourceParticipantId),
      targetParticipantId,
      targetName: roomParticipantName(room, targetParticipantId),
      kind: kind as RoomPeerRelation['kind'],
      state,
      content: text(message.content) || activity.summary.trim(),
      replyTo: text(message.replyTo),
    });
  }
  return [...byId.values()].sort((left, right) => left.id.localeCompare(right.id));
}

/** Intercom is a Room-wide peer channel and may use a delivery Session turn id
 * instead of the current Root id. Read the full projection so real A -> B and
 * B -> A edges remain visible in the task graph after Root convergence. */
export function roomPeerRelationsFromProjection(
  projection: RoomProjectionState,
  room: RoomSummary,
): RoomPeerRelation[] {
  return roomPeerRelations(
    projection.activityOrder
      .map((activityId) => projection.activitiesById[activityId])
      .filter((activity): activity is RoomActivityProjection => Boolean(activity)),
    room,
  );
}

function intercomCockpitState(status: string): CockpitState {
  if (['failed', 'stale'].includes(status)) return 'attention';
  if (status === 'cancelled') return 'cancelled';
  if (['queued', 'delivering', 'running'].includes(status)) return 'active';
  if (['delivered', 'replied', 'completed'].includes(status)) return 'complete';
  return 'waiting';
}

const PEER_GRAPH_NODE_WIDTH = 168;
const PEER_GRAPH_NODE_HEIGHT = 76;

interface PeerGraphPoint {
  x: number;
  y: number;
}

export interface PeerGraphLayout {
  width: number;
  height: number;
  nodes: Array<PeerGraphPoint & { participantId: string }>;
  edges: Array<{
    id: string;
    path: string;
    labelX: number;
    labelY: number;
    relation: RoomPeerRelation;
  }>;
}

/** Build a real node-edge layout: paths terminate on participant cards and
 * repeated messages occupy distinct curves with labels on the edges. */
export function roomPeerGraphLayout(
  participantIds: readonly string[],
  relations: readonly RoomPeerRelation[],
): PeerGraphLayout {
  const width = Math.max(640, participantIds.length * 210);
  const height = participantIds.length <= 2 ? 286 : 350;
  const center = { x: width / 2, y: height / 2 };
  const positions = new Map<string, PeerGraphPoint>();
  participantIds.forEach((participantId, index) => {
    if (participantIds.length === 1) {
      positions.set(participantId, center);
    } else if (participantIds.length === 2) {
      positions.set(participantId, { x: index === 0 ? 120 : width - 120, y: center.y });
    } else {
      const angle = -Math.PI / 2 + (index * Math.PI * 2) / participantIds.length;
      positions.set(participantId, {
        x: center.x + Math.cos(angle) * (width / 2 - 120),
        y: center.y + Math.sin(angle) * 112,
      });
    }
  });

  const visibleRelations = relations.filter((relation) => (
    positions.has(relation.sourceParticipantId)
    && positions.has(relation.targetParticipantId)
    && relation.sourceParticipantId !== relation.targetParticipantId
  ));
  const pairKey = (relation: RoomPeerRelation) => [
    relation.sourceParticipantId,
    relation.targetParticipantId,
  ].sort().join('\u001f');
  const pairCounts = new Map<string, number>();
  visibleRelations.forEach((relation) => {
    const key = pairKey(relation);
    pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
  });
  const pairIndexes = new Map<string, number>();
  const participantIndex = new Map(participantIds.map((id, index) => [id, index]));
  const edges = visibleRelations.map((relation) => {
    const key = pairKey(relation);
    const index = pairIndexes.get(key) ?? 0;
    pairIndexes.set(key, index + 1);
    const count = pairCounts.get(key) ?? 1;
    const offset = (index - (count - 1) / 2) * 54;
    const sourceCenter = positions.get(relation.sourceParticipantId)!;
    const targetCenter = positions.get(relation.targetParticipantId)!;
    const source = peerNodeBoundaryPoint(sourceCenter, targetCenter);
    const target = peerNodeBoundaryPoint(targetCenter, sourceCenter);
    const canonicalForward = (
      (participantIndex.get(relation.sourceParticipantId) ?? 0)
      < (participantIndex.get(relation.targetParticipantId) ?? 0)
    );
    const canonicalSource = canonicalForward ? sourceCenter : targetCenter;
    const canonicalTarget = canonicalForward ? targetCenter : sourceCenter;
    const dx = canonicalTarget.x - canonicalSource.x;
    const dy = canonicalTarget.y - canonicalSource.y;
    const length = Math.max(1, Math.hypot(dx, dy));
    const control = {
      x: (source.x + target.x) / 2 + (-dy / length) * offset,
      y: (source.y + target.y) / 2 + (dx / length) * offset,
    };
    return {
      id: relation.id,
      path: `M ${source.x.toFixed(1)} ${source.y.toFixed(1)} Q ${control.x.toFixed(1)} ${control.y.toFixed(1)} ${target.x.toFixed(1)} ${target.y.toFixed(1)}`,
      labelX: (source.x + 2 * control.x + target.x) / 4,
      labelY: (source.y + 2 * control.y + target.y) / 4,
      relation,
    };
  });
  return {
    width,
    height,
    nodes: participantIds.map((participantId) => ({
      participantId,
      ...positions.get(participantId)!,
    })),
    edges,
  };
}

function peerNodeBoundaryPoint(from: PeerGraphPoint, toward: PeerGraphPoint): PeerGraphPoint {
  const dx = toward.x - from.x;
  const dy = toward.y - from.y;
  const scale = 1 / Math.max(
    Math.abs(dx) / (PEER_GRAPH_NODE_WIDTH / 2),
    Math.abs(dy) / (PEER_GRAPH_NODE_HEIGHT / 2),
    Number.EPSILON,
  );
  return { x: from.x + dx * scale, y: from.y + dy * scale };
}

function PeerRelationGraph({
  participants,
  relations,
}: {
  participants: Array<Pick<PartnerProjection, 'participantId' | 'name' | 'assignment' | 'state'>>;
  relations: RoomPeerRelation[];
}) {
  const markerPrefix = useId().replace(/:/g, '');
  if (!participants.length) return null;
  const participantIds = participants.map((participant) => participant.participantId);
  const visibleRelations = relations.filter((relation) => (
    participantIds.includes(relation.sourceParticipantId)
    && participantIds.includes(relation.targetParticipantId)
  ));
  const layout = roomPeerGraphLayout(participantIds, visibleRelations);
  const participantById = new Map(participants.map((participant) => [
    participant.participantId,
    participant,
  ]));
  return <section aria-label="伙伴直接通信关系图" className="room-cockpit__peer-graph">
    <header className="room-cockpit__peer-graph-heading">
      <span><strong>直接 @ 关系</strong><small>伙伴是节点；带标签的箭头从 source 节点连到 target 节点。</small></span>
      <span>{visibleRelations.length} 条消息</span>
    </header>
    <div className="room-cockpit__peer-graph-canvas">
      <svg
        aria-label={`${participants.length} 位伙伴、${visibleRelations.length} 条直接通信的节点关系图`}
        className="room-cockpit__peer-network"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        style={participants.length > 4 ? { minWidth: layout.width + 'px' } : undefined}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
      >
        <title>伙伴直接通信节点关系图</title>
        <defs>
          {(['send', 'ask', 'reply', 'attention'] as const).map((kind) => <marker
            className={'room-cockpit__peer-arrow room-cockpit__peer-arrow--' + kind}
            id={`${markerPrefix}-room-peer-arrow-${kind}`}
            key={kind}
            markerHeight="7"
            markerWidth="7"
            orient="auto-start-reverse"
            refX="6"
            refY="3.5"
            viewBox="0 0 7 7"
          >
            <path d="M0,0 L7,3.5 L0,7 z" />
          </marker>)}
        </defs>
        <g className="room-cockpit__peer-network-edges">
          {layout.edges.map(({ id, labelX, labelY, path, relation }) => {
            const markerKind = ['attention', 'cancelled'].includes(relation.state)
              ? 'attention'
              : relation.kind;
            const label = `${peerRelationKindLabel(relation.kind)} · ${stateLabel(relation.state)}`;
            const labelWidth = Math.max(86, Math.min(132, label.length * 9 + 22));
            return <g data-kind={relation.kind} data-state={relation.state} key={id}>
              <path d={path} markerEnd={`url(#${markerPrefix}-room-peer-arrow-${markerKind})`} />
              <g className="room-cockpit__peer-edge-label" transform={`translate(${labelX} ${labelY})`}>
                <rect height="24" rx="12" width={labelWidth} x={-labelWidth / 2} y="-12" />
                <text dominantBaseline="central" textAnchor="middle">{label}</text>
              </g>
            </g>;
          })}
        </g>
        <g className="room-cockpit__peer-network-nodes">
          {layout.nodes.map((node) => {
            const participant = participantById.get(node.participantId)!;
            return <g
              data-state={participant.state}
              key={participant.participantId}
              transform={`translate(${node.x - PEER_GRAPH_NODE_WIDTH / 2} ${node.y - PEER_GRAPH_NODE_HEIGHT / 2})`}
            >
              <title>@ {participant.name}：{participant.assignment}</title>
              <rect height={PEER_GRAPH_NODE_HEIGHT} rx="14" width={PEER_GRAPH_NODE_WIDTH} />
              <text className="room-cockpit__peer-node-name" x="14" y="27">@ {participant.name}</text>
              <text className="room-cockpit__peer-node-state" x="14" y="47">{stateLabel(participant.state)}</text>
              <text className="room-cockpit__peer-node-assignment" x="14" y="65">{compactGraphText(participant.assignment)}</text>
            </g>;
          })}
        </g>
      </svg>
    </div>
    {visibleRelations.length ? <RoomSmoothDisclosure className="room-cockpit__peer-relation-details" summary={<>通信明细 · {visibleRelations.length} 条<ChevronDown className="room-cockpit__chevron" size={12} /></>}>
      <ol aria-label="伙伴直接通信列表" className="room-cockpit__peer-relation-list">
        {visibleRelations.map((relation) => <li data-kind={relation.kind} data-state={relation.state} key={relation.id}>
          <span className="room-cockpit__peer-relation-arrow">{relation.kind === 'ask' ? '?' : relation.kind === 'reply' ? '↩' : '→'}</span>
          <span><strong>@ {relation.sourceName} → @ {relation.targetName}</strong><small>{peerRelationKindLabel(relation.kind)} · {stateLabel(relation.state)}{relation.content ? ' · ' + relation.content : ''}</small></span>
        </li>)}
      </ol>
    </RoomSmoothDisclosure> : <p className="room-cockpit__peer-graph-empty">尚未记录伙伴之间的直接 @；分派关系仍会显示在下方任务流中。</p>}
  </section>;
}

function compactGraphText(value: string): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  return normalized.length > 22 ? normalized.slice(0, 21) + '…' : normalized;
}

function roomPeerParticipants(
  room: RoomSummary,
  partners: PartnerProjection[],
): Array<Pick<PartnerProjection, 'participantId' | 'name' | 'assignment' | 'state'>> {
  return room.participants
    .filter((participant) => participant.status === 'active')
    .map((participant) => partners.find((partner) => partner.participantId === participant.id) ?? {
      participantId: participant.id,
      name: roomPlanetName(participant.ordinal),
      assignment: '等待直接通信或分工',
      state: participant.id === room.moderatorParticipantId ? 'active' : 'waiting',
    });
}

function peerRelationKindLabel(kind: RoomPeerRelation['kind']): string {
  return kind === 'ask' ? '提问' : kind === 'reply' ? '回复' : '发送';
}

function partnerAssignment(workItems: RoomWorkItem[], activities: RoomActivityProjection[], fallback = ''): string {
  const workObjective = workItems.find((item) => item.objective.trim())?.objective.trim();
  if (workObjective) return workObjective;
  for (const activity of activities) {
    const objective = text(activity.payload.objective) || text(activity.payload.task) || text(activity.payload.expectedOutput);
    if (objective) return objective;
  }
  return fallback.trim() || '继续当前协作';
}

function partnerState(
  workItems: RoomWorkItem[],
  activities: RoomActivityProjection[],
  messages: RoomMessageProjection[],
  fallback?: RoomExecutionOverviewItem['status'],
): CockpitState {
  const workStates = workItems.map((item) => workItemState(item.state));
  if (workStates.includes('attention') || messages.some((message) => message.postKind === 'blocked')) return 'attention';
  if (workStates.includes('active') || activities.some((activity) => activity.status === 'running')) return 'active';
  if (workStates.includes('review')) return 'review';
  if (messages.some((message) => ['work_result', 'review_result', 'handoff'].includes(message.postKind ?? ''))) return 'complete';
  if (workStates.length && workStates.every((state) => ['complete', 'cancelled'].includes(state))) return 'complete';
  return runtimeState(fallback);
}

function roomPlan(
  facts: ReadonlyMap<string, RoomTaskSessionFact>,
  roomId: string,
  rootId: string,
): PlanProjection | undefined {
  const workflows = [...facts.values()].map((fact) => fact.workflow).filter((workflow): workflow is AgentWorkflowStateV1 => Boolean(workflow));
  const matching = workflows.find((workflow) => workflow.todo.roomLineage?.roomId === roomId && (!rootId || workflow.todo.roomLineage.rootId === rootId))
    ?? workflows.find((workflow) => workflow.todo.roomLineage?.roomId === roomId)
    ?? workflows.at(0);
  if (!matching) return undefined;
  const tasks = matching.todo.phases.flatMap((phase, phaseIndex) => phase.tasks.map((task, taskIndex) => ({
    id: `${matching.todo.id}:${phaseIndex}:${taskIndex}`,
    phase: phase.name || '执行计划',
    content: task.content,
    state: todoState(task.status),
    stateLabel: todoStateLabel(task.status),
  })));
  if (!tasks.length) return undefined;
  return {
    label: matching.todo.phases.length > 1 ? '执行计划与文档导航' : (matching.todo.phases.at(0)?.name || '执行计划'),
    completed: matching.todo.counts.completed,
    total: matching.todo.counts.total,
    tasks,
  };
}

function roomGoal(
  room: RoomSummary,
  runtime: RoomExecutionOverviewItem | undefined,
  facts: ReadonlyMap<string, RoomTaskSessionFact>,
  rootId: string,
): string {
  const workflowGoal = [...facts.values()].map((fact) => fact.workflow).find((workflow) => (
    workflow?.goal.configured
    && workflow.goal.objective.trim()
    && (!rootId || !workflow.todo.roomLineage || workflow.todo.roomLineage.rootId === rootId)
  ))?.goal.objective.trim();
  return runtime?.objective.trim() || workflowGoal || latestRoomWorkItem(room)?.objective.trim() || room.title;
}

function visibleSubagentBatches(fact: RoomTaskSessionFact | undefined, roomId: string, rootId: string) {
  return fact?.subagentBatches.filter((batch) => (
    batch.parentSessionId === fact.sessionId
    &&
    batch.causalMetadata.roomBound
    && batch.causalMetadata.roomId === roomId
    && (!rootId || batch.causalMetadata.rootId === rootId)
  )) ?? [];
}

function reasoningSummaries(activities: RoomActivityProjection[]): string[] {
  return unique(activities.flatMap((activity) => {
    if (text(activity.payload.sourceEventType) !== 'reasoning_summary') return [];
    if (text(activity.payload.source) !== 'provider_reasoning_summary') return [];
    const items = Array.isArray(activity.payload.items)
      ? activity.payload.items.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
      : [];
    return [...items, activity.summary].map((item) => item.trim()).filter(Boolean);
  }));
}

function toolSteps(activities: RoomActivityProjection[]): Array<{ id: string; name: string; summary: string; state: CockpitState }> {
  const steps = new Map<string, { id: string; name: string; summary: string; state: CockpitState }>();
  for (const activity of activities) {
    const sourceEventType = text(activity.payload.sourceEventType);
    if (!['tool_started', 'tool_progress', 'tool_finished'].includes(sourceEventType) && activity.kind !== 'tool') continue;
    const toolId = text(activity.payload.toolName) || text(activity.payload.name);
    const id = text(activity.payload.toolCallId) || `${toolId}:${activity.id}`;
    steps.set(id, {
      id,
      name: publicToolName(toolId, text(activity.payload.displayName)),
      summary: activity.summary.trim() || (sourceEventType === 'tool_finished' ? '已返回' : '正在执行'),
      state: activityState(activity.status),
    });
  }
  return [...steps.values()];
}

function findRootReply(
  projection: RoomProjectionState | undefined,
  turnId = '',
  moderatorParticipantId = '',
): RoomMessageProjection | undefined {
  if (!projection) return undefined;
  const ids = turnId ? projection.turnsById[turnId]?.messageIds ?? [] : projection.messageOrder;
  const candidates = [...ids].reverse().map((id) => projection.messagesById[id]).filter((message): message is RoomMessageProjection => (
    Boolean(message?.text.trim()) && message?.postKind === 'result'
  ));
  const published = candidates.find((message) => message.participantId === moderatorParticipantId)
    ?? candidates.at(0);
  if (published) return published;
  // Light Rooms do not require a second structured Post after Pi completes.
  // The moderator's terminal execution message is already the Root answer.
  if (turnId && projection.turnsById[turnId]?.status !== 'completed') return undefined;
  return [...ids].reverse().map((id) => projection.messagesById[id]).find((message) => (
    Boolean(message?.text.trim())
    && message?.role === 'assistant'
    && message?.status === 'completed'
    && message?.participantId === moderatorParticipantId
  ));
}

function roomOverallState(
  partners: PartnerProjection[],
  rootReply: RoomMessageProjection | undefined,
  runtime?: RoomExecutionOverviewItem['status'],
): CockpitState {
  if (rootReply) return 'complete';
  if (partners.some((partner) => partner.state === 'active')) return 'active';
  if (partners.some((partner) => partner.state === 'review')) return 'review';
  if (partners.some((partner) => ['attention', 'contract'].includes(partner.state))) return 'recovery';
  const fallback = runtimeState(runtime);
  return fallback === 'attention' ? 'recovery' : fallback;
}

function subagentResultText(run: AgentSubagentRunV1): string {
  const result = run.result as Record<string, unknown>;
  return [result.summary, result.text, result.output, result.message].map(text).find(Boolean) || '';
}

function subagentCockpitState(run: AgentSubagentRunV1): CockpitState {
  if (run.state === 'running') return 'active';
  if (isContractInvalid(run)) return 'contract';
  if (run.state === 'completed') return 'complete';
  if (['failed', 'timed_out'].includes(run.state)) return 'attention';
  if (run.state === 'aborted') return 'cancelled';
  return 'waiting';
}

function workRecoveryProjection(workItem: RoomWorkItem): WorkRecoveryProjection | undefined {
  const receiptRefs = [...workItem.evidenceRefs, ...workItem.artifactRefs].filter((reference) => (
    /(?:^|[:/#-])(?:tool[-_]?receipt|receipt|approval)(?:$|[:/#-])/iu.test(reference)
  ));
  if (workItem.state === 'done') {
    return {
      kind: 'sealed',
      label: '已完成 · 恢复时不重跑',
      detail: '终态 WorkItem 保持封存，只供 Root 汇合与历史导航。',
    };
  }
  if (workItem.state === 'review') {
    return {
      kind: 'acceptance',
      label: '已提交 · 等待自动汇合',
      detail: '恢复时只继续核对文档门槛并汇合，不重新执行已经交付的工作。',
    };
  }
  if (['failed', 'blocked', 'cancelled'].includes(workItem.state)) {
    if (receiptRefs.length) {
      return {
        kind: 'receipt',
        label: `先核对 ${receiptRefs.length} 个原 Tool 回执`,
        detail: '根据副作用是否已发生，选择继续、重试或转人工；不会盲目重放。',
      };
    }
    return {
      kind: 'repair',
      label: '不自动重试 · 等待修复或改派',
      detail: '当前没有足够回执证明可安全重放。',
    };
  }
  if (workItem.state === 'active' && receiptRefs.length) {
    return {
      kind: 'receipt',
      label: '已有副作用回执 · 恢复前核对',
      detail: '继续运行前先确认写入、命令或外部操作的原始结果。',
    };
  }
  return undefined;
}

function workItemState(state: RoomWorkState): CockpitState {
  return ({ queued: 'waiting', active: 'active', review: 'review', blocked: 'attention', done: 'complete', failed: 'attention', cancelled: 'cancelled' })[state] as CockpitState;
}

function runtimeState(state?: RoomExecutionOverviewItem['status']): CockpitState {
  return ({ queued: 'waiting', running: 'active', completed: 'complete', failed: 'attention', aborted: 'cancelled' } as const)[state ?? 'queued'];
}

function activityState(state: RoomActivityProjection['status']): CockpitState {
  return ({ running: 'active', waiting: 'waiting', completed: 'complete', failed: 'attention', aborted: 'cancelled' } as const)[state];
}

function todoState(state: 'pending' | 'in_progress' | 'blocked' | 'completed' | 'abandoned'): CockpitState {
  return ({ pending: 'waiting', in_progress: 'active', blocked: 'attention', completed: 'complete', abandoned: 'cancelled' })[state] as CockpitState;
}

function todoStateLabel(state: 'pending' | 'in_progress' | 'blocked' | 'completed' | 'abandoned'): string {
  return ({ pending: '等待开始', in_progress: '进行中', blocked: '已阻塞', completed: '已完成', abandoned: '已放弃' })[state];
}

function stateLabel(state: CockpitState): string {
  return ({ waiting: '等待开始', active: '进行中', review: '汇合中', complete: '已完成', attention: '需要处理', contract: '合同待修复', recovery: '等待修复/改派', cancelled: '已停止' })[state];
}

function stateIcon(state: CockpitState) {
  if (state === 'complete') return <CircleCheck aria-hidden="true" size={12} />;
  if (state === 'recovery') return <ShieldCheck aria-hidden="true" size={12} />;
  if (state === 'attention' || state === 'contract') return <CircleAlert aria-hidden="true" size={12} />;
  return <Clock3 aria-hidden="true" size={12} />;
}

function latestRoomWorkItem(room: RoomSummary): RoomWorkItem | undefined {
  return [...(room.workItems ?? [])].sort((left, right) => right.updatedAtMs - left.updatedAtMs).at(0);
}

function roomKnowledgeRefs(room: RoomSummary): string[] {
  return unique((room.workItems ?? []).flatMap((workItem) => workItem.evidenceRefs)
    .filter((reference) => /^(?:knowledge|kb)(?::|\/\/)/iu.test(reference.trim())))
    ;
}

function knowledgeReferenceLabel(reference: string): string {
  const normalized = reference.replace(/^(?:knowledge|kb)(?::|\/\/)/iu, '');
  const label = normalized.split(/[/?#]/u).filter(Boolean).at(-1) || 'Knowledge 来源';
  return label.length > 72 ? `${label.slice(0, 69)}…` : label;
}

function roomParticipantName(room: RoomSummary, participantId: string): string {
  const participant = room.participants.find((item) => item.id === participantId);
  return participant ? roomPlanetName(participant.ordinal) : '待接收';
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function shortId(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}

function safeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '-');
}
