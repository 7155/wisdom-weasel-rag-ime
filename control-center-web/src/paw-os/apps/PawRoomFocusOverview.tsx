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
import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';
import { Disclosure } from '@/components/primitives';
import {
  buildRoomFocusMesh,
  roomFocusMeshEdgeKindLabel,
  type RoomFocusMesh,
  type RoomFocusMeshEdge,
  type RoomFocusMeshNode,
} from './room-focus-mesh';
import {
  roomFocusHasCoordinator,
  roomFocusOriginLabel,
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
  | { kind: 'partner'; id: string }
  | { kind: 'edge'; id: string };

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
 * Sol collaboration console — the single Room 态势 surface. Mission chrome,
 * pulse, partner-only relationship graph, flow ledger and inspector all
 * project the same real Room data. The graph deliberately excludes Sol and
 * WorkItems as actors while keeping their task detail available in the
 * inspector (PF-CM-013, UR-023).
 */
export function PawRoomFocusOverview({
  focus,
  hideMission = false,
  onOpenParticipant,
  onSelectParticipant,
  selectedParticipantId,
}: {
  focus: RoomFocusProjection;
  hideMission?: boolean;
  onOpenParticipant?: (participantId: string, background?: boolean) => void;
  onSelectParticipant?: (participantId: string) => void;
  selectedParticipantId?: string;
}) {
  const defaultSelection = useMemo(() => defaultFocusSelection(focus), [focus]);
  const mesh = useMemo(() => buildRoomFocusMesh(focus), [focus]);
  const [selection, setSelection] = useState<FocusSelection>(defaultSelection);

  useEffect(() => {
    const stillExists = selection.kind === 'work'
      ? focus.workItems.some((item) => item.id === selection.id)
      : selection.kind === 'partner'
        ? focus.partners.some((partner) => partner.participantId === selection.id)
        : mesh.edges.some((edge) => edge.id === selection.id);
    if (!stillExists) setSelection(defaultSelection);
  }, [defaultSelection, focus.partners, focus.workItems, mesh.edges, selection]);

  useEffect(() => {
    if (!selectedParticipantId || !focus.partners.some((partner) => partner.participantId === selectedParticipantId)) return;
    setSelection((current) => current.kind === 'partner' && current.id === selectedParticipantId
      ? current
      : { kind: 'partner', id: selectedParticipantId });
  }, [focus.partners, selectedParticipantId]);

  const selectedWork = selection.kind === 'work'
    ? focus.workItems.find((item) => item.id === selection.id)
    : undefined;
  const selectedPartner = selection.kind === 'partner'
    ? focus.partners.find((partner) => partner.participantId === selection.id)
    : selectedWork
      ? focus.partners.find((partner) => partner.participantId === selectedWork.ownerParticipantId)
      : undefined;
  const coordinatorActive = roomFocusHasCoordinator(focus.partners);
  /* Until a connected partner really holds the coordinator role there is no
     Sol to name: the origin every surface still has to refer to is simply the
     shared main Room. */
  const originLabel = roomFocusOriginLabel(coordinatorActive);

  return (
    <section aria-label="Sol 协作态势" className="paw-room-focus-overview" data-coordinator={coordinatorActive || undefined}>
      {!hideMission && coordinatorActive ? <header className="paw-room-focus-overview__mission">
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
      </header> : !hideMission ? <header className="paw-room-focus-overview__mission paw-room-focus-overview__mission--dormant">
        <div>
          <small>等待主持</small>
          <strong>{focus.goal.title}</strong>
          <p>指定一位伙伴为「主持」后，Sol 协作态势与星空才会点亮。</p>
        </div>
      </header> : null}

      <FocusPulse counts={focus.counts} />

      <FocusMeshGraph
        focus={focus}
        mesh={mesh}
        selection={selection}
        onOpenParticipant={onOpenParticipant}
        onSelectParticipant={onSelectParticipant}
        selectedParticipantId={selectedParticipantId}
        onSelect={setSelection}
      />

      <FocusFlowLedger
        flow={focus.flow}
        originLabel={originLabel}
        partners={focus.partners}
        rootId={focus.goal.rootId}
        workItems={focus.workItems}
      />

      <FocusInspector
        onOpenParticipant={onOpenParticipant}
        originLabel={originLabel}
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

/** Partner-only collaboration graph. Sol remains mission chrome and WorkItems
 * remain inspectable data; neither is drawn as a collaborator node. */
function FocusMeshGraph({
  focus,
  mesh,
  onSelect,
  onOpenParticipant,
  onSelectParticipant,
  selectedParticipantId,
  selection,
}: {
  focus: RoomFocusProjection;
  mesh: RoomFocusMesh;
  onOpenParticipant?: (participantId: string, background?: boolean) => void;
  onSelectParticipant?: (participantId: string) => void;
  onSelect: (selection: FocusSelection) => void;
  selectedParticipantId?: string;
  selection: FocusSelection;
}) {
  const hasActors = focus.partners.length > 0;
  const arrowMarkerId = `paw-room-gravity-arrow-${useId().replace(/:/g, '')}`;
  const nodeLabels = useMemo(
    () => new Map(mesh.nodes.map((node) => [node.id, node.label])),
    [mesh.nodes],
  );
  return (
    <section aria-label="协作网" className="paw-room-focus-overview__section paw-room-focus-overview__mesh">
      <header>
        <span><Waypoints aria-hidden="true" size={14} /><strong>协作网</strong></span>
        <small>
          {focus.partners.length} 位行星伙伴 · {mesh.edges.length} 条已确认关系
          {mesh.nonDagRelations.length ? ` · ${mesh.nonDagRelations.length} 条未建立尝试` : ''}
        </small>
      </header>
      {hasActors ? (
        <>
          <div
            aria-label="协作网状图"
            className="paw-room-focus-overview__mesh-canvas"
            role="group"
            style={{ aspectRatio: `100 / ${mesh.height}` }}
          >
          <svg aria-hidden="true" focusable="false" preserveAspectRatio="none" viewBox={`0 0 100 ${mesh.height}`}>
            <defs>
              <marker
                id={arrowMarkerId}
                markerHeight="5"
                markerUnits="strokeWidth"
                markerWidth="5"
                orient="auto"
                overflow="visible"
                refX="3"
                refY="3"
                viewBox="0 0 6 6"
              >
                <path d="M 0 0 L 6 3 L 0 6 Z" fill="context-stroke" />
              </marker>
            </defs>
            {mesh.edges.map((edge) => (
              <g
                className="paw-room-focus-overview__mesh-edge"
                data-kind={edge.kind}
                data-state={edge.state}
                data-selected={selection.kind === 'edge' && selection.id === edge.id || undefined}
                key={edge.id}
              >
                <path
                  d={edge.path}
                  markerMid={`url(#${arrowMarkerId})`}
                  vectorEffect="non-scaling-stroke"
                />
              </g>
            ))}
          </svg>
          {mesh.edges.map((edge) => (
            <button
              aria-label={meshEdgeAriaLabel(edge, nodeLabels)}
              aria-pressed={selection.kind === 'edge' && selection.id === edge.id}
              className="paw-room-focus-overview__mesh-edge-label"
              data-kind={edge.kind}
              key={`${edge.id}:label`}
              onClick={() => onSelect({ kind: 'edge', id: edge.id })}
              style={{ left: `${edge.labelX}%`, top: `${(edge.labelY / mesh.height) * 100}%` }}
              type="button"
            >{edge.label}</button>
          ))}
          {mesh.nodes.map((node) => <FocusMeshNode
            canvasHeight={mesh.height}
            key={node.id}
            node={node}
            onOpenParticipant={onOpenParticipant}
            onSelectParticipant={onSelectParticipant}
            selected={selectedParticipantId
              ? selectedParticipantId === node.refId
              : selection.kind === 'partner' && selection.id === node.refId}
            onSelect={onSelect}
          />)}
          </div>
          {selection.kind === 'edge' ? (
            <MeshEdgeDetail
              edge={mesh.edges.find((candidate) => candidate.id === selection.id)}
              nodeLabels={nodeLabels}
              onOpenParticipant={onOpenParticipant}
              nodes={mesh.nodes}
            />
          ) : null}
          {mesh.nonDagRelations.length ? (
            <Disclosure
              aria-label="失败、等待与冲突关系"
              className="paw-room-focus-overview__mesh-disclosure"
              summary={`未进入成功 DAG · ${mesh.nonDagRelations.length} 条传递中 / 失败 / 冲突`}
            >
              <ol aria-label="未建立协作关系" className="paw-room-focus-overview__mesh-disclosure-list">
                {mesh.nonDagRelations.map((relation) => (
                  <li data-kind={relation.kind} data-state={relation.state} key={relation.id}>
                    <div className="paw-room-focus-overview__mesh-disclosure-route">
                      <strong>{nodeLabels.get(relation.sourceId) ?? relation.sourceId}</strong>
                      <span aria-hidden="true">→</span>
                      <strong>{nodeLabels.get(relation.targetId) ?? relation.targetId}</strong>
                      <span>{relation.label} · {relationStateLabel(relation.state)}</span>
                    </div>
                    <p className="paw-room-focus-overview__mesh-disclosure-reason">{relation.reason}</p>
                    <p className="paw-room-focus-overview__mesh-disclosure-summary">{relation.summary}</p>
                    <div className="paw-room-focus-overview__mesh-disclosure-provenance">
                      {relation.provenance.eventIds.map((value) => <code key={`event:${value}`}>事件 {value}</code>)}
                      {relation.provenance.workItemIds.map((value) => <code key={`work:${value}`}>任务 {value}</code>)}
                      {relation.provenance.dispatchIds.map((value) => <code key={`dispatch:${value}`}>分派 {value}</code>)}
                    </div>
                  </li>
                ))}
              </ol>
            </Disclosure>
          ) : null}
        </>
      ) : <p className="paw-room-focus-overview__empty">还没有任务。把目标发给 Room，协作网会从这里生长。</p>}
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

function relationStateLabel(state: string): string {
  if (state === 'sent') return '已发送';
  if (state === 'delivered') return '已送达';
  if (state === 'received') return '已接收';
  if (state === 'replied') return '已回复';
  if (state === 'offered') return '已提出';
  if (state === 'dispatched') return '已分派';
  if (state === 'accepted') return '已接受';
  if (state === 'confirmed') return '已确认';
  if (state === 'cancelled') return '已取消';
  if (state === 'rejected') return '已拒绝';
  return roomFocusStateLabel(state as RoomFocusState);
}

function meshEdgeAriaLabel(
  edge: RoomFocusMeshEdge,
  nodeLabels: ReadonlyMap<string, string>,
): string {
  return `${nodeLabels.get(edge.sourceId) ?? edge.sourceId} → ${nodeLabels.get(edge.targetId) ?? edge.targetId}，${edge.label}，${relationStateLabel(edge.state)}`;
}

function MeshEdgeDetail({
  edge,
  nodeLabels,
  nodes,
  onOpenParticipant,
}: {
  edge?: RoomFocusMeshEdge;
  nodeLabels: ReadonlyMap<string, string>;
  nodes: readonly RoomFocusMeshNode[];
  onOpenParticipant?: (participantId: string) => void;
}) {
  if (!edge) return null;
  const source = nodes.find((node) => node.id === edge.sourceId);
  const target = nodes.find((node) => node.id === edge.targetId);
  const provenance = [
    ['eventIds', edge.provenance.eventIds],
    ['workItemIds', edge.provenance.workItemIds],
    ['dispatchIds', edge.provenance.dispatchIds],
  ] as const;
  return (
    <section aria-label="协作关系详情" className="paw-room-focus-overview__mesh-detail" role="region">
      <header>
        <span><Waypoints aria-hidden="true" size={13} /><strong>协作关系</strong></span>
        <small>{edge.label} · {relationStateLabel(edge.state)}</small>
      </header>
      <p className="paw-room-focus-overview__mesh-detail-route">
        <strong>{nodeLabels.get(edge.sourceId) ?? edge.sourceId}</strong>
        {' → '}
        <strong>{nodeLabels.get(edge.targetId) ?? edge.targetId}</strong>
      </p>
      {edge.summary ? <p className="paw-room-focus-overview__mesh-detail-summary">{edge.summary}</p> : null}
      {edge.attempts.length ? (
        <div className="paw-room-focus-overview__mesh-detail-attempts">
          <div className="paw-room-focus-overview__mesh-detail-attempts-heading">
            <strong>确认尝试回执</strong>
            <span>{edge.attempts.length} 次</span>
          </div>
          <ol aria-label="确认尝试回执" className="paw-room-focus-overview__mesh-detail-attempt-list">
            {edge.attempts.map((attempt, index) => (
              <li key={attempt.id}>
                <div className="paw-room-focus-overview__mesh-detail-attempt-meta">
                  <strong>第 {index + 1} 次 · {relationStateLabel(attempt.state)}</strong>
                  <span>
                    时间 {attempt.createdAtMs}
                    {attempt.sequence === undefined ? '' : ` · 序列 ${attempt.sequence}`}
                  </span>
                </div>
                <p>{attempt.summary}</p>
                <div className="paw-room-focus-overview__mesh-detail-attempt-provenance">
                  <code>尝试 {attempt.id}</code>
                  {attempt.provenance.eventIds.map((value) => <code key={`event:${value}`}>事件 {value}</code>)}
                  {attempt.provenance.workItemIds.map((value) => <code key={`work:${value}`}>任务 {value}</code>)}
                  {attempt.provenance.dispatchIds.map((value) => <code key={`dispatch:${value}`}>分派 {value}</code>)}
                </div>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      <dl>
        <div><dt>关系类型</dt><dd>{edge.label}</dd></div>
        <div><dt>当前状态</dt><dd>{relationStateLabel(edge.state)}</dd></div>
        <div><dt>发生时间</dt><dd>{edge.createdAtMs}</dd></div>
        {provenance.map(([label, values]) => values.length ? (
          <div key={label}><dt>{label}</dt><dd>{values.map((value) => <code key={value}>{value}</code>)}</dd></div>
        ) : null)}
      </dl>
      {onOpenParticipant && source && target ? (
        <div className="paw-room-focus-overview__mesh-detail-actions">
          <button onClick={() => onOpenParticipant(source.refId)} type="button">打开 {source.label} 伙伴窗口</button>
          <button onClick={() => onOpenParticipant(target.refId)} type="button">打开 {target.label} 伙伴窗口</button>
        </div>
      ) : null}
    </section>
  );
}

function FocusMeshNode({
  canvasHeight,
  node,
  onOpenParticipant,
  onSelectParticipant,
  onSelect,
  selected,
}: {
  canvasHeight: number;
  node: RoomFocusMeshNode;
  onOpenParticipant?: (participantId: string, background?: boolean) => void;
  onSelectParticipant?: (participantId: string) => void;
  onSelect: (selection: FocusSelection) => void;
  selected: boolean;
}) {
  const position = { left: `${node.x}%`, top: `${Math.round((node.y / canvasHeight) * 10000) / 100}%` };
  const stateLabel = roomFocusStateLabel(node.state);
  return (
    <button
      aria-label={`${node.label}，${node.sublabel}，职责：${node.responsibility}，${stateLabel}`}
      aria-pressed={selected}
      className="paw-room-focus-overview__mesh-node paw-room-focus-overview__mesh-node--partner"
      data-tone={node.tone}
      data-state={node.state}
      onClick={() => {
        onSelect({ kind: 'partner', id: node.refId });
        onSelectParticipant?.(node.refId);
        /* A planet is the direct doorway to its one canonical Partner
         * satellite. The desktop raises an existing target when present, so
         * foregrounding it never creates a second conversation identity. */
        onOpenParticipant?.(node.refId);
      }}
      style={position}
      title={`${node.label} · ${node.sublabel} · ${node.responsibility}`}
      type="button"
    >
      <i aria-hidden="true" />
      <span>
        <strong>{node.label}</strong>
        <small>{node.sublabel}</small>
        <em>{node.responsibility}</em>
      </span>
    </button>
  );
}

/** Chronological ledger of what really moved between Sol and the planets:
 * public messages, approvals, dispatches, context transfers and WorkItem
 * revisions, in real event order. */
function FocusFlowLedger({
  flow,
  originLabel,
  partners,
  rootId,
  workItems,
}: {
  flow: RoomFocusPacket[];
  originLabel: string;
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
    ? originLabel
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
                aria-pressed={packet.id === selectedPacket?.id}
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
  const targetName = plan.targetParticipantId ? actorName(plan.targetParticipantId) : '伙伴';
  const objective = workItems.find((item) => item.id === plan.workItemId)?.objective;
  const selectedCandidates = plan.candidates.filter((candidate) => candidate.selected);
  return (
    <div aria-label="分派方案" className="paw-room-focus-overview__dispatch-plan" role="group">
      <span className="paw-room-focus-overview__dispatch-route">
        <b>{actorName(packet.sourceParticipantId)}</b>
        <ArrowRight aria-hidden="true" size={12} />
        <b>{targetName}</b>
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
                <small>{candidate.selected ? '已选中' : '候选行星'}</small>
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
  originLabel,
  partner,
  partners,
  work,
}: {
  onOpenParticipant?: (participantId: string) => void;
  originLabel: string;
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
        <strong>{work?.objective || partner?.celestialName || originLabel}</strong>
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
          <div><dt>负责人</dt><dd>{partner.celestialName} · {roomFocusStateLabel(partner.state)}</dd></div>
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
  if (kind === 'review') return <FileCheck2 size={13} />;
  if (kind === 'intercom') return <MessageCircle size={13} />;
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
    intercom: '伙伴请求',
    question: '问题',
    answer: '答复',
    plan: '计划',
    document: '文档',
    context: '上下文',
    result: '公开结果',
    dispatch: '任务分派',
    approval: '审批',
    review: '复核',
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
