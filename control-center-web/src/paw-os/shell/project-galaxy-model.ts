import type { WayfinderWorkItem } from './wayfinder-work-projection';

type GalaxyMotion = { working: boolean; tone: string; ring: string; pulseHz: number };
export type ProjectGalaxyBody = {
  id: string; kind: 'planet'; title: string; subtitle: string; detail: string; task: string; idle: boolean;
  orbitRadius: number; phaseRad: number; inclinationRad: number; eccentricity: number; axialTiltRad: number;
  size: number; paletteIndex: number; spinRadPerS: number; motion: GalaxyMotion;
};
export type ProjectGalaxyModel = {
  seed: string; mode: 'galaxy'; bodies: ProjectGalaxyBody[]; ringRadii: number[]; links: [];
  center: { id: 'center'; kind: 'galactic-core'; title: string; subtitle: string; size: number; motion: GalaxyMotion };
};
export function galaxyHash(key: string) {
  let value = 2166136261;
  for (const character of key) value = Math.imul(value ^ character.charCodeAt(0), 16777619);
  return value >>> 0;
}

const still: GalaxyMotion = { working: false, tone: 'muted', ring: 'none', pulseHz: 0 };

/** Assign against the full project, then retain identities through filtering,
 * pagination and new work. IDs remain independent of activity and progress. */
export function assignGalaxySurfaces(items: readonly WayfinderWorkItem[], assigned = new Map<string, number>()) {
  const order = [0, 4, 3, 2, 1, 5];
  const counts = order.map((palette) => [...assigned.values()].filter((value) => value === palette).length);
  for (const item of [...items].sort((a, b) => a.key.localeCompare(b.key))) {
    if (assigned.has(item.key)) continue;
    const index = counts.indexOf(Math.min(...counts));
    assigned.set(item.key, order[index]!);
    counts[index]!++;
  }
  return assigned;
}

/** A project is a navigation scope, not an invented Room or coordinator. */
export function projectGalaxyScene(projectId: string, title: string, items: readonly WayfinderWorkItem[], surfaces = assignGalaxySurfaces(items)): ProjectGalaxyModel {
  const visible = items.slice(0, 12);
  const bodies = visible.map((item, index) => {
    const seed = galaxyHash(item.key);
    const running = item.runtimeRunning;
    const motion: GalaxyMotion = {
      ...still,
      working: running,
      tone: item.activity === 'attention' ? 'attention' : running ? 'working' : 'muted',
      ring: item.activity === 'attention' ? 'attention' : 'none',
      pulseHz: running ? .25 : 0,
    };
    return {
      id: item.key, kind: 'planet' as const, title: item.title,
      subtitle: `${item.statusLabel}${running && item.activity !== 'running' ? ' · 运行中' : ''}${item.progress ? ` · ${item.progress.completed}/${item.progress.total} 项` : ''}`,
      detail: item.detail, task: item.detail, idle: !running,
      // Layout expresses identity only. Counts and status never change size.
      orbitRadius: 8.6 + index % 3 * 2.2,
      phaseRad: .28 + index * Math.PI * 2 / Math.max(visible.length, 1),
      inclinationRad: ((seed % 7) - 3) * .025,
      eccentricity: .06 + seed % 5 * .025,
      axialTiltRad: .12 + (seed % 5) * .12,
      size: visible.length <= 6 ? 1.45 + seed % 3 * .08 : .95 + seed % 3 * .04,
      paletteIndex: surfaces.get(item.key) ?? 2,
      spinRadPerS: .035 + seed % 5 * .018, motion,
    };
  });
  return {
    seed: `project:${projectId}`, mode: 'galaxy',
    center: { id: 'center', kind: 'galactic-core', title, subtitle: '项目文档', size: .84, motion: still },
    bodies, ringRadii: bodies.map((body) => body.orbitRadius), links: [],
  };
}
