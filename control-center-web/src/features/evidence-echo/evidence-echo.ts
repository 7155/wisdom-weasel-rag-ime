/**
 * evidence-echo — 上下文装配节点 ⇄ 证据实体的双向解析。
 *
 * 正向：Agent 轨迹的每个装配节点，如果它记录了**具体**的证据实体标识，
 * 就能打开 Memory / Knowledge / Files / Browser 的那一条；没有标识的节点
 * 保持不可点击，绝不造一个看起来能点的假链接。
 *
 * 反向：Memory / Knowledge / Files 的实体详情读取既有的
 * `agent.sessions.list` + `agent.session.contextTraces.list` +
 * `agent.session.contextTrace.get`，在前端聚合出「最近被哪些 Session 装配」。
 * 这是一层只读投影：不新增持久化、不新增事件类型、不把使用记录写回
 * Memory·Knowledge 正文。
 *
 * 唯一的输入是 contextTrace 节点自己记录的 `metadata`。Runtime 侧的
 * `_public_metadata` 只保留标量（bool / 数字 / 字符串），并丢弃键名里带
 * `path` 的项，所以能真正穿过这层清洗的引用形状只有**扁平字符串**：
 * `memoryAtomId(s)` `memoryBookId(s)` `memoryTimelineId(s)`
 * `memoryEvidenceId(s)` `knowledgeDocumentId(s)` `workspaceFile(s)`
 * `browserUrl(s)`，多值用逗号分隔。这里只认这一组键，读不到就返回空数组。
 * stage / sourceKind 只用来补默认值，永远不会凭空生成一个 id。
 */

import type { AgentContextTraceV1 } from '@/contracts/generated/agent-context-trace.v1';
import { sessionItems } from '@/features/agent/types';
import { openPawOsRoute, type PawOsWindowRequest } from '@/features/paw-os/surface-context';
import type { ControlTransport } from '@/platform/transport';

type EvidenceEchoDesktop = {
  openWindow: (request: PawOsWindowRequest) => void;
  openRoute?: (route: string) => void;
  openApp?: (appId: PawOsWindowRequest['appId'], initialRoute?: string) => void;
} | null;

export type EvidenceEchoAppId = 'memory' | 'knowledge' | 'files' | 'browser';

export type EvidenceEchoEntity = {
  appId: EvidenceEchoAppId;
  /** App 内部稳定的实体标识：记忆 id、文档 id、文件路径、页面 URL。 */
  entityId: string;
  label: string;
  /** Memory 目录层（atoms / books / evidence / timelines）。 */
  layer?: string;
  /** Knowledge 文档所属知识库。 */
  baseId?: string;
  /** Files 需要一个授权 Session 才能读取工作区文件。 */
  sessionId?: string;
};

export type EvidenceEchoTraceNode = AgentContextTraceV1['nodes'][number];

export type EvidenceEchoUsageRow = {
  sessionId: string;
  sessionTitle: string;
  traceId: string;
  turnId: string;
  nodeId: string;
  nodeLabel: string;
  disposition: EvidenceEchoTraceNode['disposition'];
  atMs: number;
};

export type EvidenceEchoUsage = {
  rows: EvidenceEchoUsageRow[];
  scannedSessionCount: number;
  scannedTraceCount: number;
  /** 至少一个 Session 或 trace 读取失败；列表只覆盖读到的部分。 */
  partial: boolean;
};

/** 一个装配节点最多解析出这么多实体，避免一条 metadata 撑爆摘要行。 */
const MAX_TARGETS_PER_NODE = 6;
const MAX_ID_LENGTH = 500;
const MAX_LABEL_LENGTH = 120;

/* 打开一条记忆不该换来一串请求。默认预算是 1 次 Session 列表 + 最多 6 次
   trace 列表 + 最多 12 次 trace 读取，全部并发且可取消。 */
const DEFAULT_SESSION_SCAN_LIMIT = 6;
const DEFAULT_TRACES_PER_SESSION = 3;
const DEFAULT_TRACE_FETCH_LIMIT = 12;
const DEFAULT_ROW_LIMIT = 8;

/** 能穿过 Runtime `_public_metadata` 清洗的那组扁平引用键。 */
const REFERENCE_KEYS: ReadonlyArray<{
  keys: readonly string[];
  appId: EvidenceEchoAppId;
  layer?: string;
}> = [
  { keys: ['memoryAtomId', 'memoryAtomIds'], appId: 'memory', layer: 'atoms' },
  { keys: ['memoryBookId', 'memoryBookIds'], appId: 'memory', layer: 'books' },
  { keys: ['memoryTimelineId', 'memoryTimelineIds'], appId: 'memory', layer: 'timelines' },
  { keys: ['memoryEvidenceId', 'memoryEvidenceIds'], appId: 'memory', layer: 'evidence' },
  { keys: ['knowledgeDocumentId', 'knowledgeDocumentIds'], appId: 'knowledge' },
  { keys: ['workspaceFile', 'workspaceFiles'], appId: 'files' },
  { keys: ['browserUrl', 'browserUrls'], appId: 'browser' },
];

/**
 * 装配节点解析出的证据实体，按上面这张表的顺序返回。读不到具体标识时返回
 * 空数组——调用方据此决定这一行不可点击。
 */
export function evidenceEchoNodeEntities(
  node: EvidenceEchoTraceNode | undefined,
  context: { sessionId?: string } = {},
): EvidenceEchoEntity[] {
  if (!node || !isRecord(node.metadata)) return [];
  const metadata = node.metadata;
  const baseId = boundedText(firstText(metadata, ['knowledgeBaseId', 'knowledgeBase']), MAX_ID_LENGTH);
  const workspaceSessionId = boundedText(firstText(metadata, ['workspaceSessionId']), MAX_ID_LENGTH)
    || context.sessionId
    || '';
  const found: EvidenceEchoEntity[] = [];
  const seen = new Set<string>();
  for (const { appId, keys, layer } of REFERENCE_KEYS) {
    for (const key of keys) {
      for (const entityId of referenceIds(metadata[key])) {
        if (found.length >= MAX_TARGETS_PER_NODE) return found;
        if (!openableEntityId(appId, entityId)) continue;
        const dedupe = `${appId}:${entityId}`;
        if (seen.has(dedupe)) continue;
        seen.add(dedupe);
        found.push({
          appId,
          entityId,
          label: entityLabel(appId, entityId),
          ...(layer ? { layer } : {}),
          ...(appId === 'knowledge' && baseId ? { baseId } : {}),
          ...(appId === 'files' ? { sessionId: workspaceSessionId } : {}),
        });
      }
    }
  }
  return found;
}

function referenceIds(value: unknown): string[] {
  if (typeof value !== 'string') return [];
  return value
    .split(',')
    .map((part) => boundedText(part, MAX_ID_LENGTH))
    .filter(Boolean);
}

/**
 * 只有真的能打开的标识才算数。Runtime 会把 `/Users` `/Volumes` 这类本地路径
 * 替换成「本地资源」，那样的值既不是路径也不是 URL，宁可不给入口。
 */
function openableEntityId(appId: EvidenceEchoAppId, entityId: string): boolean {
  if (appId === 'files') return entityId.startsWith('/');
  if (appId === 'browser') return /^https?:\/\/\S+$/u.test(entityId);
  return true;
}

function entityLabel(appId: EvidenceEchoAppId, entityId: string): string {
  if (appId === 'files') return entityId.split('/').filter(Boolean).at(-1) ?? entityId;
  if (appId === 'browser') {
    try {
      return new URL(entityId).host || entityId;
    } catch {
      return entityId;
    }
  }
  return boundedText(entityId, MAX_LABEL_LENGTH);
}

export function evidenceEchoAppLabel(appId: EvidenceEchoAppId): string {
  return ({ memory: '记忆', knowledge: '知识库', files: '文件', browser: '网页' } as const)[appId];
}

/**
 * 打开这个实体所用的桌面路由。Browser 没有实体路由——它由窗口 target 打开，
 * 所以这里返回空字符串。
 */
export function evidenceEchoRoute(entity: EvidenceEchoEntity): string {
  if (entity.appId === 'memory') {
    return `/memory?layer=${encodeURIComponent(entity.layer || 'atoms')}&id=${encodeURIComponent(entity.entityId)}`;
  }
  if (entity.appId === 'knowledge') {
    const base = entity.baseId ? `base=${encodeURIComponent(entity.baseId)}&` : '';
    return `/knowledge?${base}document=${encodeURIComponent(entity.entityId)}&tab=viewer`;
  }
  if (entity.appId === 'files') {
    const session = entity.sessionId ? `session=${encodeURIComponent(entity.sessionId)}&` : '';
    return `/files?${session}path=${encodeURIComponent(entity.entityId)}`;
  }
  return '';
}

/**
 * 正向落点：把这个实体所在的 App 打开到它自己那一条。
 *
 * Memory / Knowledge / Files 走桌面路由，最终仍然落在
 * `desktop-store.openApp(appId, { initialRoute })` 上——同一个 App 复用同一扇
 * 窗，只是导航到这个实体，而不是为每条记忆再开一扇窗。Browser 的实体就是
 * 一个页面，所以它走 `openWindow` 的 browser-target，由 Browser App 自己
 * 按 `entityId` 复用会话窗口。
 */
export function openEvidenceEchoEntity(desktop: EvidenceEchoDesktop, entity: EvidenceEchoEntity): void {
  if (entity.appId === 'browser') {
    desktop?.openWindow({
      appId: 'browser',
      target: {
        kind: 'browser-target',
        id: entity.entityId,
        title: entity.label || 'Browser',
        sessionId: entity.sessionId ?? '',
        toolCallId: '',
        targetId: '',
        provisional: true,
        url: entity.entityId,
      },
    });
    return;
  }
  const route = evidenceEchoRoute(entity);
  if (route) openPawOsRoute(desktop, route);
}

/** 反向落点：打开 Agent App 的这段 Session，并聚焦到那一个装配节点。 */
export function evidenceEchoSessionRoute(row: Pick<EvidenceEchoUsageRow, 'sessionId' | 'traceId' | 'nodeId'>): string {
  const params = new URLSearchParams({ session: row.sessionId });
  if (row.traceId) params.set('trace', row.traceId);
  if (row.nodeId) params.set('node', row.nodeId);
  return `/agent?${params.toString()}`;
}

export type EvidenceEchoFocus = { traceId: string; nodeId: string };

/** 从 Agent App 的 initialRoute 里读出反向落点要聚焦的装配节点。 */
export function evidenceEchoFocusFromRoute(initialRoute: string): EvidenceEchoFocus | undefined {
  const query = new URLSearchParams(initialRoute.split('?', 2)[1] ?? '');
  const nodeId = boundedText(query.get('node') ?? '', MAX_ID_LENGTH);
  if (!nodeId) return undefined;
  return { traceId: boundedText(query.get('trace') ?? '', MAX_ID_LENGTH), nodeId };
}

/**
 * 读取既有 route，聚合出「这个实体最近被哪些 Session 装配」。全部是 GET，
 * 请求数按 sessionScanLimit × tracesPerSession 有界；任何一次失败只让结果
 * 变成 partial，不会让整块消失。
 */
export async function collectEvidenceEchoUsage(
  transport: ControlTransport,
  entity: Pick<EvidenceEchoEntity, 'appId' | 'entityId'>,
  options: {
    sessionScanLimit?: number;
    tracesPerSession?: number;
    traceFetchLimit?: number;
    rowLimit?: number;
    signal?: AbortSignal;
  } = {},
): Promise<EvidenceEchoUsage> {
  const sessionScanLimit = options.sessionScanLimit ?? DEFAULT_SESSION_SCAN_LIMIT;
  const tracesPerSession = options.tracesPerSession ?? DEFAULT_TRACES_PER_SESSION;
  const traceFetchLimit = options.traceFetchLimit ?? DEFAULT_TRACE_FETCH_LIMIT;
  const rowLimit = options.rowLimit ?? DEFAULT_ROW_LIMIT;
  const signal = options.signal;
  const entityId = entity.entityId.trim();
  if (!entityId) return { rows: [], scannedSessionCount: 0, scannedTraceCount: 0, partial: false };

  let partial = false;
  const sessions = sessionItems(await transport.request({
    pathId: 'agent.sessions.list',
    query: { limit: sessionScanLimit, includeArchived: false },
    signal,
  })).slice(0, sessionScanLimit);

  const traceRefs: Array<{ sessionId: string; sessionTitle: string; traceId: string; turnId: string; createdAtMs: number }> = [];
  const listings = await Promise.all(sessions.map(async (session) => {
    try {
      const response = await transport.request({
        pathId: 'agent.session.contextTraces.list',
        params: { sessionId: session.id },
        query: { limit: tracesPerSession },
        signal,
      });
      return { session, items: asArray(asRecord(response).items).map(asRecord) };
    } catch {
      partial = true;
      return { session, items: [] };
    }
  }));
  for (const { session, items } of listings) {
    for (const item of items.slice(0, tracesPerSession)) {
      const traceId = text(item.traceId);
      if (!traceId) continue;
      traceRefs.push({
        sessionId: session.id,
        sessionTitle: session.title || session.id,
        traceId,
        turnId: text(item.turnId),
        createdAtMs: numeric(item.createdAtMs) || numeric(item.updatedAtMs),
      });
    }
  }
  traceRefs.sort((left, right) => right.createdAtMs - left.createdAtMs);
  if (traceRefs.length > traceFetchLimit) partial = true;
  const fetched = traceRefs.slice(0, traceFetchLimit);

  const rows: EvidenceEchoUsageRow[] = [];
  await Promise.all(fetched.map(async (ref) => {
    let trace: AgentContextTraceV1;
    try {
      trace = await transport.request({
        pathId: 'agent.session.contextTrace.get',
        params: { sessionId: ref.sessionId, traceId: ref.traceId },
        signal,
      }) as unknown as AgentContextTraceV1;
    } catch {
      partial = true;
      return;
    }
    for (const node of asArray(asRecord(trace).nodes) as EvidenceEchoTraceNode[]) {
      const matched = evidenceEchoNodeEntities(node, { sessionId: ref.sessionId })
        .some((candidate) => candidate.appId === entity.appId && candidate.entityId === entityId);
      if (!matched) continue;
      rows.push({
        sessionId: ref.sessionId,
        sessionTitle: ref.sessionTitle,
        traceId: ref.traceId,
        turnId: ref.turnId || text(asRecord(trace).turnId),
        nodeId: node.nodeId,
        nodeLabel: node.label || node.stage,
        disposition: node.disposition,
        atMs: numeric(node.createdAtMs) || ref.createdAtMs,
      });
    }
  }));

  rows.sort((left, right) => right.atMs - left.atMs || left.sessionId.localeCompare(right.sessionId));
  return {
    rows: rows.slice(0, rowLimit),
    scannedSessionCount: sessions.length,
    scannedTraceCount: fetched.length,
    partial,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}
function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  return value === undefined || value === null ? [] : [value];
}
function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
function numeric(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}
function firstText(source: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}
function boundedText(value: string, limit: number): string {
  return value.trim().slice(0, limit);
}
