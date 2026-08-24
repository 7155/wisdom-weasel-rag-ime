import {
  Activity,
  ArrowRight,
  Bell,
  Box,
  Check,
  ChevronRight,
  CircleHelp,
  Compass,
  CornerDownLeft,
  Database,
  FileText,
  Flag,
  GitCommitHorizontal,
  Inbox,
  Keyboard,
  LocateFixed,
  Map as MapIcon,
  MessageSquareText,
  PanelsTopLeft,
  Rocket,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Undo2,
  Users,
  Zap,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from 'react';
import {
  TransformComponent,
  TransformWrapper,
  type ReactZoomPanPinchRef,
} from 'react-zoom-pan-pinch';
import { usePawOsDesktop } from '@/features/paw-os/surface-context';
import { createRoomIslandGeometry } from './island-geometry';
import {
  deliveryDocumentLabel,
  deliveryStageLabel,
  projectFieldDocumentContracts,
  projectFieldDocumentDetail,
  type ProjectDocumentContracts,
  type ProjectDocumentDetail,
  type ProjectDocumentEntry,
} from './project-documents';
import { projectFieldZoomProjection } from './semantic-zoom';
import {
  projectFieldProjects,
  roomPhaseOrder,
  type ProjectFieldProject,
  type ProjectRoom,
  type ProjectRoomArea,
  type ProjectRoomAreaState,
  type ProjectRoomPhase,
  type ProjectRoomSource,
  type ProjectWayfinderProjection,
  type ProjectWayfinderRoom,
} from './prototype-data';
import './project-field.css';

type ProjectViewState = {
  focusedRoomId: string | null;
};

type FieldCameraTarget = {
  centerX: number;
  centerY: number;
  scale: number;
};

type RouteProposal = {
  projectId: string;
  query: string;
  roomId: string;
};

type UndoRoute = {
  projectId: string;
  roomId: string;
  previousFocus: string | null;
  previousMessage?: string;
  query: string;
};

// The reconstructed project currently reaches x=2100. Keep the canvas and its
// reset bounds large enough to contain the real graph instead of relying on
// overflow from an undersized 1900px world.
const WORLD_WIDTH = 2320;
const WORLD_HEIGHT = 980;
const PROJECT_ORIGIN = { x: 210, y: 520 } as const;
const PROJECT_DESTINATION = { x: 1690, y: 560 } as const;
const WAYFINDER_OVERVIEW_BOUNDS = {
  left: 60,
  right: 2240,
  top: 38,
  bottom: 930,
} as const;
const MIN_READABLE_OVERVIEW_SCALE = 0.68;
const WAYFINDER_DESTINATION_CAMERA_OFFSET_Y = 10;
const COMPACT_VIEWPORT_MAX_WIDTH = 540;
const COMPACT_LANDMARK_WIDTH = 196;
const COMPACT_LANDMARK_EDGE_INSET = 12;
// The camera contract changed with the legibility pass.  A versioned key keeps
// an old, zoomed-out overview from overriding the intended current-voyage
// first impression after the prototype refreshes.
const VIEW_STORAGE_KEY = 'rag-ime-project-field-prototype-view-v4';

export function projectFieldInitialCamera(project: ProjectFieldProject): FieldCameraTarget {
  const savedCamera = project.routeCamera;
  const currentRoom = project.wayfinder
    ? project.rooms.find((room) => room.id === project.wayfinder?.currentRoomId)
    : null;

  if (currentRoom) {
    return {
      centerX: (currentRoom.x + PROJECT_DESTINATION.x) / 2,
      centerY: (currentRoom.y + PROJECT_DESTINATION.y) / 2 + WAYFINDER_DESTINATION_CAMERA_OFFSET_Y,
      scale: savedCamera.scale,
    };
  }

  return {
    centerX: WORLD_WIDTH / 2 - savedCamera.x / savedCamera.scale,
    centerY: WORLD_HEIGHT / 2 - savedCamera.y / savedCamera.scale,
    scale: savedCamera.scale,
  };
}

export function projectFieldCameraCenterXForViewport(
  project: ProjectFieldProject,
  camera: FieldCameraTarget,
  viewportWidth: number,
  scale: number,
): number {
  if (viewportWidth > COMPACT_VIEWPORT_MAX_WIDTH || scale <= 0 || !project.wayfinder) {
    return camera.centerX;
  }

  const currentRoom = project.rooms.find((room) => room.id === project.wayfinder?.currentRoomId);
  if (!currentRoom) return camera.centerX;

  const currentRoomScreenCenter = viewportWidth / 2 + (currentRoom.x - camera.centerX) * scale;
  const rightmostReadableCenter = viewportWidth
    - COMPACT_LANDMARK_EDGE_INSET
    - COMPACT_LANDMARK_WIDTH / 2;
  if (currentRoomScreenCenter <= rightmostReadableCenter) return camera.centerX;

  return camera.centerX + (currentRoomScreenCenter - rightmostReadableCenter) / scale;
}

export function projectFieldText(value: string): string {
  return value
    .replaceAll('Personal Agent Workbench', '个人助手工作台')
    .replaceAll('Agent Engineering Lab', 'AI 工程实验室')
    .replaceAll('可持续交付的个人 Agent 工作台', '可持续交付的个人助手工作台')
    .replaceAll('Room 导航与项目图谱', '协作导航与项目图谱')
    .replaceAll('Room 协作交付', '多人协作交付')
    .replaceAll('Agent 长任务连续性', '长期任务连续性')
    .replaceAll('当前 Room', '当前协作目标')
    .replace(/\bContext Provider\b\s*/gi, '上下文服务')
    .replace(/\bRuntime\b\s*/gi, '运行环境')
    .replace(/\bProvider\b\s*/gi, '模型服务')
    .replace(/\bSession\b\s*/gi, '对话')
    .replace(/\bRoom\b\s*/gi, '协作目标')
    .replace(/\bAgent\b\s*/gi, '伙伴')
    .replace(/([\p{Script=Han}])\s+(?=[\p{Script=Han}])/gu, '$1');
}

function initialProjectStates(): Record<string, ProjectViewState> {
  return Object.fromEntries(projectFieldProjects.map((project) => [project.id, {
    focusedRoomId: null,
  }]));
}

function restoreProjectStates(): Record<string, ProjectViewState> {
  const defaults = initialProjectStates();
  if (typeof window === 'undefined') return defaults;
  try {
    const raw = window.localStorage.getItem(VIEW_STORAGE_KEY);
    if (!raw) return defaults;
    const restored = JSON.parse(raw) as Record<string, Partial<ProjectViewState>>;
    return Object.fromEntries(projectFieldProjects.map((project) => {
      const candidate = restored[project.id];
      const validFocus = project.rooms.some((room) => room.id === candidate?.focusedRoomId)
        ? candidate?.focusedRoomId ?? null
        : null;
      return [project.id, {
        focusedRoomId: validFocus,
      } satisfies ProjectViewState];
    }));
  } catch {
    return defaults;
  }
}

function findProject(projectId: string): ProjectFieldProject {
  return projectFieldProjects.find((project) => project.id === projectId) ?? projectFieldProjects[0];
}

function scoreRoom(query: string, room: ProjectRoom): number {
  const normalized = query.trim().toLocaleLowerCase('zh-CN');
  if (!normalized) return 0;
  const terms = [
    room.title,
    room.goal,
    ...room.keywords,
    ...room.areas.flatMap((area) => [area.title, area.note]),
  ].map((value) => value.toLocaleLowerCase('zh-CN'));
  let score = terms.reduce((total, value, index) => {
    if (!value.includes(normalized)) return total;
    return total + (index === 0 ? 10 : index === 1 ? 6 : 4);
  }, 0);
  for (const character of [...normalized].filter((value) => value.trim())) {
    if (terms.some((value) => value.includes(character))) score += 0.25;
  }
  return score;
}

function routeRoom(project: ProjectFieldProject, query: string): ProjectRoom {
  const scored = project.rooms
    .map((room) => ({ room, score: scoreRoom(query, room) }))
    .sort((left, right) => right.score - left.score);
  if ((scored[0]?.score ?? 0) >= 1) return scored[0].room;
  return project.rooms.find((room) => room.id === project.defaultRoomId) ?? project.rooms[0];
}

function edgePath(from: Pick<ProjectRoom, 'x' | 'y'>, to: Pick<ProjectRoom, 'x' | 'y'>): string {
  const bend = Math.max(42, Math.abs(to.x - from.x) * 0.42);
  const direction = to.x >= from.x ? 1 : -1;
  return `M ${from.x} ${from.y} C ${from.x + bend * direction} ${from.y}, ${to.x - bend * direction} ${to.y}, ${to.x} ${to.y}`;
}

function courseDistances(project: ProjectFieldProject): Map<string, number> {
  const distances = new Map<string, number>([[project.defaultRoomId, 0]]);
  const queue = [project.defaultRoomId];
  while (queue.length > 0) {
    const roomId = queue.shift();
    if (!roomId) continue;
    const distance = distances.get(roomId) ?? 0;
    for (const edge of project.edges) {
      if (edge.kind !== 'course') continue;
      const neighbor = edge.from === roomId ? edge.to : edge.to === roomId ? edge.from : null;
      if (!neighbor || distances.has(neighbor)) continue;
      distances.set(neighbor, distance + 1);
      queue.push(neighbor);
    }
  }
  return distances;
}

function eventPoint(event: TouchEvent | MouseEvent): { x: number; y: number } | null {
  if ('changedTouches' in event) {
    const touch = event.changedTouches[0];
    return touch ? { x: touch.clientX, y: touch.clientY } : null;
  }
  return { x: event.clientX, y: event.clientY };
}

export function projectFieldShouldReduceMotion(): boolean {
  if (typeof document !== 'undefined') {
    const applicationPreference = document.documentElement.dataset.reduceMotion;
    if (applicationPreference === 'true') return true;
    if (applicationPreference === 'false') return false;
  }
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false;
}

export function ProjectFieldFeature() {
  const pawOsDesktop = usePawOsDesktop();
  const [activeProjectId, setActiveProjectId] = useState(projectFieldProjects[0].id);
  const [projectStates, setProjectStates] = useState(restoreProjectStates);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [navigatorQuery, setNavigatorQuery] = useState('');
  const [routeProposal, setRouteProposal] = useState<RouteProposal | null>(null);
  const [pendingRequirement, setPendingRequirement] = useState<string | null>(null);
  const [attentionOpen, setAttentionOpen] = useState(false);
  const [documentsOpen, setDocumentsOpen] = useState(false);
  const [selectedDocumentRef, setSelectedDocumentRef] = useState<string | null>(null);
  const [roomMessages, setRoomMessages] = useState<Record<string, Record<string, string>>>({});
  const [undoRoute, setUndoRoute] = useState<UndoRoute | null>(null);
  const [liveMessage, setLiveMessage] = useState('');
  const [cameraRequest, setCameraRequest] = useState(0);
  const [transformReady, setTransformReady] = useState(false);
  const [viewportInteracted, setViewportInteracted] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const navigatorInputRef = useRef<HTMLInputElement>(null);
  const focusedWorkspaceRef = useRef<HTMLElement>(null);
  const documentsPanelRef = useRef<HTMLElement>(null);
  const documentsToggleRef = useRef<HTMLButtonElement>(null);
  const documentsReturnFocusRef = useRef<HTMLElement | null>(null);
  const previousFocusedRoomRef = useRef<string | null>(null);
  const transformRef = useRef<ReactZoomPanPinchRef | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const scaleOutputRef = useRef<HTMLSpanElement>(null);
  const panStartRef = useRef<{ x: number; y: number } | null>(null);
  const didPanRef = useRef(false);

  const project = findProject(activeProjectId);
  const projectState = projectStates[project.id] ?? initialProjectStates()[project.id];
  const focusedRoom = project.rooms.find((room) => room.id === projectState.focusedRoomId) ?? null;
  const wayfinderRooms = useMemo(
    () => new Map(project.wayfinder?.rooms.map((room) => [room.roomId, room]) ?? []),
    [project.wayfinder],
  );
  const orderedMapRooms = useMemo(() => project.rooms
    .filter((room) => wayfinderRooms.get(room.id)?.topologyRole !== 'release-lane')
    .sort((left, right) => {
      const leftWayfinder = wayfinderRooms.get(left.id);
      const rightWayfinder = wayfinderRooms.get(right.id);
      return (leftWayfinder?.emergedAt ?? '').localeCompare(rightWayfinder?.emergedAt ?? '')
        || left.y - right.y;
    }), [project.rooms, wayfinderRooms]);
  const releaseLaneRoom = project.rooms.find(
    (room) => wayfinderRooms.get(room.id)?.topologyRole === 'release-lane',
  ) ?? null;
  const activeRelationIds = useMemo(() => {
    if (!focusedRoom) return new Set<string>();
    return new Set(project.edges
      .filter((edge) => edge.from === focusedRoom.id || edge.to === focusedRoom.id)
      .flatMap((edge) => [edge.from, edge.to]));
  }, [focusedRoom, project.edges]);
  const routeDistances = useMemo(() => courseDistances(project), [project]);
  const documentContracts = useMemo(() => projectFieldDocumentContracts(project), [project]);
  const documentDetail = useMemo(
    () => (selectedDocumentRef ? projectFieldDocumentDetail(project, selectedDocumentRef) : null),
    [project, selectedDocumentRef],
  );
  const currentRoomDocumentRef = project.wayfinder?.rooms
    .find((room) => room.roomId === project.wayfinder?.currentRoomId)?.documentRef ?? null;

  const roomsWithEffectivePhase = useMemo(() => project.rooms.map((room) => ({
    room,
    phase: room.phase,
  })), [project.rooms]);
  const attentionRooms = roomsWithEffectivePhase
    .filter(({ phase }) => phase === 'attention')
    .sort((left, right) => roomPhaseOrder(left.phase) - roomPhaseOrder(right.phase));

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];
    return project.rooms
      .map((room) => ({ room, score: scoreRoom(searchQuery, room) }))
      .filter(({ score }) => score > 0)
      .sort((left, right) => right.score - left.score)
      .map(({ room }) => room);
  }, [project.rooms, searchQuery]);

  const camera = useMemo<FieldCameraTarget>(() => {
    // Focusing a result opens its reading surface above the map. Keeping the
    // map in place makes Escape a true return to the same visual context and
    // avoids a second, competing camera animation on compact screens.
    return projectFieldInitialCamera(project);
  }, [focusedRoom, project.routeCamera]);

  const updateScaleOutput = useCallback((scale: number) => {
    const percentage = `${Math.round(scale * 100)}%`;
    const scaleOutput = scaleOutputRef.current;
    if (scaleOutput && scaleOutput.textContent !== percentage) scaleOutput.textContent = percentage;
    if (viewportRef.current) {
      const projection = projectFieldZoomProjection(scale);
      if (viewportRef.current.dataset.zoom !== projection.level) {
        viewportRef.current.dataset.zoom = projection.level;
      }
      viewportRef.current.style.setProperty(
        '--project-field-counter-scale',
        projection.counterScale.toFixed(3),
      );
    }
  }, []);

  const moveCamera = useCallback((ref: ReactZoomPanPinchRef, animate: boolean) => {
    const wrapper = ref.instance.wrapperComponent;
    if (!wrapper) return;
    const overviewHeight = WAYFINDER_OVERVIEW_BOUNDS.bottom - WAYFINDER_OVERVIEW_BOUNDS.top;
    const overviewWidth = WAYFINDER_OVERVIEW_BOUNDS.right - WAYFINDER_OVERVIEW_BOUNDS.left;
    const overviewBottomInset = project.wayfinder && !focusedRoom ? 72 : 0;
    const availableHeight = Math.max(1, wrapper.clientHeight - overviewBottomInset);
    const scale = project.wayfinder && !focusedRoom
      ? Math.min(
          camera.scale,
          Math.max(MIN_READABLE_OVERVIEW_SCALE, (wrapper.clientWidth - 28) / overviewWidth),
          Math.max(MIN_READABLE_OVERVIEW_SCALE, availableHeight / overviewHeight),
        )
      : camera.scale;
    const centerX = projectFieldCameraCenterXForViewport(
      project,
      camera,
      wrapper.clientWidth,
      scale,
    );
    const positionX = wrapper.clientWidth / 2 - centerX * scale;
    const positionY = availableHeight / 2 - camera.centerY * scale;
    ref.setTransform(
      positionX,
      positionY,
      scale,
      animate && !projectFieldShouldReduceMotion() ? 240 : 0,
      'easeOutCubic',
    );
    updateScaleOutput(scale);
  }, [camera, focusedRoom, project.wayfinder, updateScaleOutput]);

  const markViewportInteracted = useCallback(() => {
    setViewportInteracted(true);
  }, []);

  const zoomViewport = useCallback((direction: 'in' | 'out') => {
    const ref = transformRef.current;
    if (!ref) return;
    markViewportInteracted();
    const duration = projectFieldShouldReduceMotion() ? 0 : 260;
    if (direction === 'in') ref.zoomIn(0.12, duration, 'easeOutCubic');
    else ref.zoomOut(0.12, duration, 'easeOutCubic');
    window.setTimeout(() => updateScaleOutput(ref.state.scale), duration + 20);
  }, [markViewportInteracted, updateScaleOutput]);

  const resetViewport = useCallback(() => {
    setCameraRequest((request) => request + 1);
    setViewportInteracted(false);
  }, []);

  const openDocuments = useCallback((ref?: string | null) => {
    documentsReturnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    setSelectedDocumentRef(ref ?? currentRoomDocumentRef);
    setDocumentsOpen(true);
    setSearchOpen(false);
    setSearchQuery('');
    setAttentionOpen(false);
    setRouteProposal(null);
  }, [currentRoomDocumentRef]);

  const closeDocuments = useCallback((restoreFocus = true) => {
    setDocumentsOpen(false);
    const returnFocus = documentsReturnFocusRef.current;
    documentsReturnFocusRef.current = null;
    if (!restoreFocus) return;
    window.setTimeout(() => {
      const target = returnFocus && returnFocus.isConnected
        ? returnFocus
        : documentsToggleRef.current;
      target?.focus({ preventScroll: true });
    }, 0);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(projectStates));
  }, [projectStates]);

  useEffect(() => {
    if (!transformRef.current) return;
    moveCamera(transformRef.current, true);
  }, [activeProjectId, cameraRequest, moveCamera]);

  useEffect(() => {
    const ref = transformRef.current;
    const wrapper = ref?.instance.wrapperComponent;
    if (!transformReady || !ref || !wrapper || typeof ResizeObserver === 'undefined') return undefined;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => moveCamera(ref, false));
    });
    observer.observe(wrapper);
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [moveCamera, transformReady]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase('en-US') === 'k') {
        event.preventDefault();
        setSearchOpen(true);
        window.requestAnimationFrame(() => searchInputRef.current?.focus());
        return;
      }
      if (event.key !== 'Escape') return;
      if (documentsOpen) {
        closeDocuments();
      } else if (routeProposal) {
        setRouteProposal(null);
      } else if (searchOpen) {
        setSearchOpen(false);
        setSearchQuery('');
        searchInputRef.current?.blur();
      } else if (searchQuery) {
        setSearchQuery('');
      } else if (attentionOpen) {
        setAttentionOpen(false);
      } else if (focusedRoom) {
        setProjectStates((current) => ({
          ...current,
          [project.id]: { ...current[project.id], focusedRoomId: null },
        }));
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [attentionOpen, closeDocuments, documentsOpen, focusedRoom, project.id, routeProposal, searchOpen, searchQuery]);

  useEffect(() => {
    if (!documentsOpen) return;
    window.setTimeout(() => documentsPanelRef.current?.focus({ preventScroll: true }), 0);
  }, [documentsOpen]);

  useEffect(() => {
    const previous = previousFocusedRoomRef.current;
    previousFocusedRoomRef.current = focusedRoom?.id ?? null;
    if (focusedRoom && previous !== focusedRoom.id) {
      window.setTimeout(() => focusedWorkspaceRef.current?.focus({ preventScroll: true }), 0);
    }
    if (!focusedRoom && previous) {
      const escaped = typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
        ? CSS.escape(previous)
        : previous.replace(/[^a-zA-Z0-9_-]/g, '');
      // Escape is a keyboard navigation command, so return focus as soon as
      // React restores the map card instead of waiting for decorative motion.
      window.setTimeout(() => document.querySelector<HTMLButtonElement>(`[data-room-id="${escaped}"]`)?.focus({ preventScroll: true }), 0);
    }
  }, [focusedRoom]);

  const updateProjectState = useCallback((updater: (state: ProjectViewState) => ProjectViewState) => {
    setProjectStates((current) => ({
      ...current,
      [project.id]: updater(current[project.id] ?? initialProjectStates()[project.id]),
    }));
  }, [project.id]);

  const focusRoom = useCallback((roomId: string) => {
    updateProjectState((state) => ({ ...state, focusedRoomId: roomId }));
    setSearchOpen(false);
    setSearchQuery('');
    setRouteProposal(null);
    setAttentionOpen(false);
    closeDocuments(false);
  }, [closeDocuments, updateProjectState]);

  const leaveRoomFocus = useCallback(() => {
    updateProjectState((state) => ({ ...state, focusedRoomId: null }));
  }, [updateProjectState]);

  const switchProject = (projectId: string) => {
    setActiveProjectId(projectId);
    setSearchOpen(false);
    setSearchQuery('');
    setRouteProposal(null);
    setAttentionOpen(false);
    setDocumentsOpen(false);
    setSelectedDocumentRef(null);
    setUndoRoute(null);
    setPendingRequirement(null);
    setViewportInteracted(false);
  };

  const submitNavigator = (event: FormEvent) => {
    event.preventDefault();
    const query = navigatorQuery.trim();
    if (!query) return;
    const room = routeRoom(project, query);
    setRouteProposal({ projectId: project.id, query, roomId: room.id });
  };

  const acceptRoute = () => {
    if (!routeProposal || routeProposal.projectId !== project.id) return;
    const acceptedRoomTitle = project.rooms.find((room) => room.id === routeProposal.roomId)?.title ?? '这个目标';
    const previousMessage = roomMessages[project.id]?.[routeProposal.roomId];
    setUndoRoute({
      projectId: project.id,
      roomId: routeProposal.roomId,
      previousFocus: projectState.focusedRoomId,
      previousMessage,
      query: routeProposal.query,
    });
    setRoomMessages((current) => ({
      ...current,
      [project.id]: { ...current[project.id], [routeProposal.roomId]: routeProposal.query },
    }));
    focusRoom(routeProposal.roomId);
    setNavigatorQuery('');
    setLiveMessage(`已在预览中归入「${projectFieldText(acceptedRoomTitle)}」，可撤销。`);
  };

  const keepAsPendingRequirement = () => {
    if (!routeProposal) return;
    setPendingRequirement(routeProposal.query);
    setNavigatorQuery('');
    setRouteProposal(null);
    setLiveMessage('已在预览中保留为待整理目标。');
  };

  const undoAcceptedRoute = () => {
    if (!undoRoute) return;
    setRoomMessages((current) => {
      const projectMessages = { ...current[undoRoute.projectId] };
      if (undoRoute.previousMessage === undefined) delete projectMessages[undoRoute.roomId];
      else projectMessages[undoRoute.roomId] = undoRoute.previousMessage;
      return { ...current, [undoRoute.projectId]: projectMessages };
    });
    if (undoRoute.projectId === project.id) {
      updateProjectState((state) => ({ ...state, focusedRoomId: undoRoute.previousFocus }));
      setNavigatorQuery(undoRoute.query);
    }
    setUndoRoute(null);
    setLiveMessage('已撤销这次预览归属。');
  };

  const proposalRoom = routeProposal?.projectId === project.id
    ? project.rooms.find((room) => room.id === routeProposal.roomId) ?? null
    : null;

  const openProjectWorkbench = pawOsDesktop ? () => pawOsDesktop.openWindow({
    appId: 'project-workbench',
    target: {
      kind: 'project',
      id: project.id,
      title: projectFieldText(project.compactTitle ?? project.name),
      subtitle: projectFieldText(project.heading),
    },
  }) : undefined;

  const openWorkbenchFromProposal = openProjectWorkbench ? () => {
    openProjectWorkbench();
    setRouteProposal(null);
    setLiveMessage('已打开项目工作台窗口，可在那里真实安排任务。');
  } : undefined;

  return (
    <main className="project-field" data-route-id="project-field">
      <h1 className="project-field__sr-only">{projectFieldText(project.compactTitle ?? project.name)} 项目场</h1>
      <ProjectRail
        activeProjectId={project.id}
        attentionCount={attentionRooms.length}
        onSwitchProject={switchProject}
      />

      <section className="project-field__workspace" aria-label={`${projectFieldText(project.compactTitle ?? project.name)} 项目场`}>
        <FieldHeader
          attentionCount={attentionRooms.length}
          onAttention={() => setAttentionOpen((open) => !open)}
          onClearSearch={() => {
            setSearchOpen(false);
            setSearchQuery('');
          }}
          onDismissSearch={() => {
            setSearchOpen(false);
            setSearchQuery('');
          }}
          onFocusSearch={() => setSearchOpen(true)}
          onOpenSearch={() => {
            setSearchOpen(true);
            window.requestAnimationFrame(() => searchInputRef.current?.focus());
          }}
          onOpenProject={openProjectWorkbench}
          documentsOpen={documentsOpen}
          documentsToggleRef={documentsToggleRef}
          onOpenDocuments={documentContracts ? () => {
            if (documentsOpen) closeDocuments();
            else openDocuments();
          } : undefined}
          onSearch={setSearchQuery}
          onSelectRoom={focusRoom}
          project={project}
          searchInputRef={searchInputRef}
          searchOpen={searchOpen}
          searchQuery={searchQuery}
          searchResults={searchResults}
        />

        <div
          className="project-field__viewport"
          data-zoom="mid"
          data-focused={focusedRoom ? true : undefined}
          data-mode={focusedRoom ? 'focus' : 'route'}
          data-view="route"
          ref={viewportRef}
          onClick={(event) => {
            if (didPanRef.current) return;
            if (!focusedRoom) return;
            const target = event.target;
            if (!(target instanceof Element) || !target.closest('button, input, textarea, .room-focus, .project-documents')) {
              leaveRoomFocus();
            }
          }}
        >
          <TransformWrapper
            centerOnInit={false}
            centerZoomedOut={false}
            doubleClick={{ disabled: true }}
            initialScale={camera.scale}
            limitToBounds={false}
            maxScale={1.35}
            minScale={MIN_READABLE_OVERVIEW_SCALE}
            onInit={(ref) => {
              transformRef.current = ref;
              moveCamera(ref, false);
              setTransformReady(true);
            }}
            onPanningStart={(_ref, event) => {
              panStartRef.current = eventPoint(event);
              markViewportInteracted();
            }}
            onPanningStop={(_ref, event) => {
              const start = panStartRef.current;
              const end = eventPoint(event);
              didPanRef.current = Boolean(start && end && Math.hypot(end.x - start.x, end.y - start.y) > 4);
              panStartRef.current = null;
              window.setTimeout(() => { didPanRef.current = false; }, 0);
            }}
            onPinchStart={markViewportInteracted}
            onTransform={(ref) => updateScaleOutput(ref.state.scale)}
            onWheelStart={markViewportInteracted}
            panning={{
              allowLeftClickPan: true,
              excluded: ['room-island__button', 'room-current-card', 'room-focus', 'project-field__pending'],
              velocityDisabled: false,
            }}
            pinch={{ excluded: ['room-focus'] }}
            ref={transformRef}
            smooth
            wheel={{
              excluded: ['room-focus'],
              step: 0.08,
            }}
          >
            <TransformComponent
              contentClass="project-field__map-content"
              contentStyle={{ height: WORLD_HEIGHT, width: WORLD_WIDTH }}
              wrapperClass="project-field__map-viewport"
            >
              <div className="project-field__world">
                <TopographicField />
                <FieldCourse
                  activeRelationIds={activeRelationIds}
                  focusedRoom={focusedRoom}
                  project={project}
                  routeDistances={routeDistances}
                />
                <article
                  aria-label="项目起点：初始愿景"
                  className="project-field__origin"
                  data-surface={project.wayfinder ? 'paper' : undefined}
                  style={{ left: PROJECT_ORIGIN.x, top: PROJECT_ORIGIN.y }}
                >
                  <header>
                    <span><FileText size={15} aria-hidden="true" />初始愿景</span>
                    <em>需求源</em>
                  </header>
                  <strong>{projectFieldText(project.wayfinder?.initialVision.title ?? project.origin)}</strong>
                  {project.wayfinder ? <p>{projectFieldText(project.wayfinder.initialVision.statement)}</p> : null}
                  {project.wayfinder ? <small>整理后细化为多个结果型协作目标 <ArrowRight size={12} aria-hidden="true" /></small> : null}
                </article>
                <article
                  aria-label="项目目的地：尚未抵达"
                  className="project-field__destination"
                  data-surface={project.wayfinder ? 'paper' : undefined}
                  style={{ left: PROJECT_DESTINATION.x, top: PROJECT_DESTINATION.y }}
                >
                  <header>
                    <span><Flag size={15} aria-hidden="true" />愿景收敛</span>
                    <em>待验收</em>
                  </header>
                  <strong>{projectFieldText(project.wayfinder?.destination.title ?? project.destination)}</strong>
                  {project.wayfinder ? <p>全部必需协作目标通过质量检查、独立复核与用户验收后连接。</p> : null}
                </article>
                {orderedMapRooms.map((room) => {
                  if (focusedRoom?.id === room.id) return null;
                  const phase = room.phase;
                  const related = focusedRoom ? activeRelationIds.has(room.id) : false;
                  const dimmed = Boolean(focusedRoom && focusedRoom.id !== room.id && !related);
                  return (
                    <RoomLandmark
                      key={room.id}
                      onFocus={() => focusRoom(room.id)}
                      phase={phase}
                      phaseLabel={room.phaseLabel}
                      room={room}
                      wayfinder={wayfinderRooms.get(room.id)}
                      projectWayfinder={project.wayfinder}
                      routeDistance={routeDistances.get(room.id) ?? 99}
                      dimmed={dimmed}
                    />
                  );
                })}
                {releaseLaneRoom && project.wayfinder && focusedRoom?.id !== releaseLaneRoom.id ? (
                  <ReleaseLane
                    focusedRoom={focusedRoom}
                    onFocus={() => focusRoom(releaseLaneRoom.id)}
                    room={releaseLaneRoom}
                    wayfinder={wayfinderRooms.get(releaseLaneRoom.id)}
                  />
                ) : null}
                <FogAndFrontier
                  pendingRequirement={pendingRequirement}
                  project={project}
                  onRevisitPending={() => {
                    if (!pendingRequirement) return;
                    setNavigatorQuery(pendingRequirement);
                    navigatorInputRef.current?.focus();
                  }}
                />
              </div>
            </TransformComponent>
          </TransformWrapper>

          {focusedRoom ? (
            <RoomFocusPanel
              message={roomMessages[project.id]?.[focusedRoom.id]}
              onClose={leaveRoomFocus}
              onOpenDocument={documentContracts ? openDocuments : undefined}
              projectWayfinder={project.wayfinder}
              room={focusedRoom}
              wayfinder={wayfinderRooms.get(focusedRoom.id)}
              workspaceRef={focusedWorkspaceRef}
            />
          ) : null}

          {documentsOpen && documentContracts ? (
            <ProjectDocumentsPanel
              contracts={documentContracts}
              detail={documentDetail}
              onClose={() => closeDocuments()}
              onOpenRoom={focusRoom}
              onSelect={setSelectedDocumentRef}
              panelRef={documentsPanelRef}
              selectedRef={selectedDocumentRef}
            />
          ) : null}

          <FieldZoomControls
            onReset={resetViewport}
            onZoomIn={() => zoomViewport('in')}
            onZoomOut={() => zoomViewport('out')}
            scaleOutputRef={scaleOutputRef}
          />

          <div className="project-field__gesture-hint" data-hidden={viewportInteracted || undefined}>
            <Compass size={14} aria-hidden="true" />
            <span>拖动画布查看 · 滚轮缩放</span>
          </div>

          {!focusedRoom ? (
            <NavigatorBar
              inputRef={navigatorInputRef}
              onChange={(value) => {
                setNavigatorQuery(value);
                if (routeProposal) setRouteProposal(null);
              }}
              onSubmit={submitNavigator}
              query={navigatorQuery}
              proposalRoom={proposalRoom}
              proposalQuery={routeProposal?.query ?? ''}
              onAcceptRoute={acceptRoute}
              onKeepPending={keepAsPendingRequirement}
              onDismissProposal={() => setRouteProposal(null)}
              onOpenWorkbench={openWorkbenchFromProposal}
            />
          ) : null}

          {attentionOpen ? (
            <AttentionDrawer
              onClose={() => setAttentionOpen(false)}
              onSelectRoom={focusRoom}
              rooms={attentionRooms.map(({ room }) => room)}
            />
          ) : null}

          {undoRoute ? (
            <div className="project-field__undo" role="status">
              <span>
                已在预览中归入「{projectFieldText(project.rooms.find((room) => room.id === undoRoute.roomId)?.title ?? '这个目标')}」。
              </span>
              <button onClick={undoAcceptedRoute} type="button"><Undo2 size={14} />撤销</button>
              <button aria-label="关闭撤销提示" onClick={() => setUndoRoute(null)} type="button"><X size={14} /></button>
            </div>
          ) : null}
          <p className="project-field__live" aria-live="polite">{projectFieldText(liveMessage)}</p>
        </div>
      </section>
    </main>
  );
}

function ProjectRail({
  activeProjectId,
  attentionCount,
  onSwitchProject,
}: {
  activeProjectId: string;
  attentionCount: number;
  onSwitchProject: (projectId: string) => void;
}) {
  return (
    <aside className="project-rail" aria-label="项目">
      <div className="project-rail__brand">
        <span aria-hidden="true"><Compass size={19} /></span>
        <div><strong>PAW</strong><small>Personal Agent Workbench</small></div>
      </div>
      <div className="project-rail__heading">
        <span>项目</span>
      </div>
      <nav className="project-rail__projects" aria-label="切换项目">
        {projectFieldProjects.map((project) => {
          const active = project.id === activeProjectId;
          const count = active ? attentionCount : project.id === 'wisdom-weasel' ? 1 : 0;
          return (
            <button
              aria-label={projectFieldText(project.name)}
              aria-current={active ? 'page' : undefined}
              className="project-rail__project"
              key={project.id}
              onClick={() => onSwitchProject(project.id)}
              type="button"
            >
              <span className="project-rail__monogram" aria-hidden="true">{project.shortName}</span>
              <span className="project-rail__project-copy">
                <strong>{projectFieldText(project.name)}</strong>
                <small>{projectFieldText(project.subtitle)}</small>
              </span>
              {count ? <span className="project-rail__count" aria-label={`${count} 件事需要你`}>{count}</span> : null}
            </button>
          );
        })}
      </nav>
      <div className="project-rail__spacer" />
      <a aria-label="现有工作台" className="project-rail__quiet-link" href="#/agent"><MessageSquareText aria-hidden="true" size={16} /><span>现有工作台</span></a>
      <a aria-label="设置" className="project-rail__quiet-link" href="#/configuration"><Settings aria-hidden="true" size={16} /><span>设置</span></a>
      <div className="project-rail__local"><i aria-hidden="true" /><span>只在本机</span></div>
    </aside>
  );
}

function FieldHeader({
  attentionCount,
  documentsOpen,
  documentsToggleRef,
  onAttention,
  onClearSearch,
  onDismissSearch,
  onFocusSearch,
  onOpenDocuments,
  onOpenSearch,
  onOpenProject,
  onSearch,
  onSelectRoom,
  project,
  searchInputRef,
  searchOpen,
  searchQuery,
  searchResults,
}: {
  attentionCount: number;
  documentsOpen: boolean;
  documentsToggleRef: React.RefObject<HTMLButtonElement | null>;
  onAttention: () => void;
  onClearSearch: () => void;
  onDismissSearch: () => void;
  onFocusSearch: () => void;
  onOpenDocuments?: () => void;
  onOpenSearch: () => void;
  onOpenProject?: () => void;
  onSearch: (query: string) => void;
  onSelectRoom: (roomId: string) => void;
  project: ProjectFieldProject;
  searchInputRef: React.RefObject<HTMLInputElement | null>;
  searchOpen: boolean;
  searchQuery: string;
  searchResults: readonly ProjectRoom[];
}) {
  return (
    <header className="project-field__header">
      <div className="project-field__identity">
        <span><MapIcon size={14} aria-hidden="true" />当前项目</span>
        <div>
          <div className="project-field__identity-title">
            <strong title={projectFieldText(project.name)}>
              <span className="project-field__identity-name project-field__identity-name--full">{projectFieldText(project.name)}</span>
              <span className="project-field__identity-name project-field__identity-name--compact">{projectFieldText(project.compactTitle ?? project.name)}</span>
            </strong>
            <span className="project-field__preview-state" title="使用演示资料，不会修改真实项目或协作空间">交互预览</span>
            {project.reconstruction?.projection ? (
              <span
                aria-label="已根据本机资料整理"
                className="project-field__source-state"
                title="已根据本机资料整理"
              >
                <ShieldCheck size={12} aria-hidden="true" />资料摘要
              </span>
            ) : null}
          </div>
          <small>{projectFieldText(project.heading)}</small>
        </div>
      </div>
      <div
        className="project-field__search"
        data-open={searchOpen ? 'true' : undefined}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onDismissSearch();
        }}
      >
        <Search size={16} aria-hidden="true" />
        <input
          aria-label="搜索协作目标"
          onChange={(event) => onSearch(event.target.value)}
          onFocus={onFocusSearch}
          placeholder="搜索协作目标"
          ref={searchInputRef}
          value={searchQuery}
        />
        <kbd>⌘K</kbd>
        {searchQuery ? (
          <div className="project-field__search-results" role="region" aria-label="搜索结果">
            {searchResults.length ? <>
              <small className="project-field__search-summary">{searchResults.length} 个匹配目标</small>
              <div className="project-field__search-list">
                {searchResults.map((room) => (
                  <button key={room.id} onClick={() => onSelectRoom(room.id)} type="button">
                    <span><strong>{projectFieldText(room.title)}</strong><small>{projectFieldText(room.goal)}</small></span>
                    <ChevronRight size={15} aria-hidden="true" />
                  </button>
                ))}
              </div>
            </> : (
              <div className="project-field__search-empty">
                <p>没有找到匹配的协作目标</p>
                <button onClick={onClearSearch} type="button">清除搜索</button>
              </div>
            )}
          </div>
        ) : null}
      </div>
      <div className="project-field__header-actions">
        {onOpenDocuments ? (
          <button
            aria-expanded={documentsOpen}
            aria-haspopup="dialog"
            aria-label="打开项目工作文档"
            className="project-field__icon-button project-field__documents-toggle"
            onClick={onOpenDocuments}
            ref={documentsToggleRef}
            title="项目工作文档"
            type="button"
          >
            <FileText size={16} aria-hidden="true" />
          </button>
        ) : null}
        {onOpenProject ? (
          <button
            aria-label="在独立窗口中打开当前项目"
            className="project-field__icon-button"
            onClick={onOpenProject}
            title="打开项目工作台"
            type="button"
          >
            <PanelsTopLeft size={16} aria-hidden="true" />
          </button>
        ) : null}
        <button
          aria-expanded={searchOpen}
          aria-label="打开协作目标搜索"
          className="project-field__icon-button project-field__search-toggle"
          onClick={onOpenSearch}
          type="button"
        >
          <Search size={16} aria-hidden="true" />
        </button>
        <button className="project-field__attention-button" onClick={onAttention} type="button" aria-label={`${attentionCount} 件事需要你`}>
          <Bell size={16} aria-hidden="true" />
          <span>{attentionCount || '安静'}</span>
        </button>
      </div>
    </header>
  );
}

function TopographicField() {
  return (
    <svg
      aria-hidden="true"
      className="project-field__topography"
      preserveAspectRatio="none"
      viewBox={`0 0 ${WORLD_WIDTH} ${WORLD_HEIGHT}`}
    >
      <g>
        <path d="M 62 658 C 176 536, 292 515, 402 551 C 493 581, 564 675, 690 659 C 803 645, 841 543, 970 531 C 1112 518, 1195 605, 1395 574" />
        <path d="M 31 711 C 158 576, 286 553, 405 592 C 506 626, 581 718, 708 701 C 830 685, 884 583, 1002 570 C 1144 554, 1240 638, 1431 615" />
        <path d="M 122 603 C 221 500, 321 478, 417 510 C 507 539, 575 624, 681 615 C 788 607, 836 501, 956 488 C 1072 475, 1178 542, 1341 520" />
        <path d="M 382 190 C 493 104, 644 102, 749 166 C 849 227, 846 337, 967 360 C 1104 386, 1197 275, 1394 297" />
        <path d="M 425 232 C 519 162, 638 157, 728 209 C 810 258, 816 364, 940 397 C 1060 428, 1184 327, 1371 348" />
        <path d="M 484 273 C 559 219, 647 215, 713 252 C 785 293, 798 391, 910 428 C 1024 466, 1164 380, 1325 397" />
        <path d="M 812 74 C 916 35, 1035 57, 1078 130 C 1123 205, 1085 286, 1171 323 C 1249 357, 1331 305, 1437 334" />
        <path d="M 887 99 C 965 71, 1037 93, 1063 151 C 1091 213, 1064 274, 1141 304 C 1210 331, 1306 286, 1409 309" />
      </g>
    </svg>
  );
}

function ReleaseLane({
  focusedRoom,
  onFocus,
  room,
  wayfinder,
}: {
  focusedRoom: ProjectRoom | null;
  onFocus: () => void;
  room: ProjectRoom;
  wayfinder?: ProjectWayfinderRoom;
}) {
  if (!wayfinder) return null;
  const stageLabel = deliveryStageLabel(wayfinder.currentStage, wayfinder.deliveryState);
  return (
    <button
      aria-label={`${projectFieldText(room.title)}长期验收，${projectFieldText(stageLabel)}，已核验 ${wayfinder.progress.completed}/${wayfinder.progress.total}`}
      className="project-release-lane"
      data-dimmed={focusedRoom ? true : undefined}
      data-room-id={room.id}
      onClick={(event) => { event.stopPropagation(); onFocus(); }}
      style={{ left: room.x, top: room.y }}
      type="button"
    >
      <span className="project-release-lane__identity">
        <span><Rocket size={17} aria-hidden="true" /></span>
        <span><small>贯穿项目</small><strong>{projectFieldText(room.title)}</strong></span>
        <em>{projectFieldText(stageLabel)}</em>
      </span>
      <span className="project-release-lane__summary">
        <small>持续验收</small>
        <strong>{projectFieldText(room.goal)}</strong>
        <span>每项能力都要经过真实使用与发布检查。</span>
      </span>
      <RoomDeliveryProgress progress={wayfinder.progress} />
      <span className="project-release-lane__open">查看验收详情<ChevronRight size={13} aria-hidden="true" /></span>
    </button>
  );
}

function FieldCourse({
  activeRelationIds,
  focusedRoom,
  project,
  routeDistances,
}: {
  activeRelationIds: Set<string>;
  focusedRoom: ProjectRoom | null;
  project: ProjectFieldProject;
  routeDistances: Map<string, number>;
}) {
  const roomMap = new Map(project.rooms.map((room) => [room.id, room]));
  const origin = PROJECT_ORIGIN;
  const relations = project.wayfinder
    ? project.wayfinder.relations
    : project.edges.map((edge) => ({ ...edge, kind: edge.kind === 'dependency' ? 'requires' : 'led-to' } as const));
  const releaseLaneRoomId = project.wayfinder?.evolution.releaseLane.roomId;
  const visibleRelations = relations.filter((edge) => {
    if (!project.wayfinder || focusedRoom) return true;
    return edge.kind !== 'requires' && edge.from !== releaseLaneRoomId && edge.to !== releaseLaneRoomId;
  });
  return (
    <svg className="project-field__course" aria-hidden="true" viewBox={`0 0 ${WORLD_WIDTH} ${WORLD_HEIGHT}`}>
      <defs>
        <marker id="project-field-route-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="7" refY="4">
          <path d="M 1 1 L 7 4 L 1 7" />
        </marker>
      </defs>
      {visibleRelations.map((edge) => {
        const from = edge.from === '@origin' ? origin : roomMap.get(edge.from);
        const to = roomMap.get(edge.to);
        if (!from || !to) return null;
        const active = Boolean(
          focusedRoom
          && edge.from !== '@origin'
          && activeRelationIds.has(edge.from)
          && activeRelationIds.has(edge.to),
        );
        const heading = edge.from === project.defaultRoomId;
        const edgeDistance = edge.from === '@origin'
          ? 2
          : Math.min(routeDistances.get(edge.from) ?? 99, routeDistances.get(edge.to) ?? 99);
        const tier = heading ? 'heading' : edgeDistance <= 1 ? 'near' : edgeDistance <= 2 ? 'context' : 'remote';
        const routeRole = edge.from === '@origin'
          ? 'origin'
          : edge.kind === 'requires'
          ? 'relation'
          : edge.from === project.defaultRoomId
            ? 'recommended'
            : edge.to === project.defaultRoomId
              ? 'current'
              : 'previous';
        const path = edgePath(from, to);
        return (
          <g data-route-role={routeRole} data-tier={tier} key={`${edge.from}:${edge.to}:${edge.kind}`}>
            {edge.kind !== 'requires' ? (
              <path className="project-field__course-bed" d={path} data-active={active || undefined} />
            ) : null}
            <path
              className="project-field__course-line"
              d={path}
              data-active={active || undefined}
              data-kind={edge.kind}
              markerEnd={routeRole === 'recommended' || routeRole === 'origin' ? 'url(#project-field-route-arrow)' : undefined}
            />
            {heading && !project.wayfinder ? <path className="project-field__course-flow" d={path} /> : null}
          </g>
        );
      })}
    </svg>
  );
}

const islandPaths = {
  1: {
    inner: 'M38 106 C34 69 67 43 115 35 C163 18 217 31 263 57 C295 77 292 119 269 145 C240 176 185 181 132 169 C83 184 44 149 38 106 Z',
    outer: 'M22 108 C18 62 58 28 112 22 C160 4 225 17 278 49 C321 75 311 128 284 158 C251 194 185 201 130 187 C75 200 29 162 22 108 Z',
    contour: 'M61 108 C57 79 82 57 120 50 C163 36 207 45 244 65 C270 82 268 113 250 134 C226 158 183 162 138 153 C99 164 68 138 61 108 Z',
  },
  2: {
    inner: 'M42 71 C67 35 118 25 158 38 C197 17 254 34 279 69 C303 102 281 143 247 154 C224 187 170 186 142 166 C97 184 46 158 35 121 C26 100 29 86 42 71 Z',
    outer: 'M26 62 C56 17 118 8 159 23 C207 1 274 21 294 62 C321 109 294 158 258 170 C226 206 167 204 137 184 C83 201 28 169 18 126 C7 97 9 79 26 62 Z',
    contour: 'M62 78 C82 50 120 43 158 53 C195 37 235 49 257 76 C276 101 259 128 233 138 C209 163 174 160 146 146 C111 159 73 140 61 113 C54 98 54 88 62 78 Z',
  },
  3: {
    inner: 'M52 53 C85 25 132 34 158 53 C191 30 245 30 273 60 C299 88 283 123 260 138 C245 172 196 183 160 165 C124 187 73 171 58 143 C23 130 22 87 52 53 Z',
    outer: 'M43 36 C81 7 132 16 160 34 C204 7 262 15 291 50 C325 89 305 136 278 151 C257 194 197 207 158 186 C113 209 55 185 42 157 C3 139 2 79 43 36 Z',
    contour: 'M71 69 C96 49 128 53 158 70 C190 52 229 51 251 74 C271 94 257 117 239 127 C225 150 190 157 161 144 C130 160 93 147 81 126 C56 116 52 91 71 69 Z',
  },
  4: {
    inner: 'M42 92 C39 58 79 33 116 42 C144 17 195 23 216 50 C260 35 293 68 279 103 C302 135 267 168 231 158 C205 184 160 185 133 165 C94 181 48 159 45 128 C29 119 28 104 42 92 Z',
    outer: 'M25 86 C19 45 70 17 111 26 C144 0 200 3 226 32 C276 18 317 58 299 104 C324 144 281 187 237 175 C205 207 156 208 126 185 C77 204 27 172 29 137 C5 123 6 98 25 86 Z',
    contour: 'M64 96 C61 73 88 56 119 61 C144 42 181 45 204 66 C236 56 263 78 252 103 C268 128 240 145 215 139 C193 159 163 158 139 143 C111 155 79 139 78 118 C62 113 57 103 64 96 Z',
  },
} as const;

function RoomIslandTerrain({
  room,
}: {
  room: ProjectRoom;
}) {
  const generatedGeometry = useMemo(
    () => createRoomIslandGeometry(room),
    [room],
  );
  const fallbackPaths = islandPaths[room.shape];
  const areas = room.areas;
  const segment = 100 / areas.length;
  const visibleSegment = Math.max(12, segment - 5);
  return (
    <svg
      className="room-island__terrain"
      aria-hidden="true"
      data-generated={generatedGeometry ? 'requirements' : undefined}
      preserveAspectRatio="none"
      viewBox="0 0 320 210"
    >
      {generatedGeometry ? (
        <>
          <path
            className="room-island__water"
            d={generatedGeometry.water}
            data-generated-layer="water"
          />
          <path
            className="room-island__shore"
            d={generatedGeometry.shore}
            data-generated-layer="shore"
            pathLength="1"
          />
          <path className="room-island__highland" d={generatedGeometry.highland} />
          <path
            className="room-island__contour"
            d={generatedGeometry.contour}
            data-generated-layer="contour"
            pathLength="1"
          />
        </>
      ) : (
        <>
          <path className="room-island__water" d={fallbackPaths.outer} />
          <path className="room-island__shore" d={fallbackPaths.inner} />
          <path className="room-island__contour" d={fallbackPaths.contour} />
          <circle className="room-island__topography" cx="92" cy="91" r="3" />
          <circle className="room-island__topography" cx="226" cy="119" r="2" />
        </>
      )}
      {areas.map((area, index) => (
        <path
          className="room-island__reef-segment"
          d={generatedGeometry?.contour ?? fallbackPaths.inner}
          data-state={area.state}
          key={area.title}
          pathLength="100"
          strokeDasharray={`${visibleSegment} ${100 - visibleSegment}`}
          strokeDashoffset={-(index * segment)}
        />
      ))}
    </svg>
  );
}

function areaStateLabel(state: ProjectRoomAreaState): string {
  return {
    active: '推进中',
    attention: '需确认',
    planned: '待推进',
    settled: '已稳定',
  }[state];
}

function AreaStateIcon({ state }: { state: ProjectRoomAreaState }) {
  if (state === 'settled') return <Check size={11} strokeWidth={2.2} aria-hidden="true" />;
  if (state === 'active') return <LocateFixed size={11} strokeWidth={2.1} aria-hidden="true" />;
  if (state === 'attention') return <CircleHelp size={11} strokeWidth={2.1} aria-hidden="true" />;
  return <Flag size={11} strokeWidth={2} aria-hidden="true" />;
}

function sourceRoleLabel(source: ProjectRoomSource): string {
  if (source.role === 'intent') return '原始意图';
  if (source.role === 'decision') return '已形成决定';
  return source.authority === 'corroborating' ? '实现旁证' : '验收依据';
}

function sourceProviderLabel(source: ProjectRoomSource): string {
  if (source.provider === 'claude-code') return 'Claude Code';
  if (source.provider === 'codex') return 'Codex';
  if (source.provider === 'pi') return 'Pi';
  if (source.provider === 'omp') return 'OMP';
  if (source.kind === 'git-commit') return 'Git';
  return '项目文档';
}

function RoomSourceIcon({ source }: { source: ProjectRoomSource }) {
  if (source.kind === 'agent-session') return <MessageSquareText size={14} aria-hidden="true" />;
  if (source.kind === 'git-commit') return <GitCommitHorizontal size={14} aria-hidden="true" />;
  return <FileText size={14} aria-hidden="true" />;
}

function RoomSources({ room }: { room: ProjectRoom }) {
  if (!room.sources?.length) return null;
  return (
    <section className="room-focus__sources" aria-label="需求来源">
      <header>
        <span>需求来源</span>
        <small>{room.sources.length} 项可追溯回执</small>
      </header>
      <ul>
        {room.sources.map((source) => (
          <li data-authority={source.authority} key={source.id}>
            <i><RoomSourceIcon source={source} /></i>
            <span>
              <strong>{projectFieldText(source.label)}</strong>
              <small>{projectFieldText(source.detail)}</small>
            </span>
            <em>{projectFieldText(sourceProviderLabel(source))} · {projectFieldText(sourceRoleLabel(source))} · {source.observedAt.slice(5)}</em>
          </li>
        ))}
      </ul>
    </section>
  );
}

function WayfinderRoomBody({
  message,
  onOpenDocument,
  projectWayfinder,
  room,
  wayfinder,
}: {
  message?: string;
  onOpenDocument?: (ref: string) => void;
  projectWayfinder: ProjectWayfinderProjection;
  room: ProjectRoom;
  wayfinder: ProjectWayfinderRoom;
}) {
  const currentStageIndex = projectWayfinder.deliveryEngine.stages
    .findIndex((stage) => stage.id === wayfinder.currentStage);
  return (
    <>
      <h2>{projectFieldText(room.title)}</h2>
      <p className="room-focus__goal">{projectFieldText(wayfinder.requirement)}</p>
      <span className="room-focus__stage-badge">
        <LocateFixed size={12} aria-hidden="true" />
        当前交付 · {projectFieldText(deliveryStageLabel(wayfinder.currentStage, wayfinder.deliveryState))}
      </span>

      {message ? (
        <div className="room-focus__message">
          <span>预览内容</span>
          <p>{projectFieldText(message)}</p>
        </div>
      ) : null}

      <section className="wayfinder-room__contract" aria-label="需求与问题">
        <article>
          <span>整理后的需求</span>
          <p>{projectFieldText(wayfinder.requirement)}</p>
        </article>
        <article>
          <span>要解决的问题</span>
          <p>{projectFieldText(wayfinder.problem)}</p>
        </article>
      </section>

      <section className="wayfinder-room__decisions" aria-label="已确认决定">
        <header>
          <span><Check size={13} aria-hidden="true" />已确认决定</span>
          <small>来自项目协作文档</small>
        </header>
        <ul>
          {wayfinder.decisions.map((decision) => (
            <li key={decision}><Check size={13} aria-hidden="true" /><span>{projectFieldText(decision)}</span></li>
          ))}
        </ul>
      </section>

      <section className="wayfinder-room__acceptance" aria-label="可观察验收">
        <header>
          <span><Check size={13} aria-hidden="true" />可观察验收</span>
          <small>{wayfinder.progress.completed}/{wayfinder.progress.total} 已核验</small>
        </header>
        <ul>
          {wayfinder.progress.items.map((item) => (
            <li data-state={item.state} key={item.label}>
              {item.state === 'verified'
                ? <Check size={13} aria-hidden="true" />
                : <CircleHelp size={13} aria-hidden="true" />}
              <span>{projectFieldText(item.label)}</span>
              <em>{item.state === 'verified' ? '已核验' : '待核验'}</em>
            </li>
          ))}
        </ul>
      </section>

      <section className="wayfinder-room__delivery" aria-label="当前交付">
        <article>
          <span>资料中的最近进展</span>
          <p>{projectFieldText(wayfinder.currentDelivery)}</p>
        </article>
        <article>
          <span>资料中记录的下一步</span>
          <p>{projectFieldText(wayfinder.nextMove)}</p>
        </article>
      </section>

      <section className="wayfinder-room__stages" aria-label="交付链">
        <header>
          <span>协作目标交付链</span>
          <small>每个需求都纵向实现并验收</small>
        </header>
        <ol>
          {projectWayfinder.deliveryEngine.stages.map((stage, index) => {
            const state = index < currentStageIndex ? 'complete' : index === currentStageIndex ? 'active' : 'pending';
            return (
            <li data-state={state} key={stage.id}>
              <span>{state === 'complete' ? <Check size={12} /> : state === 'active' ? <LocateFixed size={12} /> : index + 1}</span>
              <div>
                <strong>{projectFieldText(stage.title)}</strong>
                {stage.id === 'implementation-execution' ? (
                  <small>内层方法 · {projectFieldText(projectWayfinder.deliveryEngine.innerMethod.title)}</small>
                ) : null}
              </div>
            </li>
            );
          })}
        </ol>
      </section>

      <section className="wayfinder-room__evidence" aria-label="交付文档与需求来源">
        <section aria-label="交付文档">
          <strong>交付文档</strong>
          {onOpenDocument ? (
            <button
              className="wayfinder-room__document-open"
              onClick={() => onOpenDocument(wayfinder.documentRef)}
              type="button"
            >
              <FileText size={14} aria-hidden="true" />
              <span>
                <b>{projectFieldText(deliveryDocumentLabel(wayfinder.documentRef))}</b>
                <small>语义、契约与来源回执</small>
              </span>
              <ChevronRight size={13} aria-hidden="true" />
            </button>
          ) : (
            <ul>
              <li><FileText size={13} aria-hidden="true" /><span>{projectFieldText(deliveryDocumentLabel(wayfinder.documentRef))}</span></li>
            </ul>
          )}
          {wayfinder.detailDocumentRefs.length ? (
            <ul>
              {wayfinder.detailDocumentRefs.map((ref) => (
                <li key={ref}><FileText size={13} aria-hidden="true" /><span>{projectFieldText(deliveryDocumentLabel(ref))}</span></li>
              ))}
            </ul>
          ) : null}
        </section>
        <RoomSources room={room} />
      </section>
    </>
  );
}

function RoomSymbol({ room }: { room: ProjectRoom }) {
  const props = { 'aria-hidden': true, size: 18, strokeWidth: 1.9 } as const;
  switch (room.id) {
    case 'input-experience': return <Keyboard {...props} />;
    case 'unified-workbench': return <SlidersHorizontal {...props} />;
    case 'room-delivery': return <Users {...props} />;
    case 'workflow-system': return <Zap {...props} />;
    case 'rime-foundation': return <ShieldCheck {...props} />;
    case 'candidate-stability': return <Keyboard {...props} />;
    case 'local-model': return <Box {...props} />;
    case 'explicit-assistance': return <Zap {...props} />;
    case 'governed-memory': return <Database {...props} />;
    case 'agent-continuity': return <Activity {...props} />;
    case 'room-collaboration': return <Users {...props} />;
    case 'control-center': return <SlidersHorizontal {...props} />;
    case 'release-journey': return <Rocket {...props} />;
    case 'project-field': return <MapIcon {...props} />;
    default: return <Compass {...props} />;
  }
}

function RoomStateMark({ phase }: { phase: ProjectRoomPhase }) {
  if (phase === 'settled') return <Check size={13} strokeWidth={2.4} aria-hidden="true" />;
  if (phase === 'attention') return <CircleHelp size={13} strokeWidth={2.2} aria-hidden="true" />;
  if (phase === 'foreground' || phase === 'running') return <LocateFixed size={13} strokeWidth={2.2} aria-hidden="true" />;
  return <Flag size={13} strokeWidth={2} aria-hidden="true" />;
}

function RoomDeliveryProgress({
  progress,
}: {
  progress: ProjectWayfinderRoom['progress'];
}) {
  const ratio = progress.total > 0 ? progress.completed / progress.total : 0;

  return (
    <span
      aria-label={`验收证据进度：${progress.completed}/${progress.total}`}
      aria-valuemax={progress.total}
      aria-valuemin={0}
      aria-valuenow={progress.completed}
      className="room-requirement-card__progress"
      role="progressbar"
    >
      <span aria-hidden="true" className="room-requirement-card__progress-track">
        <i className="room-requirement-card__progress-fill" style={{ width: `${ratio * 100}%` }} />
      </span>
      <b aria-hidden="true">证据 {progress.completed}/{progress.total}</b>
    </span>
  );
}

function RoomLandmark({
  dimmed,
  onFocus,
  phase,
  phaseLabel: label,
  projectWayfinder,
  room,
  routeDistance,
  wayfinder,
}: {
  dimmed: boolean;
  onFocus: () => void;
  phase: ProjectRoomPhase;
  phaseLabel: string;
  projectWayfinder?: ProjectWayfinderProjection;
  room: ProjectRoom;
  routeDistance: number;
  wayfinder?: ProjectWayfinderRoom;
}) {
  const style = { left: room.x, top: room.y } as CSSProperties;
  return (
    <div
      className="room-island"
      data-area-count={room.areas.length}
      data-dimmed={dimmed || undefined}
      data-phase={phase}
      data-shape={room.shape}
      data-course-tier={routeDistance === 0 ? 'current' : routeDistance === 1 ? 'near' : routeDistance === 2 ? 'context' : 'remote'}
      data-layout={wayfinder ? 'timeline-paper' : undefined}
      data-surface={wayfinder ? 'paper' : undefined}
      data-wayfinder={wayfinder ? 'true' : undefined}
      style={style}
    >
      {!wayfinder ? <RoomIslandTerrain room={room} /> : null}
      {wayfinder && projectWayfinder ? (
        <button
          aria-label={`${projectFieldText(room.title)}，${projectFieldText(room.id === projectWayfinder.currentRoomId ? '当前协作目标' : deliveryStageLabel(wayfinder.currentStage, wayfinder.deliveryState))}`}
          aria-expanded="false"
          className="room-island__button room-requirement-card"
          data-room-id={room.id}
          onClick={(event) => { event.stopPropagation(); onFocus(); }}
          type="button"
        >
          <span className="room-requirement-card__heading">
            <span className="room-requirement-card__symbol"><RoomSymbol room={room} /></span>
            <span>
              <strong>{projectFieldText(room.title)}</strong>
              {room.id === projectWayfinder.currentRoomId ? <small>当前协作目标</small> : null}
            </span>
            <em>{projectFieldText(deliveryStageLabel(wayfinder.currentStage, wayfinder.deliveryState))}</em>
          </span>
          <span className="room-requirement-card__requirement">
            <small>需求</small>
            <b>{projectFieldText(wayfinder.requirement)}</b>
          </span>
          <RoomDeliveryProgress
            progress={wayfinder.progress}
          />
          <span className="room-requirement-card__open">查看详情<ChevronRight size={13} aria-hidden="true" /></span>
        </button>
      ) : (
        <button
          aria-label={`${projectFieldText(room.title)}，${projectFieldText(label)}`}
          aria-expanded="false"
          className="room-island__button room-landmark-card"
          data-room-id={room.id}
          onClick={(event) => { event.stopPropagation(); onFocus(); }}
          type="button"
        >
          <span className="room-landmark-card__heading">
            <span className="room-landmark-card__symbol"><RoomSymbol room={room} /></span>
            <span><strong>{projectFieldText(room.title)}</strong><small>{projectFieldText(label)}</small></span>
          </span>
          <span className="room-landmark-card__scope" aria-label={`${room.areas.length} 个结果范围`}>
            {room.areas.slice(0, 3).map((area) => (
              <span data-state={area.state} key={area.title} title={projectFieldText(`${area.title} · ${area.note}`)}>
                <AreaStateIcon state={area.state} />
                <b>{projectFieldText(area.title)}</b>
              </span>
            ))}
          </span>
          <span className="room-landmark-card__state" aria-hidden="true"><RoomStateMark phase={phase} /></span>
        </button>
      )}
    </div>
  );
}

function RoomFocusPanel({
  message,
  onClose,
  onOpenDocument,
  projectWayfinder,
  room,
  wayfinder,
  workspaceRef,
}: {
  message?: string;
  onClose: () => void;
  onOpenDocument?: (ref: string) => void;
  projectWayfinder?: ProjectWayfinderProjection;
  room: ProjectRoom;
  wayfinder?: ProjectWayfinderRoom;
  workspaceRef: React.RefObject<HTMLElement | null>;
}) {
  const stageLabel = wayfinder
    ? deliveryStageLabel(wayfinder.currentStage, wayfinder.deliveryState)
    : room.phaseLabel;
  return (
    <article className="room-focus project-field__focus-panel" ref={workspaceRef} tabIndex={-1} aria-label={`${projectFieldText(room.title)}协作目标工作区`}>
      <header className="room-focus__header">
        <span className="room-focus__eyebrow"><i aria-hidden="true" />{projectFieldText(stageLabel)}</span>
        <div>
          <button type="button" aria-label="返回项目场" onClick={onClose}><X size={17} /></button>
        </div>
      </header>
      <div className="room-focus__body">
        {wayfinder && projectWayfinder ? (
          <WayfinderRoomBody
            message={message}
            onOpenDocument={onOpenDocument}
            projectWayfinder={projectWayfinder}
            room={room}
            wayfinder={wayfinder}
          />
        ) : (
          <>
            <h2>{projectFieldText(room.title)}</h2>
            <p className="room-focus__goal">{projectFieldText(room.goal)}</p>
            {room.retrospective ? <span className="room-focus__inference">真实资料回顾重建 · {room.sources?.length ?? 0} 项可追溯来源</span> : null}
            <section className="room-focus__areas" aria-label="这个协作目标负责的功能方向">
              <header>
                <span>这个协作目标正在负责</span>
                <strong>{room.areas.length} 个方向</strong>
              </header>
              <div>
                {room.areas.map((area) => (
                  <div data-state={area.state} key={area.title}>
                    <i aria-hidden="true" />
                    <span>
                      <strong>{projectFieldText(area.title)}</strong>
                      <small>{projectFieldText(area.note)}</small>
                    </span>
                    <em>{areaStateLabel(area.state)}</em>
                  </div>
                ))}
              </div>
            </section>
            {message ? (
              <div className="room-focus__message">
                <span>预览内容</span>
                <p>{projectFieldText(message)}</p>
              </div>
            ) : null}
            <dl className="room-focus__summary">
              <div><dt>当前结果</dt><dd>{projectFieldText(room.recentResult)}</dd></div>
              <div data-tone="warning"><dt>尚未确认</dt><dd>{projectFieldText(room.unresolved)}</dd></div>
              <div data-tone="accent"><dt>下一步</dt><dd>{projectFieldText(room.nextStep)}</dd></div>
            </dl>
            <div className="room-focus__workflow" aria-label="当前工作流">
              {room.workflow.map((step, index) => (
                <span key={step} data-current={index === room.workflow.length - 1 || undefined}>
                  {index < room.workflow.length - 1 ? <Check size={12} aria-hidden="true" /> : <LocateFixed size={12} aria-hidden="true" />}
                  {projectFieldText(step)}
                </span>
              ))}
            </div>
            <RoomSources room={room} />
          </>
        )}
      </div>
    </article>
  );
}

function FogAndFrontier({
  onRevisitPending,
  pendingRequirement,
  project,
}: {
  onRevisitPending: () => void;
  pendingRequirement: string | null;
  project: ProjectFieldProject;
}) {
  return (
    <>
      {!project.wayfinder ? (
        <>
          <section className="project-field__fog" aria-label="尚未决定">
            <span><CircleHelp size={14} />尚未决定</span>
            {project.fog?.map((question) => <p key={question}>{projectFieldText(question)}</p>)}
          </section>
          <section className="project-field__frontier" aria-label="当前前沿">
            <span><Compass size={14} />当前前沿</span>
            {project.frontier ? <p>{projectFieldText(project.frontier)}</p> : null}
          </section>
        </>
      ) : null}
      {pendingRequirement ? (
        <button className="project-field__pending" onClick={onRevisitPending} type="button">
          <span><Inbox size={14} />待归属需求</span>
          <strong>{projectFieldText(pendingRequirement)}</strong>
          <small>尚未建立协作空间</small>
        </button>
      ) : null}
    </>
  );
}

function FieldZoomControls({
  onReset,
  onZoomIn,
  onZoomOut,
  scaleOutputRef,
}: {
  onReset: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  scaleOutputRef: React.RefObject<HTMLSpanElement | null>;
}) {
  return (
    <div className="project-field__view-controls" aria-label="画布控制" role="group">
      <div className="project-field__zoom-controls" aria-label="画布缩放">
        <button aria-label="缩小画布" onClick={onZoomOut} type="button"><ZoomOut size={15} /></button>
        <span aria-label="当前缩放" ref={scaleOutputRef}>80%</span>
        <button aria-label="放大画布" onClick={onZoomIn} type="button"><ZoomIn size={15} /></button>
        <button aria-label="复位当前视图" onClick={onReset} type="button"><RotateCcw size={14} /></button>
      </div>
    </div>
  );
}

function NavigatorBar({
  inputRef,
  onAcceptRoute,
  onChange,
  onDismissProposal,
  onKeepPending,
  onOpenWorkbench,
  onSubmit,
  proposalQuery,
  proposalRoom,
  query,
}: {
  inputRef: React.RefObject<HTMLInputElement | null>;
  onAcceptRoute: () => void;
  onChange: (value: string) => void;
  onDismissProposal: () => void;
  onKeepPending: () => void;
  onOpenWorkbench?: () => void;
  onSubmit: (event: FormEvent) => void;
  proposalQuery: string;
  proposalRoom: ProjectRoom | null;
  query: string;
}) {
  return (
    <div className="project-navigator">
      {proposalRoom ? (
        <section className="project-navigator__proposal" aria-label="推荐处理位置">
          <header>
            <span><Sparkles size={14} />建议归入现有目标</span>
            <button aria-label="关闭推荐" onClick={onDismissProposal} type="button"><X size={15} /></button>
          </header>
          <button className="project-navigator__room" onClick={onAcceptRoute} type="button">
            <span><strong>{projectFieldText(proposalRoom.title)}</strong><small>{projectFieldText(proposalRoom.goal)}</small></span>
            <ArrowRight size={17} />
          </button>
          <p>预览这条需求的归属，不会写入真实项目；你可以随时撤销。</p>
          <div className="project-navigator__actions">
            <button className="project-navigator__secondary" onClick={onKeepPending} type="button">保留为待整理目标</button>
            <button className="project-navigator__primary" onClick={onAcceptRoute} type="button">预览归入这里<CornerDownLeft size={14} /></button>
          </div>
          {onOpenWorkbench ? (
            <button className="project-navigator__workbench" onClick={onOpenWorkbench} type="button">
              <PanelsTopLeft size={13} aria-hidden="true" />
              <span>要真实安排任务，打开项目工作台</span>
              <ArrowRight size={13} aria-hidden="true" />
            </button>
          ) : null}
        </section>
      ) : null}
      <form className="project-navigator__bar" onSubmit={onSubmit}>
        <span className="project-navigator__scope" aria-hidden="true"><Sparkles size={16} /><b>项目导航</b></span>
        <label htmlFor="project-navigator-input">想继续推进什么？</label>
        <input
          id="project-navigator-input"
          onChange={(event) => onChange(event.target.value)}
          placeholder="想继续推进什么？例如：删除后旧候选偶尔还会回来"
          ref={inputRef}
          value={query}
        />
        <button aria-label="预览合适目标" disabled={!query.trim()} type="submit"><ArrowRight size={17} /></button>
      </form>
    </div>
  );
}

function DocumentRoleIcon({ role }: { role: ProjectDocumentEntry['role'] }) {
  const props = { 'aria-hidden': true, size: 14 } as const;
  if (role === 'map') return <MapIcon {...props} />;
  if (role === 'initial-vision') return <Rocket {...props} />;
  if (role === 'destination') return <Flag {...props} />;
  return <FileText {...props} />;
}

function ProjectDocumentsPanel({
  contracts,
  detail,
  onClose,
  onOpenRoom,
  onSelect,
  panelRef,
  selectedRef,
}: {
  contracts: ProjectDocumentContracts;
  detail: ProjectDocumentDetail | null;
  onClose: () => void;
  onOpenRoom: (roomId: string) => void;
  onSelect: (ref: string | null) => void;
  panelRef: React.RefObject<HTMLElement | null>;
  selectedRef: string | null;
}) {
  const detailRoomId = detail?.entry.roomId ?? null;
  return (
    <aside
      aria-label="项目工作文档"
      className="project-documents"
      ref={panelRef}
      role="dialog"
      tabIndex={-1}
    >
      <header className="project-documents__header">
        <div>
          <span><FileText size={14} aria-hidden="true" />项目工作文档</span>
          <strong>{contracts.documentCount} 份有契约的文档</strong>
        </div>
        <button aria-label="关闭项目工作文档" onClick={onClose} type="button"><X size={17} /></button>
      </header>
      <p className="project-documents__note">
        文档语义来自已核验的本机资料投影；路径、内容指纹与来源回执用于对照真实仓库。这里只阅读，不修改文档。
      </p>
      <div className="project-documents__layout" data-view={detail ? 'detail' : 'index'}>
        <nav aria-label="文档目录" className="project-documents__index">
          {contracts.groups.map((group) => (
            <section key={group.id}>
              <h3>{group.label}</h3>
              {group.entries.map((entry) => (
                <button
                  aria-current={entry.ref === selectedRef ? 'true' : undefined}
                  key={entry.ref}
                  onClick={() => onSelect(entry.ref)}
                  type="button"
                >
                  <i aria-hidden="true"><DocumentRoleIcon role={entry.role} /></i>
                  <span>
                    <strong>{projectFieldText(entry.title)}</strong>
                    <small>{entry.ref}</small>
                  </span>
                  {entry.stageLabel ? <em>{projectFieldText(entry.stageLabel)}</em> : null}
                </button>
              ))}
            </section>
          ))}
        </nav>
        <article aria-label="文档内容" className="project-documents__reader">
          {detail ? (
            <>
              <header className="project-documents__reader-head">
                <button
                  aria-label="返回文档目录"
                  className="project-documents__back"
                  onClick={() => onSelect(null)}
                  type="button"
                >
                  <Undo2 size={13} aria-hidden="true" />目录
                </button>
                <span className="project-documents__role">
                  {detail.entry.roleLabel}
                  {detail.entry.current ? <b>当前协作目标</b> : null}
                </span>
                <h4>{projectFieldText(detail.entry.title)}</h4>
                <p>{projectFieldText(detail.purpose)}</p>
              </header>
              <div className="project-documents__sections">
                {detail.sections.map((section) => (
                  <section aria-label={section.label} key={section.label}>
                    <header>
                      <span>{section.label}</span>
                      {'note' in section && section.note ? <small>{projectFieldText(section.note)}</small> : null}
                    </header>
                    {section.kind === 'statement' ? <p>{projectFieldText(section.body)}</p> : null}
                    {section.kind === 'list' ? (
                      <ul>
                        {section.items.map((item) => (
                          <li data-state={item.state} key={item.label}>
                            {item.state === 'verified'
                              ? <Check size={13} aria-hidden="true" />
                              : item.state === 'pending'
                                ? <CircleHelp size={13} aria-hidden="true" />
                                : <i aria-hidden="true" />}
                            <span>{projectFieldText(item.label)}</span>
                            {item.state ? <em>{item.state === 'verified' ? '已核验' : '待核验'}</em> : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {section.kind === 'stage-files' ? (
                      <ul data-kind="stage-files">
                        {section.items.map((item) => (
                          <li key={item.ref}>
                            <FileText size={13} aria-hidden="true" />
                            <span>{projectFieldText(item.label)}</span>
                            <code>{item.ref}</code>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </section>
                ))}
              </div>
              {detailRoomId ? (
                <button
                  className="project-documents__goal"
                  onClick={() => onOpenRoom(detailRoomId)}
                  type="button"
                >
                  在项目场查看该目标<ChevronRight size={14} aria-hidden="true" />
                </button>
              ) : null}
              <section aria-label="契约与来源" className="project-documents__authority">
                <header>
                  <span><ShieldCheck size={13} aria-hidden="true" />契约与来源</span>
                  <small>仓库状态，与文档语义分开陈述</small>
                </header>
                <dl>
                  <div><dt>文档路径</dt><dd>{detail.entry.ref}</dd></div>
                  <div><dt>内容指纹</dt><dd title={detail.entry.sha256}>SHA-256 · {detail.entry.sha256.slice(0, 12)}…</dd></div>
                </dl>
                <ul>
                  {detail.sources.map((source) => (
                    <li data-authority={source.authority} key={source.id}>
                      <i aria-hidden="true"><RoomSourceIcon source={source} /></i>
                      <span>
                        <strong>{projectFieldText(source.label)}</strong>
                        <small>{projectFieldText(source.detail)}</small>
                      </span>
                      <em>{projectFieldText(sourceProviderLabel(source))} · {projectFieldText(sourceRoleLabel(source))} · {source.observedAt.slice(5)}</em>
                    </li>
                  ))}
                </ul>
              </section>
            </>
          ) : (
            <div className="project-documents__empty">
              <FileText size={18} aria-hidden="true" />
              <p>从目录选择一份文档，阅读语义、契约与来源。</p>
            </div>
          )}
        </article>
      </div>
      <footer className="project-documents__provenance">
        <span><GitCommitHorizontal size={13} aria-hidden="true" />资料快照</span>
        <small>
          {contracts.provenance.generatedAt ? `生成于 ${contracts.provenance.generatedAt.slice(0, 10)} · ` : ''}
          {contracts.provenance.gitHead ? `git ${contracts.provenance.gitHead.slice(0, 10)} · ` : ''}
          {contracts.provenance.dirtyAtCuration ? '整理时工作区有未提交改动 · ' : ''}
          {contracts.provenance.sourceCount} 项来源回执
        </small>
      </footer>
    </aside>
  );
}

function AttentionDrawer({
  onClose,
  onSelectRoom,
  rooms,
}: {
  onClose: () => void;
  onSelectRoom: (roomId: string) => void;
  rooms: readonly ProjectRoom[];
}) {
  return (
    <aside className="project-attention" aria-label="需要你的协作目标">
      <header>
        <div><span><Bell size={15} />需要你</span><strong>{rooms.length} 个协作目标</strong></div>
        <button aria-label="关闭需要你的协作目标" onClick={onClose} type="button"><X size={17} /></button>
      </header>
      <p>这里只集中提醒；每个协作目标的状态仍以项目场中的原位置为准。</p>
      <div className="project-attention__rooms">
        {rooms.map((room) => (
          <button key={room.id} onClick={() => onSelectRoom(room.id)} type="button">
            <span className="project-attention__marker" aria-hidden="true" />
            <span>
              <strong>{projectFieldText(room.title)}</strong>
              <small>{projectFieldText(room.unresolved)}</small>
            </span>
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        ))}
      </div>
    </aside>
  );
}

export default ProjectFieldFeature;
