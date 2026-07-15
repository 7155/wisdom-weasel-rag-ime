import type { GeneratedContractName } from '@/contracts/generated';

export type ControlHttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';
export type ControlStreamKind = 'agent' | 'room' | 'control';

export interface ControlRouteDefinition {
  method: ControlHttpMethod;
  path: string;
  params?: Readonly<Record<string, readonly string[] | null>>;
  query?: readonly string[];
  requiredQuery?: readonly string[];
  body?: readonly string[];
  requiredBody?: readonly string[];
  responseContract?: GeneratedContractName;
  subscription?: ControlStreamKind;
  /** Binary responses are available only through the matching typed transport method. */
  binary?: boolean;
}

// These dotted ids are the cross-platform authority. Neither pages nor the
// native bridge may replace them with a URL supplied at runtime.
export const CONTROL_ROUTES = {
  'control.bootstrap': { method: 'GET', path: '/api/agent/control/bootstrap' },
  'control.capabilities': {
    method: 'GET',
    path: '/api/agent/control/capabilities',
  },
  'control.events': {
    method: 'GET',
    path: '/api/agent/events',
    query: ['lastEventId'],
    requiredQuery: ['lastEventId'],
    subscription: 'control',
  },
  'system.health': { method: 'GET', path: '/api/health' },
  'input.source.get': { method: 'GET', path: '/api/input-source' },
  'input.lexicon.review': {
    method: 'GET',
    path: '/api/rime-lexicon/review',
    query: ['limit', 'project'],
  },
  'input.lexicon.apply': {
    method: 'POST',
    path: '/api/rime-lexicon/apply',
    body: ['reviewToken', 'selectedKeys', 'confirmText', 'project', 'limit'],
    requiredBody: ['reviewToken', 'selectedKeys', 'confirmText'],
  },
  'input.lexicon.rollback': {
    method: 'POST',
    path: '/api/rime-lexicon/rollback',
    body: ['rollbackId'],
    requiredBody: ['rollbackId'],
  },
  'overview.get': { method: 'GET', path: '/api/overview' },

  'agent.runtime.get': {
    method: 'GET',
    path: '/api/agent/runtime',
    responseContract: 'agent-runtime.v1',
  },
  'agent.runtime.ensure': {
    method: 'POST',
    path: '/api/agent/runtime/ensure',
    body: ['sessionId'],
    requiredBody: ['sessionId'],
  },
  'agent.providers.get': { method: 'GET', path: '/api/agent/providers' },
  'agent.provider.auth.preview': {
    method: 'POST',
    path: '/api/agent/providers/auth/preview',
    body: ['provider', 'action'],
    requiredBody: ['provider', 'action'],
  },
  'agent.provider.auth.apply': {
    method: 'POST',
    path: '/api/agent/providers/auth/apply',
    body: ['previewToken', 'confirmText', 'apiKey'],
    requiredBody: ['previewToken', 'confirmText'],
  },
  'agent.provider.oauth.status': {
    method: 'GET',
    path: '/api/agent/providers/oauth/status',
    query: ['loginId'],
    requiredQuery: ['loginId'],
  },
  'agent.provider.oauth.cancel': {
    method: 'POST',
    path: '/api/agent/providers/oauth/cancel',
    body: ['loginId'],
    requiredBody: ['loginId'],
  },
  'agent.configuration.get': { method: 'GET', path: '/api/agent/configuration' },
  'agent.configuration.update': {
    method: 'POST',
    path: '/api/agent/configuration',
    body: ['expectedRevision', 'changes', 'updatedBy'],
    requiredBody: ['expectedRevision', 'changes'],
  },
  'agent.sessions.list': {
    method: 'GET',
    path: '/api/agent/sessions',
    query: ['includeArchived', 'includeInternal', 'limit'],
  },
  'agent.sessions.create': {
    method: 'POST',
    path: '/api/agent/sessions',
    body: [
      'title',
      'mode',
      'roleId',
      'roleVersion',
      'modelProfile',
      'toolProfileVersion',
      'workspaceRoots',
    ],
  },
  'agent.session.snapshot': {
    method: 'GET',
    path: '/api/agent/sessions/:sessionId/messages',
    params: { sessionId: null },
  },
  'agent.session.rename': {
    method: 'PATCH',
    path: '/api/agent/sessions/:sessionId',
    params: { sessionId: null },
    body: ['title'],
    requiredBody: ['title'],
  },
  'agent.session.archive': {
    method: 'PATCH',
    path: '/api/agent/sessions/:sessionId',
    params: { sessionId: null },
    body: ['archived'],
    requiredBody: ['archived'],
  },
  'agent.session.mode.update': {
    method: 'PATCH',
    path: '/api/agent/sessions/:sessionId',
    params: { sessionId: null },
    body: ['mode', 'workspaceRoots', 'toolProfileVersion', 'allowedTools'],
    requiredBody: ['mode'],
  },
  'agent.session.delete': {
    method: 'DELETE',
    path: '/api/agent/sessions/:sessionId',
    params: { sessionId: null },
  },
  'agent.session.prompt': {
    method: 'POST',
    path: '/api/agent/sessions/:sessionId/prompt',
    params: { sessionId: null },
    body: ['message', 'attachments', 'clientMessageId'],
    requiredBody: ['message'],
  },
  'agent.session.abort': {
    method: 'POST',
    path: '/api/agent/sessions/:sessionId/abort',
    params: { sessionId: null },
  },
  'agent.session.review.resolve': {
    method: 'POST',
    path: '/api/agent/sessions/:sessionId/review',
    params: { sessionId: null },
    body: ['runId', 'decision'],
    requiredBody: ['runId', 'decision'],
  },
  'agent.session.compact': {
    method: 'POST',
    path: '/api/agent/sessions/:sessionId/compact',
    params: { sessionId: null },
    body: ['instructions'],
  },
  'agent.session.commands': {
    method: 'GET',
    path: '/api/agent/sessions/:sessionId/commands',
    params: { sessionId: null },
  },
  'agent.session.models': {
    method: 'GET',
    path: '/api/agent/sessions/:sessionId/models',
    params: { sessionId: null },
    responseContract: 'agent-model-catalog.v1',
  },
  'agent.session.model.select': {
    method: 'POST',
    path: '/api/agent/sessions/:sessionId/model',
    params: { sessionId: null },
    body: ['provider', 'modelId'],
    requiredBody: ['provider', 'modelId'],
  },
  'agent.session.thinking.select': {
    method: 'POST',
    path: '/api/agent/sessions/:sessionId/thinking',
    params: { sessionId: null },
    body: ['level'],
    requiredBody: ['level'],
  },
  'agent.session.events': {
    method: 'GET',
    path: '/api/agent/sessions/:sessionId/events',
    params: { sessionId: null },
    query: ['lastEventId'],
    requiredQuery: ['lastEventId'],
    subscription: 'agent',
  },
  'agent.session.intercom.list': {
    method: 'GET',
    path: '/api/agent/sessions/:sessionId/intercom',
    params: { sessionId: null },
    query: ['status', 'limit'],
  },
  'agent.session.intercom.send': {
    method: 'POST',
    path: '/api/agent/sessions/:sessionId/intercom',
    params: { sessionId: null },
    body: ['kind', 'targetParticipantId', 'clientMessageId', 'replyTo', 'content'],
    requiredBody: ['kind', 'clientMessageId', 'content'],
  },
  'agent.artifact.get': {
    method: 'GET',
    path: '/api/agent/artifacts/:artifactId',
    params: { artifactId: null },
    query: ['sessionId', 'limit'],
    requiredQuery: ['sessionId'],
  },
  'agent.media.list': {
    method: 'GET',
    path: '/api/agent/media',
    query: ['sessionId', 'limit'],
    requiredQuery: ['sessionId'],
  },
  'agent.deep-search': {
    method: 'POST',
    path: '/api/agent/deep-search',
    body: ['query', 'privacyDisposition', 'context', 'frontAppBundleId', 'contextSource', 'evidence'],
    requiredBody: ['query', 'privacyDisposition'],
  },
  'agent.rooms.list': {
    method: 'GET',
    path: '/api/agent/rooms',
    query: ['includeArchived', 'limit'],
  },
  'agent.rooms.create': {
    method: 'POST',
    path: '/api/agent/rooms',
    body: ['title', 'participants', 'routingPolicy', 'moderatorRoleId'],
    requiredBody: ['participants'],
  },
  'agent.room.get': {
    method: 'GET',
    path: '/api/agent/rooms/:roomId',
    params: { roomId: null },
  },
  'agent.room.snapshot': {
    method: 'GET',
    path: '/api/agent/rooms/:roomId/snapshot',
    params: { roomId: null },
    responseContract: 'agent-room-snapshot.v1',
  },
  'agent.room.archive': {
    method: 'PATCH',
    path: '/api/agent/rooms/:roomId',
    params: { roomId: null },
    body: ['archived'],
    requiredBody: ['archived'],
  },
  'agent.room.message': {
    method: 'POST',
    path: '/api/agent/rooms/:roomId/messages',
    params: { roomId: null },
    body: ['message', 'clientMessageId'],
    requiredBody: ['message'],
  },
  'agent.room.events': {
    method: 'GET',
    path: '/api/agent/rooms/:roomId/events',
    params: { roomId: null },
    query: ['lastEventId'],
    requiredQuery: ['lastEventId'],
    subscription: 'room',
  },
  'agent.roles.list': { method: 'GET', path: '/api/agent/roles' },
  'agent.roles.create': {
    method: 'POST',
    path: '/api/agent/roles',
    body: ['displayName', 'tagline', 'summary', 'traits', 'timelineModel', 'selectableModes'],
    requiredBody: ['displayName', 'tagline', 'summary', 'traits', 'timelineModel', 'selectableModes'],
  },
  'agent.tools.list': { method: 'GET', path: '/api/agent/tools', query: ['sessionId'] },
  'agent.extensions.list': { method: 'GET', path: '/api/agent/extensions' },
  'agent.extensions.create': {
    method: 'POST',
    path: '/api/agent/extensions/drafts',
    body: ['draftId', 'manifest', 'files'],
    requiredBody: ['draftId', 'manifest', 'files'],
  },
  'agent.extensions.proposals': { method: 'GET', path: '/api/agent/extensions/proposals' },
  'agent.extensions.validate': {
    method: 'POST',
    path: '/api/agent/extensions/validate',
    body: ['sourcePath'],
    requiredBody: ['sourcePath'],
  },
  'agent.extensions.preview': {
    method: 'POST',
    path: '/api/agent/extensions/preview',
    body: ['action', 'validationToken', 'pluginId', 'enable'],
    requiredBody: ['action'],
  },
  'agent.extensions.apply': {
    method: 'POST',
    path: '/api/agent/extensions/apply',
    body: ['previewToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['previewToken', 'payloadSha256', 'confirmText'],
  },
  'agent.approvals.list': {
    method: 'GET',
    path: '/api/agent/approvals',
    query: ['sessionId', 'state', 'limit'],
    requiredQuery: ['sessionId'],
  },
  'agent.approval.get': {
    method: 'GET',
    path: '/api/agent/approvals/:approvalId',
    params: { approvalId: null },
  },
  'agent.approval.decide': {
    method: 'POST',
    path: '/api/agent/approvals/:approvalId/decision',
    params: { approvalId: null },
    body: ['decision', 'payloadSha256'],
    requiredBody: ['decision', 'payloadSha256'],
  },
  'agent.memoryMaintenance.run': {
    method: 'GET',
    path: '/api/agent/memory-maintenance',
    query: ['runId', 'project'],
    requiredQuery: ['runId'],
  },
  'agent.subagents.templates': {
    method: 'GET',
    path: '/api/agent/subagents/templates',
  },
  'agent.subagents.list': {
    method: 'GET',
    path: '/api/agent/subagents/runs',
    query: ['sessionId', 'limit'],
    requiredQuery: ['sessionId'],
  },
  'agent.subagents.create': {
    method: 'POST',
    path: '/api/agent/subagents/runs',
    body: ['sessionId', 'tasks', 'agent', 'version', 'task', 'contextMode', 'wait'],
    requiredBody: ['sessionId'],
  },
  'agent.subagent.get': {
    method: 'GET',
    path: '/api/agent/subagents/runs/:runId',
    params: { runId: null },
    query: ['sessionId'],
    requiredQuery: ['sessionId'],
  },
  'agent.subagent.abort': {
    method: 'POST',
    path: '/api/agent/subagents/runs/:runId/abort',
    params: { runId: null },
    body: ['sessionId'],
    requiredBody: ['sessionId'],
  },
  'agent.memorySources.list': {
    method: 'GET',
    path: '/api/agent/memory-sources',
    query: ['sessionId', 'limit'],
    requiredQuery: ['sessionId'],
  },

  'planning.dashboard': {
    method: 'GET',
    path: '/api/planning/dashboard',
    query: ['date', 'project'],
  },
  'planning.mutation.preview': {
    method: 'POST',
    path: '/api/planning/mutation/preview',
    body: ['kind', 'payload', 'expectedRuntimeRevision'],
    requiredBody: ['kind', 'payload', 'expectedRuntimeRevision'],
  },
  'planning.task.save': {
    method: 'POST',
    path: '/api/planning/task/save',
    body: ['taskId', 'date', 'title', 'detail', 'priority', 'status', 'dueAtMs', 'goalId', 'project', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['date', 'title', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
  },
  'planning.goal.save': {
    method: 'POST',
    path: '/api/planning/goal/save',
    body: ['goalId', 'title', 'detail', 'horizon', 'status', 'priority', 'targetDate', 'project', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['title', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
  },
  'planning.task.action': {
    method: 'POST',
    path: '/api/planning/task/action',
    body: ['taskId', 'action', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['taskId', 'action', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
  },
  'planning.taskEvent.undo': {
    method: 'POST',
    path: '/api/planning/task-event/undo',
    body: ['eventId', 'receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['eventId', 'receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
  },
  'planning.mutation.rollback': {
    method: 'POST',
    path: '/api/planning/mutation/rollback',
    body: ['receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
  },
  'memory.summary': { method: 'GET', path: '/api/memory/summary' },
  'memory.pages': {
    method: 'GET',
    path: '/api/memory/:kind',
    params: { kind: ['books', 'atoms', 'tags', 'phrases', 'groups', 'negative'] },
    query: ['limit', 'cursor', 'query', 'status'],
  },
  'memory.graph.get': {
    method: 'GET',
    path: '/api/memory/graph',
    query: ['plane', 'project', 'status', 'query', 'focusId', 'depth', 'nodeLimit', 'edgeLimit', 'minWeight'],
    requiredQuery: ['plane'],
    responseContract: 'memory-graph.v1',
  },
  'memory.entity.get': {
    method: 'GET',
    path: '/api/memory/entities/:kind/:entityId',
    params: { kind: ['tag', 'group', 'book'], entityId: null },
    query: ['project', 'connectionsLimit', 'connectionsCursor', 'membersLimit', 'membersCursor'],
    responseContract: 'memory-entity.v1',
  },
  'memory.edit': {
    method: 'POST',
    path: '/api/memory/edit',
    body: ['kind', 'id', 'title', 'text', 'summary', 'note', 'description', 'tags', 'aliases', 'type', 'color', 'reason', 'active'],
    requiredBody: ['kind', 'id'],
  },
  'memory.book.archive.preview': {
    method: 'POST',
    path: '/api/memory/book/archive/preview',
    body: ['bookId', 'archived', 'reason', 'expectedRuntimeRevision'],
    requiredBody: ['bookId', 'archived', 'expectedRuntimeRevision'],
  },
  'memory.book.archive.apply': {
    method: 'POST',
    path: '/api/memory/book/archive/apply',
    body: ['bookId', 'archived', 'reason', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['bookId', 'archived', 'reason', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
  },
  'memory.book.archive.rollback': {
    method: 'POST',
    path: '/api/memory/book/archive/rollback',
    body: ['receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
  },
  'history.page': {
    method: 'GET',
    path: '/api/history/page',
    query: ['limit', 'cursor', 'query', 'filter'],
  },
  'history.detail': {
    method: 'GET',
    path: '/api/history/detail',
    query: ['eventId'],
    requiredQuery: ['eventId'],
  },
  'history.tombstone.preview': {
    method: 'POST',
    path: '/api/history/tombstone/preview',
    body: ['eventId', 'reason', 'expectedRuntimeRevision'],
    requiredBody: ['eventId', 'expectedRuntimeRevision'],
  },
  'history.tombstone.apply': {
    method: 'POST',
    path: '/api/history/tombstone/apply',
    body: ['eventId', 'reason', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['eventId', 'reason', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
  },
  'history.tombstone.rollback': {
    method: 'POST',
    path: '/api/history/tombstone/rollback',
    body: ['receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
  },
  'knowledge.start': {
    method: 'POST',
    path: '/api/knowledge/start',
    body: ['question', 'context', 'mode', 'includeNotion', 'generation', 'contextHash', 'clientId', 'project', 'app', 'maxChars', 'latencyBudgetMs'],
    requiredBody: ['question'],
  },
  'knowledge.cancel': {
    method: 'POST',
    path: '/api/knowledge/cancel',
    body: ['sessionId', 'id'],
  },
  'knowledge.status': {
    method: 'GET',
    path: '/api/knowledge/status',
    query: ['sessionId', 'id'],
  },
  'knowledge.routeStatus': { method: 'GET', path: '/api/knowledge/route-status' },
  'knowledge.database.apply.preview': {
    method: 'POST',
    path: '/api/knowledge/database/apply-preview',
    body: ['runId', 'expectedRuntimeRevision'],
    requiredBody: ['runId'],
  },
  'knowledge.database.draft.edit': {
    method: 'POST',
    path: '/api/knowledge/database/draft-edit',
    body: ['runId', 'diffId', 'selected', 'payload'],
    requiredBody: ['runId', 'diffId', 'selected'],
  },
  'knowledge.database.apply': {
    method: 'POST',
    path: '/api/knowledge/database/apply',
    body: ['runId', 'confirm', 'previewToken', 'payloadSha256', 'expectedRuntimeRevision'],
    requiredBody: ['runId', 'confirm', 'previewToken', 'payloadSha256', 'expectedRuntimeRevision'],
  },
  'knowledge.database.rollback': {
    method: 'POST',
    path: '/api/knowledge/database/rollback',
    body: ['runId', 'confirm', 'receiptId', 'rollbackToken', 'payloadSha256'],
    requiredBody: ['runId', 'confirm', 'receiptId', 'rollbackToken', 'payloadSha256'],
  },
  'knowledgeBases.list': {
    method: 'GET',
    path: '/api/knowledge-bases',
    query: ['limit', 'cursor', 'query', 'status'],
  },
  'knowledgeBases.create': {
    method: 'POST',
    path: '/api/knowledge-bases',
    body: ['name', 'description', 'agentEnabled', 'parserProvider', 'chunkingConfig', 'retrievalConfig'],
    requiredBody: ['name'],
  },
  'knowledgeBases.get': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId',
    params: { kbId: null },
  },
  'knowledgeBases.update': {
    method: 'PATCH',
    path: '/api/knowledge-bases/:kbId',
    params: { kbId: null },
    body: ['name', 'description', 'agentEnabled', 'parserProvider', 'chunkingConfig', 'retrievalConfig', 'expectedRevision'],
    requiredBody: ['expectedRevision'],
  },
  'knowledgeBases.delete.preview': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/delete/preview',
    params: { kbId: null },
    body: ['expectedRevision'],
    requiredBody: ['expectedRevision'],
  },
  'knowledgeBases.delete.apply': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/delete/apply',
    params: { kbId: null },
    body: ['expectedRevision', 'previewToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['expectedRevision', 'previewToken', 'payloadSha256', 'confirmText'],
  },
  'knowledgeBases.documents.list': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId/documents',
    params: { kbId: null },
    query: ['limit', 'cursor', 'query', 'status'],
  },
  'knowledgeBases.document.import': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/documents/import',
    params: { kbId: null },
    query: ['fileName', 'mimeType', 'parserProvider'],
    requiredQuery: ['fileName', 'mimeType'],
  },
  'knowledgeBases.document.retry': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/documents/:fileId/retry',
    params: { kbId: null, fileId: null },
    body: ['stage', 'parserProvider', 'expectedRevision'],
    requiredBody: ['stage', 'expectedRevision'],
  },
  'knowledgeBases.document.delete': {
    method: 'DELETE',
    path: '/api/knowledge-bases/:kbId/documents/:fileId',
    params: { kbId: null, fileId: null },
  },
  'knowledgeBases.document.get': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId/documents/:fileId',
    params: { kbId: null, fileId: null },
    query: ['offset', 'limit', 'lineOffset', 'lineLimit'],
  },
  'knowledgeBases.document.source': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId/documents/:fileId/source',
    params: { kbId: null, fileId: null },
    binary: true,
  },
  'knowledgeBases.asset.get': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId/documents/:fileId/assets/:assetId',
    params: { kbId: null, fileId: null, assetId: null },
    binary: true,
  },
  'knowledgeBases.jobs.list': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId/jobs',
    params: { kbId: null },
    query: ['limit', 'cursor', 'status'],
  },
  'knowledgeBases.job.cancel': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/jobs/:jobId/cancel',
    params: { kbId: null, jobId: null },
    body: [],
  },
  'knowledgeBases.chunkPreview': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/documents/:fileId/chunk-preview',
    params: { kbId: null, fileId: null },
    body: ['chunkingConfig', 'limit'],
    requiredBody: ['chunkingConfig'],
  },
  'knowledgeBases.search': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/search',
    params: { kbId: null },
    body: ['query', 'topK', 'mode', 'threshold', 'fileIds', 'fileName'],
    requiredBody: ['query'],
  },
  'knowledgeBases.find': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/documents/:fileId/find',
    params: { kbId: null, fileId: null },
    body: ['query', 'regex', 'lineWindow'],
    requiredBody: ['query'],
  },
  'knowledgeBases.open': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId/documents/:fileId/content',
    params: { kbId: null, fileId: null },
    query: ['chunkId', 'page', 'startLine', 'lines'],
  },
  'knowledgeBases.reindexPreview': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId/reindex-preview',
    params: { kbId: null },
  },
  'knowledgeBases.rebuild': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/rebuild',
    params: { kbId: null },
    body: ['previewToken', 'payloadSha256', 'expectedRevision', 'confirmText'],
    requiredBody: ['previewToken', 'payloadSha256', 'expectedRevision', 'confirmText'],
  },
  'knowledgeBases.graph.get': {
    method: 'GET',
    path: '/api/knowledge-bases/:kbId/graph',
    params: { kbId: null },
    query: ['documentId', 'query', 'kinds', 'limit', 'depth', 'excludeChunks', 'focusId'],
    responseContract: 'knowledge-graph.v1',
  },
  'knowledgeBases.graph.rebuild': {
    method: 'POST',
    path: '/api/knowledge-bases/:kbId/graph/rebuild',
    params: { kbId: null },
    body: ['expectedRevision', 'documentIds', 'extractorMode', 'modelId', 'batchSize', 'extractionConcurrency', 'maxEntitiesPerChunk', 'maxRelationsPerChunk', 'maxTopicsPerChunk'],
    requiredBody: ['expectedRevision'],
  },
  'knowledgeWorker.health': { method: 'GET', path: '/api/knowledge-bases/health' },
  'knowledgeParsers.list': { method: 'GET', path: '/api/knowledge-bases/parsers' },
  'diagnostics.runtime': { method: 'GET', path: '/api/runtime/status' },
  'diagnostics.predictor': { method: 'GET', path: '/api/predictor/status' },
  'diagnostics.models': { method: 'GET', path: '/api/models/status' },
  'diagnostics.action.preview': {
    method: 'POST',
    path: '/api/runtime/action/preview',
    body: ['action', 'expectedRuntimeRevision'],
    requiredBody: ['action', 'expectedRuntimeRevision'],
  },
  'diagnostics.action.start': {
    method: 'POST',
    path: '/api/runtime/action/start',
    body: ['action', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'commandSha256', 'confirmText'],
    requiredBody: ['action', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'commandSha256', 'confirmText'],
  },
  'diagnostics.action.job': {
    method: 'GET',
    path: '/api/runtime/job/:jobId',
    params: { jobId: null },
  },
  'configuration.settings': { method: 'GET', path: '/api/settings' },
  'configuration.schema': { method: 'GET', path: '/api/settings/schema' },
  'configuration.settings.preview': {
    method: 'POST',
    path: '/api/settings/preview',
    body: ['changes', 'expectedRuntimeRevision'],
    requiredBody: ['changes', 'expectedRuntimeRevision'],
  },
  'configuration.settings.apply': {
    method: 'POST',
    path: '/api/settings/apply',
    body: ['changes', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['changes', 'expectedRuntimeRevision', 'previewToken', 'payloadSha256', 'confirmText'],
  },
  'configuration.settings.rollback': {
    method: 'POST',
    path: '/api/settings/rollback',
    body: ['receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
    requiredBody: ['receiptId', 'rollbackToken', 'payloadSha256', 'confirmText'],
  },
  'configuration.import.preview': {
    method: 'POST',
    path: '/api/configuration/import-preview',
    body: ['path'],
    requiredBody: ['path'],
  },
  'configuration.import.apply': {
    method: 'POST',
    path: '/api/configuration/import-apply',
    body: ['path', 'expectedRuntimeRevision', 'previewToken', 'confirmText', 'confirmRemoteModel'],
    requiredBody: ['path', 'expectedRuntimeRevision', 'previewToken', 'confirmText'],
  },
  'configuration.backup.export': {
    method: 'POST',
    path: '/api/configuration/backup-export',
    body: ['destination'],
    requiredBody: ['destination'],
  },
  'configuration.restore.preview': {
    method: 'POST',
    path: '/api/configuration/restore-preview',
    body: ['path'],
    requiredBody: ['path'],
  },
  'configuration.restore.apply': {
    method: 'POST',
    path: '/api/configuration/restore-apply',
    body: ['path', 'restoreToken', 'confirmText', 'expectedRuntimeRevision'],
    requiredBody: ['path', 'restoreToken', 'confirmText', 'expectedRuntimeRevision'],
  },
} as const satisfies Record<string, ControlRouteDefinition>;

export type ControlPathId = keyof typeof CONTROL_ROUTES;
export type SubscriptionPathId = {
  [PathId in ControlPathId]: (typeof CONTROL_ROUTES)[PathId] extends {
    subscription: ControlStreamKind;
  }
    ? PathId
    : never;
}[ControlPathId];

export function controlRoute(pathId: ControlPathId): ControlRouteDefinition {
  if (!Object.hasOwn(CONTROL_ROUTES, pathId)) {
    throw new ControlRoutePolicyError(String(pathId), 'pathId is not allowlisted');
  }
  return CONTROL_ROUTES[pathId];
}

export function isControlPathId(value: unknown): value is ControlPathId {
  return typeof value === 'string' && Object.hasOwn(CONTROL_ROUTES, value);
}

export function resolveControlPath(
  pathId: ControlPathId,
  params: Readonly<Record<string, string>> = {},
): string {
  const route = controlRoute(pathId);
  const policy = route.params ?? {};
  const suppliedKeys = Object.keys(params);
  const requiredKeys = Object.keys(policy);
  if (
    suppliedKeys.length !== requiredKeys.length ||
    suppliedKeys.some((key) => !Object.hasOwn(policy, key))
  ) {
    throw new ControlRoutePolicyError(pathId, 'path parameters do not match the route policy');
  }

  let resolved = route.path;
  for (const key of requiredKeys) {
    const value = params[key];
    if (!isSafeRouteParameter(value)) {
      throw new ControlRoutePolicyError(pathId, `invalid ${key} path parameter`);
    }
    const allowedValues = policy[key];
    if (allowedValues && !allowedValues.includes(value)) {
      throw new ControlRoutePolicyError(pathId, `${key} is not allowlisted`);
    }
    resolved = resolved.replace(`:${key}`, encodeURIComponent(value));
  }
  return resolved;
}

export function assertAllowedQuery(
  pathId: ControlPathId,
  query: Readonly<Record<string, unknown>> | undefined,
): void {
  const values = query ?? {};
  const allowed = new Set<string>(controlRoute(pathId).query ?? []);
  for (const key of Object.keys(values)) {
    if (!allowed.has(key)) {
      throw new ControlRoutePolicyError(pathId, `query field is not allowlisted: ${key}`);
    }
    const value = values[key];
    if (
      (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') ||
      (typeof value === 'number' && !Number.isFinite(value)) ||
      (typeof value === 'string' &&
        (value.length > 2_048 || /[\u0000-\u001f]/u.test(value)))
    ) {
      throw new ControlRoutePolicyError(pathId, `query field is invalid: ${key}`);
    }
  }
  for (const key of controlRoute(pathId).requiredQuery ?? []) {
    if (!Object.hasOwn(values, key)) {
      throw new ControlRoutePolicyError(pathId, `required query field is missing: ${key}`);
    }
  }
}

export function assertAllowedBody(
  pathId: ControlPathId,
  body: unknown,
): void {
  const route = controlRoute(pathId);
  if (body === undefined) {
    if ((route.requiredBody?.length ?? 0) > 0) {
      throw new ControlRoutePolicyError(pathId, 'required request body is missing');
    }
    return;
  }
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    throw new ControlRoutePolicyError(pathId, 'request body must be an object');
  }
  const allowed = new Set<string>(route.body ?? []);
  for (const key of Object.keys(body)) {
    if (!allowed.has(key)) {
      throw new ControlRoutePolicyError(pathId, `body field is not allowlisted: ${key}`);
    }
  }
  for (const key of route.requiredBody ?? []) {
    if (!Object.hasOwn(body, key)) {
      throw new ControlRoutePolicyError(pathId, `required body field is missing: ${key}`);
    }
  }
}

export class ControlRoutePolicyError extends Error {
  readonly pathId: string;

  constructor(pathId: string, message: string) {
    super(`Rejected ${pathId}: ${message}`);
    this.name = 'ControlRoutePolicyError';
    this.pathId = pathId;
  }
}

function isSafeRouteParameter(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u.test(value);
}
