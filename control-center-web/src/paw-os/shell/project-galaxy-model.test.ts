import { describe, expect, it } from 'vitest';
import { assignGalaxySurfaces, projectGalaxyScene } from './project-galaxy-model';
import type { WayfinderWorkItem } from './wayfinder-work-projection';

const item = (id: string, running = false): WayfinderWorkItem => ({
  key: `session:${id}`, id, kind: 'session', title: id, projectKey: 'paw', project: 'PAW', workspaceRoots: [],
  updatedAtMs: 0, activity: running ? 'running' : 'idle', runtimeRunning: running,
  statusLabel: running ? '进行中' : '就绪', detail: '公开进度', agents: [], repeats: [],
});

describe('project galaxy scene', () => {
  it('assigns distinct surfaces and keeps them through search, new work and status changes', () => {
    const items = ['a', 'b', 'c', 'd'].map((id) => item(id));
    const assigned = assignGalaxySurfaces(items);
    expect(new Set(assigned.values()).size).toBe(4);
    const original = new Map(assigned);
    assignGalaxySurfaces([item('0'), ...items.map((entry) => ({ ...entry, runtimeRunning: true }))], assigned);
    for (const [id, palette] of original) expect(assigned.get(id)).toBe(palette);
    const filtered = projectGalaxyScene('paw', 'PAW', [items[2]!], assigned);
    expect(filtered.bodies[0]!.paletteIndex).toBe(original.get(items[2]!.key));
  });
  it('keeps real identity and geometry through a status update without inventing work', () => {
    const before = projectGalaxyScene('paw', 'PAW', [item('a'), item('b')]);
    const after = projectGalaxyScene('paw', 'PAW', [item('a', true), item('b')]);
    expect(after.bodies.map((body) => body.id)).toEqual(['session:a', 'session:b']);
    expect(after.bodies.map(({ orbitRadius, phaseRad, size }) => [orbitRadius, phaseRad, size]))
      .toEqual(before.bodies.map(({ orbitRadius, phaseRad, size }) => [orbitRadius, phaseRad, size]));
    expect(before.bodies[0]!.motion.working).toBe(false);
    expect(before.bodies[0]!.spinRadPerS).toBeGreaterThan(0);
    expect(after.bodies[0]!.motion.working).toBe(true);
    expect(after.bodies[0]!.spinRadPerS).toBe(before.bodies[0]!.spinRadPerS);
    expect(after.bodies[0]!.motion.pulseHz).toBeGreaterThan(0);
    expect(after.links).toEqual([]);
    expect(after.center!.motion.working).toBe(false);
    expect(after.center.kind).toBe('galactic-core');
  });

  it('only shows supplied task counts and bounds the GPU scene', () => {
    const entries = Array.from({ length: 30 }, (_, i) => item(String(i)));
    entries[0] = { ...entries[0]!, kind: 'room', progress: { completed: 2, total: 7 } };
    const scene = projectGalaxyScene('paw', 'PAW', entries);
    expect(scene.bodies).toHaveLength(12);
    expect(scene.bodies[0]!.subtitle).toContain('2/7');
    expect(scene.bodies[1]!.subtitle).not.toMatch(/%|\d+\//);
  });
});
