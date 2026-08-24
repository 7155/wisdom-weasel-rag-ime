import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Brain, RefreshCw, Save } from 'lucide-react';
import { useControlTransport } from '@/app/control-transport';
import { Button, Field, Select, Switch } from '@/components/primitives';
import {
  InlineNotice,
  ManagementSection,
  QueryState,
  asRecord,
  booleanValue,
  numberValue,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import {
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';

type PreferenceLevel = 'avoid' | 'weaken' | 'normal' | 'priority';
type StablePreferenceLevel = Exclude<PreferenceLevel, 'avoid'>;
type TemporaryDetailLevel = Exclude<PreferenceLevel, 'priority'>;
type RecallDetail = 'compact' | 'balanced' | 'detailed';

type MemoryPreferenceDraft = {
  stablePreference: StablePreferenceLevel;
  temporaryDetails: TemporaryDetailLevel;
  includeAgentDialogue: boolean;
  recallDetail: RecallDetail;
};

const stablePreferenceOptions = [
  { value: 'weaken', label: '弱化' },
  { value: 'normal', label: '正常记住' },
  { value: 'priority', label: '优先记住' },
] as const;
const temporaryDetailOptions = [
  { value: 'avoid', label: '尽快忘记' },
  { value: 'weaken', label: '弱化' },
  { value: 'normal', label: '正常记住' },
] as const;
const recallDetailOptions = [
  { value: 'compact', label: '简洁' },
  { value: 'balanced', label: '平衡' },
  { value: 'detailed', label: '详细' },
] as const;

export function MemoryPreferences() {
  const transport = useControlTransport();
  const settingsQuery = useQuery({
    queryKey: ['memory', 'preferences', 'settings'],
    queryFn: ({ signal }) => transport.request({ pathId: 'configuration.settings', signal }),
    staleTime: 0,
  });
  const capabilitiesQuery = useQuery({
    queryKey: ['memory', 'preferences', 'capabilities'],
    queryFn: () => transport.capabilities(),
    staleTime: 30_000,
  });
  const persisted = useMemo(() => memoryPreferenceDraft(settingsQuery.data), [settingsQuery.data]);
  const [draft, setDraft] = useState<MemoryPreferenceDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState('');
  const [saveError, setSaveError] = useState('');

  useEffect(() => {
    if (settingsQuery.data && draft === null) setDraft(persisted);
  }, [draft, persisted, settingsQuery.data]);

  const current = draft ?? persisted;
  const changes = memoryPreferenceChanges(persisted, current);
  const routeIds = new Set(capabilitiesQuery.data?.routeIds ?? []);
  const writesSupported = Boolean(
    capabilitiesQuery.data?.features.managementWorkContract
    && capabilitiesQuery.data?.features.configurationSettingsWorkContract
    && routeIds.has('configuration.settings.preview')
    && routeIds.has('configuration.settings.apply'),
  );
  const rawError = settingsQuery.error ?? capabilitiesQuery.error;
  const queryError = rawError
    ? new Error(publicErrorText(rawError, '暂时无法读取本机记忆偏好，请刷新后重试。'))
    : null;

  return (
    <div
      className="memory-preferences memory-preferences--migrated-v1"
      data-dirty={Boolean(Object.keys(changes).length) || undefined}
      data-writable={writesSupported || undefined}
    >
      <ManagementSection
        description="这些选择直接影响本机记忆整理与召回：什么值得保留更久，什么应更快淡出，以及回答时带回多少上下文。"
        title="记忆偏好"
      >
      <QueryState
        error={queryError}
        isPending={settingsQuery.isPending || capabilitiesQuery.isPending}
        onRetry={() => { void Promise.all([settingsQuery.refetch(), capabilitiesQuery.refetch()]); }}
      >
        <div className="memory-preferences__intro">
          <span aria-hidden="true"><Brain size={22} /></span>
          <div><strong>把第二大脑调成你的记忆方式</strong><p>这里不会删除既有记忆；偏好会从下一次整理和召回开始生效。</p></div>
          <span className="memory-preferences__persistence" data-state={!writesSupported ? 'read-only' : Object.keys(changes).length ? 'pending' : 'synced'}>
            <i aria-hidden="true" />
            {!writesSupported ? '只读' : Object.keys(changes).length ? '等待保存' : '已从本机读取'}
          </span>
        </div>
        <div className="memory-preferences__grid">
          <Field description="用户习惯、长期选择和反复确认的偏好会按这个强度保留。" htmlFor="memory-stable-preference" label="稳定偏好">
            <Select
              aria-label="稳定偏好"
              id="memory-stable-preference"
              onValueChange={(value) => updateDraft({ stablePreference: value })}
              options={stablePreferenceOptions}
              value={current.stablePreference}
            />
          </Field>
          <Field description="一次性安排、临时状态和短期细节会按这个速度降低召回权重。" htmlFor="memory-temporary-details" label="临时事项">
            <Select
              aria-label="临时事项"
              id="memory-temporary-details"
              onValueChange={(value) => updateDraft({ temporaryDetails: value })}
              options={temporaryDetailOptions}
              value={current.temporaryDetails}
            />
          </Field>
          <Field description="决定回答时带回多少已治理记忆；越详细，带回的上下文越多。" htmlFor="memory-recall-detail" label="召回详细程度">
            <Select
              aria-label="召回详细程度"
              id="memory-recall-detail"
              onValueChange={(value) => updateDraft({ recallDetail: value })}
              options={recallDetailOptions}
              value={current.recallDetail}
            />
          </Field>
          <div className="memory-preferences__switch">
            <Switch
              checked={current.includeAgentDialogue}
              description="关闭后，新的自动整理不再把 Agent 对话摘要作为辅助上下文；不会删除已经保存的记忆。"
              label="让 Agent 对话摘要参与整理"
              onCheckedChange={(checked) => updateDraft({ includeAgentDialogue: checked })}
            />
          </div>
        </div>
        {!writesSupported ? (
          <InlineNotice title="当前版本只能读取偏好" tone="warning">本机服务尚未开放安全保存接口；页面不会保留仅存在于前端的修改。</InlineNotice>
        ) : null}
        {success ? <InlineNotice title="记忆偏好已保存" tone="success">{success}</InlineNotice> : null}
        {saveError ? <InlineNotice title="记忆偏好没有保存" tone="danger">{saveError}</InlineNotice> : null}
        <div className="memory-preferences__actions">
          <Button
            disabled={!writesSupported || !Object.keys(changes).length || saving}
            leadingIcon={<Save size={15} />}
            loading={saving}
            onClick={() => void save()}
            size="small"
          >保存记忆偏好</Button>
          <Button
            leadingIcon={<RefreshCw size={15} />}
            onClick={() => { setDraft(null); setSuccess(''); setSaveError(''); void settingsQuery.refetch(); }}
            size="small"
            variant="quiet"
          >重新读取</Button>
          <span>{Object.keys(changes).length ? `${Object.keys(changes).length} 项待保存` : '已与本机设置同步'}</span>
        </div>
      </QueryState>
      </ManagementSection>
    </div>
  );

  function updateDraft(change: Partial<MemoryPreferenceDraft>) {
    setDraft((value) => ({ ...(value ?? persisted), ...change }));
    setSuccess('');
    setSaveError('');
  }

  async function save(): Promise<void> {
    const runtimeRevision = settingsRuntimeRevision(settingsQuery.data);
    if (saving || !writesSupported || runtimeRevision === null || !Object.keys(changes).length) return;
    setSaving(true);
    setSuccess('');
    setSaveError('');
    try {
      const context = { changes: { ...changes } };
      const preview = parseManagementWorkPreview(
        await transport.request({
          pathId: 'configuration.settings.preview',
          body: { ...context, expectedRuntimeRevision: runtimeRevision },
        }),
        'configuration.settings.apply',
        context,
      );
      parseManagementWorkReceipt(
        await transport.request({
          pathId: 'configuration.settings.apply',
          body: {
            changes: preview.context.changes,
            expectedRuntimeRevision: preview.expectedRuntimeRevision,
            previewToken: preview.previewToken,
            payloadSha256: preview.payloadSha256,
            confirmText: preview.requiredConfirm,
          },
        }),
        'configuration.settings.apply',
        preview.payloadSha256,
      );
      const refreshed = await settingsQuery.refetch();
      if (!refreshed.data) throw new Error('保存完成，但暂时无法重新读取本机偏好，请点击重新读取。');
      setDraft(memoryPreferenceDraft(refreshed.data));
      setSuccess('已写入本机设置并重新读取；之后的记忆整理与召回会使用这些偏好。');
    } catch (error) {
      setSaveError(publicErrorText(error, '保存失败，本次修改没有被当作已生效；请重新读取后重试。'));
    } finally {
      setSaving(false);
    }
  }
}

function memoryPreferenceDraft(value: unknown): MemoryPreferenceDraft {
  const settings = asRecord(asRecord(value).settings);
  const memory = asRecord(settings.memory);
  const timeDecay = asRecord(memory.timeDecay);
  const automatic = asRecord(memory.automaticOrganization);
  const recall = asRecord(memory.recall);
  const stableDays = numberValue(timeDecay.stablePreferenceHalfLifeDays, 365);
  const temporaryDays = numberValue(timeDecay.temporaryHalfLifeDays, 14);
  const recallDetail = stringValue(recall.detailLevel, 'compact');
  return {
    stablePreference: stableDays >= 730 ? 'priority' : stableDays <= 180 ? 'weaken' : 'normal',
    temporaryDetails: temporaryDays <= 1 ? 'avoid' : temporaryDays <= 7 ? 'weaken' : 'normal',
    includeAgentDialogue: booleanValue(automatic.includeAgentDialogue, true),
    recallDetail: ['compact', 'balanced', 'detailed'].includes(recallDetail) ? recallDetail as RecallDetail : 'compact',
  };
}

function memoryPreferenceChanges(persisted: MemoryPreferenceDraft, draft: MemoryPreferenceDraft): Record<string, boolean | number | string> {
  const changes: Record<string, boolean | number | string> = {};
  if (draft.stablePreference !== persisted.stablePreference) {
    changes['memory.timeDecay.stablePreferenceHalfLifeDays'] = ({ weaken: 180, normal: 365, priority: 730 } as const)[draft.stablePreference];
  }
  if (draft.temporaryDetails !== persisted.temporaryDetails) {
    changes['memory.timeDecay.temporaryHalfLifeDays'] = ({ avoid: 1, weaken: 7, normal: 14 } as const)[draft.temporaryDetails];
  }
  if (draft.includeAgentDialogue !== persisted.includeAgentDialogue) {
    changes['memory.automaticOrganization.includeAgentDialogue'] = draft.includeAgentDialogue;
  }
  if (draft.recallDetail !== persisted.recallDetail) changes['memory.recall.detailLevel'] = draft.recallDetail;
  return changes;
}

function settingsRuntimeRevision(value: unknown): number | null {
  const envelope = asRecord(value);
  const revision = envelope.runtimeRevision ?? asRecord(envelope.runtimeConfig).runtimeRevision;
  return typeof revision === 'number' && Number.isInteger(revision) && revision >= 0 ? revision : null;
}
