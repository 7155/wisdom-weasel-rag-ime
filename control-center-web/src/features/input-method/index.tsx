import { RefreshCw, TextCursorInput } from 'lucide-react';
import { useState } from 'react';
import { Button, EmptyState, SegmentedControl } from '@/components/primitives';
import { useInputMethodQueries } from './api';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  OperationalList,
  QueryState,
  StatusBadge,
  WorkflowAction,
  arrayRecords,
  asRecord,
  booleanValue,
  configuredLabel,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';

const profiles = ['安全模式', '标准模式', '记忆增强', '调试模式'] as const;

export function InputMethodFeature() {
  const queries = useInputMethodQueries();
  const source = asRecord(queries.source.data);
  const overview = asRecord(queries.overview.data);
  const settingsPayload = asRecord(queries.settings.data);
  const settings = asRecord(settingsPayload.settings);
  const sections = arrayRecords(asRecord(queries.schema.data).sections).filter((section) =>
    ['interaction', 'display', 'activeRag', 'pinyin'].includes(stringValue(section.id)),
  );
  const initialProfile = profiles.includes(stringValue(overview.profile) as typeof profiles[number])
    ? stringValue(overview.profile) as typeof profiles[number]
    : '标准模式';
  const [profile, setProfile] = useState<typeof profiles[number]>(initialProfile);
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
      eyebrow="INPUT"
      routeId="input"
      title="输入法"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="前台输入源" description="显示实际 Squirrel/Rime 输入源与前台就绪状态。">
          <div className="mgmt-grid-2">
            <dl className="mgmt-kv">
              <dt>输入源 ID</dt><dd>{stringValue(source.inputSourceId, 'unknown')}</dd>
              <dt>检查结果</dt><dd><StatusBadge label={stringValue(source.readinessState, booleanValue(source.ok) ? 'ready' : 'unavailable')} tone={booleanValue(source.typingReady) ? 'success' : 'warning'} /></dd>
              <dt>前台可输入</dt><dd>{booleanValue(source.typingReady) ? '是' : '否'}</dd>
              <dt>当前选中</dt><dd>{booleanValue(source.selected) ? '是' : '否'}</dd>
              <dt>消息</dt><dd>{stringValue(source.readinessMessage, stringValue(source.error, '暂无'))}</dd>
            </dl>
            <div className="mgmt-stack">
              <InlineNotice title="候选键位" tone="info">Tab 接受首个助手候选；Option+2-4 选择其他助手候选；普通数字键继续翻页或选择 Rime 候选。</InlineNotice>
              <InlineNotice title="前台验收" tone={booleanValue(source.typingReady) ? 'success' : 'warning'}>
                {booleanValue(source.typingReady) ? '输入源已就绪，仍需真实前台输入与选词 smoke。' : '输入源未就绪；先完成注册、选择与前台 typing smoke。'}
              </InlineNotice>
            </div>
          </div>
        </ManagementSection>

        <ManagementSection title="运行 Profile" description="选择只更新草案；确认前不会更改输入设置。">
          <SegmentedControl aria-label="运行 Profile" items={profiles.map((item) => ({ label: item, value: item }))} onValueChange={setProfile} value={profile} />
          <div className="mgmt-stack" style={{ marginTop: 12 }}>
            <WorkflowAction
              actionId="input.profile.apply"
              description="预览目标模式将改变的输入、记忆和 RAG 选项。"
              mutationKey={['input-method', 'mutation', 'profile']}
              preview={[
                `当前 profile：${stringValue(overview.profile, 'unknown')}`,
                `目标 profile：${profile}`,
                '基础 Rime 解码与普通候选键位不变。',
              ]}
              risk="R1"
              title="应用 Profile 草案"
            />
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
                  title: stringValue(field.label, key),
                  detail: stringValue(field.description, stringValue(field.sectionLabel)),
                  meta: stringValue(field.applyMode, 'live'),
                  status: <span>{formatSetting(current, key)}</span>,
                };
              })}
            />
          ) : (
            <EmptyState description="当前没有可显示的输入设置。" icon={TextCursorInput} title="暂无输入设置" />
          )}
        </ManagementSection>

        <ManagementSection title="词库建议" description="审阅待加入词库的短语，并检查应用与回滚影响。">
          <InlineNotice title="演练模式" tone="warning">当前不会写入或重新部署词库。</InlineNotice>
          <WorkflowAction
            actionId="input.lexicon.apply"
            description="预览所选词条及重新部署影响；当前为演练。"
            mutationKey={['input-method', 'mutation', 'lexicon']}
            preview={[
              '确认待加入词库的短语。',
              '检查重复项与受影响的词频。',
              '完成后需要重新部署 Rime，并提供回滚收据。',
            ]}
            risk="R2"
            title="应用词库审阅"
          />
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function formatSetting(value: unknown, key: string): string {
  if (/token|secret|password|api.?key|authorization|cookie/i.test(key)) return configuredLabel(value);
  if (typeof value === 'boolean') return value ? '已启用' : '已关闭';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value || '未设置';
  return value === undefined ? '使用默认值' : '结构化配置';
}
