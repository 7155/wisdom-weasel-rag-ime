import {
  Cpu,
  Keyboard,
  Network,
  RefreshCw,
  TextCursorInput,
  type LucideIcon,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, EmptyState, Field, Input, SegmentedControl, Select, Switch } from '@/components/primitives';
import { inputSettingsMutationPathIds, useInputMethodQueries } from './api';
import { LexiconWorkflow } from './lexicon-workflow';
import {
  ManagementMutationWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import {
  DataTable,
  InlineNotice,
  ManagementPage,
  ManagementSection,
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
import { useProductIdentity } from '@/features/identity/product-identity';
import './input-method.css';

type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';
type DraftValue = string | number | boolean;
type InputMode = '安全模式' | '标准模式' | '记忆增强' | '调试模式';

const inputModes = [
  { value: '安全模式', label: '安全' },
  { value: '标准模式', label: '标准' },
  { value: '记忆增强', label: '记忆增强' },
  { value: '调试模式', label: '调试' },
] as const;

const inputModeChanges: Record<InputMode, Record<string, DraftValue>> = {
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
  },
  记忆增强: {
    'interaction.postCommit.enabled': true,
    'memory.enabled': true,
    'rag.lanes.tagMemo': true,
    'rag.lanes.timeDailyBook': true,
  },
  调试模式: {
    'interaction.postCommit.enabled': true,
    'diagnostics.liveTrace': true,
    'diagnostics.candidateExplain': true,
    'display.showDiagnosticsInline': true,
  },
};

const commonInputSettingKeys = new Set([
  'interaction.postCommit.enabled',
  'interaction.postCommit.idleTriggerMs',
  'interaction.postCommit.numberKeys',
  'interaction.postCommit.tabAction',
  'display.maxPostCommitCandidates',
  'display.panelStyle',
  'activeRag.defaultPlacement',
  'pinyin.fuzzyProfile',
]);

export function InputMethodFeature() {
  const identity = useProductIdentity();
  const queries = useInputMethodQueries();
  const source = asRecord(queries.source.data);
  const overview = asRecord(queries.overview.data);
  const components = asRecord(overview.components);
  const settingsPayload = asRecord(queries.settings.data);
  const settings = asRecord(settingsPayload.settings);
  const runtimeConfig = asRecord(settingsPayload.runtimeConfig);
  const rawRuntimeRevision = settingsPayload.runtimeRevision ?? runtimeConfig.runtimeRevision;
  const runtimeRevision = typeof rawRuntimeRevision === 'number'
    && Number.isInteger(rawRuntimeRevision)
    && rawRuntimeRevision >= 0
    ? rawRuntimeRevision
    : null;
  const sections = arrayRecords(asRecord(queries.schema.data).sections).filter((section) =>
    ['interaction', 'display', 'activeRag', 'pinyin'].includes(stringValue(section.id)),
  );
  const settingsGroups = sections
    .map((section) => ({
      id: stringValue(section.id),
      fields: arrayRecords(section.fields).filter((field) => commonInputSettingKeys.has(stringValue(field.key))),
    }))
    .filter((section) => section.fields.length > 0);
  const fieldCount = settingsGroups.reduce((count, section) => count + section.fields.length, 0);
  const [changes, setChanges] = useState<Record<string, DraftValue>>({});
  const fields = settingsGroups.flatMap((section) => section.fields);
  const pendingChanges = useMemo(() => Object.fromEntries(
    Object.entries(changes).filter(([key, next]) => (
      commonInputSettingKeys.has(key) && !Object.is(valueAt(settings, key), next)
    )),
  ) as Record<string, DraftValue>, [changes, settings]);
  const diffRows = useMemo(() => Object.entries(pendingChanges).map(([key, next]) => {
    const field = fields.find((item) => stringValue(item.key) === key) ?? {};
    const applyMode = stringValue(field.applyMode, 'live');
    return {
      id: key,
      key: inputFieldFallback(key),
      before: formatSetting(valueAt(settings, key), key),
      after: formatSetting(next, key),
      applyMode: applyModeLabel(applyMode),
      requiresReload: applyMode !== 'live',
    };
  }), [fields, pendingChanges, settings]);
  const hasInvalidChanges = Object.entries(pendingChanges).some(([key, value]) => {
    const field = fields.find((item) => stringValue(item.key) === key) ?? {};
    return !validInputSettingValue(field, value);
  });
  const settingsWriteAvailability = queries.settingsMutationAvailability();
  const inferredMode = inferInputMode(settings);
  const [modeDraft, setModeDraft] = useState<InputMode | ''>('');
  const displayedMode = modeDraft || inferredMode;
  const pendingModeChanges = useMemo(() => modeDraft
    ? Object.fromEntries(Object.entries(inputModeChanges[modeDraft]).filter(([key, value]) => (
      !Object.is(valueAt(settings, key), value)
    ))) as Record<string, DraftValue>
    : {}, [modeDraft, settings]);
  const modeDiffItems = Object.entries(pendingModeChanges).map(([key, value]) => (
    `${modeSettingLabel(key)}：${formatSetting(valueAt(settings, key), key)} → ${formatSetting(value, key)}`
  ));
  const reportedProfile = stringValue(overview.profile);
  const sourceError = queries.source.error as Error | null;
  const overviewError = queries.overview.error as Error | null;
  const settingsError = [queries.settings.error, queries.schema.error].find(Boolean) as Error | null;
  const settingsPending = queries.settings.isPending || queries.schema.isPending;
  const isRefreshing = [
    queries.source,
    queries.overview,
    queries.settings,
    queries.schema,
    queries.capabilities,
    queries.lexiconReview,
  ].some((query) => query.isFetching);

  const refresh = () => {
    const jobs: Promise<unknown>[] = [
      queries.source.refetch(),
      queries.overview.refetch(),
      queries.settings.refetch(),
      queries.schema.refetch(),
      queries.capabilities.refetch(),
    ];
    if (queries.lexiconAvailable) jobs.push(queries.lexiconReview.refetch());
    void Promise.all(jobs);
  };

  const lexiconState = lexiconSectionStatus({
    capabilityError: Boolean(queries.capabilities.error),
    capabilityPending: queries.capabilities.isPending,
    entryCount: queries.lexiconReview.data?.entryCount,
    reviewError: Boolean(queries.lexiconReview.error),
    reviewPending: queries.lexiconReview.isPending,
    supported: queries.lexiconAvailable,
  });

  return (
    <ManagementPage
      actions={(
        <Button
          leadingIcon={<RefreshCw size={15} />}
          loading={isRefreshing}
          onClick={refresh}
          size="small"
        >
          刷新
        </Button>
      )}
      description={`输入法只是${identity.assistantName}了解你的一个可选来源。你可以在这里管理输入体验和个人词库。`}
      eyebrow="输入来源"
      routeId="input"
      title="输入法与词库"
    >
      <ManagementSection
        description="查看 macOS 输入源是否连接，以及听写、本机模型和上下文是否准备好。"
        title="输入法状态"
        trailing={(
          <StatusBadge
            label={queries.overview.isPending ? '正在读取模式' : profileLabel(reportedProfile)}
            tone={overviewError ? 'danger' : 'neutral'}
          />
        )}
      >
        <QueryState
          error={sourceError}
          isPending={queries.source.isPending}
          onRetry={() => void queries.source.refetch()}
        >
          <div aria-label="输入法运行链状态" className="input-status-grid" role="list">
            <InputStatusItem
              detail={inputSourceDetail(source)}
              icon={Keyboard}
              label="系统输入源"
              tone={booleanValue(source.typingReady) ? 'success' : 'warning'}
              value={readinessLabel(source)}
            />
            <InputStatusItem
              {...componentStatus(
                asRecord(components.sidecar),
                '后台服务',
                Network,
                queries.overview.isPending,
                overviewError,
              )}
            />
            <InputStatusItem
              {...componentStatus(
                asRecord(components.predictor),
                '本机模型',
                Cpu,
                queries.overview.isPending,
                overviewError,
              )}
            />
            <InputStatusItem
              {...componentStatus(
                asRecord(components.foregroundContext),
                '前台上下文',
                TextCursorInput,
                queries.overview.isPending,
                overviewError,
              )}
            />
          </div>

          {overviewError ? (
            <div className="input-inline-action">
              <InlineNotice title="部分运行状态读取失败" tone="danger">
                {publicErrorText(overviewError, '输入源状态可用，但暂时无法读取其他运行状态。')}
              </InlineNotice>
              <Button onClick={() => void queries.overview.refetch()} size="small">重试运行状态</Button>
            </div>
          ) : null}

          <InlineNotice
            title={booleanValue(source.typingReady) ? '系统检查通过' : '输入源需要处理'}
            tone={booleanValue(source.typingReady) ? 'success' : 'warning'}
          >
            {inputSourceMessage(source)}
          </InlineNotice>
        </QueryState>
      </ManagementSection>

      <ManagementSection
        description="选择运行模式后先查看具体变化；仅选择模式不会直接修改设置。"
        title="运行模式"
        trailing={<StatusBadge label={displayedMode || '自定义设置'} tone={displayedMode ? 'info' : 'neutral'} />}
      >
        <div className="input-mode-layout">
          <div className="input-mode-choice">
            <strong>希望使用的模式</strong>
            <SegmentedControl
              aria-label="希望使用的运行模式"
              disabled={settingsWriteAvailability.state !== 'available'}
              items={inputModes}
              onValueChange={setModeDraft}
              value={displayedMode as InputMode}
            />
            <span>{modeDraft ? `${modeDiffItems.length} 项设置将发生变化` : inferredMode ? '当前设置与此模式一致' : '当前设置不是预设模式'}</span>
          </div>
          <ManagementMutationWorkflow
            availability={queries.settingsMutationAvailability(
              runtimeRevision === null
                ? '当前设置状态尚未同步，刷新后才能预览。'
                : !modeDraft
                  ? '请选择一个运行模式后再生成预览。'
                  : modeDiffItems.length === 0
                    ? '当前设置已经符合所选模式，无需重复应用。'
                    : '',
            )}
            description="只应用所选模式绑定的设置差异，不会改写其他自定义项。"
            draftKey={JSON.stringify({ mode: modeDraft, changes: pendingModeChanges, runtimeRevision })}
            mutationKey={['input-method', 'mutation', 'mode']}
            onApply={async (preview) => parseManagementWorkReceipt(
              await queries.requestSettingsMutation({
                pathId: inputSettingsMutationPathIds.apply,
                body: {
                  changes: preview.context.changes,
                  expectedRuntimeRevision: preview.expectedRuntimeRevision,
                  previewToken: preview.previewToken,
                  payloadSha256: preview.payloadSha256,
                  confirmText: preview.requiredConfirm,
                },
              }),
              inputSettingsMutationPathIds.apply,
              preview.payloadSha256,
            )}
            onApplied={() => void Promise.all([queries.settings.refetch(), queries.overview.refetch()])}
            onPreview={async () => {
              if (!modeDraft || runtimeRevision === null || modeDiffItems.length === 0) {
                throw new Error('运行模式或当前设置版本已失效，请刷新后重试。');
              }
              const context = { mode: modeDraft, changes: { ...pendingModeChanges } };
              const parsed = parseManagementWorkPreview(
                await queries.requestSettingsMutation({
                  pathId: inputSettingsMutationPathIds.preview,
                  body: { changes: context.changes, expectedRuntimeRevision: runtimeRevision },
                }),
                inputSettingsMutationPathIds.apply,
                context,
              );
              return {
                ...parsed,
                summary: {
                  ...parsed.summary,
                  title: `切换到${modeDraft}？`,
                  items: modeDiffItems,
                },
              };
            }}
            onRollback={async (receipt, preview) => parseManagementWorkReceipt(
              await queries.requestSettingsMutation({
                pathId: inputSettingsMutationPathIds.rollback,
                body: {
                  receiptId: receipt.receiptId,
                  rollbackToken: receipt.rollbackToken,
                  payloadSha256: receipt.payloadSha256,
                  confirmText: 'rollback',
                },
              }),
              inputSettingsMutationPathIds.rollback,
              preview.payloadSha256,
            )}
            onRolledBack={() => {
              setModeDraft('');
              void Promise.all([queries.settings.refetch(), queries.overview.refetch()]);
            }}
            risk={modeDraft === '调试模式' || modeDraft === '安全模式' ? 'R2' : 'R1'}
            title="切换运行模式"
          />
        </div>
      </ManagementSection>

      <ManagementSection
        description="调整常用输入设置；系统会先生成绑定当前版本的预览，只有明确确认后才应用。"
        title="输入设置"
        trailing={(
          <StatusBadge
            label={settingsPending ? '正在读取' : settingsError ? '读取失败' : String(fieldCount) + ' 项'}
            tone={settingsError ? 'danger' : 'neutral'}
          />
        )}
      >
        <QueryState
          error={settingsError}
          isPending={settingsPending}
          onRetry={() => void Promise.all([queries.settings.refetch(), queries.schema.refetch()])}
        >
          {settingsGroups.length ? (
            <div className="input-settings-layout">
              <div className="input-settings-grid">
                {settingsGroups.map((section) => (
                  <section
                    aria-labelledby={'input-settings-' + section.id}
                    className="input-settings-group"
                    key={section.id}
                  >
                    <header>
                      <h3 id={'input-settings-' + section.id}>{sectionLabel(section.id)}</h3>
                      <span>{section.fields.length} 项</span>
                    </header>
                    <div className="input-setting-list">
                      {section.fields.map((field) => {
                        const key = stringValue(field.key);
                        return (
                          <InputSettingField
                            disabled={settingsWriteAvailability.state !== 'available'}
                            field={field}
                            key={key}
                            onChange={(value) => setChanges((current) => ({ ...current, [key]: value }))}
                            value={changes[key] ?? valueAt(settings, key)}
                          />
                        );
                      })}
                    </div>
                  </section>
                ))}
              </div>
              <div className="mgmt-stack">
                <h3 className="input-settings-diff-title">待应用差异</h3>
                {diffRows.length ? (
                  <DataTable
                    caption="输入法设置差异"
                    columns={[
                      { key: 'key', label: '设置项', width: '34%' },
                      { key: 'before', label: '当前' },
                      { key: 'after', label: '目标' },
                      { key: 'applyMode', label: '生效方式', width: '20%' },
                    ]}
                    rows={diffRows}
                  />
                ) : (
                  <EmptyState description="调整左侧设置后会在这里显示差异。" icon={TextCursorInput} title="没有待应用变更" />
                )}
                <ManagementMutationWorkflow
                  availability={queries.settingsMutationAvailability(
                    runtimeRevision === null
                      ? '当前设置状态尚未同步，刷新后才能预览。'
                      : hasInvalidChanges
                        ? '至少一项设置超出可用范围，请先修正。'
                      : diffRows.length === 0
                        ? '修改至少一个常用输入设置后才能生成预览。'
                        : '',
                  )}
                  description="只保存上方列出的差异，并按每项设置的生效方式处理。"
                  draftKey={JSON.stringify({ changes: pendingChanges, runtimeRevision })}
                  mutationKey={['input-method', 'mutation', 'settings']}
                  onApply={async (preview) => parseManagementWorkReceipt(
                    await queries.requestSettingsMutation({
                      pathId: inputSettingsMutationPathIds.apply,
                      body: {
                        changes: preview.context.changes,
                        expectedRuntimeRevision: preview.expectedRuntimeRevision,
                        previewToken: preview.previewToken,
                        payloadSha256: preview.payloadSha256,
                        confirmText: preview.requiredConfirm,
                      },
                    }),
                    inputSettingsMutationPathIds.apply,
                    preview.payloadSha256,
                  )}
                  onApplied={() => {
                    setChanges({});
                    void queries.settings.refetch();
                  }}
                  onPreview={async () => {
                    if (runtimeRevision === null || hasInvalidChanges || diffRows.length === 0) {
                      throw new Error('输入设置差异或当前版本已失效，请刷新后重试。');
                    }
                    const context = { changes: { ...pendingChanges } };
                    const parsed = parseManagementWorkPreview(
                      await queries.requestSettingsMutation({
                        pathId: inputSettingsMutationPathIds.preview,
                        body: { ...context, expectedRuntimeRevision: runtimeRevision },
                      }),
                      inputSettingsMutationPathIds.apply,
                      context,
                    );
                    return {
                      ...parsed,
                      summary: {
                        ...parsed.summary,
                        title: '应用这些输入设置？',
                        items: diffRows.map((row) => `${row.key}：${row.before} → ${row.after}（${row.applyMode}）`),
                      },
                    };
                  }}
                  onRollback={async (receipt, preview) => parseManagementWorkReceipt(
                    await queries.requestSettingsMutation({
                      pathId: inputSettingsMutationPathIds.rollback,
                      body: {
                        receiptId: receipt.receiptId,
                        rollbackToken: receipt.rollbackToken,
                        payloadSha256: receipt.payloadSha256,
                        confirmText: 'rollback',
                      },
                    }),
                    inputSettingsMutationPathIds.rollback,
                    preview.payloadSha256,
                  )}
                  onRolledBack={() => void queries.settings.refetch()}
                  risk={diffRows.some((row) => row.requiresReload) ? 'R2' : 'R1'}
                  title="应用输入设置"
                />
              </div>
            </div>
          ) : (
            <EmptyState
              description="当前没有可显示的输入设置。刷新后仍为空时，可到问题排查页检查状态。"
              icon={TextCursorInput}
              title="暂无输入设置"
            />
          )}
        </QueryState>
      </ManagementSection>

      <ManagementSection
        description="只处理当前审阅记录中的词条；每次写入前都会先预览，之后也可以撤销。"
        title="词库建议"
        trailing={<StatusBadge label={lexiconState.label} tone={lexiconState.tone} />}
      >
        {queries.capabilities.isPending ? (
          <InlineNotice title="正在确认可用能力" tone="info">正在确认当前版本是否支持完整的词库审阅与撤销。</InlineNotice>
        ) : queries.capabilities.error ? (
          <div className="input-inline-action">
            <InlineNotice title="无法确认词库能力" tone="danger">
              {publicErrorText(queries.capabilities.error, '暂时无法确认词库能力，请稍后重试。')}
            </InlineNotice>
            <Button onClick={() => void queries.capabilities.refetch()} size="small">重试能力检查</Button>
          </div>
        ) : !queries.lexiconAvailable ? (
          <InlineNotice title="词库管理不可用" tone="warning">当前版本没有提供完整的审阅、写入与撤销能力。为避免误操作，本页不会执行任何更改。</InlineNotice>
        ) : queries.lexiconReview.isPending ? (
          <InlineNotice title="正在读取词库建议" tone="info">正在准备本次可审阅的词条。</InlineNotice>
        ) : queries.lexiconReview.error ? (
          <div className="input-inline-action">
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
          <InlineNotice title="词库审阅不可用" tone="warning">当前没有可验证的词库审阅记录，请刷新后重试。</InlineNotice>
        )}
      </ManagementSection>
    </ManagementPage>
  );
}

function InputSettingField({
  disabled,
  field,
  onChange,
  value,
}: {
  disabled: boolean;
  field: Record<string, unknown>;
  onChange: (value: DraftValue) => void;
  value: unknown;
}) {
  const key = stringValue(field.key);
  const label = inputFieldFallback(key);
  const description = [
    publicInputText(stringValue(field.description), '当前输入设置'),
    applyModeLabel(stringValue(field.applyMode, 'live')),
  ].join(' · ');
  const type = stringValue(field.type, 'string');
  const id = `input-setting-${key.replace(/[^A-Za-z0-9_-]/g, '-')}`;

  if (type === 'boolean') {
    return (
      <div className="input-setting-editor-row">
        <Switch
          checked={value === true}
          description={description}
          disabled={disabled}
          label={label}
          onCheckedChange={onChange}
        />
      </div>
    );
  }
  if (Array.isArray(field.options)) {
    return (
      <div className="input-setting-editor-row">
        <Field description={description} htmlFor={id} label={label}>
          <Select
            disabled={disabled}
            id={id}
            onValueChange={onChange}
            options={field.options.map((option) => ({
              value: String(option),
              label: inputOptionLabel(String(option)),
            }))}
            value={stringValue(value)}
          />
        </Field>
      </div>
    );
  }
  if (type === 'integer' || type === 'number') {
    return (
      <div className="input-setting-editor-row">
        <Field description={description} htmlFor={id} label={label}>
          <Input
            disabled={disabled}
            id={id}
            max={typeof field.max === 'number' ? field.max : undefined}
            min={typeof field.min === 'number' ? field.min : undefined}
            onChange={(event) => onChange(Number(event.target.value))}
            step={typeof field.step === 'number' ? field.step : 1}
            type="number"
            value={typeof value === 'number' ? String(value) : ''}
          />
        </Field>
      </div>
    );
  }
  return (
    <div className="input-setting-editor-row input-setting-editor-row--readonly">
      <span><strong>{label}</strong><small>{description}</small></span>
      <StatusBadge label={formatSetting(value, key)} tone="neutral" />
    </div>
  );
}

function InputStatusItem({
  detail,
  icon: Icon,
  label,
  tone,
  value,
}: {
  detail: string;
  icon: LucideIcon;
  label: string;
  tone: StatusTone;
  value: string;
}) {
  return (
    <div className="input-status-item" data-tone={tone} role="listitem">
      <span aria-hidden="true" className="input-status-item__icon"><Icon size={16} /></span>
      <span className="input-status-item__copy">
        <small>{label}</small>
        <strong>{value}</strong>
        <span title={detail}>{detail}</span>
      </span>
    </div>
  );
}

function componentStatus(
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

function inferInputMode(settings: Record<string, unknown>): InputMode | '' {
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

function modeSettingLabel(key: string): string {
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

function formatSetting(value: unknown, key: string): string {
  if (/token|secret|password|api.?key|authorization|cookie/i.test(key)) return configuredLabel(value);
  if (typeof value === 'boolean') return value ? '已启用' : '已关闭';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return inputOptionLabel(value);
  return value === undefined ? '使用默认值' : '结构化配置';
}

function validInputSettingValue(field: Record<string, unknown>, value: DraftValue): boolean {
  const type = stringValue(field.type);
  if (type === 'boolean') return typeof value === 'boolean';
  if (Array.isArray(field.options)) return field.options.some((option) => String(option) === value);
  if (type === 'integer' || type === 'number') {
    if (typeof value !== 'number' || !Number.isFinite(value)) return false;
    if (type === 'integer' && !Number.isInteger(value)) return false;
    if (typeof field.min === 'number' && value < field.min) return false;
    if (typeof field.max === 'number' && value > field.max) return false;
  }
  return true;
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
    'interaction.postCommit.enabled': '提交后预测',
    'interaction.postCommit.idleTriggerMs': '停顿多久开始预测',
    'interaction.postCommit.numberKeys': '预测出现时的数字键',
    'interaction.postCommit.tabAction': 'Tab 键行为',
    'display.maxPostCommitCandidates': '续写候选数量',
    'display.panelStyle': '候选界面样式',
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
  if (booleanValue(source.typingReady)) return '系统检查通过';
  return ({ not_selected: '尚未选择', not_registered: '尚未注册', unavailable: '不可用', unknown: '等待状态' } as Record<string, string>)[stringValue(source.readinessState)] ?? '需检查';
}

function inputSourceDetail(source: Record<string, unknown>): string {
  if (booleanValue(source.typingReady)) return '系统检查已确认';
  if (booleanValue(source.selected)) return '当前已选择';
  if (stringValue(source.inputSourceId)) return '已识别，尚未选择';
  return '系统尚未识别输入源';
}

function inputSourceMessage(source: Record<string, unknown>): string {
  if (booleanValue(source.typingReady)) return '输入源已被系统识别并选中；真实应用中的输入与选词结果仍是最终验收。';
  const state = stringValue(source.readinessState);
  if (state === 'not_selected') return '请先在系统输入法菜单中选择智鼬输入法，再进行前台输入实测。';
  if (state === 'not_registered') return '输入法尚未完成系统注册，请重新安装后再试。';
  if (state === 'unavailable') return '输入法服务暂时不可用，请稍后重试。';
  return '正在等待系统确认输入法状态。';
}

function applyModeLabel(value: string): string {
  return ({
    live: '立即生效',
    reload: '需重新载入',
    restart: '需重启',
    restart_input_method: '重新载入输入法',
    redeploy_rime: '重新部署输入法',
    restart_sidecar: '重启后台服务',
    restart_predictor: '重启本机模型',
  } as Record<string, string>)[value] ?? '应用后生效';
}

function profileLabel(value: string): string {
  if (!value) return '尚未读取到运行模式';
  return ['安全模式', '标准模式', '记忆增强', '调试模式'].includes(value) ? value : '自定义模式';
}

function lexiconSectionStatus({
  capabilityError,
  capabilityPending,
  entryCount,
  reviewError,
  reviewPending,
  supported,
}: {
  capabilityError: boolean;
  capabilityPending: boolean;
  entryCount: number | undefined;
  reviewError: boolean;
  reviewPending: boolean;
  supported: boolean;
}): { label: string; tone: StatusTone } {
  if (capabilityPending) return { label: '能力检查中', tone: 'neutral' };
  if (capabilityError) return { label: '能力读取失败', tone: 'danger' };
  if (!supported) return { label: '当前不可用', tone: 'warning' };
  if (reviewPending) return { label: '正在读取', tone: 'neutral' };
  if (reviewError) return { label: '读取失败', tone: 'danger' };
  if (entryCount === undefined) return { label: '等待审阅快照', tone: 'warning' };
  return {
    label: entryCount > 0 ? String(entryCount) + ' 条待审' : '暂无待审',
    tone: entryCount > 0 ? 'info' : 'success',
  };
}
