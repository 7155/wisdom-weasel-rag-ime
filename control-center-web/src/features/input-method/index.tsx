import { RefreshCw, TextCursorInput } from 'lucide-react';
import { Button, EmptyState } from '@/components/primitives';
import { useInputMethodQueries } from './api';
import { LexiconWorkflow } from './lexicon-workflow';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  OperationalList,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  booleanValue,
  configuredLabel,
  publicErrorText,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';
import { UnsupportedWorkflow } from '@/features/overview/management-mutation';

export function InputMethodFeature() {
  const queries = useInputMethodQueries();
  const source = asRecord(queries.source.data);
  const overview = asRecord(queries.overview.data);
  const settingsPayload = asRecord(queries.settings.data);
  const settings = asRecord(settingsPayload.settings);
  const sections = arrayRecords(asRecord(queries.schema.data).sections).filter((section) =>
    ['interaction', 'display', 'activeRag', 'pinyin'].includes(stringValue(section.id)),
  );
  const reportedProfile = stringValue(overview.profile);
  const error = [queries.source.error, queries.overview.error, queries.settings.error, queries.schema.error].find(Boolean) as Error | null;
  const pending = queries.source.isPending || queries.settings.isPending || queries.schema.isPending;

  const refresh = () => {
    void Promise.all([queries.source.refetch(), queries.overview.refetch(), queries.settings.refetch(), queries.schema.refetch()]);
  };

  const fields = sections.flatMap((section) =>
    arrayRecords(section.fields).map((field) => ({
      ...field,
      sectionLabel: stringValue(section.label, stringValue(section.id)),
    } as Record<string, unknown>)),
  );

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={queries.source.isFetching} onClick={refresh} size="small">刷新</Button>}
      description="管理提交后预测、快捷键、候选界面、模糊音和词库审阅。普通拼音与数字键仍由 Rime 负责。"
      eyebrow="输入"
      routeId="input"
      title="输入法"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="前台输入源" description="显示实际 Squirrel/Rime 输入源与前台就绪状态。">
          <div className="mgmt-grid-2">
            <dl className="mgmt-kv">
              <dt>输入源</dt><dd>{stringValue(source.inputSourceId) ? '已识别' : '未识别'}</dd>
              <dt>检查结果</dt><dd><StatusBadge label={readinessLabel(source)} tone={booleanValue(source.typingReady) ? 'success' : 'warning'} /></dd>
              <dt>前台可输入</dt><dd>{booleanValue(source.typingReady) ? '是' : '否'}</dd>
              <dt>当前选中</dt><dd>{booleanValue(source.selected) ? '是' : '否'}</dd>
              <dt>提示</dt><dd>{inputSourceMessage(source)}</dd>
            </dl>
            <div className="mgmt-stack">
              <InlineNotice title="候选键位" tone="info">Tab 接受首个助手候选；Option+2-4 选择其他助手候选；普通数字键继续翻页或选择 Rime 候选。</InlineNotice>
              <InlineNotice title="前台验收" tone={booleanValue(source.typingReady) ? 'success' : 'warning'}>
                {booleanValue(source.typingReady) ? '输入源已就绪，仍需在真实应用中完成输入与选词实测。' : '输入源未就绪；先完成注册、选择与前台输入实测。'}
              </InlineNotice>
            </div>
          </div>
        </ManagementSection>

        <ManagementSection title="运行模式" description="显示当前模式；暂不支持安全切换时保持只读。">
          <div className="mgmt-stack" style={{ marginTop: 12 }}>
            <InlineNotice title="当前模式" tone="info">{profileLabel(reportedProfile)}</InlineNotice>
            <UnsupportedWorkflow description="在多个输入与记忆预设之间切换。" reason="当前版本暂不支持安全切换。请使用下方已经可用的具体设置。" risk="R1" title="切换运行模式" />
          </div>
        </ManagementSection>

        <ManagementSection title="输入设置" description="查看当前输入行为；敏感配置只显示是否已配置。">
          {fields.length ? (
            <OperationalList
              items={fields.map((field) => {
                const key = stringValue(field.key);
                const current = valueAt(settings, key);
                return {
                  id: key,
                  title: publicInputText(stringValue(field.label), inputFieldFallback(key)),
                  detail: publicInputText(stringValue(field.description), sectionLabel(stringValue(field.sectionLabel))),
                  meta: applyModeLabel(stringValue(field.applyMode, 'live')),
                  status: <span>{formatSetting(current, key)}</span>,
                };
              })}
            />
          ) : (
            <EmptyState description="当前没有可显示的输入设置。" icon={TextCursorInput} title="暂无输入设置" />
          )}
        </ManagementSection>

        <ManagementSection title="词库建议" description="审阅待加入词库的短语，并检查应用与撤销影响。">
          {queries.capabilities.isPending ? (
            <InlineNotice title="正在确认可用能力" tone="info">正在确认当前版本是否支持完整的词库审阅与撤销。</InlineNotice>
          ) : queries.capabilities.error ? (
            <InlineNotice title="无法确认词库能力" tone="danger">{publicErrorText(queries.capabilities.error, '暂时无法确认词库能力，请稍后重试。')}</InlineNotice>
          ) : !queries.lexiconAvailable ? (
            <InlineNotice title="词库管理不可用" tone="warning">当前版本没有提供完整的审阅、写入与撤销能力。为避免误操作，本页不会执行任何更改。</InlineNotice>
          ) : queries.lexiconReview.isPending ? (
            <InlineNotice title="正在读取词库建议" tone="info">正在准备本次可审阅的词条。</InlineNotice>
          ) : queries.lexiconReview.error ? (
            <div className="mgmt-stack">
              <InlineNotice title="词库审阅失败" tone="danger">{publicErrorText(queries.lexiconReview.error, '暂时无法读取词库建议，请稍后重试。')}</InlineNotice>
              <Button onClick={() => void queries.lexiconReview.refetch()} size="small">重试审阅</Button>
            </div>
          ) : queries.lexiconReview.data ? (
            <LexiconWorkflow
              isFetching={queries.lexiconReview.isFetching}
              onRefresh={() => void queries.lexiconReview.refetch()}
              review={queries.lexiconReview.data}
              transport={queries.transport}
            />
          ) : (
            <InlineNotice title="词库审阅不可用" tone="warning">服务端没有返回可验证的审阅快照。</InlineNotice>
          )}
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function formatSetting(value: unknown, key: string): string {
  if (/token|secret|password|api.?key|authorization|cookie/i.test(key)) return configuredLabel(value);
  if (typeof value === 'boolean') return value ? '已启用' : '已关闭';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return inputOptionLabel(value);
  return value === undefined ? '使用默认值' : '结构化配置';
}

function publicInputText(value: string, fallback: string): string {
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

function inputFieldFallback(key: string): string {
  return ({
    'interaction.postCommit.numberKeys': '预测出现时的数字键',
    'interaction.postCommit.tabAction': 'Tab 键行为',
    'display.maxPostCommitCandidates': '续写候选数量',
    'activeRag.defaultPlacement': '结果插入方式',
    'pinyin.fuzzyProfile': '模糊音方案',
  } as Record<string, string>)[key] ?? '输入设置';
}

function sectionLabel(value: string): string {
  return ({ interaction: '输入体验', display: '候选界面', activeRag: '主动知识生成', pinyin: '拼音设置' } as Record<string, string>)[value] ?? publicInputText(value, '输入设置');
}

function inputOptionLabel(value: string): string {
  if (!value) return '未设置';
  return ({
    pass_through: '保持输入法默认行为',
    select_prediction: '选择对应的续写候选',
    accept_top_prediction: '接受首个续写候选',
    rime_default: '保持输入法默认行为',
    disabled: '关闭',
    compact: '紧凑',
    expanded: '展开',
    replace_selection: '替换选中内容',
    insert_after_selection: '插入到选中内容后',
    show_only: '只显示，不插入',
    'sichuan-mild': '四川轻度模糊音',
    none: '关闭',
  } as Record<string, string>)[value] ?? (/[\u3400-\u9fff]/u.test(value) ? value : '自定义设置');
}

function readinessLabel(source: Record<string, unknown>): string {
  if (booleanValue(source.typingReady)) return '可输入';
  return ({ not_selected: '尚未选择', not_registered: '尚未注册', unavailable: '不可用', unknown: '等待状态' } as Record<string, string>)[stringValue(source.readinessState)] ?? '需检查';
}

function inputSourceMessage(source: Record<string, unknown>): string {
  if (booleanValue(source.typingReady)) return '输入法已经可以在前台应用中使用。';
  const state = stringValue(source.readinessState);
  if (state === 'not_selected') return '请先在系统输入法菜单中选择智鼬输入法。';
  if (state === 'not_registered') return '输入法尚未完成系统注册，请重新安装后再试。';
  if (state === 'unavailable') return '输入法服务暂时不可用，请稍后重试。';
  return '正在等待系统确认输入法状态。';
}

function applyModeLabel(value: string): string {
  return ({ live: '立即生效', reload: '需重新载入', restart: '需重启' } as Record<string, string>)[value] ?? '应用后生效';
}

function profileLabel(value: string): string {
  if (!value) return '尚未读取到运行模式';
  return ['安全模式', '标准模式', '记忆增强', '调试模式'].includes(value) ? value : '自定义模式';
}
