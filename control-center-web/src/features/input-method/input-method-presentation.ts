import type { LucideIcon } from 'lucide-react';
import {
  booleanValue,
  configuredLabel,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';

export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';
export type DraftValue = string | number | boolean;
export type InputMode = '安全模式' | '标准模式' | '记忆增强' | '调试模式';

export const presetInputModes: readonly InputMode[] = ['安全模式', '标准模式', '记忆增强', '调试模式'];

/* 每种使用方式只等于它真实写入的键值。卡片事实、差异列表和保存请求都
 * 从这一份数据派生，宣传语没有独立生存空间。
 *
 * 标准 与 记忆增强 曾经共用同一份变更（选“记忆增强”保存后仍推断为标准
 * 模式），是一个说谎的死选项。两个模式通过真实的 memory.recall 键区分：
 * 标准保持紧凑召回，记忆增强启用详尽召回与按需时间线。 */
export const inputModeChanges: Record<InputMode, Record<string, DraftValue>> = {
  安全模式: {
    'interaction.postCommit.enabled': false,
    'memory.enabled': false,
    'activeRag.allowRemoteModel': false,
  },
  标准模式: {
    'interaction.postCommit.enabled': true,
    'memory.enabled': true,
    'rag.lanes.tagMemo': true,
    'rag.lanes.timeDailyBook': true,
    'memory.recall.detailLevel': 'compact',
  },
  记忆增强: {
    'interaction.postCommit.enabled': true,
    'memory.enabled': true,
    'rag.lanes.tagMemo': true,
    'rag.lanes.timeDailyBook': true,
    'memory.recall.detailLevel': 'detailed',
    'memory.recall.timelineEnabled': true,
  },
  调试模式: {
    'interaction.postCommit.enabled': true,
    'diagnostics.liveTrace': true,
    'diagnostics.candidateExplain': true,
    'display.showDiagnosticsInline': true,
  },
};

/* 标准 与 记忆增强 的真实分界键，机械求差而不是手写清单。 */
const memorySplitKeys = new Set(
  [...new Set([
    ...Object.keys(inputModeChanges.标准模式),
    ...Object.keys(inputModeChanges.记忆增强),
  ])].filter((key) => !Object.is(inputModeChanges.标准模式[key], inputModeChanges.记忆增强[key])),
);

export type ModeFactChip = {
  key: string;
  label: string;
  /** 这条事实关闭了某项能力，视觉上降权。 */
  off: boolean;
  /** 这条事实是 标准/记忆增强 之间的真实差异，视觉上强调。 */
  highlight: boolean;
};

const modeFactLabels: Record<string, string> = {
  'interaction.postCommit.enabled=true': '本机联想',
  'interaction.postCommit.enabled=false': '联想关闭',
  'memory.enabled=true': '记忆召回',
  'memory.enabled=false': '记忆关闭',
  'activeRag.allowRemoteModel=false': '远程生成关闭',
  'rag.lanes.tagMemo=true': '标签记忆',
  'rag.lanes.timeDailyBook=true': '时间与日记',
  'memory.recall.detailLevel=compact': '紧凑召回',
  'memory.recall.detailLevel=detailed': '详尽召回',
  'memory.recall.timelineEnabled=true': '按需时间线',
  'diagnostics.liveTrace=true': '实时诊断',
  'diagnostics.candidateExplain=true': '候选解释',
  'display.showDiagnosticsInline=true': '行内诊断',
};

/** 模式卡片上的事实签名：逐键翻译真实写入，一键一枚，不可多也不可少。 */
export function modeFactChips(mode: InputMode): readonly ModeFactChip[] {
  return Object.entries(inputModeChanges[mode]).map(([key, value]) => ({
    key,
    label: modeFactLabels[`${key}=${String(value)}`]
      ?? `${modeSettingLabel(key)}：${formatSetting(value, key)}`,
    off: value === false,
    highlight: memorySplitKeys.has(key) && (mode === '标准模式' || mode === '记忆增强'),
  }));
}

export function componentStatus(
  status: Record<string, unknown>,
  label: string,
  icon: LucideIcon,
  pending: boolean,
  error: Error | null,
): {
  detail: string;
  icon: LucideIcon;
  label: string;
  tone: StatusTone;
  value: string;
} {
  if (pending) return { detail: '等待运行概览返回', icon, label, tone: 'neutral', value: '正在读取' };
  if (error) return { detail: '运行概览暂时不可用', icon, label, tone: 'danger', value: '读取失败' };
  if (!Object.keys(status).length) return { detail: '暂未收到这项状态', icon, label, tone: 'warning', value: '未报告' };
  const state = stringValue(status.status);
  const ready = booleanValue(status.ok) && state !== 'degraded';
  return {
    detail: publicInputText(stringValue(status.detail), '暂时没有更多状态说明'),
    icon,
    label,
    tone: ready ? 'success' : state === 'degraded' ? 'warning' : 'danger',
    value: ready ? '就绪' : state === 'degraded' ? '降级' : '需检查',
  };
}

/* ---------------------------------------------------------------------------
 * 生成阶段（上屏后的智能候选）
 *
 * 三步车道与候选面板示意都只从真实设置和真实运行状态派生；这里绝不
 * 编造候选正文或运行结果。示意图是"当前配置长什么样"，不是运行证据。
 * ------------------------------------------------------------------------- */

export type SuggestionPanel = {
  /** 上屏后是否生成智能候选；只有明确写为 false 才算关闭。 */
  enabled: boolean;
  /** 真实配置的候选数量；配置缺失或超界时为 0（示意用抽象槽位）。 */
  candidateCount: number;
  /** 候选界面：紧凑单行或展开列表。 */
  expanded: boolean;
  /** 已配置的采纳方式与停留时长，逐条可扫读。 */
  hints: readonly string[];
};

export function suggestionPanel(settings: Record<string, unknown>): SuggestionPanel {
  const enabled = valueAt(settings, 'interaction.postCommit.enabled') !== false;
  const rawCount = valueAt(settings, 'display.maxPostCommitCandidates');
  const candidateCount = typeof rawCount === 'number' && Number.isInteger(rawCount) && rawCount >= 1 && rawCount <= 8
    ? rawCount
    : 0;
  const hints: string[] = [];
  const tabAction = stringValue(valueAt(settings, 'interaction.postCommit.tabAction'));
  if (tabAction === 'accept_top_prediction') hints.push('Tab 采纳第 1 条');
  if (tabAction === 'rime_default') hints.push('Tab 保留给输入法');
  const optionNumber = stringValue(valueAt(settings, 'interaction.postCommit.optionNumber'));
  if (optionNumber === 'select_prediction_by_ordinal' || optionNumber === 'select_prediction') {
    hints.push('Option+数字 选对应候选');
  }
  const ttl = valueAt(settings, 'interaction.postCommit.panelTtlMs');
  if (typeof ttl === 'number' && Number.isFinite(ttl) && ttl > 0) {
    hints.push(`约 ${secondsLabel(ttl)}后自动收起`);
  }
  return {
    enabled,
    candidateCount,
    expanded: stringValue(valueAt(settings, 'display.panelStyle')) === 'expanded',
    hints: enabled ? hints : [],
  };
}

export type GenerationLaneFacts = {
  /** 车道是否参与本次生成；召回与联想由设置决定。 */
  enabled: boolean;
  /** 一句话说明这一步做什么（人话，不出现实现字段）。 */
  summary: string;
  /** 可扫读的事实项，全部来自真实设置。 */
  facts: readonly string[];
};

export function contextLaneFacts(settings: Record<string, unknown>): GenerationLaneFacts {
  const facts: string[] = [];
  const baseline = valueAt(settings, 'context.recentInputBaseline');
  if (typeof baseline === 'number' && Number.isInteger(baseline) && baseline > 0) {
    facts.push(`最近 ${baseline} 段输入作基线`);
  }
  if (valueAt(settings, 'context.temporalRecall') === true) {
    facts.push('理解"昨天 / 上周"这类时间说法');
  }
  return {
    enabled: true,
    summary: '读取光标附近的文本，让候选贴合正在写的内容。',
    facts,
  };
}

export function recallLaneFacts(settings: Record<string, unknown>): GenerationLaneFacts {
  const enabled = valueAt(settings, 'memory.enabled') === true;
  if (!enabled) {
    return {
      enabled,
      summary: '不查找个人记忆，候选只依据眼前的上下文。',
      facts: [],
    };
  }
  const facts: string[] = [];
  if (valueAt(settings, 'rag.lanes.tagMemo') === true) facts.push('标签记忆');
  if (valueAt(settings, 'rag.lanes.timeDailyBook') === true) facts.push('时间与日记');
  const detail = stringValue(valueAt(settings, 'memory.recall.detailLevel'));
  if (detail) facts.push(`${inputOptionLabel(detail)}召回`);
  if (valueAt(settings, 'memory.recall.timelineEnabled') === true) facts.push('按需展开时间线');
  return {
    enabled,
    summary: '从你的记录里找相关内容，作为联想的依据。',
    facts,
  };
}

export function completionLaneFacts(
  settings: Record<string, unknown>,
  modelLabel: string,
): GenerationLaneFacts {
  const enabled = valueAt(settings, 'interaction.postCommit.enabled') !== false;
  if (!enabled) {
    return {
      enabled,
      summary: '上屏后不再生成智能候选，输入完全交回系统输入法。',
      facts: [],
    };
  }
  const facts: string[] = [];
  if (modelLabel) facts.push(modelLabel);
  const count = valueAt(settings, 'display.maxPostCommitCandidates');
  if (typeof count === 'number' && Number.isInteger(count) && count > 0) {
    facts.push(`每次最多 ${count} 条`);
  }
  const idle = valueAt(settings, 'interaction.postCommit.idleTriggerMs');
  if (typeof idle === 'number' && Number.isFinite(idle) && idle > 0) {
    facts.push(`停顿 ${secondsLabel(idle)}后生成`);
  }
  return {
    enabled,
    summary: '本机模型结合上下文与召回结果，续写出候选。',
    facts,
  };
}

export function secondsLabel(milliseconds: number): string {
  const seconds = milliseconds / 1000;
  const rounded = Math.round(seconds * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded} 秒`;
}

export function inferInputMode(settings: Record<string, unknown>): InputMode | '' {
  if (
    valueAt(settings, 'diagnostics.liveTrace') === true
    && valueAt(settings, 'diagnostics.candidateExplain') === true
    && valueAt(settings, 'display.showDiagnosticsInline') === true
  ) return '调试模式';
  if (
    valueAt(settings, 'interaction.postCommit.enabled') === false
    && valueAt(settings, 'memory.enabled') === false
    && valueAt(settings, 'activeRag.allowRemoteModel') === false
  ) return '安全模式';
  if (
    valueAt(settings, 'interaction.postCommit.enabled') === true
    && valueAt(settings, 'memory.enabled') === true
    && valueAt(settings, 'rag.lanes.tagMemo') === true
    && valueAt(settings, 'rag.lanes.timeDailyBook') === true
  ) {
    // 记忆增强与标准模式共享基础键；真实区分是详尽召回加按需时间线。
    // 只开详尽召回而关掉时间线不属于任何预设，如实返回自定义。
    const recallDetail = valueAt(settings, 'memory.recall.detailLevel');
    if (recallDetail === 'detailed') {
      return valueAt(settings, 'memory.recall.timelineEnabled') === true ? '记忆增强' : '';
    }
    // balanced 是手动调出的中间档，不冒充任何预设。
    if (recallDetail === 'balanced') return '';
    return '标准模式';
  }
  return '';
}

export function modeSettingLabel(key: string): string {
  return ({
    'interaction.postCommit.enabled': '上屏后联想',
    'memory.enabled': '记忆召回',
    'activeRag.allowRemoteModel': '远程生成',
    'rag.lanes.tagMemo': '标签记忆召回',
    'rag.lanes.timeDailyBook': '时间与日记召回',
    'memory.recall.detailLevel': '召回详细程度',
    'memory.recall.timelineEnabled': '按需召回时间线',
    'diagnostics.liveTrace': '实时诊断',
    'diagnostics.candidateExplain': '候选解释',
    'display.showDiagnosticsInline': '候选行内诊断',
  } as Record<string, string>)[key] ?? '运行设置';
}

export function formatSetting(value: unknown, key: string): string {
  if (/token|secret|password|api.?key|authorization|cookie/i.test(key)) return configuredLabel(value);
  if (typeof value === 'boolean') return value ? '已启用' : '已关闭';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return inputOptionLabel(value);
  return value === undefined ? '使用默认值' : '结构化配置';
}

export function validInputSettingValue(field: Record<string, unknown>, value: DraftValue): boolean {
  const type = stringValue(field.type);
  if (type === 'boolean') return typeof value === 'boolean';
  if (Array.isArray(field.options)) return field.options.some((option) => String(option) === value);
  if (type === 'integer' || type === 'number') {
    if (typeof value !== 'number' || !Number.isFinite(value)) return false;
    if (type === 'integer' && !Number.isInteger(value)) return false;
    if (typeof field.min === 'number' && value < field.min) return false;
    if (typeof field.max === 'number' && value > field.max) return false;
  }
  if (type === 'string') {
    if (typeof value !== 'string') return false;
    if (typeof field.maxLength === 'number' && value.length > field.maxLength) return false;
    if (stringValue(field.key) === 'models.path' && value.trim() && !/^(?:\/|~\/)/.test(value.trim())) return false;
  }
  return true;
}

export function publicInputText(value: string, fallback: string): string {
  const text = value.trim();
  if (!text || text.length > 120 || /pathId|schema|revision|hash|receipt|provider|policy|profile|\/api\/|https?:\/\//i.test(text)) return fallback;
  return text
    .replace(/Post-commit/gi, '上屏后')
    .replace(/Active RAG/gi, '主动知识生成')
    .replace(/RAG/gi, '知识召回')
    .replace(/Rime/gi, '输入法')
    .replace(/fallback/gi, '备用方式')
    .replace(/TTL/gi, '保留时间')
    .replace(/patch/gi, '支持');
}

export function inputFieldFallback(key: string): string {
  return ({
    'interaction.composition.showPrediction': '输入拼音时预测',
    'interaction.composition.showOnlyRime': '输入拼音时只显示 Rime 候选',
    'interaction.postCommit.showPendingStatus': '预测开始时显示状态',
    'interaction.postCommit.enabled': '上屏后联想',
    'interaction.postCommit.idleTriggerMs': '停顿多久开始联想',
    'interaction.postCommit.minDeltaChars': '最少新增字符数',
    'interaction.postCommit.maxCallsPer10s': '10 秒最多联想次数',
    'interaction.postCommit.cooldownMs': '两次联想最短间隔',
    'interaction.postCommit.panelTtlMs': '联想候选停留时间',
    'interaction.postCommit.modelBudgetMs': '本机模型最长等待',
    'interaction.postCommit.tabAction': 'Tab 键行为',
    'interaction.postCommit.optionNumber': 'Option+数字行为',
    'display.maxPostCommitCandidates': '联想候选数量',
    'display.panelStyle': '候选界面样式',
    'activeRag.defaultPlacement': '结果插入方式',
    'activeRag.latencyBudgetMs': '生成框最长等待',
    'pinyin.fuzzyProfile': '模糊音方案',
    'lexiconOrganization.enabled': '定期整理',
    'lexiconOrganization.runsPerDay': '每天整理次数',
    'models.modelId': '本机联想模型',
    'models.hot': '联想引擎',
    'models.path': '本机模型目录',
    'models.promptMode': '联想方式',
    'models.maxTokens': '单次联想长度',
    'models.temperature': '表达变化程度',
    'models.topP': '表达变化范围',
  } as Record<string, string>)[key] ?? '输入设置';
}

export function sectionLabel(value: string): string {
  return ({ interaction: '输入体验', display: '候选界面', activeRag: '知识建议', pinyin: '拼音习惯', models: '本机联想', lexiconOrganization: '词库整理' } as Record<string, string>)[value] ?? publicInputText(value, '输入设置');
}

export function inputOptionLabel(value: string): string {
  if (!value) return '未设置';
  return ({
    pass_through: '保持输入法默认行为',
    select_prediction: '选择对应的联想候选',
    select_prediction_by_ordinal: '按序号选择智能候选',
    accept_top_prediction: '接受首个联想候选',
    rime_default: '保持输入法默认行为',
    disabled: '关闭',
    compact: '紧凑',
    balanced: '均衡',
    detailed: '详尽',
    expanded: '展开',
    replace_selection: '替换选中内容',
    insert_after_selection: '插入到选中内容后',
    show_only: '只显示，不插入',
    'sichuan-mild': '四川轻度模糊音',
    minimind_ime_v2: 'MiniMind 输入法 v2',
    qwen3_06b_ime_hot: 'Qwen3 0.6B IME Hot',
    'base-completion': '直接续写',
    'chat-json': '对话式生成',
    none: '关闭',
  } as Record<string, string>)[value] ?? (/[\u3400-\u9fff]/u.test(value) ? value : '自定义设置');
}

export function numericDraftValue(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function modelConfigValue(value: unknown): string {
  const normalized = stringValue(value).trim();
  return normalized && !/[\\/]/.test(normalized) ? normalized : '由本机注册表决定';
}

export function readinessLabel(source: Record<string, unknown>): string {
  if (booleanValue(source.typingReady)) return '系统检查通过';
  return ({ not_selected: '尚未选择', not_registered: '尚未注册', unavailable: '不可用', unknown: '等待状态' } as Record<string, string>)[stringValue(source.readinessState)] ?? '需检查';
}

export function inputSourceDetail(source: Record<string, unknown>): string {
  if (booleanValue(source.typingReady)) return '系统检查已确认';
  if (booleanValue(source.selected)) return '当前已选择';
  if (stringValue(source.inputSourceId)) return '已识别，尚未选择';
  return '系统尚未识别输入源';
}

export function inputSourceMessage(source: Record<string, unknown>): string {
  if (booleanValue(source.typingReady)) return '输入源已被系统识别并选中；真实应用中的输入与选词结果仍是最终验收。';
  const state = stringValue(source.readinessState);
  if (state === 'not_selected') return '请先在系统输入法菜单中选择 PAW 输入法，再进行前台输入实测。';
  if (state === 'not_registered') return '输入法尚未完成系统注册，请重新安装后再试。';
  if (state === 'unavailable') return '输入法服务暂时不可用，请稍后重试。';
  return '正在等待系统确认输入法状态。';
}

export function applyModeLabel(value: string): string {
  return ({
    live: '立即生效',
    reload: '需重新载入',
    restart: '需重启',
    restart_input_method: '重新载入输入法',
    redeploy_rime: '重新部署输入法',
    restart_sidecar: '重新连接本机补全服务',
    restart_predictor: '应用并重启联想模型',
  } as Record<string, string>)[value] ?? '应用后生效';
}

export function profileLabel(value: string): string {
  if (!value) return '尚未读取到运行模式';
  return (presetInputModes as readonly string[]).includes(value) ? value : '自定义模式';
}
