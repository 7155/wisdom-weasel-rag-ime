import { describe, expect, it } from 'vitest';
import { toolItems } from './types';

describe('Agent tool catalogue projection', () => {
  it('keeps the Pi Host ask tool in the same countable manifest set', () => {
    const items = toolItems({
      items: [{
        schemaVersion: 'rag-ime.control-tool-manifest.v1',
        id: 'ask',
        domain: 'planning',
        displayName: 'Ask',
        description: '向用户提出仍需其决定的结构化选择',
        category: 'planning',
        riskLevel: 'R0',
        sessionModes: ['assistant', 'coordinator'],
        operations: ['ask'],
        resultPresentation: 'approval',
        availability: 'online',
        version: '1',
        runtimeOwner: 'pi_host',
        enabled: true,
        effectiveOperations: ['ask'],
      }],
    });

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ id: 'ask', runtimeOwner: 'pi_host' });
  });
});
