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
  const waveId = `${roomId}:wave-implementation`;
  const participants = [
    previewParticipant(roomId, 'participant-present', 'session-room-present', 'companion-present-v1', 'Earth', 0),
    previewParticipant(roomId, 'participant-firstlight', 'session-room-firstlight', 'companion-firstlight-v1', 'Mars', 1),
    previewParticipant(roomId, 'participant-future', 'session-room-future', 'companion-future-v1', 'Venus', 2),
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
        : participantId === 'participant-future'
          ? 'session-room-future'
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
      text: '并行实现 Room 任务图与依赖数据，整合后交给独立伙伴复核。',
    }),
    event(2, 'route_decision', 'participant-present', {
      rootId, dispatchId: 'dispatch-present',
      targetParticipantId: 'participant-present', targetDisplayName: 'Earth',
      reason: '负责任务图交互', summary: 'Earth 已接手任务图交互',
    }),
    event(3, 'route_decision', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight',
      targetParticipantId: 'participant-firstlight', targetDisplayName: 'Mars',
      reason: '负责依赖数据', summary: 'Mars 已接手依赖数据',
    }),
    event(4, 'participant_activity', 'participant-present', {
      rootId, dispatchId: 'dispatch-present', sourceEventId: 'tool-present-start',
      sourceEventType: 'tool_started', toolCallId: 'tool-present', toolName: 'read_file',
      waveId, phaseName: '并行实现', parallelIndex: 0, parallelSize: 2,
      task: '实现 Room 任务图交互', expectedOutput: '可复查的任务图交互实现',
      acceptanceCriteria: ['公开时间线保持事件顺序', '思维与工具默认折叠'],
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
    event(8, 'participant_activity', 'participant-present', {
      rootId,
      dispatchId: 'dispatch-present',
      responsePostId: 'room-post-present',
      sourceEventId: 'message-present-completed',
      sourceEventType: 'message_completed',
      runtimeTurnId: 'runtime-turn-present',
      status: 'draft_ready',
      summary: '正在整理正式 Post',
      provider: 'openai',
      model: 'gpt-5.4',
      usageReported: true,
      cacheUsageReported: true,
      usage: { input: 12_480, output: 642, cacheRead: 9_600, cacheWrite: 0, totalTokens: 22_722 },
    }),
    event(9, 'turn_completed', 'participant-present', {
      rootId, dispatchId: 'dispatch-present', summary: '前端时间线检查完成',
    }),
    event(10, 'participant_activity', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight', sourceEventId: 'tool-firstlight-start',
      sourceEventType: 'tool_started', toolCallId: 'tool-firstlight', toolName: 'control_api',
      waveId, phaseName: '并行实现', parallelIndex: 1, parallelSize: 2,
      task: '实现 Room 依赖数据投影', expectedOutput: '可核验的路由与权限投影',
      acceptanceCriteria: ['失败回执不伪装成功', '投影保留来源与边界'],
      summary: '检查路由与权限回执',
    }),
    event(11, 'participant_delta', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight', messageId: 'room-assistant-2',
      delta: 'Control API 只在服务端确认后更新权限状态，失败回执不会伪装成已生效。',
    }),
    event(12, 'participant_activity', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight', sourceEventId: 'tool-firstlight-finish',
      sourceEventType: 'tool_finished', toolCallId: 'tool-firstlight', toolName: 'control_api',
      summary: '路由与权限回执检查完成', isError: false,
    }),
    event(13, 'room_post', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight',
      post: roomPost(
        'room-post-firstlight', 'participant-firstlight', 'dispatch-firstlight',
        '我核对了工作目录和授权边界：需要确认的操作会等你，公开消息也不会重复出现。',
        now + 13,
      ),
    }),
    event(14, 'participant_activity', 'participant-firstlight', {
      rootId,
      dispatchId: 'dispatch-firstlight',
      responsePostId: 'room-post-firstlight',
      sourceEventId: 'message-firstlight-completed',
      sourceEventType: 'message_completed',
      runtimeTurnId: 'runtime-turn-firstlight',
      status: 'draft_ready',
      summary: '正在整理正式 Post',
      provider: 'anthropic',
      model: 'claude-sonnet-4-5',
      usageReported: true,
      cacheUsageReported: true,
      usage: { input: 8_320, output: 418, cacheRead: 6_400, cacheWrite: 320, totalTokens: 15_458 },
    }),
    event(15, 'turn_completed', 'participant-firstlight', {
      rootId, dispatchId: 'dispatch-firstlight', summary: '依赖数据检查完成',
    }),
    event(16, 'turn_completed', null, { rootId, summary: '协作检查完成' }),
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
      description: '验证并行实现、整合依赖与独立复核',
      routingPolicy: 'natural',
      moderatorParticipantId: 'participant-present',
      activeTopicId: 'topic-preview',
      workspaceRoots: ['/Volumes/work/wisdom-weasel-rag-ime'],
      topics: [{
        schemaVersion: 'rag-ime.agent-room-topic.v1',
        id: 'topic-preview',
        roomId,
        title: '任务图依赖验证',
        summary: '两个实现分支并行推进，整合完成后交给独立伙伴复核。',
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
        objective: '并行实现 Room 任务图，整合后交给独立伙伴复核',
        expectedOutput: '可复查的依赖图与独立复核结论',
        acceptanceCriteria: ['两项实现任务可并行推进', '整合依赖两个实现结果', '独立伙伴复核整合版本'],
        accountableParticipantId: 'participant-present',
        currentOwnerParticipantId: 'participant-future',
        offeredToParticipantId: '',
        createdByParticipantId: 'participant-present',
        clientMessageId: 'preview-assignment',
        state: 'review',
        depth: 1,
        revision: 1,
        resultSummary: '两个实现分支已完成，整合版本正在等待独立复核。',
        artifactRefs: [],
        evidenceRefs: ['test:room-graph-ui', 'test:room-graph-data'],
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
    collaborationRole: ordinal === 0 ? 'coordinator' : ordinal === 2 ? 'reviewer' : 'researcher',
    status: 'active',
    ordinal,
    createdAtMs: 1,
    lastSpokeAtMs: null,
  };
}
