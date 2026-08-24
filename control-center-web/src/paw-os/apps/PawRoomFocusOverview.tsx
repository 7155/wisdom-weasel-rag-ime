import {
  ArrowRight,
  CircleHelp,
  ExternalLink,
  FileCheck2,
  FileText,
  GitBranch,
  GitCommitHorizontal,
  MessageCircle,
  Orbit,
  Route,
  Send,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Disclosure } from '@/components/primitives';
import {
  roomFocusStateLabel,
  type RoomFocusPacket,
  type RoomFocusPacketKind,
  type RoomFocusPartner,
  type RoomFocusProjection,
  type RoomFocusState,
  type RoomFocusWorkItem,
} from './room-focus-projection';

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
 * Sol collaboration console — the single Room 态势 surface. Mission,
 * WorkItem tree, planet partners, handoffs, the chronological flow ledger and
 * the inspector all project the same real Room data; there is no separate
 * flow/execution panel to keep in sync anymore.
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

      <dl aria-label="协作摘要" className="paw-room-focus-overview__counts">
        <div data-tone="active"><dt>进行</dt><dd>{focus.counts.active}</dd></div>
        <div data-tone="review"><dt>复核</dt><dd>{focus.counts.review}</dd></div>
        <div data-tone="blocked"><dt>受阻</dt><dd>{focus.counts.blocked}</dd></div>
        <div data-tone="completed"><dt>完成</dt><dd>{focus.counts.completed}</dd></div>
      </dl>

      <section aria-labelledby="paw-room-focus-work-title" className="paw-room-focus-overview__section paw-room-focus-overview__work">
        <header>
          <span><GitCommitHorizontal aria-hidden="true" size={14} /><strong id="paw-room-focus-work-title">任务树</strong></span>
          <small>{focus.workItems.length} 项</small>
        </header>
        {focus.workItems.length ? (
          <ol aria-label="任务树" className="paw-room-focus-overview__tree" role="tree">
            {focus.workItems.map((item) => {
              const partner = focus.partners.find((candidate) => candidate.participantId === item.ownerParticipantId);
              const level = item.parentId ? 2 : 1;
              const selected = selection.kind === 'work' && selection.id === item.id;
              return (
                <li aria-level={level} aria-selected={selected} data-level={level} data-state={item.state} key={item.id} role="treeitem">
                  <button onClick={() => setSelection({ kind: 'work', id: item.id })} type="button">
                    <span aria-hidden="true" className="paw-room-focus-overview__tree-node"><i /></span>
                    <span className="paw-room-focus-overview__tree-copy">
                      <strong>{item.objective}</strong>
                      <small>{workAction(item)}{partner ? ` · ${partner.celestialName}` : ''}</small>
                    </span>
                    <span className="paw-room-focus-overview__state"><i aria-hidden="true" />{roomFocusStateLabel(item.state)}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        ) : <p className="paw-room-focus-overview__empty">还没有任务。把目标发给 Room，任务会从这里生长。</p>}
      </section>

      <section aria-labelledby="paw-room-focus-partners-title" className="paw-room-focus-overview__section paw-room-focus-overview__partners">
        <header>
          <span><Orbit aria-hidden="true" size={14} /><strong id="paw-room-focus-partners-title">行星伙伴</strong></span>
          <small>{focus.partners.length} 位</small>
        </header>
        <ul aria-label="行星伙伴" className="paw-room-focus-overview__planet-list" role="list">
          {focus.partners.map((partner, index) => {
            const selected = selection.kind === 'partner' && selection.id === partner.participantId;
            return (
              <li data-orbit={index % 4} data-state={partner.state} key={partner.participantId}>
                <button
                  aria-pressed={selected}
                  aria-label={`${partner.celestialName}，${partner.displayName}，${roomFocusStateLabel(partner.state)}`}
                  onClick={() => setSelection({ kind: 'partner', id: partner.participantId })}
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    setSelection({ kind: 'partner', id: partner.participantId });
                  }}
                  type="button"
                >
                  <span aria-hidden="true" className="paw-room-focus-overview__planet"><i /></span>
                  <span><strong>{partner.celestialName}</strong><small>{partner.displayName}</small></span>
                  <span className="paw-room-focus-overview__state"><i aria-hidden="true" />{roomFocusStateLabel(partner.state)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-label="任务交接" className="paw-room-focus-overview__section paw-room-focus-overview__handoffs">
        <header>
          <span><ArrowRight aria-hidden="true" size={14} /><strong>任务交接</strong></span>
          <small>{focus.handoffs.length} 次</small>
        </header>
        {focus.handoffs.length ? (
          <ol>
            {focus.handoffs.map((handoff) => {
              const source = focus.partners.find((partner) => partner.participantId === handoff.sourceParticipantId);
              const target = focus.partners.find((partner) => partner.participantId === handoff.targetParticipantId);
              return (
                <li data-state={handoff.state} key={handoff.id}>
                  <span><strong>{source?.celestialName ?? 'Sol'} → {target?.celestialName ?? '伙伴'}</strong><small>{handoff.task || handoff.artifactOrContract || '工作项交接'}</small></span>
                  <span className="paw-room-focus-overview__state"><i aria-hidden="true" />{roomFocusHandoffStateLabel(handoff.state)}</span>
                </li>
              );
            })}
          </ol>
        ) : <p className="paw-room-focus-overview__empty">当前没有待追踪的交接。</p>}
      </section>

      <FocusFlowLedger flow={focus.flow} partners={focus.partners} rootId={focus.goal.rootId} />

      <FocusInspector
        onOpenParticipant={onOpenParticipant}
        partner={selectedPartner}
        work={selectedWork}
      />
    </section>
  );
}

/** Chronological ledger of what really moved between Sol and the planets:
 * public messages, approvals, dispatches, context transfers and WorkItem
 * revisions, in real event order. */
function FocusFlowLedger({
  flow,
  partners,
  rootId,
}: {
  flow: RoomFocusPacket[];
  partners: RoomFocusPartner[];
  rootId: string;
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

function FocusInspector({
  onOpenParticipant,
  partner,
  work,
}: {
  onOpenParticipant?: (participantId: string) => void;
  partner?: RoomFocusPartner;
  work?: RoomFocusWorkItem;
}) {
  const state = work?.state ?? partner?.state ?? 'idle';
  const action = workAction(work) || partner?.currentAction || '等待新的工作项';
  const evidence = work?.evidence ?? [];
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

function roomFocusHandoffStateLabel(state: RoomFocusProjection['handoffs'][number]['state']): string {
  return ({
    offered: '待接收',
    dispatched: '已分派',
    completed: '已交付',
    failed: '需要关注',
    stopped: '已停止',
  } as const)[state];
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
