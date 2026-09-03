import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BrainCircuit,
  Bot,
  ChevronRight,
  Database,
  FileCheck2,
  Gauge,
  Keyboard,
  Library,
  Mic2,
  PlugZap,
  RefreshCw,
  Search,
  ShieldCheck,
  Settings2,
  Sparkles,
  UsersRound,
} from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Button,
  Disclosure,
  EmptyState,
  Field,
  Input,
  Select,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/primitives';
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
import {
  parsePiModelCatalogOptions,
  supportedPiThinkingLevels,
  type PiModelOption,
} from '@/features/agent/model-catalog-options';
import { useProductIdentity } from '@/features/identity/product-identity';
import { SubagentSettingsPanel } from './SubagentSettingsPanel';
import type { ControlTransport } from '@/platform/transport';
import './configuration.css';

type DraftValue = string | number | boolean;

const skillScenarioIds = ['ordinary', 'room', 'trace', 'agentLab'] as const;
type SkillScenarioId = (typeof skillScenarioIds)[number];
type SkillRouting = Record<SkillScenarioId, string[]>;

type ScenarioSkill = {
  name: string;
  description: string;
};

type ScenarioSkillSnapshot = {
  revision: number;
  routing: SkillRouting;
};

type ScenarioSkillInventory = {
  items: ScenarioSkill[];
  collisions: string[];
};

const skillScenarios: readonly {
  id: SkillScenarioId;
  label: string;
  description: string;
  requiredSkill?: string;
}[] = [
  { id: 'ordinary', label: '普通对话', description: '日常一对一会话' },
  { id: 'room', label: 'Room 会话', description: '多伙伴协作', requiredSkill: 'facilitate-room' },
  { id: 'trace', label: 'Trace Agent', description: '诊断与修复', requiredSkill: 'trace-agent-diagnostics' },
  { id: 'agentLab', label: 'Agent Lab', description: '实验与评测', requiredSkill: 'agent-eval-room-optimizer' },
];

const privateSkillScenarios: Readonly<Record<string, SkillScenarioId>> = {
  'facilitate-room': 'room',
  'trace-agent-diagnostics': 'trace',
  'agent-eval-room-optimizer': 'agentLab',
};

const scenarioSkillConfigurationQueryKey = ['configuration', 'scenario-skill-routing', 'configuration'] as const;
const scenarioSkillInventoryQueryKey = ['configuration', 'scenario-skill-routing', 'inventory'] as const;

export function ConfigurationFeature() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const identity = useProductIdentity();
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
  const sections = useMemo(
    () => runtimeSettingSections(arrayRecords(asRecord(queries.schema.data).sections)),
    [queries.schema.data],
  );
  const piModels = useMemo(
    () => parsePiModelCatalogOptions(queries.modelCatalog.data).models,
    [queries.modelCatalog.data],
  );
  const [activeSection, setActiveSection] = useState('');
  const [expertMode, setExpertMode] = useState(false);
  const [settingsQuery, setSettingsQuery] = useState('');
  const [changes, setChanges] = useState<Record<string, DraftValue>>({});
  const visibleSections = useMemo(
    () => sections.filter((item) => visibleSettingFields(item, settingsQuery, expertMode).length > 0),
    [expertMode, sections, settingsQuery],
  );

  useEffect(() => {
    if (!visibleSections.some((item) => stringValue(item.id) === activeSection)) {
      setActiveSection(stringValue(visibleSections[0]?.id));
    }
  }, [activeSection, visibleSections]);

  const section = visibleSections.find((item) => stringValue(item.id) === activeSection) ?? visibleSections[0];
  const fields = visibleSettingFields(section, settingsQuery, expertMode);
  const pendingChanges = useMemo(() => Object.fromEntries(
    Object.entries(changes).filter(([key, next]) => (
      !isSecretConfigurationField(findField(sections, key), key)
      && !Object.is(valueAt(settings, key), next)
    )),
  ) as Record<string, DraftValue>, [changes, sections, settings]);
  const pendingSectionCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const key of Object.keys(pendingChanges)) {
      const owner = sections.find((item) => (
        arrayRecords(item.fields).some((field) => stringValue(field.key) === key)
      ));
      const id = stringValue(owner?.id);
      if (id) counts[id] = (counts[id] ?? 0) + 1;
    }
    return counts;
  }, [pendingChanges, sections]);
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
    ?? queries.capabilities.error
    ?? (queries.modelCatalogSupported ? queries.modelCatalog.error : null);
  const error = rawError ? new Error(publicErrorText(rawError, '无法读取本机设置，请刷新后重试。')) : null;
  const pending = queries.settings.isPending
    || queries.schema.isPending
    || queries.capabilities.isPending
    || (queries.modelCatalogSupported && queries.modelCatalog.isPending);
  const refreshing = queries.settings.isFetching
    || queries.schema.isFetching
    || queries.capabilities.isFetching
    || (queries.modelCatalogSupported && queries.modelCatalog.isFetching);
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
      const supported = supportedPiThinkingLevels(selected);
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
          <Switch checked={expertMode} label="显示高级设置" onCheckedChange={setExpertMode} />
          <Button leadingIcon={<RefreshCw size={15} />} loading={refreshing} onClick={refresh} size="small">刷新</Button>
        </>
      }
      description="调整称呼、本机模型、上下文和各项功能。普通设置可直接保存；涉及重启、部署或权限的更改会先说明影响。"
      eyebrow={`你的${identity.productName}`}
      routeId="configuration"
      title="设置"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="称呼、对话与上下文" description="这里调整全局称呼和伙伴的工作方式；输入法、语音与知识库的专属选项留在对应页面。">
          {sections.length ? (
            <>
              <div className="configuration-search">
                <Field
                  description="按你想调整的内容搜索，不需要记内部配置名。"
                  htmlFor="configuration-search"
                  label="查找设置"
                >
                  <Input
                    id="configuration-search"
                    onChange={(event) => setSettingsQuery(event.target.value)}
                    placeholder="例如：模型、记忆、上下文或隐私"
                    type="search"
                    value={settingsQuery}
                  />
                </Field>
              </div>
              {visibleSections.length ? (
                <div className="configuration-editor">
              <nav aria-label="运行设置分组" className="configuration-section-nav">
                {visibleSections.map((item) => {
                  const id = stringValue(item.id);
                  const meta = runtimeSectionMeta[id] ?? runtimeSectionMeta.other;
                  const Icon = meta.icon;
                  const active = id === stringValue(section?.id);
                  const pendingInSection = pendingSectionCounts[id] ?? 0;
                  return (
                    <button
                      aria-current={active ? 'page' : undefined}
                      key={id}
                      onClick={() => setActiveSection(id)}
                      type="button"
                    >
                      <Icon size={16} />
                      <span>
                        <strong>{publicSectionLabel(id, stringValue(item.label))}</strong>
                        <small>{meta.description}</small>
                      </span>
                      {pendingInSection ? (
                        <em aria-label={`${pendingInSection} 项未保存`} className="configuration-section-nav__pending">
                          {pendingInSection}
                        </em>
                      ) : null}
                    </button>
                  );
                })}
              </nav>
              <div className="configuration-editor__fields mgmt-stack">
                <header className="configuration-editor__heading">
                  <span>
                    <strong>{publicSectionLabel(stringValue(section?.id), stringValue(section?.label))}</strong>
                    <small>{(runtimeSectionMeta[stringValue(section?.id)] ?? runtimeSectionMeta.other).description}</small>
                  </span>
                  <StatusBadge
                    label={runtimeRevision === null
                      ? '等待刷新'
                      : diffRows.length
                        ? `共 ${diffRows.length} 项未保存`
                        : '没有未保存的更改'}
                    tone={runtimeRevision === null ? 'warning' : diffRows.length ? 'info' : 'success'}
                  />
                </header>
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
              <div className="configuration-editor__review mgmt-stack" data-has-changes={diffRows.length > 0 || hasSensitiveChanges}>
                <header className="configuration-editor__review-heading">
                  <h3 className="configuration-editor__title">保存设置</h3>
                  {diffRows.length ? (
                    <Button onClick={() => setChanges({})} size="small" variant="quiet">放弃更改</Button>
                  ) : null}
                </header>
                {diffRows.length ? (
                  <>
                    <p className="configuration-review-consequence">{reviewConsequenceSummary(diffRows)}</p>
                    <DataTable caption="准备保存的设置" columns={[
                      { key: 'key', label: '设置项', width: '32%' },
                      { key: 'before', label: '当前' },
                      { key: 'after', label: '更改后' },
                      { key: 'applyMode', label: '生效方式', width: '18%' },
                    ]} rows={diffRows} />
                  </>
                ) : <p className="mgmt-muted configuration-editor__empty-review">更改设置后，可以在这里直接保存；需要重启、部署或权限的更改会先说明需要采取的操作。</p>}
                <ManagementMutationWorkflow
                  availability={mutationBoundary.availability(
                    runtimeRevision === null
                      ? '当前设置还没有刷新完成，请刷新后再保存。'
                      : hasSensitiveChanges
                        ? '账号密钥请使用下方「模型账号」的安全入口修改；这里不会发送密钥。'
                      : diffRows.length === 0
                        ? '调整任一设置后，就可以在这里核对并保存。'
                        : '',
                  )}
                  description="普通设置会直接保存；涉及重启、重新部署或权限的更改会在保存前说明影响。未列出的设置不会改变。"
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
                      throw new Error('准备保存的内容已经变化，请刷新后重试。');
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
                        title: '保存这些设置？',
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
                  title="保存这些设置"
                />
              </div>
                </div>
              ) : (
                <EmptyState
                  action={<Button onClick={() => setSettingsQuery('')} size="small">清除搜索</Button>}
                  description="换一个更简单的关键词，或清除搜索查看全部设置。"
                  icon={Search}
                  title="没有找到相关设置"
                />
              )}
            </>
          ) : <EmptyState description="当前没有可显示的设置分组。" icon={Settings2} title="设置为空" />}
        </ManagementSection>

        <ScenarioSkillSettings
          routeIds={queries.capabilities.data?.routeIds ?? []}
          transport={queries.transport}
        />

        <PiProviderCredentials />
        <SubagentSettingsPanel highlighted={searchParams.get('section') === 'subagents'} />

        <ManagementSection description="输入法、语音、记忆等功能的专属选项在各自页面调整，从这里直接进入。" title="功能设置">
          <nav aria-label="功能设置入口" className="configuration-destinations">
            {settingDestinations.map((destination) => {
              const Icon = destination.icon;
              return <button key={destination.path} onClick={() => navigate(destination.path)} type="button"><Icon size={18} /><span><strong>{destination.label}</strong><small>{destination.detail}</small></span><ChevronRight size={15} /></button>;
            })}
          </nav>
        </ManagementSection>

        <ManagementSection title="迁移与恢复">
          <Disclosure
            className="configuration-transfer"
            summary={<>
              <span><strong>导入、备份与恢复</strong><small>平时无需打开；执行前会先列出具体影响</small></span>
              <ChevronRight size={16} />
            </>}
          >
            <PortabilityWorkflows
              capabilities={queries.capabilities.data}
              currentSettings={settings}
              onConfigurationChanged={() => {
                void Promise.all([queries.settings.refetch(), queries.schema.refetch()]);
              }}
              transport={queries.transport}
            />
          </Disclosure>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function ScenarioSkillSettings({
  routeIds,
  transport,
}: {
  routeIds: readonly string[];
  transport: ControlTransport;
}) {
  const queryClient = useQueryClient();
  const [activeScenario, setActiveScenario] = useState<SkillScenarioId>('ordinary');
  const [draftRouting, setDraftRouting] = useState<Partial<SkillRouting>>({});
  const [savedScenario, setSavedScenario] = useState<SkillScenarioId | null>(null);
  const supportedRoutes = useMemo(() => new Set(routeIds), [routeIds]);
  const readsSupported = supportedRoutes.has('agent.configuration.get')
    && supportedRoutes.has('agent.extensions.skills.list');
  const updateSupported = supportedRoutes.has('agent.configuration.update');
  const configurationQuery = useQuery({
    queryKey: scenarioSkillConfigurationQueryKey,
    queryFn: async ({ signal }) => requireScenarioSkillSnapshot(
      await transport.request({ pathId: 'agent.configuration.get', signal }),
    ),
    enabled: readsSupported,
    retry: false,
    staleTime: 5_000,
    refetchOnReconnect: 'always',
  });
  const inventoryQuery = useQuery({
    queryKey: scenarioSkillInventoryQueryKey,
    queryFn: async ({ signal }) => requireScenarioSkillInventory(
      await transport.request({ pathId: 'agent.extensions.skills.list', signal }),
    ),
    enabled: readsSupported,
    retry: false,
    staleTime: 5_000,
    refetchOnReconnect: 'always',
  });
  const saveMutation = useMutation({
    mutationFn: async (input: {
      scenario: SkillScenarioId;
      names: string[];
      expectedRevision: number;
    }) => {
      if (!updateSupported) {
        throw new Error('当前 Runtime 没有公布技能加载保存能力，本次修改未发送。');
      }
      const response = await transport.request({
        pathId: 'agent.configuration.update',
        body: {
          expectedRevision: input.expectedRevision,
          changes: {
            [`skillRouting.${input.scenario}`]: input.names,
          },
          updatedBy: 'settings-ui',
        },
      });
      return {
        scenario: input.scenario,
        snapshot: requireScenarioSkillSnapshot(response),
      };
    },
    onSuccess: ({ scenario, snapshot }) => {
      queryClient.setQueryData(scenarioSkillConfigurationQueryKey, snapshot);
      setDraftRouting((current) => {
        const next = { ...current };
        delete next[scenario];
        return next;
      });
      setSavedScenario(scenario);
    },
  });

  const resetSaveFeedback = () => {
    saveMutation.reset();
    setSavedScenario(null);
  };
  const retryReads = () => {
    void Promise.all([configurationQuery.refetch(), inventoryQuery.refetch()]);
  };

  return (
    <ManagementSection
      description="为不同会话选择 Runtime 在开始时加载的 Skill。专属 Skill 只在所属场景出现，并会保持锁定。"
      title="技能加载"
    >
      {!readsSupported ? (
        <InlineNotice title="技能加载暂不可用" tone="warning">
          <p>当前 Runtime 没有公布技能配置与清单读取能力，因此不会猜测或发送任何设置。</p>
        </InlineNotice>
      ) : configurationQuery.isPending || inventoryQuery.isPending ? (
        <p aria-live="polite" className="configuration-skill-routing__state" role="status">
          正在读取场景配置与可用 Skill…
        </p>
      ) : configurationQuery.error || inventoryQuery.error ? (
        <InlineNotice title="技能加载读取失败" tone="danger">
          <p>{publicErrorText(
            configurationQuery.error ?? inventoryQuery.error,
            '无法读取技能加载设置；现有配置没有改变。',
          )}</p>
          <Button
            loading={configurationQuery.isFetching || inventoryQuery.isFetching}
            onClick={retryReads}
            size="small"
            variant="secondary"
          >
            重试
          </Button>
        </InlineNotice>
      ) : configurationQuery.data && inventoryQuery.data ? (
        <div className="configuration-skill-routing">
          {!updateSupported ? (
            <InlineNotice title="当前只能查看" tone="warning">
              <p>Runtime 没有公布技能加载更新能力；开关已锁定，不会发送修改。</p>
            </InlineNotice>
          ) : null}
          {inventoryQuery.data.collisions.length ? (
            <InlineNotice title="已隐藏重名 Skill" tone="warning">
              <p>
                这些名称在清单中出现多次，无法确认唯一来源，因此不会作为可选项显示，也不会被新加入配置：
                {' '}{inventoryQuery.data.collisions.join('、')}
              </p>
            </InlineNotice>
          ) : null}
          <Tabs
            onValueChange={(value) => {
              setActiveScenario(value as SkillScenarioId);
              resetSaveFeedback();
            }}
            value={activeScenario}
          >
            <TabsList aria-label="技能加载场景" className="configuration-skill-routing__tabs">
              {skillScenarios.map((scenario) => (
                <TabsTrigger
                  disabled={saveMutation.isPending}
                  key={scenario.id}
                  value={scenario.id}
                >
                  <strong>{scenario.label}</strong>
                  <small>{scenario.description}</small>
                </TabsTrigger>
              ))}
            </TabsList>
            {skillScenarios.map((scenario) => {
              const availableSkills = scenarioSkillItems(inventoryQuery.data.items, scenario.id);
              const requiredAvailable = !scenario.requiredSkill
                || availableSkills.some((skill) => skill.name === scenario.requiredSkill);
              const baseline = scenarioSkillSelection(
                configurationQuery.data.routing[scenario.id],
                scenario.requiredSkill,
              );
              const selected = scenarioSkillSelection(
                draftRouting[scenario.id] ?? baseline,
                scenario.requiredSkill,
              );
              const visibleSelectedCount = availableSkills.filter(
                (skill) => selected.includes(skill.name),
              ).length;
              const unavailableSelectedCount = selected.length - visibleSelectedCount;
              const selectedStatus = `${visibleSelectedCount}/${availableSkills.length} 已加载${
                unavailableSelectedCount
                  ? ` · ${unavailableSelectedCount} 个暂不可用`
                  : ''
              }`;
              const dirty = !sameStringArray(selected, baseline);
              const saving = saveMutation.isPending
                && saveMutation.variables?.scenario === scenario.id;
              const saveFailed = Boolean(
                saveMutation.error
                && saveMutation.variables?.scenario === scenario.id,
              );

              return (
                <TabsContent
                  className="configuration-skill-routing__panel"
                  key={scenario.id}
                  value={scenario.id}
                >
                  <header className="configuration-skill-routing__heading">
                    <span>
                      <strong>{scenario.label}</strong>
                      <small>{scenario.description} · 选择这个场景开始时可加载的 Skill</small>
                    </span>
                    <StatusBadge
                      label={selectedStatus}
                      tone={dirty ? 'info' : 'neutral'}
                    />
                  </header>
                  {!requiredAvailable ? (
                    <InlineNotice title="必需 Skill 不在清单中" tone="danger">
                      <p>
                        {scenario.requiredSkill} 是此场景的运行基础。找到并启用它之前，本场景不会保存。
                      </p>
                    </InlineNotice>
                  ) : null}
                  {unavailableSelectedCount ? (
                    <InlineNotice title="保留暂不可用的 Skill" tone="warning">
                      <p>
                        {unavailableSelectedCount} 个已配置名称当前不在唯一可用清单中。本次保存会原样保留，避免修改其他开关时意外删除。
                      </p>
                    </InlineNotice>
                  ) : null}
                  {scenario.id === 'agentLab' ? (
                    <p className="configuration-skill-routing__inheritance">
                      Agent Lab 的实际执行会话属于 Room；Runtime 还会强制叠加 Room 的 facilitate-room，但不会把它写入 Agent Lab 专属列表。
                    </p>
                  ) : null}
                  {availableSkills.length ? (
                    <div
                      aria-label={`${scenario.label} 可用 Skill`}
                      className="configuration-skill-routing__list"
                      role="group"
                    >
                      {availableSkills.map((skill) => {
                        const required = skill.name === scenario.requiredSkill;
                        const checked = required || selected.includes(skill.name);
                        return (
                          <Switch
                            checked={checked}
                            description={[
                              skill.description || '已安装，可用于这个场景。',
                              required ? '此场景必需，始终加载。' : '',
                            ].filter(Boolean).join(' ')}
                            disabled={required
                              || !updateSupported
                              || saveMutation.isPending
                              || !requiredAvailable}
                            key={skill.name}
                            label={`${skill.name}：${required
                              ? '必需并已加载'
                              : checked ? '已加载' : '未加载'}`}
                            onCheckedChange={(nextChecked) => {
                              resetSaveFeedback();
                              const next = nextChecked
                                ? [...new Set([...selected, skill.name])].sort(compareSkillNames)
                                : selected.filter((name) => name !== skill.name);
                              setDraftRouting((current) => {
                                const nextDraft = { ...current };
                                if (sameStringArray(next, baseline)) {
                                  delete nextDraft[scenario.id];
                                } else {
                                  nextDraft[scenario.id] = next;
                                }
                                return nextDraft;
                              });
                            }}
                          />
                        );
                      })}
                    </div>
                  ) : (
                    <EmptyState
                      description="安装并启用 Skill 后，它们会出现在这个场景中。"
                      headingLevel={3}
                      icon={Sparkles}
                      title="没有可加载的 Skill"
                    />
                  )}
                  <footer className="configuration-skill-routing__actions">
                    <p>
                      保存会重新启动并同步 Runtime。若有对话正在生成回复，当前回合可能阻止保存；请等待结束后重试。
                    </p>
                    <Button
                      aria-label={`保存 ${scenario.label} 技能加载`}
                      disabled={!dirty || !updateSupported || !requiredAvailable}
                      loading={saving}
                      onClick={() => {
                        resetSaveFeedback();
                        saveMutation.mutate({
                          scenario: scenario.id,
                          names: selected,
                          expectedRevision: configurationQuery.data.revision,
                        });
                      }}
                      size="small"
                      variant="primary"
                    >
                      保存此场景
                    </Button>
                  </footer>
                  {saveFailed ? (
                    <InlineNotice title={`${scenario.label} 技能加载未保存`} tone="danger">
                      <p>{publicErrorText(
                        saveMutation.error,
                        '保存被阻止；如果有对话正在回复，请等待当前回合结束后重试。',
                      )}</p>
                    </InlineNotice>
                  ) : null}
                  {savedScenario === scenario.id ? (
                    <InlineNotice title={`${scenario.label} 技能加载已保存`} tone="success">
                      <p>设置已提交，Runtime 正在重新启动并同步。</p>
                    </InlineNotice>
                  ) : null}
                </TabsContent>
              );
            })}
          </Tabs>
        </div>
      ) : null}
    </ManagementSection>
  );
}

function requireScenarioSkillSnapshot(value: unknown): ScenarioSkillSnapshot {
  const snapshot = asRecord(asRecord(value).configuration);
  const configuration = asRecord(snapshot.configuration);
  const routing = asRecord(configuration.skillRouting);
  const keys = Object.keys(routing);
  if (
    typeof snapshot.revision !== 'number'
    || !Number.isInteger(snapshot.revision)
    || snapshot.revision < 1
    || keys.length !== skillScenarioIds.length
    || skillScenarioIds.some((scenario) => !Object.hasOwn(routing, scenario))
  ) {
    throw new Error('Runtime 返回的技能加载配置不完整；不会猜测或修改现有设置。');
  }

  const parsed = {} as SkillRouting;
  for (const scenario of skillScenarioIds) {
    const route = routing[scenario];
    if (
      !Array.isArray(route)
      || route.some((name) => typeof name !== 'string' || !name.trim())
    ) {
      throw new Error('Runtime 返回的技能加载配置格式无效；不会猜测或修改现有设置。');
    }
    const names = route.map((name) => name.trim());
    if (new Set(names).size !== names.length) {
      throw new Error('Runtime 返回的技能加载配置包含重复名称；不会发送修改。');
    }
    parsed[scenario] = names;
  }
  return { revision: snapshot.revision, routing: parsed };
}

function requireScenarioSkillInventory(value: unknown): ScenarioSkillInventory {
  const envelope = asRecord(value);
  if (
    envelope.schemaVersion !== 'rag-ime.skill-inventory.v1'
    || envelope.ok !== true
    || envelope.runtimeAvailable !== true
    || !Array.isArray(envelope.items)
  ) {
    throw new Error('Runtime Skill 清单当前不可用；不会用空清单覆盖现有配置。');
  }

  const byName = new Map<string, ScenarioSkill[]>();
  for (const item of arrayRecords(envelope.items)) {
    const name = stringValue(item.name);
    if (!name || item.installed !== true || item.enabled === false) continue;
    const entries = byName.get(name) ?? [];
    entries.push({
      name,
      description: stringValue(item.description),
    });
    byName.set(name, entries);
  }
  const collisions = [...byName.entries()]
    .filter(([, items]) => items.length > 1)
    .map(([name]) => name)
    .sort(compareSkillNames);
  const items = [...byName.entries()]
    .filter(([, matches]) => matches.length === 1)
    .map(([, matches]) => matches[0]!)
    .sort((left, right) => compareSkillNames(left.name, right.name));
  return { collisions, items };
}

function scenarioSkillItems(
  items: readonly ScenarioSkill[],
  scenario: SkillScenarioId,
): ScenarioSkill[] {
  return items.filter((item) => (
    privateSkillScenarios[item.name] === undefined
    || privateSkillScenarios[item.name] === scenario
  ));
}

function scenarioSkillSelection(
  configuredNames: readonly string[],
  requiredSkill?: string,
): string[] {
  const selected = new Set(configuredNames);
  if (requiredSkill) selected.add(requiredSkill);
  return [...selected].sort(compareSkillNames);
}

function compareSkillNames(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function sameStringArray(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length
    && left.every((value, index) => value === right[index]);
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
  const type = stringValue(field.type, 'string');
  const secret = isSecretConfigurationField(field, key);
  const id = `configuration-${key.replace(/[^A-Za-z0-9_-]/g, '-')}`;
  // Consequence-first: a field that will not take effect immediately says so
  // next to its control, before the person edits, not only in the save diff.
  const consequence = secret ? '' : fieldConsequenceLabel(stringValue(field.applyMode, 'live'));
  const description = withConsequence(publicDescription(stringValue(field.description)), consequence);
  const changed = !secret
    && key in changes
    && !Object.is(valueAt(settings, key), changes[key]);
  const rowProps = {
    className: 'mgmt-list__row',
    'data-changed': changed || undefined,
  } as const;

  if (type === 'pi-model' && !secret) {
    const available = models;
    if (!modelCatalogSupported) {
      return <div {...rowProps}><span>{label}</span><StatusBadge label="暂时无法读取模型列表" tone="warning" /></div>;
    }
    if (!available.length) {
      return <div {...rowProps}><span>{label}</span><StatusBadge label="当前没有可用模型" tone="warning" /></div>;
    }
    return (
      <div {...rowProps}>
        <Field description={description} htmlFor={id} label={label}>
          <Select
            id={id}
            onValueChange={onChange}
            options={available.map((model) => ({
              value: model.reference,
              label: model.name,
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
    const levels = supportedPiThinkingLevels(selected);
    if (!modelCatalogSupported || !selected || !levels.length) {
      return <div {...rowProps}><span>{label}</span><StatusBadge label="请先选择支持思考的模型" tone="warning" /></div>;
    }
    return (
      <div {...rowProps}>
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
    return <div {...rowProps}><Switch checked={value === true} description={description} label={label} onCheckedChange={onChange} /></div>;
  }
  if (Array.isArray(field.options) && !secret) {
    return (
      <div {...rowProps}>
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
      return <div className="mgmt-list__row"><Field description="请使用下方模型账号或对应安全功能修改。" htmlFor={id} label={label}><Input disabled id={id} placeholder={configuredLabel(value)} type="password" value="" /></Field></div>;
    }
    return (
      <div {...rowProps}>
        <Field
          description={description}
          htmlFor={id}
          label={label}
        >
          <Input
            autoComplete={undefined}
            id={id}
            maxLength={typeof field.maxLength === 'number' ? field.maxLength : undefined}
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

function withConsequence(description: string, consequence: string): ReactNode {
  if (!consequence) return description;
  return (
    <>
      {description}
      <em className="configuration-field-consequence">{consequence}</em>
    </>
  );
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
  return ({ live: '立即生效', reload: '重新载入后生效', restart: '重新启动后生效', restart_input_method: '重新载入输入法', redeploy_rime: '重新载入输入法', restart_sidecar: '重启本机补全服务', restart_agent_gateway: '重启对话服务', restart_predictor: '重启本机模型', next_voice_session: '下次语音输入时生效' } as Record<string, string>)[value] ?? '保存后生效';
}

function fieldConsequenceLabel(value: string): string {
  if (value === 'live') return '';
  return ({
    reload: '保存后需重新载入',
    restart: '保存后需重新启动',
    restart_input_method: '保存后需重新载入输入法',
    redeploy_rime: '保存后需重新载入输入法',
    restart_sidecar: '保存后需重启本机补全服务',
    restart_agent_gateway: '保存后需重启对话服务',
    restart_predictor: '保存后需重启本机模型',
    next_voice_session: '下次语音输入时生效',
  } as Record<string, string>)[value] ?? '保存后按提示生效';
}

function reviewConsequenceSummary(
  rows: readonly { requiresReload: boolean; applyMode: string }[],
): string {
  const deferred = rows.filter((row) => row.requiresReload);
  if (!deferred.length) return `这 ${rows.length} 项更改保存后立即生效。`;
  const followUps = [...new Set(deferred.map((row) => row.applyMode))].join('、');
  if (deferred.length === rows.length) {
    return `这 ${rows.length} 项更改保存后不会立即生效（${followUps}）。`;
  }
  return `共 ${rows.length} 项更改：${rows.length - deferred.length} 项立即生效，其余 ${deferred.length} 项（${followUps}）。`;
}

function previewDiffItems(rows: readonly { key: string; before: string; after: string; applyMode: string }[]): string[] {
  const visible = rows.slice(0, 6).map((row) => `${row.key}：${row.before} → ${row.after}（${row.applyMode}）`);
  return rows.length > visible.length
    ? [...visible, `另有 ${rows.length - visible.length} 项更改，请在上方列表中核对。`]
    : visible;
}

const sectionLabels: Record<string, string> = { identity: '称呼与外观', interaction: '输入体验', display: '候选窗口', rag: '知识检索', models: '模型分工', activeRag: '深度生成', memory: '记忆', context: '上下文', planning: '任务与规划', agent: '伙伴对话', voice: '语音', pinyin: '拼音', privacy: '隐私与安全' };
const fieldLabels: Record<string, string> = {
  'interaction.postCommit.numberKeys': '预测结果出现时的数字键',
  'interaction.postCommit.tabAction': 'Tab 键行为',
  'display.maxPostCommitCandidates': '续写候选数量',
  'models.hot': '本机预测配置',
  'activeRag.quickModel': '闪电生成模型',
  'activeRag.quickThinkingLevel': '闪电生成推理强度',
  'memory.automaticOrganization.thinkingLevel': '自动整理推理强度',
  'memory.dreaming.model': '后台整理模型',
  'memory.dreaming.thinkingLevel': '后台整理推理强度',
  'memory.recall.detailLevel': '联想内容详略',
  'memory.recall.timelineEnabled': '参考时间线',
  'planning.injectIntoContext': '向伙伴提供当前任务',
  'agent.pi.enabled': '启用伙伴对话',
  'agent.pi.idleTimeoutSeconds': '伙伴空闲休息时间',
  'privacy.redactSecrets': '在诊断信息中隐藏敏感内容',
  'managementSecurity.requireToken': '限制本机管理请求',
};

function publicSectionLabel(id: string, label: string): string { return sectionLabels[id] ?? (/[\u3400-\u9fff]/.test(label) ? label : '其他设置'); }
function publicFieldLabel(key: string, label: string): string { return fieldLabels[key] ?? (label && !/pathId|schema|revision|hash|receipt|provider/i.test(label) ? publicDescription(label) : '设置项'); }
function publicDescription(value: string): string {
  return value
    .replace(/Sidecar/gi, '本机补全服务')
    .replace(/SQLite FTS5/gi, '本机索引')
    .replace(/BM25/gi, '关键词检索')
    .replace(/Hybrid RAG/gi, '多路知识检索')
    .replace(/Active RAG/gi, '深度生成')
    .replace(/RAG/gi, '知识检索')
    .replace(/\bAgent\b/gi, '伙伴')
    .replace(/\bSession\b/gi, '对话')
    .replace(/\bRoom\b/gi, '协作空间')
    .replace(/\bMemory\b/gi, '记忆')
    .replace(/召回/g, '联想')
    .replace(/fallback/gi, '备用方式')
    .replace(/TTL/gi, '保留时间')
    .replace(/token/gi, '容量')
    .replace(/POST/gi, '管理请求')
    .replace(/patch/gi, '配置');
}
function optionLabel(key: string, value: string, _field: Record<string, unknown> = {}): string { return ({ pass_through: '按原数字键处理', select_prediction: '选择对应候选', accept_top_prediction: '接受首个预测', rime_default: '保持输入法默认', disabled: '不使用', compact: '紧凑', expanded: '展开', replace_selection: '替换选中内容', insert_after_selection: '插入到选中内容后', show_only: '只显示不插入', lazy: '使用时启动', 'sichuan-mild': '四川轻度模糊音', none: '关闭', off: '关闭', minimal: '极低', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高' } as Record<string, string>)[value] ?? value; }

const dedicatedSettingSections = new Set([
  'interaction',
  'display',
  'pinyin',
  'voice',
  'knowledgeLibrary',
]);

const runtimeSectionOrder = ['identity', 'agent', 'context', 'rag', 'memory', 'models', 'activeRag', 'planning', 'privacy'] as const;

const runtimeSectionMeta: Record<string, { description: string; icon: typeof Bot }> = {
  identity: { description: '应用名称、通用伙伴称呼和侧栏短句', icon: Sparkles },
  agent: { description: '伙伴何时启动、多久后休息，以及是否继续上次对话', icon: Bot },
  context: { description: '近期输入、上下文容量与时间表达', icon: Gauge },
  rag: { description: '检索通道与响应时间预算', icon: Search },
  memory: { description: '记忆保留、整理与按需联想', icon: Database },
  models: { description: '输入时快速建议与后台整理模型', icon: BrainCircuit },
  activeRag: { description: '闪电生成与显式深度生成', icon: Sparkles },
  planning: { description: '任务状态、计划引用与完成识别', icon: FileCheck2 },
  privacy: { description: '远程连接、诊断记录与本机保护', icon: ShieldCheck },
  other: { description: '不常用的运行设置', icon: Settings2 },
};

function visibleSettingFields(
  section: Record<string, unknown> | undefined,
  query: string,
  expertMode: boolean,
): Record<string, unknown>[] {
  const fields = arrayRecords(section?.fields).filter((field) => expertMode || field.expert !== true);
  const needle = query.trim().toLocaleLowerCase('zh-CN');
  if (!needle) return fields;
  const sectionId = stringValue(section?.id);
  const sectionText = [
    publicSectionLabel(sectionId, stringValue(section?.label)),
    (runtimeSectionMeta[sectionId] ?? runtimeSectionMeta.other).description,
  ].join(' ').toLocaleLowerCase('zh-CN');
  const matchingFields = fields.filter((field) => {
    const key = stringValue(field.key);
    const text = [
      publicFieldLabel(key, stringValue(field.label)),
      publicDescription(stringValue(field.description)),
    ].join(' ').toLocaleLowerCase('zh-CN');
    return text.includes(needle);
  });
  if (matchingFields.length) return matchingFields;
  return sectionText.includes(needle) ? fields : [];
}

function runtimeSettingSections(sections: Record<string, unknown>[]): Record<string, unknown>[] {
  const order = new Map<string, number>(runtimeSectionOrder.map((id, index) => [id, index]));
  return sections
    .filter((item) => !dedicatedSettingSections.has(stringValue(item.id)))
    .filter((item) => arrayRecords(item.fields).length > 0)
    .sort((left, right) => (
      (order.get(stringValue(left.id)) ?? runtimeSectionOrder.length)
      - (order.get(stringValue(right.id)) ?? runtimeSectionOrder.length)
    ));
}

const settingDestinations = [
  { path: '/input', label: '输入法与词库', detail: '输入体验、候选窗口和个人词库', icon: Keyboard },
  { path: '/voice', label: '语音输入', detail: '识别方式、快捷键与热词', icon: Mic2 },
  { path: '/memory', label: '我的记忆', detail: '事实、关系和待确认内容', icon: Database },
  { path: '/knowledge', label: '知识库', detail: '材料、检索与图谱', icon: Library },
  { path: '/plugins', label: '插件管理', detail: '技能、工具、扩展与安装状态', icon: PlugZap },
  { path: '/configuration?section=subagents', label: '子 Agent', detail: '模板、上下文、工具与权限边界', icon: UsersRound },
  { path: '/rooms', label: '多人协作', detail: '伙伴、任务和交接', icon: UsersRound },
] as const;
