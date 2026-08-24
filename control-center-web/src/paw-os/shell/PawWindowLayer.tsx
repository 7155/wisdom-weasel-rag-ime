import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from 'react';
import { ChevronRight, Maximize2, Minimize2, Minus, X } from 'lucide-react';
import { useControlTransport } from '@/app/control-transport';
import { Disclosure } from '@/components/primitives';
import {
  PawOsAppSurfaceProvider,
  PawOsDesktopProvider as FeatureDesktopProvider,
  type PawOsWindowRequest,
} from '@/features/paw-os/surface-context';
import { pawApp, pawAppForPath, type PawAppId } from '../runtime/app-registry';
import { usePawDesktopApi, usePawDesktopStore } from '../runtime/desktop-context';
import { satelliteGroup, type PawWindowBounds, type PawWindowNode, type PawWindowPlacement } from '../runtime/desktop-store';
import { PawAppProcess } from '../apps/PawApps';
import { PawAppIcon } from './PawAppIcon';
import { PawWindowChromeProvider } from './PawWindowChrome';
import { pulsePawComposition, pulsePawCompositionForRuntimeEvents } from '../runtime/composition-pulse';
import { useRoomLiveStore } from '@/features/rooms/state/live-store';
import { useRoomLiveSession } from '@/features/rooms/runtime/use-room-live-session';
import { roomActivityFlowKind } from '@/features/rooms/room-flow-projection';
import type { RoomProjectionState } from '@/contracts/room-reducer';

export function PawWindowLayer() {
  const api = usePawDesktopApi();
  const windows = usePawDesktopStore((state) => state.windows);
  const idSignature = usePawDesktopStore((state) => Object.keys(state.windows).join('\u0000'));
  const overviewOpen = usePawDesktopStore((state) => state.overviewOpen);
  const collaborationFocusGroup = usePawDesktopStore((state) => state.collaborationFocusGroup);
  const projections = useRoomLiveStore((state) => state.projections);
  const ids = useMemo(() => idSignature.split('\u0000').filter(Boolean), [idSignature]);
  const [viewport, setViewport] = useState(() => desktopSize());
  const [focusFrameOverrides, setFocusFrameOverrides] = useState<Record<string, PawWindowBounds>>({});
  const keptRoomIds = useMemo(() => roomProjectionKeepaliveIds(windows, overviewOpen), [overviewOpen, windows]);
  const focusedRoomId = collaborationFocusGroup?.startsWith('room:') ? collaborationFocusGroup.slice('room:'.length) : '';
  const computedFocusFrames = useMemo(() => collaborationFocusGroup
    ? layoutCollaborationFocus(
        Object.values(windows).filter((node) => windowBelongsToFocus(node, collaborationFocusGroup)),
        viewport,
        focusedRoomId ? { modeBarHeight: 46, ledgerHeight: 0 } : {},
      )
    : new Map<string, PawWindowBounds>(), [collaborationFocusGroup, focusedRoomId, viewport, windows]);
  const focusFrames = useMemo(() => new Map([...computedFocusFrames].map(([id, frame]) => [
    id,
    focusFrameOverrides[id] ?? frame,
  ])), [computedFocusFrames, focusFrameOverrides]);
  const focusedRoomNodes = useMemo(() => focusedRoomId
    ? Object.values(windows).filter((node) => windowBelongsToFocus(node, `room:${focusedRoomId}`))
    : [], [focusedRoomId, windows]);
  const focusedRoomSatellites = useMemo(() => focusedRoomNodes.filter(isCollaborationSatellite), [focusedRoomNodes]);
  const focusedRoomMain = focusedRoomNodes.find((node) => !isCollaborationSatellite(node));
  const focusedRoomProjection = focusedRoomId ? projections[focusedRoomId] : undefined;
  const focusedRoomStatus = roomFocusStatus(focusedRoomProjection);
  const flowWindows = useMemo(() => Object.fromEntries(Object.entries(windows).map(([id, node]) => [
    id,
    focusFrames.has(id) ? { ...node, bounds: focusFrames.get(id)! } : node,
  ])), [focusFrames, windows]);
  const flowGroups = useMemo(() => roomWindowFlowGroups(flowWindows, projections), [flowWindows, projections]);
  const flowPulse = useWindowFlowPulse(flowGroups);
  const roomFocusRail = useMemo(() => roomFocusRailMetrics(focusedRoomSatellites, focusFrames, viewport), [focusFrames, focusedRoomSatellites, viewport]);
  const roomFocusRailIds = useMemo(() => new Set(roomFocusRail?.satelliteIds ?? []), [roomFocusRail]);
  useEffect(() => {
    setFocusFrameOverrides({});
  }, [collaborationFocusGroup, viewport.height, viewport.width]);
  useEffect(() => {
    const update = () => {
      setViewport(desktopSize());
      api.getState().fitWindowsToViewport();
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [api]);
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
  const bindAgentMain = useCallback((
    windowId: string,
    target?: Extract<PawOsWindowRequest['target'], { kind: 'session' | 'room' }>,
  ) => {
    api.getState().bindAgentMain(windowId, target);
  }, [api]);
  const commitFocusFrame = useCallback((windowId: string, bounds: PawWindowBounds) => {
    setFocusFrameOverrides((current) => ({
      ...current,
      [windowId]: clampFocusBounds(bounds, viewport, focusedRoomId ? { modeBarHeight: 46, ledgerHeight: 0 } : {}),
    }));
  }, [focusedRoomId, viewport]);
  const commitFocusRailFrame = useCallback((windowId: string, bounds: PawWindowBounds) => {
    if (!roomFocusRail) return;
    const localBounds = clampRoomFocusRailBounds(bounds, roomFocusRail);
    setFocusFrameOverrides((current) => ({
      ...current,
      [windowId]: roomFocusRailGlobalFrame(localBounds, roomFocusRail.top),
    }));
  }, [roomFocusRail]);
  return (
    <FeatureDesktopProvider bindAgentMain={bindAgentMain} bindRoomMain={bindRoomMain} openApp={openFeatureApp} openRoute={openFeatureRoute} openWindow={openFeatureWindow}>
      <div className="paw-window-layer" data-overview={overviewOpen || undefined} data-room-focus={focusedRoomId || undefined}>
        {focusedRoomId ? <>
          <div aria-hidden="true" className="paw-room-focus-plane" />
          <header aria-label={`${focusedRoomMain?.title || focusedRoomId} Sol 协作聚焦`} className="paw-room-focus-modebar">
            <span><strong>SOL</strong><b>协作聚焦</b></span>
            <span><i data-status={focusedRoomStatus.key} />{focusedRoomStatus.label} · {focusedRoomNodes.filter((node) => node.target?.kind === 'participant').length} 颗行星窗口</span>
          </header>
        </> : null}
        {keptRoomIds.map((roomId) => <PawRoomProjectionKeeper key={roomId} roomId={roomId} />)}
        {!overviewOpen ? <PawRoomWindowFlowLayer activePulseKeys={flowPulse.packetPulseKeys} focusGroup={collaborationFocusGroup} groups={flowGroups} /> : null}
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
  const width = Math.min(Math.max(280, bounds.width), Math.max(280, rail.trackWidth));
  const height = Math.min(Math.max(210, bounds.height), Math.max(210, rail.height));
  return {
    x: Math.min(Math.max(0, bounds.x), Math.max(0, rail.trackWidth - width)),
    y: Math.min(Math.max(0, bounds.y), Math.max(0, rail.height - height)),
    width,
    height,
  };
}

function PawRoomProjectionKeeper({ roomId }: { roomId: string }) {
  const transport = useControlTransport();
  useRoomLiveSession({
    roomId,
    transport,
    onLoadingChange: () => undefined,
    onSnapshot: () => undefined,
    onMetadata: () => undefined,
    onConnectionRestored: () => undefined,
    onConnectionError: () => undefined,
    onRecoveryState: () => undefined,
    onEvents: (_roomId, events) => pulsePawCompositionForRuntimeEvents('room', events.map((event) => event.eventType)),
  });
  return null;
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
  if (!projection) return { key: 'recovering', label: '正在恢复 Sol' };
  if (projection.needsSnapshot) return { key: 'recovering', label: '正在重新同步' };
  if (turn?.status === 'queued' || turn?.status === 'running') return { key: 'running', label: 'Sol 协作中' };
  if (turn?.status === 'failed') return { key: 'failed', label: '最近一轮失败' };
  if (turn?.status === 'aborted') return { key: 'aborted', label: '最近一轮已停止' };
  return { key: 'synced', label: 'Sol 已同步' };
}

export function PawRoomWindowFlowLayer({ activePulseKeys, focusGroup, groups }: {
  activePulseKeys: ReadonlySet<string>;
  focusGroup: string | null;
  groups: WindowFlowGroup[];
}) {
  if (!groups.length) return null;
  const focusedRoomId = focusGroup?.startsWith('room:') ? focusGroup.slice('room:'.length) : '';
  const focusedGroup = groups.find((group) => group.roomId === focusedRoomId);
  return (
    <>
      <svg aria-hidden="true" className="paw-room-window-flow" height="100%" width="100%">
        {groups.flatMap((group) => group.packets.flatMap((packet, packetIndex) => packet.targetIds.flatMap((targetId, targetIndex) => {
          const source = group.points.get(packet.sourceId);
          const target = group.points.get(targetId);
          if (!source || !target || packet.sourceId === targetId) return [];
          const path = windowFlowPath(source, target, packetIndex + targetIndex);
          const delay = targetIndex * 90;
          const live = activePulseKeys.has(packet.pulseKey);
          return <g data-kind={packet.kind} data-live={live || undefined} key={`${group.roomId}:${packet.id}:${targetId}`}>
            <path className="paw-room-window-flow__base" d={path} />
            {live ? <>
              <path className="paw-room-window-flow__live" d={path} pathLength="1" style={{ animationDelay: `${delay}ms` }} />
              <circle className="paw-room-window-flow__source" cx={source.x} cy={source.y} r="7" style={{ animationDelay: `${delay}ms` }} />
              <circle className="paw-room-window-flow__packet" r="4.5">
                <animateMotion begin={`${delay}ms`} dur="720ms" fill="freeze" path={path} />
              </circle>
              <text className="paw-room-window-flow__label" textAnchor="middle" x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 8}>{windowFlowKindLabel(packet.kind)}</text>
              <circle className="paw-room-window-flow__arrival" cx={target.x} cy={target.y} r="8" style={{ animationDelay: `${delay + 590}ms` }} />
            </> : null}
          </g>;
        })))}
      </svg>
      {focusedGroup?.packets.length ? (
        <Disclosure
          aria-label="Room 流转记录"
          className="paw-room-window-flow-ledger"
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
  kind: 'request' | 'question' | 'answer' | 'result' | 'context' | 'dispatch' | 'approval';
  summary?: string;
  status?: string;
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
      const targetId = kind === 'approval' ? 'root' : stringValue(activity.payload.targetParticipantId) || activity.participantId || '';
      if (!points.has(targetId)) continue;
      const sourceId = stringValue(activity.payload.sourceParticipantId)
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
        status: activity.status,
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
  if (node.minimized || !node.target) return false;
  if (node.target.kind === 'participant' || node.target.kind === 'subagent') return true;
  if (node.target.kind === 'process-terminal' || node.target.kind === 'browser-target') return true;
  if (node.target.kind === 'room') return Boolean(node.target.panel);
  return node.target.kind === 'work-document' || node.target.kind === 'result';
}

export function windowBelongsToFocus(node: PawWindowNode, group: string): boolean {
  if (node.minimized) return false;
  if (satelliteGroup(node.target) === group) return true;
  if (group.startsWith('room:') && node.target?.kind === 'room') {
    return node.target.id === group.slice('room:'.length);
  }
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
  const inset = 10;
  const gap = 10;
  const modeBarHeight = Math.max(0, reserved.modeBarHeight ?? 0);
  const ledgerSpace = nodes.length > 1 && viewport.height >= 420 ? Math.max(0, reserved.ledgerHeight ?? 48) : 0;
  const usableTop = modeBarHeight;
  const usableBottom = Math.max(usableTop, viewport.height - ledgerSpace);
  const usableHeight = usableBottom - usableTop;
  const main = nodes.find((node) => !isCollaborationSatellite(node)) ?? nodes[0]!;
  const satellites = nodes.filter((node) => node.id !== main.id);
  if (!satellites.length) {
    frames.set(main.id, { x: inset, y: usableTop + inset, width: viewport.width - inset * 2, height: usableHeight - inset * 2 });
    return frames;
  }
  if (viewport.width < 720) {
    if (satellites.length >= 5) {
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
    const mainRatio = satellites.length >= 5 ? .49 : .58;
    const mainHeight = satellites.length ? Math.max(210, Math.round(usableHeight * mainRatio)) : usableHeight - inset * 2;
    frames.set(main.id, { x: inset, y: usableTop + inset, width: viewport.width - inset * 2, height: mainHeight });
    if (!satellites.length) return frames;
    const columns = Math.min(2, satellites.length);
    const rows = Math.ceil(satellites.length / columns);
    const auxiliaryTop = usableTop + inset + mainHeight + gap;
    const auxiliaryHeight = Math.max(0, usableBottom - auxiliaryTop - inset);
    const cellWidth = (viewport.width - inset * 2 - gap * (columns - 1)) / columns;
    const cellHeight = (auxiliaryHeight - gap * (rows - 1)) / rows;
    satellites.forEach((node, index) => frames.set(node.id, {
      x: inset + (index % columns) * (cellWidth + gap),
      y: auxiliaryTop + Math.floor(index / columns) * (cellHeight + gap),
      width: cellWidth,
      height: cellHeight,
    }));
    return frames;
  }
  if (viewport.width < 1000) {
    const railWidth = Math.min(300, Math.max(240, viewport.width * .34));
    frames.set(main.id, {
      x: inset,
      y: usableTop + inset,
      width: viewport.width - railWidth - gap - inset * 2,
      height: usableHeight - inset * 2,
    });
    const height = (usableHeight - inset * 2 - gap * (satellites.length - 1)) / satellites.length;
    satellites.forEach((node, index) => frames.set(node.id, {
      x: viewport.width - inset - railWidth,
      y: usableTop + inset + index * (height + gap),
      width: railWidth,
      height,
    }));
    return frames;
  }
  const railWidth = Math.min(320, Math.max(260, viewport.width * .21));
  const mainX = railWidth + gap * 2;
  frames.set(main.id, {
    x: mainX,
    y: usableTop + inset,
    width: Math.max(420, viewport.width - mainX * 2),
    height: Math.max(320, usableHeight - inset * 2),
  });
  const left = satellites.filter((_, index) => index % 2 === 0);
  const right = satellites.filter((_, index) => index % 2 === 1);
  const placeRail = (items: PawWindowNode[], x: number) => {
    if (!items.length) return;
    const height = Math.max(96, (usableHeight - inset * 2 - gap * (items.length - 1)) / items.length);
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
): RoomFocusRailMetrics | null {
  if (viewport.width >= 720 || satellites.length < 5) return null;
  const satelliteFrames = satellites.flatMap((node) => {
    const frame = frames.get(node.id);
    return frame ? [{ id: node.id, frame }] : [];
  });
  if (satelliteFrames.length !== satellites.length) return null;
  const top = Math.min(...satelliteFrames.map(({ frame }) => frame.y));
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
  const width = Math.min(Math.max(280, bounds.width), Math.max(280, viewport.width));
  const height = Math.min(Math.max(210, bounds.height), Math.max(210, bottom - top));
  return {
    x: Math.min(Math.max(0, bounds.x), Math.max(0, viewport.width - width)),
    y: Math.min(Math.max(top, bounds.y), Math.max(top, bottom - height)),
    width,
    height,
  };
}

function windowCenter(bounds: PawWindowBounds): WindowFlowPoint {
  return { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
}

function windowFlowPath(source: WindowFlowPoint, target: WindowFlowPoint, index: number): string {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const length = Math.max(1, Math.hypot(dx, dy));
  const bend = (index % 2 ? -1 : 1) * Math.min(46, length * .11);
  const controlX = (source.x + target.x) / 2 - dy / length * bend;
  const controlY = (source.y + target.y) / 2 + dx / length * bend;
  return `M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`;
}

function windowFlowKindLabel(kind: WindowFlowPacket['kind']): string {
  return ({ request: '需求', question: '问题', answer: '答复', result: '结果', context: '上下文', dispatch: '分派', approval: '审批' } as const)[kind];
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

function PawWindow({ collaborationFocusGroup, flowState, focusFrame, onFocusFrameCommit, overview, overviewFrame, windowId }: {
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
  const openLinkedRoute = (event: ReactMouseEvent<HTMLElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const anchor = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[href]');
    if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return;
    const href = anchor.getAttribute('href') ?? '';
    if (!href.startsWith('#/')) return;
    event.preventDefault();
    openDesktopRoute(api, href.slice(1));
  };
  return (
    <PawWindowFrame
      active={active}
      bounds={node.bounds}
      collaborationRole={collaborationRole}
      deferPointerInteractionUntilFocused={!collaborationFocusGroup && Boolean(satelliteGroup(node.target))}
      flowState={flowState}
      focusFrame={focusFrame}
      frameMode={focusFrame && collaborationRole === 'satellite' ? 'focus-card' : 'window'}
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
      targetKind={node.target?.kind}
      windowChrome={node.target?.kind === 'room' && !node.target.panel ? 'room-workspace' : node.appId === 'agent' ? 'agent-session' : node.appId === 'browser' ? 'browser-tabs' : node.appId === 'files' ? 'files-tools' : node.appId === 'terminal' ? 'terminal-tabs' : undefined}
      windowId={windowId}
      zIndex={zIndex}
    >
      <div className="paw-window-route-surface" onClick={openLinkedRoute}>
        <PawOsAppSurfaceProvider appId={node.appId} height={Math.max(0, focusFrame?.height ?? node.bounds.height)} width={focusFrame?.width ?? node.bounds.width} windowId={windowId}>
          <PawAppProcess appId={node.appId} entityId={node.entityId} initialRoute={node.initialRoute} target={node.target} />
        </PawOsAppSurfaceProvider>
      </div>
    </PawWindowFrame>
  );
}

function openDesktopRoute(api: ReturnType<typeof usePawDesktopApi>, route: string): void {
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

export function PawWindowFrame({ active, appId, bounds, children, collaborationRole, deferPointerInteractionUntilFocused = false, flowState, focusFrame, frameMode = 'window', onBoundsCommit, onClose, onFocus, onMinimize, onOpenFromOverview, onSnap, onToggleMaximize, overview = false, overviewFrame, placement, targetKind, title, windowChrome, windowId, zIndex }: {
  active: boolean;
  appId: PawAppId;
  bounds: PawWindowBounds;
  children: ReactNode;
  collaborationRole?: 'primary' | 'satellite' | 'unrelated' | 'hidden';
  deferPointerInteractionUntilFocused?: boolean;
  flowState?: 'source' | 'arrival';
  focusFrame?: PawWindowBounds;
  frameMode?: 'window' | 'focus-card';
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
  targetKind?: PawOsWindowRequest['target']['kind'];
  title: string;
  windowChrome?: string;
  windowId: string;
  zIndex: number;
}) {
  const shellRef = useRef<HTMLElement>(null);
  const [windowChromeTarget, setWindowChromeTarget] = useState<HTMLElement | null>(null);
  const maximized = placement === 'maximized';
  const identityIconId = targetKind === 'room' ? 'room' : appId;
  const interactionBounds = focusFrame ?? bounds;
  const drag = useWindowDrag(shellRef, interactionBounds, onBoundsCommit, onFocus, focusFrame ? undefined : onSnap, active, deferPointerInteractionUntilFocused);
  const exit = useWindowExit(shellRef);
  const transform = focusFrame
    ? `translate3d(${focusFrame.x}px, ${focusFrame.y}px, 0)`
    : overview && overviewFrame
    ? `translate3d(${overviewFrame.x}px, ${overviewFrame.y}px, 0) scale(${overviewFrame.scale})`
    : `translate3d(${bounds.x}px, ${bounds.y}px, 0)`;
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
    <PawWindowChromeProvider target={windowChromeTarget}>
      <section aria-label={`${title}窗口`} className="paw-window-shell" data-active={active || undefined} data-app={appId} data-collaboration-role={collaborationRole} data-flow-state={flowState} data-focus-layout={focusFrame ? true : undefined} data-frame-mode={frameMode} data-overview={overview || undefined} data-paw-window-id={windowId} data-placement={placement} data-window-target={targetKind} onPointerDown={() => { if (!overview && !active) onFocus(); }} ref={shellRef} style={shellStyle}>
        <div className="paw-window">
          <header className="paw-window-titlebar" data-window-chrome={windowChrome} onDoubleClick={overview || focusFrame ? undefined : onToggleMaximize} onPointerDown={overview ? undefined : drag}>
            {frameMode === 'focus-card' ? null : <div className="paw-traffic-lights" onDoubleClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()}><button aria-label="关闭窗口" data-action="close" onClick={() => exit('close', onClose)} title="关闭" type="button"><X size={9} /></button><button aria-label="最小化窗口" data-action="minimize" onClick={() => exit('minimize', onMinimize)} title="最小化" type="button"><Minus size={9} /></button><button aria-label={maximized ? '还原窗口' : '最大化窗口'} data-action={maximized ? 'restore' : 'maximize'} onClick={onToggleMaximize} title={maximized ? '还原' : '最大化'} type="button">{maximized ? <Minimize2 size={8} /> : <Maximize2 size={8} />}</button></div>}
            <div className="paw-window-title"><PawAppIcon appId={identityIconId} size={16} /><strong>{title}</strong></div>
            {windowChrome ? <div className="paw-window-chrome-slot" onDoubleClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()} ref={setWindowChromeTarget} /> : null}
            {frameMode === 'focus-card' ? <button aria-label={`关闭伙伴窗口：${title}`} className="paw-focus-card-close" onClick={() => exit('close', onClose)} onDoubleClick={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()} title="关闭伙伴窗口" type="button"><X size={13} /></button> : null}
          </header>
          <MemoizedWindowBody>{children}</MemoizedWindowBody>
        </div>
        {overview ? (
          <button aria-label={`打开 ${title}`} className="paw-overview-window-target" onClick={onOpenFromOverview} type="button"><PawAppIcon appId={identityIconId} size={24} /><span>{title}</span></button>
        ) : (
          <PawWindowResizeHandles active={active} bounds={interactionBounds} deferPointerInteractionUntilFocused={deferPointerInteractionUntilFocused} onBoundsCommit={onBoundsCommit} onFocus={onFocus} shellRef={shellRef} />
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

function PawWindowResizeHandles({ active, bounds, deferPointerInteractionUntilFocused, onBoundsCommit, onFocus, shellRef }: {
  active: boolean;
  bounds: PawWindowBounds;
  deferPointerInteractionUntilFocused: boolean;
  onBoundsCommit: (bounds: PawWindowBounds) => void;
  onFocus: () => void;
  shellRef: RefObject<HTMLElement | null>;
}) {
  return pawWindowResizeHandles.map((handle) => (
    <PawWindowResizeHandle
      active={active}
      bounds={bounds}
      deferPointerInteractionUntilFocused={deferPointerInteractionUntilFocused}
      handle={handle}
      key={handle}
      onBoundsCommit={onBoundsCommit}
      onFocus={onFocus}
      shellRef={shellRef}
    />
  ));
}

function PawWindowResizeHandle({ active, bounds, deferPointerInteractionUntilFocused, handle, onBoundsCommit, onFocus, shellRef }: {
  active: boolean;
  bounds: PawWindowBounds;
  deferPointerInteractionUntilFocused: boolean;
  handle: PawWindowResizeHandle;
  onBoundsCommit: (bounds: PawWindowBounds) => void;
  onFocus: () => void;
  shellRef: RefObject<HTMLElement | null>;
}) {
  const resize = useWindowResize(shellRef, bounds, handle, onBoundsCommit, onFocus, active, deferPointerInteractionUntilFocused);
  const horizontal = handle.includes('east') || handle.includes('west');
  const vertical = handle.includes('north') || handle.includes('south');
  const keyShortcuts = [horizontal ? 'ArrowLeft ArrowRight' : '', vertical ? 'ArrowUp ArrowDown' : ''].filter(Boolean).join(' ');
  const resizeFromKeyboard = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const deltaX = event.key === 'ArrowRight' ? 16 : event.key === 'ArrowLeft' ? -16 : 0;
    const deltaY = event.key === 'ArrowDown' ? 16 : event.key === 'ArrowUp' ? -16 : 0;
    if ((!deltaX || !horizontal) && (!deltaY || !vertical)) return;
    event.preventDefault();
    if (!active) onFocus();
    onBoundsCommit(resizeWindowBounds(bounds, handle, deltaX, deltaY));
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

function desktopSize(): { width: number; height: number } {
  if (typeof window === 'undefined') return { width: 1280, height: 800 };
  return { width: window.innerWidth, height: window.innerHeight - 28 };
}

const MemoizedWindowBody = memo(function WindowBody({ children }: { children: ReactNode }) {
  return <div className="paw-window-body">{children}</div>;
});

function useWindowExit(ref: RefObject<HTMLElement | null>) {
  return useCallback((kind: 'close' | 'minimize', finish: () => void) => {
    const surface = ref.current?.querySelector<HTMLElement>('.paw-window');
    if (!surface || typeof surface.animate !== 'function' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      finish();
      return;
    }
    if (surface.dataset.exiting) return;
    surface.dataset.exiting = kind;
    const target = kind === 'minimize'
      ? 'translate3d(0, 34px, 0) scale(.9)'
      : 'translate3d(0, 10px, 0) scale(.97)';
    const animation = surface.animate([
      { opacity: 1, transform: 'translate3d(0, 0, 0) scale(1)' },
      { opacity: 0, transform: target },
    ], {
      duration: kind === 'minimize' ? 180 : 160,
      easing: 'cubic-bezier(.77, 0, .175, 1)',
      fill: 'forwards',
    });
    void animation.finished.then(finish, finish);
  }, [ref]);
}

function useWindowDrag(ref: RefObject<HTMLElement | null>, bounds: PawWindowBounds, commit: (bounds: PawWindowBounds) => void, focus: () => void, snap: ((placement: PawWindowPlacement) => void) | undefined, active: boolean, deferPointerInteractionUntilFocused: boolean) {
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
    const origin = { x: event.clientX, y: event.clientY };
    let next = bounds;
    let frame = 0;
    const render = () => { frame = 0; shell.style.transform = `translate3d(${next.x}px, ${next.y}px, 0)`; };
    const move = (moveEvent: PointerEvent) => {
      next = { ...bounds, x: bounds.x + moveEvent.clientX - origin.x, y: Math.max(0, bounds.y + moveEvent.clientY - origin.y) };
      setSnapPreview(desktopRoot, snapPlacement(moveEvent.clientX, moveEvent.clientY));
      if (!frame) frame = window.requestAnimationFrame(render);
    };
    const finish = (finishEvent: PointerEvent) => {
      if (frame) window.cancelAnimationFrame(frame);
      render();
      delete shell.dataset.interaction;
      setSnapPreview(desktopRoot);
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
      shell.style.transform = `translate3d(${bounds.x}px, ${bounds.y}px, 0)`;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', cancel);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', cancel);
  }, [active, bounds, commit, deferPointerInteractionUntilFocused, focus, ref, snap]);
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

function snapPlacement(clientX: number, clientY: number): PawWindowPlacement | undefined {
  if (clientY <= 14) return 'maximized';
  if (clientX <= 14) return 'left';
  if (clientX >= window.innerWidth - 14) return 'right';
  return undefined;
}

function useWindowResize(ref: RefObject<HTMLElement | null>, bounds: PawWindowBounds, handle: PawWindowResizeHandle, commit: (bounds: PawWindowBounds) => void, focus: () => void, active: boolean, deferPointerInteractionUntilFocused: boolean) {
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
    event.currentTarget.setPointerCapture(event.pointerId);
    shell.dataset.interaction = 'resizing';
    const origin = { x: event.clientX, y: event.clientY };
    let next = bounds;
    let frame = 0;
    const render = () => {
      frame = 0;
      shell.style.width = `${next.width}px`;
      shell.style.height = `${next.height}px`;
      shell.style.transform = `translate3d(${next.x}px, ${next.y}px, 0)`;
    };
    const move = (moveEvent: PointerEvent) => {
      next = resizeWindowBounds(bounds, handle, moveEvent.clientX - origin.x, moveEvent.clientY - origin.y);
      if (!frame) frame = window.requestAnimationFrame(render);
    };
    const finish = () => {
      if (frame) window.cancelAnimationFrame(frame);
      render();
      delete shell.dataset.interaction;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
      commit(next);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
  }, [active, bounds, commit, deferPointerInteractionUntilFocused, focus, handle, ref]);
}

function resizeWindowBounds(bounds: PawWindowBounds, handle: PawWindowResizeHandle, deltaX: number, deltaY: number): PawWindowBounds {
  const next = { ...bounds };
  if (handle.includes('east')) next.width = Math.max(280, bounds.width + deltaX);
  if (handle.includes('south')) next.height = Math.max(210, bounds.height + deltaY);
  if (handle.includes('west')) {
    next.width = Math.max(280, bounds.width - deltaX);
    next.x = bounds.x + bounds.width - next.width;
  }
  if (handle.includes('north')) {
    next.height = Math.max(210, bounds.height - deltaY);
    next.y = bounds.y + bounds.height - next.height;
  }
  return next;
}
