import { describe, expect, it } from 'vitest';
import { parseRoomRequirementsReadProjection } from '@/features/rooms/requirements/room-requirements-read-model';
import {
  buildCancelRootCommand,
  createControlRoomKernelCommandTransport,
} from '@/features/rooms/kernel/room-kernel-command-transport';
import { evaluateRoomKernelControlGate } from '@/features/rooms/kernel/room-kernel-control-gate';
import { parseSnapshot } from '@/features/rooms/kernel/RoomKernelLivePanel';
import { createPreviewTransport } from './preview-control-transport';

describe('preview control transport', () => {
  it('imports real browser clipboard Files into owner-scoped preview media receipts', async () => {
    const transport = createPreviewTransport();
    const image = new File(
      [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])],
      'clipboard.png',
      { type: 'image/png' },
    );

    await expect(transport.pasteImages?.({
      sessionId: 'session-preview',
      files: [image],
      maxFiles: 1,
    })).resolves.toEqual([
      expect.objectContaining({
        id: expect.stringMatching(/^media_preview_[a-f0-9]{24}$/),
        name: 'clipboard.png',
        mimeType: 'image/png',
        byteSize: image.size,
        sessionId: 'session-preview',
        sha256: expect.stringMatching(/^[a-f0-9]{64}$/),
      }),
    ]);
    const roomReceipts = await transport.pasteImages?.({
      roomId: 'room-preview',
      files: [image],
      maxFiles: 1,
    });
    expect(roomReceipts).toEqual([
      expect.objectContaining({
        roomId: 'room-preview',
        sha256: expect.stringMatching(/^[a-f0-9]{64}$/),
      }),
    ]);
    expect(roomReceipts?.[0]).not.toHaveProperty('sessionId');
  });

  it('projects Room ownership onto the participant Sessions listed to Agent', async () => {
    const transport = createPreviewTransport();
    const response = record(await transport.request({
      pathId: 'agent.sessions.list',
      query: { limit: 100 },
    }));
    const sessions = response.sessions as Record<string, unknown>[];

    expect(sessions.find((session) => session.id === 'session-room-present')).toMatchObject({
      roomParticipant: {
        roomId: 'room-preview',
        participantId: 'participant-present',
        status: 'active',
      },
    });
    expect(sessions.find((session) => session.id === 'session-room-firstlight')).toMatchObject({
      roomParticipant: {
        roomId: 'room-preview',
        participantId: 'participant-firstlight',
        status: 'active',
      },
    });
    expect(sessions.find((session) => session.id === 'session-preview')).not.toHaveProperty('roomParticipant');
  });

  it('keeps the Room task view and its stop action on the production contracts', async () => {
    const transport = createPreviewTransport();
    const gate = await evaluateRoomKernelControlGate(await transport.capabilities());
    expect(gate).toMatchObject({ readEnabled: true, commandEnabled: true, panicEnabled: false });

    const raw = await transport.request({
      pathId: 'agent.room.kernel.snapshot',
      params: { roomId: 'room-preview' },
    });
    const snapshot = parseSnapshot(raw, 'room-preview');
    expect(snapshot.roots).toHaveLength(1);
    expect(snapshot.roots[0]).toMatchObject({ state: 'running', facilitatorParticipantId: 'participant-present' });
    expect(snapshot.tasks).toEqual(expect.arrayContaining([
      expect.objectContaining({
        taskId: 'room-preview:root-preview:task-review',
        currentOwnerParticipantId: 'participant-firstlight',
        ownershipRevision: 1,
      }),
    ]));
    expect(snapshot.receipts).toEqual(expect.arrayContaining([
      expect.objectContaining({
        receiptId: 'room-preview:root-preview:receipt-owner-review',
        details: expect.objectContaining({
          fromParticipantId: 'participant-present',
          toParticipantId: 'participant-firstlight',
        }),
      }),
    ]));

    const requirement = parseRoomRequirementsReadProjection(
      record(record(raw).requirementsByRootId)[snapshot.roots[0]!.rootId],
    );
    expect(requirement.anchors[0]?.originalText).toBe('核对多端网关回放与责任闭环');

    const receipt = await createControlRoomKernelCommandTransport(transport).execute(
      buildCancelRootCommand(
        {
          roomId: 'room-preview',
          rootId: snapshot.roots[0]!.rootId,
          generation: snapshot.roots[0]!.generation,
        },
        { commandId: 'preview-stop', sourceId: 'preview-test', createdAtMs: 1 },
      ),
    );
    expect(receipt).toMatchObject({
      commandId: 'preview-stop',
      receiptKind: 'root_cancelled',
      status: 'applied',
      generation: 2,
    });
  });

  it('returns verifiable Room projections for preview creation and topic mutations', async () => {
    const transport = createPreviewTransport();
    const created = record(await transport.request({
      pathId: 'agent.rooms.create',
      body: {
        title: '发布前检查',
        roomKind: 'collaboration',
        avatar: 'briefcase',
        description: '核对发布边界',
        scenarioPrompt: '',
        routingPolicy: 'natural',
        routingConfig: { maxResponders: 1, naturalJitter: 0, fallbackParticipantId: '' },
        workspaceRoots: ['/Volumes/work/learnA'],
        executionMode: 'workspace_managed',
        participants: [
          {
            roleId: 'companion-present-v1',
            roleVersion: '1',
            displayName: '澄·今',
            collaborationRole: 'coordinator',
          },
          {
            roleId: 'companion-firstlight-v1',
            roleVersion: '1',
            displayName: '澄·初',
            collaborationRole: 'researcher',
          },
        ],
      },
    }));
    const createdRoom = record(created.room);
    expect(createdRoom).toMatchObject({
      schemaVersion: 'rag-ime.agent-room.v1',
      id: 'room-preview-1',
      title: '发布前检查',
      status: 'active',
      workspaceRoots: ['/Volumes/work/learnA'],
      participants: [
        expect.objectContaining({ displayName: '澄·今', collaborationRole: 'coordinator' }),
        expect.objectContaining({ displayName: '澄·初', collaborationRole: 'researcher' }),
      ],
    });

    const snapshot = record(await transport.request({
      pathId: 'agent.room.snapshot',
      params: { roomId: 'room-preview-1' },
    }));
    expect(snapshot).toMatchObject({
      schemaVersion: 'rag-ime.agent-room-snapshot.v1',
      ok: true,
      room: { id: 'room-preview-1', title: '发布前检查' },
      events: [],
      lastSequence: 0,
    });

    const kernel = parseSnapshot(await transport.request({
      pathId: 'agent.room.kernel.snapshot',
      params: { roomId: 'room-preview-1' },
    }), 'room-preview-1');
    expect(kernel).toMatchObject({
      roomId: 'room-preview-1',
      roots: [expect.objectContaining({ roomId: 'room-preview-1' })],
    });

    const topicCreated = record(await transport.request({
      pathId: 'agent.room.topic.create',
      params: { roomId: 'room-preview-1' },
      body: { title: '发布风险', summary: '核对上线边界' },
    }));
    expect(record(topicCreated.room).topics).toEqual([
      expect.objectContaining({
        id: 'room-preview-1:topic-1',
        title: '发布风险',
        summary: '核对上线边界',
        status: 'active',
      }),
    ]);

    const topicActivated = record(await transport.request({
      pathId: 'agent.room.topic.update',
      params: { roomId: 'room-preview-1' },
      body: { topicId: 'room-preview-1:topic-1', activate: true },
    }));
    expect(record(topicActivated.room)).toMatchObject({
      id: 'room-preview-1',
      activeTopicId: 'room-preview-1:topic-1',
    });
  });

  it('exercises background job logs and cancellation through production routes', async () => {
    const transport = createPreviewTransport();
    const sessionId = 'session-states';
    const events: Record<string, unknown>[] = [];
    const unsubscribe = transport.subscribe(
      {
        pathId: 'agent.session.events',
        params: { sessionId },
        lastEventId: `${sessionId}:7`,
      },
      { next: (event) => events.push(record(event)) },
    );
    const listed = record(await transport.request({
      pathId: 'agent.session.backgroundJobs.list',
      params: { sessionId },
    }));
    const jobs = listed.items as Record<string, unknown>[];
    const running = jobs.find((job) => job.status === 'running');
    expect(running).toMatchObject({ label: '前端生产构建' });

    const jobId = String(running?.jobId ?? '');
    const logs = record(await transport.request({
      pathId: 'agent.session.backgroundJob.logs',
      params: { sessionId, jobId },
      query: { cursor: 0 },
    }));
    expect(logs.text).toContain('vite build');

    const cancelled = record(await transport.request({
      pathId: 'agent.session.backgroundJob.cancel',
      params: { sessionId, jobId },
      body: { reason: 'preview-test' },
    }));
    expect(cancelled.job).toMatchObject({ jobId, status: 'cancelled' });
    expect(events).toEqual(expect.arrayContaining([
      expect.objectContaining({
        eventType: 'background_job_cancelled',
        payload: expect.objectContaining({
          job: expect.objectContaining({ jobId, status: 'cancelled' }),
        }),
      }),
    ]));

    const refreshed = record(await transport.request({
      pathId: 'agent.session.backgroundJobs.list',
      params: { sessionId },
    }));
    expect(refreshed.items).toEqual(expect.arrayContaining([
      expect.objectContaining({ jobId, status: 'cancelled' }),
    ]));
    unsubscribe();
  });

  it('keeps the Input preview on real settings and lexicon contracts', async () => {
    const transport = createPreviewTransport();
    const capabilities = await transport.capabilities();
    expect(capabilities.features).toMatchObject({
      configurationSettingsWorkContract: true,
      managementWorkContract: true,
    });

    const source = record(await transport.request({ pathId: 'input.source.get' }));
    expect(source).toMatchObject({ typingReady: true, readinessState: 'ready' });

    const schema = record(await transport.request({ pathId: 'configuration.schema' }));
    const sections = schema.sections as Record<string, unknown>[];
    expect(sections.map((section) => section.id)).toEqual(expect.arrayContaining([
      'interaction',
      'models',
      'lexiconOrganization',
    ]));

    const review = record(await transport.request({ pathId: 'input.lexicon.review' }));
    expect(review).toMatchObject({
      schemaVersion: 'rag-ime.rime-lexicon-review.v1',
      ok: true,
      applySupported: true,
      organization: expect.objectContaining({
        schemaVersion: 'rag-ime.lexicon-organization-status.v1',
        owner: 'maintenance_poll',
        decoderOwner: 'rime',
        enabled: true,
      }),
    });

    const preview = record(await transport.request({
      pathId: 'configuration.settings.preview',
      body: {
        changes: { 'lexiconOrganization.runsPerDay': 4 },
        expectedRuntimeRevision: 12,
      },
    }));
    const applied = record(await transport.request({
      pathId: 'configuration.settings.apply',
      body: {
        changes: { 'lexiconOrganization.runsPerDay': 4 },
        expectedRuntimeRevision: 12,
        previewToken: preview.previewToken as string,
        payloadSha256: preview.payloadSha256 as string,
        confirmText: 'apply',
      },
    }));
    expect(applied).toMatchObject({
      ok: true,
      pathId: 'configuration.settings.apply',
      payloadSha256: preview.payloadSha256,
      rollbackAvailable: true,
    });
    expect(record(record(
      record(await transport.request({ pathId: 'configuration.settings' })).settings,
    ).lexiconOrganization).runsPerDay).toBe(4);

    const rolledBack = record(await transport.request({
      pathId: 'configuration.settings.rollback',
      body: {
        receiptId: applied.receiptId as string,
        rollbackToken: applied.rollbackToken as string,
        payloadSha256: preview.payloadSha256 as string,
        confirmText: 'rollback',
      },
    }));
    expect(rolledBack).toMatchObject({
      ok: true,
      pathId: 'configuration.settings.rollback',
      payloadSha256: preview.payloadSha256,
      rollbackAvailable: false,
    });
  });

  it('keeps History preview data and tombstone receipts on production routes', async () => {
    const transport = createPreviewTransport();
    const page = record(await transport.request({
      pathId: 'history.page',
      query: { query: 'TextEdit', filter: '' },
    }));
    expect(page.items).toEqual([
      expect.objectContaining({ id: 201, source: 'rime_commit' }),
    ]);

    const detail = record(await transport.request({
      pathId: 'history.detail',
      query: { eventId: 201 },
    }));
    expect(record(detail.item)).toMatchObject({
      id: 201,
      auxiliaryContext: expect.objectContaining({ available: true }),
      feedback: expect.objectContaining({ acceptedCount: 1 }),
    });

    const preview = record(await transport.request({
      pathId: 'history.tombstone.preview',
      body: { eventId: 201, reason: 'control-center-history', expectedRuntimeRevision: 12 },
    }));
    const applied = record(await transport.request({
      pathId: 'history.tombstone.apply',
      body: {
        eventId: 201,
        reason: 'control-center-history',
        expectedRuntimeRevision: 12,
        previewToken: preview.previewToken as string,
        payloadSha256: preview.payloadSha256 as string,
        confirmText: 'apply',
      },
    }));
    expect(applied).toMatchObject({
      ok: true,
      pathId: 'history.tombstone.apply',
      rollbackAvailable: true,
    });
  });

  it('persists Knowledge preview mutations and projects reparse work through jobs', async () => {
    const transport = createPreviewTransport();
    const created = record(await transport.request({
      pathId: 'knowledgeBases.create',
      body: {
        name: '迁移证据库',
        description: '只包含外部项目文档',
        agentEnabled: false,
        parserProvider: 'auto',
      },
    }));
    const createdBase = record(created.base);
    const createdId = String(createdBase.id);
    expect(createdBase).toMatchObject({ name: '迁移证据库', description: '只包含外部项目文档' });

    const listed = arrayRecords(record(await transport.request({
      pathId: 'knowledgeBases.list',
    })).items);
    expect(listed).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: createdId, name: '迁移证据库' }),
    ]));

    const updated = record(await transport.request({
      pathId: 'knowledgeBases.update',
      params: { kbId: createdId },
      body: {
        name: '迁移证据库 · 已核验',
        description: '服务端已确认',
        expectedRevision: Number(createdBase.revision),
      },
    }));
    expect(record(updated.base)).toMatchObject({
      id: createdId,
      name: '迁移证据库 · 已核验',
      description: '服务端已确认',
      revision: 2,
    });
    expect(record(record(await transport.request({
      pathId: 'knowledgeBases.get',
      params: { kbId: createdId },
    })).base)).toMatchObject({ name: '迁移证据库 · 已核验' });

    await transport.request({
      pathId: 'knowledgeBases.document.retry',
      params: { kbId: 'kb:preview-project-docs', fileId: 'file:preview-yuxi' },
      body: { stage: 'parse', parserProvider: 'builtin', expectedRevision: 1 },
    });
    const jobs = arrayRecords(record(await transport.request({
      pathId: 'knowledgeBases.jobs.list',
      params: { kbId: 'kb:preview-project-docs' },
    })).items);
    expect(jobs).toEqual([
      expect.objectContaining({
        fileId: 'file:preview-yuxi',
        fileName: 'agent-runtime-notes.md',
        kind: 'reparse',
        status: 'succeeded',
        progress: 1,
      }),
    ]);
  });

  it('keeps Work Documents preview data and terminal receipts on production routes', async () => {
    const transport = createPreviewTransport();
    const listed = record(await transport.request({
      pathId: 'workDocuments.list',
    }));
    expect(listed.items).toEqual([
      expect.objectContaining({
        documentId: 'workdoc_0123456789abcdef0123456789abcdef',
        state: 'active',
      }),
    ]);

    const archived = record(await transport.request({
      pathId: 'workDocuments.archive',
      params: { documentId: 'workdoc_0123456789abcdef0123456789abcdef' },
      body: { terminalReceiptId: 'terminal-receipt-preview' },
    }));
    expect(archived).toMatchObject({
      ok: true,
      document: expect.objectContaining({ state: 'archived' }),
      receipt: expect.objectContaining({ operation: 'archive', status: 'applied' }),
    });

    const history = record(await transport.request({
      pathId: 'workDocuments.history.search',
      query: { query: '' },
    }));
    expect(history.items).toEqual(expect.arrayContaining([
      expect.objectContaining({ state: 'archived', terminalReceiptId: expect.any(String) }),
    ]));
  });
  it('rolls an installed extension back once with a truthful version and display name', async () => {
    const transport = createPreviewTransport();
    const before = arrayRecords(record(await transport.request({
      pathId: 'agent.extensions.list',
    })).items);
    expect(before).toEqual([
      expect.objectContaining({
        id: 'timeline-inspector',
        displayName: 'Timeline Inspector',
        version: '1.0.0',
        rollbackAvailable: true,
      }),
    ]);

    const preview = record(await transport.request({
      pathId: 'agent.extensions.preview',
      body: { action: 'rollback', pluginId: 'timeline-inspector' },
    }));
    expect(record(preview.summary)).toMatchObject({
      action: 'rollback',
      pluginId: 'timeline-inspector',
      displayName: 'Timeline Inspector',
      version: '0.9.0',
    });

    await expect(transport.request({
      pathId: 'agent.extensions.apply',
      body: {
        previewToken: preview.previewToken as string,
        payloadSha256: preview.payloadSha256 as string,
        confirmText: 'apply',
      },
    })).resolves.toMatchObject({
      ok: true,
      receipt: { receiptId: 'plugin:rollback:preview' },
    });

    const after = arrayRecords(record(await transport.request({
      pathId: 'agent.extensions.list',
    })).items);
    expect(after).toEqual([
      expect.objectContaining({
        id: 'timeline-inspector',
        displayName: 'Timeline Inspector',
        version: '0.9.0',
        rollbackAvailable: false,
      }),
    ]);
    await expect(transport.request({
      pathId: 'agent.extensions.preview',
      body: { action: 'rollback', pluginId: 'timeline-inspector' },
    })).rejects.toThrow('这个扩展当前没有可恢复的上一版本。');
  });

});

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function arrayRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record) : [];
}
