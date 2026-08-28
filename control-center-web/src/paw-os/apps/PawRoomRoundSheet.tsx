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
  const [expandedRows, setExpandedRows] = useState<Set<string>>(() => new Set());
  const detailIdPrefix = useId();
  const desktop = usePawOsDesktop();
  const roundsRef = useRef<HTMLElement>(null);
  const previousLatestSheetId = useRef('');
  const previousResultState = useRef<Map<string, { hasResult: boolean; state: RoomRoundRowState }>>(new Map());
  const autoOpenedResults = useRef<Set<string>>(new Set());
  const latestSheetId = sheets.at(-1)?.id ?? '';

  useEffect(() => {
    if (!latestSheetId) return;
    const node = roundsRef.current;
    const behavior = previousLatestSheetId.current ? 'smooth' : 'auto';
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

  useEffect(() => {
    const next = new Map<string, { hasResult: boolean; state: RoomRoundRowState }>();
    const rowsToOpen: string[] = [];

    for (const sheet of sheets) {
      for (const row of sheet.rows) {
        const hasResult = Boolean(row.result || row.evidenceRefs.length);
        const previous = previousResultState.current.get(row.key);
        next.set(row.key, { hasResult, state: row.state });
        if (
          previous
          && row.state === 'completed'
          && hasResult
          && (previous.state !== 'completed' || !previous.hasResult)
          && !autoOpenedResults.current.has(row.key)
        ) {
          autoOpenedResults.current.add(row.key);
          rowsToOpen.push(row.key);
        }
      }
    }

    previousResultState.current = next;
    if (!rowsToOpen.length) return;
    setExpandedRows((current) => {
      const nextExpanded = new Set(current);
      rowsToOpen.forEach((key) => nextExpanded.add(key));
      return nextExpanded;
    });
  }, [sheets]);

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
        const open = sheetDisclosure[sheet.id] ?? index === sheets.length - 1;
        return (
          <article
            className="paw-room-round"
            data-round-id={sheet.id}
            data-state={sheet.status}
            key={sheet.id}
          >
            <header className="paw-room-round__header">
              <button
                aria-expanded={open}
                aria-label={open ? '折叠本轮任务' : '展开本轮任务'}
                className="paw-room-round__toggle"
                onClick={() => setSheetDisclosure((current) => ({ ...current, [sheet.id]: !open }))}
                type="button"
              >
                <span aria-hidden="true" className="paw-room-round__toggle-icon" data-open={open || undefined}>
                  <ChevronRight size={17} />
                </span>
                <span>
                  <strong>{sheet.objective}</strong>
                  <small>{sheet.rows.length} 颗行星 · {sheetStateLabels[sheet.status] ?? sheet.status}</small>
                </span>
              </button>
              <span className="paw-room-round__state" data-state={sheet.status}>
                <i aria-hidden="true" />
                {sheetStateLabels[sheet.status] ?? sheet.status}
              </span>
            </header>

            {open ? (
              <div className="paw-room-round__table-scroll">
                <table aria-label={`${sheet.objective} · 行星进展`}>
                  <thead>
                    <tr>
                      <th scope="col">行星</th>
                      <th scope="col">当前任务</th>
                      <th scope="col">阶段</th>
                      <th scope="col">最新公开进展</th>
                      <th scope="col"><span className="sr-only">操作</span></th>
                    </tr>
                  </thead>
                  {sheet.rows.map((row) => {
                    const rowOpen = expandedRows.has(row.key);
                    const detailId = `${detailIdPrefix}-${domToken(row.key)}`;
                    return (
                      <tbody data-row-key={row.key} data-state={row.state} key={row.key}>
                        <tr
                          aria-selected={selectedParticipantId === row.participantId || undefined}
                          data-planet-row={row.key}
                          data-selected={selectedParticipantId === row.participantId || undefined}
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
                          <td data-label="阶段"><span className="paw-room-round__row-state" data-state={row.state}><i aria-hidden="true" />{rowStateLabels[row.state]}</span></td>
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
                                    aria-label={`${resumeErrorByRow?.[row.key] ? '重试' : '恢复'} ${row.celestialName} 并重新分派`}
                                    disabled={resumingWorkItemId === row.blockedWorkItemId}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      void onResumeBlocked(row);
                                    }}
                                    type="button"
                                  >
                                    {resumingWorkItemId === row.blockedWorkItemId ? '恢复中' : resumeErrorByRow?.[row.key] ? '重试恢复' : '恢复'}
                                  </button>
                                  {resumeErrorByRow?.[row.key] ? <span className="paw-room-round__resume-error" role="alert">{resumeErrorByRow[row.key]}</span> : null}
                                </>
                              ) : null}
                              <button
                                aria-controls={detailId}
                                aria-expanded={rowOpen}
                                aria-label={`${rowOpen ? '收起' : '展开'} ${row.celestialName} 详情`}
                                onClick={() => setExpandedRows((current) => toggled(current, row.key))}
                                type="button"
                              >
                                {rowOpen ? <ChevronDown aria-hidden="true" size={15} /> : <ChevronRight aria-hidden="true" size={15} />}
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
                        {rowOpen ? (
                          <tr className="paw-room-round__detail-row">
                            <td colSpan={5}>
                              <div
                                aria-label={`${row.celestialName} 公开进展与证据`}
                                aria-live={row.state === 'completed' ? 'polite' : undefined}
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
                                      {resumeErrorByRow?.[row.key] ? <small className="paw-room-round__resume-error" role="alert">恢复失败：{resumeErrorByRow[row.key]}</small> : null}
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
                  })}
                </table>
              </div>
            ) : null}
          </article>
        );
      })}
    </section>
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
  target,
}: {
  desktop: ReturnType<typeof usePawOsDesktop>;
  target: EvidenceEchoEntity;
}) {
  return (
    <button
      aria-label={`打开文件 ${target.label}`}
      className="paw-room-round__file-reference"
      onClick={() => openEvidenceEchoEntity(desktop, target)}
      title={target.entityId}
      type="button"
    >
      <FileText aria-hidden="true" size={13} />
      <span>{target.label}</span>
    </button>
  );
}
