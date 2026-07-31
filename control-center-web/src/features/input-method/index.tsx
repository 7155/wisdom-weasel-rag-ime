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
import {
  inputSettingsMutationPathIds,
  useInputMethodQueries,
  type LexiconOrganizationStatus,
} from './api';
import {
  applyModeLabel,
  componentStatus,
  formatSetting,
  inferInputMode,
  inputFieldFallback,
  inputOptionLabel,
  inputSourceDetail,
  inputSourceMessage,
  modeSettingLabel,
  modelConfigValue,
  modelTokenLabel,
  numericDraftValue,
  profileLabel,
  publicInputText,
  readinessLabel,
  sectionLabel,
  validInputSettingValue,
  type DraftValue,
  type InputMode,
  type StatusTone,
} from './input-method-presentation';
import { LexiconWorkflow } from './lexicon-workflow';
import { DiagnosticsRuntimeWorkflow } from '@/features/diagnostics/runtime-actions';
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
  publicErrorText,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';
import { useProductIdentity } from '@/features/identity/product-identity';
import './input-method.css';


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
  'interaction.postCommit.minDeltaChars',
  'interaction.postCommit.maxCallsPer10s',
  'interaction.postCommit.cooldownMs',
  'interaction.postCommit.panelTtlMs',
  'interaction.postCommit.modelBudgetMs',
  'interaction.postCommit.tabAction',
  'interaction.postCommit.optionNumber',
  'display.maxPostCommitCandidates',
  'display.panelStyle',
  'activeRag.defaultPlacement',
  'activeRag.latencyBudgetMs',
  'pinyin.fuzzyProfile',
  'lexiconOrganization.enabled',
  'lexiconOrganization.runsPerDay',
  'models.modelId',
  'models.hot',
  'models.path',
  'models.promptMode',
  'models.maxTokens',
  'models.temperature',
  'models.topP',
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
  const modelsStatus = asRecord(queries.models.data);
  const activeModelConfig = asRecord(modelsStatus.activeConfig);
  const availableModels = arrayRecords(modelsStatus.availableModels);
  const availableModelIds = availableModels
    .map((item) => modelConfigValue(item.id))
    .filter((item) => item !== '由本机注册表决定');
  const modelHealthAgreement = asRecord(modelsStatus.healthAgreement);
  const modelConfigurationPending = booleanValue(modelsStatus.configurationPending);
  const modelHealthReady = booleanValue(modelHealthAgreement.ok);
  const rawRuntimeRevision = settingsPayload.runtimeRevision ?? runtimeConfig.runtimeRevision;
  const runtimeRevision = typeof rawRuntimeRevision === 'number'
    && Number.isInteger(rawRuntimeRevision)
    && rawRuntimeRevision >= 0
    ? rawRuntimeRevision
    : null;
  const sections = arrayRecords(asRecord(queries.schema.data).sections).filter((section) =>
    ['interaction', 'display', 'activeRag', 'pinyin', 'models', 'lexiconOrganization'].includes(stringValue(section.id)),
  );
  const settingsGroups = sections
    .map((section) => ({
      id: stringValue(section.id),
      fields: arrayRecords(section.fields).filter((field) => commonInputSettingKeys.has(stringValue(field.key))),
    }))
    .filter((section) => section.fields.length > 0);
  const fieldCount = settingsGroups.reduce((count, section) => count + section.fields.length, 0);
  const [changes, setChanges] = useState<Record<string, DraftValue>>({});
  const updateSettingChange = (key: string, value: DraftValue) => {
    setChanges((current) => {
      const next = { ...current, [key]: value };
      if (key !== 'models.modelId' || typeof value !== 'string') return next;
      const selected = value
        ? availableModels.find((item) => stringValue(item.id) === value)
        : availableModels.find((item) => booleanValue(item.active));
      if (!selected) return next;
      return {
        ...next,
        'models.hot': stringValue(selected.profileId),
        'models.path': stringValue(selected.path),
        'models.promptMode': stringValue(selected.promptMode),
        'models.maxTokens': numericDraftValue(selected.maxTokens, 8),
        'models.temperature': numericDraftValue(selected.temperature, 0.15),
        'models.topP': numericDraftValue(selected.topP, 0.85),
      };
    });
  };
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
  const nativeExternalActions = Boolean(
    queries.capabilities.data?.native.approvedExternalActions
      && queries.transport.runApprovedExternalAction,
  );
  const sourceError = queries.source.error as Error | null;
  const overviewError = queries.overview.error as Error | null;
  const settingsError = [queries.settings.error, queries.schema.error].find(Boolean) as Error | null;
  const settingsPending = queries.settings.isPending || queries.schema.isPending;
  const isRefreshing = [
    queries.source,
    queries.overview,
    queries.models,
    queries.settings,
    queries.schema,
    queries.capabilities,
    queries.lexiconReview,
  ].some((query) => query.isFetching);

  const refresh = () => {
    const jobs: Promise<unknown>[] = [
      queries.source.refetch(),
      queries.overview.refetch(),
      queries.models.refetch(),
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
        description="模型设置保存为期望状态；只有受信任宿主完成重装且 Sidecar 与 MLX 健康回读一致后才算生效。"
        title="本地预测"
        trailing={(
          <StatusBadge
            label={queries.models.isPending ? '正在读取' : modelHealthReady && !modelConfigurationPending ? '配置已生效' : '等待应用'}
            tone={modelHealthReady && !modelConfigurationPending ? 'success' : 'warning'}
          />
        )}
      >
        {booleanValue(modelsStatus.statusUnavailable) ? (
          <InlineNotice title="模型状态暂不可用" tone="warning">
            仍可编辑设置；应用前请刷新模型状态。
          </InlineNotice>
        ) : queries.models.isPending ? (
          <InlineNotice title="正在读取模型状态" tone="info">正在核对模型注册表、后台服务与 MLX 预测器。</InlineNotice>
        ) : null}
          <dl className="mgmt-kv">
            <dt>当前模型</dt><dd>{modelConfigValue(activeModelConfig.modelId)}</dd>
            <dt>已登记模型</dt><dd>{availableModelIds.length ? availableModelIds.join('、') : '等待注册表状态'}</dd>
            <dt>推理 Profile</dt><dd>{inputOptionLabel(stringValue(activeModelConfig.profileId))}</dd>
            <dt>Prompt 模式</dt><dd>{inputOptionLabel(stringValue(activeModelConfig.promptMode))}</dd>
            <dt>生成上限</dt><dd>{modelTokenLabel(activeModelConfig.maxTokens)}</dd>
          </dl>
          <InlineNotice
            title={modelHealthReady && !modelConfigurationPending ? '模型配置一致' : modelConfigurationPending ? '设置已保存，等待应用' : '运行配置需要修复'}
            tone={modelHealthReady && !modelConfigurationPending ? 'success' : 'warning'}
          >
            {modelHealthReady && !modelConfigurationPending
              ? '模型注册表、后台服务和 MLX 预测器报告了同一组配置。'
              : '先在下方修改并保存设置，再通过受信任操作应用；普通数字键始终保留给输入法。'}
          </InlineNotice>
          {runtimeRevision === null ? (
            <InlineNotice title="正在等待运行版本" tone="warning">运行版本返回后才能安全应用模型配置。</InlineNotice>
          ) : !nativeExternalActions ? (
            <InlineNotice title="请在已安装的应用中操作" tone="warning">浏览器预览可以查看和保存设置，但重装本机模型只允许由已安装宿主执行。</InlineNotice>
          ) : null}
          <DiagnosticsRuntimeWorkflow
            action="restart_predictor"
            description="读取已保存设置，更新模型注册表，依次重启 MLX 与后台服务，并执行两端健康一致性检查。"
            nativeExternalActions={nativeExternalActions}
            onApplied={refresh}
            risk="R2"
            runtimeRevision={runtimeRevision ?? -1}
            title="应用并重启本机预测"
            transport={queries.transport}
          />
      </ManagementSection>

      <ManagementSection
        description="调整输入体验和本机模型；系统会先生成绑定当前版本的预览，只有明确确认后才应用。"
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
                            modelIds={key === 'models.modelId' ? availableModelIds : undefined}
                            onChange={(value) => updateSettingChange(key, value)}
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
                    void Promise.all([queries.settings.refetch(), queries.models.refetch(), queries.overview.refetch()]);
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
                  onRolledBack={() => void Promise.all([queries.settings.refetch(), queries.models.refetch()])}
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
        description="候选数量和触发延迟需要写入受管理的 Rime 配置块并重新载入；Tab 与 Option+数字策略由后台响应实时下发。"
        title="应用到输入法前端"
      >
        {!nativeExternalActions ? (
          <InlineNotice title="请在已安装的应用中操作" tone="warning">
            浏览器预览不会改写 Rime 文件，也不会重载当前输入法。
          </InlineNotice>
        ) : runtimeRevision === null ? (
          <InlineNotice title="正在等待运行版本" tone="warning">运行版本返回后才能生成绑定当前状态的部署预览。</InlineNotice>
        ) : null}
        <DiagnosticsRuntimeWorkflow
          action="redeploy_rime"
          description="从设置数据库读取候选数量和停顿触发时间，只更新应用拥有的 YAML 块，然后构建并重新载入 Squirrel。"
          nativeExternalActions={nativeExternalActions}
          onApplied={refresh}
          risk="R3"
          runtimeRevision={runtimeRevision ?? -1}
          title="应用输入法前端设置"
          transport={queries.transport}
        />
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
          <>
            <LexiconOrganizationState organization={queries.lexiconReview.data.organization} />
            <LexiconWorkflow
              isFetching={queries.lexiconReview.isFetching}
              onRefresh={() => void queries.lexiconReview.refetch()}
              review={queries.lexiconReview.data}
              transport={queries.transport}
            />
          </>
        ) : (
          <InlineNotice title="词库审阅不可用" tone="warning">当前没有可验证的词库审阅记录，请刷新后重试。</InlineNotice>
        )}
      </ManagementSection>
    </ManagementPage>
  );
}

function LexiconOrganizationState({
  organization,
}: {
  organization: LexiconOrganizationStatus;
}) {
  const lastRun = organization.lastRun;
  const failure = lastRun.status === 'failed';
  return (
    <div className="mgmt-stack">
      <dl className="mgmt-kv">
        <dt>定期整理建议</dt>
        <dd>{organization.enabled ? `已启用 · 每天约 ${organization.runsPerDay} 次` : '已停用'}</dd>
        <dt>上次运行</dt>
        <dd>{formatLexiconRunTime(organization.lastRunAtMs, '尚未运行')}</dd>
        <dt>下次运行</dt>
        <dd>{organization.enabled && organization.nextRunAtMs !== null ? formatLexiconRunTime(organization.nextRunAtMs, '等待下一次本机整理') : '已停用'}</dd>
        <dt>本次结果</dt>
        <dd>{lastRun.status === 'succeeded' ? `已整理 ${lastRun.candidateCount} 条待审阅建议` : lastRun.status === 'running' ? '正在本机整理' : failure ? '运行失败' : '等待首次运行'}</dd>
        <dt>由谁处理</dt>
        <dd>由本机定时任务安排；Rime 仍负责基础输入和候选排序</dd>
      </dl>
      {failure ? (
        <InlineNotice title="上次定期整理失败" tone="danger">
          {lastRun.error || '本机任务没有返回成功结果。'}
          {lastRun.errorCode ? `（${lastRun.errorCode}）` : ''}
        </InlineNotice>
      ) : (
        <InlineNotice title="只在本机整理，先审阅再写入" tone="info">
          定期整理只根据本机实际选词反馈生成待审阅建议。页面只保存数量和校验摘要，不保存建议正文；你确认前，不会改动或重排 Rime 词库。
        </InlineNotice>
      )}
    </div>
  );
}

function formatLexiconRunTime(value: number, fallback: string): string {
  if (!Number.isFinite(value) || value <= 0) return fallback;
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function InputSettingField({
  disabled,
  field,
  modelIds,
  onChange,
  value,
}: {
  disabled: boolean;
  field: Record<string, unknown>;
  modelIds?: readonly string[];
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
  if (key === 'models.modelId' && modelIds?.length) {
    const current = stringValue(value);
    const options = [...new Set([...modelIds, ...(current ? [current] : [])])];
    return (
      <div className="input-setting-editor-row">
        <Field description={description} htmlFor={id} label={label}>
          <Select
            disabled={disabled}
            id={id}
            onValueChange={(next) => onChange(next === '__active_model__' ? '' : next)}
            options={[
              { value: '__active_model__', label: '沿用当前 Hot 模型' },
              ...options.map((modelId) => ({ value: modelId, label: modelId })),
            ]}
            value={current || '__active_model__'}
          />
        </Field>
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
  if (type === 'string') {
    return (
      <div className="input-setting-editor-row">
        <Field description={description} htmlFor={id} label={label}>
          <Input
            disabled={disabled}
            id={id}
            maxLength={typeof field.maxLength === 'number' ? field.maxLength : undefined}
            onChange={(event) => onChange(event.target.value)}
            type="text"
            value={stringValue(value)}
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
