import type { EvalLabExperiment } from './api';
import { isSceneRecipeBinding, sceneRecipeIdForExperiment, type SceneRecipeBinding } from './scene-recipes';

export type OptimizationLayer = 'configuration' | 'implementation';
export type OptimizationTarget = 'model' | 'prompt' | 'retrieval' | 'tool' | 'skill' | 'workflow';

export type ExperimentSetup = {
  layer: OptimizationLayer;
  target: OptimizationTarget;
  goal: string;
  allowedChanges: string;
  maxCandidates: number;
  budgetUsd: number;
  stopCondition: string;
  workspaceRoot: string;
};

export type RepairOperator = {
  id: string;
  layer: OptimizationLayer;
  target: OptimizationTarget;
  failureOwner: 'model_quality_cost' | 'prompt_context' | 'rag_retrieval' | 'tool_runtime' | 'skill_runtime' | 'workflow';
  change: string;
  requiredEvidence: string[];
};

export type CounterfactualProbe = {
  id: string;
  kind: 'single_factor_replay' | 'retrieval_ablation' | 'same_case_regression';
  operatorId: string;
  hypothesis: string;
  frozenControls: string[];
  acceptance: string;
  status: 'planned';
};

/** A persisted task for Pi, not a second execution or lifecycle authority. */
export type ExperimentDispatchContract = {
  schemaVersion: 'rag-ime.agent-lab-dispatch.v1';
  experimentId: string;
  experimentRevisionSha256: string;
  objective: { description: string; primaryMetric: string; hardGates: string[] };
  scope: { layer: OptimizationLayer; target: OptimizationTarget; allowedChanges: string };
  baseline: { runId: string; evidenceRefs: string[] };
  dataset: { datasetId: string; manifestSha256: string; split: string; caseCount: number; heldOutAllowed: false };
  budget: { maxCandidates: number; maxEstimatedCostUsd: number; enforcement: 'agent_observed' };
  stopConditions: Array<
    | { kind: 'candidate_limit' | 'cost_limit_usd'; value: number }
    | { kind: 'user_condition'; value: string }
    | { kind: 'user_stop' | 'missing_usage' | 'incomparable_evidence' }
  >;
  workspace: { root: string; isolation: 'candidate_copy_required' };
  repairOperators: RepairOperator[];
  counterfactualProbes: CounterfactualProbe[];
  terminalResults: Array<'improved' | 'no_improvement' | 'budget_exhausted' | 'stopped' | 'blocked' | 'failed'>;
  application: 'separate_action';
  sceneRecipeBinding?: SceneRecipeBinding;
};

const OPERATORS: RepairOperator[] = [
  { id: 'model_configuration', layer: 'configuration', target: 'model', failureOwner: 'model_quality_cost', change: '只替换业务执行模型，固定推理强度、Judge 模型、Prompt、Tool、Skill 和工作流。', requiredEvidence: ['runtime_model_receipt', 'quality_baseline', 'complete_priced_usage', 'same_case_eval'] },
  { id: 'prompt_evidence_gate', layer: 'configuration', target: 'prompt', failureOwner: 'prompt_context', change: '只修改通用证据覆盖、拒答或逐主张引用规则。', requiredEvidence: ['exact_baseline_trace', 'prompt_diff', 'same_case_eval'] },
  { id: 'prompt_implementation', layer: 'implementation', target: 'prompt', failureOwner: 'prompt_context', change: '只在候选副本修复有证据的 Prompt 模板或组装实现。', requiredEvidence: ['exact_baseline_trace', 'source_diff', 'regression_check', 'same_case_eval'] },
  { id: 'retrieval_configuration', layer: 'configuration', target: 'retrieval', failureOwner: 'rag_retrieval', change: '只修改一个检索参数族，冻结模型、Prompt 和其余检索控制。', requiredEvidence: ['retrieval_stage_trace', 'configuration_diff', 'same_case_eval'] },
  { id: 'retrieval_implementation', layer: 'implementation', target: 'retrieval', failureOwner: 'rag_retrieval', change: '只在候选副本修复证据定位到的 parse/chunk/search/rerank/packing 实现。', requiredEvidence: ['retrieval_stage_trace', 'source_diff', 'regression_check', 'same_case_eval'] },
  { id: 'tool_configuration', layer: 'configuration', target: 'tool', failureOwner: 'tool_runtime', change: '只修改 Tool 选择、参数约束或调用顺序配置，冻结 Prompt、模型和业务权限。', requiredEvidence: ['tool_trace', 'configuration_diff', 'same_case_eval'] },
  { id: 'skill_configuration', layer: 'configuration', target: 'skill', failureOwner: 'skill_runtime', change: '只修改 Skill 选择、版本或加载配置，冻结 Prompt、模型和权限。', requiredEvidence: ['skill_load_trace', 'configuration_diff', 'same_case_eval'] },
  { id: 'workflow_configuration', layer: 'configuration', target: 'workflow', failureOwner: 'workflow', change: '只修改一个工作流编排参数族，冻结任务、权限和其余执行控制。', requiredEvidence: ['runtime_terminal_trace', 'configuration_diff', 'same_case_eval'] },
  { id: 'tool_contract_implementation', layer: 'implementation', target: 'tool', failureOwner: 'tool_runtime', change: '修复有失败回执的 Tool schema、传输或错误语义，保持原业务权限范围。', requiredEvidence: ['tool_failure_receipt', 'source_diff', 'tool_fixture', 'same_case_eval'] },
  { id: 'skill_implementation', layer: 'implementation', target: 'skill', failureOwner: 'skill_runtime', change: '只在候选副本修复有证据的 Skill 契约、加载或输出边界。', requiredEvidence: ['skill_load_trace', 'source_diff', 'regression_check', 'same_case_eval'] },
  { id: 'workflow_implementation', layer: 'implementation', target: 'workflow', failureOwner: 'workflow', change: '修复有证据的依赖、重试、恢复或清理边界，复用 Pi Session/Room。', requiredEvidence: ['runtime_terminal_trace', 'source_diff', 'regression_check', 'same_case_eval'] },
];

export function defaultExperimentSetup(experiment: EvalLabExperiment): ExperimentSetup {
  return {
    layer: 'configuration',
    target: 'prompt',
    goal: experiment.businessProblem,
    allowedChanges: '通用 Prompt 与证据规则；每个候选只改变一个因素。',
    maxCandidates: 3,
    budgetUsd: 5,
    stopCondition: '找到首个通过全部质量门禁的有效改善，或连续两个候选没有改善时停止。',
    workspaceRoot: '',
  };
}

export function compileExperimentDispatch(
  experiment: EvalLabExperiment,
  setup: ExperimentSetup,
  additionalScenarioContext = '',
  sceneRecipeBinding?: SceneRecipeBinding,
): { ok: true; contract: ExperimentDispatchContract; scenarioPrompt: string; message: string } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  if (sceneRecipeBinding && (!isSceneRecipeBinding(sceneRecipeBinding) || sceneRecipeIdForExperiment(experiment.experimentId) !== sceneRecipeBinding.sceneId)) errors.push('场景版本与本次实验不匹配，请刷新后重试。');
  for (const [label, value, limit] of [
    ['优化目标', setup.goal, 4000], ['允许修改范围', setup.allowedChanges, 2000], ['停止条件', setup.stopCondition, 2000],
  ] as const) {
    if (!value.trim() || value.length > limit || /[\u0000]/u.test(value)) errors.push(`${label}需要 1–${limit} 个有效字符。`);
  }
  if (!['configuration', 'implementation'].includes(setup.layer)) errors.push('请选择配置层或实现层。');
  if (!['model', 'prompt', 'retrieval', 'tool', 'skill', 'workflow'].includes(setup.target)) errors.push('请选择模型、Prompt、RAG、Tool、Skill 或工作流优化对象。');
  if (setup.target === 'model' && setup.layer !== 'configuration') errors.push('模型对照属于配置层，请选择配置层后运行。');
  if (!Number.isInteger(setup.maxCandidates) || setup.maxCandidates < 1 || setup.maxCandidates > 100) errors.push('候选数量需要是 1–100 的整数。');
  if (!Number.isFinite(setup.budgetUsd) || setup.budgetUsd <= 0 || setup.budgetUsd > 10000) errors.push('成本预算需要大于 0 且不超过 10000 美元。');
  const root = setup.workspaceRoot.trim().replace(/\/+$/u, '');
  if (!root.startsWith('/') || !root || /[\u0000-\u001f]/u.test(root) || root.split('/').some((part) => part === '..' || part === '.')) errors.push('请选择有效的候选工作目录。');
  if (['held_out', 'held-out', 'heldout'].includes(experiment.dataset.split.toLowerCase())) errors.push('此入口只运行 Validation，不能消费 Held-out。');
  if (!experiment.baseline.runId || !experiment.dataset.manifestSha256 || experiment.dataset.caseCount < 1) errors.push('需要可追踪的基线和非空冻结数据集。');
  if (errors.length) return { ok: false, errors };

  const operators = OPERATORS.filter((operator) => operator.layer === setup.layer && operator.target === setup.target).map((operator) => ({ ...operator, requiredEvidence: [...operator.requiredEvidence] }));
  const contract: ExperimentDispatchContract = {
    schemaVersion: 'rag-ime.agent-lab-dispatch.v1',
    experimentId: experiment.experimentId,
    experimentRevisionSha256: experiment.revisionSha256,
    objective: { description: setup.goal.trim(), primaryMetric: experiment.scoring.primaryMetric, hardGates: [...experiment.scoring.hardGates] },
    scope: { layer: setup.layer, target: setup.target, allowedChanges: setup.allowedChanges.trim() },
    baseline: { runId: experiment.baseline.runId, evidenceRefs: [...experiment.baseline.evidenceRefs] },
    dataset: { datasetId: experiment.dataset.datasetId, manifestSha256: experiment.dataset.manifestSha256, split: experiment.dataset.split, caseCount: experiment.dataset.caseCount, heldOutAllowed: false },
    budget: { maxCandidates: setup.maxCandidates, maxEstimatedCostUsd: setup.budgetUsd, enforcement: 'agent_observed' },
    stopConditions: [
      { kind: 'candidate_limit', value: setup.maxCandidates }, { kind: 'cost_limit_usd', value: setup.budgetUsd },
      { kind: 'user_condition', value: setup.stopCondition.trim() }, { kind: 'user_stop' }, { kind: 'missing_usage' }, { kind: 'incomparable_evidence' },
    ],
    workspace: { root, isolation: 'candidate_copy_required' },
    repairOperators: operators,
    counterfactualProbes: operators.map((operator) => ({
      id: `probe.${operator.id}`, operatorId: operator.id,
      kind: operator.id === 'retrieval_configuration' ? 'retrieval_ablation' : setup.layer === 'configuration' ? 'single_factor_replay' : 'same_case_regression',
      hypothesis: operator.target === 'model' ? '固定评审模型和其余控制，仅替换业务模型，检验能否在质量门禁不退化时降低每个成功任务的成本。'
        : `若失败由 ${operator.failureOwner} 导致，只执行 ${operator.id} 应改善对应门禁。先核对该 owner 的证据再启用此探针。`,
      frozenControls: ['case_set', 'manifest', 'split', 'scorer', 'judge_model', 'permissions', 'all_other_factors'],
      acceptance: '同一冻结 Case 的前后 Trace/Eval 与实际 diff 均齐全；质量门禁通过后才比较成本。',
      status: 'planned',
    })),
    terminalResults: ['improved', 'no_improvement', 'budget_exhausted', 'stopped', 'blocked', 'failed'],
    application: 'separate_action',
    ...(sceneRecipeBinding ? { sceneRecipeBinding: { ...sceneRecipeBinding, recipe: { ...sceneRecipeBinding.recipe } } } : {}),
  };
  const instructions = [
    '$agent-eval-room-optimizer',
    '用户提交本实验设置即授权这次有界 Validation；在已授权范围直接推进，不重复确认。',
    '执行者是现有 Pi Session/Room。此 JSON 是持久任务合同，历史矩阵不是执行器，候选建议不是运行结果。',
    `agentLabDispatch=${JSON.stringify(contract)}`,
    ...(sceneRecipeBinding ? ['将 sceneRecipeBinding 完整写入独立候选副本的 scene-recipe.json，作为冻结起点；不得覆盖旧快照或运行中改读当前版本。复跑原方案时执行 scripts/run_rag_agent_ablation.py --scene-recipe 指向此文件，在基线和候选显式固定相同 --judge-model。原方案以 conditions.sceneRecipe 核对；Prompt 候选在同一 recipe 上追加 --candidate-prompt-file，报告必须回显 conditions.parentSceneRecipe 与 candidatePrompt，不能声称派生候选等同原 recipe。'] : []),
    ...(setup.target === 'model' ? ['模型候选只改变业务模型，Judge 保持冻结；不得使用 RAG --model-override 隐式替换评审模型。基线可用 --scene-recipe；模型候选使用独立显式参数（--model-override 与固定 --judge-model），保留原 Prompt/检索/Skill 参数，并在结果证据绑定原 recipe 与 baselineRunId；不要向旧 recipe 强塞不同模型。'] : []),
    '先核对冻结基线、精确 Trace、数据和 Host evaluator，再按有证据的 failureOwner 选择一个 scope 内的 repairOperator；列出的探针是 planned，不是已发生或已授权扩大范围的结果。',
    '在选定目录内创建独立候选副本并记录 baseline revision、candidate root 和实际 diff；选定 workspaceRoots 不等于已完成隔离。配置及实现候选均不得直接修改来源工作区。',
    '每次候选开始前检查累计实际 usage 与剩余估算预算；没有可读 usage/价格回执就停止付费试验并返回 blocked。成本和候选上限当前由 Agent 观察，Host 尚未提供 Room 累计美元硬限，不得声称已强制限额。',
    '逐候选保存候选编号、父节点、假设、改动、命令、隔离环境、真实 Trace/Eval、逐 Case before/after、Token 和成本回执。比较前确认 case-set/manifest/scorer/分母一致；无改善是正常终态。',
    '用户经 agent.room.message 干预；经 agent.room.abort 停止。复用 Pi 的 Steer、Stop、取消扇出、恢复和唯一终态，窗口关闭不能终止执行。',
    'Held-out 保持封存。candidate-aware Validation 不支持 unbiased Promotion；Keep 只保留候选，应用到场景是 separate_action，已有 Session 的资源快照保持稳定。',
    '由 Facilitator 汇总一份真实终态：improved/no_improvement/budget_exhausted/stopped/blocked/failed，保留失败、取消与不可比证据。',
  ];
  const scenarioPrompt = [...instructions, additionalScenarioContext].filter(Boolean).join('\n');
  // Room persists at most 8000 characters. Never submit a truncated JSON contract.
  if (scenarioPrompt.length > 8000) return { ok: false, errors: ['实验设置过长，请缩短优化目标、允许修改范围或停止条件后重试。'] };
  return { ok: true, contract, scenarioPrompt, message: [`开始实验：${experiment.title}`, ...instructions].join('\n') };
}
