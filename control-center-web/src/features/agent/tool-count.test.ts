import { describe, expect, it } from 'vitest';

import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { countUniqueToolActivities, uniqueToolActivities } from './tool-count';

describe('logical Agent tool counting', () => {
  it('counts one logical call across lifecycle updates and excludes Todo maintenance', () => {
    const activities = [
      activity('started', 'tool_started', 'call-1', 'browser'),
      activity('progress', 'tool_progress', 'call-1', 'browser'),
      activity('finished', 'tool_finished', 'call-1', 'browser'),
      activity('todo', 'tool_finished', 'call-todo', 'todo'),
      activity('second', 'tool_finished', 'call-2', 'knowledge'),
    ];

    expect(uniqueToolActivities(activities).map((item) => item.id))
      .toEqual(['started', 'second']);
    expect(countUniqueToolActivities(activities)).toBe(2);
  });
});

function activity(
  id: string,
  kind: string,
  toolCallId: string,
  toolId: string,
): AgentActivityProjection {
  return {
    id,
    turnId: 'turn-1',
    kind,
    status: 'completed',
    summary: id,
    payload: { toolCallId, toolId },
    createdAtMs: 1,
    updatedAtMs: 2,
  };
}
