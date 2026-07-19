import type { AgentActivityProjection } from '@/contracts/agent-reducer';

export interface PublicToolResultField {
  id: string;
  label: string;
  value: string;
}

export interface PublicToolResultView {
  toolId: string;
  toolLabel: string;
  operation: string;
  summary: string;
  fields: PublicToolResultField[];
  sources: string[];
  preview?: PublicToolSemanticPreview;
  error?: string;
  recovery?: 'approval' | 'permission';
  destination?: {
    href: string;
    label: string;
  };
}

export interface PublicToolSemanticPreview {
  kind: 'atom' | 'book' | 'collection' | 'evidence' | 'timeline' | 'role_book';
  title: string;
  description?: string;
  badges: string[];
  items: Array<{
    id: string;
    label?: string;
    text: string;
    href?: string;
  }>;
}

const toolLabels: Record<string, string> = {
  ime_overview: '控制中心概览',
  ime_input: '输入法',
  ime_voice: '语音输入',
  ime_planning: '规划与任务',
  ime_memory: '个人上下文记忆',
  agent_role_book: 'Agent 角色书',
  ime_knowledge: '文档知识库',
  ime_models: '模型',
  ime_runtime: '诊断与运行时',
  ime_configuration: '历史与配置',
  ime_agents: '多 Agent 协作',
  agent_plan: '任务执行清单',
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
  agent_role_book: { href: '#/memory?layer=role-books', label: '打开角色书' },
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
  get: '读取详情',
  explain: '追溯事实来源',
  review: '审阅草案',
  remember_preview: '预览新增记忆',
  correct_preview: '预览事实更正',
  forget_preview: '预览遗忘',
  remember_apply: '应用新增记忆',
  correct_apply: '应用事实更正',
  forget_apply: '应用遗忘',
  governance_rollback: '回滚记忆变更',
  propose_revision: '提出角色书修订',
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
  ['memoryBookCount', '主题书'],
  ['memoryAtomCount', '当前事实'],
  ['timelineCount', '活动时间线'],
  ['roleBookCount', '角色书'],
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
  const preview = semanticToolPreview(toolId, operation, layers);
  const error = activity.status === 'failed' || payload.isError === true
    ? publicToolError(layers, carrier)
    : '';
  const recovery = error ? publicToolRecovery(error, payload) : undefined;

  return {
    toolId,
    toolLabel,
    operation,
    summary: summary || codeResult.summary || `${toolLabel}${activity.status === 'running' ? '正在处理' : activity.status === 'failed' ? '执行失败' : '已完成'}`,
    fields,
    sources,
    ...(preview ? { preview } : {}),
    ...(error ? { error } : {}),
    ...(recovery ? { recovery } : {}),
    ...(toolDestinations[toolId] ? { destination: toolDestinations[toolId] } : {}),
  };
}

function semanticToolPreview(
  toolId: string,
  operation: string,
  layers: Record<string, unknown>[],
): PublicToolSemanticPreview | undefined {
  if (toolId === 'agent_role_book') return roleBookToolPreview(operation, layers);
  if (toolId !== 'ime_memory') return undefined;

  if (operation === 'read') {
    const book = firstRecord(layers, ['book']);
    if (Object.keys(book).length === 0) return undefined;
    const title = publicDisplayText(book.title, '未命名工具书');
    const description = publicLongText(book.summary);
    const badges = firstStringArray([book], ['tags']).slice(0, 6);
    const memories = firstArray([book], ['memories']);
    const items = memories.slice(0, 8).flatMap((value, index) => {
      const memory = record(value);
      const ref = record(memory.ref);
      const kind = memoryReferenceKind(memory, ref);
      const itemText = publicLongText(memory.text);
      if (!itemText) return [];
      const referenceId = memoryReferenceId(memory, ref);
      const layer = memoryLayerForKind(kind);
      return [{
        id: referenceId || `memory:${index}`,
        label: memoryTypeLabel(text(memory.type)),
        text: itemText,
        ...(referenceId && layer ? {
          href: `#/memory?layer=${encodeURIComponent(layer)}&id=${encodeURIComponent(referenceId)}`,
        } : {}),
      }];
    });
    return {
      kind: 'book',
      title: `《${title}》`,
      ...(description ? { description } : {}),
      badges,
      items,
    };
  }

  if (operation === 'catalog') {
    const items = firstArray(layers, ['items']).slice(0, 8).flatMap((value, index) => {
      const item = record(value);
      const ref = record(item.ref);
      const kind = memoryReferenceKind(item, ref);
      const itemText = publicDisplayText(item.title ?? item.name ?? item.label, '');
      if (!itemText) return [];
      const referenceId = memoryReferenceId(item, ref);
      const layer = memoryLayerForKind(kind);
      return [{
        id: referenceId || `catalog:${index}`,
        label: memoryCatalogKindLabel(kind),
        text: itemText,
        ...(referenceId && layer ? {
          href: `#/memory?layer=${encodeURIComponent(layer)}&id=${encodeURIComponent(referenceId)}`,
        } : {}),
      }];
    });
    if (items.length === 0) return undefined;
    return {
      kind: 'collection',
      title: '个人上下文目录',
      badges: [],
      items,
    };
  }

  if (['search', 'get', 'explain', 'recent', 'list'].includes(operation)) {
    const rawItems = firstArray(layers, ['items']);
    const singleItem = firstRecord(layers, ['item']);
    const values = rawItems.length ? rawItems : Object.keys(singleItem).length ? [singleItem] : [];
    const items = values.slice(0, 8).flatMap((value, index) => {
      const item = record(value);
      const ref = record(item.ref);
      const kind = memoryReferenceKind(item, ref);
      const itemText = publicLongText(
        item.text ?? item.summary ?? item.title ?? item.label ?? item.preview,
      );
      if (!itemText) return [];
      const referenceId = memoryReferenceId(item, ref);
      const layer = memoryLayerForKind(kind);
      return [{
        id: referenceId || `memory-result:${index}`,
        label: memoryCatalogKindLabel(kind),
        text: itemText,
        ...(referenceId && layer ? {
          href: `#/memory?layer=${encodeURIComponent(layer)}&id=${encodeURIComponent(referenceId)}`,
        } : {}),
      }];
    });
    if (!items.length) return undefined;
    const kinds = [...new Set(values.map((value) => {
      const item = record(value);
      const ref = record(item.ref);
      return memoryReferenceKind(item, ref);
    }).filter(Boolean))];
    const previewKind = kinds.length === 1 ? semanticPreviewKind(kinds[0]!) : 'collection';
    return {
      kind: previewKind,
      title: operation === 'search' ? '记忆召回结果' : '记忆详情',
      badges: kinds.map(memoryCatalogKindLabel).filter((value, index, source) => source.indexOf(value) === index),
      items,
    };
  }

  if (['remember_preview', 'correct_preview', 'forget_preview'].includes(operation)) {
    const proposedText = firstPublicText(layers, ['proposedText', 'text', 'summary']);
    const targetId = firstText(layers, ['targetId', 'targetMemoryId']);
    const proposalId = firstText(layers, ['proposalId']);
    const evidenceIds = firstArray(layers, ['evidenceIds']).map(text).filter(Boolean).slice(0, 8);
    const items: PublicToolSemanticPreview['items'] = [];
    if (proposedText) {
      items.push({
        id: targetId || proposalId || 'memory-proposal',
        label: operation === 'forget_preview' ? '将撤回' : operation === 'correct_preview' ? '更正为' : '新增事实',
        text: proposedText,
        ...(targetId ? { href: `#/memory?layer=atoms&id=${encodeURIComponent(targetId)}` } : {}),
      });
    }
    evidenceIds.forEach((evidenceId, index) => items.push({
      id: `proposal-evidence:${evidenceId}`,
      label: '原始证据',
      text: `来源证据 ${index + 1}`,
      href: `#/memory?layer=evidence&id=${encodeURIComponent(evidenceId)}`,
    }));
    if (!items.length) return undefined;
    return {
      kind: 'atom',
      title: '受治理记忆预览',
      badges: ['尚未应用', '需要本机审批'],
      items,
    };
  }

  if (['remember_apply', 'correct_apply', 'forget_apply', 'governance_rollback'].includes(operation)) {
    const memoryId = firstText(layers, ['memoryId', 'previousMemoryId']);
    const summary = firstPublicText(layers, ['summary']);
    if (!memoryId || !summary) return undefined;
    return {
      kind: 'atom',
      title: '记忆治理回执',
      badges: ['已留审计记录'],
      items: [{
        id: memoryId,
        label: '事实谱系',
        text: summary,
        href: `#/memory?layer=atoms&id=${encodeURIComponent(memoryId)}`,
      }],
    };
  }

  return undefined;
}

function roleBookToolPreview(
  operation: string,
  layers: Record<string, unknown>[],
): PublicToolSemanticPreview | undefined {
  const revision = firstRecord(layers, ['revision']);
  const draft = firstRecord(layers, ['draft']);
  const history = firstArray(layers, ['items']);
  const values = history.length
    ? history
    : Object.keys(revision).length
      ? [revision]
      : Object.keys(draft).length
        ? [draft]
        : [];
  const items = values.slice(0, 8).flatMap((value, index) => {
    const item = record(value);
    const revisionId = text(item.revisionId);
    const draftId = text(item.draftId);
    const id = revisionId || draftId || `role-book:${index}`;
    const revisionNumber = finiteNumber(item.revisionNumber);
    const itemText = publicDisplayText(
      item.changeSummary
        ?? item.summary
        ?? (revisionNumber !== undefined ? `角色书修订 #${revisionNumber}` : '角色书待审草案'),
      '角色书修订',
    );
    return [{
      id,
      label: text(item.status) === 'draft' || draftId ? '待审草案' : '角色书修订',
      text: itemText,
      ...(revisionId ? {
        href: `#/memory?layer=role-books&id=${encodeURIComponent(revisionId)}`,
      } : {}),
    }];
  });
  if (!items.length) return undefined;
  return {
    kind: 'role_book',
    title: operation === 'history' ? '角色书修订历史' : 'Agent 角色书',
    badges: operation === 'propose_revision' ? ['仅保存草案', '不能自行激活'] : [],
    items,
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

function publicDisplayText(value: unknown, fallback: string): string {
  return publicStructuredText(text(value))?.slice(0, 180) || fallback;
}

function publicLongText(value: unknown): string {
  return publicStructuredText(text(value)) ?? '';
}

function firstStringArray(layers: Record<string, unknown>[], keys: string[]): string[] {
  return firstArray(layers, keys)
    .map((value) => publicDisplayText(value, ''))
    .filter(Boolean);
}

function memoryTypeLabel(value: string): string {
  return ({
    principle: '原则',
    fact: '事实',
    preference: '偏好',
    decision: '决定',
    event: '事件',
    note: '记录',
  } as Record<string, string>)[value.toLowerCase()] ?? '记忆';
}

function memoryCatalogKindLabel(value: string): string {
  return ({
    atom: '当前事实',
    memory_atom: '当前事实',
    current_fact: '当前事实',
    fact: '当前事实',
    book: '主题书',
    memory_book: '主题书',
    topic: '主题书',
    timeline: '活动时间线',
    daily_timeline: '活动时间线',
    activity_timeline: '活动时间线',
    evidence: '原始证据',
    event: '原始证据',
    role_book: '角色书',
    role_book_revision: '角色书',
    group: '分组',
    tag: '标签',
  } as Record<string, string>)[value.toLowerCase()] ?? '条目';
}

function memoryLayerForKind(value: string): string {
  return ({
    atom: 'atoms',
    memory_atom: 'atoms',
    current_fact: 'atoms',
    fact: 'atoms',
    book: 'books',
    memory_book: 'books',
    topic: 'books',
    timeline: 'timelines',
    daily_timeline: 'timelines',
    activity_timeline: 'timelines',
    evidence: 'evidence',
    event: 'evidence',
    role_book: 'role-books',
    role_book_revision: 'role-books',
  } as Record<string, string>)[value.toLowerCase()] ?? '';
}

function memoryReferenceKind(
  item: Record<string, unknown>,
  ref: Record<string, unknown>,
): string {
  return text(
    ref.referenceKind
    ?? ref.kind
    ?? ref.type
    ?? item.referenceKind
    ?? item.kind
    ?? item.type
    ?? item.docType,
  ).toLowerCase();
}

function memoryReferenceId(
  item: Record<string, unknown>,
  ref: Record<string, unknown>,
): string {
  return text(
    ref.referenceId
    ?? ref.id
    ?? item.referenceId
    ?? item.id
    ?? item.sourceId,
  );
}

function semanticPreviewKind(value: string): PublicToolSemanticPreview['kind'] {
  const layer = memoryLayerForKind(value);
  if (layer === 'atoms') return 'atom';
  if (layer === 'books') return 'book';
  if (layer === 'timelines') return 'timeline';
  if (layer === 'evidence') return 'evidence';
  return 'collection';
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
