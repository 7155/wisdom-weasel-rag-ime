import type { ControlPathId } from '@/platform/routes';
import type { ControlRequest } from '@/platform/transport';
import type { MockRouteHandler } from '@/test/mock-transport';

const HISTORY_EVENT_ID = 201;
const HISTORY_RUNTIME_REVISION = 12;
const HISTORY_PAYLOAD_SHA256 = `sha256:${'1'.repeat(64)}`;
const HISTORY_SUBJECT_REVISION = `sha256:${'2'.repeat(64)}`;
const HISTORY_PREVIEW_TOKEN = 'preview-history-tombstone-token-v1';

type PreviewRoutes = Partial<Record<ControlPathId, MockRouteHandler>>;

export function createPreviewHistoryRoutes(): PreviewRoutes {
  return {
    'history.page': (request: ControlRequest) => previewHistoryPage(record(request.query)),
    'history.detail': (request: ControlRequest) =>
      previewHistoryDetail(Number(record(request.query).eventId ?? 0)),
    'history.tombstone.preview': (request: ControlRequest) => {
      const body = record(request.body);
      const eventId = Number(body.eventId ?? HISTORY_EVENT_ID);
      return {
        schemaVersion: 'rag-ime.management-work-preview.v1',
        ok: true,
        previewToken: HISTORY_PREVIEW_TOKEN,
        pathId: 'history.tombstone.apply',
        payloadSha256: HISTORY_PAYLOAD_SHA256,
        expectedRevision: {
          runtimeRevision: Number(body.expectedRuntimeRevision ?? HISTORY_RUNTIME_REVISION),
          subjectRevision: HISTORY_SUBJECT_REVISION,
        },
        expiresAtMs: Date.now() + 300_000,
        requiredConfirm: 'apply',
        summary: {
          title: '让这条记录不再参与记忆？',
          items: [`记录 ${eventId} 将停止参与后续召回；原始输入仍会保留。`],
          risk: 'R2',
        },
      };
    },
    'history.tombstone.apply': (request: ControlRequest) =>
      previewHistoryReceipt('history.tombstone.apply', request, true),
    'history.tombstone.rollback': (request: ControlRequest) =>
      previewHistoryReceipt('history.tombstone.rollback', request, false),
  };
}

function previewHistoryPage(query: Record<string, unknown>): Record<string, unknown> {
  const item = {
    id: HISTORY_EVENT_ID,
    createdAtMs: Date.now() - 86_400_000,
    source: 'rime_commit',
    app: 'TextEdit',
    project: 'personal-agent-workbench',
    textPreview: '已脱敏 · 这条记录用于演示按需查看完整输入',
    textChars: 24,
    contextHash: HISTORY_SUBJECT_REVISION,
  };
  const search = stringValue(query.query).trim().toLocaleLowerCase('zh-CN');
  const filter = stringValue(query.filter);
  const matchesSearch = !search
    || item.textPreview.toLocaleLowerCase('zh-CN').includes(search)
    || item.app.toLocaleLowerCase('en-US').includes(search);
  const matchesFilter = !filter || filter === 'rime_commit';
  const items = matchesSearch && matchesFilter ? [item] : [];
  return {
    ok: true,
    runtimeRevision: HISTORY_RUNTIME_REVISION,
    items,
    nextCursor: '',
    limit: 50,
    rawTextVisible: false,
  };
}

function previewHistoryDetail(eventId: number): Record<string, unknown> {
  if (eventId !== HISTORY_EVENT_ID) return { ok: false, reason: 'not_found' };
  const createdAtMs = Date.now() - 86_400_000;
  return {
    ok: true,
    runtimeRevision: HISTORY_RUNTIME_REVISION,
    rawTextVisible: true,
    item: {
      id: HISTORY_EVENT_ID,
      createdAtMs,
      source: 'rime_commit',
      text: '请保留输入来源，并让我能回看这次整理使用的上下文。',
      textChars: 24,
      app: 'TextEdit',
      project: 'personal-agent-workbench',
      provider: 'local',
      candidateRank: null,
      groupId: 'project:personal-agent-workbench',
      groupLevel: 'project',
      auxiliaryContext: {
        available: true,
        text: '在同一份本机工作文档中，用户先说明了时间线不应把几分钟活动算作持久整理结果。',
        textChars: 39,
        truncated: false,
        hasAdditionalText: true,
        captureSource: 'accessibility',
        captureMode: 'foreground_selection',
        fallbackReason: '',
        fieldContextChars: 39,
        imeBufferChars: 0,
        modelRequestLinked: true,
      },
      status: 'active',
      feedback: {
        available: true,
        acceptedCount: 1,
        skippedCount: 0,
        pinned: false,
        downranked: false,
        deleted: false,
        updatedAtMs: createdAtMs + 10_000,
        latestAction: 'accept',
        latestActionAtMs: createdAtMs + 10_000,
      },
    },
  };
}

function previewHistoryReceipt(
  pathId: 'history.tombstone.apply' | 'history.tombstone.rollback',
  request: ControlRequest,
  rollbackAvailable: boolean,
): Record<string, unknown> {
  const body = record(request.body);
  return {
    schemaVersion: 'rag-ime.management-work-receipt.v1',
    ok: true,
    receiptId: `preview-history-receipt-${Date.now()}`,
    pathId,
    payloadSha256: stringValue(body.payloadSha256) || HISTORY_PAYLOAD_SHA256,
    appliedAtMs: Date.now(),
    auditId: HISTORY_EVENT_ID,
    rollbackAvailable,
    rollbackToken: rollbackAvailable ? 'preview-history-rollback-token-v1' : '',
    rollbackAuthority: { eventId: HISTORY_EVENT_ID },
    restartComponents: [],
    result: { runtimeRevision: HISTORY_RUNTIME_REVISION + 1 },
  };
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
