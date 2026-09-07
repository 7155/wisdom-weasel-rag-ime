import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { ChevronRight, Sparkles } from 'lucide-react';
import { Button, Disclosure, EmptyState, Field, Input, Select, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/primitives';
import { InlineNotice, ManagementSection, StatusBadge, arrayRecords, asRecord, publicErrorText, stringValue } from '@/features/overview/management-ui';
import type { ControlTransport } from '@/platform/transport';
import './configuration.css';

const skillScenarioIds = ['ordinary', 'room', 'trace', 'agentLab'] as const;
type SkillScenarioId = (typeof skillScenarioIds)[number];
type SkillRouting = Record<SkillScenarioId, string[]>;

type ScenarioSkill = {
  skillId: string;
  sourceKind: string;
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
  const [skillQuery, setSkillQuery] = useState('');
  const [skillFilter, setSkillFilter] = useState('all');
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
      description="选择每类新对话可以加载的技能。场景必需技能固定加载，其余可自行选择；已有对话保持原来的设置。"
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
              const needle = skillQuery.trim().toLocaleLowerCase('zh-CN');
              const filteredSkills = availableSkills.filter((skill) => {
                const presentation = scenarioSkillPresentation(skill);
                const checked = selected.includes(skill.name);
                const required = skill.name === scenario.requiredSkill;
                return (!needle || [skill.name, presentation.name, presentation.description, skill.description]
                  .join(' ').toLocaleLowerCase('zh-CN').includes(needle))
                  && (skillFilter === 'all' || (skillFilter === 'selected' && checked)
                    || (skillFilter === 'unselected' && !checked) || (skillFilter === 'required' && required));
              });
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
                  <div className="configuration-skill-routing__filters">
                    <Field label="搜索技能" htmlFor={`scenario-skill-search-${scenario.id}`}>
                      <Input id={`scenario-skill-search-${scenario.id}`} value={skillQuery}
                        onChange={(event) => setSkillQuery(event.target.value)} placeholder="名称、用途或技能标识" />
                    </Field>
                    <Field label="筛选技能" htmlFor={`scenario-skill-filter-${scenario.id}`}>
                      <Select id={`scenario-skill-filter-${scenario.id}`} value={skillFilter} onValueChange={setSkillFilter}
                        options={[{ value: 'all', label: '全部技能' }, { value: 'selected', label: '已选择' },
                          { value: 'unselected', label: '未选择' }, { value: 'required', label: '场景必需' }]} />
                    </Field>
                  </div>
                  <div className="configuration-skill-routing__count" role="status"><span>显示 {filteredSkills.length} / {availableSkills.length} 项技能</span>
                    <StatusBadge label={`${selectedStatus}${dirty ? ' · 有未保存更改' : ''}`} tone={dirty ? 'info' : 'neutral'} />
                  </div>
                  {filteredSkills.length ? (
                    <div
                      aria-label={`${scenario.label} 可用 Skill`}
                      className="configuration-skill-routing__list"
                      role="group"
                    >
                      {filteredSkills.map((skill) => {
                        const presentation = scenarioSkillPresentation(skill);
                        const required = skill.name === scenario.requiredSkill;
                        const checked = required || selected.includes(skill.name);
                        return (
                          <article aria-label={presentation.name} className="configuration-skill-routing__row" key={skill.name}>
                          <Switch
                            checked={checked}
                            description={[
                              presentation.description || '已安装，可用于这个场景。',
                              required ? '此场景必需。' : '',
                            ].filter(Boolean).join(' ')}
                            disabled={required
                              || !updateSupported
                              || saveMutation.isPending
                              || !requiredAvailable}
                            label={`${presentation.name}：${required
                              ? '场景必需'
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
                          <ScenarioSkillInstructions skill={skill} transport={transport} active={active}
                            supported={supportedRoutes.has('agent.extensions.skills.get')} />
                          </article>
                        );
                      })}
                    </div>
                  ) : (
                    <EmptyState
                      action={availableSkills.length ? <Button size="small" variant="quiet" onClick={() => {
                        setSkillQuery(''); setSkillFilter('all');
                      }}>清除筛选</Button> : undefined}
                      description={availableSkills.length ? '换一个关键词或筛选条件；已有选择会保留。' : '安装并启用技能后，它们会出现在这个场景中。'}
                      headingLevel={3}
                      icon={Sparkles}
                      title={availableSkills.length ? '没有匹配的技能' : '没有可加载的技能'}
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
      skillId: stringValue(item.skillId, name),
      sourceKind: stringValue(item.sourceKind),
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


const bundledSkillPresentation: Readonly<Record<string, { name: string; description: string }>> = {
  'agent-eval-room-optimizer': { name: '实验执行', description: '按实验约定评测 Agent、工具、流程、检索或记忆。' },
  'agent-lab-project': { name: 'Lab 项目交付', description: '从业务描述和材料出发，制作适合项目的成果与界面。' },
  'alignment-and-decision': { name: '需求与决策', description: '澄清影响范围、验收和成本等关键选择。' },
  'bootstrap-project-context': { name: '项目上下文', description: '为缺少可靠入口的项目建立或补齐根目录说明。' },
  'ego-browser': { name: '网页操作', description: '使用 PAW 内置浏览器阅读网页、填写表单和验证页面。' },
  'facilitate-room': { name: 'Room 协作主持', description: '组织伙伴分工、整合结果，并完成协作验收。' },
  'implementation-planning': { name: '实施规划', description: '把已确认的改动拆成有依赖关系、可验证的步骤。' },
  'improve-codebase-architecture': { name: '架构改进', description: '根据代码证据找出值得实施的架构改进。' },
  'independent-review': { name: '独立审查', description: '对照原始要求与项目标准，审查已有改动和结果。' },
  'memory-curation': { name: '记忆整理', description: '审阅证据，为长期记忆准备可审查的更新。' },
  'orchestrate-session': { name: '子 Agent 协作', description: '委派边界明确的辅助工作，由当前对话整合结果。' },
  'organize-work-documents': { name: '工作文档整理', description: '整理用户原始要求、来源链接和已接受的工作记录。' },
  'pawos-app-builder': { name: '制作 PAW 应用', description: '制作、验证和维护拥有独立界面的 PAW 扩展应用。' },
  'pawos-system': { name: 'PAW 系统使用', description: '解释和操作 PAW 的应用、对话、协作、记忆与系统设置。' },
  'plugin-creator': { name: '插件获取与制作', description: '查找、检查或制作可复用的技能、扩展、提示词与主题包。' },
  'project-maintainer': { name: '安装与维护', description: '维护 PAW 的安装、更新、恢复和托管运行环境。' },
  'rag-retrieval-optimization': { name: '知识检索优化', description: '构建和优化文档解析、索引与检索流程，并验证效果。' },
  'systematic-debugging': { name: '故障定位', description: '先复现并定位故障原因，再验证修复。' },
  'test-driven-implementation': { name: '实现与回归测试', description: '为明确的行为改动建立回归检查，再完成实现。' },
  'trace-agent-diagnostics': { name: '运行诊断', description: '根据对话和运行记录定位失败、评估执行质量并提出修复。' },
};

function scenarioSkillPresentation(skill: ScenarioSkill) {
  return (skill.sourceKind === 'bundled' ? bundledSkillPresentation[skill.name] : undefined)
    ?? { name: skill.name, description: skill.description };
}

function ScenarioSkillInstructions({ skill, transport, active, supported }: {
  skill: ScenarioSkill; transport: ControlTransport; active: boolean; supported: boolean;
}) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ['configuration', 'scenario-skill-body', skill.skillId],
    queryFn: async ({ signal }) => {
      const response = asRecord(await transport.request({ pathId: 'agent.extensions.skills.get', query: { skillId: skill.skillId }, signal }));
      const item = asRecord(response.item);
      if (response.ok !== true || typeof item.body !== 'string') throw new Error('没有读取到这项技能的原文。');
      return item.body;
    },
    enabled: open && active && supported,
    retry: false,
    staleTime: 5_000,
  });
  return <Disclosure className="configuration-skill-routing__instructions" onOpenChange={setOpen}
    summary={<><ChevronRight aria-hidden="true" size={14} />查看技能原文</>}>
    <p className="configuration-skill-routing__identity">技能标识：<code>{skill.name}</code></p>
    {!supported ? <p>当前环境只提供清单说明，无法读取正文。{skill.description}</p>
      : query.isPending ? <p role="status">正在读取技能原文…</p>
        : query.error ? <InlineNotice title="技能原文暂时无法读取" tone="warning">
          <p>{publicErrorText(query.error, '已有选择会保留，请重试。')}</p>
          <Button size="small" variant="quiet" onClick={() => void query.refetch()}>重试原文</Button>
        </InlineNotice>
          : <pre>{query.data || '这项技能没有提供正文。'}</pre>}
  </Disclosure>;
}
