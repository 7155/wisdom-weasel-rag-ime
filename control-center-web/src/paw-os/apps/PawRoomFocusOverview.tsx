import {
  ArrowRight,
  CircleHelp,
  ExternalLink,
  FileCheck2,
  FileText,
  GitBranch,
  MessageCircle,
  Route,
  Send,
  ShieldCheck,
  Waypoints,
} from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Disclosure } from '@/components/primitives';
import {
  buildRoomFocusMesh,
  roomFocusMeshEdgeKindLabel,
  type RoomFocusMeshNode,
} from './room-focus-mesh';
import {
  roomFocusStateLabel,
  type RoomFocusPacket,
  type RoomFocusPacketKind,
  type RoomFocusPartner,
  type RoomFocusProjection,
  type RoomFocusState,
  type RoomFocusWorkItem,
} from './room-focus-projection';
import type { RoomDispatchPlan } from './room-gravity-projection';

type FocusSelection =
  | { kind: 'work'; id: string }
  | { kind: 'partner'; id: string };

const selectionPriority: RoomFocusState[] = [
  'blocked',
  'failed',
  'review',
  'running',
  'waiting',
  'completed',
  'stopped',
  'idle',
  'disconnected',
];

const FLOW_PACKET_WINDOW = 18;

/**
 * Sol collaboration console — the single Room 态势 surface. Mission, the
 * pulse instrument, the chronological collaboration mesh (partners and
 * WorkItems as nodes on a top→bottom time axis,
 * ownership/accountability/review/lineage/handoff as edges), the
 * chronological flow ledger and the inspector all project the same real Room
 * data. The solar metaphor stays visual seasoning: every node keeps its real
 * role/task text (PF-CM-013, UR-023).
 */
export function PawRoomFocusOverview({
  focus,
  hideMission = false,
  onOpenParticipant,
}: {
  focus: RoomFocusProjection;
  hideMission?: boolean;
  onOpenParticipant?: (participantId: string) => void;
}) {
  const defaultSelection = useMemo(() => defaultFocusSelection(focus), [focus]);
  const [selection, setSelection] = useState<FocusSelection>(defaultSelection);

  useEffect(() => {
    const stillExists = selection.kind === 'work'
      ? focus.workItems.some((item) => item.id === selection.id)
      : focus.partners.some((partner) => partner.participantId === selection.id);
    if (!stillExists) setSelection(defaultSelection);
  }, [defaultSelection, focus.partners, focus.workItems, selection]);

  const selectedWork = selection.kind === 'work'
    ? focus.workItems.find((item) => item.id === selection.id)
    : undefined;
  const selectedPartner = selection.kind === 'partner'
    ? focus.partners.find((partner) => partner.participantId === selection.id)
    : selectedWork
      ? focus.partners.find((partner) => partner.participantId === selectedWork.ownerParticipantId)
      : undefined;

  return (
    <section aria-label="Sol 协作态势" className="paw-room-focus-overview">
      {!hideMission ? <header className="paw-room-focus-overview__mission">
        <span aria-hidden="true" className="paw-room-focus-overview__sol"><i /></span>
        <div>
          <small>Sol · 当前目标</small>
          <strong>{focus.goal.title}</strong>
          {focus.goal.description ? <p>{focus.goal.description}</p> : null}
        </div>
        <div aria-label={`目标状态：${roomFocusStateLabel(focus.goal.state)}`} className="paw-room-focus-overview__mission-state" data-state={focus.goal.state}>
          <i aria-hidden="true" />
          <span>{roomFocusStateLabel(focus.goal.state)}</span>
        </div>
      </header> : null}

      <FocusPulse counts={focus.counts} />

      <FocusMeshGraph
        focus={focus}
        selection={selection}
        onSelect={setSelection}
      />

      <FocusFlowLedger
        flow={focus.flow}
        partners={focus.partners}
        rootId={focus.goal.rootId}
        workItems={focus.workItems}
      />

      <FocusInspector
        onOpenParticipant={onOpenParticipant}
        partner={selectedPartner}
        partners={focus.partners}
        work={selectedWork}
      />
    </section>
  );
}

/** 任务脉搏 — the four real counters as one proportional bar plus the exact
 * numbers. Zero work renders a quiet track, never a fake segment. */
function FocusPulse({ counts }: { counts: RoomFocusProjection['counts'] }) {
  const segments = [
    ['active', counts.active, '进行'],
    ['review', counts.review, '复核'],
    ['blocked', counts.blocked, '受阻'],
    ['completed', counts.completed, '完成'],
  ] as const;
  const total = counts.active + counts.review + counts.blocked + counts.completed;
  return (
    <section aria-label="协作摘要" className="paw-room-focus-overview__pulse">
      <div aria-hidden="true" className="paw-room-focus-overview__pulse-bar" data-empty={total === 0 || undefined}>
        {segments.map(([tone, count]) => count > 0
          ? <i data-tone={tone} key={tone} style={{ flexGrow: count }} title={`${count}`} />
          : null)}
      </div>
      <dl className="paw-room-focus-overview__counts">
        {segments.map(([tone, count, label]) => (
          <div data-tone={tone} data-zero={count === 0 || undefined} key={tone}><dt>{label}</dt><dd>{count}</dd></div>
        ))}
      </dl>
    </section>
  );
}

/** 协作时序网 — partners and WorkItems as one chronological flow graph.
 * Columns are identity lanes (Sol origin, then each partner); vertical order
 * is real event order, so reading top→bottom is reading time. Nodes carry
 * real names and live state colors; edges draw only recorded relations
 * (ownership, accountability, review, parent/child lineage, handoffs).
 * Clicking a node drives the same selection the inspector and open-partner
 * path already use. */
function FocusMeshGraph({
  focus,
  onSelect,
  selection,
}: {
  focus: RoomFocusProjection;
  onSelect: (selection: FocusSelection) => void;
  selection: FocusSelection;
}) {
  const mesh = useMemo(() => buildRoomFocusMesh(focus), [focus]);
  const hasActors = focus.partners.length > 0 || focus.workItems.length > 0;
  return (
    <section aria-label="协作网" className="paw-room-focus-overview__section paw-room-focus-overview__mesh">
      <header>
        <span><Waypoints aria-hidden="true" size={14} /><strong>协作网</strong></span>
        <small>{focus.partners.length} 位伙伴 · {focus.workItems.length} 项任务 · 时间自上而下</small>
      </header>
      {hasActors ? (
        <div
          aria-label="协作网状图"
          className="paw-room-focus-overview__mesh-canvas"
          role="group"
          style={{ aspectRatio: `100 / ${mesh.height}` }}
        >
          <svg aria-hidden="true" focusable="false" preserveAspectRatio="none" viewBox={`0 0 100 ${mesh.height}`}>
            {mesh.lanes.map((lane) => (
              <line
                className="paw-room-focus-overview__mesh-lane"
                key={lane.id}
                vectorEffect="non-scaling-stroke"
                x1={lane.x}
                x2={lane.x}
                y1={lane.y0}
                y2={lane.y1}
              />
            ))}
            {mesh.edges.map((edge) => (
              <g
                className="paw-room-focus-overview__mesh-edge"
                data-kind={edge.kind}
                data-state={edge.state}
                key={edge.id}
              >
                <path d={edge.path} vectorEffect="non-scaling-stroke" />
                {edge.tip ? <circle cx={edge.tip.x} cy={edge.tip.y} r="1.1" /> : null}
              </g>
            ))}
          </svg>
          {mesh.nodes.map((node) => <FocusMeshNode
            canvasHeight={mesh.height}
            key={node.id}
            node={node}
            selected={node.kind === 'work'
              ? selection.kind === 'work' && selection.id === node.refId
              : node.kind === 'partner' && selection.kind === 'partner' && selection.id === node.refId}
            onSelect={onSelect}
          />)}
        </div>
      ) : <p className="paw-room-focus-overview__empty">还没有任务。把目标发给 Room，协作网会从这里生长。</p>}
      {mesh.timeline ? (
        <p className="paw-room-focus-overview__mesh-timespan">
          <span>起 {packetClock(mesh.timeline.startMs)}</span>
          <span>止 {packetClock(mesh.timeline.endMs)}</span>
        </p>
      ) : null}
      {mesh.edgeKinds.length ? (
        <ul aria-label="关系图例" className="paw-room-focus-overview__mesh-legend">
          {mesh.edgeKinds.map((kind) => (
            <li data-kind={kind} key={kind}><i aria-hidden="true" />{roomFocusMeshEdgeKindLabel(kind)}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function FocusMeshNode({
  canvasHeight,
  node,
  onSelect,
  selected,
}: {
  canvasHeight: number;
  node: RoomFocusMeshNode;
  onSelect: (selection: FocusSelection) => void;
  selected: boolean;
}) {
  const position = { left: `${node.x}%`, top: `${Math.round((node.y / canvasHeight) * 10000) / 100}%` };
  if (node.kind === 'root') {
    return (
      <div
        aria-label={`Sol，${roomFocusStateLabel(node.state)}`}
        className="paw-room-focus-overview__mesh-node paw-room-focus-overview__mesh-node--root"
        data-state={node.state}
        role="img"
        style={position}
        title={node.label}
      >
        <i aria-hidden="true" />
        <span><strong>Sol</strong></span>
      </div>
    );
  }
  const stateLabel = roomFocusStateLabel(node.state);
  return (
    <button
      aria-label={node.kind === 'partner'
        ? `${node.label}，${node.sublabel ?? ''}，${stateLabel}`
        : `${node.label}，${stateLabel}`}
      aria-pressed={selected}
      className={`paw-room-focus-overview__mesh-node paw-room-focus-overview__mesh-node--${node.kind}`}
      data-tone={node.tone}
      data-state={node.state}
      onClick={() => onSelect(node.kind === 'partner'
        ? { kind: 'partner', id: node.refId }
        : { kind: 'work', id: node.refId })}
      style={position}
      title={node.sublabel ? `${node.label} · ${node.sublabel}` : node.label}
      type="button"
    >
      <i aria-hidden="true" />
      <span>
        <strong>{node.label}</strong>
        {node.sublabel ? <small>{node.sublabel}</small> : null}
      </span>
    </button>
  );
}

/** Chronological ledger of what really moved between Sol and the planets:
 * public messages, approvals, dispatches, context transfers and WorkItem
 * revisions, in real event order. */
function FocusFlowLedger({
  flow,
  partners,
  rootId,
  workItems,
}: {
  flow: RoomFocusPacket[];
  partners: RoomFocusPartner[];
  rootId: string;
  workItems: RoomFocusWorkItem[];
}) {
  const [selectedPacketId, setSelectedPacketId] = useState('');
  const [showAllPackets, setShowAllPackets] = useState(false);
  useEffect(() => {
    setShowAllPackets(false);
    setSelectedPacketId('');
  }, [rootId]);
  const selectedPacket = flow.find((packet) => packet.id === selectedPacketId) ?? flow.at(-1);
  const visiblePackets = showAllPackets ? flow : flow.slice(-FLOW_PACKET_WINDOW);
  const actorName = (actorId: string) => actorId === 'root'
    ? 'Sol'
    : partners.find((partner) => partner.participantId === actorId)?.celestialName ?? actorId;

  return (
    <section aria-label="往来记录" className="paw-room-focus-overview__section paw-room-focus-overview__flow">
      <header>
        <span><GitBranch aria-hidden="true" size={14} /><strong>往来记录</strong></span>
        <span className="paw-room-focus-overview__flow-window">
          <small>最近 {visiblePackets.length} / 共 {flow.length} 条</small>
          {flow.length > visiblePackets.length ? <button onClick={() => setShowAllPackets(true)} type="button">显示全部</button> : null}
        </span>
      </header>
      {flow.length ? (
        <ol aria-label="往来事件" className="paw-room-focus-overview__packets">
          {visiblePackets.map((packet, index) => (
            <li data-kind={packet.kind} data-status={packet.status} key={packet.id}>
              <button
                aria-current={packet.id === selectedPacket?.id || undefined}
                onClick={() => setSelectedPacketId(packet.id)}
                type="button"
              >
                <span aria-hidden="true" className="paw-room-focus-overview__packet-icon">{packetIcon(packet.kind)}</span>
                <span className="paw-room-focus-overview__packet-copy">
                  <strong>{packetKindLabel(packet.kind)}</strong>
                  <p>{packet.summary}</p>
                  <small>
                    #{flow.length - visiblePackets.length + index + 1}
                    {' · '}{actorName(packet.sourceParticipantId)} → {packet.targetParticipantIds.map(actorName).join('、') || 'Room'}
                    {packet.createdAtMs ? ` · ${packetClock(packet.createdAtMs)}` : ''}
                  </small>
                </span>
              </button>
            </li>
          ))}
        </ol>
      ) : <p className="paw-room-focus-overview__empty">还没有公开往来。第一条消息发出后，这里会记下谁把什么交给了谁。</p>}
      {selectedPacket ? (
        <div className="paw-room-focus-overview__packet-detail">
          <header>
            <strong>{packetKindLabel(selectedPacket.kind)}</strong>
            <span data-status={selectedPacket.status}>{flowStatusLabel(selectedPacket.status)}</span>
          </header>
          <p>{selectedPacket.summary}</p>
          {selectedPacket.dispatchPlan ? (
            <FocusDispatchPlan
              actorName={actorName}
              packet={selectedPacket}
              plan={selectedPacket.dispatchPlan}
              workItems={workItems}
            />
          ) : null}
          {selectedPacket.dispatchId || selectedPacket.workItemId || selectedPacket.refs.length ? (
            <dl>
              {selectedPacket.dispatchId ? <><dt>分派</dt><dd>{selectedPacket.dispatchId}</dd></> : null}
              {selectedPacket.workItemId ? <><dt>任务</dt><dd>{selectedPacket.workItemId}</dd></> : null}
              {selectedPacket.refs.length ? <><dt>上下文 / 文档</dt><dd>{selectedPacket.refs.join('\n')}</dd></> : null}
            </dl>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** A route_decision as a readable plan: who exerted the gravity on whom, why,
 * inside which parallel wave, for which real task — plus the scored候选. */
function FocusDispatchPlan({
  actorName,
  packet,
  plan,
  workItems,
}: {
  actorName: (actorId: string) => string;
  packet: RoomFocusPacket;
  plan: RoomDispatchPlan;
  workItems: RoomFocusWorkItem[];
}) {
  const targetName = plan.targetParticipantId ? actorName(plan.targetParticipantId) : plan.targetDisplayName || '伙伴';
  const objective = workItems.find((item) => item.id === plan.workItemId)?.objective;
  const selectedCandidates = plan.candidates.filter((candidate) => candidate.selected);
  return (
    <div aria-label="分派方案" className="paw-room-focus-overview__dispatch-plan" role="group">
      <span className="paw-room-focus-overview__dispatch-route">
        <b>{actorName(packet.sourceParticipantId)}</b>
        <ArrowRight aria-hidden="true" size={12} />
        <b>{targetName}</b>
        {plan.targetDisplayName ? <small>{plan.targetDisplayName}</small> : null}
      </span>
      <dl>
        <div><dt>方式</dt><dd>{plan.reasonLabel}{plan.routingPolicyLabel ? ` · ${plan.routingPolicyLabel}` : ''}</dd></div>
        {plan.parallelIndex >= 0 && plan.parallelSize > 1 ? (
          <div><dt>并行</dt><dd>轨道 {plan.parallelIndex + 1}/{plan.parallelSize}{plan.phaseName ? ` · ${plan.phaseName}` : ''}</dd></div>
        ) : plan.phaseName ? <div><dt>阶段</dt><dd>{plan.phaseName}</dd></div> : null}
        {objective ? <div><dt>任务</dt><dd className="paw-room-focus-overview__dispatch-objective">{objective}</dd></div> : null}
      </dl>
      {plan.candidates.length ? (
        <Disclosure
          className="paw-room-focus-overview__dispatch-candidates"
          summary={`候选 ${plan.candidates.length} 位 · 选中 ${selectedCandidates.length} 位`}
        >
          <ul>
            {plan.candidates.map((candidate) => (
              <li data-selected={candidate.selected || undefined} key={candidate.participantId}>
                <strong>{actorName(candidate.participantId)}</strong>
                <small>{candidate.displayName}</small>
                <span>{candidate.signals.length ? candidate.signals.join('、') : '无信号'} · {candidate.score.toFixed(1)}</span>
              </li>
            ))}
          </ul>
        </Disclosure>
      ) : null}
    </div>
  );
}

function FocusInspector({
  onOpenParticipant,
  partner,
  partners,
  work,
}: {
  onOpenParticipant?: (participantId: string) => void;
  partner?: RoomFocusPartner;
  partners: RoomFocusPartner[];
  work?: RoomFocusWorkItem;
}) {
  const state = work?.state ?? partner?.state ?? 'idle';
  const action = workAction(work) || partner?.currentAction || '等待新的工作项';
  const evidence = work?.evidence ?? [];
  const verifier = work?.review
    ? partners.find((candidate) => candidate.participantId === work.review?.reviewerParticipantId)
    : undefined;
  return (
    <section aria-label="焦点详情" className="paw-room-focus-overview__inspector" data-state={state} key={`${work?.id ?? ''}:${partner?.participantId ?? ''}`} role="region">
      <header>
        <span><FileCheck2 aria-hidden="true" size={14} /><strong>焦点详情</strong></span>
        <span className="paw-room-focus-overview__state"><i aria-hidden="true" />{roomFocusStateLabel(state)}</span>
      </header>
      <div className="paw-room-focus-overview__inspector-copy">
        <small>{work ? '当前任务' : '当前伙伴'}</small>
        <strong>{work?.objective || partner?.celestialName || 'Sol'}</strong>
        <p>{action}</p>
      </div>
      {work?.wave ? (
        <p className="paw-room-focus-overview__inspector-wave">
          <Waypoints aria-hidden="true" size={12} />
          并行轨道 {Math.max(work.wave.parallelIndex, 0) + 1}/{Math.max(work.wave.parallelSize, 1)}
          {work.wave.phaseName ? ` · ${work.wave.phaseName}` : ''}
        </p>
      ) : null}
      {partner ? (
        <dl>
          <div><dt>负责人</dt><dd>{partner.celestialName} · {partner.displayName}</dd></div>
          {partner.latestReceipt ? <div><dt>最近回执</dt><dd>{partner.latestReceipt}</dd></div> : null}
        </dl>
      ) : null}
      {work?.expectedOutput ? (
        <p className="paw-room-focus-overview__expected"><span>期望交付</span>{work.expectedOutput}</p>
      ) : null}
      {work?.acceptanceCriteria.length ? (
        <Disclosure
          className="paw-room-focus-overview__acceptance"
          summary={`验收条件 · ${work.acceptanceCriteria.length}`}
        >
          <ul>{work.acceptanceCriteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul>
        </Disclosure>
      ) : null}
      {work?.blocker ? (
        <div className="paw-room-focus-overview__blocker">
          <strong>{work.blocker.reason}</strong>
          {work.blocker.nextStep ? <span>下一步：{work.blocker.nextStep}</span> : null}
        </div>
      ) : null}
      {work?.review ? (
        <div className="paw-room-focus-overview__review" data-verdict={reviewPassed(work) ? 'passed' : 'attention'}>
          <span><ShieldCheck aria-hidden="true" size={13} />独立复核{verifier ? ` · ${verifier.celestialName}` : ''}</span>
          <dl>
            <div><dt>可运行</dt><dd>{reviewVerdictLabel(work.review.operability)}</dd></div>
            <div><dt>符合需求</dt><dd>{reviewVerdictLabel(work.review.requirement)}</dd></div>
          </dl>
          {work.review.reason ? <p>{work.review.reason}</p> : null}
        </div>
      ) : null}
      {work?.latestResult ? <p className="paw-room-focus-overview__result">{work.latestResult}</p> : null}
      {evidence.length ? (
        <ul aria-label="证据与产物" className="paw-room-focus-overview__evidence">
          {evidence.map((item) => <li key={`${item.kind}:${item.ref}`}><span>{item.kind === 'artifact' ? '产物' : '证据'}</span><code>{item.ref}</code></li>)}
        </ul>
      ) : null}
      {partner && onOpenParticipant ? (
        <button className="paw-room-focus-overview__open" onClick={() => onOpenParticipant(partner.participantId)} type="button">
          <ExternalLink aria-hidden="true" size={13} />打开 {partner.celestialName} 伙伴窗口
        </button>
      ) : null}
    </section>
  );
}

function reviewPassed(work: RoomFocusWorkItem): boolean {
  if (!work.review) return false;
  const good = new Set(['passed', 'satisfied', 'pass', 'ok']);
  return good.has(work.review.operability) && good.has(work.review.requirement);
}

function reviewVerdictLabel(verdict: string): string {
  return ({
    passed: '通过',
    pass: '通过',
    satisfied: '满足',
    ok: '通过',
    failed: '未通过',
    unsatisfied: '未满足',
    blocked: '受阻',
  } as Record<string, string>)[verdict] ?? (verdict || '未记录');
}

function packetIcon(kind: RoomFocusPacketKind): ReactNode {
  if (kind === 'approval') return <ShieldCheck size={13} />;
  if (kind === 'question') return <CircleHelp size={13} />;
  if (kind === 'plan') return <GitBranch size={13} />;
  if (kind === 'document' || kind === 'context') return <FileText size={13} />;
  if (kind === 'result' || kind === 'answer') return <MessageCircle size={13} />;
  if (kind === 'dispatch') return <Route size={13} />;
  return <Send size={13} />;
}

function packetKindLabel(kind: RoomFocusPacketKind): string {
  return ({
    request: '需求',
    question: '问题',
    answer: '答复',
    plan: '计划',
    document: '文档',
    context: '上下文',
    result: '公开结果',
    dispatch: '任务分派',
    approval: '审批',
  } satisfies Record<RoomFocusPacketKind, string>)[kind];
}

function flowStatusLabel(status: string): string {
  return ({
    queued: '等待送达',
    running: '传递中',
    waiting: '等待批准',
    active: '进行中',
    review: '待复核',
    completed: '已送达',
    done: '已完成',
    failed: '失败',
    aborted: '已停止',
    blocked: '受阻',
  } as Record<string, string>)[status] ?? status;
}

function packetClock(timestamp: number): string {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(timestamp));
}

function defaultFocusSelection(focus: RoomFocusProjection): FocusSelection {
  for (const state of selectionPriority) {
    const item = focus.workItems.find((candidate) => candidate.state === state);
    if (item) return { kind: 'work', id: item.id };
  }
  const partner = focus.partners.at(0);
  return partner ? { kind: 'partner', id: partner.participantId } : { kind: 'work', id: '' };
}

function workAction(work?: RoomFocusWorkItem): string {
  if (!work) return '';
  if (work.currentAction) return work.currentAction;
  if (work.blocker?.reason) return work.blocker.reason;
  if (work.reviewRequired) return '等待独立复核';
  return work.latestResult || work.expectedOutput || '';
}
