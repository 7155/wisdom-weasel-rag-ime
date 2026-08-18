import { useCallback, useMemo, useState } from 'react';

export type RoomSurfaceModuleId =
  | 'plan'
  | 'assignments'
  | 'flow'
  | 'partner-work'
  | 'participant-rail';

export interface RoomSurfaceModuleDefinition {
  id: RoomSurfaceModuleId;
  name: string;
  description: string;
  slot: 'navigation' | 'execution' | 'evidence';
  defaultMounted: boolean;
}

export const ROOM_SURFACE_MODULES: readonly RoomSurfaceModuleDefinition[] = [
  {
    id: 'plan',
    name: '计划与文档导航',
    description: '在目标下方投影真实 Todo 或计划文档；没有事实时不占位置。',
    slot: 'navigation',
    defaultMounted: true,
  },
  {
    id: 'assignments',
    name: '分工与 @',
    description: '显示 Partner、WorkItem、负责人、验收条件与显式 @ 关系。',
    slot: 'execution',
    defaultMounted: true,
  },
  {
    id: 'flow',
    name: '阶段与并行流转',
    description: '首版只绘制阶段和并行支线，并保留 Partner 调用的子 Agent。',
    slot: 'execution',
    defaultMounted: true,
  },
  {
    id: 'partner-work',
    name: '伙伴工作与公开回复',
    description: '按思维摘要、工具、子 Agent、公开回复的顺序投影伙伴工作。',
    slot: 'evidence',
    defaultMounted: true,
  },
  {
    id: 'participant-rail',
    name: '任务快速索引',
    description: '在目标下方突出当前执行人，并提供计划、分工、伙伴交付与 Root 的单行导航。',
    slot: 'navigation',
    defaultMounted: true,
  },
] as const;

const ROOM_SURFACE_MODULE_STORAGE_KEY = 'wisdom-weasel.rooms.surface-modules.v1';

type RoomSurfaceModulePreferences = Partial<Record<RoomSurfaceModuleId, boolean>>;

export function useRoomSurfaceModules() {
  const [preferences, setPreferences] = useState<RoomSurfaceModulePreferences>(readPreferences);
  const mountedIds = useMemo(() => new Set(ROOM_SURFACE_MODULES
    .filter((module) => preferences[module.id] ?? module.defaultMounted)
    .map((module) => module.id)), [preferences]);
  const setMounted = useCallback((id: RoomSurfaceModuleId, mounted: boolean) => {
    setPreferences((current) => {
      const next = { ...current, [id]: mounted };
      writePreferences(next);
      return next;
    });
  }, []);
  const reset = useCallback(() => {
    writePreferences({});
    setPreferences({});
  }, []);
  return {
    definitions: ROOM_SURFACE_MODULES,
    isMounted: (id: RoomSurfaceModuleId) => mountedIds.has(id),
    mountedIds,
    reset,
    setMounted,
  };
}

function readPreferences(): RoomSurfaceModulePreferences {
  if (typeof window === 'undefined') return {};
  try {
    const parsed = JSON.parse(window.localStorage.getItem(ROOM_SURFACE_MODULE_STORAGE_KEY) || '{}') as unknown;
    if (!isRecord(parsed)) return {};
    return Object.fromEntries(ROOM_SURFACE_MODULES.flatMap((module) => (
      typeof parsed[module.id] === 'boolean' ? [[module.id, parsed[module.id]]] : []
    ))) as RoomSurfaceModulePreferences;
  } catch {
    return {};
  }
}

function writePreferences(preferences: RoomSurfaceModulePreferences): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(ROOM_SURFACE_MODULE_STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // A blocked browser store must not make the Room surface unusable.
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
