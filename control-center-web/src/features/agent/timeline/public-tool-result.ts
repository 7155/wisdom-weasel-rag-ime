import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { approvalDecisionReasonLabel, approvalDecisionView, approvalNeedsHumanDecision } from '@/contracts/approval-decision';
import { normalizeAgentBlock, type UiAgentBlock } from '@/contracts/ui-events';
import { canonicalToolId, publicToolName } from '../tool-presentation';
const PUBLIC_TOOL_OUTPUT_MAX_CHARS = 6_000;
const PUBLIC_TOOL_OUTPUT_MAX_LINES = 40;

export interface PublicToolActivityProjection {
  kind: string;
  status: AgentActivityProjection['status'] | 'aborted';
  payload: Record<string, unknown>;
}

export interface PublicToolResultField {
  id: string;
  label: string;
  value: string;
}

export interface PublicToolRequestField extends PublicToolResultField {
  code?: boolean;
}

export interface PublicToolResultView {
  toolId: string;
  toolLabel: string;
  operation: string;
  summary: string;
  fields: PublicToolResultField[];
  request: PublicToolRequestField[];
  output?: {
    text: string;
    truncated: boolean;
    kind: 'code' | 'diff' | 'search' | 'terminal' | 'text';
    title: string;
    channels?: Array<{
      id: 'stdout' | 'stderr';
      label: string;
      text: string;
      truncated: boolean;
    }>;
  };
  artifacts: UiAgentBlock[];
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

export function publicToolLabel(toolId: string): string {
  return publicToolName(toolId);
}

const toolDestinations: Record<string, { href: string; label: string }> = {
  overview: { href: '#/overview', label: '打开当前状态' },
  input: { href: '#/input', label: '打开输入法与词库' },
  voice: { href: '#/voice', label: '打开语音输入' },
  planning: { href: '#/planning', label: '打开任务' },
  memory: { href: '#/memory', label: '打开我的记忆' },
  agent_role_book: { href: '#/memory?layer=role-books', label: '打开伙伴记忆' },
  knowledge: { href: '#/knowledge', label: '打开知识库' },
  models: { href: '#/configuration', label: '打开模型与连接' },
  runtime: { href: '#/diagnostics', label: '打开运行检查' },
  configuration: { href: '#/configuration', label: '打开设置' },
  agents: { href: '#/rooms', label: '打开多人协作' },
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
  symbols: '查找符号',
  hover: '查看悬浮信息',
  definition: '定位定义',
  references: '查找引用',
  diagnostics: '查看诊断',
  rename: '预览重命名',
  code_action_apply: '预览代码动作',
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

export function publicToolResultView(activity: PublicToolActivityProjection): PublicToolResultView {
  const payload = activity.payload;
  const carrier = record(payload.result ?? payload.partialResult);
  const carrierDetails = record(carrier.details);
  const envelope = Object.keys(carrierDetails).length > 0 ? carrierDetails : carrier;
  const envelopeResult = record(envelope.result);
  const carrierResult = record(carrier.result);
  const domain = Object.keys(envelopeResult).length > 0 ? envelopeResult : carrierResult;
  const publicResult = record(payload.publicResult);
  const publicArguments = record(payload.args);
  const layers = [domain, envelope, carrier, publicResult, publicArguments, payload];
  const toolId = canonicalToolId(firstText(
    [payload, envelope, carrier],
    ['toolId', 'toolName', 'tool'],
  ));
  const toolLabel = publicToolLabel(toolId);
  const expectedNoop = payload.expectedNoop === true;
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
    const operationLabel = toolId === 'todo'
      ? ({ init: '建立 Todo', start: '开始任务', done: '完成任务', drop: '放弃任务', append: '追加任务', view: '查看 Todo', rm: '移除 Todo' } as Record<string, string>)[operation]
      : operationLabels[operation];
    append('operation', '操作', operationLabel ?? '受控操作');
  }

  const ok = firstBoolean([envelope, domain, carrier], ['ok']);
  if (!expectedNoop && ok !== undefined) append('ok', '执行结果', ok ? '成功' : '未成功');

  const resultStatus = publicStatusLabel(firstText(layers, ['status', 'state', 'availability']));
  if (resultStatus) append('resultStatus', '服务状态', resultStatus);

  const summary = firstPublicText(layers, ['summary', 'message', 'label']);
  if (summary) append('summary', activity.kind === 'tool_progress' ? '当前进度' : '结果摘要', summary);
  const approvalDecision = approvalDecisionView(payload);
  if (approvalDecision.mode) {
    append(
      'approvalDecisionMode',
      '审批方式',
      approvalDecision.mode === 'model'
        ? 'Luna Max 独立判定'
        : approvalDecision.mode === 'policy'
          ? '安全策略自动处理'
          : '人工确认',
    );
    if (approvalDecision.model) {
      append(
        'approvalModel',
        '审批模型',
        /(?:^|[./_-])luna(?:$|[./_-])/i.test(approvalDecision.model)
          ? 'Luna Max'
          : approvalDecision.model,
      );
    }
    if (approvalDecision.decision) {
      append(
        'approvalDecision',
        '审批结论',
        approvalDecision.decision === 'approve' ? '批准' : '拒绝',
      );
    }
    if (approvalDecision.status === 'failed_closed') {
      append(
        'approvalDecisionStatus',
        '审批状态',
        '无法形成可验证裁决，已按拒绝处理',
      );
    }
    if (approvalDecision.rationaleSummary) {
      append(
        'approvalRationale',
        '裁决说明',
        approvalDecision.rationaleSummary,
      );
    }
    if (approvalDecision.reasonCodes.length) {
      append(
        'approvalReasonCodes',
        '判定依据',
        boundedList(
          approvalDecision.reasonCodes.map(approvalDecisionReasonLabel),
          8,
        ),
      );
    }
    if (approvalDecision.receiptId) {
      append('approvalDecisionReceiptId', '决策回执', approvalDecision.receiptId);
    }
  }

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
    append('items', toolId === 'knowledge' ? '引用数量' : '近期活动', `${items.length} 条`);
  }
  const sourceCounts = safeActivitySourceCounts(items);
  if (sourceCounts) append('activitySources', '活动来源', sourceCounts);

  const writePolicy = firstPublicText(layers, ['writePolicy', 'safety']);
  if (writePolicy) append('writePolicy', '写入保护', writePolicy);

  const codeResult = publicCodeToolResult(toolId, record(payload.args), publicResult, envelope, carrier);
  const codeSummary = publicCodeActivitySummary(toolId, activity.status, codeResult);
  const activitySummary = codeSummary && (!summary || summary === codeResult.summary)
    ? codeSummary
    : summary;
  if (codeResult.file) append('file', '文件', codeResult.file);
  if (codeResult.lines !== undefined) append('lineCount', '行数', `${codeResult.lines} 行`);
  if (codeResult.additions !== undefined || codeResult.deletions !== undefined) {
    append('changes', '变更', `+${codeResult.additions ?? 0} -${codeResult.deletions ?? 0}`);
  }
  if (toolId === 'bash' && codeResult.exitCode !== undefined) {
    append('exitCode', '退出码', String(codeResult.exitCode));
  }

  const sources = toolId === 'knowledge'
    ? safeKnowledgeSourceLabels(items)
    : safeSourceLabels(payload.sources ?? payload.documents ?? payload.books);
  const preview = semanticToolPreview(toolId, operation, layers);
  const error = !expectedNoop && (activity.status === 'failed' || payload.isError === true)
    ? publicToolError(layers, carrier)
    : '';
  const recovery = error ? publicToolRecovery(error, payload) : undefined;
  const artifacts = publicToolArtifactBlocks(payload);

  return {
    toolId,
    toolLabel,
    operation,
    summary: activitySummary || codeResult.summary || `${toolLabel} ${activity.status === 'running' ? '正在处理' : activity.status === 'failed' ? '执行失败' : activity.status === 'aborted' ? '已停止' : '已完成'}`,
    fields,
    request: codeResult.request,
    ...(codeResult.output ? { output: codeResult.output } : {}),
    artifacts,
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
  const roomPreview = roomToolPreview(toolId, layers);
  if (roomPreview) return roomPreview;
  if (toolId === 'agent_role_book') return roleBookToolPreview(operation, layers);
  if (toolId !== 'memory') return undefined;

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

function roomToolPreview(
  toolId: string,
  layers: Record<string, unknown>[],
): PublicToolSemanticPreview | undefined {
  if (toolId === 'room_state') {
    const current = firstRecord(layers, ['currentResponsibility']);
    const objective = publicLongText(current.objective);
    const expectedOutput = publicLongText(current.expectedOutput);
    const state = publicStatusLabel(text(current.state));
    const acceptance = firstArray(layers, ['acceptanceAliases'])
      .map(record)
      .filter((item) => publicLongText(item.statement));
    const participants = firstArray(layers, ['participants'])
      .map(record)
      .filter((item) => publicDisplayText(item.displayName, ''));
    const changes = firstArray(layers, ['recentPublicChanges'])
      .map(record)
      .filter((item) => publicLongText(item.content));
    const integrations = firstArray(layers, ['pendingIntegrations'])
      .map(record)
      .filter((item) => publicLongText(item.objective));
    if (!objective && !expectedOutput && !acceptance.length && !participants.length && !changes.length && !integrations.length) {
      return undefined;
    }
    const verified = acceptance.filter((item) => item.verified === true).length;
    const canSettle = firstBoolean(layers, ['canSettle']);
    const items: PublicToolSemanticPreview['items'] = [];
    if (expectedOutput) {
      items.push({ id: 'room:expected-output', label: '要交付', text: expectedOutput });
    }
    acceptance.slice(0, 6).forEach((item, index) => items.push({
      id: `room:acceptance:${index}`,
      label: item.verified === true ? '已验证' : '待验证',
      text: publicLongText(item.statement),
    }));
    participants.slice(0, 6).forEach((item, index) => {
      const name = publicDisplayText(item.displayName, '协作伙伴');
      const capability = publicLongText(item.capabilitySummary);
      const availability = roomAvailabilityLabel(text(item.availability));
      items.push({
        id: `room:participant:${index}`,
        label: availability,
        text: capability ? `${name} · ${capability}` : name,
      });
    });
    changes.slice(0, 4).forEach((item, index) => items.push({
      id: `room:change:${index}`,
      label: '最近进展',
      text: publicLongText(item.content),
    }));
    integrations.slice(0, 4).forEach((item, index) => items.push({
      id: `room:integration:${index}`,
      label: '等待集成',
      text: publicLongText(item.objective),
    }));
    return {
      kind: 'timeline',
      title: '当前协作状态',
      ...(objective ? { description: objective } : {}),
      badges: [
        ...(state ? [state] : []),
        ...(acceptance.length ? [`已验证 ${verified}/${acceptance.length}`] : []),
        ...(integrations.length ? [`${integrations.length} 项等待集成`] : []),
        ...(canSettle === true ? ['可以收束结果'] : []),
      ],
      items: items.slice(0, 16),
    };
  }
  if (toolId === 'room_commit') {
    const decision = text(firstText(layers, ['decision'])).toLowerCase();
    const publicSummary = firstPublicText(layers, ['publicSummary', 'summary']);
    const question = firstPublicText(layers, ['question']);
    const questionOptions = firstArray(layers, ['questionOptions']).map(record);
    const items: PublicToolSemanticPreview['items'] = [];
    if (publicSummary) items.push({ id: 'room:commit:summary', label: '公开说明', text: publicSummary });
    if (question) items.push({ id: 'room:commit:question', label: '等待回答', text: question });
    questionOptions.slice(0, 5).forEach((option, index) => {
      const label = publicDisplayText(option.label, `选项 ${index + 1}`);
      const description = publicLongText(option.description);
      if (!description) return;
      items.push({
        id: `room:commit:option:${index}`,
        label: option.recommended === true ? '推荐选项' : '可选答案',
        text: `${label} · ${description}`,
      });
    });
    if (!items.length) return undefined;
    return {
      kind: 'timeline',
      title: decision === 'wait' ? '等待用户回答后继续' : '已提交这一步的结果',
      badges: [],
      items,
    };
  }
  if (toolId === 'room_collaborate') {
    const objective = firstPublicText(layers, ['objective']);
    const expectedOutput = firstPublicText(layers, ['expectedOutput']);
    if (!objective && !expectedOutput) return undefined;
    return {
      kind: 'timeline',
      title: '已安排并行工作',
      ...(objective ? { description: objective } : {}),
      badges: [],
      items: expectedOutput
        ? [{ id: 'room:collaborate:output', label: '等待交付', text: expectedOutput }]
        : [],
    };
  }
  return undefined;
}

function roomAvailabilityLabel(value: string): string {
  return ({
    current: '当前负责',
    busy: '正在工作',
    available: '可以加入',
  } as Record<string, string>)[value.toLowerCase()] ?? '协作伙伴';
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
  request: PublicToolRequestField[];
  output?: {
    text: string;
    truncated: boolean;
    kind: 'code' | 'diff' | 'search' | 'terminal' | 'text';
    title: string;
    channels?: Array<{
      id: 'stdout' | 'stderr';
      label: string;
      text: string;
      truncated: boolean;
    }>;
  };
  lines?: number;
  additions?: number;
  deletions?: number;
  exitCode?: number;
}

function publicCodeActivitySummary(
  toolId: string,
  status: PublicToolActivityProjection['status'],
  result: PublicCodeToolResult,
): string {
  if (!result.summary) return '';
  const running = status === 'running';
  const completed = status === 'completed';
  if (!running && !completed) return result.summary;
  if (toolId === 'edit') {
    return `${running ? '正在编辑' : '已编辑'} ${result.summary}`;
  }
  if (toolId === 'write') {
    return `${running ? '正在写入' : '已写入'} ${result.summary.replace(/\s已写入$/u, '')}`;
  }
  if (toolId === 'read') {
    return `${running ? '正在读取' : '已读取'} ${result.summary.replace(/\s已读取$/u, '')}`;
  }
  if (toolId === 'grep') {
    const searchMatch = /^在\s+(.+?)\s+中搜索\s+(.+)$/u.exec(result.summary);
    if (searchMatch) {
      const [, location, query] = searchMatch;
      return running
        ? `正在搜索 ${location} 中的 ${query}`
        : `已在 ${location} 中搜索 ${query}`;
    }
    return `${running ? '正在' : '已'}${result.summary}`;
  }
  if (['find', 'ls'].includes(toolId)) {
    return `${running ? '正在' : '已'}${result.summary}`;
  }
  if (toolId === 'bash') {
    return `${running ? '正在' : '已'}${result.summary}`;
  }
  return result.summary;
}

function publicCodeToolResult(
  toolId: string,
  args: Record<string, unknown>,
  publicResult: Record<string, unknown>,
  envelope: Record<string, unknown>,
  carrier: Record<string, unknown>,
): PublicCodeToolResult {
  const fileTools = new Set([
    'read', 'write', 'edit',
  ]);
  const searchTools = new Set(['grep']);
  const listTools = new Set(['find', 'ls']);
  const commandTools = new Set(['bash']);
  const codeTools = new Set([...fileTools, ...searchTools, ...listTools, ...commandTools]);
  // Session events normally carry the sanitized result in `publicResult`,
  // while Room history may persist the same public fields in its bounded
  // `result` carrier. Read both shapes through one precedence-ordered view so
  // the two surfaces do not invent separate Tool contracts.
  const resultLayers = [publicResult, envelope, carrier];
  const rawOutputText = firstText(resultLayers, ['outputPreview']);
  const stdoutText = publicToolOutputText(firstText(resultLayers, ['stdoutPreview']));
  const stderrText = publicToolOutputText(firstText(resultLayers, ['stderrPreview']));
  const commandChannels = commandTools.has(toolId)
    ? [
        ...(stdoutText ? [{
          id: 'stdout' as const,
          label: '标准输出',
          text: stdoutText,
          truncated: firstBoolean(resultLayers, ['stdoutTruncated']) === true,
        }] : []),
        ...(stderrText ? [{
          id: 'stderr' as const,
          label: '标准错误',
          text: stderrText,
          truncated: firstBoolean(resultLayers, ['stderrTruncated']) === true,
        }] : []),
      ]
    : [];
  const managedEvidence = managedEvidencePreview(rawOutputText);
  const requestLayers = [
    publicResult,
    managedEvidence?.request ?? {},
    args,
    envelope,
    carrier,
  ];
  const rawPath = firstText(requestLayers, ['relativePath', 'fileName', 'file_path', 'path']);
  const file = codeTools.has(toolId) ? publicWorkspacePath(rawPath) : '';
  const request: PublicToolRequestField[] = [];
  const addRequest = (id: string, label: string, value: string, code = false) => {
    if (!value || request.some((field) => field.id === id)) return;
    request.push({ id, label, value, ...(code ? { code: true } : {}) });
  };
  if (file) addRequest('path', '目标', file, true);

  const operation = firstText(requestLayers, ['op']);
  const mode = firstText(requestLayers, ['mode']);
  const patternKind = firstText(requestLayers, ['patternKind']);
  const query = firstText(requestLayers, ['query']);
  const pattern = firstText(requestLayers, ['pattern']);
  const glob = firstText(requestLayers, ['glob']);
  const command = firstText(requestLayers, ['command']);
  const protectedCommand = commandTools.has(toolId) && commandReferencesSensitiveFile(command);
  if (operation) addRequest('op', '动作', operation, true);
  if (query) addRequest('query', '查询', query, true);
  if (pattern) addRequest('pattern', '模式', pattern, true);
  if (glob) addRequest('glob', '文件范围', glob, true);
  if (mode) addRequest('mode', '搜索方式', mode, true);
  if (patternKind) addRequest('patternKind', '模式类型', patternKind, true);
  if (command) {
    addRequest(
      'command',
      '命令',
      protectedCommand ? '已运行受保护命令' : command,
      true,
    );
  }
  for (const [key, label] of [
    ['offset', '起始行'],
    ['limit', '上限'],
    ['context', '上下文行'],
    ['timeout', '超时'],
  ] as const) {
    const value = firstFiniteNumber(requestLayers, [key]);
    if (value !== undefined) {
      addRequest(key, label, key === 'timeout' ? `${value} 秒` : String(value), true);
    }
  }

  const outputText = protectedCommand
    ? ''
    : managedEvidence?.summary
      || publicToolOutputText(rawOutputText)
      || commandChannels.map((channel) => channel.text).join('\n');
  const output = outputText
    ? {
        text: outputText,
        truncated: managedEvidence?.truncated
          ?? (
            firstBoolean(resultLayers, ['outputTruncated']) === true
            || publicToolOutputWasTruncated(rawOutputText)
          ),
        ...publicCodeOutputPresentation(toolId, file),
        ...(commandChannels.length ? { channels: commandChannels } : {}),
      }
    : undefined;

  if (toolId === 'write') {
    const lines = firstFiniteNumber(resultLayers, ['lineCount']) ?? publicLineCount(text(args.content));
    const additions = firstFiniteNumber(resultLayers, ['additions']) ?? lines;
    return {
      file,
      request,
      ...(lines !== undefined ? { lines } : {}),
      ...(additions !== undefined ? { additions } : {}),
      summary: file ? `${file}${lines !== undefined ? ` +${lines}` : ' 已写入'}` : '文件已写入',
    };
  }
  if (toolId === 'edit') {
    const diff = firstText(resultLayers, ['diff', 'patch']) || rawOutputText;
    const publicDiff = publicToolOutputText(diff);
    const diffOutput = publicDiff
      ? {
          text: publicDiff,
          truncated: publicToolOutputWasTruncated(diff),
          kind: 'diff' as const,
          title: file || '代码变更',
        }
      : output;
    const additions = firstFiniteNumber(resultLayers, ['additions']);
    const deletions = firstFiniteNumber(resultLayers, ['deletions']);
    const changes = additions !== undefined || deletions !== undefined
      ? { additions, deletions }
      : publicDiffCounts(diff);
    const changeLabel = changes.additions !== undefined || changes.deletions !== undefined
      ? ` +${changes.additions ?? 0} -${changes.deletions ?? 0}`
      : ' 已更新';
    return {
      file,
      request,
      ...(diffOutput ? { output: diffOutput } : {}),
      summary: file ? `${file}${changeLabel}` : '文件已更新',
      ...changes,
    };
  }
  if (toolId === 'read') {
    const truncation = firstRecord(resultLayers, ['truncation']);
    const totalLines = firstFiniteNumber([truncation], ['totalLines']);
    const lines = totalLines ?? publicLineCount(publicToolContentText(carrier));
    return {
      file,
      request,
      ...(output ? { output } : {}),
      ...(lines !== undefined ? { lines } : {}),
      summary: file ? `${file}${lines !== undefined ? ` · ${lines} 行` : ' 已读取'}` : '文件已读取',
    };
  }
  if (searchTools.has(toolId)) {
    const needle = pattern || query;
    return {
      file,
      request,
      ...(output ? { output } : {}),
      summary: needle
        ? `在 ${file || '工作区'} 中搜索 “${needle.slice(0, 100)}”`
        : '搜索项目内容',
    };
  }
  if (listTools.has(toolId)) {
    const needle = pattern || query;
    return {
      file,
      request,
      ...(output ? { output } : {}),
      summary: toolId === 'ls'
        ? `列出 ${file || '工作区'}`
        : needle
          ? `查找 “${needle.slice(0, 100)}”`
          : '查找项目文件',
    };
  }
  if (commandTools.has(toolId)) {
    const firstLine = protectedCommand
      ? '受保护命令'
      : command.split('\n', 1)[0]?.slice(0, 140) ?? '';
    const exitCode = firstFiniteNumber(resultLayers, ['exitCode']);
    return {
      file,
      request,
      ...(output ? { output } : {}),
      ...(exitCode !== undefined ? { exitCode } : {}),
      summary: firstLine ? `运行 ${firstLine}` : '运行项目命令',
    };
  }
  return { file: '', request: [], summary: '' };
}

function publicCodeOutputPresentation(
  toolId: string,
  file: string,
): Pick<NonNullable<PublicCodeToolResult['output']>, 'kind' | 'title'> {
  if (toolId === 'edit') {
    return { kind: 'diff', title: file || '代码变更' };
  }
  if (toolId === 'read') {
    return { kind: 'code', title: file || '文件内容' };
  }
  if (['grep', 'find', 'ls'].includes(toolId)) {
    return { kind: 'search', title: toolId === 'ls' ? '文件列表' : '搜索结果' };
  }
  if (toolId === 'bash') {
    return { kind: 'terminal', title: '命令输出' };
  }
  return { kind: 'text', title: '返回片段' };
}

function publicToolArtifactBlocks(payload: Record<string, unknown>): UiAgentBlock[] {
  const values = Array.isArray(payload.agentBlocks) ? payload.agentBlocks : [];
  return values.flatMap((value) => {
    const raw = record(value);
    if (!text(raw.id) || !['file', 'diff'].includes(text(raw.type)) || Object.keys(record(raw.data)).length === 0) {
      return [];
    }
    return [normalizeAgentBlock(raw)];
  });
}

function commandReferencesSensitiveFile(value: string): boolean {
  if (!value) return false;
  const fixedBasenames = new Set([
    'credentials', 'id_rsa', 'id_ed25519', '.npmrc', '.pypirc', '.netrc',
  ]);
  return value
    .split(/[\s"'`|;&<>()]+/u)
    .flatMap((token) => token.split('='))
    .some((part) => {
      const candidate = part.replace(/^[\[\]{}:,$]+|[\[\]{}:,$]+$/gu, '');
      if (!candidate) return false;
      const basename = candidate
        .replace(/\\/gu, '/')
        .replace(/\/+$/gu, '')
        .split('/')
        .at(-1)
        ?.toLocaleLowerCase('en-US') ?? '';
      const looksLikeFile = candidate.includes('/')
        || basename.includes('.')
        || fixedBasenames.has(basename);
      if (!looksLikeFile) return false;
      return basename.startsWith('.env')
        || fixedBasenames.has(basename)
        || /(?:^|[._-])(?:auth|credentials?|secrets?|tokens?|passwords?|cookies?|api[_-]?keys?|authorization)(?:$|[._-])/iu.test(basename)
        || /\.(?:pem|key|p12|pfx)$/iu.test(basename);
    });
}

function managedEvidencePreview(value: string): {
  request: Record<string, unknown>;
  summary: string;
  truncated: boolean;
} | undefined {
  const normalized = value.trim();
  if (!normalized.startsWith('{') || !normalized.includes('"evidenceHandle"')) return undefined;
  let envelope: Record<string, unknown>;
  try {
    envelope = record(JSON.parse(normalized));
  } catch {
    // Older durable events may contain a generic preview truncated in the
    // middle of the evidence JSON. Never expose that internal envelope; the
    // backend will rebuild a semantic receipt after the next snapshot.
    return {
      request: {},
      summary: '受管工具结果已安全保存；刷新对话后可查看语义摘要。',
      truncated: true,
    };
  }
  if (!text(envelope.evidenceHandle)) return undefined;
  const rawSummary = text(envelope.evidenceSummary ?? envelope.previewHead);
  const summary = publicToolOutputText(rawSummary)
    || '受管工具结果已安全保存。';
  const evidenceBytes = finiteNumber(envelope.evidenceBytes) ?? 0;
  return {
    request: record(envelope.evidenceRequest),
    summary,
    truncated: (
      rawSummary.length > summary.length
      || evidenceBytes > rawSummary.length
      || Boolean(envelope.continuation)
    ),
  };
}

function publicToolOutputText(value: string): string {
  const redacted = value
    .replace(/\r\n?/gu, '\n')
    .replace(/\bsk-[A-Za-z0-9_-]{6,}\b/gu, '[REDACTED_SECRET]')
    .replace(
      /(^|[^A-Za-z0-9_-])(["']?)([A-Za-z0-9_-]*(?:api[_-]?key|access[_-]?token|password|secret|authorization|token|cookie|bearer))\2(\s*(?:=|:)\s*)(?:(?:Bearer|Basic|Token)\s+)?("[^"\r\n]*"|'[^'\r\n]*'|[^\s'"&,}]+)/gimu,
      '$1$2$3$2$4[REDACTED_SECRET]',
    )
    .replace(/(--(?:api[_-]?key|token|password|secret)\s+)([^\s;'"\\]+|"[^"]*"|'[^']*')/giu, '$1[REDACTED_SECRET]')
    .replace(/\/Users\/[^/\s]+\//gu, '~/')
    .replace(/\/Volumes\/[^/]+\//gu, '/…/')
    .replace(/\/private\/var\//gu, '/…/var/')
    .replace(/\/var\/folders\//gu, '/…/var/folders/');
  return redacted
    .split('\n')
    .slice(0, PUBLIC_TOOL_OUTPUT_MAX_LINES)
    .join('\n')
    .slice(0, PUBLIC_TOOL_OUTPUT_MAX_CHARS)
    .trim();
}

function publicToolOutputWasTruncated(value: string): boolean {
  const normalized = value.replace(/\r\n?/gu, '\n').trim();
  return (
    normalized.length > PUBLIC_TOOL_OUTPUT_MAX_CHARS
    || normalized.split('\n').length > PUBLIC_TOOL_OUTPUT_MAX_LINES
  );
}

function publicWorkspacePath(value: string): string {
  const normalized = value.replace(/\\/gu, '/').replace(/\/{2,}/gu, '/').trim();
  if (!normalized || normalized.length > 1_000) return '';
  if (/(?:api.?key|authorization|cookie|password|secret|bearer\s)/iu.test(normalized)) return '';
  const parts = normalized.split('/').filter(Boolean);
  if (parts.length === 0) return '';
  const absolute = normalized.startsWith('/') || normalized.startsWith('~/') || /^[a-z]:\//iu.test(normalized);
  const unsafeRelative = parts.some((part) => part === '..' || part === '.');
  const serverRedacted = normalized.startsWith('…/');
  const clientRedacted = normalized.includes('[REDACTED_PATH]');
  const candidate = serverRedacted
    ? normalized
    : absolute || unsafeRelative || clientRedacted
      ? parts.at(-1) ?? ''
      : parts.join('/');
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
  if (approvalNeedsHumanDecision(payload) && text(payload.approvalId) && text(payload.payloadSha256)) return 'approval';
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
  return publicToolName(id, publicText(item.displayName ?? item.label));
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

function activityStatusLabel(status: PublicToolActivityProjection['status']): string {
  switch (status) {
    case 'running': return '进行中';
    case 'waiting': return '等待确认';
    case 'failed': return '失败';
    case 'aborted': return '已停止';
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
