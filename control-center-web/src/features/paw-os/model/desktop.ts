import type { PawOsDesktopAppId } from './app-registry';

export type PawOsRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PawOsWindowTarget =
  | { kind: 'work-document'; id: string; title: string; subtitle?: string }
  | { kind: 'project'; id: string; title: string; subtitle?: string }
  | { kind: 'task'; id: string; title: string; subtitle?: string; date: string; project?: string }
  | { kind: 'session'; id: string; title: string; subtitle?: string }
  | { kind: 'room'; id: string; title: string; subtitle?: string; panel?: 'focus' | 'progress' | 'governance' }
  | { kind: 'participant'; id: string; title: string; subtitle?: string; roomId: string; sessionId?: string }
  | { kind: 'subagent'; id: string; title: string; subtitle?: string; sessionId: string }
  | {
    kind: 'process-terminal';
    id: string;
    title: string;
    subtitle?: string;
    sessionId: string;
    roomId?: string;
    participantId?: string;
    toolCallId: string;
    runId?: string;
    terminalId?: string;
    command: string;
    cwd?: string;
    runStatus?: 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'orphaned';
    roomBound?: boolean;
    roomTurnId?: string;
    exitCode?: number;
  }
  | {
    kind: 'browser-target';
    id: string;
    title: string;
    subtitle?: string;
    sessionId: string;
    roomId?: string;
    participantId?: string;
    toolCallId: string;
    targetId: string;
    provisional?: boolean;
    url?: string;
    tabId?: number;
    commandId?: string;
  }
  | { kind: 'package'; id: string; title: string; subtitle?: string; version: string; resourceCount: number }
  | {
    kind: 'result';
    id: string;
    title: string;
    subtitle?: string;
    resultKind: 'html' | 'web' | 'game' | 'music' | 'image' | 'audio' | 'artifact';
    content?: string;
    source?: string;
    mimeType?: string;
  };

export type PawOsDesktopWindow = {
  id: string;
  appId: PawOsDesktopAppId;
  title: string;
  rect: PawOsRect;
  restoreRect: PawOsRect | null;
  minimized: boolean;
  maximized: boolean;
  target?: PawOsWindowTarget;
};

export type PawOsDesktopOverlay = 'launchpad' | 'mission-control' | null;

export type PawOsDesktopState = {
  windows: PawOsDesktopWindow[];
  stack: string[];
  activeWindowId: string | null;
  overlay: PawOsDesktopOverlay;
  surface: { width: number; height: number };
};

export type PawOsDesktopAction =
  | { type: 'open'; window: PawOsDesktopWindow }
  | { type: 'focus'; windowId: string }
  | { type: 'close'; windowId: string }
  | { type: 'minimize'; windowId: string }
  | { type: 'toggleMaximize'; windowId: string }
  | { type: 'move'; windowId: string; rect: PawOsRect }
  | { type: 'resize'; windowId: string; rect: PawOsRect }
  | { type: 'setSurface'; width: number; height: number }
  | { type: 'showOverlay'; overlay: PawOsDesktopOverlay };

const defaultSurface = { width: 1440, height: 788 };
const desktopInset = 14;
const minimumWindowWidth = 420;
const minimumWindowHeight = 280;
const visibleTitleBarWidth = 160;
const titleBarHeight = 42;

export function createPawOsDesktopState(
  partial: Partial<PawOsDesktopState> = {},
): PawOsDesktopState {
  const windows = partial.windows ?? [];
  const knownIds = new Set(windows.map((window) => window.id));
  const stack = [
    ...(partial.stack ?? []).filter((id) => knownIds.has(id)),
    ...windows.map((window) => window.id).filter((id) => !(partial.stack ?? []).includes(id)),
  ];
  return {
    windows,
    stack,
    activeWindowId: resolveActiveWindow(windows, stack, partial.activeWindowId),
    overlay: partial.overlay ?? null,
    surface: partial.surface ?? defaultSurface,
  };
}

export function pawOsDesktopReducer(
  state: PawOsDesktopState,
  action: PawOsDesktopAction,
): PawOsDesktopState {
  switch (action.type) {
    case 'open': {
      const exists = state.windows.some((window) => window.id === action.window.id);
      const windows = exists
        ? state.windows.map((window) => window.id === action.window.id
          ? { ...window, minimized: false }
          : window)
        : [...state.windows, clampWindow(action.window, state.surface, 'move')];
      return {
        ...state,
        windows,
        stack: raiseWindow(state.stack, action.window.id),
        activeWindowId: action.window.id,
        overlay: null,
      };
    }
    case 'focus': {
      if (!state.windows.some((window) => window.id === action.windowId)) return state;
      return {
        ...state,
        windows: state.windows.map((window) => window.id === action.windowId
          ? { ...window, minimized: false }
          : window),
        stack: raiseWindow(state.stack, action.windowId),
        activeWindowId: action.windowId,
        overlay: null,
      };
    }
    case 'close': {
      const windows = state.windows.filter((window) => window.id !== action.windowId);
      const stack = state.stack.filter((id) => id !== action.windowId);
      return {
        ...state,
        windows,
        stack,
        activeWindowId: topVisibleWindowId(windows, stack),
      };
    }
    case 'minimize': {
      const windows = state.windows.map((window) => window.id === action.windowId
        ? { ...window, minimized: true }
        : window);
      return {
        ...state,
        windows,
        activeWindowId: topVisibleWindowId(windows, state.stack),
      };
    }
    case 'toggleMaximize':
      return updateWindow(state, action.windowId, (window) => {
        if (window.maximized && window.restoreRect) {
          return { ...window, rect: window.restoreRect, restoreRect: null, maximized: false };
        }
        return {
          ...window,
          rect: maximizedRect(state.surface),
          restoreRect: window.rect,
          minimized: false,
          maximized: true,
        };
      });
    case 'move':
      return updateWindow(state, action.windowId, (window) => ({
        ...window,
        rect: clampRect(action.rect, state.surface, 'move'),
        restoreRect: null,
        maximized: false,
      }));
    case 'resize':
      return updateWindow(state, action.windowId, (window) => ({
        ...window,
        rect: clampRect(action.rect, state.surface, 'resize'),
        restoreRect: null,
        maximized: false,
      }));
    case 'setSurface': {
      const surface = {
        width: Math.max(320, action.width),
        height: Math.max(320, action.height),
      };
      if (surface.width === state.surface.width && surface.height === state.surface.height) {
        return state;
      }
      return {
        ...state,
        surface,
        windows: state.windows.map((window) => window.maximized
          ? { ...window, rect: maximizedRect(surface) }
          : fitWindowToSurface(window, surface)),
      };
    }
    case 'showOverlay':
      return { ...state, overlay: action.overlay };
  }
}

export function createPawOsWindow(input: {
  appId: PawOsDesktopAppId;
  title: string;
  surface: PawOsDesktopState['surface'];
  sequence: number;
  target?: PawOsWindowTarget;
}): PawOsDesktopWindow {
  const compact = input.surface.width < 760;
  const satellite = Boolean(input.target);
  const width = compact
    ? Math.max(320, input.surface.width - 20)
    : satellite
      ? Math.min(720, input.surface.width - 390)
      : Math.min(1080, input.surface.width - 350);
  const height = compact
    ? Math.max(300, input.surface.height - 28)
    : satellite
      ? Math.min(620, input.surface.height - 112)
      : Math.min(720, input.surface.height - 72);
  const cascade = (input.sequence % 6) * 28;
  const x = compact ? 10 : Math.max(316, input.surface.width - width - 38 + cascade - 56);
  const y = compact ? 10 : Math.max(22, (input.surface.height - height) / 2 + cascade - 42);
  return {
    id: input.target
      ? `${input.appId}:${input.target.kind}:${encodeURIComponent(input.target.id)}`
      : `${input.appId}:primary`,
    appId: input.appId,
    title: input.title,
    rect: clampRect({ x, y, width, height }, input.surface, 'move'),
    restoreRect: null,
    minimized: false,
    maximized: compact,
    ...(input.target ? { target: input.target } : {}),
  };
}

export function windowZIndex(state: PawOsDesktopState, windowId: string): number {
  const index = state.stack.indexOf(windowId);
  return index < 0 ? 1 : index + 1;
}

function updateWindow(
  state: PawOsDesktopState,
  windowId: string,
  update: (window: PawOsDesktopWindow) => PawOsDesktopWindow,
): PawOsDesktopState {
  if (!state.windows.some((window) => window.id === windowId)) return state;
  return {
    ...state,
    windows: state.windows.map((window) => window.id === windowId ? update(window) : window),
  };
}

function clampWindow(
  window: PawOsDesktopWindow,
  surface: PawOsDesktopState['surface'],
  mode: 'move' | 'resize',
): PawOsDesktopWindow {
  return { ...window, rect: clampRect(window.rect, surface, mode) };
}

function fitWindowToSurface(
  window: PawOsDesktopWindow,
  surface: PawOsDesktopState['surface'],
): PawOsDesktopWindow {
  const inset = 10;
  const width = Math.min(window.rect.width, Math.max(320, surface.width - inset * 2));
  const height = Math.min(window.rect.height, Math.max(240, surface.height - inset * 2));
  return {
    ...window,
    rect: {
      x: Math.min(Math.max(inset, window.rect.x), Math.max(inset, surface.width - width - inset)),
      y: Math.min(Math.max(inset, window.rect.y), Math.max(inset, surface.height - height - inset)),
      width,
      height,
    },
  };
}

function clampRect(
  rect: PawOsRect,
  surface: PawOsDesktopState['surface'],
  mode: 'move' | 'resize',
): PawOsRect {
  const responsiveMinimumWidth = Math.min(minimumWindowWidth, Math.max(320, surface.width - 20));
  const responsiveMinimumHeight = Math.min(minimumWindowHeight, Math.max(240, surface.height - 20));
  const width = mode === 'resize' ? Math.max(responsiveMinimumWidth, rect.width) : rect.width;
  const height = mode === 'resize' ? Math.max(responsiveMinimumHeight, rect.height) : rect.height;
  return {
    x: Math.min(
      surface.width - visibleTitleBarWidth,
      Math.max(-(width - visibleTitleBarWidth), rect.x),
    ),
    y: Math.min(surface.height - titleBarHeight, Math.max(0, rect.y)),
    width,
    height,
  };
}

function maximizedRect(surface: PawOsDesktopState['surface']): PawOsRect {
  return {
    x: desktopInset,
    y: desktopInset,
    width: Math.max(minimumWindowWidth, surface.width - desktopInset * 2),
    height: Math.max(minimumWindowHeight, surface.height - desktopInset * 2),
  };
}

function raiseWindow(stack: string[], windowId: string): string[] {
  return [...stack.filter((id) => id !== windowId), windowId];
}

function topVisibleWindowId(windows: PawOsDesktopWindow[], stack: string[]): string | null {
  const visible = new Set(windows.filter((window) => !window.minimized).map((window) => window.id));
  return [...stack].reverse().find((id) => visible.has(id)) ?? null;
}

function resolveActiveWindow(
  windows: PawOsDesktopWindow[],
  stack: string[],
  requested: string | null | undefined,
): string | null {
  if (requested && windows.some((window) => window.id === requested && !window.minimized)) {
    return requested;
  }
  return topVisibleWindowId(windows, stack);
}
