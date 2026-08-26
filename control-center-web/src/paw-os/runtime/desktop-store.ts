import { createStore, type StoreApi } from 'zustand/vanilla';
import type { PawOsWindowTarget } from '@/features/paw-os/model/desktop';
import { pawApp, type PawAppId } from './app-registry';

export type PawWindowBounds = { x: number; y: number; width: number; height: number };
export type PawWindowPlacement = 'maximized' | 'left' | 'right';

/* A window is an App container with a floor, not a free-floating page. Below
   these sizes the titlebar can no longer hold its three verbs beside an App's
   own chrome, so no gesture, layout or fit may produce a smaller frame. */
export const PAW_WINDOW_MIN_WIDTH = 280;
export const PAW_WINDOW_MIN_HEIGHT = 210;

/* Window bounds are `.paw-window-layer` coordinates, and that layer is a real
   chrome box: the menu bar sits above it and the Dock gutter below it
   (`inset: 0 0 76px` inside `.paw-desktop-viewport`, whose own top is
   `--paw-menu-h`). Every owner that fits, snaps, clamps or lays out a window
   resolves this one box — when they disagree, a "fitted" window still lands
   under the Dock where the pointer cannot reach its bottom edge. */
const PAW_MENU_BAR_HEIGHT = 34;
const PAW_DOCK_GUTTER_HEIGHT = 76;
const PAW_WINDOW_AREA_INSET = 8;
const PAW_WINDOW_REACHABLE_GRIP_WIDTH = 120;
const PAW_WINDOW_TITLEBAR_HEIGHT = 40;

/** Usable size of the window layer itself, in layer coordinates. */
export function pawWindowLayerSize(): { width: number; height: number } {
  const width = typeof window === 'undefined' ? 1280 : window.innerWidth;
  const height = typeof window === 'undefined' ? 800 : window.innerHeight;
  return {
    width: Math.max(PAW_WINDOW_MIN_WIDTH, width),
    height: Math.max(PAW_WINDOW_MIN_HEIGHT, height - PAW_MENU_BAR_HEIGHT - PAW_DOCK_GUTTER_HEIGHT),
  };
}

/** The inset rectangle an ordinary desktop window may occupy. */
export function pawWindowArea(): PawWindowBounds {
  const layer = pawWindowLayerSize();
  return {
    x: PAW_WINDOW_AREA_INSET,
    y: PAW_WINDOW_AREA_INSET,
    width: Math.max(PAW_WINDOW_MIN_WIDTH, layer.width - PAW_WINDOW_AREA_INSET * 2),
    height: Math.max(PAW_WINDOW_MIN_HEIGHT, layer.height - PAW_WINDOW_AREA_INSET * 2),
  };
}

/** Clamp one frame so the whole window — not just its titlebar — stays reachable. */
export function fitPawWindowBounds(bounds: PawWindowBounds, area: PawWindowBounds = pawWindowArea()): PawWindowBounds {
  const width = Math.min(area.width, Math.max(Math.min(PAW_WINDOW_MIN_WIDTH, area.width), bounds.width));
  const height = Math.min(area.height, Math.max(Math.min(PAW_WINDOW_MIN_HEIGHT, area.height), bounds.height));
  return {
    x: Math.min(Math.max(area.x, bounds.x), area.x + area.width - width),
    y: Math.min(Math.max(area.y, bounds.y), area.y + area.height - height),
    width,
    height,
  };
}

/** Keep an ordinary window recoverable without forcing its entire frame into
 * the OS canvas. A deliberate drag may leave content partially outside the
 * canvas, but at least one 120px titlebar grip and a full titlebar row remain
 * reachable. Width/height still shrink when the desktop itself gets smaller. */
export function fitReachablePawWindowBounds(
  bounds: PawWindowBounds,
  area: PawWindowBounds = pawWindowArea(),
): PawWindowBounds {
  const width = Math.min(area.width, Math.max(Math.min(PAW_WINDOW_MIN_WIDTH, area.width), bounds.width));
  const height = Math.min(area.height, Math.max(Math.min(PAW_WINDOW_MIN_HEIGHT, area.height), bounds.height));
  const horizontalGrip = Math.min(PAW_WINDOW_REACHABLE_GRIP_WIDTH, width);
  const titlebarGrip = Math.min(PAW_WINDOW_TITLEBAR_HEIGHT, height);
  return {
    x: Math.min(
      Math.max(area.x - width + horizontalGrip, bounds.x),
      area.x + area.width - horizontalGrip,
    ),
    y: Math.min(
      Math.max(area.y, bounds.y),
      area.y + area.height - titlebarGrip,
    ),
    width,
    height,
  };
}
export type PawWindowNode = {
  id: string;
  appId: PawAppId;
  title: string;
  entityId?: string;
  initialRoute?: string;
  target?: PawOsWindowTarget;
  bounds: PawWindowBounds;
  restoreBounds?: PawWindowBounds;
  placement?: PawWindowPlacement;
  minimized: boolean;
};

export type PawDesktopState = {
  windows: Record<string, PawWindowNode>;
  stack: string[];
  activeWindowId: string | null;
  collaborationFocusGroup: string | null;
  collaborationFocusReturnWindowId: string | null;
  launchpadOpen: boolean;
  overviewOpen: boolean;
  openApp: (appId: PawAppId, options?: { background?: boolean; entityId?: string; initialRoute?: string; title?: string; target?: PawOsWindowTarget }) => string;
  bindAgentMain: (
    windowId: string,
    target?: Extract<PawOsWindowTarget, { kind: 'session' | 'room' }>,
  ) => void;
  bindRoomMain: (target: Extract<PawOsWindowTarget, { kind: 'room' }>) => void;
  closeWindow: (windowId: string) => void;
  closeAppWindows: (appId: PawAppId) => void;
  closeAllWindows: () => void;
  minimizeWindow: (windowId: string) => void;
  focusWindow: (windowId: string) => void;
  commitBounds: (windowId: string, bounds: PawWindowBounds) => void;
  fitWindowsToViewport: () => void;
  snapWindow: (windowId: string, placement: PawWindowPlacement) => void;
  toggleMaximize: (windowId: string) => void;
  showWayfinder: () => void;
  setLaunchpadOpen: (open: boolean) => void;
  setOverviewOpen: (open: boolean) => void;
  setCollaborationFocusGroup: (group: string | null) => void;
};

export type PawDesktopStore = StoreApi<PawDesktopState>;
export type PawDesktopSnapshot = Pick<PawDesktopState, 'windows' | 'stack' | 'activeWindowId'>;

export function createPawDesktopStore(initialAppId?: PawAppId | null, initialRoute?: string, snapshot?: PawDesktopSnapshot): PawDesktopStore {
  const store = createStore<PawDesktopState>((set, get) => ({
    windows: snapshot?.windows ?? {},
    stack: snapshot?.stack ?? [],
    activeWindowId: snapshot?.activeWindowId ?? null,
    collaborationFocusGroup: null,
    collaborationFocusReturnWindowId: null,
    launchpadOpen: false,
    overviewOpen: false,
    openApp(appId, options = {}) {
      const windowId = options.entityId ? `${appId}:${options.entityId}` : appId;
      const current = get().windows[windowId];
      if (current) {
        set((state) => {
          const nextFocusGroup = satelliteGroup(options.target);
          return ({
          windows: current.minimized || options.initialRoute !== undefined || options.target !== undefined || options.title !== undefined
            ? {
                ...state.windows,
                [windowId]: {
                  ...current,
                  ...(options.initialRoute !== undefined ? { initialRoute: options.initialRoute } : {}),
                  ...(options.target !== undefined ? { target: options.target } : {}),
                  ...(options.title !== undefined ? { title: options.title } : {}),
                  minimized: false,
                },
              }
            : state.windows,
          activeWindowId: options.background ? state.activeWindowId : windowId,
          stack: options.background
            ? backgroundStack(state.stack, windowId, state.activeWindowId)
            : [...state.stack.filter((id) => id !== windowId), windowId],
          launchpadOpen: false,
          overviewOpen: false,
          collaborationFocusGroup: nextFocusGroup || state.collaborationFocusGroup,
          collaborationFocusReturnWindowId: nextFocusGroup && !state.collaborationFocusGroup
            ? state.activeWindowId
            : state.collaborationFocusReturnWindowId,
          });
        });
        return windowId;
      }
      const currentState = get();
      const participantTarget = options.target?.kind === 'participant' ? options.target : undefined;
      const roomPanelTarget = options.target?.kind === 'room' && options.target.panel ? options.target : undefined;
      const satelliteTarget = participantTarget
        || roomPanelTarget
        || (options.target?.kind === 'subagent' ? options.target : undefined);
      const satelliteIndex = satelliteTarget
        ? Object.values(currentState.windows).filter((window) => (
            satelliteGroup(window.target) === satelliteGroup(satelliteTarget)
          )).length
        : 0;
      const bounds = satelliteTarget
        ? roomParticipantWindowBounds(satelliteIndex)
        : initialWindowBounds(currentState.stack.length);
      const node: PawWindowNode = {
        id: windowId,
        appId,
        title: options.title ?? pawApp(appId).label,
        entityId: options.entityId,
        initialRoute: options.initialRoute,
        target: options.target,
        bounds,
        minimized: false,
      };
      set((state) => {
        const windows = { ...state.windows, [windowId]: node };
        const nextFocusGroup = satelliteGroup(options.target);
        return {
          windows,
          stack: options.background
            ? backgroundStack(state.stack, windowId, state.activeWindowId)
            : [...state.stack, windowId],
          activeWindowId: options.background ? state.activeWindowId : windowId,
          launchpadOpen: false,
          overviewOpen: false,
          collaborationFocusGroup: nextFocusGroup || state.collaborationFocusGroup,
          collaborationFocusReturnWindowId: nextFocusGroup && !state.collaborationFocusGroup
            ? state.activeWindowId
            : state.collaborationFocusReturnWindowId,
        };
      });
      return windowId;
    },
    bindAgentMain(windowId, target) {
      set((state) => {
        const mainWindow = state.windows[windowId];
        if (!mainWindow || mainWindow.appId !== 'agent' || isAgentSatellite(mainWindow.target)) return state;
        const title = target?.title ?? pawApp('agent').label;
        const initialRoute = target
          ? `/agent?${target.kind === 'room' ? 'room' : 'session'}=${encodeURIComponent(target.id)}`
          : '/agent';
        if (mainWindow.target?.kind === target?.kind
          && mainWindow.target?.id === target?.id
          && mainWindow.title === title
          && mainWindow.initialRoute === initialRoute) return state;
        const previousRoomId = mainWindow.target?.kind === 'room' ? mainWindow.target.id : '';
        const leavingFocusedRoom = previousRoomId
          && state.collaborationFocusGroup === `room:${previousRoomId}`
          && (target?.kind !== 'room' || target.id !== previousRoomId);
        const rebound: PawDesktopState = {
          ...state,
          windows: {
            ...state.windows,
            [windowId]: {
              ...mainWindow,
              initialRoute,
              target,
              title,
            },
          },
        };
        const leftGroup = satelliteOwnerGroup(mainWindow.target);
        const orphaned = leftGroup && leftGroup !== satelliteOwnerGroup(target)
          ? orphanedSatelliteIds(rebound, leftGroup, windowId)
          : new Set<string>();
        if (!orphaned.size) {
          return {
            windows: rebound.windows,
            ...(leavingFocusedRoom ? {
              collaborationFocusGroup: null,
              collaborationFocusReturnWindowId: null,
            } : {}),
          };
        }
        /* 主窗离开这个 Room 就是父窗离场，卫星跟着走；但导航不是「关掉桌面
           总览」这个动作，overview 保持用户自己留下的状态。 */
        return {
          ...closeWindowsWhere(rebound, (node) => orphaned.has(node.id)),
          overviewOpen: state.overviewOpen,
        };
      });
    },
    bindRoomMain(target) {
      set((state) => {
        const mainWindow = findRoomMainCandidate(state, target.id);
        if (!mainWindow) return state;
        if (mainWindow.target?.kind === 'room'
          && mainWindow.target.id === target.id
          && mainWindow.title === target.title
          && mainWindow.target.subtitle === target.subtitle) return state;
        return {
          windows: {
            ...state.windows,
            [mainWindow.id]: { ...mainWindow, target, title: target.title },
          },
        };
      });
    },
    closeWindow(windowId) {
      set((state) => {
        const closing = state.windows[windowId];
        const orphaned = closing
          ? orphanedSatelliteIds(state, satelliteOwnerGroup(closing.target), windowId)
          : new Set<string>();
        return closeWindowsWhere(state, (node) => node.id === windowId || orphaned.has(node.id));
      });
    },
    closeAppWindows(appId) {
      set((state) => closeWindowsWhere(state, (node) => node.appId === appId));
    },
    closeAllWindows() {
      set((state) => closeWindowsWhere(state, () => true));
    },
    minimizeWindow(windowId) {
      set((state) => {
        const node = state.windows[windowId];
        if (!node) return state;
        const stack = state.stack.filter((id) => id !== windowId);
        const windows = { ...state.windows, [windowId]: { ...node, minimized: true } };
        const collaborationFocusGroup = state.collaborationFocusGroup
          && Object.values(windows).some((candidate) => !candidate.minimized && satelliteGroup(candidate.target) === state.collaborationFocusGroup)
          ? state.collaborationFocusGroup
          : null;
        return {
          windows,
          stack,
          activeWindowId: stack.at(-1) ?? null,
          collaborationFocusGroup,
          collaborationFocusReturnWindowId: collaborationFocusGroup
            ? state.collaborationFocusReturnWindowId
            : null,
        };
      });
    },
    focusWindow(windowId) {
      const state = get();
      if (state.activeWindowId === windowId) return;
      const node = state.windows[windowId];
      if (!node) return;
      const nextFocusGroup = satelliteGroup(node.target);
      set({
        windows: node.minimized
          ? { ...state.windows, [windowId]: { ...node, minimized: false } }
          : state.windows,
        stack: [...state.stack.filter((id) => id !== windowId), windowId],
        activeWindowId: windowId,
        collaborationFocusGroup: nextFocusGroup || state.collaborationFocusGroup,
        collaborationFocusReturnWindowId: nextFocusGroup && !state.collaborationFocusGroup
          ? state.activeWindowId
          : state.collaborationFocusReturnWindowId,
        overviewOpen: false,
      });
    },
    commitBounds(windowId, bounds) {
      set((state) => {
        const node = state.windows[windowId];
        if (!node || sameBounds(node.bounds, bounds)) return state;
        return { windows: { ...state.windows, [windowId]: { ...node, bounds, restoreBounds: undefined, placement: undefined } } };
      });
    },
    fitWindowsToViewport() {
      const viewport = pawWindowArea();
      set((state) => {
        let changed = false;
        const windows = Object.fromEntries(Object.entries(state.windows).map(([windowId, node]) => {
          const bounds = node.placement
            ? placementBounds(node.placement)
            : fitReachablePawWindowBounds(node.bounds, viewport);
          const restoreBounds = node.restoreBounds
            ? fitReachablePawWindowBounds(node.restoreBounds, viewport)
            : undefined;
          if (sameBounds(bounds, node.bounds)
            && ((!restoreBounds && !node.restoreBounds) || (restoreBounds && node.restoreBounds && sameBounds(restoreBounds, node.restoreBounds)))) {
            return [windowId, node];
          }
          changed = true;
          return [windowId, { ...node, bounds, restoreBounds }];
        }));
        return changed ? { windows } : state;
      });
    },
    snapWindow(windowId, placement) {
      set((state) => {
        const node = state.windows[windowId];
        if (!node) return state;
        const restoreBounds = node.restoreBounds ?? node.bounds;
        return {
          windows: {
            ...state.windows,
            [windowId]: {
              ...node,
              bounds: placementBounds(placement),
              restoreBounds,
              placement,
            },
          },
        };
      });
    },
    toggleMaximize(windowId) {
      set((state) => {
        const node = state.windows[windowId];
        if (!node) return state;
        const maximized = node.placement === 'maximized';
        return {
          windows: {
            ...state.windows,
            [windowId]: maximized
              ? { ...node, bounds: node.restoreBounds ?? node.bounds, restoreBounds: undefined, placement: undefined }
              : { ...node, restoreBounds: node.restoreBounds ?? node.bounds, bounds: placementBounds('maximized'), placement: 'maximized' },
          },
        };
      });
    },
    showWayfinder() {
      set({ activeWindowId: null, launchpadOpen: false, overviewOpen: false });
    },
    setLaunchpadOpen(open) { set({ launchpadOpen: open, overviewOpen: false }); },
    setOverviewOpen(open) {
      set({ overviewOpen: open, launchpadOpen: false });
    },
    setCollaborationFocusGroup(group) {
      set((state) => {
        if (group) {
          return {
            collaborationFocusGroup: group,
            collaborationFocusReturnWindowId: state.collaborationFocusGroup
              ? state.collaborationFocusReturnWindowId
              : state.activeWindowId,
          };
        }
        if (!state.collaborationFocusGroup) {
          return { collaborationFocusGroup: null, collaborationFocusReturnWindowId: null };
        }
        const currentGroup = state.collaborationFocusGroup;
        const main = Object.values(state.windows).find((node) => (
          !node.minimized
          && !satelliteGroup(node.target)
          && (
            (currentGroup.startsWith('room:') && node.target?.kind === 'room' && node.target.id === currentGroup.slice(5))
            || (currentGroup.startsWith('session:') && node.target?.kind === 'session' && node.target.id === currentGroup.slice(8))
          )
        ));
        const returnWindow = state.collaborationFocusReturnWindowId
          ? state.windows[state.collaborationFocusReturnWindowId]
          : undefined;
        const restore = returnWindow && !returnWindow.minimized ? returnWindow : main;
        return {
          collaborationFocusGroup: null,
          collaborationFocusReturnWindowId: null,
          ...(restore ? {
            activeWindowId: restore.id,
            stack: [...state.stack.filter((id) => id !== restore.id), restore.id],
          } : {}),
        };
      });
    },
  }));
  if (initialAppId) store.getState().openApp(initialAppId, { initialRoute });
  store.getState().fitWindowsToViewport();
  return store;
}

function initialWindowBounds(offset: number): PawWindowBounds {
  const viewport = pawWindowArea();
  const inset = Math.min(48, (offset % 5) * 16);
  const width = Math.min(viewport.width, 1280, Math.max(480, viewport.width * 0.82));
  const height = Math.min(viewport.height, 860, Math.max(360, viewport.height * 0.82));
  return fitPawWindowBounds({
    x: viewport.x + (viewport.width - width) / 2 + inset,
    y: viewport.y + (viewport.height - height) / 2 - 12 + inset,
    width,
    height,
  }, viewport);
}

function backgroundStack(stack: string[], windowId: string, activeWindowId: string | null): string[] {
  const next = stack.filter((id) => id !== windowId && id !== activeWindowId);
  next.push(windowId);
  if (activeWindowId) next.push(activeWindowId);
  return next;
}

function closeWindowsWhere(
  state: PawDesktopState,
  shouldClose: (node: PawWindowNode) => boolean,
): PawDesktopState | Partial<PawDesktopState> {
  const closing = new Set(
    Object.values(state.windows).filter(shouldClose).map((node) => node.id),
  );
  if (!closing.size) return state;
  const windows = Object.fromEntries(
    Object.entries(state.windows).filter(([windowId]) => !closing.has(windowId)),
  );
  const stack = state.stack.filter((windowId) => !closing.has(windowId));
  const collaborationFocusGroup = state.collaborationFocusGroup
    && Object.values(windows).some((node) => (
      !node.minimized && satelliteGroup(node.target) === state.collaborationFocusGroup
    ))
    ? state.collaborationFocusGroup
    : null;
  const focusReturnWindowId = collaborationFocusGroup
    && state.collaborationFocusReturnWindowId
    && windows[state.collaborationFocusReturnWindowId]
    ? state.collaborationFocusReturnWindowId
    : null;
  return {
    windows,
    stack,
    activeWindowId: stack.at(-1) ?? null,
    collaborationFocusGroup,
    collaborationFocusReturnWindowId: focusReturnWindowId,
    overviewOpen: false,
  };
}

export function satelliteGroup(target?: PawOsWindowTarget): string {
  if (target?.kind === 'participant') return `room:${target.roomId}`;
  if (target?.kind === 'room' && target.panel) return `room:${target.id}`;
  if (target?.kind === 'subagent') return `session:${target.sessionId}`;
  if ((target?.kind === 'process-terminal' || target?.kind === 'browser-target') && target.roomId) return `room:${target.roomId}`;
  return '';
}

/**
 * 谁是这组卫星的原点：主 Room 窗与主 Session 窗自己就是恒星，卫星（伙伴、
 * Room 面板、subagent）绕着它转，不会再拥有下一层卫星。返回值与
 * `satelliteGroup` 同一套键，所以「父窗」和「它的卫星」永远说同一种话。
 */
function satelliteOwnerGroup(target?: PawOsWindowTarget): string {
  if (target?.kind === 'room' && !target.panel) return `room:${target.id}`;
  if (target?.kind === 'session') return `session:${target.id}`;
  return '';
}

/**
 * 父窗离场后会被留在桌面上的卫星窗。Designer 的合同是「关掉 Room 就顺带
 * 关掉卫星」：恒星没了，行星不该继续飘着。同一个 Room 还开着另一扇主窗时
 * 卫星仍有原点，这时不做级联；无关的 App 窗口从来不在这组键里。
 */
function orphanedSatelliteIds(state: PawDesktopState, group: string, leavingWindowId: string): Set<string> {
  if (!group) return new Set();
  const anotherOwner = Object.values(state.windows).some((node) => (
    node.id !== leavingWindowId && satelliteOwnerGroup(node.target) === group
  ));
  if (anotherOwner) return new Set();
  return new Set(
    Object.values(state.windows)
      .filter((node) => satelliteGroup(node.target) === group)
      .map((node) => node.id),
  );
}

function isAgentSatellite(target?: PawOsWindowTarget): boolean {
  return target?.kind === 'participant'
    || target?.kind === 'subagent'
    || (target?.kind === 'room' && Boolean(target.panel));
}

function findRoomMainCandidate(state: PawDesktopState, roomId: string): PawWindowNode | undefined {
  const candidates = state.stack
    .map((id) => state.windows[id])
    .filter((window): window is PawWindowNode => Boolean(
      window
      && window.appId === 'agent'
      && window.target?.kind !== 'participant'
      && window.target?.kind !== 'subagent'
      && !(window.target?.kind === 'room' && Boolean(window.target.panel)),
    ));
  return candidates.reduce<PawWindowNode | undefined>((best, candidate) => {
    if (!best || roomMainCandidateScore(candidate, roomId, state.activeWindowId) > roomMainCandidateScore(best, roomId, state.activeWindowId)) return candidate;
    return best;
  }, undefined);
}

function roomMainCandidateScore(window: PawWindowNode, roomId: string, activeWindowId: string | null): number {
  if (window.target?.kind === 'room' && window.target.id === roomId && !window.target.panel) return 3;
  if (window.id === activeWindowId) return 2;
  return 1;
}

function roomParticipantWindowBounds(index: number): PawWindowBounds {
  const viewport = pawWindowArea();
  const width = Math.min(viewport.width, 300, Math.max(PAW_WINDOW_MIN_WIDTH, viewport.width * .22));
  const height = Math.min(viewport.height, 240, Math.max(PAW_WINDOW_MIN_HEIGHT, viewport.height * .27));
  const left = viewport.x;
  const center = viewport.x + (viewport.width - width) / 2;
  const right = viewport.x + viewport.width - width;
  const top = viewport.y;
  const middle = viewport.y + (viewport.height - height) / 2;
  const bottom = viewport.y + viewport.height - height;
  // Room admits eight participants. Keep all eight on distinct perimeter
  // slots so the sixth through eighth windows do not cycle back over the
  // first three. Corners stay first to preserve the familiar small-Room
  // composition; edge centers are only occupied as the Room grows.
  const positions = [
    { x: left, y: top },
    { x: right, y: top },
    { x: left, y: bottom },
    { x: right, y: bottom },
    { x: center, y: top },
    { x: center, y: bottom },
    { x: left, y: middle },
    { x: right, y: middle },
  ];
  const position = positions[index % positions.length]!;
  return fitPawWindowBounds({ ...position, width, height }, viewport);
}

function placementBounds(placement: PawWindowPlacement): PawWindowBounds {
  const viewport = pawWindowArea();
  if (placement === 'maximized') return viewport;
  const gap = 6;
  const width = (viewport.width - gap) / 2;
  return {
    x: placement === 'left' ? viewport.x : viewport.x + width + gap,
    y: viewport.y,
    width,
    height: viewport.height,
  };
}

function sameBounds(left: PawWindowBounds, right: PawWindowBounds): boolean {
  return left.x === right.x && left.y === right.y
    && left.width === right.width && left.height === right.height;
}
