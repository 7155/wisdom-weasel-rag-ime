import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { Button, EmptyState, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/primitives';
import { InlineNotice, ManagementSection, StatusBadge, arrayRecords, asRecord, publicErrorText, stringValue } from '@/features/overview/management-ui';
import type { ControlTransport } from '@/platform/transport';
import './configuration.css';

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

export function ScenarioSkillSettings({
  routeIds,
  transport,
  active = true,
}: {
  routeIds: readonly string[];
  transport: ControlTransport;
  active?: boolean;
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
    enabled: readsSupported && active,
    retry: false,
    staleTime: 5_000,
    refetchOnReconnect: 'always',
  });
  const inventoryQuery = useQuery({
    queryKey: scenarioSkillInventoryQueryKey,
    queryFn: async ({ signal }) => requireScenarioSkillInventory(
      await transport.request({ pathId: 'agent.extensions.skills.list', signal }),
    ),
    enabled: readsSupported && active,
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
              const selectedStatus = `${visibleSelectedCount}/${availableSkills.length} 已选择${
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
                              required ? '此场景必需。' : '',
                            ].filter(Boolean).join(' ')}
                            disabled={required
                              || !updateSupported
                              || saveMutation.isPending
                              || !requiredAvailable}
                            key={skill.name}
                            label={`${skill.name}：${required
                              ? '必需'
                              : checked ? '新对话加载' : '不加载'}`}
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
                      保存后用于此场景的新对话。已有对话保留创建时的加载快照，可以继续当前任务。
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
                        '设置尚未保存，当前选择已保留。请重新读取配置后重试。',
                      )}</p>
                    </InlineNotice>
                  ) : null}
                  {savedScenario === scenario.id ? (
                    <InlineNotice title={`${scenario.label} 技能加载已保存`} tone="success">
                      <p>已保存，新对话将使用这份选择；当前任务会继续执行。</p>
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
