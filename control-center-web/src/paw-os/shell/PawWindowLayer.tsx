import { lazy, memo, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from 'react';
import { ChevronRight, Maximize2, Minimize2, Minus, X } from 'lucide-react';
import { Disclosure } from '@/components/primitives';
import {
  PawOsAppSurfaceProvider,
  PawOsDesktopProvider as FeatureDesktopProvider,
  type PawOsWindowRequest,
} from '@/features/paw-os/surface-context';
import { pawApp, pawAppForPath, type PawAppId } from '../runtime/app-registry';
import { usePawDesktopApi, usePawDesktopStore } from '../runtime/desktop-context';
import {
  PAW_WINDOW_MIN_HEIGHT,
  PAW_WINDOW_MIN_WIDTH,
  fitReachablePawWindowBounds,
  pawFocusWindowLayerSize,
  pawWindowArea,
  pawWindowLayerSize,
  satelliteGroup,
  type PawWindowBounds,
  type PawWindowNode,
  type PawWindowPlacement,
} from '../runtime/desktop-store';
import { PawAppProcess } from '../apps/PawApps';
import { PawAppIcon } from './PawAppIcon';
import { PawWindowChromeProvider } from './PawWindowChrome';
import { pulsePawComposition } from '../runtime/composition-pulse';
import { useRoomProjectionBridge } from '@/features/rooms/state/projection-bridge';
import { roomActivityFlowKind, roomWorkReviewFlow } from '@/features/rooms/room-flow-projection';
import type { RoomProjectionState } from '@/contracts/room-reducer';

const PawRoomProjectionKeeper = lazy(() => import('./PawRoomProjectionKeeper'));

const noRoomProjections: Record<string, RoomProjectionState> = {};
const selectRoomProjections = (state: { projections: Record<string, RoomProjectionState> }) => state.projections;
const selectNoRoomProjections = () => noRoomProjections;
const noWindows: Record<string, PawWindowNode> = {};
const selectWindows = (state: { windows: Record<string, PawWindowNode> }) => state.windows;
const selectNoWindows = () => noWindows;

export function PawWindowLayer() {
  const api = usePawDesktopApi();
  const idSignature = usePawDesktopStore((state) => Object.keys(state.windows).join('\u0000'));
  const overviewOpen = usePawDesktopStore((state) => state.overviewOpen);
  const collaborationFocusGroup = usePawDesktopStore((state) => state.collaborationFocusGroup);
  /* Room projections stream — during a live turn they change many times per
   * second. The layer only reads them for flow groups (which require a
   * participant window) and the focus mode bar, so an ordinary desktop
   * subscribes to a constant instead and never re-renders on Room events.
   * The participant signature ignores bounds/title churn so a geometry
   * commit cannot flip the subscription or fan into Room live-store. */
  const participantSignature = usePawDesktopStore((state) => Object.values(state.windows)
    .filter((node) => node.target?.kind === 'participant')
    .map((node) => node.id)
    .sort()
    .join('\u0000'));
  const wantsRoomProjections = Boolean(collaborationFocusGroup?.startsWith('room:'))
    || Boolean(participantSignature);
  const projections = useRoomProjectionBridge(wantsRoomProjections ? selectRoomProjections : selectNoRoomProjections);
  /* Live window geometry is the layer's most expensive input: the whole
   * windows record changes identity on every bounds commit, focus change and
   * runtime title bind. Only collaboration focus frames and Room flow paths
   * actually read bounds, so an ordinary desktop subscribes to a frozen empty
   * record and the layer stops re-rendering — and stops re-deriving focus
   * frames, flow groups and the rail — every time one window moves. Each
   * PawWindow still owns its own node subscription, so the window that moved
   * is the only thing React touches. */
  const wantsWindowGeometry = Boolean(collaborationFocusGroup) || Boolean(participantSignature);
  const windows = usePawDesktopStore(wantsWindowGeometry ? selectWindows : selectNoWindows);
  const ids = useMemo(() => idSignature.split('\u0000').filter(Boolean), [idSignature]);
  /* Focus and overview frames are laid out in window-layer coordinates. Both
   * planes use the full menu-below viewport; the resident Dock is an overlay
   * instead of reserving a permanent gutter. */
  const [viewport, setViewport] = useState(() => collaborationFocusGroup ? pawFocusWindowLayerSize() : pawWindowLayerSize());
  const [focusFrameOverrides, setFocusFrameOverrides] = useState<Record<string, PawWindowBounds>>({});
  const [flowLedgerOpen, setFlowLedgerOpen] = useState(false);
  /* Keepalive identity is answered inside the subscription so the layer sees a
   * stable string: geometry churn cannot re-render it, and only an actual
   * Room window open/close/minimize produces a new value. */
  const keptRoomSignature = usePawDesktopStore(
    (state) => roomProjectionKeepaliveIds(state.windows, overviewOpen).join('\u0000'),
  );
  const keptRoomIds = useMemo(() => keptRoomSignature.split('\u0000').filter(Boolean), [keptRoomSignature]);
  const focusedRoomId = collaborationFocusGroup?.startsWith('room:') ? collaborationFocusGroup.slice('room:'.length) : '';
  const focusReservation = useMemo(() => focusedRoomId
    ? { modeBarHeight: 46, ledgerHeight: 0 }
    : {}, [focusedRoomId]);
  useEffect(() => {
    setFlowLedgerOpen(false);
  }, [focusedRoomId]);
  const computedFocusFrames = useMemo(() => collaborationFocusGroup
    ? layoutCollaborationFocus(
        Object.values(windows).filter((node) => windowBelongsToFocus(node, collaborationFocusGroup)),
        viewport,
        focusReservation,
      )
    : new Map<string, PawWindowBounds>(), [collaborationFocusGroup, focusReservation, viewport, windows]);
  const focusFrames = useMemo(() => normalizeCollaborationFocusFrames(
    computedFocusFrames,
    focusFrameOverrides,
    viewport,
    focusReservation,
    Boolean(focusedRoomId),
  ), [computedFocusFrames, focusFrameOverrides, focusReservation, focusedRoomId, viewport]);
  const focusedRoomNodes = useMemo(() => focusedRoomId
    ? Object.values(windows).filter((node) => windowBelongsToFocus(node, `room:${focusedRoomId}`))
    : [], [focusedRoomId, windows]);
  const focusedRoomSatellites = useMemo(() => focusedRoomNodes.filter(isCollaborationSatellite), [focusedRoomNodes]);
  /* In a Room focus, participant targets are the complete planet Sessions.
     They are deliberately not `isCollaborationSatellite` (that name belongs
     only to a subagent), but a narrow perimeter still needs to move them into
     the same scrollable rail when the canvas cannot fit them. */
  const focusedRoomPlanets = useMemo(
    () => focusedRoomNodes.filter((node) => node.target?.kind === 'participant'),
    [focusedRoomNodes],
  );
  const focusedRoomMain = focusedRoomNodes.find((node) => node.target?.kind === 'room' && !node.target.panel);
  const focusedRoomProjection = focusedRoomId ? projections[focusedRoomId] : undefined;
  const focusedRoomStatus = roomFocusStatus(focusedRoomProjection);
  const focusedRoomPlanetCount = focusedRoomNodes.filter((node) => node.target?.kind === 'participant').length;
  const flowWindows = useMemo(() => Object.fromEntries(Object.entries(windows).map(([id, node]) => [
    id,
    focusFrames.has(id) ? { ...node, bounds: focusFrames.get(id)! } : node,
  ])), [focusFrames, windows]);
  const flowGroups = useMemo(() => roomWindowFlowGroups(flowWindows, projections), [flowWindows, projections]);
  const flowPulse = useWindowFlowPulse(flowGroups);
  const roomFocusRail = useMemo(
    () => roomFocusRailMetrics(
      focusedRoomPlanets.length ? focusedRoomPlanets : focusedRoomSatellites,
      focusFrames,
      viewport,
      { modeBarHeight: 46, ledgerHeight: 0 },
    ),
    [focusFrames, focusedRoomPlanets, focusedRoomSatellites, viewport],
  );
  const roomFocusRailIds = useMemo(() => new Set(roomFocusRail?.satelliteIds ?? []), [roomFocusRail]);
  useEffect(() => {
    setFocusFrameOverrides({});
  }, [collaborationFocusGroup, viewport.height, viewport.width]);
  /* A viewport drag emits resize events far faster than the frame rate, and
   * each one used to refit every window and replace the viewport object. Both
   * now happen at most once per frame, and an unchanged desktop size keeps its
   * existing object so the focus/overview layouts do not recompute at all. */
  useEffect(() => {
    let frame = 0;
    const apply = () => {
      frame = 0;
      setViewport((current) => {
        const next = collaborationFocusGroup ? pawFocusWindowLayerSize() : pawWindowLayerSize();
        return current.width === next.width && current.height === next.height ? current : next;
      });
      api.getState().fitWindowsToViewport();
    };
    apply();
    const update = () => {
      if (!frame) frame = window.requestAnimationFrame(apply);
    };
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [api, collaborationFocusGroup]);
  const overviewFrames = useMemo(() => {
    if (!overviewOpen) return new Map<string, OverviewFrame>();
    const state = api.getState();
    return layoutOverview(ids.flatMap((id) => state.windows[id] ? [state.windows[id]] : []), viewport);
  }, [api, ids, overviewOpen, viewport]);
  const openFeatureWindow = useCallback((request: PawOsWindowRequest) => {
    const existingBrowser = request.target.kind === 'browser-target'
      ? Object.values(api.getState().windows).find((node) => node.appId === 'browser')
      : undefined;
    const entityId = request.target.kind === 'browser-target'
      ? existingBrowser?.entityId
      : request.target.kind === 'room' && request.target.panel
        ? `${request.target.id}:${request.target.panel}`
        : request.target.id;
    api.getState().openApp(request.appId, {
      background: request.background,
      ...(entityId ? { entityId } : {}),
      target: request.target,
      title: request.target.title,
    });
  }, [api]);
  const openFeatureApp = useCallback((appId: PawAppId, initialRoute?: string) => {
    api.getState().openApp(appId, { initialRoute });
  }, [api]);
  const openFeatureRoute = useCallback((route: string) => {
    openDesktopRoute(api, route);
  }, [api]);
  const bindRoomMain = useCallback((target: Extract<PawOsWindowRequest['target'], { kind: 'room' }>) => {
    api.getState().bindRoomMain(target);
  }, [api]);
  const setCollaborationFocusGroup = useCallback((group: string | null) => {
    api.getState().setCollaborationFocusGroup(group);
  }, [api]);
  const closeWindow = useCallback((windowId: string) => {
    api.getState().closeWindow(windowId);
  }, [api]);
  const bindAgentMain = useCallback((
    windowId: string,
    target?: Extract<PawOsWindowRequest['target'], { kind: 'session' | 'room' }>,
  ) => {
    api.getState().bindAgentMain(windowId, target);
  }, [api]);
  const commitFocusFrame = useCallback((windowId: string, bounds: PawWindowBounds) => {
    setFocusFrameOverrides((current) => ({
      ...current,
      [windowId]: clampFocusBounds(bounds, viewport, focusReservation),
    }));
  }, [focusReservation, viewport]);
  const commitFocusRailFrame = useCallback((windowId: string, bounds: PawWindowBounds) => {
    if (!roomFocusRail) return;
    const localBounds = clampRoomFocusRailBounds(bounds, roomFocusRail);
    setFocusFrameOverrides((current) => ({
      ...current,
      [windowId]: roomFocusRailGlobalFrame(localBounds, roomFocusRail.top),
    }));
  }, [roomFocusRail]);
  return (
    <FeatureDesktopProvider bindAgentMain={bindAgentMain} bindRoomMain={bindRoomMain} closeWindow={closeWindow} openApp={openFeatureApp} openRoute={openFeatureRoute} openWindow={openFeatureWindow} setCollaborationFocusGroup={setCollaborationFocusGroup}>
      <div className="paw-window-layer" data-overview={overviewOpen || undefined} data-room-focus={focusedRoomId || undefined}>
        {focusedRoomId ? <>
          <div aria-hidden="true" className="paw-room-focus-plane" />
          <header aria-label={`${focusedRoomMain?.title || focusedRoomId} Sol 协作聚焦`} className="paw-room-focus-modebar">
            <span><strong>SOL</strong><b>{focusedRoomMain?.title || '协作聚焦'}</b></span>
            <span><i data-status={focusedRoomStatus.key} />{focusedRoomStatus.label}{focusedRoomPlanetCount ? ` · ${focusedRoomPlanetCount} 颗行星` : ''}</span>
          </header>
        </> : null}
        {keptRoomIds.length ? (
          <Suspense fallback={null}>
            {keptRoomIds.map((roomId) => <PawRoomProjectionKeeper key={roomId} roomId={roomId} />)}
          </Suspense>
        ) : null}
        {!overviewOpen ? <PawRoomWindowFlowLayer focusGroup={collaborationFocusGroup} groups={flowGroups} ledgerOpen={flowLedgerOpen} onLedgerOpenChange={setFlowLedgerOpen} /> : null}
        {ids.filter((id) => !roomFocusRailIds.has(id)).map((id) => (
          <PawWindow
            collaborationFocusGroup={collaborationFocusGroup}
            flowState={flowPulse.targetWindowIds.has(id) ? 'arrival' : flowPulse.sourceWindowIds.has(id) ? 'source' : undefined}
            focusFrame={focusFrames.get(id)}
            key={id}
            onFocusFrameCommit={commitFocusFrame}
            overview={overviewOpen}
            overviewFrame={overviewFrames.get(id)}
            windowId={id}
          />
        ))}
        {roomFocusRail ? (
          <PawRoomFocusRail count={roomFocusRail.satelliteIds.length} height={roomFocusRail.height} top={roomFocusRail.top} trackWidth={roomFocusRail.trackWidth}>
            {roomFocusRail.satelliteIds.map((id) => {
              const frame = focusFrames.get(id);
              return <PawWindow
                collaborationFocusGroup={collaborationFocusGroup}
                flowState={flowPulse.targetWindowIds.has(id) ? 'arrival' : flowPulse.sourceWindowIds.has(id) ? 'source' : undefined}
                focusFrame={frame ? roomFocusRailLocalFrame(frame, roomFocusRail.top) : undefined}
                key={id}
                onFocusFrameCommit={commitFocusRailFrame}
                overview={overviewOpen}
                overviewFrame={overviewFrames.get(id)}
                windowId={id}
              />;
            })}
          </PawRoomFocusRail>
        ) : null}
      </div>
    </FeatureDesktopProvider>
  );
}

export function PawRoomFocusRail({ children, count, height, top, trackWidth }: {
  children: ReactNode;
  count: number;
  height: number;
  top: number;
  trackWidth: number;
}) {
  return (
    <section
      aria-label={`Sol 行星窗口，横向滚动查看全部 ${count} 个窗口`}
      className="paw-room-focus-satellite-rail"
      data-satellite-count={count}
      style={{ height, top }}
      tabIndex={0}
    >
      <div className="paw-room-focus-satellite-track" style={{ width: trackWidth }}>{children}</div>
    </section>
  );
}

function roomFocusRailLocalFrame(frame: PawWindowBounds, railTop: number): PawWindowBounds {
  return { ...frame, y: frame.y - railTop };
}

function roomFocusRailGlobalFrame(frame: PawWindowBounds, railTop: number): PawWindowBounds {
  return { ...frame, y: frame.y + railTop };
}

function clampRoomFocusRailBounds(bounds: PawWindowBounds, rail: RoomFocusRailMetrics): PawWindowBounds {
  const width = Math.min(Math.max(PAW_WINDOW_MIN_WIDTH, bounds.width), Math.max(PAW_WINDOW_MIN_WIDTH, rail.trackWidth));
  const height = Math.min(Math.max(PAW_WINDOW_MIN_HEIGHT, bounds.height), Math.max(PAW_WINDOW_MIN_HEIGHT, rail.height));
  return {
    x: Math.min(Math.max(0, bounds.x), Math.max(0, rail.trackWidth - width)),
    y: Math.min(Math.max(0, bounds.y), Math.max(0, rail.height - height)),
    width,
    height,
  };
}

function roomProjectionKeepaliveIds(windows: Record<string, PawWindowNode>, overviewOpen: boolean): string[] {
  const mainVisible = new Set<string>();
  const auxiliary = new Set<string>();
  for (const node of Object.values(windows)) {
    const target = node.target;
    if (target?.kind === 'participant') {
      auxiliary.add(target.roomId);
      continue;
    }
    if (target?.kind !== 'room') continue;
    if (target.panel) auxiliary.add(target.id);
    else if (!node.minimized || overviewOpen) mainVisible.add(target.id);
  }
  return [...auxiliary].filter((roomId) => !mainVisible.has(roomId));
}

function roomFocusStatus(projection?: RoomProjectionState): { key: string; label: string } {
  const turn = projection?.turnOrder
    .map((turnId) => projection.turnsById[turnId])
    .filter(Boolean)
    .at(-1);
  /* status overlay 克制：Room 名已在左侧，状态只说一个人话短语，不再重复 Sol。 */
  if (!projection) return { key: 'recovering', label: '正在恢复' };
  if (projection.needsSnapshot) return { key: 'recovering', label: '正在重新同步' };
  if (turn?.status === 'queued' || turn?.status === 'running') return { key: 'running', label: '协作进行中' };
  if (turn?.status === 'failed') return { key: 'failed', label: '最近一轮失败' };
  if (turn?.status === 'aborted') return { key: 'aborted', label: '最近一轮已停止' };
  return { key: 'synced', label: '已同步' };
}

export function PawRoomWindowFlowLayer({ focusGroup, groups, ledgerOpen = false, onLedgerOpenChange }: {
  focusGroup: string | null;
  groups: WindowFlowGroup[];
  ledgerOpen?: boolean;
  onLedgerOpenChange?: (open: boolean) => void;
}) {
  if (!groups.length) return null;
  const focusedRoomId = focusGroup?.startsWith('room:') ? focusGroup.slice('room:'.length) : '';
  const focusedGroup = groups.find((group) => group.roomId === focusedRoomId);
  return (
    <>
      {focusedGroup?.packets.length ? (
        <Disclosure
          aria-label="Room 流转记录"
          className="paw-room-window-flow-ledger"
          defaultOpen={ledgerOpen}
          key={focusedRoomId}
          onOpenChange={onLedgerOpenChange}
          summary={<><span><strong>流转记录</strong><small>{focusedGroup.packets.length} 条</small></span><ChevronRight aria-hidden="true" size={14} /></>}
        >
          {focusedGroup.packets.map((packet) => (
            <span data-kind={packet.kind} data-status={packet.status} key={packet.id} title={packet.summary}>
              <i />
              <code>{windowFlowPacketId(packet.id)}</code>
              <small>{windowFlowKindLabel(packet.kind)}</small>
              <b>{focusedGroup.actorNames?.get(packet.sourceId) || '主 Room'} → {packet.targetIds.map((id) => focusedGroup.actorNames?.get(id) || id).join('、')}</b>
              <em>{windowFlowStatusLabel(packet.status)}</em>
              <time>{windowFlowClock(packet.createdAtMs)}</time>
            </span>
          ))}
        </Disclosure>
      ) : null}
    </>
  );
}

type WindowFlowActor = 'root' | string;
type WindowFlowPoint = { x: number; y: number };
export type WindowFlowPacket = {
  id: string;
  pulseKey: string;
  sourceId: WindowFlowActor;
  targetIds: WindowFlowActor[];
  kind: 'request' | 'intercom' | 'question' | 'answer' | 'result' | 'context' | 'dispatch' | 'approval' | 'review';
  summary?: string;
  status?: string;
  workItemId?: string;
  refs?: string[];
  createdAtMs?: number;
};
export type WindowFlowGroup = {
  roomId: string;
  points: Map<WindowFlowActor, WindowFlowPoint>;
  windowIds: Map<WindowFlowActor, string>;
  actorNames?: Map<WindowFlowActor, string>;
  packets: WindowFlowPacket[];
};

export function roomWindowFlowGroups(
  windows: Record<string, PawWindowNode>,
  projections: Record<string, RoomProjectionState>,
): WindowFlowGroup[] {
  const nodes = Object.values(windows).filter((node) => !node.minimized);
  const roomIds = [...new Set(nodes.flatMap((node) => node.target?.kind === 'participant' ? [node.target.roomId] : []))];
  return roomIds.flatMap((roomId) => {
    const main = nodes.find((node) => node.appId === 'agent' && node.target?.kind === 'room' && node.target.id === roomId);
    if (!main) return [];
    const participantNodes = nodes.filter((node) => node.target?.kind === 'participant' && node.target.roomId === roomId);
    const projection = projections[roomId];
    if (!projection || !participantNodes.length) return [];
    const points = new Map<WindowFlowActor, WindowFlowPoint>([['root', windowCenter(main.bounds)]]);
    const windowIds = new Map<WindowFlowActor, string>([['root', main.id]]);
    const actorNames = new Map<WindowFlowActor, string>([['root', main.title]]);
    for (const node of participantNodes) {
      if (node.target?.kind === 'participant') {
        points.set(node.target.id, windowCenter(node.bounds));
        windowIds.set(node.target.id, node.id);
        actorNames.set(node.target.id, node.title);
      }
    }
    const packets: WindowFlowPacket[] = [];
    for (const activityId of projection.activityOrder.slice(-18)) {
      const activity = projection.activitiesById[activityId];
      if (!activity) continue;
      const kind = roomActivityFlowKind(activity);
      if (!kind) continue;
      const review = kind === 'review' ? roomWorkReviewFlow(activity) : undefined;
      const targetId = kind === 'approval'
        ? 'root'
        : kind === 'review'
          ? review?.targetParticipantId || reviewTargetParticipantId(activity.payload)
          : stringValue(activity.payload.targetParticipantId) || activity.participantId || '';
      if (!points.has(targetId)) continue;
      const sourceId = review?.sourceParticipantId
        || stringValue(activity.payload.sourceParticipantId)
        || stringValue(activity.payload.actorParticipantId)
        || (kind === 'approval' ? activity.participantId : '')
        || 'root';
      packets.push({
        id: `activity:${activity.id}`,
        pulseKey: `activity:${activity.id}:${activity.status}:${activity.updatedAtMs ?? activity.createdAtMs}`,
        sourceId: points.has(sourceId) ? sourceId : 'root',
        targetIds: [targetId],
        kind,
        summary: activity.summary,
        status: review?.status ?? activity.status,
        ...(review?.workItemId ? { workItemId: review.workItemId } : {}),
        ...(review?.refs.length ? { refs: review.refs } : {}),
        createdAtMs: activity.createdAtMs,
      });
    }
    for (const messageId of projection.messageOrder.slice(-18)) {
      const message = projection.messagesById[messageId];
      if (!message || message.projectionKind === 'execution') continue;
      if (message.role === 'assistant' && message.participantId && points.has(message.participantId)) {
        packets.push({ id: `message:${message.id}`, pulseKey: `message:${message.id}:${message.status}:${message.completedAtMs ?? message.createdAtMs}`, sourceId: message.participantId, targetIds: ['root'], kind: message.question ? 'question' : message.answerToPostId ? 'answer' : 'result', summary: message.text, status: message.status, createdAtMs: message.createdAtMs });
        continue;
      }
      const targets = (message.mentionedParticipantIds ?? []).filter((id) => points.has(id));
      if (message.role === 'user' && targets.length) packets.push({ id: `message:${message.id}`, pulseKey: `message:${message.id}:${message.status}:${message.completedAtMs ?? message.createdAtMs}`, sourceId: 'root', targetIds: targets, kind: 'request', summary: message.text, status: message.status, createdAtMs: message.createdAtMs });
    }
    return [{ roomId, points, windowIds, actorNames, packets: packets.slice(-8) }];
  });
}

export type WindowFlowPulse = {
  packetPulseKeys: ReadonlySet<string>;
  sourceWindowIds: ReadonlySet<string>;
  targetWindowIds: ReadonlySet<string>;
};

function useWindowFlowPulse(groups: WindowFlowGroup[]): WindowFlowPulse {
  const seenPulseKeys = useRef<Set<string> | null>(null);
  const [pulse, setPulse] = useState<WindowFlowPulse>(() => ({
    packetPulseKeys: new Set(),
    sourceWindowIds: new Set(),
    targetWindowIds: new Set(),
  }));
  const pulseSignature = groups.flatMap((group) => group.packets.map((packet) => packet.pulseKey)).join('\u001f');
  useEffect(() => {
    const nextKeys = new Set(groups.flatMap((group) => group.packets.map((packet) => packet.pulseKey)));
    const seen = seenPulseKeys.current;
    seenPulseKeys.current = new Set([...(seen ?? []), ...nextKeys]);
    if (!seen) return;
    const arriving = windowFlowArrivalPulse(groups, seen);
    if (!arriving.packetPulseKeys.size) return;
    setPulse(arriving);
    const timer = window.setTimeout(() => setPulse({
      packetPulseKeys: new Set(),
      sourceWindowIds: new Set(),
      targetWindowIds: new Set(),
    }), 980);
    return () => window.clearTimeout(timer);
  // The signature is the authoritative event/revision identity; geometry-only
  // window moves must not replay an information arrival.
  }, [pulseSignature]);
  return pulse;
}

export function windowFlowArrivalPulse(
  groups: WindowFlowGroup[],
  seenPulseKeys: ReadonlySet<string>,
): WindowFlowPulse {
  const packetPulseKeys = new Set(
    groups.flatMap((group) => group.packets.map((packet) => packet.pulseKey))
      .filter((key) => !seenPulseKeys.has(key)),
  );
  const sourceWindowIds = new Set<string>();
  const targetWindowIds = new Set<string>();
  for (const group of groups) {
    for (const packet of group.packets) {
      if (!packetPulseKeys.has(packet.pulseKey)) continue;
      const sourceWindowId = group.windowIds.get(packet.sourceId);
      if (sourceWindowId) sourceWindowIds.add(sourceWindowId);
      for (const targetId of packet.targetIds) {
        const targetWindowId = group.windowIds.get(targetId);
        if (targetWindowId) targetWindowIds.add(targetWindowId);
      }
    }
  }
  return { packetPulseKeys, sourceWindowIds, targetWindowIds };
}

export function isCollaborationSatellite(node: PawWindowNode): boolean {
  return !node.minimized && node.target?.kind === 'subagent';
}

export function windowBelongsToFocus(node: PawWindowNode, group: string): boolean {
  if (node.minimized) return false;
  /* A Room focus is a composition of the Room main and compact participant
     planet observers. Runtime projections (terminal/browser), documents,
     results and Room tool panels stay ordinary desktop windows; only a
     Session-created subagent is ever a satellite. */
  if (group.startsWith('room:')) {
    const roomId = group.slice('room:'.length);
    if (node.target?.kind === 'room') return node.target.id === roomId && !node.target.panel;
    return node.target?.kind === 'participant' && node.target.roomId === roomId;
  }
  if (satelliteGroup(node.target) === group) return true;
  if (group.startsWith('session:') && node.target?.kind === 'session') {
    return node.target.id === group.slice('session:'.length);
  }
  return false;
}

export function layoutCollaborationFocus(
  nodes: PawWindowNode[],
  viewport: { width: number; height: number },
  reserved: { modeBarHeight?: number; ledgerHeight?: number } = {},
): Map<string, PawWindowBounds> {
  const frames = new Map<string, PawWindowBounds>();
  if (!nodes.length) return frames;
  const roomMain = nodes.find((node) => node.target?.kind === 'room' && !node.target.panel);
  if (roomMain) return layoutRoomCollaborationFocus(nodes, roomMain, viewport, reserved);
  const inset = 10;
  const gap = 10;
  const modeBarHeight = Math.max(0, reserved.modeBarHeight ?? 0);
  /* The ledger is an absolute overlay. It never reserves focus geometry,
     whether collapsed or open. */
  const ledgerSpace = 0;
  const usableTop = modeBarHeight;
  const usableBottom = Math.max(usableTop, viewport.height - ledgerSpace);
  const usableHeight = usableBottom - usableTop;
  const main = nodes.find((node) => !isCollaborationSatellite(node)) ?? nodes[0]!;
  const satellites = nodes.filter((node) => node.id !== main.id);
  if (!satellites.length) {
    frames.set(main.id, {
      x: inset,
      y: usableTop + inset,
      width: Math.max(PAW_WINDOW_MIN_WIDTH, viewport.width - inset * 2),
      height: Math.max(PAW_WINDOW_MIN_HEIGHT, usableHeight - inset * 2),
    });
    return frames;
  }
  if (usesHorizontalFocusRail(satellites.length, viewport.width, usableHeight, inset, gap)) {
    const minimumSatelliteHeight = 220;
    const maximumMainHeight = usableHeight - inset * 2 - gap - minimumSatelliteHeight;
    const mainHeight = Math.max(320, Math.min(Math.round(usableHeight * .54), maximumMainHeight));
    frames.set(main.id, { x: inset, y: usableTop + inset, width: viewport.width - inset * 2, height: mainHeight });
    const auxiliaryTop = usableTop + inset + mainHeight + gap;
    const auxiliaryHeight = Math.max(0, usableBottom - auxiliaryTop - inset);
    const satelliteWidth = Math.min(300, Math.max(260, Math.round(viewport.width * .5)));
    const satelliteHeight = Math.max(minimumSatelliteHeight, auxiliaryHeight - 12);
    satellites.forEach((node, index) => frames.set(node.id, {
      x: inset + index * (satelliteWidth + gap),
      y: auxiliaryTop,
      width: satelliteWidth,
      height: satelliteHeight,
    }));
    return frames;
  }
  if (viewport.width < 720) {
    const mainRatio = satellites.length >= 5 ? .49 : .58;
    const mainHeight = Math.max(PAW_WINDOW_MIN_HEIGHT, Math.round(usableHeight * mainRatio));
    const mainWidth = Math.max(PAW_WINDOW_MIN_WIDTH, viewport.width - inset * 2);
    const columns = Math.min(2, satellites.length);
    const rows = Math.ceil(satellites.length / columns);
    const auxiliaryTop = usableTop + inset + mainHeight + gap;
    const auxiliaryHeight = Math.max(0, usableBottom - auxiliaryTop - inset);
    const cellWidth = (viewport.width - inset * 2 - gap * (columns - 1)) / columns;
    const cellHeight = (auxiliaryHeight - gap * (rows - 1)) / rows;
    /* Two columns are attractive until the cards stop fitting. At that point
     * keeping their CSS min-size in the grid only makes the layer clip the
     * right-hand cards; the horizontal rail below preserves every card's
     * identity and gives the user an explicit scroll affordance. */
    if (cellWidth < PAW_WINDOW_MIN_WIDTH || cellHeight < PAW_WINDOW_MIN_HEIGHT) {
      return layoutHorizontalSatelliteRail(frames, main, satellites, viewport, usableTop, usableBottom, inset, gap);
    }
    frames.set(main.id, { x: inset, y: usableTop + inset, width: mainWidth, height: mainHeight });
    satellites.forEach((node, index) => frames.set(node.id, {
      x: inset + (index % columns) * (cellWidth + gap),
      y: auxiliaryTop + Math.floor(index / columns) * (cellHeight + gap),
      width: Math.max(PAW_WINDOW_MIN_WIDTH, cellWidth),
      height: Math.max(PAW_WINDOW_MIN_HEIGHT, cellHeight),
    }));
    return frames;
  }
  if (viewport.width < 1000) {
    const railWidth = Math.min(320, Math.max(PAW_WINDOW_MIN_WIDTH, Math.round(viewport.width * .34)));
    const height = (usableHeight - inset * 2 - gap * (satellites.length - 1)) / satellites.length;
    const mainWidth = viewport.width - inset * 2 - railWidth - gap;
    if (height < PAW_WINDOW_MIN_HEIGHT || mainWidth < PAW_WINDOW_MIN_WIDTH) {
      return layoutHorizontalSatelliteRail(frames, main, satellites, viewport, usableTop, usableBottom, inset, gap);
    }
    frames.set(main.id, {
      x: inset,
      y: usableTop + inset,
      width: Math.max(PAW_WINDOW_MIN_WIDTH, mainWidth),
      height: Math.max(PAW_WINDOW_MIN_HEIGHT, usableHeight - inset * 2),
    });
    satellites.forEach((node, index) => frames.set(node.id, {
      x: viewport.width - inset - railWidth,
      y: usableTop + inset + index * (height + gap),
      width: railWidth,
      height: Math.max(PAW_WINDOW_MIN_HEIGHT, height),
    }));
    return frames;
  }
  const railWidth = Math.min(320, Math.max(PAW_WINDOW_MIN_WIDTH, Math.round(viewport.width * .21)));
  const mainX = inset + railWidth + gap;
  const mainWidth = viewport.width - inset * 2 - railWidth * 2 - gap * 2;
  frames.set(main.id, {
    x: mainX,
    y: usableTop + inset,
    width: Math.max(PAW_WINDOW_MIN_WIDTH, mainWidth),
    height: Math.max(PAW_WINDOW_MIN_HEIGHT, usableHeight - inset * 2),
  });
  const left = satellites.filter((_, index) => index % 2 === 0);
  const right = satellites.filter((_, index) => index % 2 === 1);
  const maximumSideCount = Math.max(left.length, right.length);
  const sideHeight = (usableHeight - inset * 2 - gap * (maximumSideCount - 1)) / maximumSideCount;
  if (mainWidth < PAW_WINDOW_MIN_WIDTH || sideHeight < PAW_WINDOW_MIN_HEIGHT) {
    frames.clear();
    return layoutHorizontalSatelliteRail(frames, main, satellites, viewport, usableTop, usableBottom, inset, gap);
  }
  const placeRail = (items: PawWindowNode[], x: number) => {
    if (!items.length) return;
    const height = Math.max(PAW_WINDOW_MIN_HEIGHT, (usableHeight - inset * 2 - gap * (items.length - 1)) / items.length);
    items.forEach((node, index) => frames.set(node.id, {
      x,
      y: usableTop + inset + index * (height + gap),
      width: railWidth,
      height,
    }));
  };
  placeRail(left, inset);
  placeRail(right, viewport.width - inset - railWidth);
  return frames;
}

/**
 * Room collaboration is a different composition from a Session's optional
 * subagent popup: the Room stays a reduced, complete central workspace and
 * participant windows are compact planet observers placed around it. Auxiliary
 * projections never reach this function because `windowBelongsToFocus` keeps
 * them out of the `room:<id>` group.
 */
function layoutRoomCollaborationFocus(
  nodes: PawWindowNode[],
  main: PawWindowNode,
  viewport: { width: number; height: number },
  reserved: { modeBarHeight?: number; ledgerHeight?: number },
): Map<string, PawWindowBounds> {
  const frames = new Map<string, PawWindowBounds>();
  const inset = 10;
  const gap = 12;
  const modeBarHeight = Math.max(0, reserved.modeBarHeight ?? 0);
  const usableTop = modeBarHeight + inset;
  const usableBottom = Math.max(usableTop + PAW_WINDOW_MIN_HEIGHT, viewport.height - inset);
  const usableWidth = Math.max(PAW_WINDOW_MIN_WIDTH, viewport.width - inset * 2);
  const usableHeight = Math.max(PAW_WINDOW_MIN_HEIGHT, usableBottom - usableTop);
  const planets = nodes
    .filter((node) => node.id !== main.id && node.target?.kind === 'participant')
    .slice()
    .sort((left, right) => (
      (left.target?.title ?? '').localeCompare(right.target?.title ?? '')
      || left.id.localeCompare(right.id)
    ));

  if (!planets.length) {
    const mainWidth = Math.min(
      usableWidth,
      Math.max(PAW_WINDOW_MIN_WIDTH, Math.round(usableWidth * .54)),
    );
    const mainHeight = Math.min(
      usableHeight,
      Math.max(PAW_WINDOW_MIN_HEIGHT, Math.round(usableHeight * .7)),
    );
    frames.set(main.id, {
      x: inset + Math.max(0, (usableWidth - mainWidth) / 2),
      y: usableTop + Math.max(0, (usableHeight - mainHeight) / 2),
      width: mainWidth,
      height: mainHeight,
    });
    return frames;
  }

  /* The perimeter is a real layout region, not a set of thumbnail cards. Let
     planet slots grow with the available desktop so a wide focus canvas does
     not leave a second band of unused space beside tiny fixed windows. The
     shared minimum still protects the complete Session chrome on small screens. */
  const planetWidth = Math.min(
    380,
    Math.max(PAW_WINDOW_MIN_WIDTH, Math.round(usableWidth * .18)),
  );
  const planetRows = Math.max(1, Math.ceil(planets.length / 2));
  const planetHeight = Math.max(
    PAW_WINDOW_MIN_HEIGHT,
    Math.floor((usableHeight + gap) / planetRows - gap),
  );
  const sideCapacity = Math.floor((usableHeight + gap) / (planetHeight + gap)) * 2;
  const sideReserve = planetWidth + gap;
  const sideMainWidth = usableWidth - sideReserve * 2;

  /* Two side columns are the most useful composition when the vertical space
     is tight: unlike the old bottom rail, the Room remains central and every
     participant keeps a compact observation frame. */
  if (planets.length <= sideCapacity && sideMainWidth >= PAW_WINDOW_MIN_WIDTH) {
    const left = planets.filter((_, index) => index % 2 === 0);
    const right = planets.filter((_, index) => index % 2 === 1);
    const mainHeight = usableHeight;
    const mainX = inset + sideReserve;
    frames.set(main.id, {
      x: mainX,
      y: usableTop,
      width: sideMainWidth,
      height: mainHeight,
    });
    const placeSide = (items: PawWindowNode[], x: number) => {
      if (!items.length) return;
      const totalHeight = items.length * planetHeight + (items.length - 1) * gap;
      const top = usableTop + Math.max(0, (usableHeight - totalHeight) / 2);
      items.forEach((node, index) => frames.set(node.id, {
        x,
        y: top + index * (planetHeight + gap),
        width: planetWidth,
        height: planetHeight,
      }));
    };
    placeSide(left, inset);
    placeSide(right, viewport.width - inset - planetWidth);
    return frames;
  }

  const rowCapacity = Math.max(1, Math.floor((usableWidth + gap) / (planetWidth + gap)));
  const topCount = Math.min(rowCapacity, Math.ceil(planets.length / 2));
  const bottomCount = Math.min(rowCapacity, planets.length - topCount);
  const remaining = planets.slice(topCount + bottomCount);
  const left = remaining.filter((_, index) => index % 2 === 0);
  const right = remaining.filter((_, index) => index % 2 === 1);
  const topSpace = topCount ? planetHeight + gap : 0;
  const bottomSpace = bottomCount ? planetHeight + gap : 0;
  const centralHeight = usableHeight - topSpace - bottomSpace;
  const centralWidth = usableWidth - (left.length ? sideReserve : 0) - (right.length ? sideReserve : 0);

  /* If the requested number of planet observation windows cannot physically surround a
     Room at this viewport, preserve the same ownership and z-order contract
     with a bounded stack. This branch is only for genuinely undersized
     canvases; normal desktop sizes use the perimeter composition above. */
  if (centralHeight < PAW_WINDOW_MIN_HEIGHT || centralWidth < PAW_WINDOW_MIN_WIDTH) {
    /* A rail is the narrow-screen fallback, not an overflowing grid. The
       WindowLayer extracts these frames into a real scroll container so the
       main Room remains bounded and every planet stays reachable. */
    return layoutHorizontalSatelliteRail(frames, main, planets, viewport, usableTop, usableBottom, inset, gap);
  }

  const preferredMainWidth = Math.round(usableWidth * .54);
  const mainWidth = Math.min(centralWidth, Math.max(PAW_WINDOW_MIN_WIDTH, preferredMainWidth));
  const mainX = inset + (usableWidth - mainWidth) / 2;
  const mainY = usableTop + topSpace + Math.max(0, (centralHeight - Math.min(centralHeight, Math.round(usableHeight * .7))) / 2);
  const mainHeight = Math.min(centralHeight, Math.max(PAW_WINDOW_MIN_HEIGHT, Math.round(usableHeight * .7)));
  frames.set(main.id, { x: mainX, y: mainY, width: mainWidth, height: mainHeight });

  const placeRow = (items: PawWindowNode[], y: number) => {
    if (!items.length) return;
    const rowWidth = items.length * planetWidth + (items.length - 1) * gap;
    const start = Math.max(inset, (viewport.width - rowWidth) / 2);
    items.forEach((node, index) => frames.set(node.id, {
      x: start + index * (planetWidth + gap),
      y,
      width: planetWidth,
      height: planetHeight,
    }));
  };
  placeRow(planets.slice(0, topCount), usableTop);
  placeRow(planets.slice(topCount, topCount + bottomCount), usableBottom - planetHeight);
  const placeSide = (items: PawWindowNode[], x: number) => {
    if (!items.length) return;
    const totalHeight = items.length * planetHeight + (items.length - 1) * gap;
    const top = usableTop + Math.max(0, (usableHeight - totalHeight) / 2);
    items.forEach((node, index) => frames.set(node.id, {
      x,
      y: top + index * (planetHeight + gap),
      width: planetWidth,
      height: planetHeight,
    }));
  };
  placeSide(left, inset);
  placeSide(right, viewport.width - inset - planetWidth);
  return frames;
}

function usesHorizontalFocusRail(
  satelliteCount: number,
  viewportWidth: number,
  usableHeight: number,
  inset = 10,
  gap = 10,
): boolean {
  if (satelliteCount < 5) return false;
  const columnCount = viewportWidth < 1_000 ? 1 : 2;
  const longestColumn = Math.ceil(satelliteCount / columnCount);
  const projectedHeight = (
    usableHeight - inset * 2 - gap * Math.max(0, longestColumn - 1)
  ) / longestColumn;
  return viewportWidth < 720 || projectedHeight < PAW_WINDOW_MIN_HEIGHT;
}

const PAW_ROOM_FOCUS_RAIL_HEIGHT = 220;

/**
 * Lay out satellites in one scrollable strip when a side/grid projection
 * cannot honor the window floor. The strip deliberately overflows in the x
 * axis; PawRoomFocusRail owns that overflow and exposes every stable window
 * identity through keyboard and pointer scrolling.
 */
function layoutHorizontalSatelliteRail(
  frames: Map<string, PawWindowBounds>,
  main: PawWindowNode,
  satellites: PawWindowNode[],
  viewport: { width: number; height: number },
  usableTop: number,
  usableBottom: number,
  inset: number,
  gap: number,
): Map<string, PawWindowBounds> {
  const mainTop = usableTop + inset;
  const railHeight = Math.max(PAW_ROOM_FOCUS_RAIL_HEIGHT, Math.min(260, Math.round((usableBottom - usableTop) * .32)));
  const railTop = Math.max(mainTop + PAW_WINDOW_MIN_HEIGHT + gap, usableBottom - inset - railHeight);
  const mainHeight = Math.max(PAW_WINDOW_MIN_HEIGHT, railTop - gap - mainTop);
  const mainWidth = Math.max(PAW_WINDOW_MIN_WIDTH, viewport.width - inset * 2);
  const satelliteWidth = Math.max(PAW_WINDOW_MIN_WIDTH, Math.min(320, Math.round(viewport.width * .34)));
  frames.set(main.id, {
    x: inset,
    y: mainTop,
    width: mainWidth,
    height: mainHeight,
  });
  satellites.forEach((node, index) => frames.set(node.id, {
    x: inset + index * (satelliteWidth + gap),
    y: railTop,
    width: satelliteWidth,
    height: railHeight,
  }));
  return frames;
}
type RoomFocusRailMetrics = {
  height: number;
  satelliteIds: string[];
  top: number;
  trackWidth: number;
};

function roomFocusRailMetrics(
  satellites: PawWindowNode[],
  frames: ReadonlyMap<string, PawWindowBounds>,
  viewport: { width: number; height: number },
  reserved: { modeBarHeight?: number; ledgerHeight?: number } = {},
): RoomFocusRailMetrics | null {
  const usableHeight = Math.max(0,
    viewport.height
    - Math.max(0, reserved.modeBarHeight ?? 0)
    - Math.max(0, reserved.ledgerHeight ?? 0),
  );
  if (usableHeight <= 0) return null;
  const satelliteFrames = satellites.flatMap((node) => {
    const frame = frames.get(node.id);
    return frame ? [{ id: node.id, frame }] : [];
  });
  if (satelliteFrames.length !== satellites.length) return null;
  const top = Math.min(...satelliteFrames.map(({ frame }) => frame.y));
  /* A user may drag one card a few pixels while it is in the rail. The
   * overflow itself is the stable layout marker; requiring equal y values
   * would unmount the rail on the next render and swap the interaction back
   * to the ordinary focus clamp. */
  const horizontalRail = satelliteFrames.some(({ frame }) => frame.x + frame.width > viewport.width);
  if (!horizontalRail) return null;
  const bottom = Math.max(...satelliteFrames.map(({ frame }) => frame.y + frame.height));
  const trackWidth = Math.max(viewport.width, ...satelliteFrames.map(({ frame }) => frame.x + frame.width + 10));
  return { height: bottom - top + 12, satelliteIds: satelliteFrames.map(({ id }) => id), top, trackWidth };
}

function clampFocusBounds(
  bounds: PawWindowBounds,
  viewport: { width: number; height: number },
  reserved: { modeBarHeight?: number; ledgerHeight?: number },
): PawWindowBounds {
  const top = Math.max(0, reserved.modeBarHeight ?? 0);
  const bottom = Math.max(top, viewport.height - Math.max(0, reserved.ledgerHeight ?? 0));
  const width = Math.min(Math.max(PAW_WINDOW_MIN_WIDTH, bounds.width), Math.max(PAW_WINDOW_MIN_WIDTH, viewport.width));
  const height = Math.min(Math.max(PAW_WINDOW_MIN_HEIGHT, bounds.height), Math.max(PAW_WINDOW_MIN_HEIGHT, bottom - top));
  return {
    x: Math.min(Math.max(0, bounds.x), Math.max(0, viewport.width - width)),
    y: Math.min(Math.max(top, bounds.y), Math.max(top, bottom - height)),
    width,
    height,
  };
}

type CollaborationRail = {
  ids: ReadonlySet<string>;
  trackWidth: number;
};

function collaborationHorizontalRail(
  frames: ReadonlyMap<string, PawWindowBounds>,
  viewport: { width: number; height: number },
): CollaborationRail | null {
  /* A focus rail is the only collaboration layout that intentionally lets
   * several same-row frames run past the viewport. Looking only for an
   * overflowing frame would mistake a stale one-window override for that
   * layout, so require a real same-row run with at least two members. */
  const rows = new Map<number, Array<[string, PawWindowBounds]>>();
  for (const entry of frames) {
    const row = Math.round(entry[1].y);
    const current = rows.get(row) ?? [];
    current.push(entry);
    rows.set(row, current);
  }
  for (const row of rows.values()) {
    if (row.length < 2 || !row.some(([, frame]) => frame.x + frame.width > viewport.width)) continue;
    const ordered = row.slice().sort((left, right) => left[1].x - right[1].x);
    return {
      ids: new Set(ordered.map(([id]) => id)),
      trackWidth: Math.max(viewport.width, ...ordered.map(([, frame]) => frame.x + frame.width + 10)),
    };
  }
  return null;
}

function clampCollaborationRailBounds(
  bounds: PawWindowBounds,
  viewport: { width: number; height: number },
  reserved: { modeBarHeight?: number; ledgerHeight?: number },
  trackWidth: number,
): PawWindowBounds {
  const top = Math.max(0, reserved.modeBarHeight ?? 0);
  const bottom = Math.max(top, viewport.height - Math.max(0, reserved.ledgerHeight ?? 0));
  const width = Math.min(Math.max(PAW_WINDOW_MIN_WIDTH, bounds.width), Math.max(PAW_WINDOW_MIN_WIDTH, trackWidth));
  const height = Math.min(Math.max(PAW_WINDOW_MIN_HEIGHT, bounds.height), Math.max(PAW_WINDOW_MIN_HEIGHT, bottom - top));
  return {
    x: Math.min(Math.max(0, bounds.x), Math.max(0, trackWidth - width)),
    y: Math.min(Math.max(top, bounds.y), Math.max(top, bottom - height)),
    width,
    height,
  };
}

/**
 * Merge user-adjusted focus frames while keeping ordinary Room grid frames
 * inside the desktop after roster or viewport changes. A horizontal Room rail
 * is an intentional scroll region: its frames may extend past the viewport,
 * but stale overrides are still bounded to that rail's reachable track.
 */
export function normalizeCollaborationFocusFrames(
  computed: ReadonlyMap<string, PawWindowBounds>,
  overrides: Readonly<Record<string, PawWindowBounds>>,
  viewport: { width: number; height: number },
  reserved: { modeBarHeight?: number; ledgerHeight?: number },
  containRoomFrames = false,
): Map<string, PawWindowBounds> {
  const rail = containRoomFrames ? collaborationHorizontalRail(computed, viewport) : null;
  return new Map([...computed].map(([id, frame]) => [
    id,
    containRoomFrames
      ? rail?.ids.has(id)
        ? clampCollaborationRailBounds(overrides[id] ?? frame, viewport, reserved, rail.trackWidth)
        : clampFocusBounds(overrides[id] ?? frame, viewport, reserved)
      : overrides[id] ?? frame,
  ]));
}

function windowCenter(bounds: PawWindowBounds): WindowFlowPoint {
  return { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
}

function windowFlowKindLabel(kind: WindowFlowPacket['kind']): string {
  return ({ request: '需求', intercom: '伙伴请求', question: '问题', answer: '答复', result: '结果', context: '上下文', dispatch: '分派', approval: '审批', review: '复核' } as const)[kind];
}

function reviewTargetParticipantId(payload: Record<string, unknown>): string {
  return stringValue(payload.targetParticipantId)
    || stringValue(payload.reviewerParticipantId)
    || stringValue(payload.verifierParticipantId)
    || stringValue(payload.reviewedParticipantId)
    || stringValue(payload.revieweeParticipantId);
}

function windowFlowClock(timestamp?: number): string {
  return timestamp ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(timestamp)) : '';
}

/** FlowPacket 合同字段：FP-ID 只展示可辨识尾段，完整 ID 留在 title/详情里。 */
function windowFlowPacketId(id: string): string {
  const tail = id.replace(/^(activity|message):/, '');
  return tail.length > 12 ? `…${tail.slice(-9)}` : tail;
}

function windowFlowStatusLabel(status?: string): string {
  if (!status) return '已记录';
  if (['completed', 'delivered', 'done'].includes(status)) return '已送达';
  if (['running', 'streaming'].includes(status)) return '送达中';
  if (['queued', 'pending', 'waiting'].includes(status)) return '等待';
  if (status === 'failed') return '失败';
  if (['aborted', 'cancelled', 'stopped'].includes(status)) return '已停止';
  return status;
}

function stringValue(value: unknown): string { return typeof value === 'string' ? value : ''; }

/* One window's geometry commit replaces the store's windows map, which
 * re-renders the layer — but it must not re-render every other window's App
 * tree. memo bails untouched windows out at the frame boundary; each window's
 * own store slice (its node, stack position, active flag) still re-renders
 * exactly the window that changed. */
const PawWindow = memo(function PawWindow({ collaborationFocusGroup, flowState, focusFrame, onFocusFrameCommit, overview, overviewFrame, windowId }: {
  collaborationFocusGroup: string | null;
  flowState?: 'source' | 'arrival';
  focusFrame?: PawWindowBounds;
  onFocusFrameCommit: (windowId: string, bounds: PawWindowBounds) => void;
  overview: boolean;
  overviewFrame?: OverviewFrame;
  windowId: string;
}) {
  const api = usePawDesktopApi();
  const node = usePawDesktopStore((state) => state.windows[windowId]);
  const zIndex = usePawDesktopStore((state) => state.stack.indexOf(windowId) + 10);
  const active = usePawDesktopStore((state) => state.activeWindowId === windowId);
  const openLinkedRoute = useCallback((event: ReactMouseEvent<HTMLElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[href]');
    if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return;
    const href = anchor.getAttribute('href') ?? '';
    if (!href.startsWith('#/')) return;
    event.preventDefault();
    openDesktopRoute(api, href.slice(1));
  }, [api]);
  /* The App surface depends only on process identity and committed size.
   * Keeping the element referentially stable means frame-only re-renders —
   * z-order churn on every focus click, active/flow flags, drag position
   * commits — bail out at MemoizedWindowBody instead of reconciling the App
   * provider chain, so a window's own re-render walks chrome only. */
  const appId = node?.appId;
  const entityId = node?.entityId;
  const initialRoute = node?.initialRoute;
  const target = node?.target;
  const surfaceWidth = focusFrame?.width ?? node?.bounds.width ?? 0;
  const surfaceHeight = Math.max(0, focusFrame?.height ?? node?.bounds.height ?? 0);
  const appSurface = useMemo(() => (appId ? (
    <div className="paw-window-route-surface" onClick={openLinkedRoute}>
      <PawOsAppSurfaceProvider active={active && !overview} appId={appId} height={surfaceHeight} width={surfaceWidth} windowId={windowId}>
        <PawAppProcess appId={appId} entityId={entityId} initialRoute={initialRoute} target={target} />
      </PawOsAppSurfaceProvider>
    </div>
  ) : null), [active, appId, entityId, initialRoute, openLinkedRoute, overview, surfaceHeight, surfaceWidth, target, windowId]);
  if (!node || (node.minimized && !overview)) return null;
  const app = pawApp(node.appId);
  const inFocus = collaborationFocusGroup ? windowBelongsToFocus(node, collaborationFocusGroup) : false;
  const collaborationRole = collaborationFocusGroup
    ? !inFocus
      ? 'hidden'
      : isCollaborationSatellite(node)
      ? 'satellite'
      : node.appId === 'agent'
        ? 'primary'
        : 'unrelated'
    : undefined;
  return (
    <PawWindowFrame
      active={active}
      bounds={node.bounds}
      collaborationRole={collaborationRole}
      deferPointerInteractionUntilFocused={!collaborationFocusGroup && Boolean(satelliteGroup(node.target))}
      flowState={flowState}
      focusFrame={focusFrame}
      frameMode={focusFrame && target?.kind === 'participant'
        ? 'planet'
        : focusFrame && collaborationRole === 'satellite'
          ? 'focus-card'
          : 'window'}
      onBoundsCommit={(bounds) => {
        if (focusFrame) {
          onFocusFrameCommit(windowId, bounds);
          return;
        }
        api.getState().commitBounds(windowId, bounds);
        api.getState().fitWindowsToViewport();
      }}
      onClose={() => {
        pulsePawComposition('system', .84);
        api.getState().closeWindow(windowId);
      }}
      onFocus={() => {
        pulsePawComposition('system', .38);
        api.getState().focusWindow(windowId);
      }}
      onMinimize={() => {
        pulsePawComposition('system', .62);
        api.getState().minimizeWindow(windowId);
      }}
      onOpenFromOverview={() => api.getState().focusWindow(windowId)}
      onSnap={(placement) => {
        pulsePawComposition('system', .76);
        api.getState().snapWindow(windowId, placement);
      }}
      onToggleMaximize={() => {
        pulsePawComposition('system', .72);
        api.getState().toggleMaximize(windowId);
      }}
      placement={node.placement}
      overview={overview}
      overviewFrame={overviewFrame}
      appId={node.appId}
      title={node.title || app.label}
      subtitle={node.target?.subtitle}
      targetKind={node.target?.kind}
      windowChrome={node.target?.kind === 'room' && !node.target.panel ? 'room-workspace' : node.appId === 'agent' ? 'agent-session' : node.appId === 'browser' ? 'browser-tabs' : node.appId === 'files' ? 'files-tools' : node.appId === 'terminal' ? 'terminal-tabs' : undefined}
      windowId={windowId}
      zIndex={zIndex}
    >
      {appSurface}
    </PawWindowFrame>
  );
});

export function openDesktopRoute(api: ReturnType<typeof usePawDesktopApi>, route: string): void {
  const normalized = route.replace(/^#/, '');
  if (normalized.split(/[?#]/, 1)[0] === '/project-field') {
    api.getState().showWayfinder();
    return;
  }
  const app = pawAppForPath(normalized);
  if (!app) return;
  const search = normalized.split('?', 2)[1] ?? '';
  const params = new URLSearchParams(search);
  if (app.id === 'agent') {
    const sessionId = params.get('session') || params.get('sessionId');
    if (sessionId) {
      api.getState().openApp('agent', {
        entityId: sessionId,
        initialRoute: normalized,
        target: { kind: 'session', id: sessionId, title: 'Session' },
        title: 'Agent',
      });
      return;
    }
    const roomId = params.get('room');
    if (roomId) {
      api.getState().openApp('agent', {
        entityId: roomId,
        initialRoute: normalized,
        target: { kind: 'room', id: roomId, title: 'Room' },
        title: 'Agent',
      });
      return;
    }
  }
  api.getState().openApp(app.id, { initialRoute: normalized, title: app.label });
}

export function PawWindowFrame({ active, appId, bounds, children, collaborationRole, deferPointerInteractionUntilFocused = false, flowState, focusFrame, frameMode = 'window', onBoundsCommit, onClose, onFocus, onMinimize, onOpenFromOverview, onSnap, onToggleMaximize, overview = false, overviewFrame, placement, subtitle, targetKind, title, windowChrome, windowId, zIndex }: {
  active: boolean;
  appId: PawAppId;
  bounds: PawWindowBounds;
  children: ReactNode;
  collaborationRole?: 'primary' | 'satellite' | 'unrelated' | 'hidden';
  deferPointerInteractionUntilFocused?: boolean;
  flowState?: 'source' | 'arrival';
  focusFrame?: PawWindowBounds;
  frameMode?: 'window' | 'focus-card' | 'planet';
  onBoundsCommit: (bounds: PawWindowBounds) => void;
  onClose: () => void;
  onFocus: () => void;
  onMinimize: () => void;
  onOpenFromOverview?: () => void;
  onSnap?: (placement: PawWindowPlacement) => void;
  onToggleMaximize: () => void;
  overview?: boolean;
  overviewFrame?: OverviewFrame;
  placement?: PawWindowPlacement;
  subtitle?: string;
  targetKind?: PawOsWindowRequest['target']['kind'];
  title: string;
  windowChrome?: string;
  windowId: string;
  zIndex: number;
}) {
  const shellRef = useRef<HTMLElement>(null);
  const [windowLeadingChromeTarget, setWindowLeadingChromeTarget] = useState<HTMLElement | null>(null);
  const [windowChromeTarget, setWindowChromeTarget] = useState<HTMLElement | null>(null);
  const maximized = placement === 'maximized';
  const identityIconId = targetKind === 'room' ? 'room' : appId;
  const planetFrame = frameMode === 'planet' && !overview;
  const interactionBounds = focusFrame ?? bounds;
  /* A focus frame or rail slot is laid out by its owning mode and clamped on
   * commit against that mode's own box, so only an ordinary desktop window
   * answers to the shared desktop area. */
  const containToDesktop = !focusFrame;
  const drag = useWindowDrag(shellRef, interactionBounds, onBoundsCommit, onFocus, focusFrame ? undefined : onSnap, active, deferPointerInteractionUntilFocused, containToDesktop);
  const exit = useWindowExit(shellRef, appId);
  /* Windows arrive the way a real OS opens them: a short scale-up fade on the
   * inner surface (the shell's transform belongs to drag, snap and overview).
   * The same mount path covers restore-from-minimize, so a restored window
   * reads as returning instead of popping. Room-flow arrivals and
   * collaboration satellites carry their own authored choreography and are
   * left to it. */
  const authoredArrival = Boolean(flowState) || collaborationRole === 'satellite';
  useLayoutEffect(() => {
    const shell = shellRef.current;
    if (!active || overview || collaborationRole === 'hidden' || !shell || shell.contains(document.activeElement)) return;
    /* Opening or restoring a window changes the keyboard context too. Focus
     * the frame itself before child effects run; an App may still promote a
     * more specific autofocus target, while Tab naturally enters titlebar and
     * content controls from here. */
    shell.focus({ preventScroll: true });
  // The frame only owns the mount transition. Later activation by pointer is
  // already focused through the pressed descendant and must not be stolen.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (authoredArrival) return;
    const surface = shellRef.current?.querySelector<HTMLElement>('.paw-window');
    if (!surface || typeof surface.animate !== 'function' || pawWindowReducedMotion()) return;
    surface.animate([
      { opacity: .6, transform: 'translate3d(0, 6px, 0) scale(.98)' },
      { opacity: 1, transform: 'translate3d(0, 0, 0) scale(1)' },
    ], { duration: 150, easing: 'cubic-bezier(.2, .85, .25, 1)' });
    // Mount-only by design: re-running on prop drift would re-arrive a window
    // that is already on stage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const transform = focusFrame
    ? `translate3d(${focusFrame.x}px, ${focusFrame.y}px, 0)`
    : overview && overviewFrame
    ? `translate3d(${overviewFrame.x}px, ${overviewFrame.y}px, 0) scale(${overviewFrame.scale})`
    : `translate3d(${bounds.x}px, ${bounds.y}px, 0)`;
  useWindowPlacementFlip(shellRef, {
    bounds,
    enabled: !focusFrame && !overview && frameMode === 'window',
    placement,
  });
  const shellStyle = {
    width: focusFrame?.width ?? bounds.width,
    height: focusFrame?.height ?? bounds.height,
    transform,
    zIndex: overviewFrame?.zIndex ?? zIndex,
    ...(focusFrame ? {
      '--paw-focus-frame-height': `${focusFrame.height}px`,
      '--paw-focus-frame-transform': transform,
      '--paw-focus-frame-width': `${focusFrame.width}px`,
    } : {}),
  } as CSSProperties;
  return (
    <PawWindowChromeProvider leading={windowLeadingChromeTarget} trailing={windowChromeTarget}>
      <section aria-label={`${title}${subtitle ? ` · ${subtitle}` : ''}窗口`} className="paw-window-shell" data-active={active || undefined} data-app={appId} data-collaboration-role={collaborationRole} data-flow-state={flowState} data-focus-layout={focusFrame ? true : undefined} data-frame-mode={frameMode} data-overview={overview || undefined} data-paw-window-id={windowId} data-placement={placement} data-window-target={targetKind} onPointerDown={() => { if (!overview && !active) onFocus(); }} ref={shellRef} style={shellStyle} tabIndex={-1}>
        {planetFrame ? (
          <div className="paw-planet-surface" data-flow-state={flowState}>
            <header className="paw-planet-identity" onPointerDown={drag}>
              <span aria-hidden="true" className="paw-planet-identity-mark" />
              <strong>{title}</strong>
              {subtitle ? <small>{subtitle}</small> : null}
              <button
                aria-label={`关闭${title}行星窗口`}
                className="paw-planet-close"
                onClick={() => exit('close', onClose)}
                onPointerDown={(event) => event.stopPropagation()}
                title="关闭行星窗口"
                type="button"
              >
                <X aria-hidden="true" size={12} />
              </button>
            </header>
            <MemoizedWindowBody>{children}</MemoizedWindowBody>
          </div>
        ) : (
          <div aria-hidden={overview || undefined} className="paw-window" inert={overview ? true : undefined}>
            <header className="paw-window-titlebar" data-window-chrome={windowChrome} onDoubleClick={overview || focusFrame ? undefined : onToggleMaximize} onPointerDown={overview ? undefined : drag}>
              {/* One chrome language: every window — main Room, collaboration
                * focus primary and focus-card satellite alike — opens with the
                * same red/yellow/green cluster in the same slot. The lights stay
                * the first children so the shared nth-child colour rules keep
                * mapping onto close/minimize/maximize; App-owned leading chrome
                * docks after them instead of pushing them out of position.
                * Inside the collaboration focus layout the layout owns geometry,
                * so the maximize verb drops for primary and satellite together
                * rather than only for satellites. */}
              <div className="paw-traffic-lights" onDoubleClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()}>
                <button aria-label="关闭窗口" data-action="close" onClick={() => exit('close', onClose)} title="关闭" type="button"><X size={9} /></button>
                <button aria-label="最小化窗口" data-action="minimize" onClick={() => exit('minimize', onMinimize)} title="最小化" type="button"><Minus size={9} /></button>
                {focusFrame ? null : <button aria-label={maximized ? '还原窗口' : '最大化窗口'} data-action={maximized ? 'restore' : 'maximize'} onClick={onToggleMaximize} title={maximized ? '还原' : '最大化'} type="button">{maximized ? <Minimize2 size={8} /> : <Maximize2 size={8} />}</button>}
                {windowChrome ? <div className="paw-window-leading-slot" onDoubleClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()} ref={setWindowLeadingChromeTarget} /> : null}
              </div>
              <div className="paw-window-title"><PawAppIcon appId={identityIconId} size={16} /><strong>{title}</strong>{subtitle ? <small>{subtitle}</small> : null}</div>
              {windowChrome ? <div className="paw-window-chrome-slot" onDoubleClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()} ref={setWindowChromeTarget} /> : null}
            </header>
            <MemoizedWindowBody>{children}</MemoizedWindowBody>
          </div>
        )}
        {overview ? (
          <button aria-label={`打开 ${title}`} className="paw-overview-window-target" onClick={onOpenFromOverview} type="button"><PawAppIcon appId={identityIconId} size={24} /><span>{title}</span></button>
        ) : planetFrame ? null : (
          <PawWindowResizeHandles active={active} bounds={interactionBounds} containToDesktop={containToDesktop} deferPointerInteractionUntilFocused={deferPointerInteractionUntilFocused} onBoundsCommit={onBoundsCommit} onFocus={onFocus} shellRef={shellRef} />
        )}
      </section>
    </PawWindowChromeProvider>
  );
}

type PawWindowResizeHandle = 'north' | 'south' | 'east' | 'west' | 'north-east' | 'north-west' | 'south-east' | 'south-west';
const pawWindowResizeHandles: PawWindowResizeHandle[] = ['north', 'south', 'east', 'west', 'north-east', 'north-west', 'south-east', 'south-west'];
const pawWindowResizeLabels: Record<PawWindowResizeHandle, string> = {
  north: '调整窗口上边缘',
  south: '调整窗口下边缘',
  east: '调整窗口右边缘',
  west: '调整窗口左边缘',
  'north-east': '调整窗口右上角',
  'north-west': '调整窗口左上角',
  'south-east': '调整窗口右下角',
  'south-west': '调整窗口左下角',
};

function PawWindowResizeHandles({ active, bounds, containToDesktop, deferPointerInteractionUntilFocused, onBoundsCommit, onFocus, shellRef }: {
  active: boolean;
  bounds: PawWindowBounds;
  containToDesktop: boolean;
  deferPointerInteractionUntilFocused: boolean;
  onBoundsCommit: (bounds: PawWindowBounds) => void;
  onFocus: () => void;
  shellRef: RefObject<HTMLElement | null>;
}) {
  return pawWindowResizeHandles.map((handle) => (
    <PawWindowResizeHandle
      active={active}
      bounds={bounds}
      containToDesktop={containToDesktop}
      deferPointerInteractionUntilFocused={deferPointerInteractionUntilFocused}
      handle={handle}
      key={handle}
      onBoundsCommit={onBoundsCommit}
      onFocus={onFocus}
      shellRef={shellRef}
    />
  ));
}

function PawWindowResizeHandle({ active, bounds, containToDesktop, deferPointerInteractionUntilFocused, handle, onBoundsCommit, onFocus, shellRef }: {
  active: boolean;
  bounds: PawWindowBounds;
  containToDesktop: boolean;
  deferPointerInteractionUntilFocused: boolean;
  handle: PawWindowResizeHandle;
  onBoundsCommit: (bounds: PawWindowBounds) => void;
  onFocus: () => void;
  shellRef: RefObject<HTMLElement | null>;
}) {
  const resize = useWindowResize(shellRef, bounds, handle, onBoundsCommit, onFocus, active, deferPointerInteractionUntilFocused, containToDesktop);
  const horizontal = handle.includes('east') || handle.includes('west');
  const vertical = handle.includes('north') || handle.includes('south');
  const keyShortcuts = [horizontal ? 'ArrowLeft ArrowRight' : '', vertical ? 'ArrowUp ArrowDown' : ''].filter(Boolean).join(' ');
  const resizeFromKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const deltaX = event.key === 'ArrowRight' ? 16 : event.key === 'ArrowLeft' ? -16 : 0;
    const deltaY = event.key === 'ArrowDown' ? 16 : event.key === 'ArrowUp' ? -16 : 0;
    if ((!deltaX || !horizontal) && (!deltaY || !vertical)) return;
    event.preventDefault();
    if (!active) onFocus();
    onBoundsCommit(resizeWindowBounds(bounds, handle, deltaX, deltaY, containToDesktop ? pawWindowArea() : undefined));
  };
  return <button
    aria-keyshortcuts={keyShortcuts}
    aria-label={pawWindowResizeLabels[handle]}
    className="paw-window-resize"
    data-handle={handle}
    onKeyDown={resizeFromKeyboard}
    onPointerDown={resize}
    tabIndex={active ? 0 : -1}
    type="button"
  />;
}

type OverviewFrame = { x: number; y: number; scale: number; zIndex: number };

function layoutOverview(
  nodes: Array<{ id: string; bounds: PawWindowBounds }>,
  viewport: { width: number; height: number },
): Map<string, OverviewFrame> {
  const frames = new Map<string, OverviewFrame>();
  if (nodes.length === 0) return frames;
  const insetX = 44;
  const insetTop = 34;
  const insetBottom = 104;
  const gap = 24;
  const availableWidth = Math.max(320, viewport.width - insetX * 2);
  const availableHeight = Math.max(240, viewport.height - insetTop - insetBottom);
  const columns = Math.min(nodes.length, Math.max(1, Math.ceil(Math.sqrt(nodes.length * availableWidth / availableHeight))));
  const rows = Math.ceil(nodes.length / columns);
  const cellWidth = (availableWidth - gap * (columns - 1)) / columns;
  const cellHeight = (availableHeight - gap * (rows - 1)) / rows;
  nodes.forEach((node, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const scale = Math.min(.82, (cellWidth - 20) / node.bounds.width, (cellHeight - 38) / node.bounds.height);
    const previewWidth = node.bounds.width * scale;
    const previewHeight = node.bounds.height * scale;
    frames.set(node.id, {
      x: insetX + column * (cellWidth + gap) + (cellWidth - previewWidth) / 2,
      y: insetTop + row * (cellHeight + gap) + (cellHeight - previewHeight) / 2,
      scale,
      zIndex: index + 20,
    });
  });
  return frames;
}

const MemoizedWindowBody = memo(function WindowBody({ children }: { children: ReactNode }) {
  return <div className="paw-window-body">{children}</div>;
});

function pawWindowReducedMotion(): boolean {
  if (document.documentElement.getAttribute('data-reduce-motion') === 'true') return true;
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

type PawWindowPlacementFrame = {
  bounds: PawWindowBounds;
  placement?: PawWindowPlacement;
};

/* Maximize, restore and snap are layout changes, but their visible trip does
 * not have to be. React commits the destination width/height once; this FLIP
 * animation paints the previous rectangle through an inverse transform and
 * lets the compositor carry it to the destination. Live drag/resize never
 * enters this path, and overview/focus layouts keep their own choreography. */
function useWindowPlacementFlip(
  ref: RefObject<HTMLElement | null>,
  next: PawWindowPlacementFrame & { enabled: boolean },
): void {
  const previousRef = useRef<PawWindowPlacementFrame | undefined>(undefined);
  useLayoutEffect(() => {
    const previous = previousRef.current;
    previousRef.current = { bounds: next.bounds, placement: next.placement };
    const shell = ref.current;
    if (
      !previous
      || !next.enabled
      || previous.placement === next.placement
      || !shell
      || typeof shell.animate !== 'function'
      || pawWindowReducedMotion()
      || next.bounds.width <= 0
      || next.bounds.height <= 0
    ) return undefined;

    const scaleX = previous.bounds.width / next.bounds.width;
    const scaleY = previous.bounds.height / next.bounds.height;
    shell.dataset.placementAnimation = 'true';
    const animation = shell.animate([
      {
        transform: `translate3d(${previous.bounds.x}px, ${previous.bounds.y}px, 0) scale(${scaleX}, ${scaleY})`,
      },
      {
        transform: `translate3d(${next.bounds.x}px, ${next.bounds.y}px, 0) scale(1, 1)`,
      },
    ], {
      duration: 180,
      easing: 'cubic-bezier(.23, 1, .32, 1)',
    });
    const clear = () => {
      if (shell.dataset.placementAnimation) delete shell.dataset.placementAnimation;
    };
    const finished = (animation as unknown as { finished?: Promise<Animation> }).finished;
    const fallbackTimer = finished ? 0 : window.setTimeout(clear, 180);
    if (finished) void finished.then(clear, clear);
    return () => {
      if (fallbackTimer) window.clearTimeout(fallbackTimer);
      animation.cancel();
      clear();
    };
  }, [next.bounds.height, next.bounds.width, next.bounds.x, next.bounds.y, next.enabled, next.placement, ref]);
}

function useWindowExit(ref: RefObject<HTMLElement | null>, appId: PawAppId) {
  return useCallback((kind: 'close' | 'minimize', finish: () => void) => {
    const surface = ref.current?.querySelector<HTMLElement>('.paw-window');
    if (!surface || typeof surface.animate !== 'function' || pawWindowReducedMotion()) {
      finish();
      return;
    }
    if (surface.dataset.exiting) return;
    surface.dataset.exiting = kind;
    let duration = 160;
    let easing = 'cubic-bezier(.77, 0, .175, 1)';
    let target = 'translate3d(0, 10px, 0) scale(.97)';
    if (kind === 'minimize') {
      duration = 180;
      target = 'translate3d(0, 34px, 0) scale(.9)';
      /* Minimize flies to the App's Dock tile, the way the reference genie
       * reads: window centre travels to the tile centre while the frame
       * scales toward the tile, 280ms on the shared genie curve. When the
       * Dock is hidden (a maximized window owns the desktop) or the tile
       * cannot be measured, the window keeps the older sink-in-place exit. */
      const genie = dockTileGenieDelta(appId, surface);
      if (genie) {
        target = `translate3d(${genie.dx.toFixed(1)}px, ${genie.dy.toFixed(1)}px, 0) scale(${genie.scale.toFixed(3)})`;
        duration = 280;
        easing = 'cubic-bezier(.4, 0, .2, 1)';
      }
    }
    const animation = surface.animate([
      { opacity: 1, transform: 'translate3d(0, 0, 0) scale(1)' },
      { opacity: 0, transform: target },
    ], {
      duration,
      easing,
      fill: 'forwards',
    });
    void animation.finished.then(finish, finish);
  }, [ref, appId]);
}

/* The one genie geometry, shared by both directions of the minimize round
 * trip: the delta from the window's centre to its App's Dock tile centre and
 * the scale that lands the frame on the tile. Null when the tile cannot be
 * measured (the Dock is hidden while a maximized window owns the desktop), so
 * both callers can fall back to their in-place choreography. */
function dockTileGenieDelta(appId: PawAppId, surface: HTMLElement): { dx: number; dy: number; scale: number } | null {
  const tile = document.querySelector<HTMLElement>(`.paw-dock [data-desktop-app="${appId}"]`);
  if (!tile) return null;
  const windowRect = surface.getBoundingClientRect();
  const tileRect = tile.getBoundingClientRect();
  if (windowRect.width <= 0 || tileRect.width <= 0) return null;
  return {
    dx: tileRect.left + tileRect.width / 2 - (windowRect.left + windowRect.width / 2),
    dy: tileRect.top + tileRect.height / 2 - (windowRect.top + windowRect.height / 2),
    scale: Math.max(.06, Math.min(.24, tileRect.width / windowRect.width)),
  };
}

function useWindowDrag(ref: RefObject<HTMLElement | null>, bounds: PawWindowBounds, commit: (bounds: PawWindowBounds) => void, focus: () => void, snap: ((placement: PawWindowPlacement) => void) | undefined, active: boolean, deferPointerInteractionUntilFocused: boolean, containToDesktop: boolean) {
  return useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
    event.preventDefault();
    if (!active) {
      focus();
      if (deferPointerInteractionUntilFocused) return;
    }
    const shell = ref.current;
    if (!shell) return;
    const desktopRoot = shell.closest<HTMLElement>('.paw-desktop-root');
    event.currentTarget.setPointerCapture(event.pointerId);
    shell.dataset.interaction = 'dragging';
    setWindowInteraction(desktopRoot, true);
    const origin = { x: event.clientX, y: event.clientY };
    /* Measured once per gesture, never per move: the desktop cannot resize
     * while a captured pointer owns the drag, and reading it per event would
     * put a layout-dependent measurement on the frame path. */
    const area = containToDesktop ? pawWindowArea() : null;
    let next = bounds;
    let frame = 0;
    const render = () => {
      frame = 0;
      shell.style.transform = `translate3d(${next.x}px, ${next.y}px, 0)`;
    };
    const move = (moveEvent: PointerEvent) => {
      const travelled = { ...bounds, x: bounds.x + moveEvent.clientX - origin.x, y: bounds.y + moveEvent.clientY - origin.y };
      /* Ordinary windows may keep a recoverable partial offset instead of
       * sticking to the canvas edge. Focus layouts still own their own clamp. */
      next = area ? fitReachablePawWindowBounds(travelled, area) : { ...travelled, y: Math.max(0, travelled.y) };
      setSnapPreview(desktopRoot, snapPlacement(moveEvent.clientX, moveEvent.clientY));
      if (!frame) frame = window.requestAnimationFrame(render);
    };
    const finish = (finishEvent: PointerEvent) => {
      if (frame) window.cancelAnimationFrame(frame);
      render();
      delete shell.dataset.interaction;
      setSnapPreview(desktopRoot);
      setWindowInteraction(desktopRoot, false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', cancel);
      const placement = snapPlacement(finishEvent.clientX, finishEvent.clientY);
      if (placement && snap) {
        snap(placement);
        return;
      }
      commit(next);
    };
    const cancel = () => {
      if (frame) window.cancelAnimationFrame(frame);
      delete shell.dataset.interaction;
      setSnapPreview(desktopRoot);
      setWindowInteraction(desktopRoot, false);
      shell.style.transform = `translate3d(${bounds.x}px, ${bounds.y}px, 0)`;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', cancel);
    };
    // The move stream never calls preventDefault; passive keeps the
    // compositor thread free while the pointer drives the transform.
    window.addEventListener('pointermove', move, { passive: true });
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', cancel);
  }, [active, bounds, commit, containToDesktop, deferPointerInteractionUntilFocused, focus, ref, snap]);
}

function setSnapPreview(root: HTMLElement | null, placement?: PawWindowPlacement): void {
  if (!root) return;
  // Pointermove can outpace the frame rate; rewriting the same attribute on
  // the desktop root would invalidate style for the whole desktop subtree on
  // every event, so only touch the DOM when the preview actually changes.
  if (root.dataset.snapPreview === placement) return;
  if (placement) root.dataset.snapPreview = placement;
  else delete root.dataset.snapPreview;
}

/* Exactly one attribute write per gesture edge (start and finish), never per
 * move event. The wallpaper reads this to pause weather animation while a
 * window drag/resize owns the frame budget. */
function setWindowInteraction(root: HTMLElement | null, active: boolean): void {
  if (!root) return;
  if (active) root.dataset.windowInteraction = 'true';
  else delete root.dataset.windowInteraction;
}

function snapPlacement(clientX: number, clientY: number): PawWindowPlacement | undefined {
  if (clientY <= 14) return 'maximized';
  if (clientX <= 14) return 'left';
  if (clientX >= window.innerWidth - 14) return 'right';
  return undefined;
}

function useWindowResize(ref: RefObject<HTMLElement | null>, bounds: PawWindowBounds, handle: PawWindowResizeHandle, commit: (bounds: PawWindowBounds) => void, focus: () => void, active: boolean, deferPointerInteractionUntilFocused: boolean, containToDesktop: boolean) {
  return useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    if (!active) {
      focus();
      if (deferPointerInteractionUntilFocused) return;
    }
    const shell = ref.current;
    if (!shell) return;
    const desktopRoot = shell.closest<HTMLElement>('.paw-desktop-root');
    event.currentTarget.setPointerCapture(event.pointerId);
    shell.dataset.interaction = 'resizing';
    shell.style.transformOrigin = '0 0';
    shell.style.willChange = 'transform';
    setWindowInteraction(desktopRoot, true);
    const origin = { x: event.clientX, y: event.clientY };
    const area = containToDesktop ? pawWindowArea() : undefined;
    let next = bounds;
    let frame = 0;
    const render = () => {
      frame = 0;
      shell.style.transform = `translate3d(${next.x}px, ${next.y}px, 0) scale(${next.width / bounds.width}, ${next.height / bounds.height})`;
    };
    const move = (moveEvent: PointerEvent) => {
      next = resizeWindowBounds(bounds, handle, moveEvent.clientX - origin.x, moveEvent.clientY - origin.y, area);
      if (!frame) frame = window.requestAnimationFrame(render);
    };
    const finish = () => {
      if (frame) window.cancelAnimationFrame(frame);
      /* The pointer stream only touched a compositor transform. Commit the
       * final geometry once, then remove the preview scale; this is the sole
       * live-resize layout pass. */
      shell.style.width = `${next.width}px`;
      shell.style.height = `${next.height}px`;
      shell.style.transform = `translate3d(${next.x}px, ${next.y}px, 0)`;
      shell.style.transformOrigin = '';
      shell.style.willChange = '';
      delete shell.dataset.interaction;
      setWindowInteraction(desktopRoot, false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
      commit(next);
    };
    window.addEventListener('pointermove', move, { passive: true });
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
  }, [active, bounds, commit, containToDesktop, deferPointerInteractionUntilFocused, focus, handle, ref]);
}

/** UR-057 / PF-CM-005：每条边都跟随指针 1:1，但窗口最小尺寸与桌面边界都是硬约束。
 *  A north/west drag moves the opposite edge, so without the area limit the
 *  titlebar can be pushed above the desktop where no pointer can reach it. */
export function resizeWindowBounds(
  bounds: PawWindowBounds,
  handle: PawWindowResizeHandle,
  deltaX: number,
  deltaY: number,
  area?: PawWindowBounds,
): PawWindowBounds {
  const left = area?.x ?? 0;
  const top = area?.y ?? 0;
  const right = area ? area.x + area.width : Number.POSITIVE_INFINITY;
  const bottom = area ? area.y + area.height : Number.POSITIVE_INFINITY;
  const next = { ...bounds };
  if (handle.includes('east')) {
    next.width = Math.min(Math.max(PAW_WINDOW_MIN_WIDTH, bounds.width + deltaX), Math.max(PAW_WINDOW_MIN_WIDTH, right - bounds.x));
  }
  if (handle.includes('south')) {
    next.height = Math.min(Math.max(PAW_WINDOW_MIN_HEIGHT, bounds.height + deltaY), Math.max(PAW_WINDOW_MIN_HEIGHT, bottom - bounds.y));
  }
  if (handle.includes('west')) {
    next.width = Math.min(Math.max(PAW_WINDOW_MIN_WIDTH, bounds.width - deltaX), Math.max(PAW_WINDOW_MIN_WIDTH, bounds.x + bounds.width - left));
    next.x = bounds.x + bounds.width - next.width;
  }
  if (handle.includes('north')) {
    next.height = Math.min(Math.max(PAW_WINDOW_MIN_HEIGHT, bounds.height - deltaY), Math.max(PAW_WINDOW_MIN_HEIGHT, bounds.y + bounds.height - top));
    next.y = bounds.y + bounds.height - next.height;
  }
  return next;
}
