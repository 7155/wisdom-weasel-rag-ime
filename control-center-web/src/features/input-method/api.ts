import { useQuery } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import type { ControlTransport } from '@/platform/transport';

export type LexiconReviewEntry = {
  reviewKey: string;
  text: string;
  pinyin: string;
  weight: number;
  positiveCount: number;
  negativeCount: number;
  reasons: readonly string[];
  reviewSource: string;
  reviewReason: string;
  selected: boolean;
};

export type LexiconReview = {
  schemaVersion: 'rag-ime.rime-lexicon-review.v1';
  project: string;
  entryCount: number;
  entries: readonly LexiconReviewEntry[];
  reviewToken: string;
  confirmText: string;
  applySupported: boolean;
  reviewRequired: boolean;
};

export type LexiconMutationReceipt = {
  rollbackId: string;
  entryCount: number;
  requiresRedeploy: boolean;
};

const lexiconPathIds = [
  'input.lexicon.review',
  'input.lexicon.apply',
  'input.lexicon.rollback',
] as const;

export const inputMethodQueryKeys = {
  root: ['input-method'] as const,
  source: () => [...inputMethodQueryKeys.root, 'source'] as const,
  overview: () => [...inputMethodQueryKeys.root, 'overview'] as const,
  settings: () => [...inputMethodQueryKeys.root, 'settings'] as const,
  schema: () => [...inputMethodQueryKeys.root, 'schema'] as const,
  capabilities: () => [...inputMethodQueryKeys.root, 'capabilities'] as const,
  lexiconReview: () => [...inputMethodQueryKeys.root, 'lexicon-review'] as const,
};

export function useInputMethodQueries() {
  const transport = useControlTransport();
  const source = useQuery({
    queryKey: inputMethodQueryKeys.source(),
    queryFn: ({ signal }) => transport.request({ pathId: 'input.source.get', signal }),
    refetchInterval: 10_000,
  });
  const overview = useQuery({
    queryKey: inputMethodQueryKeys.overview(),
    queryFn: ({ signal }) => transport.request({ pathId: 'overview.get', signal }),
  });
  const settings = useQuery({
    queryKey: inputMethodQueryKeys.settings(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.settings', signal }),
  });
  const schema = useQuery({
    queryKey: inputMethodQueryKeys.schema(),
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.schema', signal }),
  });
  const capabilities = useQuery({
    queryKey: inputMethodQueryKeys.capabilities(),
    queryFn: () => transport.capabilities(),
    staleTime: Infinity,
  });
  const lexiconAvailable = Boolean(
    capabilities.data
      && lexiconPathIds.every((pathId) => capabilities.data.routeIds.includes(pathId)),
  );
  const lexiconReview = useQuery({
    enabled: lexiconAvailable,
    queryKey: inputMethodQueryKeys.lexiconReview(),
    queryFn: async ({ signal }) => parseLexiconReview(await transport.request({
      pathId: 'input.lexicon.review',
      query: { limit: 200 },
      signal,
    })),
    staleTime: 10_000,
  });
  return {
    capabilities,
    lexiconAvailable,
    lexiconReview,
    overview,
    schema,
    settings,
    source,
    transport,
    transportKind: transport.kind,
  };
}

export async function applyLexiconReview(
  transport: ControlTransport,
  review: LexiconReview,
  selectedKeys: readonly string[],
): Promise<LexiconMutationReceipt> {
  const payload = await transport.request({
    pathId: 'input.lexicon.apply',
    body: {
      reviewToken: review.reviewToken,
      selectedKeys: [...selectedKeys],
      confirmText: review.confirmText,
      project: review.project,
      limit: 200,
    },
  });
  return parseLexiconMutation(payload, 'apply');
}

export async function rollbackLexiconReview(
  transport: ControlTransport,
  rollbackId: string,
): Promise<LexiconMutationReceipt> {
  const payload = await transport.request({
    pathId: 'input.lexicon.rollback',
    body: { rollbackId },
  });
  return parseLexiconMutation(payload, 'rollback');
}

function parseLexiconReview(value: unknown): LexiconReview {
  const payload = record(value);
  if (payload.ok !== true) throw new Error(failureMessage(payload.reason ?? payload.error, payload));
  if (payload.schemaVersion !== 'rag-ime.rime-lexicon-review.v1') {
    throw new Error('词库审阅返回了不兼容的数据。');
  }
  const reviewToken = requiredString(payload.reviewToken, 'reviewToken');
  const confirmText = requiredString(payload.confirmText, 'confirmText');
  const entries = Array.isArray(payload.entries) ? payload.entries.map(parseLexiconEntry) : [];
  const entryCount = nonNegativeInteger(payload.entryCount, 'entryCount');
  if (entryCount !== entries.length) throw new Error('词库审阅条目数量与服务端摘要不一致。');
  return {
    schemaVersion: payload.schemaVersion,
    project: stringValue(payload.project),
    entryCount,
    entries,
    reviewToken,
    confirmText,
    applySupported: payload.applySupported === true,
    reviewRequired: payload.reviewRequired === true,
  };
}

function parseLexiconEntry(value: unknown): LexiconReviewEntry {
  const entry = record(value);
  return {
    reviewKey: requiredString(entry.reviewKey, 'reviewKey'),
    text: requiredString(entry.text, 'text'),
    pinyin: stringValue(entry.pinyin),
    weight: numberValue(entry.weight),
    positiveCount: numberValue(entry.positiveCount),
    negativeCount: numberValue(entry.negativeCount),
    reasons: Array.isArray(entry.reasons)
      ? entry.reasons.filter((item): item is string => typeof item === 'string' && item.length > 0)
      : [],
    reviewSource: stringValue(entry.reviewSource),
    reviewReason: stringValue(entry.reviewReason),
    selected: entry.selected === true,
  };
}

function parseLexiconMutation(value: unknown, kind: 'apply' | 'rollback'): LexiconMutationReceipt {
  const payload = record(value);
  const succeeded = kind === 'apply' ? payload.applied === true : payload.rolledBack === true;
  if (payload.ok !== true || !succeeded) {
    throw new Error(failureMessage(payload.reason ?? payload.error, payload));
  }
  if (payload.schemaVersion !== 'rag-ime.rime-lexicon-review.v1') {
    throw new Error('词库操作返回了不兼容的数据。');
  }
  return {
    rollbackId: requiredString(payload.rollbackId, 'rollbackId'),
    entryCount: payload.entryCount === undefined ? 0 : nonNegativeInteger(payload.entryCount, 'entryCount'),
    // Missing redeploy state is treated conservatively: never claim foreground activation.
    requiresRedeploy: payload.requiresRedeploy !== false,
  };
}

function failureMessage(value: unknown, payload: Record<string, unknown>): string {
  const reason = stringValue(value) || 'unknown_error';
  const message = ({
    review_token_stale: '词库审阅已变化，请刷新后重新选择并确认。',
    no_reviewed_entries: '没有可应用的已审词条。',
    confirm_text_required: '服务端确认绑定已失效，请重新审阅。',
    rollback_manifest_missing: '找不到该词库操作记录。',
    rollback_manifest_invalid: '词库撤销记录已损坏，未执行撤销。',
    rollback_already_applied: '该词库操作已经撤销。',
    newer_rollback_required_first: '存在更新的词库写入，必须先撤销最新一次操作。',
  } as Record<string, string>)[reason] ?? '词库操作失败，请刷新后重试。';
  const blockingRollbackId = stringValue(payload.blockingRollbackId);
  return blockingRollbackId ? `${message} 存在更新的操作记录。` : message;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function requiredString(value: unknown, field: string): string {
  const text = stringValue(value);
  if (!text) throw new Error(field === 'reviewKey' || field === 'text' ? '词库条目数据不完整。' : '词库审阅缺少必要凭据，未执行操作。');
  return text;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new Error(field === 'entryCount' ? '词库条目数量无效。' : '词库返回的数据无效。');
  }
  return value;
}
