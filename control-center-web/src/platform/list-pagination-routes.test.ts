import { describe, expect, it } from 'vitest';

import { CONTROL_ROUTES } from './routes';
import { assertControlRequest } from './transport';

describe('session and Room list pagination routes', () => {
  it('allow the stable updated-time and id cursor pair', () => {
    expect(CONTROL_ROUTES['agent.sessions.list'].query).toEqual([
      'includeArchived',
      'includeInternal',
      'limit',
      'beforeUpdatedAtMs',
      'beforeId',
      'surfaceKind',
      'ownerAppId',
      'surfaceKey',
      'projectionOnly',
    ]);
    expect(CONTROL_ROUTES['agent.rooms.list'].query).toEqual([
      'includeArchived',
      'limit',
      'beforeUpdatedAtMs',
      'beforeId',
      'projectionOnly',
      'ownerAppId',
      'surfaceKey',
    ]);

    expect(() =>
      assertControlRequest({
        pathId: 'agent.sessions.list',
        query: {
          limit: 100,
          beforeUpdatedAtMs: 1_000,
          beforeId: 'session:cursor',
          projectionOnly: 1,
        },
      }),
    ).not.toThrow();
    expect(() =>
      assertControlRequest({
        pathId: 'agent.rooms.list',
        query: {
          limit: 100,
          beforeUpdatedAtMs: 1_000,
          beforeId: 'room:cursor',
          projectionOnly: 1,
        },
      }),
    ).not.toThrow();
  });
});
