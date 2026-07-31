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
  ) return '标准模式';
  return '';
}

export function modeSettingLabel(key: string): string {
  return ({
    'interaction.postCommit.enabled': '提交后预测',
    'memory.enabled': '记忆增强',
    'activeRag.allowRemoteModel': '远程生成',
    'rag.lanes.tagMemo': '标签记忆',
    'rag.lanes.timeDailyBook': '时间与日记召回',
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
    .replace(/Post-commit/gi, '输入完成后')
    .replace(/Active RAG/gi, '主动知识生成')
    .replace(/RAG/gi, '知识检索')
    .replace(/Rime/gi, '输入法')
    .replace(/fallback/gi, '备用方式')
    .replace(/TTL/gi, '保留时间')
    .replace(/patch/gi, '支持');
}

export function inputFieldFallback(key: string): string {
  return ({
    'interaction.postCommit.enabled': '提交后预测',
    'interaction.postCommit.idleTriggerMs': '停顿多久开始预测',
    'interaction.postCommit.minDeltaChars': '最少新增字符数',
    'interaction.postCommit.maxCallsPer10s': '10 秒最多预测次数',
    'interaction.postCommit.cooldownMs': '两次预测最短间隔',
    'interaction.postCommit.panelTtlMs': '生成结果停留时间',
    'interaction.postCommit.modelBudgetMs': '本机模型最长等待',
    'interaction.postCommit.tabAction': 'Tab 键行为',
    'interaction.postCommit.optionNumber': 'Option+数字行为',
    'display.maxPostCommitCandidates': '续写候选数量',
    'display.panelStyle': '候选界面样式',
    'activeRag.defaultPlacement': '结果插入方式',
    'activeRag.latencyBudgetMs': '生成框最长等待',
    'pinyin.fuzzyProfile': '模糊音方案',
    'lexiconOrganization.enabled': '定期整理',
    'lexiconOrganization.runsPerDay': '每天整理次数',
    'models.modelId': '注册模型 ID',
    'models.hot': '推理 Profile',
    'models.path': '本机模型目录',
    'models.promptMode': 'Prompt 模式',
    'models.maxTokens': '最大生成 Token',
    'models.temperature': 'Temperature',
    'models.topP': 'Top P',
  } as Record<string, string>)[key] ?? '输入设置';
}

export function sectionLabel(value: string): string {
  return ({ interaction: '输入体验', display: '候选界面', activeRag: '主动知识生成', pinyin: '拼音设置', models: '本机预测', lexiconOrganization: '词库定期整理' } as Record<string, string>)[value] ?? publicInputText(value, '输入设置');
}

export function inputOptionLabel(value: string): string {
  if (!value) return '未设置';
  return ({
    pass_through: '保持输入法默认行为',
    select_prediction: '选择对应的续写候选',
    select_prediction_by_ordinal: '按序号选择智能候选',
    accept_top_prediction: '接受首个续写候选',
    rime_default: '保持输入法默认行为',
    disabled: '关闭',
    compact: '紧凑',
    expanded: '展开',
    replace_selection: '替换选中内容',
    insert_after_selection: '插入到选中内容后',
    show_only: '只显示，不插入',
    'sichuan-mild': '四川轻度模糊音',
    minimind_ime_v2: 'MiniMind IME v2',
    qwen3_06b_ime_hot: 'Qwen3 0.6B IME Hot',
    'base-completion': 'Base Completion',
    'chat-json': 'Chat JSON',
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

export function modelTokenLabel(value: unknown): string {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
    ? `${value} token`
    : '由模型 Profile 决定';
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
  if (state === 'not_selected') return '请先在系统输入法菜单中选择澄输入法，再进行前台输入实测。';
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
    restart_sidecar: '重启后台服务',
    restart_predictor: '应用并重启本机模型',
  } as Record<string, string>)[value] ?? '应用后生效';
}

export function profileLabel(value: string): string {
  if (!value) return '尚未读取到运行模式';
  return ['安全模式', '标准模式', '记忆增强', '调试模式'].includes(value) ? value : '自定义模式';
}
