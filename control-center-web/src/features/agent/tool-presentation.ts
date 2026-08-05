const toolNames: Record<string, string> = {
  overview: '当前状态',
  input: '输入法与词库',
  voice: '语音输入',
  planning: '任务与安排',
  memory: '我的记忆',
  agent_role_book: '伙伴记忆',
  knowledge: '知识库',
  models: '模型与连接',
  runtime: '运行检查',
  configuration: '设置与记录',
  agents: '多人协作',
  browser: '浏览网页',
  plugins: '扩展能力',
  todo: 'Todo',
  agent_schedule: '定时提醒',
  desktop_semantic: '操作当前应用',
  room_state: '查看协作状态',
  room_post: '发送协作消息',
  room_commit: '提交工作结果',
  room_collaborate: '邀请伙伴协作',
  skill_load: '读取技能说明',
  tool_load: '读取工具说明',
  workspace_list: '浏览项目文件',
  workspace_search: '搜索项目内容',
  workspace_lsp: '代码智能',
  control_api: '调用控制服务',
  read: '读取文件',
  write: '写入文件',
  edit: '编辑文件',
  bash: '运行命令',
  grep: '搜索文本',
  find: '查找文件',
  ls: '浏览目录',
};

const toolIntents: Record<string, string> = {
  overview: '帮我看看当前状态',
  input: '帮我调整输入法或词库',
  voice: '帮我检查语音输入',
  planning: '帮我整理任务与安排',
  memory: '帮我从记忆里找找',
  agent_role_book: '帮我查看伙伴记忆',
  knowledge: '帮我从知识库里查找',
  models: '帮我检查模型与连接',
  runtime: '帮我检查运行状态',
  configuration: '帮我查看设置或变更记录',
  agents: '请伙伴和我一起完成',
  browser: '帮我查看当前网页',
  todo: '帮我维护 Todo',
  read: '帮我读取这个项目文件',
  edit: '帮我编辑这个项目文件',
  write: '帮我写入这个项目文件',
  bash: '帮我运行这条项目命令',
  workspace_list: '帮我看看项目里有哪些文件',
  workspace_search: '帮我在项目里搜索',
};

const codingToolAliases: Record<string, string> = {
  read_file: 'read',
  workspace_read: 'read',
  edit_file: 'edit',
  workspace_edit_file: 'edit',
  workspace_edit: 'edit',
  workspace_patch: 'edit',
  apply_patch: 'edit',
  write_file: 'write',
  workspace_write_file: 'write',
  workspace_write: 'write',
  shell: 'bash',
  workspace_shell: 'bash',
  workspace_job: 'bash',
  workspace_search: 'grep',
  workspace_list: 'ls',
};

// Catalogs expose four public coding capabilities. Keep this projection
// separate from `canonicalToolId`: timeline activity still needs precise
// action labels such as "search" and "browse" even though those operations
// belong to the public read capability.
const publicCatalogCodingToolAliases: Record<string, 'read' | 'edit' | 'write' | 'bash'> = {
  read: 'read',
  read_file: 'read',
  workspace_read: 'read',
  workspace_search: 'read',
  workspace_list: 'read',
  workspace_lsp: 'read',
  grep: 'read',
  find: 'read',
  ls: 'read',
  edit: 'edit',
  edit_file: 'edit',
  workspace_edit_file: 'edit',
  workspace_edit: 'edit',
  workspace_patch: 'edit',
  apply_patch: 'edit',
  patch: 'edit',
  write: 'write',
  write_file: 'write',
  workspace_write_file: 'write',
  workspace_write: 'write',
  bash: 'bash',
  shell: 'bash',
  workspace_shell: 'bash',
  workspace_job: 'bash',
  job: 'bash',
};

const publicCodingToolIds = new Set(['read', 'edit', 'write', 'bash']);

export function canonicalToolId(toolId: string): string {
  const normalizedId = toolId.trim().toLowerCase();
  return codingToolAliases[normalizedId] ?? normalizedId;
}

interface PublicToolCatalogEntry {
  id: string;
  displayName: string;
  description?: string;
  canonicalId?: string;
  kind?: string;
  enabled?: boolean;
  effectiveOperations?: unknown;
  operations?: unknown;
  profileOperations?: unknown;
  sessionModes?: unknown;
  requiredPermissions?: unknown;
  availability?: unknown;
  status?: unknown;
  riskLevel?: unknown;
  risk?: unknown;
  alwaysAvailable?: boolean;
}

/**
 * Project historical/provider tool aliases into one stable public catalog.
 * Runtime authorization remains owned by the backend; this only prevents one
 * capability from appearing as several competing tools in the UI.
 */
export function projectPublicToolCatalog<T extends PublicToolCatalogEntry>(
  items: readonly T[],
): T[] {
  const projected: T[] = [];
  const indexByCanonicalId = new Map<string, number>();
  const canonicalSourceKeys = new Set<string>();
  for (const item of items) {
    if (item.kind !== undefined && item.kind !== 'tool') {
      projected.push(item);
      continue;
    }
    const canonicalId = publicCatalogToolId(item);
    if (!canonicalId) continue;
    const sourceIsCanonical = originalCatalogId(item) === canonicalId;
    const normalized = normalizePublicToolCatalogItem(item, canonicalId);
    const key = `tool:${canonicalId}`;
    const existingIndex = indexByCanonicalId.get(key);
    if (existingIndex === undefined) {
      indexByCanonicalId.set(key, projected.length);
      projected.push(normalized);
      if (sourceIsCanonical) canonicalSourceKeys.add(key);
      continue;
    }
    projected[existingIndex] = mergePublicToolCatalogItems(
      projected[existingIndex]!,
      normalized,
      canonicalId,
      sourceIsCanonical && !canonicalSourceKeys.has(key),
    );
    if (sourceIsCanonical) canonicalSourceKeys.add(key);
  }
  return projected;
}

/** Canonicalize only tool capability keys; skill and extension keys are kept. */
export function projectPublicToolPreferenceMap<T>(
  preferences: Readonly<Record<string, T>>,
): Record<string, T> {
  const projected: Record<string, T> = {};
  const canonicalSources = new Set<string>();
  for (const [sourceKey, value] of Object.entries(preferences)) {
    const targetKey = canonicalCapabilityKey(sourceKey);
    const sourceIsCanonical = targetKey === sourceKey.trim().toLowerCase();
    if (!(targetKey in projected) || sourceIsCanonical || !canonicalSources.has(targetKey)) {
      projected[targetKey] = value;
      if (sourceIsCanonical) canonicalSources.add(targetKey);
    }
  }
  return projected;
}

export function publicToolName(toolId: string, fallback = ''): string {
  const normalizedId = canonicalToolId(toolId);
  const mapped = toolNames[normalizedId];
  if (mapped) return mapped;
  const readableFallback = fallback.trim();
  return isReadableToolName(readableFallback) ? readableFallback : '工具操作';
}

export function toolIntentPrompt(toolId: string, fallback = ''): string {
  const normalizedId = canonicalToolId(toolId);
  return toolIntents[normalizedId] ?? `帮我用${publicToolName(normalizedId, fallback)}处理`;
}

function isReadableToolName(value: string): boolean {
  return Boolean(value)
    && value.length <= 64
    && !/pathId|schema|receipt|operation|policy|profile|\/api\/|https?:\/\//i.test(value);
}

function publicCatalogToolId(item: PublicToolCatalogEntry): string {
  const capabilityId = typeof item.canonicalId === 'string'
    && item.canonicalId.toLowerCase().startsWith('tool:')
    ? item.canonicalId.slice(5)
    : item.id;
  return canonicalCatalogToolId(capabilityId);
}

function normalizePublicToolCatalogItem<T extends PublicToolCatalogEntry>(
  item: T,
  canonicalId: string,
): T {
  const source = item as PublicToolCatalogEntry & Record<string, unknown>;
  return {
    ...item,
    id: canonicalId,
    displayName: publicCodingToolIds.has(canonicalId)
      ? publicToolName(canonicalId, item.displayName)
      : item.displayName,
    ...(typeof item.canonicalId === 'string' ? { canonicalId: `tool:${canonicalId}` } : {}),
    ...(Array.isArray(source.operations) ? { operations: uniqueStrings(source.operations) } : {}),
    ...(Array.isArray(source.effectiveOperations)
      ? { effectiveOperations: uniqueStrings(source.effectiveOperations) }
      : {}),
  } as T;
}

function mergePublicToolCatalogItems<T extends PublicToolCatalogEntry>(
  left: T,
  right: T,
  canonicalId: string,
  preferRight: boolean,
): T {
  const preferred = preferRight ? right : left;
  const fallback = preferred === left ? right : left;
  const merged = {
    ...fallback,
    ...preferred,
    description: preferred.description || fallback.description,
  } as unknown as T & Record<string, unknown>;
  for (const key of ['operations', 'effectiveOperations', 'sessionModes', 'requiredPermissions'] as const) {
    const values = uniqueStrings([
      ...arrayValue((left as unknown as Record<string, unknown>)[key]),
      ...arrayValue((right as unknown as Record<string, unknown>)[key]),
    ]);
    if (values.length) merged[key] = values;
  }
  const profiles = mergeStringArrayRecords(left.profileOperations, right.profileOperations);
  if (Object.keys(profiles).length) merged.profileOperations = profiles;
  const enabledValues = [left.enabled, right.enabled].filter(
    (value): value is boolean => typeof value === 'boolean',
  );
  if (enabledValues.length) {
    merged.enabled = enabledValues.some(Boolean);
  }
  if (left.alwaysAvailable !== undefined || right.alwaysAvailable !== undefined) {
    merged.alwaysAvailable = left.alwaysAvailable === true || right.alwaysAvailable === true;
  }
  merged.availability = preferredAvailability(left.availability, right.availability, preferred.availability);
  merged.status = preferredAvailability(left.status, right.status, preferred.status);
  merged.riskLevel = highestRisk(left.riskLevel, right.riskLevel, preferred.riskLevel);
  merged.risk = highestRisk(left.risk, right.risk, preferred.risk);
  return normalizePublicToolCatalogItem(merged as T, canonicalId);
}

function originalCatalogId(item: PublicToolCatalogEntry): string {
  return typeof item.canonicalId === 'string' && item.canonicalId.toLowerCase().startsWith('tool:')
    ? item.canonicalId.slice(5).trim().toLowerCase()
    : item.id.trim().toLowerCase();
}

function canonicalCapabilityKey(value: string): string {
  const normalized = value.trim().toLowerCase();
  return normalized.startsWith('tool:')
    ? `tool:${canonicalCatalogToolId(normalized.slice(5))}`
    : value;
}

function canonicalCatalogToolId(toolId: string): string {
  const normalizedId = toolId.trim().toLowerCase();
  return publicCatalogCodingToolAliases[normalizedId] ?? canonicalToolId(normalizedId);
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function uniqueStrings(values: readonly unknown[]): string[] {
  return [...new Set(values.filter((value): value is string => typeof value === 'string' && Boolean(value)))];
}

function mergeStringArrayRecords(left: unknown, right: unknown): Record<string, string[]> {
  const leftRecord = objectValue(left);
  const rightRecord = objectValue(right);
  return Object.fromEntries([...new Set([...Object.keys(leftRecord), ...Object.keys(rightRecord)])].map((key) => [
    key,
    uniqueStrings([...arrayValue(leftRecord[key]), ...arrayValue(rightRecord[key])]),
  ]));
}

function preferredAvailability(left: unknown, right: unknown, fallback: unknown): unknown {
  const values = [left, right].filter((value): value is string => typeof value === 'string');
  for (const status of ['online', 'ready', 'installed', 'available', 'unconfigured', 'offline', 'disabled']) {
    if (values.includes(status)) return status;
  }
  return fallback;
}

function highestRisk(left: unknown, right: unknown, fallback: unknown): unknown {
  const ranks: Record<string, number> = { R0: 0, R1: 1, R2: 2, R3: 3 };
  const risks = [left, right].filter((value): value is string => typeof value === 'string');
  return risks.sort((a, b) => (ranks[b] ?? -1) - (ranks[a] ?? -1))[0] ?? fallback;
}

function objectValue(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
