import type { AgentActivityProjection } from '@/contracts/agent-reducer';

export interface PublicToolResultField {
  id: string;
  label: string;
  value: string;
}

export interface PublicToolResultView {
  toolLabel: string;
  summary: string;
  fields: PublicToolResultField[];
  sources: string[];
  structuredResult?: PublicStructuredResult;
  error?: string;
  recovery?: 'approval' | 'permission';
  destination?: {
    href: string;
    label: string;
  };
}

export type PublicStructuredResult =
  | string
  | number
  | boolean
  | PublicStructuredResult[]
  | { [key: string]: PublicStructuredResult };

const toolLabels: Record<string, string> = {
  ime_overview: '控制中心概览',
  ime_input: '输入法',
  ime_voice: '语音输入',
  ime_planning: '规划与任务',
  ime_memory: '记忆与工具书',
  ime_knowledge: '文档知识库',
  ime_models: '模型',
  ime_runtime: '诊断与运行时',
  ime_configuration: '历史与配置',
  ime_agents: '多 Agent 协作',
  agent_plan: '当前回合计划',
  read: '读取文件',
  read_file: '读取文件',
  write: '写入文件',
  write_file: '写入文件',
  workspace_write_file: '写入文件',
  edit: '编辑文件',
  edit_file: '编辑文件',
  workspace_edit_file: '编辑文件',
  bash: '运行命令',
  shell: '运行命令',
  grep: '搜索文本',
  find: '查找文件',
  ls: '浏览目录',
  todo: '待办事项',
  write_todos: '待办事项',
  update_plan: '更新计划',
  workspace_list: '工作区浏览',
  workspace_read: '工作区读取',
  workspace_shell: '受控命令',
};

const toolDestinations: Record<string, { href: string; label: string }> = {
  ime_overview: { href: '#/overview', label: '打开总览' },
  ime_input: { href: '#/input', label: '打开输入法' },
  ime_voice: { href: '#/voice', label: '打开语音输入' },
  ime_planning: { href: '#/planning', label: '打开规划' },
  ime_memory: { href: '#/memory', label: '打开记忆' },
  ime_knowledge: { href: '#/knowledge', label: '打开知识库' },
  ime_models: { href: '#/configuration', label: '打开模型配置' },
  ime_runtime: { href: '#/diagnostics', label: '打开诊断' },
  ime_configuration: { href: '#/configuration', label: '打开配置' },
  ime_agents: { href: '#/rooms', label: '打开 Rooms' },
};

const operationLabels: Record<string, string> = {
  status: '检查状态',
  capabilities: '查看可用能力',
  recent_activity: '查看近期活动',
  get_settings: '读取设置',
  preview_settings: '预览设置变更',
  apply_settings: '应用设置变更',
  rollback_settings: '撤销设置变更',
  profile: '查看当前方案',
  candidate_explain: '解释候选结果',
  dashboard: '查看任务面板',
  catalog: '查看目录',
  read: '读取内容',
  recent: '查看近期记录',
  search: '搜索',
  list_bases: '查看知识库',
  find: '定位文档证据',
  open: '读取引用窗口',
  recall: '检索知识',
  deep_recall: '深度检索',
  route_status: '检查检索路由',
  profiles: '查看模型方案',
  probe: '检查模型连接',
  cache_stats: '查看缓存状态',
  health: '检查运行状态',
  components: '检查运行组件',
  diagnose: '运行诊断',
  history: '查看历史摘要',
  audit: '查看审计记录',
  delegate: '委派协作任务',
  artifact: '查看协作产物',
  list: '浏览工作区',
  run: '运行受控命令',
};

const componentLabels: Record<string, string> = {
  inputMethod: '输入法',
  sidecar: '控制服务',
  predictor: '预测服务',
  foregroundContext: '前台上下文',
  hybridRag: '混合检索',
  memoryCompiler: '记忆整理',
  sqlite: '本地数据库',
  voiceAgent: '语音代理',
  voiceMicrophone: '麦克风权限',
  voiceAccessibility: '辅助功能权限',
  voiceRecognition: '语音定稿',
};

const countFields: Array<[string, string]> = [
  ['count', '结果数量'],
  ['resultCount', '结果数量'],
  ['itemCount', '记录数量'],
  ['entryCount', '条目数量'],
  ['changeCount', '变更数量'],
  ['taskCount', '任务数量'],
  ['runCount', '运行数量'],
  ['providerCount', '服务数量'],
  ['profileCount', '方案数量'],
  ['completed', '已完成'],
  ['artifacts', '产物数量'],
];

const booleanFields: Array<[string, string, string, string]> = [
  ['enabled', '功能状态', '已启用', '未启用'],
  ['connected', '连接状态', '已连接', '未连接'],
  ['ready', '就绪状态', '已就绪', '未就绪'],
  ['healthy', '健康状态', '正常', '需要检查'],
  ['available', '可用状态', '可用', '不可用'],
  ['readOnly', '能力范围', '只读', '包含受确认保护的操作'],
  ['reviewRequired', '审阅要求', '需要审阅', '无需额外审阅'],
  ['approvalRequiredForApply', '应用保护', '需要本机确认', '无需本机确认'],
];

const memoryCountFields: Array<[string, string]> = [
  ['eventCount', '输入记录'],
  ['memoryItemCount', '记忆项目'],
  ['memoryBookCount', '记忆工具书'],
  ['memoryAtomCount', '记忆原子'],
  ['retrievalDocCount', '可检索文档'],
  ['pendingCompileEvents', '待整理记录'],
];

export function publicToolResultView(activity: AgentActivityProjection): PublicToolResultView {
  const payload = activity.payload;
  const carrier = record(payload.result ?? payload.partialResult);
  const carrierDetails = record(carrier.details);
  const envelope = Object.keys(carrierDetails).length > 0 ? carrierDetails : carrier;
  const envelopeResult = record(envelope.result);
  const carrierResult = record(carrier.result);
  const domain = Object.keys(envelopeResult).length > 0 ? envelopeResult : carrierResult;
  const publicResult = record(payload.publicResult);
  const layers = [domain, envelope, carrier, publicResult, payload];
  const toolId = firstText(
    [payload, envelope, carrier],
    ['toolId', 'toolName', 'tool'],
  ).toLowerCase();
  const toolLabel = toolLabels[toolId] ?? '工具操作';
  const fields: PublicToolResultField[] = [];
  const seen = new Set<string>();
  const append = (id: string, label: string, value: string) => {
    if (!value || seen.has(id)) return;
    seen.add(id);
    fields.push({ id, label, value });
  };

  append('status', '状态', activityStatusLabel(activity.status));

  const operation = firstText([envelope, carrier, payload], ['operation']);
  if (operation) {
    const operationLabel = toolId === 'agent_plan'
      ? ({ list: '查看计划', update: '更新计划' } as Record<string, string>)[operation]
      : operationLabels[operation];
    append('operation', '操作', operationLabel ?? '受控操作');
  }

  const ok = firstBoolean([envelope, domain, carrier], ['ok']);
  if (ok !== undefined) append('ok', '执行结果', ok ? '成功' : '未成功');

  const resultStatus = publicStatusLabel(firstText(layers, ['status', 'state', 'availability']));
  if (resultStatus) append('resultStatus', '服务状态', resultStatus);

  const summary = firstPublicText(layers, ['summary', 'message', 'label']);
  if (summary) append('summary', activity.kind === 'tool_progress' ? '当前进度' : '结果摘要', summary);

  for (const [key, label] of countFields) {
    const value = firstFiniteNumber(layers, [key]);
    if (value !== undefined) append(key, label, `${value} 项`);
  }
  for (const [key, label, trueLabel, falseLabel] of booleanFields) {
    const value = firstBoolean(layers, [key]);
    if (value !== undefined) append(key, label, value ? trueLabel : falseLabel);
  }

  const tools = firstArray(layers, ['tools']);
  const capabilityLabels = tools
    .map((item) => capabilityLabel(item))
    .filter((item): item is string => Boolean(item));
  const declaredToolCount = firstFiniteNumber(layers, ['toolCount']);
  if (declaredToolCount !== undefined || capabilityLabels.length > 0) {
    append('toolCount', '能力数量', `${declaredToolCount ?? capabilityLabels.length} 项`);
  }
  if (capabilityLabels.length > 0) {
    append('tools', '可用能力', boundedList(capabilityLabels, 6));
  }

  const approvalOperations = firstArray(layers, ['approvalGatedOperations']);
  if (approvalOperations.length > 0) {
    append('approvalCount', '本机确认保护', `${approvalOperations.length} 项操作`);
  }

  const components = firstRecord(layers, ['components']);
  if (Object.keys(components).length > 0) {
    const unavailableIds = firstArray(layers, ['unhealthyComponents'])
      .map((item) => text(item))
      .filter(Boolean);
    const readiness = Object.values(components)
      .map((item) => record(item).ok)
      .filter((item): item is boolean => typeof item === 'boolean');
    if (readiness.length > 0) {
      append('components', '运行组件', `${readiness.filter(Boolean).length} / ${readiness.length} 可用`);
    } else if (unavailableIds.length <= Object.keys(components).length) {
      append('components', '运行组件', `${Object.keys(components).length - unavailableIds.length} / ${Object.keys(components).length} 可用`);
    }
    const unavailable = (unavailableIds.length > 0
      ? unavailableIds
      : Object.entries(components).filter(([, item]) => record(item).ok === false).map(([key]) => key))
      .map((key) => componentLabels[key])
      .filter((item): item is string => Boolean(item));
    if (unavailable.length > 0) {
      append('unavailableComponents', '需要检查', boundedList(unavailable, 5));
    } else if (unavailableIds.length > 0) {
      append('unavailableComponents', '需要检查', `${unavailableIds.length} 项组件`);
    }
  }

  const memory = firstRecord(layers, ['memory']);
  for (const [key, label] of memoryCountFields) {
    const value = finiteNumber(memory[key]);
    if (value !== undefined) append(`memory.${key}`, label, `${value} 条`);
  }

  const items = firstArray(layers, ['items']);
  if (items.length > 0 && !seen.has('resultCount') && !seen.has('itemCount')) {
    append('items', toolId === 'ime_knowledge' ? '引用数量' : '近期活动', `${items.length} 条`);
  }
  const sourceCounts = safeActivitySourceCounts(items);
  if (sourceCounts) append('activitySources', '活动来源', sourceCounts);

  const writePolicy = firstPublicText(layers, ['writePolicy', 'safety']);
  if (writePolicy) append('writePolicy', '写入保护', writePolicy);

  const codeResult = publicCodeToolResult(toolId, record(payload.args), publicResult, envelope, carrier);
  if (codeResult.file) append('file', '文件', codeResult.file);
  if (codeResult.lines !== undefined) append('lineCount', '行数', `${codeResult.lines} 行`);
  if (codeResult.additions !== undefined || codeResult.deletions !== undefined) {
    append('changes', '变更', `+${codeResult.additions ?? 0} / -${codeResult.deletions ?? 0}`);
  }

  const sources = toolId === 'ime_knowledge'
    ? safeKnowledgeSourceLabels(items)
    : safeSourceLabels(payload.sources ?? payload.documents ?? payload.books);
  const structuredResult = publicStructuredResult(
    Object.keys(domain).length > 0 ? domain : envelope,
  );
  const error = activity.status === 'failed' || payload.isError === true
    ? publicToolError(layers, carrier)
    : '';
  const recovery = error ? publicToolRecovery(error, payload) : undefined;

  return {
    toolLabel,
    summary: summary || codeResult.summary || `${toolLabel}${activity.status === 'running' ? '正在处理' : activity.status === 'failed' ? '执行失败' : '已完成'}`,
    fields,
    sources,
    ...(structuredResult !== undefined ? { structuredResult } : {}),
    ...(error ? { error } : {}),
    ...(recovery ? { recovery } : {}),
    ...(toolDestinations[toolId] ? { destination: toolDestinations[toolId] } : {}),
  };
}

interface PublicCodeToolResult {
  summary: string;
  file: string;
  lines?: number;
  additions?: number;
  deletions?: number;
}

function publicCodeToolResult(
  toolId: string,
  args: Record<string, unknown>,
  publicResult: Record<string, unknown>,
  envelope: Record<string, unknown>,
  carrier: Record<string, unknown>,
): PublicCodeToolResult {
  const fileTools = new Set([
    'read', 'read_file', 'workspace_read',
    'write', 'write_file', 'workspace_write_file',
    'edit', 'edit_file', 'workspace_edit_file',
  ]);
  const rawPath = firstText([publicResult, args, envelope, carrier], ['relativePath', 'fileName', 'file_path', 'path']);
  const file = fileTools.has(toolId) ? publicWorkspacePath(rawPath) : '';
  if (['write', 'write_file', 'workspace_write_file'].includes(toolId)) {
    const lines = firstFiniteNumber([publicResult], ['lineCount']) ?? publicLineCount(text(args.content));
    const additions = firstFiniteNumber([publicResult], ['additions']) ?? lines;
    return {
      file,
      ...(lines !== undefined ? { lines } : {}),
      ...(additions !== undefined ? { additions } : {}),
      summary: file ? `${file}${lines !== undefined ? ` +${lines}` : ' 已写入'}` : '文件已写入',
    };
  }
  if (['edit', 'edit_file', 'workspace_edit_file'].includes(toolId)) {
    const diff = firstText([envelope, carrier], ['diff', 'patch']);
    const changes = publicDiffCounts(diff);
    const changeLabel = changes.additions !== undefined || changes.deletions !== undefined
      ? ` +${changes.additions ?? 0} / -${changes.deletions ?? 0}`
      : ' 已更新';
    return { file, summary: file ? `${file}${changeLabel}` : '文件已更新', ...changes };
  }
  if (['read', 'read_file', 'workspace_read'].includes(toolId)) {
    const truncation = firstRecord([envelope, carrier], ['truncation']);
    const totalLines = firstFiniteNumber([truncation], ['totalLines']);
    const lines = totalLines ?? publicLineCount(publicToolContentText(carrier));
    return {
      file,
      ...(lines !== undefined ? { lines } : {}),
      summary: file ? `${file}${lines !== undefined ? ` · ${lines} 行` : ' 已读取'}` : '文件已读取',
    };
  }
  return { file: '', summary: '' };
}

function publicWorkspacePath(value: string): string {
  const normalized = value.replace(/\\/gu, '/').replace(/\/{2,}/gu, '/').trim();
  if (!normalized || normalized.length > 1_000) return '';
  if (/(?:api.?key|authorization|cookie|password|secret|bearer\s)/iu.test(normalized)) return '';
  const parts = normalized.split('/').filter(Boolean);
  if (parts.length === 0) return '';
  const absolute = normalized.startsWith('/') || normalized.startsWith('~/') || /^[a-z]:\//iu.test(normalized);
  const unsafeRelative = parts.some((part) => part === '..' || part === '.');
  const candidate = absolute || unsafeRelative ? parts.at(-1) ?? '' : parts.join('/');
  if (!candidate || candidate.length > 240 || /[\u0000-\u001f]/u.test(candidate)) return '';
  return candidate;
}

function publicLineCount(value: string): number | undefined {
  if (!value) return undefined;
  const lines = value.replace(/\r\n?/gu, '\n').split('\n');
  while (lines.length > 0 && lines.at(-1) === '') lines.pop();
  return Math.max(lines.length, 1);
}

function publicDiffCounts(value: string): Pick<PublicCodeToolResult, 'additions' | 'deletions'> {
  if (!value) return {};
  let additions = 0;
  let deletions = 0;
  for (const line of value.replace(/\r\n?/gu, '\n').split('\n').slice(0, 20_000)) {
    if (line.startsWith('+') && !line.startsWith('+++')) additions += 1;
    if (line.startsWith('-') && !line.startsWith('---')) deletions += 1;
  }
  return additions || deletions ? { additions, deletions } : {};
}

function publicToolContentText(carrier: Record<string, unknown>): string {
  const content = Array.isArray(carrier.content) ? carrier.content : [];
  return content
    .slice(0, 12)
    .map((item) => text(record(item).text))
    .filter(Boolean)
    .join('\n');
}

const privateResultKey = /(?:^_|^id$|(?:approval|session|request|toolCall|event)Id$|token|secret|password|passphrase|api.?key|authorization|cookie|credential|reasoning|thinking|chain.?of.?thought|system.?prompt|prompt|headers?|environment|\benv\b|stack|traceback|raw|request.?body|response.?body|source.?path|file.?path|absolute.?path|^path$|stdout|stderr|^diff$|^patch$)/iu;

function publicStructuredResult(value: unknown, depth = 0): PublicStructuredResult | undefined {
  if (depth > 3 || value === null || value === undefined) return undefined;
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value === 'string') return publicStructuredText(value);
  if (Array.isArray(value)) {
    const items = value
      .slice(0, 12)
      .map((item) => publicStructuredResult(item, depth + 1))
      .filter((item): item is PublicStructuredResult => item !== undefined);
    return items.length > 0 ? items : undefined;
  }
  const source = record(value);
  const entries: Array<[string, PublicStructuredResult]> = [];
  for (const [rawKey, rawValue] of Object.entries(source).slice(0, 32)) {
    const key = rawKey.trim().slice(0, 80);
    if (!key || privateResultKey.test(key)) continue;
    if (/^(?:content|text)$/iu.test(key)) {
      if (typeof rawValue === 'string' || isToolContentBlocks(rawValue)) continue;
    }
    const safeValue = publicStructuredResult(rawValue, depth + 1);
    if (safeValue === undefined) continue;
    entries.push([key, safeValue]);
  }
  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
}

function isToolContentBlocks(value: unknown): boolean {
  if (!Array.isArray(value) || value.length === 0) return false;
  return value.every((item) => {
    const block = record(item);
    return ['text', 'image'].includes(text(block.type).toLowerCase())
      && (Object.hasOwn(block, 'text') || Object.hasOwn(block, 'data'));
  });
}

function publicStructuredText(value: string): string | undefined {
  let normalized = value.replace(/\s+/gu, ' ').trim();
  if (!normalized) return undefined;
  if (/^(?:\{|\[)/u.test(normalized)) return undefined;
  if (/(?:api.?key|authorization|cookie|password|secret|bearer\s|chain[- ]?of[- ]?thought|private reasoning|思维链)/iu.test(normalized)) return undefined;
  if (/(?:file:\/\/|\/Users\/|\/Volumes\/|\/private\/var\/|\/var\/folders\/)/u.test(normalized)) return undefined;
  normalized = normalized
    .replace(/\[REDACTED_SECRET\]/gu, '已隐藏敏感值')
    .replace(/\[REDACTED_PATH\]/gu, '已隐藏本机路径');
  return normalized.slice(0, 500);
}

function publicToolError(layers: Record<string, unknown>[], carrier: Record<string, unknown>): string {
  for (const layer of layers) {
    for (const key of ['error', 'errorMessage', 'message', 'summary']) {
      const value = publicStructuredText(text(layer[key]));
      if (value) return value;
    }
  }
  const content = Array.isArray(carrier.content) ? carrier.content : [];
  for (const item of content.slice(0, 4)) {
    const value = publicStructuredText(text(record(item).text));
    if (value) return value;
  }
  return '工具执行失败，但没有返回可公开展示的错误明细。';
}

function publicToolRecovery(
  error: string,
  payload: Record<string, unknown>,
): 'approval' | 'permission' | undefined {
  if (text(payload.approvalId) && text(payload.payloadSha256)) return 'approval';
  if (/(?:approval required|requires approval|pending approval|需要(?:本机)?(?:审批|批准)|等待(?:审批|批准)|审批后|需(?:要)?本机确认)/iu.test(error)) {
    return 'permission';
  }
  if (/(?:permission denied|access denied|not allowed|allowlist|sandbox|权限不足|没有权限|未授权|授权目录|只读模式|运行协调)/iu.test(error)) {
    return 'permission';
  }
  return undefined;
}

function safeKnowledgeSourceLabels(items: unknown[]): string[] {
  const labels: string[] = [];
  for (const value of items) {
    const item = record(value);
    const fileName = publicFileName(item.fileName ?? item.name ?? item.title);
    if (!fileName) continue;
    const citation = record(item.citation);
    const page = finiteNumber(citation.page);
    const startLine = finiteNumber(citation.startLine ?? item.startLine);
    const endLine = finiteNumber(citation.endLine ?? item.endLine);
    const location = page !== undefined && page > 0
      ? `第 ${page} 页`
      : startLine !== undefined && startLine > 0
        ? `${startLine}${endLine !== undefined && endLine > startLine ? `-${endLine}` : ''} 行`
        : '';
    const label = location ? `${fileName} · ${location}` : fileName;
    if (!labels.includes(label)) labels.push(label);
    if (labels.length >= 8) break;
  }
  return labels;
}

function publicFileName(value: unknown): string {
  const normalized = text(value).replace(/\s+/gu, ' ').trim();
  if (!normalized || normalized.length > 240) return '';
  if (/[\\/]/u.test(normalized)) return '';
  if (/(?:api.?key|authorization|cookie|password|secret|bearer\s)/iu.test(normalized)) return '';
  return normalized;
}

export function safeSourceLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const labels: string[] = [];
  for (const item of value) {
    const candidate = typeof item === 'string'
      ? publicText(item)
      : publicText(record(item).title ?? record(item).name ?? record(item).label);
    if (candidate && !labels.includes(candidate)) labels.push(candidate);
    if (labels.length >= 8) break;
  }
  return labels;
}

function capabilityLabel(value: unknown): string {
  const item = record(value);
  const id = text(item.id);
  if (toolLabels[id]) return toolLabels[id];
  return publicText(item.displayName ?? item.label);
}

function safeActivitySourceCounts(items: unknown[]): string {
  const labels: Record<string, string> = {
    voice: '语音',
    rime: '输入法',
    keyboard: '键盘',
    import: '导入',
  };
  const counts = new Map<string, number>();
  for (const item of items) {
    const source = text(record(item).source).toLowerCase();
    const label = labels[source];
    if (!label) continue;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()].map(([label, count]) => `${label} ${count} 条`).join('、');
}

function boundedList(values: string[], limit: number): string {
  const unique = [...new Set(values)];
  const visible = unique.slice(0, limit);
  return `${visible.join('、')}${unique.length > visible.length ? `，另 ${unique.length - visible.length} 项` : ''}`;
}

function activityStatusLabel(status: AgentActivityProjection['status']): string {
  switch (status) {
    case 'running': return '进行中';
    case 'waiting': return '等待确认';
    case 'failed': return '失败';
    case 'completed': return '已完成';
  }
}

function publicStatusLabel(value: string): string {
  return ({
    online: '在线',
    offline: '离线',
    ready: '可用',
    running: '运行中',
    healthy: '正常',
    available: '可用',
    connected: '已连接',
    disabled: '未启用',
    unavailable: '不可用',
    degraded: '部分可用',
    failed: '失败',
    completed: '已完成',
    pending: '等待处理',
  } as Record<string, string>)[value.toLowerCase()] ?? publicText(value);
}

function firstRecord(layers: Record<string, unknown>[], keys: string[]): Record<string, unknown> {
  for (const layer of layers) {
    for (const key of keys) {
      if (!Object.hasOwn(layer, key)) continue;
      const value = record(layer[key]);
      if (Object.keys(value).length > 0) return value;
    }
  }
  return {};
}

function firstArray(layers: Record<string, unknown>[], keys: string[]): unknown[] {
  for (const layer of layers) {
    for (const key of keys) {
      if (Object.hasOwn(layer, key) && Array.isArray(layer[key])) return layer[key] as unknown[];
    }
  }
  return [];
}

function firstText(layers: Record<string, unknown>[], keys: string[]): string {
  for (const layer of layers) {
    for (const key of keys) {
      const value = text(layer[key]);
      if (value) return value;
    }
  }
  return '';
}

function firstPublicText(layers: Record<string, unknown>[], keys: string[]): string {
  for (const layer of layers) {
    for (const key of keys) {
      const value = publicText(layer[key]);
      if (value) return value;
    }
  }
  return '';
}

function firstBoolean(layers: Record<string, unknown>[], keys: string[]): boolean | undefined {
  for (const layer of layers) {
    for (const key of keys) {
      const value = layer[key];
      if (typeof value === 'boolean') return value;
    }
  }
  return undefined;
}

function firstFiniteNumber(layers: Record<string, unknown>[], keys: string[]): number | undefined {
  for (const layer of layers) {
    for (const key of keys) {
      const value = finiteNumber(layer[key]);
      if (value !== undefined) return value;
    }
  }
  return undefined;
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
}

function publicText(value: unknown): string {
  const normalized = text(value).replace(/\s+/gu, ' ').trim();
  if (!normalized || normalized.length > 500) return '';
  if (/^(?:\{|\[)/u.test(normalized)) return '';
  if (/(?:\[REDACTED_|api.?key|authorization|cookie|password|secret|bearer\s|chain[- ]?of[- ]?thought|private reasoning|思维链)/iu.test(normalized)) return '';
  if (/(?:file:\/\/|\/Users\/|\/Volumes\/|\/private\/var\/|\/var\/folders\/)/u.test(normalized)) return '';
  if (/^[a-z][a-z0-9_.:/-]*$/iu.test(normalized)) return '';
  return normalized.slice(0, 240);
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
