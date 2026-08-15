import { describe, expect, it } from 'vitest';

import { recommendedCreateRole } from './room-presentation';

describe('recommendedCreateRole', () => {
  it('keeps every non-facilitator peer available for implementation', () => {
    const selected = [
      'companion-future-v1',
      'companion-present-v1',
      'companion-firstlight-v1',
      'companion-flash-v1',
    ];

    expect(recommendedCreateRole(selected[0], selected, selected[0])).toBe('coordinator');
    expect(selected.slice(1).map((roleId) => recommendedCreateRole(roleId, selected, selected[0])))
      .toEqual(['implementer', 'implementer', 'implementer']);
  });
});
