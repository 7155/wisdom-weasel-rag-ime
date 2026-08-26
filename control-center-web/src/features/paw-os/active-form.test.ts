import { describe, expect, it } from 'vitest';
import {
  dockAppIdsForForm,
  landingFormFromPayload,
  launchpadAppIdsForForm,
  type LandingFormSummary,
} from './active-form';
import { primaryDockAppIds, type PawOsAppId } from './model/app-registry';

const knowledgeQa: LandingFormSummary = {
  id: 'knowledge-qa',
  displayName: '知识库问答',
  version: '1.0.0',
  description: '',
  tagline: '',
  dockAppIds: ['agent', 'knowledge', 'files', 'app-center'],
  launchpadAppIds: ['agent', 'knowledge', 'memory', 'files', 'app-center', 'system-settings'],
  defaultLandingAppId: 'knowledge',
  defaultPersona: { roleId: 'companion-present-v1', version: '1' },
  policyPreset: 'default',
  skillRefs: ['landing-app-builder', 'plugin-creator'],
  bootstrapPrompt: '/skill:landing-app-builder …',
  digest: 'abc',
  active: true,
};

describe('Landing Form shell filters', () => {
  it('parses an active Form payload', () => {
    const form = landingFormFromPayload({
      id: 'knowledge-qa',
      displayName: '知识库问答',
      version: '1.0.0',
      dockAppIds: ['agent', 'knowledge', 'files', 'app-center'],
      launchpadAppIds: ['agent', 'knowledge'],
      defaultLandingAppId: 'knowledge',
      defaultPersona: { roleId: 'companion-present-v1', version: '1' },
      active: true,
    });
    expect(form?.id).toBe('knowledge-qa');
    expect(form?.defaultLandingAppId).toBe('knowledge');
  });

  it('filters Dock to the Form list while keeping App Center', () => {
    const dock = dockAppIdsForForm(knowledgeQa);
    expect(dock).toEqual(['agent', 'knowledge', 'files', 'app-center']);
    expect(dock).not.toContain('project-workbench');
    expect(dock).not.toContain('browser');
  });

  it('falls back to the primary Dock when no Form is active', () => {
    expect(dockAppIdsForForm(null)).toEqual(primaryDockAppIds);
  });

  it('filters Launchpad to the Form list', () => {
    const all: PawOsAppId[] = [
      'project-workbench',
      'agent',
      'memory',
      'knowledge',
      'browser',
      'app-center',
      'system-settings',
    ];
    expect(launchpadAppIdsForForm(knowledgeQa, all)).toEqual([
      'agent',
      'memory',
      'knowledge',
      'app-center',
      'system-settings',
    ]);
  });
});
