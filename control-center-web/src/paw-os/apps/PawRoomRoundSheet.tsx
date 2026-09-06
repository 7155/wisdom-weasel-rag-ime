import { ChevronDown, ChevronRight, ExternalLink, FileText, Orbit } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { RoomProjectionState } from '@/contracts/room-reducer';
import {
  openEvidenceEchoEntity,
  type EvidenceEchoEntity,
} from '@/features/evidence-echo/evidence-echo';
import { MarkdownBody } from '@/features/agent/timeline/MarkdownRenderer';
import { usePawOsDesktop } from '@/features/paw-os/surface-context';
import type { RoomSummary } from '@/features/rooms/room-types';
import {
  progressFallback,
  selectRoomRoundTaskSheets,
  type RoomRoundTaskRow,
  type RoomRoundRowState,
} from './room-round-task-sheet';
import './paw-room-round-sheet.css';

const rowStateLabels: Record<RoomRoundRowState, string> = {
  queued: '待开始',
  waiting: '等待中',
  running: '进行中',
  blocked: '已阻塞',
  completed: '已完成',
  failed: '需要关注',
  aborted: '已停止',
};

const sheetStateLabels: Record<string, string> = {
  queued: '待开始',
  running: '协作中',
  completed: '已完成',
  failed: '需要处理',
  aborted: '已停止',
};

export function PawRoomRoundSheet({
  onOpenParticipant,
  onResumeBlocked,
  projection,
  resumeErrorByRow,
  resumingWorkItemId,
  room,
  selectedParticipantId,
}: {
  onOpenParticipant: (participantId: string) => void;
  /** Optional so compact surfaces keep their composer-less behavior. */
  onResumeBlocked?: (row: RoomRoundTaskRow) => void | Promise<void>;
  projection: RoomProjectionState;
  resumeErrorByRow?: Record<string, string | undefined>;
  resumingWorkItemId?: string;
  room: RoomSummary;
  selectedParticipantId?: string;
}) {
  const sheets = useMemo(
    () => selectRoomRoundTaskSheets(room, projection),
    [projection, room],
  );
  const [sheetDisclosure, setSheetDisclosure] = useState<Record<string, boolean>>({});
  const [historicalDisclosure, setHistoricalDisclosure] = useState<Record<string, boolean>>({});
  const [expandedRows, setExpandedRows] = useState<Set<string>>(() => new Set());
  const detailIdPrefix = useId();
  const desktop = usePawOsDesktop();
  const roundsRef = useRef<HTMLElement>(null);
  const previousLatestSheetId = useRef('');
  const latestSheetId = sheets.at(-1)?.id ?? '';

  useEffect(() => {
    if (!latestSheetId) return;
    const node = roundsRef.current;
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      || document.documentElement.dataset.reduceMotion === 'true';
    const behavior = previousLatestSheetId.current && !reducedMotion ? 'smooth' : 'auto';
    previousLatestSheetId.current = latestSheetId;
    if (!node) return;
    const frame = requestAnimationFrame(() => {
      if (typeof node.scrollTo === 'function') {
        node.scrollTo({ top: node.scrollHeight, behavior });
      } else {
        node.scrollTop = node.scrollHeight;
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [latestSheetId]);

  if (!sheets.length) {
    return (
      <section aria-label="Room 行星任务表" className="paw-room-rounds paw-room-rounds--empty">
        <Orbit aria-hidden="true" size={24} />
        <strong>等待第一轮任务</strong>
        <p>发送目标后，每颗行星会在同一张表里更新任务、阶段与公开进展。</p>
      </section>
    );
  }

  return (
    <section aria-label="Room 行星任务表" className="paw-room-rounds" ref={roundsRef}>
      {sheets.map((sheet, index) => {
        const latest = index === sheets.length - 1;
        const settled = ['completed', 'failed', 'aborted'].includes(sheet.status);
        const allRowsSettled = sheet.rows.filter((row) => row.assigned).every((row) => (
          ['completed', 'failed', 'aborted'].includes(row.state)
        ));
        const hasLiveActivity = projection.turnsById[sheet.turnId]?.activityIds.some((id) => (
          ['running', 'waiting'].includes(projection.activitiesById[id]?.status ?? '')
        ));
        const resultRows = sheet.rows.filter((row) => isStandaloneResult(row, room));
        const finalRows = resultRows.filter((row) => isCoordinatorRow(row, room));
        const partnerResults = resultRows.filter((row) => !isCoordinatorRow(row, room));
        const workerAssignmentExists = sheet.rows.some((row) => (
          !isCoordinatorRow(row, room)
          && (row.assigned || resultRows.includes(row))
        ));
        /* The moderator/coordinator owns the user-facing synthesis. It is a
           Room-level answer, not one more parallel work item, so keep it out
           of the worker table even when several planets are executing. An
           explicit progress/wait post is also a coordinator report when it is
           the only visible lane; activity-only rows retain the existing
           standalone task presentation. */
        const coordinatorRows = sheet.rows.filter((row) => (
          !resultRows.includes(row)
          && isCoordinatorSummaryRow(row, room)
          && (workerAssignmentExists || Boolean(row.postKind || row.report))
        ));
        /* Disclosure is a reading preference, never a completion signal. An
           aborted round can contain a useful host report; show that report
           in full while keeping its authoritative stopped state visible. */
        const hasReadableReport = coordinatorRows.length > 0 || resultRows.length > 0;
        const open = sheetDisclosure[sheet.id] ?? (
          !(settled && hasReadableReport && allRowsSettled && !hasLiveActivity)
        );
        const taskRows = sheet.rows.filter((row) => (
          row.assigned
          && !resultRows.includes(row)
          && !coordinatorRows.includes(row)
          /* Once a worker assignment exists, the moderator is a Room-level
             synthesis lane. Never let a sparse/stale coordinator row fall
             back into the worker table just because its turn listed it as a
             participant. */
          && !(workerAssignmentExists && isCoordinatorRow(row, room))
        ));
        const starterRows = taskRows.length || resultRows.length || coordinatorRows.length
          ? []
          : sheet.rows.filter((row) => !row.assigned && !coordinatorRows.includes(row));
        const standaloneTaskRow = taskRows.length === 1 ? taskRows[0] : undefined;
        const multiParticipantRows = taskRows.length > 1 ? taskRows : [];
        const countedResultRows = workerAssignmentExists
          ? resultRows.filter((row) => !isCoordinatorRow(row, room))
          : resultRows;
        const planetCount = taskRows.length + countedResultRows.length
          + (workerAssignmentExists ? 0 : coordinatorRows.length) || starterRows.length;
        const roundOpen = latest || Boolean(historicalDisclosure[sheet.id]);
        const replyId = `${detailIdPrefix}-${domToken(sheet.id)}-reply`;
        const processId = `${detailIdPrefix}-${domToken(sheet.id)}-process`;
        const hasProcess = taskRows.length > 0 || starterRows.length > 0;
        const toggleProcess = () => setSheetDisclosure((current) => ({
          ...current,
          [sheet.id]: !open,
        }));
        const prompt = <span>
          <strong>{sheet.objective}</strong>
          <small>{planetCount} 颗行星 · {sheetStateLabels[sheet.status] ?? sheet.status}</small>
        </span>;

        return (
          <article
            className="paw-room-session-round paw-room-session-round--collaboration"
            data-round-id={sheet.id}
            data-state={sheet.status}
            key={sheet.id}
          >
            <header className="paw-room-session-round__prompt">
              {latest ? <div className="paw-room-session-round__objective">{prompt}</div> : <button
                aria-controls={replyId}
                aria-expanded={roundOpen}
                aria-label={roundOpen ? '折叠本轮任务' : '展开本轮任务'}
                onClick={() => setHistoricalDisclosure((current) => ({ ...current, [sheet.id]: !roundOpen }))}
                type="button"
              >
                {prompt}
                <ChevronDown aria-hidden="true" className="paw-room-session-round__chevron" data-open={roundOpen || undefined} size={15} />
              </button>}
            </header>
            <div className="paw-room-session-round__reply" hidden={!roundOpen} id={replyId}>
              {roundOpen && hasProcess ? (
                <section className={multiParticipantRows.length ? 'paw-room-round' : 'paw-room-round-process'} data-state={sheet.status}>
                  <header className="paw-room-round__header">
                    <button
                      aria-controls={processId}
                      aria-expanded={open}
                      aria-label={open ? '收起协作过程' : '查看协作过程'}
                      className="paw-room-round__toggle"
                      onClick={toggleProcess}
                      type="button"
                    >
                      <span aria-hidden="true" className="paw-room-round__toggle-icon" data-open={open || undefined}>
                        <ChevronRight size={17} />
                      </span>
                      <span><strong>协作过程</strong><small>{[...taskRows, ...starterRows].map((row) => row.celestialName).join(' · ')}</small></span>
                    </button>
                    <span className="paw-room-round__state" data-state={sheet.status}>
                      <i aria-hidden="true" />{sheetStateLabels[sheet.status] ?? sheet.status}
                    </span>
                  </header>
                  <div hidden={!open} id={processId}>
                    {open && multiParticipantRows.length ? (
                      <div className="paw-room-round__table-scroll">
                        <table aria-label={`${sheet.objective} · 行星进展`}>
                          <thead><tr>
                            <th scope="col">伙伴</th><th scope="col">分工</th>
                            <th scope="col">状态</th><th scope="col">进展与交接</th>
                            <th scope="col"><span className="sr-only">操作</span></th>
                          </tr></thead>
                          {multiParticipantRows.map((row) => (
                            <TaskPlanetRows
                              desktop={desktop}
                              detailId={`${detailIdPrefix}-${domToken(row.key)}`}
                              expanded={expandedRows.has(row.key)}
                              key={row.key}
                              onOpenParticipant={onOpenParticipant}
                              onResumeBlocked={onResumeBlocked}
                              onToggle={() => setExpandedRows((current) => toggled(current, row.key))}
                              resumingWorkItemId={resumingWorkItemId}
                              resumeError={resumeErrorByRow?.[row.key]}
                              room={room}
                              row={row}
                              selected={selectedParticipantId === row.participantId}
                            />
                          ))}
                        </table>
                      </div>
                    ) : null}
                    {open ? <>
                      {starterRows.map((row) => (
                        <StandaloneStarterPlanet key={row.key} onOpenParticipant={onOpenParticipant} row={row} selected={selectedParticipantId === row.participantId} />
                      ))}
                      {standaloneTaskRow ? (
                        <StandaloneTaskPlanet
                          desktop={desktop}
                          detailId={`${detailIdPrefix}-${domToken(standaloneTaskRow.key)}`}
                          expanded={expandedRows.has(standaloneTaskRow.key)}
                          onOpenParticipant={onOpenParticipant}
                          onResumeBlocked={onResumeBlocked}
                          onToggle={() => setExpandedRows((current) => toggled(current, standaloneTaskRow.key))}
                          resumingWorkItemId={resumingWorkItemId}
                          resumeError={resumeErrorByRow?.[standaloneTaskRow.key]}
                          room={room}
                          row={standaloneTaskRow}
                          selected={selectedParticipantId === standaloneTaskRow.participantId}
                        />
                      ) : null}
                    </> : null}
                  </div>
                </section>
              ) : null}
              {roundOpen ? <>
                {coordinatorRows.map((row) => (
                  <StandaloneCoordinatorSummary desktop={desktop} key={row.key} onOpenParticipant={onOpenParticipant} room={room} row={row} selected={selectedParticipantId === row.participantId} />
                ))}
                {finalRows.map((row) => (
                  <StandaloneResultPlanet desktop={desktop} key={row.key} onOpenParticipant={onOpenParticipant} room={room} row={row} selected={selectedParticipantId === row.participantId} />
                ))}
                {partnerResults.length ? (
                  <section aria-label="伙伴交付" className="paw-room-round__partner-results">
                    <header><h3>伙伴交付</h3><span>{partnerResults.length} 份结果</span></header>
                    {partnerResults.map((row) => (
                      <PartnerResult desktop={desktop} key={row.key} onOpenParticipant={onOpenParticipant} room={room} row={row} selected={selectedParticipantId === row.participantId} />
                    ))}
                  </section>
                ) : null}
              </> : null}
            </div>
          </article>
        );
      })}
    </section>
  );
}

function TaskPlanetRows({
  desktop,
  detailId,
  expanded,
  onOpenParticipant,
  onResumeBlocked,
  onToggle,
  resumingWorkItemId,
  resumeError,
  room,
  row,
  selected,
}: {
  desktop: ReturnType<typeof usePawOsDesktop>;
  detailId: string;
  expanded: boolean;
  onOpenParticipant: (participantId: string) => void;
  onResumeBlocked?: (row: RoomRoundTaskRow) => void | Promise<void>;
  onToggle: () => void;
  resumingWorkItemId?: string;
  resumeError?: string;
  room: RoomSummary;
  row: RoomRoundTaskRow;
  selected: boolean;
}) {
  return (
    <tbody data-expanded={expanded || undefined} data-row-key={row.key} data-state={row.state}>
      <tr
        aria-selected={selected || undefined}
        data-planet-row={row.key}
        data-selected={selected || undefined}
        data-state={row.state}
        data-flowing-light={row.state === 'running' || undefined}
        onClick={(event) => {
          const target = event.target;
          if (target instanceof Element && target.closest('button, a, input, select, textarea, summary')) return;
          onOpenParticipant(row.participantId);
        }}
      >
        <th scope="row">
          <button
            aria-label={`打开 ${row.celestialName} Session`}
            className="paw-room-round__planet"
            onClick={() => onOpenParticipant(row.participantId)}
            type="button"
          >
            <span aria-hidden="true"><Orbit size={15} /></span>
            <span><strong>{row.celestialName}</strong><small>{row.role}</small></span>
          </button>
        </th>
        <td data-label="当前任务">
          <MarkdownBody
            documentKey={`${row.key}:task`}
            sessionId={row.sessionId}
            text={row.task}
          />
        </td>
        <td data-label="阶段">
          <span className="paw-room-round__row-state" data-state={row.state}>
            <i aria-hidden="true" />{rowStateLabels[row.state]}
          </span>
        </td>
        <td data-label="最新公开进展">
          <div
            className="paw-room-round__progress-text"
            data-live={row.state === 'running' || undefined}
            data-state={row.state}
            key={`${row.key}:${row.updatedAtMs}`}
          >
            <MarkdownBody
              documentKey={`${row.key}:progress:${row.updatedAtMs}`}
              sessionId={row.sessionId}
              text={row.latestProgress}
            />
          </div>
        </td>
        <td data-label="操作">
          <div className="paw-room-round__actions">
            {row.state === 'blocked' && row.blockedWorkItemId && onResumeBlocked ? (
              <>
                <button
                  aria-label={`${resumeError ? '重试' : '恢复'} ${row.celestialName} 并重新分派`}
                  disabled={resumingWorkItemId === row.blockedWorkItemId}
                  onClick={(event) => {
                    event.stopPropagation();
                    void onResumeBlocked(row);
                  }}
                  type="button"
                >
                  {resumingWorkItemId === row.blockedWorkItemId ? '恢复中' : resumeError ? '重试恢复' : '恢复'}
                </button>
                {resumeError ? <span className="paw-room-round__resume-error" role="alert">{resumeError}</span> : null}
              </>
            ) : null}
            <button
              aria-controls={detailId}
              aria-expanded={expanded}
              aria-label={`${expanded ? '收起' : '展开'} ${row.celestialName} 详情`}
              onClick={onToggle}
              type="button"
            >
              {expanded ? <ChevronDown aria-hidden="true" size={15} /> : <ChevronRight aria-hidden="true" size={15} />}
            </button>
            <button
              aria-label={`打开 ${row.celestialName} Session 窗口`}
              onClick={() => onOpenParticipant(row.participantId)}
              type="button"
            >
              <ExternalLink aria-hidden="true" size={14} />
            </button>
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr className="paw-room-round__detail-row">
          <td colSpan={5}>
            <div
              aria-label={`${row.celestialName} 公开进展与证据`}
              className="paw-room-round__detail"
              data-result-ready={row.state === 'completed' && (row.result || row.evidenceRefs.length) ? true : undefined}
              id={detailId}
              role="region"
              tabIndex={0}
            >
              <section>
                <strong>公开进展</strong>
                {row.history.length ? (
                  <ol>
                    {row.history.map((event) => (
                      <li data-state={event.status} key={event.id}>
                        <i aria-hidden="true" />
                        <MarkdownBody
                          documentKey={`${row.key}:history:${event.id}`}
                          sessionId={row.sessionId}
                          text={event.summary}
                        />
                      </li>
                    ))}
                  </ol>
                ) : <p>尚无可公开的运行事件。</p>}
              </section>
              <section>
                <strong>结果与证据</strong>
                {row.blockerReason ? (
                  <div className="paw-room-round__blocker" role="status">
                    <strong>阻塞原因</strong>
                    <MarkdownBody
                      documentKey={`${row.key}:blocker:reason`}
                      sessionId={row.sessionId}
                      text={row.blockerReason}
                    />
                    {row.blockerNextStep ? (
                      <small>
                        建议下一步：
                        <MarkdownBody
                          documentKey={`${row.key}:blocker:next-step`}
                          sessionId={row.sessionId}
                          text={row.blockerNextStep}
                        />
                      </small>
                    ) : null}
                    {resumeError ? <small className="paw-room-round__resume-error" role="alert">恢复失败：{resumeError}</small> : null}
                  </div>
                ) : null}
                {row.result ? (
                  <div className="paw-room-round__result">
                    <MarkdownBody
                      documentKey={`${row.key}:result`}
                      sessionId={row.sessionId}
                      text={row.result}
                    />
                  </div>
                ) : <p>结果尚未返回；打开行星 Session 可查看完整公开过程。</p>}
                {row.evidenceRefs.length ? (
                  <ul>
                    {row.evidenceRefs.map((ref) => {
                      const file = workspaceFileTarget(ref, row, room.artifacts);
                      return (
                        <li key={ref}>
                          {file ? <FileReferenceAction desktop={desktop} target={file} /> : <span>{ref}</span>}
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
                <button onClick={() => onOpenParticipant(row.participantId)} type="button">
                  打开行星 Session 查看完整过程 <ExternalLink aria-hidden="true" size={13} />
                </button>
              </section>
            </div>
          </td>
        </tr>
      ) : null}
    </tbody>
  );
}

function isStandaloneResult(row: RoomRoundTaskRow, room: RoomSummary): boolean {
  if (row.state !== 'completed') return false;
  /* A coordinator's WorkItem result or untyped assistant message is evidence,
     not the Room's final report. Only the persisted moderator's typed result
     post can open the standalone final card. Worker result/evidence cards keep
     their existing projection rules. */
  if (isCoordinatorRow(row, room)) {
    return row.postKind === 'result' && Boolean(row.result);
  }
  return Boolean(row.result || row.evidenceRefs.length);
}


function isCoordinatorSummaryRow(row: RoomRoundTaskRow, room: RoomSummary): boolean {
  /* moderatorParticipantId is the persisted authority; mutable role labels
     never confer final-report ownership. */
  const isCoordinator = isCoordinatorRow(row, room);
  /* An idle coordinator still belongs to the roster and must keep the
     unassigned Grill Me surface. Only move it to the synthesis card after
     this round has an explicit assignment, public progress, or a result. */
  const progressIsPublic = Boolean(row.latestProgress)
    && row.latestProgress !== progressFallback(row.state);
  const taskIsPublic = Boolean(row.task)
    && !row.task.endsWith('· 等待本轮分工');
  /* A routing receipt can populate history without being a user-facing
     synthesis. Do not promote that bookkeeping-only row into a report card;
     require an actual result, public progress, or an explicit assignment. */
  return isCoordinator && (
    Boolean(row.result || row.report)
    || progressIsPublic
    || (row.assigned && taskIsPublic)
  );
}

function isCoordinatorRow(row: RoomRoundTaskRow, room: RoomSummary): boolean {
  return row.participantId === room.moderatorParticipantId;
}

function StandaloneCoordinatorSummary({
  desktop,
  onOpenParticipant,
  room,
  row,
  selected,
}: {
  desktop: ReturnType<typeof usePawOsDesktop>;
  onOpenParticipant: (participantId: string) => void;
  room: RoomSummary;
  row: RoomRoundTaskRow;
  selected: boolean;
}) {
  const summary = row.report || row.result || row.latestProgress || row.task;
  return (
    <section
      aria-label={`${row.celestialName} 主控汇报`}
      className="paw-room-round__report"
      data-coordinator="true"
      data-row-key={row.key}
      data-selected={selected || undefined}
      data-state={row.state}
      role="region"
    >
      <ReportHeading onOpenParticipant={onOpenParticipant} row={row} title="主控汇报" />
      <div className="paw-room-round__prose">
        <MarkdownBody documentKey={`${row.key}:summary:${row.updatedAtMs}`} sessionId={row.sessionId} text={summary} />
      </div>
      <ResultReferences desktop={desktop} room={room} row={row} />
    </section>
  );
}

function StandaloneTaskPlanet({
  desktop,
  detailId,
  expanded,
  onOpenParticipant,
  onResumeBlocked,
  onToggle,
  resumingWorkItemId,
  resumeError,
  room,
  row,
  selected,
}: {
  desktop: ReturnType<typeof usePawOsDesktop>;
  detailId: string;
  expanded: boolean;
  onOpenParticipant: (participantId: string) => void;
  onResumeBlocked?: (row: RoomRoundTaskRow) => void | Promise<void>;
  onToggle: () => void;
  resumingWorkItemId?: string;
  resumeError?: string;
  room: RoomSummary;
  row: RoomRoundTaskRow;
  selected: boolean;
}) {
  return (
    <section
      aria-label={`${row.celestialName} 当前任务`}
      className="paw-room-round__standalone paw-room-round__standalone--task"
      data-flowing-light={row.state === 'running' || undefined}
      data-row-key={row.key}
      data-selected={selected || undefined}
      data-state={row.state}
      role="region"
    >
      <header>
        <span aria-hidden="true" className="paw-room-round__standalone-orbit"><Orbit size={18} /></span>
        <span>
          <strong>{row.celestialName}</strong>
          <small>{row.role}</small>
        </span>
        <span className="paw-room-round__row-state" data-state={row.state}>
          <i aria-hidden="true" />{rowStateLabels[row.state]}
        </span>
      </header>
      <div className="paw-room-round__standalone-body paw-room-round__standalone-task-body">
        <section>
          <small>当前任务</small>
          <MarkdownBody documentKey={`${row.key}:task`} sessionId={row.sessionId} text={row.task} />
        </section>
        <section>
          <small>最新公开进展</small>
          <MarkdownBody
            documentKey={`${row.key}:progress:${row.updatedAtMs}`}
            sessionId={row.sessionId}
            text={row.latestProgress}
          />
        </section>
      </div>
      <div className="paw-room-round__standalone-actions">
        {row.state === 'blocked' && row.blockedWorkItemId && onResumeBlocked ? (
          <button
            aria-label={`${resumeError ? '重试' : '恢复'} ${row.celestialName} 并重新分派`}
            disabled={resumingWorkItemId === row.blockedWorkItemId}
            onClick={() => void onResumeBlocked(row)}
            type="button"
          >
            {resumingWorkItemId === row.blockedWorkItemId ? '恢复中' : resumeError ? '重试恢复' : '恢复'}
          </button>
        ) : null}
        <button
          aria-controls={detailId}
          aria-expanded={expanded}
          aria-label={`${expanded ? '收起' : '展开'} ${row.celestialName} 详情`}
          onClick={onToggle}
          type="button"
        >
          {expanded ? <ChevronDown aria-hidden="true" size={15} /> : <ChevronRight aria-hidden="true" size={15} />}
          {expanded ? '收起详情' : '查看详情'}
        </button>
        <button aria-label={`打开 ${row.celestialName} Session`} onClick={() => onOpenParticipant(row.participantId)} type="button">
          打开 Session <ExternalLink aria-hidden="true" size={14} />
        </button>
        {resumeError ? <span className="paw-room-round__resume-error" role="alert">{resumeError}</span> : null}
      </div>
      {expanded ? (
        <div
          aria-label={`${row.celestialName} 公开进展与证据`}
          className="paw-room-round__standalone-detail"
          id={detailId}
          role="region"
          tabIndex={0}
        >
          <section>
            <strong>公开进展</strong>
            {row.history.length ? (
              <ol>
                {row.history.map((event) => (
                  <li data-state={event.status} key={event.id}>
                    <i aria-hidden="true" />
                    <MarkdownBody documentKey={`${row.key}:history:${event.id}`} sessionId={row.sessionId} text={event.summary} />
                  </li>
                ))}
              </ol>
            ) : <p>尚无可公开的运行事件。</p>}
          </section>
          <section>
            <strong>结果与证据</strong>
            {row.blockerReason ? (
              <div className="paw-room-round__blocker" role="status">
                <strong>阻塞原因</strong>
                <MarkdownBody documentKey={`${row.key}:blocker:reason`} sessionId={row.sessionId} text={row.blockerReason} />
                {row.blockerNextStep ? <small>建议下一步：{row.blockerNextStep}</small> : null}
                {resumeError ? <small className="paw-room-round__resume-error" role="alert">恢复失败：{resumeError}</small> : null}
              </div>
            ) : null}
            {row.result ? (
              <div className="paw-room-round__result">
                <MarkdownBody documentKey={`${row.key}:result`} sessionId={row.sessionId} text={row.result} />
              </div>
            ) : <p>结果尚未返回；打开行星 Session 可查看完整公开过程。</p>}
            {row.evidenceRefs.length ? (
              <ul>
                {row.evidenceRefs.map((ref) => {
                  const file = workspaceFileTarget(ref, row, room.artifacts);
                  return <li key={ref}>{file ? <FileReferenceAction desktop={desktop} target={file} /> : <span>{ref}</span>}</li>;
                })}
              </ul>
            ) : null}
          </section>
        </div>
      ) : null}
    </section>
  );
}

function StandaloneStarterPlanet({
  onOpenParticipant,
  row,
  selected,
}: {
  onOpenParticipant: (participantId: string) => void;
  row: RoomRoundTaskRow;
  selected: boolean;
}) {
  return (
    <section
      aria-label={`${row.celestialName} 未分配`}
      className="paw-room-round__standalone paw-room-round__standalone--starter"
      data-row-key={row.key}
      data-selected={selected || undefined}
      role="region"
    >
      <header>
        <span aria-hidden="true" className="paw-room-round__standalone-orbit"><Orbit size={18} /></span>
        <span>
          <strong>{row.celestialName}</strong>
          <small>{row.role}</small>
        </span>
        <span className="paw-room-round__row-state"><i aria-hidden="true" />尚未分配</span>
      </header>
      <div className="paw-room-round__standalone-body">
        <strong>先和这颗行星说清楚要做什么</strong>
        <p>进入 Session 后可以直接对话、补充上下文，或使用 Grill Me 把目标与取舍问清楚，再决定是否发起协作。</p>
      </div>
      <button
        aria-label={`打开 ${row.celestialName} Session`}
        onClick={() => onOpenParticipant(row.participantId)}
        type="button"
      >
        打开 {row.celestialName} Session <ExternalLink aria-hidden="true" size={14} />
      </button>
    </section>
  );
}

function StandaloneResultPlanet({
  desktop,
  onOpenParticipant,
  room,
  row,
  selected,
}: {
  desktop: ReturnType<typeof usePawOsDesktop>;
  onOpenParticipant: (participantId: string) => void;
  room: RoomSummary;
  row: RoomRoundTaskRow;
  selected: boolean;
}) {
  return (
    <section
      aria-label={`${row.celestialName} 最终结果`}
      className="paw-room-round__report paw-room-round__report--final"
      data-coordinator="true"
      data-row-key={row.key}
      data-result-ready="true"
      data-selected={selected || undefined}
      role="region"
    >
      <ReportHeading final onOpenParticipant={onOpenParticipant} row={row} title="最终结果" />
      <div className="paw-room-round__prose">
        <MarkdownBody documentKey={`${row.key}:result`} sessionId={row.sessionId} text={row.result ?? ''} />
      </div>
      <ResultReferences desktop={desktop} room={room} row={row} />
    </section>
  );
}

function ReportHeading({
  final = false,
  onOpenParticipant,
  row,
  title,
}: {
  final?: boolean;
  onOpenParticipant: (participantId: string) => void;
  row: RoomRoundTaskRow;
  title: string;
}) {
  return (
    <header className="paw-room-round__report-heading">
      <div className="paw-room-round__report-title">
        <h3>{title}</h3>
        <span className="paw-room-round__row-state" data-state={row.state} role="status">
          <i aria-hidden="true" />{final ? '已提交' : row.state === 'completed' ? '已回复' : rowStateLabels[row.state]}
        </span>
      </div>
      <button
        aria-label={`打开 ${row.celestialName} Session`}
        className="paw-room-round__report-author"
        onClick={() => onOpenParticipant(row.participantId)}
        type="button"
      >
        <Orbit aria-hidden="true" size={16} />
        <strong>{row.celestialName}</strong>
        <span>查看过程</span>
        <ExternalLink aria-hidden="true" size={13} />
      </button>
    </header>
  );
}

function PartnerResult({
  desktop,
  onOpenParticipant,
  room,
  row,
  selected,
}: {
  desktop: ReturnType<typeof usePawOsDesktop>;
  onOpenParticipant: (participantId: string) => void;
  room: RoomSummary;
  row: RoomRoundTaskRow;
  selected: boolean;
}) {
  return (
    <section
      aria-label={`${row.celestialName} 伙伴结果`}
      className="paw-room-round__partner-result"
      data-row-key={row.key}
      data-result-ready="true"
      data-selected={selected || undefined}
      role="region"
    >
      <details>
        <summary>
          <ChevronRight aria-hidden="true" className="paw-room-round__partner-chevron" size={16} />
          <Orbit aria-hidden="true" size={17} />
          <span><strong>{row.celestialName}</strong><small>{row.role}</small></span>
          <span className="paw-room-round__partner-toggle">查看结果</span>
        </summary>
        <div className="paw-room-round__partner-body">
          {row.result ? (
            <div className="paw-room-round__prose">
              <MarkdownBody documentKey={`${row.key}:result`} sessionId={row.sessionId} text={row.result} />
            </div>
          ) : <p>此伙伴已提交产物与证据。</p>}
          <button
            aria-label={`打开 ${row.celestialName} Session`}
            className="paw-room-round__text-action"
            onClick={() => onOpenParticipant(row.participantId)}
            type="button"
          >
            查看 {row.celestialName} 的完整过程 <ExternalLink aria-hidden="true" size={13} />
          </button>
        </div>
      </details>
      <ResultReferences desktop={desktop} room={room} row={row} />
    </section>
  );
}

function ResultReferences({
  desktop,
  room,
  row,
}: {
  desktop: ReturnType<typeof usePawOsDesktop>;
  room: RoomSummary;
  row: RoomRoundTaskRow;
}) {
  const files = new Map<string, EvidenceEchoEntity>();
  const references: string[] = [];
  for (const ref of row.evidenceRefs) {
    const file = workspaceFileTarget(ref, row, room.artifacts);
    if (file) files.set(file.entityId, file);
    else references.push(ref);
  }
  if (!files.size && !references.length) return null;
  return (
    <div className="paw-room-round__deliverables">
      {files.size ? (
        <section aria-label={`${row.celestialName} 产物`}>
          <h4>产物</h4>
          <ul className="paw-room-round__file-list">
            {[...files.values()].map((target) => (
              <li key={target.entityId}>
                <FileReferenceAction desktop={desktop} showPath target={target} />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {references.length ? (
        <details className="paw-room-round__evidence">
          <summary><ChevronRight aria-hidden="true" size={14} />引用与证据<span>{references.length}</span></summary>
          <ul aria-label="结果证据">{references.map((ref) => <li key={ref}>{ref}</li>)}</ul>
        </details>
      ) : null}
    </div>
  );
}

function toggled(current: ReadonlySet<string>, key: string): Set<string> {
  const next = new Set(current);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

function domToken(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/gu, '-');
}

function workspaceFileTarget(
  reference: string,
  row: Pick<RoomRoundTaskRow, 'sessionId'>,
  artifacts: RoomSummary['artifacts'],
): EvidenceEchoEntity | undefined {
  const normalized = reference.trim();
  const artifact = artifacts?.find((candidate) => (
    candidate.id === normalized || candidate.id === `artifact:${normalized}`
  ));
  const path = artifact?.path.trim() || normalized;
  if (!isWorkspaceFilePath(path)) return undefined;
  return {
    appId: 'files',
    entityId: path,
    label: artifact?.displayName.trim() || fileName(path),
    sessionId: row.sessionId,
  };
}

function isWorkspaceFilePath(value: string): boolean {
  if (value.startsWith('/') && !value.startsWith('//') && !value.includes('://')) return true;
  const relative = value.replace(/^\.\//u, '');
  return Boolean(
    relative
    && !relative.includes('://')
    && !relative.split('/').some((segment) => !segment || segment === '..')
    && /^(?:[A-Za-z0-9._-]+\/)*[A-Za-z0-9._-]+\.[A-Za-z0-9_-]+$/u.test(relative),
  );
}

function fileName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) || path;
}

function FileReferenceAction({
  desktop,
  showPath = false,
  target,
}: {
  desktop: ReturnType<typeof usePawOsDesktop>;
  showPath?: boolean;
  target: EvidenceEchoEntity;
}) {
  return (
    <button
      aria-label={`打开文件 ${target.label}`}
      className="paw-room-round__file-reference"
      data-show-path={showPath || undefined}
      onClick={() => openEvidenceEchoEntity(desktop, target)}
      title={target.entityId}
      type="button"
    >
      <FileText aria-hidden="true" size={showPath ? 19 : 13} />
      <span>{showPath ? <><strong>{target.label}</strong><small>{target.entityId}</small></> : target.label}</span>
      {showPath ? <ExternalLink aria-hidden="true" size={14} /> : null}
    </button>
  );
}
