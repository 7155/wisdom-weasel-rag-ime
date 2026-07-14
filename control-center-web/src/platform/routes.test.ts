import { describe, expect, it } from 'vitest';

import {
  CONTROL_ROUTES,
  ControlRoutePolicyError,
  resolveControlPath,
} from './routes';
import { assertControlRequest, assertControlSubscription } from './transport';

const canonicalPathIds = [
  'control.bootstrap',
  'control.capabilities',
  'control.events',
  'system.health',
  'overview.get',
  'input.source.get',
  'agent.runtime.get',
  'agent.runtime.ensure',
  'agent.configuration.get',
  'agent.configuration.update',
  'agent.sessions.list',
  'agent.sessions.create',
  'agent.session.snapshot',
  'agent.session.rename',
  'agent.session.archive',
  'agent.session.mode.update',
  'agent.session.delete',
  'agent.session.prompt',
  'agent.session.abort',
  'agent.session.compact',
  'agent.session.models',
  'agent.session.model.select',
  'agent.session.thinking.select',
  'agent.session.events',
  'agent.session.intercom.list',
  'agent.session.intercom.send',
  'agent.artifact.get',
  'agent.media.list',
  'agent.deep-search',
  'agent.rooms.list',
  'agent.rooms.create',
  'agent.room.get',
  'agent.room.snapshot',
  'agent.room.archive',
  'agent.room.message',
  'agent.room.events',
  'agent.roles.list',
  'agent.tools.list',
  'agent.approvals.list',
  'agent.approval.get',
  'agent.approval.decide',
  'agent.subagents.templates',
  'agent.subagents.list',
  'agent.subagents.create',
  'agent.subagent.get',
  'agent.subagent.abort',
  'agent.memorySources.list',
  'planning.dashboard',
  'planning.mutation.preview',
  'planning.task.save',
  'planning.task.action',
  'planning.taskEvent.undo',
  'planning.mutation.rollback',
  'memory.summary',
  'memory.pages',
  'history.page',
  'knowledge.start',
  'knowledge.cancel',
  'knowledge.status',
  'knowledge.routeStatus',
  'knowledge.database.apply.preview',
  'knowledge.database.apply',
  'knowledge.database.rollback',
  'diagnostics.runtime',
  'diagnostics.predictor',
  'diagnostics.models',
  'configuration.settings',
  'configuration.schema',
] as const;

describe('control route policy', () => {
  it('mirrors the canonical Lane F pathId manifest exactly', () => {
    expect(Object.keys(CONTROL_ROUTES).sort()).toEqual([...canonicalPathIds].sort());
    expect(Object.keys(CONTROL_ROUTES)).toHaveLength(68);
  });

  it('resolves only allowlisted path parameters', () => {
    expect(
      resolveControlPath('agent.session.prompt', { sessionId: 'session:123' }),
    ).toBe('/api/agent/sessions/session%3A123/prompt');
    expect(() =>
      resolveControlPath('agent.session.prompt', { sessionId: 'https://evil.invalid' }),
    ).toThrow(ControlRoutePolicyError);
    expect(() => resolveControlPath('memory.pages', { kind: 'private-db' })).toThrow(
      /not allowlisted/,
    );
  });

  it('uses the concrete Agent handlers without advertising privileged internal routes', () => {
    expect(CONTROL_ROUTES['control.events'].path).toBe('/api/agent/events');
    expect(CONTROL_ROUTES['agent.subagents.templates'].path).toBe(
      '/api/agent/subagents/templates',
    );
    expect(Object.hasOwn(CONTROL_ROUTES, 'agent.media.import')).toBe(false);
    expect(Object.hasOwn(CONTROL_ROUTES, 'agent.tool.execute')).toBe(false);
    expect(Object.hasOwn(CONTROL_ROUTES, 'agent.session.get')).toBe(false);
  });

  it('rejects arbitrary URL/host fields and fields outside each route contract', () => {
    expect(() =>
      assertControlRequest({
        pathId: 'system.health',
        url: 'http://evil.invalid',
      } as never),
    ).toThrow(/url/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.session.prompt',
        params: { sessionId: 'session-1' },
        body: { message: 'hello', shell: 'rm -rf' },
      } as never),
    ).toThrow(/body field/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.session.prompt',
        params: { sessionId: 'session-1' },
        body: {},
      }),
    ).toThrow(/required body/);
    expect(() =>
      assertControlRequest({
        pathId: 'history.page',
        query: { arbitrary: 'yes' },
      }),
    ).toThrow(/query field/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.session.prompt',
        params: { sessionId: 'contains whitespace' },
        body: { message: 'hello' },
      }),
    ).toThrow(/invalid sessionId/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.sessions.list',
        query: { limit: Number.NaN },
      }),
    ).toThrow(/query field is invalid/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.artifact.get',
        params: { artifactId: 'artifact-1' },
      }),
    ).toThrow(/required query/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.session.intercom.send',
        params: { sessionId: 'session-1' },
        body: {
          kind: 'send',
          clientMessageId: 'message-1',
          content: 'hello',
          sourceSessionId: 'session-2',
        },
      } as never),
    ).toThrow(/body field/);
  });

  it('requires an explicit lastEventId for every subscription', () => {
    expect(() =>
      assertControlSubscription({
        pathId: 'agent.session.events',
        params: { sessionId: 'session-1' },
      } as never),
    ).toThrow(/lastEventId/);
    expect(() =>
      assertControlSubscription({
        pathId: 'agent.session.events',
        params: { sessionId: 'session-1' },
        lastEventId: '',
      }),
    ).not.toThrow();
  });
});
