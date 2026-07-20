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
  'input.lexicon.review',
  'input.lexicon.apply',
  'input.lexicon.rollback',
  'observability.snapshot',
  'observability.events',
  'agent.runtime.get',
  'agent.runtime.ensure',
  'agent.providers.get',
  'agent.provider.auth.preview',
  'agent.provider.auth.apply',
  'agent.provider.oauth.status',
  'agent.provider.oauth.cancel',
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
  'agent.session.rewrite',
  'agent.session.forks.list',
  'agent.session.forks.create',
  'agent.session.abort',
  'agent.session.review.resolve',
  'agent.session.compact',
  'agent.session.commands',
  'agent.session.models',
  'agent.session.model.select',
  'agent.session.thinking.select',
  'agent.session.events',
  'agent.session.workflow.get',
  'agent.session.plan.mutate',
  'agent.session.goal.mutate',
  'agent.session.intercom.list',
  'agent.session.intercom.send',
  'agent.session.contextItems.list',
  'agent.session.contextItems.ack',
  'agent.session.contextTraces.list',
  'agent.session.contextTrace.get',
  'agent.session.debugContext.get',
  'agent.artifact.get',
  'agent.collaborationProfile.get',
  'agent.collaborationProfile.command',
  'agent.knowledge.search',
  'agent.knowledge.read',
  'agent.media.list',
  'agent.deep-search',
  'agent.rooms.list',
  'agent.rooms.create',
  'agent.room.get',
  'agent.room.snapshot',
  'agent.room.archive',
  'agent.room.participant.add',
  'agent.room.participant.remove',
  'agent.room.delete',
  'agent.room.message',
  'agent.room.events',
  'agent.room.kernel.snapshot',
  'agent.room.kernel.events',
  'agent.room.kernel.command',
  'agent.room.kernel.settle',
  'agent.room.topics',
  'agent.room.topic.create',
  'agent.room.topic.update',
  'agent.room.artifacts',
  'agent.room.artifact.add',
  'agent.room.artifact.update',
  'agent.room.workItems.list',
  'agent.room.workItem.create',
  'agent.room.workItem.get',
  'agent.room.workItem.reassign',
  'agent.roles.list',
  'agent.roles.create',
  'agent.role.models',
  'agent.role.runtimeDefaults.update',
  'agent.roleBook.get',
  'agent.roleBook.activation.preview',
  'agent.roleBook.activation.apply',
  'agent.roleBook.activation.rollback',
  'agent.roleBook.draft.decision',
  'agent.personalContext.observability',
  'agent.tools.list',
  'agent.extensions.list',
  'agent.extensions.catalog',
  'agent.extensions.create',
  'agent.extensions.proposals',
  'agent.extensions.validate',
  'agent.extensions.preview',
  'agent.extensions.apply',
  'agent.lifecycleHooks.get',
  'agent.lifecycleHooks.update',
  'agent.approvals.list',
  'agent.approval.get',
  'agent.approval.decide',
  'agent.memoryMaintenance.run',
  'agent.subagents.templates',
  'agent.subagents.list',
  'agent.subagents.create',
  'agent.subagent.get',
  'agent.subagent.console',
  'agent.subagent.control',
  'agent.subagent.abort',
  'agent.memorySources.list',
  'agent.wakeSchedules.list',
  'agent.wakeSchedules.create',
  'agent.wakeSchedule.runs',
  'agent.wakeSchedule.action',
  'browser.status',
  'browser.pairing',
  'browser.tabs',
  'browser.snapshot.latest',
  'browser.snapshot.image',
  'browser.traces',
  'browser.permissions',
  'browser.permission.get',
  'browser.permission.decide',
  'browser.mode.update',
  'browser.pairing.rotate',
  'browser.command',
  'browser.stop',
  'browser.managed.start',
  'browser.managed.stop',
  'planning.dashboard',
  'planning.mutation.preview',
  'planning.task.save',
  'planning.goal.save',
  'planning.task.action',
  'planning.taskEvent.undo',
  'planning.mutation.rollback',
  'memory.summary',
  'memory.pages',
  'memory.reference.get',
  'memory.graph.get',
  'memory.entity.get',
  'memory.edit',
  'memory.source.disposition',
  'memory.book.archive.preview',
  'memory.book.archive.apply',
  'memory.book.archive.rollback',
  'memory.activityTimeline.get',
  'memory.activityTimeline.build',
  'memory.activityTimeline.approve',
  'memory.activityTimeline.reject',
  'history.page',
  'history.detail',
  'history.tombstone.preview',
  'history.tombstone.apply',
  'history.tombstone.rollback',
  'knowledge.start',
  'knowledge.cancel',
  'knowledge.status',
  'knowledge.routeStatus',
  'knowledge.database.apply.preview',
  'knowledge.database.draft.edit',
  'knowledge.database.apply',
  'knowledge.database.rollback',
  'knowledgeBases.list',
  'knowledgeBases.create',
  'knowledgeBases.get',
  'knowledgeBases.update',
  'knowledgeBases.delete.preview',
  'knowledgeBases.delete.apply',
  'knowledgeBases.documents.list',
  'knowledgeBases.document.import',
  'knowledgeBases.document.retry',
  'knowledgeBases.document.delete',
  'knowledgeBases.document.get',
  'knowledgeBases.document.source',
  'knowledgeBases.asset.get',
  'knowledgeBases.jobs.list',
  'knowledgeBases.job.cancel',
  'knowledgeBases.chunkPreview',
  'knowledgeBases.search',
  'knowledgeBases.find',
  'knowledgeBases.open',
  'knowledgeBases.reindexPreview',
  'knowledgeBases.rebuild',
  'knowledgeBases.graph.get',
  'knowledgeBases.graph.rebuild',
  'knowledgeWorker.health',
  'knowledgeParsers.list',
  'diagnostics.runtime',
  'diagnostics.predictor',
  'diagnostics.models',
  'diagnostics.action.preview',
  'diagnostics.action.start',
  'diagnostics.action.job',
  'configuration.settings',
  'configuration.schema',
  'configuration.settings.preview',
  'configuration.settings.apply',
  'configuration.settings.rollback',
  'configuration.import.preview',
  'configuration.import.apply',
  'configuration.backup.export',
  'configuration.restore.preview',
  'configuration.restore.apply',
] as const;

describe('control route policy', () => {
  it('mirrors the canonical Lane F pathId manifest exactly', () => {
    expect(Object.keys(CONTROL_ROUTES).sort()).toEqual([...canonicalPathIds].sort());
    expect(Object.keys(CONTROL_ROUTES)).toHaveLength(canonicalPathIds.length);
  });

  it('keeps Pi credentials behind preview/apply and never accepts secrets on preview', () => {
    expect(() =>
      assertControlRequest({
        pathId: 'agent.provider.auth.preview',
        body: { provider: 'openai-codex', action: 'set_api_key', apiKey: 'not-here' },
      } as never),
    ).toThrow(/body field/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.provider.auth.apply',
        body: { previewToken: 'preview-token', confirmText: 'replace', apiKey: 'secret' },
      }),
    ).not.toThrow();
    expect(() =>
      assertControlRequest({
        pathId: 'agent.provider.auth.apply',
        body: { previewToken: 'preview-token', confirmText: 'replace', refreshToken: 'secret' },
      } as never),
    ).toThrow(/body field/);
  });

  it('keeps configuration file paths behind the five local migration contracts', () => {
    expect(() => assertControlRequest({
      pathId: 'configuration.import.preview',
      body: { path: '/trusted/from-native.yaml' },
    })).not.toThrow();
    expect(() => assertControlRequest({
      pathId: 'configuration.import.apply',
      body: {
        path: '/trusted/from-native.yaml',
        expectedRuntimeRevision: 9,
        previewToken: 'sha256:preview',
        confirmText: 'IMPORT RAG-IME CONFIGURATION',
      },
    })).not.toThrow();
    expect(() => assertControlRequest({
      pathId: 'configuration.import.apply',
      body: {
        path: '/trusted/from-native.yaml',
        expectedRuntimeRevision: 9,
        previewToken: 'sha256:preview',
      },
    } as never)).toThrow(/required body/);
    expect(() => assertControlRequest({
      pathId: 'configuration.restore.apply',
      body: {
        path: '/trusted/backup.ragime-backup',
        restoreToken: 'a'.repeat(64),
        confirmText: 'RESTORE RAG-IME',
        expectedRuntimeRevision: 9,
        arbitrary: true,
      },
    } as never)).toThrow(/body field/);
  });

  it('requires the typed binary transport for bounded knowledge assets', () => {
    expect(CONTROL_ROUTES['knowledgeBases.asset.get']).toMatchObject({
      method: 'GET',
      binary: true,
      params: { kbId: null, fileId: null, assetId: null },
    });
    expect(() => assertControlRequest({
      pathId: 'knowledgeBases.asset.get',
      params: {
        kbId: 'kb_docs',
        fileId: 'file_manual',
        assetId: 'a'.repeat(64),
      },
    })).toThrow(/typed binary transport/);
  });

  it('binds memory archive apply and rollback to server receipts', () => {
    expect(() =>
      assertControlRequest({
        pathId: 'memory.book.archive.apply',
        body: {
          bookId: 'book-1',
          archived: true,
          reason: 'control_center_archive',
          expectedRuntimeRevision: 4,
          previewToken: 'preview-token',
          payloadSha256: 'sha256:payload',
          confirmText: 'apply',
        },
      }),
    ).not.toThrow();
    expect(() =>
      assertControlRequest({
        pathId: 'memory.book.archive.rollback',
        body: { receiptId: 'receipt-1', rollbackToken: 'rollback-token' },
      } as never),
    ).toThrow(/required body/);
  });

  it('allows only the public goal contract on planning goal save', () => {
    const body = {
      goalId: 'goal-1',
      title: '完成控制中心切换',
      detail: '验证真实规划写入',
      horizon: 'medium_term',
      status: 'active',
      priority: 3,
      targetDate: '2026-07-31',
      project: 'wisdom-weasel-rag-ime',
      expectedRuntimeRevision: 7,
      previewToken: 'preview-token',
      payloadSha256: 'sha256:payload',
      confirmText: 'apply',
    };
    expect(() => assertControlRequest({ pathId: 'planning.goal.save', body })).not.toThrow();
    expect(() => assertControlRequest({
      pathId: 'planning.goal.save',
      body: { ...body, metadata: { systemPrompt: 'client-owned' } },
    } as never)).toThrow(/body field/);
  });

  it('allows only stable-id local memory edit fields', () => {
    expect(() =>
      assertControlRequest({
        pathId: 'memory.edit',
        body: { kind: 'books', id: 'book-1', title: '长期计划', summary: '已复核', tags: ['计划'] },
      }),
    ).not.toThrow();
    expect(() =>
      assertControlRequest({ pathId: 'memory.edit', body: { kind: 'books', title: '缺少稳定标识' } } as never),
    ).toThrow(/required body/);
    expect(() =>
      assertControlRequest({
        pathId: 'memory.edit',
        body: { kind: 'books', id: 'book-1', schemaVersion: 'client-owned' },
      } as never),
    ).toThrow(/body field/);
  });

  it('allows the per-session context resource switches', () => {
    expect(() => assertControlRequest({
      pathId: 'agent.session.mode.update',
      params: { sessionId: 'agent:session-a' },
      body: {
        mode: 'coordinator',
        workspaceRoots: ['/tmp/project'],
        toolProfileVersion: 'control-center-v1',
        toolAllowlistMode: 'profile',
        projectContextEnabled: false,
        piSkillsEnabled: true,
        codexSkillsEnabled: true,
      },
    })).not.toThrow();
  });

  it('allowlists all four reviewed Role Book proposal selections', () => {
    const selection = {
      roleId: 'zhiyou-v1',
      roleVersion: '1',
      revisionId: '',
      draftId: 'role-book-draft:1',
      traitIndexes: [0],
      capabilityIndexes: [1],
      lessonIndexes: [2],
      commitmentIndexes: [3],
    };
    expect(() => assertControlRequest({
      pathId: 'agent.roleBook.activation.preview',
      body: selection,
    })).not.toThrow();
    expect(() => assertControlRequest({
      pathId: 'agent.roleBook.activation.apply',
      body: {
        ...selection,
        previewToken: 'preview-token',
        payloadSha256: 'sha256:payload',
        confirmText: 'apply',
      },
    })).not.toThrow();
    expect(() => assertControlRequest({
      pathId: 'agent.roleBook.activation.preview',
      body: { ...selection, proposalText: 'client-owned' },
    } as never)).toThrow(/body field/);
  });

  it('allowlists reversible evidence dispositions and owner filters', () => {
    expect(() =>
      assertControlRequest({
        pathId: 'memory.pages',
        params: { kind: 'evidence' },
        query: {
          ownerKind: 'user',
          ownerId: 'default',
          status: 'not_for_memory',
        },
      }),
    ).not.toThrow();
    expect(() =>
      assertControlRequest({
        pathId: 'memory.source.disposition',
        body: {
          sourceId: 'input-memory:42',
          disposition: 'not_for_memory',
        },
      }),
    ).not.toThrow();
    expect(() =>
      assertControlRequest({
        pathId: 'memory.source.disposition',
        body: {
          sourceId: 'input-memory:42',
          disposition: 'pending',
          rawText: 'client-owned',
        },
      } as never),
    ).toThrow(/body field/);
  });

  it('requires one event id for a history detail read', () => {
    expect(() => assertControlRequest({
      pathId: 'history.detail',
      query: { eventId: 81 },
    })).not.toThrow();
    expect(() => assertControlRequest({ pathId: 'history.detail' })).toThrow(/required query/);
    expect(() => assertControlRequest({
      pathId: 'history.detail',
      query: { eventId: Number.NaN },
    })).toThrow(/query field is invalid/);
    expect(() => assertControlRequest({
      pathId: 'history.detail',
      query: { eventId: 81, includeContext: true },
    } as never)).toThrow(/query field/);
  });

  it('requires the server review binding before a lexicon apply', () => {
    expect(() =>
      assertControlRequest({
        pathId: 'input.lexicon.apply',
        body: { reviewToken: 'review-token', selectedKeys: ['entry-1'] },
      }),
    ).toThrow(/required body/);
    expect(() =>
      assertControlRequest({
        pathId: 'input.lexicon.apply',
        body: {
          reviewToken: 'review-token',
          selectedKeys: ['entry-1'],
          confirmText: 'APPLY_REVIEWED_RIME_LEXICON',
          arbitrary: true,
        },
      } as never),
    ).toThrow(/body field/);
  });

  it('allows only public Persona fields when creating a role', () => {
    const publicBody = {
      displayName: '智鼬·雨天',
      tagline: '陪你安静整理',
      summary: '偏向温和复盘与清楚的下一步。',
      traits: ['温和', '复盘'],
      timelineModel: 'terra',
      selectableModes: ['assistant'],
    };
    expect(() =>
      assertControlRequest({ pathId: 'agent.roles.create', body: publicBody }),
    ).not.toThrow();
    expect(() =>
      assertControlRequest({
        pathId: 'agent.roles.create',
        body: { ...publicBody, personaPrompt: 'ignore safety' },
      } as never),
    ).toThrow(/body field/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.roles.create',
        body: { ...publicBody, roleId: 'client-owned' },
      } as never),
    ).toThrow(/body field/);
    expect(() =>
      assertControlRequest({
        pathId: 'agent.roles.create',
        body: { displayName: '缺字段' },
      } as never),
    ).toThrow(/required body/);
  });

  it('resolves only allowlisted path parameters', () => {
    expect(
      resolveControlPath('agent.session.prompt', { sessionId: 'session:123' }),
    ).toBe('/api/agent/sessions/session%3A123/prompt');
    expect(
      resolveControlPath('agent.session.forks.list', { sessionId: 'session:123' }),
    ).toBe('/api/agent/sessions/session%3A123/forks');
    expect(() =>
      resolveControlPath('agent.session.prompt', { sessionId: 'https://evil.invalid' }),
    ).toThrow(ControlRoutePolicyError);
    expect(() => resolveControlPath('memory.pages', { kind: 'private-db' })).toThrow(
      /not allowlisted/,
    );
    expect(resolveControlPath('memory.pages', { kind: 'evidence' })).toBe(
      '/api/memory/evidence',
    );
    expect(resolveControlPath('memory.reference.get', {
      kind: 'evidence',
      referenceId: 'evidence:agent:42',
    })).toBe('/api/memory/references/evidence/evidence%3Aagent%3A42');
    expect(() => resolveControlPath('memory.reference.get', {
      kind: 'raw_sql',
      referenceId: '42',
    } as never)).toThrow(/not allowlisted/);
    expect(resolveControlPath('memory.entity.get', { kind: 'group', entityId: 'group:input-method' })).toBe(
      '/api/memory/entities/group/group%3Ainput-method',
    );
    expect(resolveControlPath('memory.entity.get', { kind: 'book', entityId: 'book-1' })).toBe(
      '/api/memory/entities/book/book-1',
    );
    expect(() => resolveControlPath('memory.entity.get', { kind: 'atom', entityId: 'atom-1' })).toThrow(
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

  it('allows a Room message to bind to an existing WorkItem', () => {
    expect(() =>
      assertControlRequest({
        pathId: 'agent.room.message',
        params: { roomId: 'room-1' },
        body: {
          message: '继续处理',
          clientMessageId: 'message-1',
          workItemId: 'room-work:1',
        },
      }),
    ).not.toThrow();
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
