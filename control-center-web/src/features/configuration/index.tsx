import { FileCheck2, KeyRound, RefreshCw, Settings2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button, EmptyState, Field, Input, Select, Switch } from '@/components/primitives';
import {
  configurationMutationPathIds,
  isSecretConfigurationKey,
  useConfigurationMutationBoundary,
  useConfigurationQueries,
} from './api';
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
  MetricStrip,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  configuredLabel,
  publicErrorText,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';
import { PiProviderCredentials } from './PiProviderCredentials';
import { PortabilityWorkflows } from './PortabilityWorkflows';
import './configuration.css';

type DraftValue = string | number | boolean;

type PiModelOption = {
  id: string;
  name: string;
  provider: string;
  reference: string;
  thinkingLevels: string[];
};

export function ConfigurationFeature() {
  const queries = useConfigurationQueries();
  const mutationBoundary = useConfigurationMutationBoundary();
  const settingsEnvelope = asRecord(queries.settings.data);
  const settings = asRecord(settingsEnvelope.settings);
  const runtimeConfig = asRecord(settingsEnvelope.runtimeConfig);
  const rawRuntimeRevision = settingsEnvelope.runtimeRevision ?? runtimeConfig.runtimeRevision;
  const runtimeRevision = typeof rawRuntimeRevision === 'number'
    && Number.isInteger(rawRuntimeRevision)
    && rawRuntimeRevision >= 0
    ? rawRuntimeRevision
    : null;
  const schemaEnvelope = asRecord(queries.schema.data);
  const sections = arrayRecords(schemaEnvelope.sections);
  const piModels = useMemo(
    () => parsePiModelOptions(queries.modelCatalog.data),
    [queries.modelCatalog.data],
  );
  const [activeSection, setActiveSection] = useState('');
  const [expertMode, setExpertMode] = useState(false);
  const [changes, setChanges] = useState<Record<string, DraftValue>>({});

  useEffect(() => {
    if (!activeSection && sections.length) setActiveSection(stringValue(sections[0]?.id));
  }, [activeSection, sections]);

  const section = sections.find((item) => stringValue(item.id) === activeSection) ?? sections[0];
  const fields = arrayRecords(section?.fields).filter((field) => expertMode || field.expert !== true);
  const pendingChanges = useMemo(() => Object.fromEntries(
    Object.entries(changes).filter(([key, next]) => (
      !isSecretConfigurationField(findField(sections, key), key)
      && !Object.is(valueAt(settings, key), next)
    )),
  ) as Record<string, DraftValue>, [changes, sections, settings]);
  const diffRows = useMemo(() => Object.entries(pendingChanges).map(([key, next]) => {
    const field = findField(sections, key);
    const applyMode = stringValue(field.applyMode, 'live');
    return {
      id: key,
      key: publicFieldLabel(key, stringValue(field.label)),
      before: displayDraftValue(valueAt(settings, key), field, key),
      after: displayDraftValue(next, field, key),
      applyMode: applyModeLabel(applyMode),
      requiresReload: applyMode !== 'live',
    };
  }), [pendingChanges, sections, settings]);
  const hasSensitiveChanges = Object.entries(changes).some(([key, next]) => (
    isSecretConfigurationField(findField(sections, key), key)
    && !Object.is(valueAt(settings, key), next)
  ));
  const rawError = queries.settings.error
    ?? queries.schema.error
    ?? queries.capabilities.error;
  const error = rawError ? new Error(publicErrorText(rawError, '无法读取本机设置，请刷新后重试。')) : null;
  const pending = queries.settings.isPending
    || queries.schema.isPending
    || queries.capabilities.isPending
    || (queries.modelCatalogSupported && queries.modelCatalog.isPending);
  const refresh = () => {
    const refreshes = [
      queries.settings.refetch(),
      queries.schema.refetch(),
      queries.capabilities.refetch(),
    ];
    if (queries.modelCatalogSupported) refreshes.push(queries.modelCatalog.refetch());
    void Promise.all(refreshes);
  };

  const updateField = (field: Record<string, unknown>, value: DraftValue) => {
    const key = stringValue(field.key);
    setChanges((current) => {
      const next = { ...current, [key]: value };
      const type = stringValue(field.type);
      if (type !== 'pi-model') return next;
      const thinkingField = sections
        .flatMap((item) => arrayRecords(item.fields))
        .find((item) => stringValue(item.modelKey) === key);
      const thinkingKey = stringValue(thinkingField?.key);
      if (!thinkingKey) return next;
      const selected = piModels.find((model) => model.reference === String(value));
      const supported = oneShotThinkingLevels(selected);
      const currentThinking = String(current[thinkingKey] ?? valueAt(settings, thinkingKey) ?? '');
      if (!supported.includes(currentThinking) && supported.length) {
        next[thinkingKey] = supported.includes('off') ? 'off' : supported[0];
      }
      return next;
    });
  };

  return (
    <ManagementPage
      actions={
        <>
          <Switch checked={expertMode} label="高级设置" onCheckedChange={setExpertMode} />
          <Button leadingIcon={<RefreshCw size={15} />} loading={queries.settings.isFetching} onClick={refresh} size="small">刷新</Button>
        </>
      }
      description="管理本机设置与模型账号；变更会先预览，再由你确认。"
      eyebrow="设置"
      routeId="configuration"
      title="配置与迁移"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <PiProviderCredentials />
        <ManagementSection title="配置快照">
          <MetricStrip items={[
            { label: '设置分组', value: sections.length, detail: '可编辑范围', icon: Settings2 },
            { label: '当前设置', value: settingsEnvelope.ok === true ? '已加载' : '需刷新', detail: '来自本机', icon: FileCheck2 },
            { label: '生效状态', value: runtimeRevision === null ? '需刷新' : '已同步', detail: '运行中设置', icon: RefreshCw },
            { label: '安全存储', value: queries.capabilities.data?.native.keychain ? '可用' : '不可用', detail: '秘密不会回显', icon: KeyRound, tone: queries.capabilities.data?.native.keychain ? 'success' : 'warning' },
          ]} />
          <InlineNotice title="秘密字段" tone="success">已保存的秘密只显示是否配置。新值不会出现在差异、操作记录或日志中。</InlineNotice>
        </ManagementSection>

        <ManagementSection title="设置表单" description="按分组逐项调整设置；开启高级设置可显示更多选项。">
          {sections.length ? (
            <div className="configuration-editor">
              <div className="configuration-editor__fields mgmt-stack">
                <Field htmlFor="configuration-section" label="设置分组">
                  <Select
                    id="configuration-section"
                    onValueChange={setActiveSection}
                    options={sections.map((item) => ({
                      value: stringValue(item.id),
                      label: publicSectionLabel(stringValue(item.id), stringValue(item.label)),
                    }))}
                    value={stringValue(section?.id)}
                  />
                </Field>
                <div className="mgmt-list">
                  {fields.map((field) => (
                    <SettingField
                      changes={changes}
                      field={field}
                      key={stringValue(field.key)}
                      modelCatalogSupported={queries.modelCatalogSupported}
                      models={piModels}
                      onChange={(value) => updateField(field, value)}
                      settings={settings}
                      value={changes[stringValue(field.key)] ?? valueAt(settings, stringValue(field.key))}
                    />
                  ))}
                </div>
              </div>
              <div className="configuration-editor__review mgmt-stack">
                <h3 className="configuration-editor__title">待应用差异</h3>
                {diffRows.length ? (
                  <DataTable caption="配置差异" columns={[
                    { key: 'key', label: '设置项', width: '32%' },
                    { key: 'before', label: '当前' },
                    { key: 'after', label: '目标' },
                    { key: 'applyMode', label: '应用', width: '18%' },
                  ]} rows={diffRows} />
                ) : <EmptyState description="修改字段后会在这里显示差异。" icon={Settings2} title="没有待应用变更" />}
                <ManagementMutationWorkflow
                  availability={mutationBoundary.availability(
                    runtimeRevision === null
                      ? '当前设置状态尚未同步，刷新后才能预览。'
                      : hasSensitiveChanges
                        ? '秘密设置必须通过专用安全流程修改；当前差异不会发送。'
                      : diffRows.length === 0
                        ? '修改至少一个非敏感设置后才能生成服务端预览。'
                        : '',
                  )}
                  description="仅保存本次字段差异，并按应用方式刷新相关组件。"
                  draftKey={JSON.stringify({ changes: pendingChanges, runtimeRevision })}
                  mutationKey={['configuration', 'mutation', 'settings']}
                  onApply={async (preview) => parseManagementWorkReceipt(
                    await mutationBoundary.request({
                      pathId: configurationMutationPathIds.apply,
                      body: {
                        changes: preview.context.changes,
                        expectedRuntimeRevision: preview.expectedRuntimeRevision,
                        previewToken: preview.previewToken,
                        payloadSha256: preview.payloadSha256,
                        confirmText: preview.requiredConfirm,
                      },
                    }),
                    configurationMutationPathIds.apply,
                    preview.payloadSha256,
                  )}
                  onApplied={() => {
                    setChanges({});
                    void queries.settings.refetch();
                  }}
                  onPreview={async () => {
                    if (runtimeRevision === null || diffRows.length === 0) {
                      throw new Error('设置差异或当前状态已失效，请刷新后重试。');
                    }
                    const context = { changes: { ...pendingChanges } };
                    const parsed = parseManagementWorkPreview(
                      await mutationBoundary.request({
                        pathId: configurationMutationPathIds.preview,
                        body: {
                          ...context,
                          expectedRuntimeRevision: runtimeRevision,
                        },
                      }),
                      configurationMutationPathIds.apply,
                      context,
                    );
                    return {
                      ...parsed,
                      summary: {
                        ...parsed.summary,
                        title: '应用这些设置？',
                        items: previewDiffItems(diffRows),
                      },
                    };
                  }}
                  onRollback={async (receipt, preview) => parseManagementWorkReceipt(
                    await mutationBoundary.request({
                      pathId: configurationMutationPathIds.rollback,
                      body: {
                        receiptId: receipt.receiptId,
                        rollbackToken: receipt.rollbackToken,
                        payloadSha256: receipt.payloadSha256,
                        confirmText: 'rollback',
                      },
                    }),
                    configurationMutationPathIds.rollback,
                    preview.payloadSha256,
                  )}
                  onRolledBack={() => void queries.settings.refetch()}
                  risk={diffRows.some((row) => row.requiresReload) ? 'R2' : 'R1'}
                  title="应用设置差异"
                />
              </div>
            </div>
          ) : <EmptyState description="当前没有可显示的设置分组。" icon={Settings2} title="设置为空" />}
        </ManagementSection>

        <ManagementSection title="文件迁移" description="导入与恢复先校验和预览；备份只写入你在本机选择的目录。">
          <PortabilityWorkflows
            capabilities={queries.capabilities.data}
            currentSettings={settings}
            onConfigurationChanged={() => {
              void Promise.all([queries.settings.refetch(), queries.schema.refetch()]);
            }}
            transport={queries.transport}
          />
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function SettingField({
  changes,
  field,
  modelCatalogSupported,
  models,
  onChange,
  settings,
  value,
}: {
  changes: Record<string, DraftValue>;
  field: Record<string, unknown>;
  modelCatalogSupported: boolean;
  models: PiModelOption[];
  onChange: (value: DraftValue) => void;
  settings: Record<string, unknown>;
  value: unknown;
}) {
  const key = stringValue(field.key);
  const label = publicFieldLabel(key, stringValue(field.label));
  const description = publicDescription(stringValue(field.description));
  const type = stringValue(field.type, 'string');
  const secret = isSecretConfigurationField(field, key);
  const id = `configuration-${key.replace(/[^A-Za-z0-9_-]/g, '-')}`;

  if (type === 'pi-model' && !secret) {
    const available = models;
    if (!modelCatalogSupported) {
      return <div className="mgmt-list__row"><span>{label}</span><StatusBadge label="Pi 实时模型目录不可用" tone="warning" /></div>;
    }
    if (!available.length) {
      return <div className="mgmt-list__row"><span>{label}</span><StatusBadge label="Pi 当前没有可用模型" tone="warning" /></div>;
    }
    return (
      <div className="mgmt-list__row">
        <Field description={description} htmlFor={id} label={label}>
          <Select
            id={id}
            onValueChange={onChange}
            options={available.map((model) => ({
              value: model.reference,
              label: `${model.name} (${model.reference})`,
            }))}
            value={stringValue(value)}
          />
        </Field>
      </div>
    );
  }

  if (type === 'pi-thinking' && !secret) {
    const modelKey = stringValue(field.modelKey);
    const modelReference = String(changes[modelKey] ?? valueAt(settings, modelKey) ?? '');
    const selected = models.find((model) => model.reference === modelReference);
    const levels = oneShotThinkingLevels(selected);
    if (!modelCatalogSupported || !selected || !levels.length) {
      return <div className="mgmt-list__row"><span>{label}</span><StatusBadge label="请先选择 Pi 可用模型" tone="warning" /></div>;
    }
    return (
      <div className="mgmt-list__row">
        <Field description={description} htmlFor={id} label={label}>
          <Select
            id={id}
            onValueChange={onChange}
            options={levels.map((level) => ({ value: level, label: optionLabel(key, level) }))}
            value={stringValue(value)}
          />
        </Field>
      </div>
    );
  }

  if (type === 'boolean' && !secret) {
    return <div className="mgmt-list__row"><Switch checked={value === true} description={description} label={label} onCheckedChange={onChange} /></div>;
  }
  if (Array.isArray(field.options) && !secret) {
    return (
      <div className="mgmt-list__row">
        <Field description={description} htmlFor={id} label={label}>
          <Select
            id={id}
            onValueChange={onChange}
            options={field.options.map((option) => ({ value: String(option), label: optionLabel(key, String(option)) }))}
            value={stringValue(value)}
          />
        </Field>
      </div>
    );
  }
  if (['string', 'number', 'integer', 'secret', 'password'].includes(type) || secret) {
    if (secret) {
      return <div className="mgmt-list__row"><Field description="请使用上方模型账号或对应安全功能修改。" htmlFor={id} label={label}><Input disabled id={id} placeholder={configuredLabel(value)} type="password" value="" /></Field></div>;
    }
    return (
      <div className="mgmt-list__row">
        <Field
          description={description}
          htmlFor={id}
          label={label}
        >
          <Input
            autoComplete={undefined}
            id={id}
            max={typeof field.max === 'number' ? field.max : undefined}
            min={typeof field.min === 'number' ? field.min : undefined}
            onChange={(event) => {
              onChange(type === 'number' || type === 'integer' ? Number(event.target.value) : event.target.value);
            }}
            placeholder={undefined}
            step={typeof field.step === 'number' ? field.step : undefined}
            type={type === 'number' || type === 'integer' ? 'number' : 'text'}
            value={stringValue(value)}
          />
        </Field>
      </div>
    );
  }
  return <div className="mgmt-list__row"><span>{label}</span><StatusBadge label="请在对应功能中调整" tone="info" /></div>;
}

function findField(sections: Record<string, unknown>[], key: string): Record<string, unknown> {
  return sections.flatMap((section) => arrayRecords(section.fields)).find((field) => stringValue(field.key) === key) ?? {};
}

function isSecretConfigurationField(field: Record<string, unknown>, key: string): boolean {
  const type = stringValue(field.type).toLowerCase();
  return type === 'secret' || type === 'password' || isSecretConfigurationKey(key);
}

function displayDraftValue(value: unknown, field: Record<string, unknown> = {}, key = ''): string {
  if (typeof value === 'boolean') return value ? '开启' : '关闭';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value ? optionLabel(key, value, field) : '空';
  return value === undefined ? '未设置' : '结构化内容';
}

function applyModeLabel(value: string): string {
  return ({ live: '立即生效', reload: '需重新载入', restart: '需重启', restart_input_method: '重新载入输入法', redeploy_rime: '重新载入输入法', restart_sidecar: '重启后台服务', restart_predictor: '重启本机模型', next_voice_session: '下次语音使用' } as Record<string, string>)[value] ?? '应用后生效';
}

function previewDiffItems(rows: readonly { key: string; before: string; after: string; applyMode: string }[]): string[] {
  const visible = rows.slice(0, 6).map((row) => `${row.key}：${row.before} → ${row.after}（${row.applyMode}）`);
  return rows.length > visible.length
    ? [...visible, `另有 ${rows.length - visible.length} 项差异，请在上方差异表中核对。`]
    : visible;
}

const sectionLabels: Record<string, string> = { interaction: '输入体验', display: '候选窗口', rag: '知识检索', models: '模型分工', activeRag: '深度生成', memory: '记忆', context: '上下文', planning: '规划', agent: 'Agent', voice: '语音', pinyin: '拼音', privacy: '隐私与安全' };
const fieldLabels: Record<string, string> = { 'interaction.postCommit.numberKeys': '预测结果出现时的数字键', 'interaction.postCommit.tabAction': 'Tab 键行为', 'display.maxPostCommitCandidates': '续写候选数量', 'models.hot': '输入时即时预测模型', 'models.activeRag': '深度生成模型', 'models.offlineCleanup': '离线整理模型', 'activeRag.quickModel': '闪电生成模型', 'activeRag.quickThinkingLevel': '闪电生成思考', 'agent.ui.showReasoningSummary': '显示处理进度', 'managementSecurity.requireToken': '限制本机管理请求' };

function publicSectionLabel(id: string, label: string): string { return sectionLabels[id] ?? (/[\u3400-\u9fff]/.test(label) ? label : '其他设置'); }
function publicFieldLabel(key: string, label: string): string { return fieldLabels[key] ?? (label && !/pathId|schema|revision|hash|receipt|provider/i.test(label) ? publicDescription(label) : '设置项'); }
function publicDescription(value: string): string { return value.replace(/Sidecar/gi, '后台服务').replace(/SQLite FTS5/gi, '本机索引').replace(/BM25/gi, '关键词检索').replace(/Hybrid RAG/gi, '多路知识检索').replace(/Active RAG/gi, '深度生成').replace(/RAG/gi, '知识检索').replace(/fallback/gi, '备用方式').replace(/TTL/gi, '保留时间').replace(/token/gi, '容量').replace(/POST/gi, '管理请求').replace(/patch/gi, '配置'); }
function optionLabel(key: string, value: string, _field: Record<string, unknown> = {}): string { return ({ pass_through: '按原数字键处理', select_prediction: '选择对应候选', accept_top_prediction: '接受首个预测', rime_default: '保持输入法默认', disabled: '不使用', compact: '紧凑', expanded: '展开', replace_selection: '替换选中内容', insert_after_selection: '插入到选中内容后', show_only: '只显示不插入', lazy: '使用时启动', 'sichuan-mild': '四川轻度模糊音', none: '关闭', off: '关闭', minimal: '极低', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高' } as Record<string, string>)[value] ?? value; }

function parsePiModelOptions(value: unknown): PiModelOption[] {
  const envelope = asRecord(value);
  return arrayRecords(envelope.providers).flatMap((provider) => (
    arrayRecords(provider.models).map((model) => {
      const providerId = stringValue(model.provider, stringValue(provider.id));
      const id = stringValue(model.id);
      return {
        id,
        name: stringValue(model.name, id),
        provider: providerId,
        reference: providerId && id ? `${providerId}/${id}` : '',
        thinkingLevels: Array.isArray(model.thinkingLevels)
          ? model.thinkingLevels.map(String)
          : [],
      };
    })
  )).filter((model) => model.reference);
}

function oneShotThinkingLevels(model: PiModelOption | undefined): string[] {
  if (!model) return [];
  return ['minimal', 'low', 'medium', 'high', 'xhigh', 'max']
    .filter((level) => model.thinkingLevels.includes(level));
}
