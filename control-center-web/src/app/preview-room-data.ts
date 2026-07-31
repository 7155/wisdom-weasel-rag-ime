import { PREVIEW_REPORT_BYTES } from '@/features/agent/preview-data';

function roomPostBlock(
  id: string,
  type: string,
  presentationKind: string,
  summary: string,
  data: Record<string, unknown>,
): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.agent-block.v1',
    id,
    type,
    status: 'completed',
    presentationKind,
    data,
    summary,
    source: {},
    visibility: 'room_post',
    digest: 'd'.repeat(64),
    ref: `ref:${id}`,
    generation: 0,
  };
}

export function previewRoomSnapshot(roomId: string) {
  const now = Date.now() - 60_000;
  const rootId = `${roomId}:turn-1`;
  const participants = [
    previewParticipant(roomId, 'participant-present', 'session-room-present', 'companion-present-v1', '澄·今', 0),
    previewParticipant(roomId, 'participant-firstlight', 'session-room-firstlight', 'companion-firstlight-v1', '澄·初', 1),
  ];
  const event = (
    sequence: number,
    eventType: string,
    participantId: string | null,
    payload: Record<string, unknown>,
  ) => ({
    schemaVersion: 'rag-ime.agent-room-event.v1',
    eventId: `${roomId}:${sequence}`,
    roomId,
    sequence,
    turnId: rootId,
    eventType,
    participantId,
    sourceSessionId: participantId === 'participant-present'
      ? 'session-room-present'
      : participantId === 'participant-firstlight'
        ? 'session-room-firstlight'
        : '',
    createdAtMs: now + sequence,
    payload,
    resumeToken: `${roomId}:${sequence}`,
  });
  const roomPost = (
    postId: string,
    participantId: string,
    dispatchId: string,
    content: string,
    createdAtMs: number,
    blocks?: Record<string, unknown>[],
  ) => ({
    schemaVersion: 'wisdom-weasel.room-post.v2',
    postId,
    roomId,
    rootId,
    generation: 0,
    dispatchId,
    authorActorRef: participantId,
    kind: 'result',
    visibility: 'room',
    content,
    idempotencyKey: postId,
    publicationSource: { kind: 'room_commit', ref: `commit:${postId}` },
    createdAtMs,
    ...(blocks ? { blocks } : {}),
  });
  const events = [
    event(1, 'user_message', null, {
      messageId: 'room-user-1', rootId,
      text: '并行检查 Agent UI 与 Control API 的集成边界。',
    }),
    event(2, 'route_decision', 'participant-present', {
      rootId, dispatchId: 'dispatch-present',
      targetParticipantId: 'participant-present', targetDisplayName: '澄·今',
      reason: '负责前端时间线', summary: '澄·今已接手前端时间线',
    }),
    event(3, 'route_decision', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight',
      targetParticipantId: 'participant-firstlight', targetDisplayName: '澄·初',
      reason: '负责接口边界', summary: '澄·初已接手接口边界',
    }),
    event(4, 'participant_activity', 'participant-present', {
      rootId, dispatchId: 'dispatch-present', sourceEventId: 'tool-present-start',
      sourceEventType: 'tool_started', toolCallId: 'tool-present', toolName: 'read_file',
      summary: '读取 Room 时间线实现',
    }),
    event(5, 'participant_activity', 'participant-present', {
      rootId, dispatchId: 'dispatch-present', sourceEventId: 'tool-present-finish',
      sourceEventType: 'tool_finished', toolCallId: 'tool-present', toolName: 'read_file',
      summary: '已核对流式投影与 Post 替换', isError: false,
    }),
    event(6, 'participant_delta', 'participant-present', {
      rootId, dispatchId: 'dispatch-present', messageId: 'room-assistant-1',
      delta: '我会把工具进展留在当前消息里；完成后，这里会直接变成清晰的公开结果。',
    }),
    event(7, 'room_post', 'participant-present', {
      rootId, dispatchId: 'dispatch-present',
      post: roomPost(
        'room-post-present', 'participant-present', 'dispatch-present',
        '我已把实时进展收拢在同一条消息里；完成后会在原处留下清晰结果。',
        now + 7,
        /* The same managed report a Session turn delivers. Room routes results
           through the identical AgentBlocks renderer, so this is what proves
           the two workspaces share one result language rather than merely
           looking alike. Room post blocks carry the full agent-block.v1 shape
           — summary/source/visibility/digest/ref/generation are all required,
           and a post whose blocks fail validation is dropped whole. */
        [
          roomPostBlock('room-post-text', 'text', 'markdown', '结果说明', {
            text: '我已把实时进展收拢在同一条消息里；完成后会在原处留下清晰结果。',
          }),
          roomPostBlock('room-post-report', 'file', 'file', '词库健康报告', {
            mediaId: 'media_previewreport01',
            name: 'lexicon-health-report.html',
            mimeType: 'text/html',
            byteSize: PREVIEW_REPORT_BYTES,
            sha256: 'c'.repeat(64),
          }),
        ],
      ),
    }),
    event(8, 'turn_completed', 'participant-present', {
      rootId, dispatchId: 'dispatch-present', summary: '前端时间线检查完成',
    }),
    event(9, 'participant_activity', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight', sourceEventId: 'tool-firstlight-start',
      sourceEventType: 'tool_started', toolCallId: 'tool-firstlight', toolName: 'control_api',
      summary: '检查路由与权限回执',
    }),
    event(10, 'participant_delta', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight', messageId: 'room-assistant-2',
      delta: 'Control API 只在服务端确认后更新权限状态，失败回执不会伪装成已生效。',
    }),
    event(11, 'participant_activity', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight', sourceEventId: 'tool-firstlight-finish',
      sourceEventType: 'tool_finished', toolCallId: 'tool-firstlight', toolName: 'control_api',
      summary: '路由与权限回执检查完成', isError: false,
    }),
    event(12, 'room_post', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight',
      post: roomPost(
        'room-post-firstlight', 'participant-firstlight', 'dispatch-firstlight',
        '我核对了工作目录和授权边界：需要确认的操作会等你，公开消息也不会重复出现。',
        now + 12,
      ),
    }),
    event(13, 'turn_completed', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight', summary: '接口边界检查完成',
    }),
    event(14, 'turn_completed', null, { rootId, summary: '协作检查完成' }),
  ];
  return {
    schemaVersion: 'rag-ime.agent-room-snapshot.v1',
    ok: true,
    room: {
      schemaVersion: 'rag-ime.agent-room.v1',
      id: roomId,
      title: '迁移作战室',
      status: 'active',
      executionMode: 'workspace_managed',
      roomKind: 'collaboration',
      avatar: 'briefcase',
      description: '验证责任交接、流式投影与多端控制面板',
      routingPolicy: 'natural',
      moderatorParticipantId: 'participant-present',
      activeTopicId: 'topic-preview',
      workspaceRoots: ['/Volumes/work/wisdom-weasel-rag-ime'],
      topics: [{
        schemaVersion: 'rag-ime.agent-room-topic.v1',
        id: 'topic-preview',
        roomId,
        title: '网关升级',
        summary: '保持 Pi Session 独立，以 WorkItem 责任账本完成协作闭环。',
        status: 'active',
        ordinal: 0,
        createdAtMs: now,
        updatedAtMs: now,
      }],
      artifacts: [],
      workItems: [{
        schemaVersion: 'rag-ime.agent-room-work-item.v1',
        id: 'room-work:preview',
        roomId,
        topicId: 'topic-preview',
        rootTurnId: `${roomId}:turn-1`,
        rootWorkId: 'room-work:preview',
        parentWorkId: '',
        objective: '核对多端网关回放与责任闭环',
        expectedOutput: '测试证据和风险说明',
        acceptanceCriteria: ['目标回合接受后才转移 owner', '交付经过协调者验收'],
        accountableParticipantId: 'participant-present',
        currentOwnerParticipantId: 'participant-firstlight',
        offeredToParticipantId: '',
        createdByParticipantId: 'participant-present',
        clientMessageId: 'preview-assignment',
        state: 'review',
        depth: 1,
        revision: 1,
        resultSummary: '已完成回放游标与公平队列测试。',
        artifactRefs: [],
        evidenceRefs: ['test:room-replay'],
        blocker: {},
        acceptedTurnId: 'turn:preview-worker',
        createdAtMs: now + 2,
        updatedAtMs: now + 7,
        completedAtMs: null,
      }],
      createdAtMs: now,
      updatedAtMs: now + events.length,
      lastEventSequence: events.length,
      participants,
    },
    events,
    firstSequence: 1,
    lastSequence: events.length,
    resumeToken: `${roomId}:${events.length}`,
    truncated: false,
  };
}

export function previewRoomKernelSnapshot(roomId: string): Record<string, unknown> {
  const now = Date.now() - 24_000;
  const rootId = `${roomId}:root-preview`;
  const originalText = '核对多端网关回放与责任闭环';
  const anchorId = `${rootId}:anchor`;
  const catalogRevisionId = `${rootId}:requirements-v1`;
  return {
    roomId,
    lastSequence: 1,
    snapshotHash: `sha256:${'b'.repeat(64)}`,
    roots: [{
      schemaVersion: 'wisdom-weasel.room-root-execution.v3',
      rootId,
      roomId,
      generation: 1,
      state: 'running',
      facilitatorParticipantId: 'participant-present',
      reporterParticipantId: null,
      reporterSelectionReceiptId: null,
      requirementAnchorRef: anchorId,
      createdByActorRef: 'user:preview',
      terminalReceiptId: null,
      activeProfileRef: null,
      budgetPolicyRef: 'budget:preview',
      createdAtMs: now,
    }],
    tasks: [{
      schemaVersion: 'wisdom-weasel.room-task.v3',
      taskId: `${rootId}:task-interface`,
      rootId,
      parentTaskId: null,
      taskKind: 'work',
      currentOwnerParticipantId: 'participant-present',
      ownershipRevision: 0,
      ownershipReceiptId: null,
      objective: '核对 Control API 边界',
      expectedOutput: '边界核对结果',
      requirementItemIds: [`${catalogRevisionId}:item:1`],
      acceptanceCriterionIds: [`${catalogRevisionId}:criterion:1`],
      contextEvidenceRefs: [],
      invitationId: null,
      reviewOfTaskIds: [],
      reviewAuthorParticipantIds: [],
      reviewState: 'not_required',
      revision: 0,
      state: 'active',
    }, {
      schemaVersion: 'wisdom-weasel.room-task.v3',
      taskId: `${rootId}:task-review`,
      rootId,
      parentTaskId: `${rootId}:task-interface`,
      taskKind: 'review',
      currentOwnerParticipantId: 'participant-firstlight',
      ownershipRevision: 1,
      ownershipReceiptId: `${rootId}:receipt-owner-review`,
      objective: '独立验收多端回放证据',
      expectedOutput: '独立验收结论',
      requirementItemIds: [`${catalogRevisionId}:item:1`],
      acceptanceCriterionIds: [`${catalogRevisionId}:criterion:1`],
      contextEvidenceRefs: [],
      invitationId: null,
      reviewOfTaskIds: [`${rootId}:task-interface`],
      reviewAuthorParticipantIds: ['participant-firstlight'],
      reviewState: 'in_review',
      revision: 1,
      state: 'review',
    }],
    dispatches: [],
    posts: [{
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: `${rootId}:post-progress`,
      roomId,
      rootId,
      generation: 1,
      authorActorRef: '澄·初',
      kind: 'finding',
      visibility: 'room',
      content: '已核对回放游标与权限边界，正在等待独立验收。',
      idempotencyKey: `${rootId}:post-progress`,
      publicationSource: { kind: 'room_commit', ref: 'commit:preview-progress' },
      createdAtMs: now + 10_000,
    }],
    sessions: [{
      sessionId: 'session-room-present',
      rootId,
      generation: 1,
      state: 'running',
      updatedAtMs: now + 20_000,
    }],
    receipts: [{
      schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1',
      receiptId: `${rootId}:receipt-owner-review`,
      rootId,
      commandId: null,
      receiptKind: 'accepted',
      status: 'applied',
      generation: 1,
      details: {
        operation: 'task_owner_transfer',
        taskId: `${rootId}:task-review`,
        fromParticipantId: 'participant-present',
        toParticipantId: 'participant-firstlight',
        ownershipRevision: 1,
      },
      createdAtMs: now + 15_000,
    }],
    cancellationSurfaces: [],
    requirementsByRootId: {
      [rootId]: {
        projectionSource: 'canonical_fixture',
        rootId,
        anchors: [{
          anchor: {
            schemaVersion: 'wisdom-weasel.requirement-anchor.v1',
            anchorId,
            rootId,
            rootSequence: 1,
            originalContentSha256: 'a'.repeat(64),
            originalByteLength: new TextEncoder().encode(originalText).byteLength,
            createdBy: 'user:preview',
            authenticity: 'original_user_bytes',
            provenance: { requestId: 'request:preview-room-task' },
            createdAtMs: now,
          },
          originalText,
          integrityStatus: 'verified',
        }],
        catalog: {
          schemaVersion: 'wisdom-weasel.requirement-catalog-revision.v1',
          catalogRevisionId,
          rootId,
          revision: 1,
          supersedesRevisionId: null,
          anchorRefs: [anchorId],
          items: [{
            itemId: `${rootId}:item-1`,
            statement: '回放游标与权限边界均有可复查证据',
            kind: 'explicit_user_requirement',
            state: 'active',
          }],
          acceptanceCriteria: [{
            criterionId: `${rootId}:criterion-1`,
            itemId: `${rootId}:item-1`,
            acceptanceCriterionFullNameZh: '多端回放与权限边界验收标准',
            criterionKind: 'user_journey',
            expectedReceiptTypes: ['test'],
            statement: '公开结果不重复，越权操作不会被静默执行',
          }],
          changeReason: '把原始请求整理成可核对的任务目录',
          provenance: { source: 'preview-room-task' },
          payloadHash: 'c'.repeat(64),
          createdBy: 'requirements-governor',
          createdAtMs: now + 1,
        },
        receiptAssessments: [],
        deliveryGate: null,
        conflicts: [],
        peerReviewRounds: [],
      },
    },
  };
}

export function previewRoomKernelReceipt(command: Record<string, unknown>): Record<string, unknown> {
  const commandKind = stringValue(command.commandKind);
  const generation = Number(command.generation) || 0;
  const commandId = stringValue(command.commandId) || 'preview-room-command';
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1',
    receiptId: `preview:${commandId}`,
    rootId: command.rootId === null ? null : stringValue(command.rootId),
    commandId,
    receiptKind: commandKind === 'panic' ? 'panic' : 'root_cancelled',
    status: 'applied',
    generation: commandKind === 'cancel_root' ? generation + 1 : generation,
    details: { preview: true },
    createdAtMs: Date.now(),
  };
}

export function previewRoomKernelRouteManifest(): Record<string, unknown>[] {
  return [
    previewRoomKernelRoute('agent.room.kernel.snapshot', 'GET', false, ['agent.read'], []),
    previewRoomKernelRoute('agent.room.kernel.events', 'GET', true, ['agent.read'], ['lastEventId']),
    previewRoomKernelRoute('agent.room.kernel.command', 'POST', false, ['agent.write'], []),
  ];
}

function previewRoomKernelRoute(
  pathId: string,
  method: string,
  subscription: boolean,
  remoteScopes: string[],
  query: string[],
): Record<string, unknown> {
  return {
    pathId,
    method,
    remoteSafe: true,
    subscription,
    params: ['roomId'],
    query,
    remoteScopes,
  };
}

function previewParticipant(
  roomId: string,
  id: string,
  sessionId: string,
  roleId: string,
  displayName: string,
  ordinal: number,
) {
  return {
    schemaVersion: 'rag-ime.agent-participant.v1',
    id,
    roomId,
    sessionId,
    roleId,
    roleVersion: '1',
    displayName,
    collaborationRole: ordinal === 0 ? 'coordinator' : 'researcher',
    status: 'active',
    ordinal,
    createdAtMs: 1,
    lastSpokeAtMs: null,
  };
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
