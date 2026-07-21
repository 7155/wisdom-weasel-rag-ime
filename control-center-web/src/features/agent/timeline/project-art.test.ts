import { describe, expect, it } from 'vitest';
import { projectSceneAssets, resolveProjectScene } from './project-art';

describe('project art contract', () => {
  it('exposes the functional product scene slots', () => {
    expect(Object.keys(projectSceneAssets)).toEqual([
      'knowledge-authorized-retrieval',
      'memory-evidence-timeline',
      'recovery-safe-resume',
      'room-agent-handoff',
      'room-onboarding',
      'task-evidence-acceptance',
    ]);
    expect(resolveProjectScene('room-agent-handoff')).toMatchObject({
      source: '/companions/scenes/room-structured-handoff-v2.webp',
      width: 960,
      height: 640,
    });
    expect(resolveProjectScene('memory-evidence-timeline').intendedSlots).toContain('memory-empty-state');
    expect(resolveProjectScene('recovery-safe-resume').intendedSlots).toContain('room-runtime-error');
  });

  it('ships useful alternative text instead of filename-derived labels', () => {
    for (const asset of Object.values(projectSceneAssets)) {
      expect(asset.alt.length).toBeGreaterThan(20);
      expect(asset.alt).not.toMatch(/\.webp|v1|image|图片/iu);
    }
  });
});
