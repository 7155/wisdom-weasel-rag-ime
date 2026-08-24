import {
  ArrowRight,
  ExternalLink,
  FileCheck2,
  GitCommitHorizontal,
  Orbit,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  roomFocusReadableText,
  roomFocusStateFallbackCopy,
  roomFocusStateLabel,
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

      {/* 工作区顶部的信号条已经常驻同一组计数；面板内不再重复一份
          （截图问题 3/5：叠层与状态噪音收敛）。 */}
      {!hideMission ? <dl aria-label="协作摘要" className="paw-room-focus-overview__counts">
        <div data-tone="active"><dt>进行</dt><dd>{focus.counts.active}</dd></div>
        <div data-tone="review"><dt>复核</dt><dd>{focus.counts.review}</dd></div>
        <div data-tone="blocked"><dt>受阻</dt><dd>{focus.counts.blocked}</dd></div>
        <div data-tone="completed"><dt>完成</dt><dd>{focus.counts.completed}</dd></div>
      </dl> : null}

      <section aria-labelledby="paw-room-focus-work-title" className="paw-room-focus-overview__section paw-room-focus-overview__work">
        <header>
          <span><GitCommitHorizontal aria-hidden="true" size={14} /><strong id="paw-room-focus-work-title">任务拆解</strong></span>
          <small>{focus.workItems.length} 项</small>
        </header>
        {focus.workItems.length ? (
          <ol aria-label="任务拆解" className="paw-room-focus-overview__tree" role="tree">
            {focus.workItems.map((item) => {
              const partner = focus.partners.find((candidate) => candidate.participantId === item.ownerParticipantId);
              const level = item.parentId ? 2 : 1;
              const selected = selection.kind === 'work' && selection.id === item.id;
              /* 行内摘要位只放能读的话：原始工具日志换成状态兜底语，完整
                 记录仍在伙伴窗口的披露里。空段不参与拼接，避免行首悬点。 */
              const action = [workAction(item), partner?.celestialName].filter(Boolean).join(' · ');
              return (
                <li aria-level={level} aria-selected={selected} data-level={level} data-state={item.state} key={item.id} role="treeitem">
                  <button onClick={() => setSelection({ kind: 'work', id: item.id })} title={item.objective} type="button">
                    <span aria-hidden="true" className="paw-room-focus-overview__tree-node"><i /></span>
                    <span className="paw-room-focus-overview__tree-copy">
                      <strong>{item.objective}</strong>
                      {action ? <small>{action}</small> : null}
                    </span>
                    <span className="paw-room-focus-overview__state"><i aria-hidden="true" />{roomFocusStateLabel(item.state)}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        ) : <p className="paw-room-focus-overview__empty">还没有拆出任务。把目标发到对话里，分工会实时出现在这里。</p>}
      </section>

      <section aria-labelledby="paw-room-focus-partners-title" className="paw-room-focus-overview__section paw-room-focus-overview__partners">
        <header>
          <span><Orbit aria-hidden="true" size={14} /><strong id="paw-room-focus-partners-title">协作伙伴</strong></span>
          <small>{focus.partners.length} 位</small>
        </header>
        {focus.partners.length ? (
          <ul aria-label="协作伙伴" className="paw-room-focus-overview__planet-list" role="list">
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
        ) : <p className="paw-room-focus-overview__empty">还没有伙伴加入。邀请伙伴后，他们的行星会出现在这里。</p>}
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
                  {handoff.createdAtMs ? <time dateTime={new Date(handoff.createdAtMs).toISOString()}>{focusClock(handoff.createdAtMs)}</time> : null}
                </li>
              );
            })}
          </ol>
        ) : <p className="paw-room-focus-overview__empty">伙伴之间还没有发生任务交接。</p>}
      </section>

      <FocusInspector
        onOpenParticipant={onOpenParticipant}
        partner={selectedPartner}
        work={selectedWork}
      />
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
  /* 详情面板同样只说人话：原始工具日志与机器串换成跟随状态的兜底语，
     完整原文留在伙伴窗口的「查看公开原文」披露里。 */
  const action = roomFocusReadableText(
    workAction(work) || partner?.currentAction || '',
    roomFocusStateFallbackCopy(state),
  );
  const receipt = partner ? roomFocusReadableText(partner.latestReceipt ?? '', '') : '';
  const result = work ? roomFocusReadableText(work.latestResult ?? '', '') : '';
  const acceptance = work?.acceptanceCriteria.filter((criterion) => criterion.trim()) ?? [];
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
          {receipt ? <div><dt>最近回执</dt><dd>{receipt}</dd></div> : null}
        </dl>
      ) : null}
      {work?.blocker ? (
        <div className="paw-room-focus-overview__blocker">
          <strong>{work.blocker.reason}</strong>
          {work.blocker.nextStep ? <span>下一步：{work.blocker.nextStep}</span> : null}
        </div>
      ) : null}
      {result ? <p className="paw-room-focus-overview__result">{result}</p> : null}
      {acceptance.length ? (
        <div className="paw-room-focus-overview__acceptance">
          <small>验收标准</small>
          <ul aria-label="验收标准">
            {acceptance.map((criterion) => <li key={criterion}>{criterion}</li>)}
          </ul>
        </div>
      ) : null}
      {evidence.length ? (
        <ul aria-label="依据与产物" className="paw-room-focus-overview__evidence">
          {evidence.map((item) => <li key={`${item.kind}:${item.ref}`}><span>{item.kind === 'artifact' ? '产物' : '依据'}</span><code>{item.ref}</code></li>)}
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

function focusClock(timestamp: number): string {
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

/** 运行时动作沿真实字段逐级回落；来自工具日志的字段先过可读性投影，
 *  读不成话的段落让位给下一级真实事实，而不是把 JSON 摆进摘要位。 */
function workAction(work?: RoomFocusWorkItem): string {
  if (!work) return '';
  const action = roomFocusReadableText(work.currentAction ?? '', '');
  if (action) return action;
  if (work.blocker?.reason) return work.blocker.reason;
  if (work.reviewRequired) return '等待独立复核';
  return roomFocusReadableText(work.latestResult || work.expectedOutput || '', '');
}
