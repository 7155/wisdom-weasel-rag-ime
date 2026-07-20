import { describe, expect, it } from 'vitest';
import { projectSceneAssets, resolveProjectScene } from './project-art';

describe('project art contract', () => {
  it('exposes only functional Room and Memory scene slots', () => {
    expect(Object.keys(projectSceneAssets)).toEqual([
      'memory-evidence-timeline',
      'room-agent-handoff',
    ]);
    expect(resolveProjectScene('room-agent-handoff')).toMatchObject({
      source: '/companions/scenes/room-duoagent-handoff-v1.webp',
      width: 960,
      height: 720,
    });
    expect(resolveProjectScene('memory-evidence-timeline').intendedSlots).toContain('memory-empty-state');
  });

  it('ships useful alternative text instead of filename-derived labels', () => {
    for (const asset of Object.values(projectSceneAssets)) {
      expect(asset.alt.length).toBeGreaterThan(20);
      expect(asset.alt).not.toMatch(/\.webp|v1|image|图片/iu);
    }
  });
});
