/*
 * Public, deterministic Agent Lab preview data.
 *
 * The preview transport must remain useful when the desktop is started with
 * VITE_CONTROL_TRANSPORT=mock.  Keep this fixture deliberately smaller than
 * the interview ledger: it contains only the same public projection that the
 * HTTP endpoint serves (aggregate metrics, bounded output examples and
 * explainable acceptance summaries).  It is labelled “演示数据” by the shell
 * and must never be read as a production or Held-out receipt.
 */

const HASH = (character: string): string => character.repeat(64);

type ExperimentInput = {
  id: string;
  revision: string;
  title: string;
  vertical: string;
  evaluationKind: string;
  status: string;
  claimStatus: string;
  effectStatus: string;
  candidateType: string;
  businessProblem: string;
  whyAgent: string;
  datasetId: string;
  split: string;
  caseCount: number;
  unit: string;
  manifest: string;
  heldOutConsumed?: boolean;
  primaryMetric: string;
  evaluator: string;
  hardGates: string[];
  factors: { name: string; before: string; after: string; reason: string }[];
  frozenControls: { name: string; value: string; reason: string }[];
  baseline: { runId: string; metrics: Record<string, number>; evidenceRefs?: string[]; outputExamples?: OutputExample[] };
  candidate: { runId: string; metrics: Record<string, number>; evidenceRefs?: string[]; outputExamples?: OutputExample[] };
  comparison: { decision: string; decisionReason: string; metricDeltas: MetricDelta[]; outputComparisons?: OutputComparison[] };
  star: { situation: string; task: string; action: string; result: string };
  claim: { resumeBullet: string; allowed: string; forbidden: string };
  openGaps: string[];
};

type OutputExample = { caseId: string; input: string; output: string };
type MetricDelta = { metric: string; before: number; after: number; delta: number };
type OutputComparison = { caseId: string; before: string; after: string };

function experiment(input: ExperimentInput): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.agent-lab-experiment.v1',
    experimentId: input.id,
    revisionSha256: HASH(input.revision),
    title: input.title,
    vertical: input.vertical,
    evaluationKind: input.evaluationKind,
    status: input.status,
    claimStatus: input.claimStatus,
    effectStatus: input.effectStatus,
    candidateType: input.candidateType,
    businessProblem: input.businessProblem,
    whyAgent: input.whyAgent,
    dataset: {
      datasetId: input.datasetId,
      split: input.split,
      caseCount: input.caseCount,
      unit: input.unit,
      manifestSha256: HASH(input.manifest),
      heldOutConsumed: input.heldOutConsumed ?? false,
    },
    scoring: {
      primaryMetric: input.primaryMetric,
      evaluatorAuthority: input.evaluator,
      goldHiddenFromAgent: true,
      hardGates: input.hardGates,
    },
    factors: input.factors,
    frozenControls: input.frozenControls,
    baseline: {
      runId: input.baseline.runId,
      metrics: input.baseline.metrics,
      evidenceRefs: input.baseline.evidenceRefs ?? [`preview:${input.id}:baseline`],
      ...(input.baseline.outputExamples ? { outputExamples: input.baseline.outputExamples } : {}),
    },
    candidate: {
      runId: input.candidate.runId,
      metrics: input.candidate.metrics,
      evidenceRefs: input.candidate.evidenceRefs ?? [`preview:${input.id}:candidate`],
      ...(input.candidate.outputExamples ? { outputExamples: input.candidate.outputExamples } : {}),
    },
    comparison: input.comparison,
    star: input.star,
    claim: input.claim,
    openGaps: input.openGaps,
    importedAtMs: 1_788_000_000_000,
  };
}

type AblationInput = {
  id: string;
  revision: string;
  title: string;
  evaluationKind?: string;
  status: 'kept' | 'rejected' | 'diagnostic' | 'open_gap';
  claimStatus?: 'headline' | 'supporting' | 'diagnostic' | 'blocked';
  effectStatus: 'improved' | 'neutral' | 'regressed' | 'not_run' | 'unverified';
  candidateType?: 'single_factor' | 'compound_repair' | 'baseline' | 'unknown';
  factor: { name: string; before: string; after: string; reason: string };
  datasetId?: string;
  manifestSha256?: string;
  caseCount?: number;
  unit?: string;
  primaryMetric?: string;
  hardGates?: string[];
  baseline: ExperimentInput['baseline'];
  candidate: ExperimentInput['candidate'];
  decision: string;
  decisionReason: string;
  metricDeltas?: MetricDelta[];
  outputComparisons?: OutputComparison[];
  action: string;
  result: string;
  resumeBullet: string;
  allowed: string;
  forbidden: string;
  openGaps?: string[];
};

/**
 * Project matrices show one independently inspectable ablation per row.  The
 * parent carries the frozen business contract; the row changes one factor and
 * binds its own before/after run receipts.  This keeps a failed candidate from
 * being flattened into a vague project summary.
 */
function ablationExperiment(parent: Record<string, unknown>, input: AblationInput): Record<string, unknown> {
  const source = parent as Record<string, any>;
  const withEvidence = (side: ExperimentInput['baseline'], suffix: string) => ({
    ...side,
    evidenceRefs: side.evidenceRefs ?? [`preview:${input.id}:${suffix}`],
  });
  return {
    ...source,
    experimentId: input.id,
    revisionSha256: HASH(input.revision),
    title: input.title,
    evaluationKind: input.evaluationKind ?? source.evaluationKind,
    status: input.status,
    claimStatus: input.claimStatus ?? (input.status === 'open_gap' ? 'blocked' : 'supporting'),
    effectStatus: input.effectStatus,
    candidateType: input.candidateType ?? 'single_factor',
    dataset: {
      ...source.dataset,
      datasetId: input.datasetId ?? source.dataset.datasetId,
      caseCount: input.caseCount ?? source.dataset.caseCount,
      unit: input.unit ?? source.dataset.unit,
      manifestSha256: input.manifestSha256 ?? source.dataset.manifestSha256,
    },
    scoring: {
      ...source.scoring,
      primaryMetric: input.primaryMetric ?? source.scoring.primaryMetric,
      hardGates: input.hardGates ?? source.scoring.hardGates,
    },
    factors: [input.factor],
    baseline: withEvidence(input.baseline, 'baseline'),
    candidate: withEvidence(input.candidate, 'candidate'),
    comparison: {
      decision: input.decision,
      decisionReason: input.decisionReason,
      metricDeltas: input.metricDeltas ?? [],
      ...(input.outputComparisons ? { outputComparisons: input.outputComparisons } : {}),
    },
    star: {
      ...source.star,
      action: input.action,
      result: input.result,
    },
    claim: {
      resumeBullet: input.resumeBullet,
      allowed: input.allowed,
      forbidden: input.forbidden,
    },
    openGaps: input.openGaps ?? source.openGaps,
  };
}
function run(
  runId: string,
  title: string,
  suiteId: string,
  workflowProfile: string,
  taskCount: number,
  taskSuccessCount: number,
  verifierPassCount: number,
  verifierCount: number,
  toolCalls: number,
  failedToolCalls: number,
  latencyMs: number,
  tasks: Record<string, unknown>[],
): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.eval-lab-run.v1',
    runId,
    title,
    suiteId,
    split: 'validation',
    workflowProfile,
    status: 'completed',
    taskCount,
    taskSuccessCount,
    taskSuccessRate: taskCount ? taskSuccessCount / taskCount : 0,
    verifierPassCount,
    verifierCount,
    verifierPassRate: verifierCount ? verifierPassCount / verifierCount : 0,
    toolCalls,
    failedToolCalls,
    latencyMs,
    sourceDatabaseSha256: HASH('d'),
    sourceReportSha256: HASH('e'),
    createdAtMs: 1_787_999_000_000,
    updatedAtMs: 1_788_000_000_000,
    tasks,
  };
}

function task(
  sessionId: string,
  taskAlias: string,
  taskIndex: number,
  succeeded: boolean,
  verifierPassed: number,
  verifierTotal: number,
  toolCalls: number,
  explanation?: Record<string, unknown>,
  failedToolCalls = 0,
): Record<string, unknown> {
  return {
    sessionId,
    title: taskAlias,
    taskAlias,
    taskIndex,
    taskSucceeded: succeeded,
    terminalEvent: 'turn_completed',
    verifierPassed,
    verifierTotal,
    toolCalls,
    failedToolCalls,
    latencyMs: 120_000,
    ...(explanation ? { explanation } : {}),
  };
}

function acceptanceExplanation(
  caseId: string,
  request: string,
  outcome: string,
  passed: number,
  total: number,
  items: Record<string, unknown>[],
): Record<string, unknown> {
  return {
    caseId,
    businessRequest: { normalizedText: request },
    agentOutcome: { normalizedSummary: outcome },
    acceptance: { passed, total, items },
  };
}

const enterpriseOpsExecution = experiment({
  id: 'enterpriseops-csm.execution-chain.v1',
  revision: 'a',
  title: 'EnterpriseOps CSM execution-chain repair',
  vertical: 'enterprise-customer-support',
  evaluationKind: 'workflow',
  status: 'kept',
  claimStatus: 'supporting',
  effectStatus: 'improved',
  candidateType: 'compound_repair',
  businessProblem: '客户支持 Agent 需要按依赖顺序完成跨实体操作，同时不能泄露标准答案、重复写入或遗留临时数据库。',
  whyAgent: '任务同时需要实体发现、状态化 Tool 调用、依赖排序和写后验收，单条聊天回答不能证明最终状态。',
  datasetId: 'enterpriseops-csm-frozen-validation-v1',
  split: 'validation',
  caseCount: 3,
  unit: '3 条端到端客户支持任务、31 个 Host-private verifier',
  manifest: 'b',
  primaryMetric: 'Host verifier 通过率（任务按全有或全无计）',
  evaluator: 'Host-private SQL verifier',
  hardGates: ['所有终态可验收', '临时数据库清理完成', 'Gold 对 Agent 隐藏', 'Tool failure 单独计数'],
  factors: [
    { name: 'execution_policy', before: 'Session 声明 read-only，但任务 Tool 需修改临时 CSM 数据库', after: '宿主文件仍只读；业务 Tool 按 per-action 授权，并锁定 provider / model / thinking', reason: 'Trace 在业务 Tool 前就出现授权冲突，且 Tool 调用为 0；这是执行策略问题，不是模型知识或 RAG。按动作授权能放行临时库写入，又不扩大 workspace 权限。' },
    { name: 'tool', before: 'file-spool wrapper', after: 'capability-token loopback Gateway + MCP isError + toolCallId 幂等', reason: 'Trace 显示 file-spool 没有收到 Pi 的实时 Tool fetch；网关必须接在 Pi 真正的 loopback HTTP seam，再用 token、allowlist、错误语义和调用 ID 解决可达、失败识别与重复写入。' },
    { name: 'workflow', before: 'verifier 与 cleanup 各自 best-effort', after: 'terminal → verifier → cleanup 的 fail-closed 生命周期', reason: 'Tool 调用成功不等于业务完成；只有 turn_completed、全部 Verifier 和 cleanup 回执共同通过，才能防止 Agent 自述掩盖部分写入或临时库残留。' },
  ],
  frozenControls: [
    { name: 'validation_cases', value: '3 条 Validation task / 31 个 verifier', reason: '前后使用同一分母。' },
    { name: 'seed_and_gold', value: '同一临时数据库 seed；Gold 隐藏', reason: '防止答案泄漏和状态漂移。' },
    { name: 'runtime_identity', value: 'source-local Pi + Gateway + Tool catalog hash', reason: '失败可以回到实际运行时。' },
  ],
  baseline: {
    runId: 'enterpriseops-csm-baseline-validation-20260901',
    metrics: { verifierPassRate: 3 / 31, businessToolCalls: 0, taskSuccessRate: 0 },
    outputExamples: [{ caseId: 'aggregate', input: '3 条冻结的客户支持任务', output: '运行在进入业务 Tool 前失败，仅有 3/31 个 verifier 通过。' }],
  },
  candidate: {
    runId: 'enterpriseops-csm-baseline-validation-20260901-v5',
    metrics: { verifierPassRate: 26 / 31, businessToolCalls: 47, failedToolCalls: 0, taskSuccessRate: 1 / 3, temporaryDatabasesDeleted: 3 },
    outputExamples: [{ caseId: 'aggregate', input: '同一组 3 条冻结任务', output: '3 个 Session 都进入真实业务 Tool，47 次调用无 Tool failure，26/31 个 verifier 通过，3/3 临时库已删除。' }],
  },
  comparison: {
    decision: 'keep',
    decisionReason: '执行链从无法进入业务 Tool 恢复到可执行；剩余 5 个 verifier 失败保留给后续 suite-v2，不隐藏。',
    metricDeltas: [
      { metric: 'verifier_pass_rate', before: 3 / 31, after: 26 / 31, delta: 23 / 31 },
      { metric: 'business_tool_calls', before: 0, after: 47, delta: 47 },
    ],
    outputComparisons: [{ caseId: 'aggregate', before: '未进入业务 Tool。', after: '真实 Tool 可执行，临时库清理闭合。' }],
  },
  star: { situation: '初始运行被权限语义和 Tool transport 卡住。', task: '建立可复现、可清理、可验收的执行链。', action: '修复 authority、Gateway、MCP error、幂等和 fail-closed cleanup。', result: 'Verifier 3/31 → 26/31，业务 Tool 0 → 47，3/3 临时库清理。' },
  claim: { resumeBullet: '在冻结 Validation 上修复执行链，使 Host verifier 3/31 → 26/31，并完成 3/3 临时数据库清理。', allowed: '可表述为执行/评测链恢复。', forbidden: '不能表述为业务准确率 100% 或生产稳定性。' },
  openGaps: ['suite-v2 的业务工作流另行验收', 'source-local candidate 尚未安装到当前 PAWOS'],
});

const stateContract = experiment({
  id: 'enterpriseops-csm.state-contract-suite-v2',
  revision: 'b',
  title: 'EnterpriseOps CSM state-contract workflow selection',
  vertical: 'enterprise-customer-support',
  evaluationKind: 'workflow',
  status: 'rejected',
  claimStatus: 'supporting',
  effectStatus: 'improved',
  candidateType: 'compound_repair',
  businessProblem: '复杂客户请求含精确字符串、相对日期、角色身份和有序写入；最终消息看似合理不代表数据库状态正确。',
  whyAgent: '需要发现记录、解析依赖、选择合法负责人、写回多实体并审计终态。',
  datasetId: 'enterpriseops-csm-suite-v2-final-validation',
  split: 'validation',
  caseCount: 3,
  unit: '3 条 Validation task、31 个 Host-private SQL verifier；另有一次性 8 条 Held-out',
  manifest: 'c',
  heldOutConsumed: true,
  primaryMetric: '全有或全无任务完成率',
  evaluator: 'suite-v2 Host-private SQL verifier',
  hardGates: ['31 个 verifier 可执行', '每个任务 turn_completed', '零 Tool failure', '临时数据库全部清理', 'Held-out 只消费一次'],
  factors: [
    { name: 'prompt', before: '共同任务合同没有权威 as-of date；候选也没有精确值/角色约束', after: '所有 lane 共用 2025-11-04；仅 candidate 增加 exact-string / role guidance', reason: 'Trace 显示 3 条失败来自 next year 被解释成不同年份；没有基准日期时不存在唯一正确状态，所以日期先作为共享评测合同修复，不能算 candidate 收益。修复后 Baseline 已选对日期和负责人，却把精确标题擅自扩写，才把剩余变量收窄到字符串与角色约束。' },
    { name: 'workflow', before: '直接执行，末尾才统一验收', after: '状态合同：规划 → 依赖 → 写回 → 回读 → 逐条终态审计', reason: '相同 suite、Tool、模型和数据库下，Baseline 已能找实体并写入，代表性失败只是一个标题漂移连带击穿 3 个依赖条件；责任因此位于要求到跨实体终态的编排层，而不是 Tool 可达性。新增约束均为通用规则，没有写入本题答案。' },
    { name: 'tool', before: 'list_users 只有 locationId 与任职时间', after: '仅给要求国家规则的任务增加 find_locations', reason: '任务要求选择活跃英国员工，但现有 Tool 没有 location 到 country 的映射，信息上不可判定，不能靠 Prompt 猜。find_locations 同时给 Baseline 和 Candidate，只暴露国家映射、不暴露正确员工 ID，所以是公平性前置修复，不是 workflow 涨分归因。' },
  ],
  frozenControls: [
    { name: 'validation_and_heldout', value: 'Validation 3/31；Held-out 8/65，一次性消费', reason: '分开调参和泛化门禁。' },
    { name: 'runtime_and_model', value: 'Sol / high / Pi / 89-Tool / 900s 固定', reason: '只比较 Prompt/workflow 候选。' },
    { name: 'evaluator', value: '同一 40ac966a overlay + 31 个 Host-private SQL verifier', reason: '先保留 31 个槽位，把隐藏固定 owner 与矛盾 SQL 改成用户可见的动态规则；再让两条 lane 绑定同一 hash，避免删题、换 Gold 或泄露答案制造涨分。' },
  ],
  baseline: {
    runId: 'enterpriseops-csm-suite-v2-final-baseline-validation-20260901',
    metrics: { taskSuccessRate: 2 / 3, verifierPassRate: 28 / 31, toolCalls: 72, latencyMs: 529349.673 },
    outputExamples: [{ caseId: 'aggregate', input: '3 条状态合同任务', output: 'Validation 完成 2/3 任务，28/31 verifier 通过。' }],
  },
  candidate: {
    runId: 'enterpriseops-csm-suite-v2-final-state-validation-20260901',
    metrics: { taskSuccessRate: 1, verifierPassRate: 1, toolCalls: 64, latencyMs: 758437.096, failedToolCalls: 0 },
    outputExamples: [{ caseId: 'aggregate', input: '同一 3 条 Validation task', output: 'Validation 完成 3/3 任务，31/31 verifier 通过；一次性 Held-out 仅 1/8。' }],
  },
  comparison: {
    decision: 'reject',
    decisionReason: 'Validation A/B 变好，但一次性 Held-out 只有 1/8、54/65，且有 2 次 Tool failure；质量泛化硬门禁未通过，拒绝 Promotion。',
    metricDeltas: [
      { metric: 'task_success_rate', before: 2 / 3, after: 1, delta: 1 / 3 },
      { metric: 'verifier_pass_rate', before: 28 / 31, after: 1, delta: 3 / 31 },
      { metric: 'tool_calls', before: 72, after: 64, delta: -8 },
      { metric: 'latency_ms', before: 529349.673, after: 758437.096, delta: 229087.423 },
    ],
    outputComparisons: [{ caseId: 'aggregate', before: 'Validation 2/3；未通过全量质量门禁。', after: 'Validation 3/3，但 Held-out 1/8，不能 Promotion。' }],
  },
  star: { situation: 'Validation 中存在日期、角色和依赖语义歧义。', task: '在不改 Gold 的前提下验证状态合同工作流。', action: '固定日期和字符串合同，加入规划与终态审计。', result: 'Validation 2/3 → 3/3、28/31 → 31/31；Held-out 1/8，严格拒绝 Promotion。' },
  claim: { resumeBullet: 'state-contract 在 Validation 由 2/3 → 3/3、28/31 → 31/31；一次性 Held-out 1/8 后自动拒绝 Promotion。', allowed: '可表述为 Validation 胜出但泛化门禁拒绝。', forbidden: '不能表述为 Held-out 成功或生产 100%。' },
  openGaps: ['Held-out 已消费，禁止重跑', '失败 taxonomy 因 Gold 语义保持私有而仍是只读暂定归因', 'Provider usage 仍不可用'],
});

const enterpriseRag = experiment({
  id: 'enterprise-rag.retrieval-selection.v1',
  revision: 'd',
  title: 'Enterprise RAG retrieval selection',
  vertical: 'enterprise-knowledge-retrieval',
  evaluationKind: 'rag_retrieval',
  status: 'diagnostic',
  claimStatus: 'diagnostic',
  effectStatus: 'improved',
  candidateType: 'compound_repair',
  businessProblem: '企业问题同时包含精确标识、语义表达、冲突版本和多来源证据，词法检索单独使用会漏召回或排序过后。',
  whyAgent: '最终工作流需要私有文档中的证据和拒答；先隔离检索层，避免把答案生成误归因给索引。',
  datasetId: 'enterprise-rag-smoke-validation-v1',
  split: 'validation',
  caseCount: 16,
  unit: '16 条冻结检索问题、5,101 篇文档、29,846 个 chunk',
  manifest: 'e',
  primaryMetric: 'nDCG@10（Recall@10 与 MRR 为保护指标）',
  evaluator: 'Host-private qrels + deterministic retrieval scorer',
  hardGates: ['qrels 对 Agent 隐藏', 'corpus/split hash 固定', '向量覆盖完整', 'Held-out 未打开'],
  factors: [
    { name: 'memory_rag', before: 'lexical-only + 固定 Top-10', after: 'BM25 + dense hybrid + RRF + Qwen3 rerank', reason: '同时覆盖关键字、语义和多来源完整性。' },
    { name: 'context', before: '只按检索分数打包', after: 'lexical floor + bounded rerank + 来源边界', reason: '避免 rerank 挤掉关键字命中和独立来源。' },
    { name: 'guardrail', before: '结果直接进入答案', after: '先过 Recall/MRR/nDCG，再进入答案引用测试', reason: '把检索收益和最终回答质量分开。' },
  ],
  frozenControls: [
    { name: 'corpus', value: '5,101 docs / 29,846 chunks / manifest 固定', reason: '避免新增文档伪装成配置收益。' },
    { name: 'query_qrels', value: '16 条 query + Host-private qrels', reason: '固定问题、相关性和分母。' },
    { name: 'promotion', value: 'Held-out 未消费；答案/引用 gate 未通过', reason: '检索 Validation 不能直接推广。' },
  ],
  baseline: { runId: 'enterprise-rag-lexical-floor-validation', metrics: { mrr: 0.604167, ndcgAt10: 0.612801, recallAt10: 0.671875 }, evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-validation-20260831.v1.json'], outputExamples: [{ caseId: 'retrieval', input: '查找跨版本的企业控制条款', output: 'Lexical floor 找到部分相关 chunk，但关键证据排序靠后。' }] },
  candidate: { runId: 'enterprise-rag-hybrid-qwen3-validation', metrics: { mrr: 0.867188, ndcgAt10: 0.887203, recallAt10: 0.955357 }, evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-validation-20260831.v1.json'], outputExamples: [{ caseId: 'retrieval', input: '同一组 16 条冻结 query', output: 'Hybrid + rerank 把相关来源更早放入 Top-10；仍需答案/引用 gate。' }] },
  comparison: {
    decision: 'diagnostic_only',
    decisionReason: '检索候选赢得 Validation，但公开回执没有安全的逐 query 排名，最终答案/引用门禁尚未通过。',
    metricDeltas: [
      { metric: 'ndcg_at_10', before: 0.612801, after: 0.887203, delta: 0.274402 },
      { metric: 'recall_at_10', before: 0.671875, after: 0.955357, delta: 0.283482 },
      { metric: 'mrr', before: 0.604167, after: 0.867188, delta: 0.263021 },
    ],
    outputComparisons: [{ caseId: 'retrieval', before: '相关证据排序靠后。', after: '相关证据更早进入 Top-10，但还不能证明答案引用正确。' }],
  },
  star: { situation: '企业问题既有专名又有跨文档语义关系。', task: '先优化检索，再单独验证答案与引用。', action: '比较 BM25、dense、RRF 和 Qwen3 rerank，并固定 corpus/qrels。', result: 'Recall@10 0.6719 → 0.9554，MRR 0.6042 → 0.8672，nDCG@10 0.6128 → 0.8872。' },
  claim: { resumeBullet: '在 16 条冻结 Validation query 上，Hybrid + Qwen3 rerank 将 Recall@10 0.6719 → 0.9554。', allowed: '可表述为检索层 Validation 诊断结果。', forbidden: '不能表述为最终答案准确率或生产提升。' },
  openGaps: ['安全逐 query 排名回执待补', '答案与引用 Validation 尚未产生可 Promotion 结果', 'Held-out 仍封存'],
});

const cloudOps = experiment({
  id: 'cloudops.agent-validation-and-falsification.v1',
  revision: 'f',
  title: 'CloudOps evidence workflow validation and falsification',
  vertical: 'cloudops-incident-diagnosis',
  evaluationKind: 'workflow',
  status: 'rejected',
  claimStatus: 'supporting',
  effectStatus: 'regressed',
  candidateType: 'compound_repair',
  businessProblem: '云上告警需要跨服务观察、证据读取和根因判断；减少 Tool 次数不能抵消诊断质量回退。',
  whyAgent: '每个 case 都要在冻结观察快照和 Host-only scorer 下组合查询、证据与结论，固定脚本无法覆盖探索路径。',
  datasetId: 'cloudops-smoke-v1',
  split: 'validation',
  caseCount: 12,
  unit: '12 条冻结故障定位 case、3 个顺序 PAW Session',
  manifest: '1',
  primaryMetric: 'CA（FA/JRA/Top3JRA 为保护门禁）',
  evaluator: 'Host-only CloudOps scorer',
  hardGates: ['12 个 case 都有答案', '观察快照与 scorer 一致', 'Tool failure 单独计数', 'Held-out 未观察'],
  factors: [
    { name: 'tool', before: '公开长 cache key + 宽泛搜索', after: 'case-scoped observationId + 受限 search/list/read', reason: '降低地址错误和越权读取。' },
    { name: 'workflow', before: '优先减少 Tool 次数', after: '先过 CA/FA/JRA/Top3JRA，再比较效率', reason: '避免局部省调用掩盖根因退化。' },
    { name: 'guardrail', before: 'Tool 成功即结束', after: 'Host-only scorer 检查覆盖、根因和 Top-3', reason: '分离 Tool/runtime 成功与诊断正确性。' },
  ],
  frozenControls: [
    { name: 'validation_suite', value: '同一 12-case Validation / 3x4 Session', reason: '固定问题和分母。' },
    { name: 'runtime_identity', value: 'Pi + Sol + max + loopback + suite hash 固定', reason: '避免运行时漂移。' },
    { name: 'heldout_and_cost', value: 'Held-out 未观察；usage 不可用', reason: '不把 Validation 写成泛化或成本。' },
  ],
  baseline: { runId: 'cloudops-agent-validation-20260901-v1', metrics: { answerCoverage: 1, ca: 1, fa: 0.833333, jra: 0.833333, top3Jra: 0.833333, toolCalls: 98, failedToolCalls: 0, elapsedMs: 1356582 }, evidenceRefs: ['eval/interview-metrics/runs/cloudops-agent-validation-20260901.v1.json'], outputExamples: [{ caseId: 'aggregate', input: '12 条冻结故障定位任务', output: '12/12 有答案，CA 1.00，98/98 Tool 调用成功。' }] },
  candidate: { runId: 'cloudops-bounded-workflow-validation-reject-20260901-v1', metrics: { answerCoverage: 0.75, ca: 0.75, jra: 0.75, top3Jra: 0.833333, toolCalls: 82, failedToolCalls: 1, elapsedMs: 1175311 }, evidenceRefs: ['eval/interview-metrics/runs/cloudops-bounded-workflow-validation-reject-20260901.v1.json'], outputExamples: [{ caseId: 'aggregate', input: '同一 12 条任务', output: 'Tool 98 → 82，耗时下降，但覆盖率 0.75、CA 0.75，并出现 1 次 Tool failure。' }] },
  comparison: { decision: 'reject', decisionReason: '效率下降不能抵消 CA/JRA 回退；保留 baseline，拒绝 bounded workflow。', metricDeltas: [{ metric: 'ca', before: 1, after: 0.75, delta: -0.25 }, { metric: 'jra', before: 0.833333, after: 0.75, delta: -0.083333 }, { metric: 'tool_calls', before: 98, after: 82, delta: -16 }, { metric: 'elapsed_ms', before: 1356582, after: 1175311, delta: -181271 }], outputComparisons: [{ caseId: 'aggregate', before: '12/12 答案，CA 1.00。', after: '调用更少，但 CA 退到 0.75，不能保留。' }] },
  star: { situation: '初始 CloudOps Agent 已能完成答案，但 Tool 调用偏多。', task: '在不损失根因和引用质量的前提下找效率候选。', action: '收紧 observation Tool、增加质量门禁并保留失败回执。', result: 'Tool 98 → 82、耗时下降，但 CA 1.00 → 0.75，严格 Reject。' },
  claim: { resumeBullet: '对 CloudOps 效率候选执行 falsification：Tool 98 → 82 但 CA 1.00 → 0.75，自动拒绝并保留 baseline。', allowed: '可表述为质量保护门禁阻止错误优化。', forbidden: '不能表述为效率和质量同时提升。' },
  openGaps: ['Provider usage 与 process signals 待投影', 'Trace Skill 通用盲测尚未运行', 'candidate 尚未安装到当前 PAWOS'],
});

const cloudOpsLuna = experiment({
  id: 'cloudops.agent-validation-luna-max-timeout.v1',
  revision: 'cloudops-luna-max-baseline-validation-20260902',
  title: 'CloudOps · Luna Max baseline Validation（第三批超时）',
  vertical: 'cloudops-incident-diagnosis',
  evaluationKind: 'workflow',
  status: 'rejected',
  claimStatus: 'supporting',
  effectStatus: 'unverified',
  candidateType: 'single_factor',
  businessProblem: 'CloudOps 诊断需要在冻结观察和 Host-only 质量门禁下完成；Luna Max 这次 Validation 在第三批和 abort 阶段超时，不能把 Runtime 失败写成业务质量结果。',
  whyAgent: '需要真实 Agent Session 产生可追踪的 Tool、usage 和终态回执；没有完整批次和 Host formal CA/JRA，就不能判断模型质量或成本。',
  datasetId: 'cloudops-smoke-v1',
  split: 'validation',
  caseCount: 3,
  unit: '3 个 Session 汇总回执；0 份公开 transcript',
  manifest: '1',
  primaryMetric: '本次不产出 Host formal CA/JRA；只记录 Runtime/Transcript 失败回执',
  evaluator: 'Runtime failure receipt；Host formal CA/JRA 未运行',
  hardGates: ['第三批不得 timeout', 'abort 不得 timeout', 'Host formal CA/JRA 可执行', 'Held-out 保持未消费', 'source-local candidate 未安装'],
  factors: [
    { name: 'model', before: 'gpt-5.6-sol / max', after: 'gpt-5.6-luna / max', reason: '只替换模型；Prompt、Skill、Tool、Workflow 和 scorer 保持冻结。' },
  ],
  frozenControls: [
    { name: 'validation_contract', value: 'CloudOps Validation；3 个 Session 汇总回执，0 份公开 transcript', reason: '固定问题和本次 Runtime 失败边界。' },
    { name: 'agent_contract', value: 'Prompt、Skill、Tool、Workflow、scorer、thinking=max 固定', reason: '只改变模型。' },
    { name: 'heldout_and_install', value: 'Held-out 未消费；source-local candidate 未安装', reason: '不把失败写成泛化或安装态结论。' },
  ],
  baseline: {
    runId: 'cloudops-agent-validation-20260901-v1',
    metrics: { answerCoverage: 1, ca: 1, fa: 0.833333, jra: 0.833333, top3Jra: 0.833333, toolCalls: 98, failedToolCalls: 0, elapsedMs: 1356582 },
    outputExamples: [{ caseId: 'aggregate', input: '同一 CloudOps Validation 的业务 baseline。', output: 'Baseline 有 98 次业务 Tool 调用、CA 1.00、JRA 0.8333；这是业务 Tool 统计，不与 Luna 的 transcript Tool 直接比较。' }],
  },
  candidate: {
    runId: 'cloudops--cloudops-luna-max-baseline-validation-20260902',
    metrics: { sessionCount: 3, transcriptCount: 0, transcriptToolCalls: 278, failedTranscriptToolCalls: 14, inputTokens: 916112, outputTokens: 57057, cacheReadTokens: 18809344, latencyMs: 1718516, thirdBatchTimeout: 1, abortTimeout: 1, hostFormalCaJraAvailable: 0, costReceiptAvailable: 1, estimatedApiCostUsd: 0.62787768, providerBillAvailable: 0, sourceLocal: 1, installed: 0 },
    evidenceRefs: ['eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902.v1.json', 'eval/interview-metrics/runs/agent-lab-cost-cloudops-luna-failed-run-20260902.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: 'CloudOps Luna Max Validation 的 3 份 Session 汇总回执。', output: '0 份公开 transcript；汇总记录 278 次 transcript Tool、14 次失败、输入 916112、输出 57057、cacheRead 18809344、1718516ms；第三批 timeout 且 abort timeout；无 Host formal CA/JRA。' }],
  },
  comparison: {
    decision: 'reject',
    decisionReason: '第三批 timeout 且 abort timeout，未产生 Host formal CA/JRA；278 次 transcript Tool 与 baseline 的 98 次业务 Tool 不是同一统计口径，不能拿来宣称效率或质量变化，Reject。',
    metricDeltas: [],
    outputComparisons: [{ caseId: 'aggregate', before: 'Baseline 98 次业务 Tool，CA 1.00、JRA 0.8333。', after: 'Luna 回执只有 278 次 transcript Tool、14 次失败和 timeout；没有 Host formal CA/JRA。' }],
  },
  star: { situation: 'CloudOps Luna Max baseline Validation 的第三批发生 timeout，随后 abort 也 timeout；回执只能支持 Runtime/Transcript 失败观察。', task: '在不消费 Held-out 的前提下，观察 Luna Max 的同协议 CloudOps Validation 稳定性，并保留失败回执。', action: '只替换模型为 Luna Max；Prompt、Skill、Tool、Workflow、scorer 和其余 Validation 合同保持冻结，汇总 3 个 Session 回执；公开目录没有对话原文。', result: '记录 278 次 transcript Tool、14 次失败、输入 916112、输出 57057、cacheRead 18809344、1718516ms；第三批 timeout 且 abort timeout；没有 Host formal CA/JRA，Reject。' },
  claim: { resumeBullet: 'CloudOps Luna Max Validation 因第三批与 abort timeout 被 Reject；仅保留 278 次 transcript Tool、14 次失败和 token/latency 回执，未产生 Host formal CA/JRA。', allowed: 'Runtime/Transcript 失败诊断、token/latency 观测；Transcript Tool 278 不与 baseline business Tool 98 比较。', forbidden: 'CloudOps CA/JRA 质量、模型质量、成本节省、Held-out 泛化、生产或安装稳定性。' },
  openGaps: ['没有 Host formal CA/JRA 结果', '第三批 timeout 和 abort timeout 的完整恢复路径待补', 'Provider pricing/billing 未提供', 'source-local candidate 未安装到 PAWOS', 'Held-out 未消费'],
});

const traceAgent = experiment({
  id: 'trace-agent.closed-loop-historical-replay.v1',
  revision: '2',
  title: 'Trace Agent closed-loop historical replay',
  vertical: 'agent-runtime-diagnosis-and-repair',
  evaluationKind: 'trace_repair',
  status: 'open_gap',
  claimStatus: 'blocked',
  effectStatus: 'not_run',
  candidateType: 'compound_repair',
  businessProblem: '失败常在下游暴露；诊断需要找到最早失败 span、正确 owner 和必要证据，再决定是否授权修复。',
  whyAgent: '证据跨 Session、Provider、Tool、Workflow 和 Eval，固定错误字符串匹配无法解释因果链。',
  datasetId: 'paw-trace-closed-loop-historical-replay-v1',
  split: 'historical_replay',
  caseCount: 3,
  unit: '3 条公开历史 before/finding/change/after episode',
  manifest: '3',
  primaryMetric: '硬门禁诊断 case 成功率',
  evaluator: 'Host-private Trace gold + deterministic scorer',
  hardGates: ['first failing span 正确', 'root owner 正确', '证据组完整', '不得无依据下结论', 'Gold 不进入 Agent'],
  factors: [
    { name: 'skill', before: '只按错误字符串查找', after: 'Trace Skill + evidence envelope + scorer contract', reason: '覆盖 first-failing-span、owner、证据和修复边界。' },
    { name: 'workflow', before: '只统计失败数量', after: '诊断 → 授权修复 → 新 Trace/Eval → Keep/Reject', reason: '把建议和已验证修复分开。' },
    { name: 'human_loop', before: 'Agent 直接下修复结论', after: 'Host-private Gold + 用户授权后才可改', reason: '防止未知被写成确定。' },
  ],
  frozenControls: [
    { name: 'replay_cases', value: '3 条公开历史 episode', reason: '固定 before/finding/change/after manifest。' },
    { name: 'gold_boundary', value: 'Host-private diagnosis Gold 对 Agent 隐藏', reason: '测定位而不是答案泄漏。' },
    { name: 'promotion_gate', value: '无 Provider prediction；Held-out 不消费', reason: '当前只证明 scorer 和流程准备。' },
  ],
  baseline: { runId: 'not-run-error-proximity-v0', metrics: { realPredictionCases: 0, scorerContractTestsPassed: 8 }, outputExamples: [{ caseId: 'status', input: '3 条公开历史 case', output: '尚无真实 Agent prediction；只能证明确定性 scorer 合同通过。' }] },
  candidate: { runId: 'not-run-trace-skill-v1', metrics: { realPredictionCases: 0, publicHistoricalCasesPrepared: 3 }, outputExamples: [{ caseId: 'status', input: 'Trace Skill + evidence envelope', output: '候选流程已准备，但没有新 Trace/Eval 复验。' }] },
  comparison: { decision: 'not_run', decisionReason: '公开 case 和确定性 scorer 已准备，但真实 Host-private gold、Agent prediction 和 blind split 尚未形成。', metricDeltas: [], outputComparisons: [{ caseId: 'status', before: '错误字符串诊断，未运行。', after: '流程合同已准备，仍未运行真实 prediction。' }] },
  star: { situation: '历史 Trace 只有顶层失败，无法判断最早根因。', task: '准备跨 Session 的可授权修复闭环。', action: '定义 evidence envelope、受限 Reviewer 和新 Trace/Eval gate。', result: '3 条公开 case 已准备，真实 prediction 仍为 0。' },
  claim: { resumeBullet: '设计 Trace 诊断到授权修复的闭环，并保留未运行边界。', allowed: '可表述为流程和 scorer 准备。', forbidden: '不能表述为 Trace Agent 已自主修复或提升成功率。' },
  openGaps: ['Host-private historical gold 尚未编译', 'Agent prediction 尚未运行', '没有 blind incident split'],
});

const memory = experiment({
  id: 'memory.personal-shadow-evaluation.v1',
  revision: '4',
  title: 'Memory / Personal RAG shadow evaluation',
  vertical: 'personal-memory-and-rag',
  evaluationKind: 'memory',
  status: 'diagnostic',
  claimStatus: 'diagnostic',
  effectStatus: 'unverified',
  candidateType: 'compound_repair',
  businessProblem: '长期记忆既要召回有用事实，也要避免旧输入回声、跨项目泄漏和已删除内容复活。',
  whyAgent: '记忆维护跨 Evidence、Atom、Book、投影、召回和反馈；单次问答无法证明生命周期安全。',
  datasetId: 'memory-private-shadow-v1',
  split: 'shadow_validation',
  caseCount: 74,
  unit: '74 条私有 shadow 语义复核；另有 16 个行为 case × 3 轮',
  manifest: '5',
  primaryMetric: '独立复核通过率与 direct rank-1 召回',
  evaluator: '独立复核 + deterministic memory case gate',
  hardGates: ['Evidence 可追溯', 'scope 隔离', '墓碑不复活', '旧输入不回声', '没有可比结果时保持 unknown'],
  factors: [
    { name: 'memory_rag', before: '只看单次召回', after: 'Evidence → Atom → Book + hybrid/tag retrieval', reason: '让来源、范围和反馈成为召回约束。' },
    { name: 'context', before: '直接把长记忆注入 Agent', after: '按 scope、freshness 和 token budget 选择', reason: '减少旧主题污染和无关上下文。' },
    { name: 'guardrail', before: '候选命中即可展示', after: '反回声、tombstone、项目隔离与人工反馈门禁', reason: '把错误候选挡在用户界面前。' },
  ],
  frozenControls: [
    { name: 'shadow_data', value: '私有 shadow 数据与复核清单固定', reason: '不把用户日志暴露给 Agent。' },
    { name: 'scope', value: '用户 / 项目 / App scope 固定', reason: '跨域召回必须拒绝。' },
    { name: 'claim_boundary', value: '没有 before/after 不计算 uplift', reason: '独立通过不等于提升。' },
  ],
  baseline: { runId: 'memory-private-shadow-review-v1', metrics: { reviewed: 74, passed: 74, directRank1Cases: 4, endToEndP95Ms: 37 }, outputExamples: [{ caseId: 'recall', input: '在当前项目里找回已确认的输入法约束', output: '4 个 recall case 均 direct rank-1；来源仍可回溯到 Evidence。' }] },
  candidate: { runId: 'memory-optimizer-case-gate-v3', metrics: { behaviorCases: 16, repeats: 3, passed: 48, traces: 48, endToEndP95Ms: 37 }, outputExamples: [{ caseId: 'safety', input: '验证旧输入回声、tombstone 和项目隔离', output: '48/48 行为观察通过；没有可比 before/after，保持 diagnostic。' }] },
  comparison: { decision: 'diagnostic_only', decisionReason: 'Memory shadow 和行为 gate 都有正向观察，但没有同一任务的 before/after 质量对照，不能称为泛化提升。', metricDeltas: [], outputComparisons: [{ caseId: 'recall', before: '单次召回结果不可作为生命周期证明。', after: 'Evidence、scope 和反回声门禁均有独立观察，但 uplift 未计算。' }] },
  star: { situation: 'Memory 召回容易把旧输入、跨项目内容和已删除候选带回来。', task: '建立可追溯、可隔离、可恢复的个人记忆评测。', action: '把 Evidence/Atom/Book、hybrid/tag、tombstone 和反馈纳入冻结 case。', result: '74/74 私有 shadow 复核；16 case × 3 轮 48/48 通过；仍标 diagnostic-only。' },
  claim: { resumeBullet: '为 Personal Memory 建立 Evidence→Atom→Book 与反回声/墓碑门禁，私有 shadow 复核 74/74。', allowed: '可表述为治理和诊断证据。', forbidden: '不能表述为 LongMemEval 泛化准确率或 before/after uplift。' },
  openGaps: ['缺少同任务 before/after 质量对照', '长期维护 gold labels 尚未建立', '安装态选择/反馈/删除尚未验收'],
});

const memoryMaintenance = experiment({
  id: 'memory.maintenance-luna-shadow-v5.v1',
  revision: '8',
  title: 'Memory Maintenance · Luna v4 to v5 shadow gate',
  vertical: 'memory-maintenance',
  evaluationKind: 'memory',
  status: 'kept',
  claimStatus: 'supporting',
  effectStatus: 'improved',
  candidateType: 'compound_repair',
  businessProblem: '真实月度整理在 834.945 秒后因 JSONL 截断失败；修复候选必须先在隔离 shadow 中证明完整生命周期。',
  whyAgent: '整理横跨模型判断、Evidence→Atom→Book、RAG、rollback 和 replay，需要真实模型与 Host gate 联合验收。',
  datasetId: 'memory-maintenance-public-safe-fixture-v1',
  split: 'shadow_validation',
  caseCount: 5,
  unit: '4 durable memory cases + 1 temporary control',
  manifest: '8',
  primaryMetric: '五例整理、召回、拒记、dense、rollback 与 replay 完整门禁',
  evaluator: 'Host lifecycle verifier + real Luna receipts',
  hardGates: ['production DB 不打开', '5/5 决策', 'vector coverage 1', 'rollback/replay 通过', '合法 JSON receipt'],
  factors: [
    { name: 'memory_rag', before: 'v4：Null embedding，vector coverage 0', after: 'v5：确定性本地 dense provider，vector coverage 1', reason: '召回链缺少可用向量，必须先补齐可验证的 dense 投影。' },
    { name: 'workflow', before: 'Markdown body 使用 .json 后缀', after: '写入合法、可机器读取的无原文 JSON receipt', reason: '旧回执不能被 Host 稳定解析，需修复结果合同。' },
  ],
  frozenControls: [
    { name: 'model_prompt', value: 'Luna Max；Prompt/Schema 冻结', reason: '不混入模型或提示词差异。' },
    { name: 'fixture', value: '相同五个 case ID；v5 manifest 已冻结', reason: 'v4 receipt 未记录 manifest SHA，不能声称 v4/v5 内容级完全相同。' },
    { name: 'production', value: 'DB 未打开、Held-out 未消费', reason: 'shadow winner 不等于生产修复。' },
  ],
  baseline: { runId: 'memory-maintenance-luna-max-validation-20260902-v4', metrics: { curationCases: 5, curationPassed: 5, durableRecallPassed: 4, durableRecallTotal: 4, abstentionPassed: 1, abstentionTotal: 1, vectorCoverage: 0, rollbackPassed: 1, replayPassed: 1, receiptJsonValid: 0, actualModelCallElapsedMs: 90642 }, evidenceRefs: ['eval/interview-metrics/runs/memory-maintenance-luna-max-validation-20260902.v4.json'], outputExamples: [{ caseId: 'aggregate', input: '同一五例 v4', output: 'case 与恢复通过，但 vector coverage 0，回执格式不合法。' }] },
  candidate: { runId: 'memory-maintenance-luna-max-validation-20260902-v5', metrics: { curationCases: 5, curationPassed: 5, durableRecallPassed: 4, durableRecallTotal: 4, abstentionPassed: 1, abstentionTotal: 1, vectorCoverage: 1, rollbackPassed: 1, replayPassed: 1, receiptJsonValid: 1, actualModelCallElapsedMs: 85172, modelTokensAvailable: 0 }, evidenceRefs: ['eval/interview-metrics/runs/memory-maintenance-luna-max-validation-20260902.v5.json'], outputExamples: [{ caseId: 'aggregate', input: '同一五例 v5', output: '5/5 决策、4/4 durable recall、1/1 temporary abstention；dense、rollback、replay 与 JSON receipt 全部通过。' }] },
  comparison: { decision: 'keep', decisionReason: 'v5 补齐 v4 的 dense 和 receipt 硬门禁，只保留为 private-shadow winner。', metricDeltas: [{ metric: 'vectorCoverage', before: 0, after: 1, delta: 1 }, { metric: 'receiptJsonValid', before: 0, after: 1, delta: 1 }, { metric: 'actualModelCallElapsedMs', before: 90642, after: 85172, delta: -5470 }], outputComparisons: [{ caseId: 'aggregate', before: 'v4 dense/receipt 不完整。', after: 'v5 完整通过 shadow lifecycle gate。' }] },
  star: { situation: '真实维护晚失败，早期 shadow 候选也不完整。', task: '找到第一条完整的隔离维护证据链。', action: '保留 v1/v3/v4 Reject；v5 同时补齐 deterministic dense provider 与合法 JSON receipt writer。', result: 'v5 通过五例、dense、rollback/replay；模型调用 85.172 秒，公开回执未提供 token 或 USD。' },
  claim: { resumeBullet: '建立 Memory private-shadow lifecycle Eval，v5 通过 5/5 整理、4/4 recall、1/1 拒记及 rollback/replay。', allowed: 'private-shadow Validation v4→v5。', forbidden: '生产、Held-out、全 rank-1 或 USD 降本。' },
  openGaps: ['生产修复后 Trace 未运行', 'Held-out 未消费', 'USD 成本不可用', 'candidate 未安装'],
});

const modelCost = experiment({
  id: 'agent-lab.model-cost.luna-max-validation.v1',
  revision: '8',
  title: 'Agent Lab quality-gated model cost: Sol versus Luna',
  vertical: 'agent-evaluation-cost',
  evaluationKind: 'model_cost',
  status: 'rejected',
  claimStatus: 'supporting',
  effectStatus: 'regressed',
  candidateType: 'single_factor',
  businessProblem: '低价模型即使更快、更省，也不能越过任务与 Verifier 质量门禁。',
  whyAgent: '只有真实 Agent Session 才能在同任务、同 Prompt、同 Tool、同 Workflow 和同 Host-private Verifier 下产生可比结果与 usage。',
  datasetId: 'enterpriseops-csm-suite-v2-final-validation',
  split: 'validation',
  caseCount: 3,
  unit: '同一 3 条 EnterpriseOps task、31 个 Host-private verifier',
  manifest: '7',
  primaryMetric: '质量门禁通过后才比较 API 成本估算',
  evaluator: 'Host verifier + Runtime DB Provider usage receipt',
  hardGates: ['质量不低于 incumbent', '3/3 cleanup', 'usage 与价格来源可核验', 'Held-out 未消费'],
  factors: [
    { name: 'model', before: 'gpt-5.6-sol / max', after: 'gpt-5.6-luna / max', reason: '只替换模型，检验低价候选能否保持质量门禁。' },
  ],
  frozenControls: [
    { name: 'task_and_split', value: '3 tasks / 31 verifier；Held-out 未消费', reason: '模型对比使用同一分母。' },
    { name: 'agent_contract', value: 'Prompt、Skill、Tool、Workflow、runner、Runtime provenance、thinking=max 与 timeout 固定', reason: '只改变模型身份。' },
    { name: 'usage_authority', value: 'Runtime DB usage + 同日 pricing source hash', reason: '缺 usage 不评分；estimate 不冒充账单。' },
  ],
  baseline: {
    runId: 'enterpriseops-csm-sol-max-validation-20260903-v1',
    metrics: { taskSuccessRate: 1, verifierPassRate: 1, toolCalls: 87, failedToolCalls: 1, latencyMs: 1112646.229, allDatabasesCleaned: 1, costReceiptAvailable: 1, totalTokens: 3964517, apiCostUsd: 3.243385 },
    evidenceRefs: ['eval/interview-metrics/runs/enterpriseops-csm-sol-max-validation-20260903.v1.json', 'eval/interview-metrics/runs/agent-lab-cost-sol-max-20260903.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: 'Sol Max 执行 3 条 Validation task', output: '3/3 task、31/31 verifier、87 Tool（1 次已恢复失败）、1112.65 秒；API 价格估算 $3.243385。' }],
  },
  candidate: {
    runId: 'enterpriseops-csm-luna-max-validation-20260903-v3',
    metrics: { taskSuccessRate: 2 / 3, verifierPassRate: 30 / 31, toolCalls: 66, failedToolCalls: 0, latencyMs: 929656.199, allDatabasesCleaned: 1, costReceiptAvailable: 1, totalTokens: 3609609, apiCostUsd: 0.725239 },
    evidenceRefs: ['eval/interview-metrics/runs/enterpriseops-csm-luna-max-validation-20260903.v3.json', 'eval/interview-metrics/runs/agent-lab-cost-luna-max-20260903.v3.json'],
    outputExamples: [{ caseId: 'aggregate', input: '同一合同仅替换为 Luna Max', output: '2/3 task、30/31 verifier、66 Tool、929.66 秒；API 价格估算 $0.725239。' }],
  },
  comparison: {
    decision: 'reject',
    decisionReason: 'Luna 的成本估算降低 77.64%、耗时降低 16.45%，但 task 3/3→2/3、verifier 31/31→30/31；质量门禁优先，保留 Sol。',
    metricDeltas: [
      { metric: 'taskSuccessRate', before: 1, after: 2 / 3, delta: -1 / 3 },
      { metric: 'verifierPassRate', before: 1, after: 30 / 31, delta: -1 / 31 },
      { metric: 'toolCalls', before: 87, after: 66, delta: -21 },
      { metric: 'latencyMs', before: 1112646.229, after: 929656.199, delta: -182990.03 },
      { metric: 'totalTokens', before: 3964517, after: 3609609, delta: -354908 },
      { metric: 'apiCostUsd', before: 3.243385, after: 0.725239, delta: -2.518146 },
    ],
    outputComparisons: [{ caseId: 'aggregate', before: 'Sol 通过 3/3 task、31/31 verifier。', after: 'Luna 更省、更快，但仅 2/3 task、30/31 verifier，因此 Reject。' }],
  },
  star: {
    situation: '旧成本记录混入不同 thinking 与源码提交，不能支持单变量结论。',
    task: '在相同当前源码、Runtime provenance 与 Validation 合同下重跑 Sol/Luna Max。',
    action: '冻结任务、Prompt、Skill、Tool、Workflow、runner、thinking 与价格来源，只替换模型，并聚合真实 Runtime DB usage。',
    result: 'Luna 成本估算 -77.64%、耗时 -16.45%，但质量从 3/3、31/31 回退到 2/3、30/31，故 Reject。',
  },
  claim: {
    resumeBullet: '设计单变量 Agent 模型评测：Luna Max 虽将 API 成本估算降低 77.6%、延迟降低 16.4%，却使 task 3/3→2/3、verifier 31/31→30/31；据此阻止低价模型越过质量门禁。',
    allowed: '匹配 Validation 合同下的质量回退、usage、价格估算与 Reject。',
    forbidden: 'Provider 账单节省、生产替换、稳定性或 Held-out 泛化。',
  },
  openGaps: ['没有 billed receipt', '单次 Validation，无稳定性区间', 'source-local candidate 未安装', 'Held-out 未消费'],
});

const ragTagReadiness = ablationExperiment(enterpriseRag, {
  id: 'enterprise-rag.tag-graph-readiness.v1', revision: 'g',
  title: 'Enterprise RAG · Graph + Tag 重排就绪检查',
  status: 'open_gap', claimStatus: 'blocked', effectStatus: 'not_run',
  factor: {
    name: 'memory_rag',
    before: 'Qwen3 reranker 已有 16 题 Validation 分数',
    after: 'Graph + Tag 候选因企业 source-bound 图为空而不运行',
    reason: '先检查 documentId/chunkId 绑定；不能拿 Memory 的 memory_item_id 冒充企业文档排序信号。',
  },
  baseline: {
    runId: 'enterprise-rag-hybrid-qwen3-validation',
    metrics: { mrr: 0.867188, ndcgAt10: 0.887203, recallAt10: 0.955357 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-validation-20260831.v1.json'],
    outputExamples: [{ caseId: 'readiness', input: 'Qwen3 与 Graph + Tag 是否可做公平 A/B？', output: 'Qwen3 有冻结 Validation 参照。' }],
  },
  candidate: {
    runId: 'enterprise-rag-tag-reranker-readiness-20260901-v1',
    metrics: { knowledgeGraphNodes: 0, knowledgeGraphEdges: 0, knowledgeGraphExtractions: 0, tagMetricsAvailable: 0 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-tag-reranker-readiness-20260901.v1.json'],
    outputExamples: [{ caseId: 'readiness', input: '检查企业 Knowledge 图与 Tag 身份。', output: 'node、edge、extraction 都为 0；A/B 在评分前被阻断。' }],
  },
  decision: 'not_run',
  decisionReason: '企业 source-bound Graph 尚未建立，候选没有合法排序特征；不生成伪分数，保留 Qwen3 参照。',
  action: 'Trace Reviewer 先核对 Graph/Tag 的实体身份、数据覆盖和可评分条件。',
  result: '在 Provider 运行前阻断无效 A/B；没有消耗 Held-out，也没有声称 Tag 优于或劣于 Qwen3。',
  resumeBullet: '为 Graph + Tag 重排增加 readiness gate，在企业图为空时阻断伪 A/B。',
  allowed: '可说明就绪检查阻止了不可比较实验。',
  forbidden: '不能声称 Graph + Tag 已经得到质量分或可替代 Qwen3。',
  openGaps: ['需要先构建 documentId + chunkId 绑定的企业 Knowledge 图'],
});

const ragAnswerBaseline = ablationExperiment(enterpriseRag, {
  id: 'enterprise-rag.answer-luna-baseline.v20', revision: 'h',
  title: 'Enterprise RAG · Luna Baseline（模型消融）',
  evaluationKind: 'answer_evidence', status: 'rejected', effectStatus: 'neutral',
  factor: {
    name: 'model', before: 'GPT-5.6 Sol / max', after: 'GPT-5.6 Luna / max',
    reason: '先只换模型，判断低价模型是否保持答案与逐事实引用质量。',
  },
  datasetId: 'enterprise-rag-answer-evidence-validation-v1',
  manifestSha256: 'f154bbc55dba2733e10e0ebac91da6af50493565e688b19e80327bc028f21c96',
  caseCount: 4, unit: '4 个协议 case：2 个可回答、2 个 info_not_found；共 9 条必要事实',
  primaryMetric: '答案通过、事实覆盖、可回答问题引用支持与拒答分开计分',
  hardGates: ['逐事实 source/chunk/quote 支持', 'info_not_found 拒答', '输出协议', 'Held-out 未消费'],
  baseline: {
    runId: 'enterprise-rag-answer-evidence-sol-v16-baseline',
    metrics: { agentCaseCount: 4, agentSuccessRate: 0.5, answerCaseCount: 2, answerSuccessRate: 0.5, highLevelFactCount: 9, verifiedRequiredFactCount: 9, highLevelFactCoverage: 6 / 9, citationFactCoverage: 2 / 9, answerableCaseCount: 2, answerableCitationSupportRate: 0, infoNotFoundCaseCount: 2, infoNotFoundAbstentionRecall: 1, citationHardGatePassed: 0, outputProtocolRate: 1, tokens: 25384, toolCalls: 6, latencyMs: 63693.186 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-answer-evidence-validation-reject-20260901.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '同一 4 个 Validation 协议 case', output: 'Sol：Agent 2/4；可回答答案 1/2；必要事实 6/9，引用事实 2/9，可回答引用支持 0/2，应拒答问题 2/2。' }],
  },
  candidate: {
    runId: 'enterprise-rag-answer-evidence-luna-v20-baseline',
    metrics: { agentCaseCount: 4, agentSuccessRate: 0.5, answerCaseCount: 2, answerSuccessRate: 0.5, highLevelFactCount: 9, verifiedRequiredFactCount: 9, highLevelFactCoverage: 6 / 9, citationFactCoverage: 2 / 9, answerableCaseCount: 2, answerableCitationSupportRate: 0, infoNotFoundCaseCount: 2, infoNotFoundAbstentionRecall: 1, citationHardGatePassed: 0, outputProtocolRate: 1, tokens: 25778, toolCalls: 6, latencyMs: 51577.706 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-validation-20260902.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '只替换为 Luna Max', output: 'Luna：Agent 2/4、可回答答案 1/2；必要事实 6/9、引用事实 2/9；更快但仍不满足引用硬门。' }],
  },
  decision: 'reject', decisionReason: '模型替换保持现有质量且耗时下降，但核心引用支持仍为 0；候选不能上线。',
  metricDeltas: [{ metric: 'answerSuccessRate', before: 0.5, after: 0.5, delta: 0 }, { metric: 'latencyMs', before: 63693.186, after: 51577.706, delta: -12115.48 }, { metric: 'tokens', before: 25384, after: 25778, delta: 394 }],
  outputComparisons: [{ caseId: 'aggregate', before: 'Sol：Agent 2/4、答案 1/2；citation support 0/2。', after: 'Luna：Agent 2/4、答案 1/2；citation support 0/2。' }],
  action: '冻结 Prompt、Skill、Tool、Workflow、corpus 与 answer contract，只替换模型。',
  result: '质量持平、耗时下降 19.0%，Token 增加 1.6%；引用硬门未通过，Reject。',
  resumeBullet: '在冻结答案合同上完成 Sol/Luna 模型消融，并因引用支持为 0 拒绝候选。',
  allowed: '可说明 Luna 在这 4 个 Validation case 上质量持平且更快。',
  forbidden: '不能声称成本下降、引用质量提升、Held-out 或生产通过。',
});

const ragAnswerSkill = ablationExperiment(ragAnswerBaseline, {
  id: 'enterprise-rag.answer-luna-skill.v20', revision: 'i',
  title: 'Enterprise RAG · Skill Profile 的 Sol / Luna 模型消融',
  evaluationKind: 'answer_evidence', status: 'rejected', effectStatus: 'neutral',
  factor: {
    name: 'model', before: 'GPT-5.6 Sol / max + 冻结 Citation Skill', after: 'GPT-5.6 Luna / max + 同一 Citation Skill',
    reason: '该回执只替换模型；Prompt、Skill、Tool、Workflow、语料和评分合同全部冻结。',
  },
  baseline: {
    runId: 'enterprise-rag-answer-evidence-sol-v16-skill',
    metrics: { agentCaseCount: 4, agentSuccessRate: 0.5, answerCaseCount: 2, answerSuccessRate: 0.5, highLevelFactCount: 9, verifiedRequiredFactCount: 9, highLevelFactCoverage: 6 / 9, citationFactCoverage: 2 / 9, answerableCaseCount: 2, answerableCitationSupportRate: 0, infoNotFoundCaseCount: 2, infoNotFoundAbstentionRecall: 1, citationHardGatePassed: 0, outputProtocolRate: 1, tokens: 68404, toolCalls: 7, latencyMs: 224479.982 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-answer-evidence-validation-reject-20260901.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: 'Sol Max + 冻结 Citation Skill', output: 'Agent 2/4；可回答答案 1/2；必要事实 6/9，引用事实 2/9，可回答引用支持 0/2，应拒答问题 2/2。' }],
  },
  candidate: {
    runId: 'enterprise-rag-answer-evidence-luna-v20-skill',
    metrics: { agentCaseCount: 4, agentSuccessRate: 0.5, answerCaseCount: 2, answerSuccessRate: 0.5, highLevelFactCount: 9, verifiedRequiredFactCount: 9, highLevelFactCoverage: 6 / 9, citationFactCoverage: 2 / 9, answerableCaseCount: 2, answerableCitationSupportRate: 0, infoNotFoundCaseCount: 2, infoNotFoundAbstentionRecall: 1, citationHardGatePassed: 0, outputProtocolRate: 1, tokens: 74769, toolCalls: 7, latencyMs: 208063.982 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-validation-20260902.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '只把 Skill profile 的模型替换为 Luna Max', output: '质量和 Tool 数不变；耗时下降，Token 增加，引用硬门仍失败。' }],
  },
  decision: 'reject', decisionReason: 'Luna 在同一 Skill profile 上质量与 Tool 持平、耗时下降，但 Token 增加且引用硬门仍失败。',
  metricDeltas: [{ metric: 'answerSuccessRate', before: 0.5, after: 0.5, delta: 0 }, { metric: 'tokens', before: 68404, after: 74769, delta: 6365 }, { metric: 'toolCalls', before: 7, after: 7, delta: 0 }, { metric: 'latencyMs', before: 224479.982, after: 208063.982, delta: -16416 }],
  outputComparisons: [{ caseId: 'aggregate', before: 'Sol + Skill：Agent 2/4、答案 1/2，引用支持 0/2。', after: 'Luna + 同一 Skill：Agent 2/4、答案 1/2，引用支持仍为 0/2。' }],
  action: '固定 Citation Skill profile，只把 Sol Max 替换为 Luna Max。',
  result: '质量持平；Token 68,404 → 74,769（+9.3%），Tool 7 → 7，耗时 224.5s → 208.1s（-7.3%）；引用硬门未过，Reject。',
  resumeBullet: '在冻结 Citation Skill profile 上完成 Sol/Luna 模型消融；耗时下降但引用硬门仍失败。',
  allowed: '可说明 Luna 在这条 Skill profile 的 Validation 上质量持平、耗时下降。',
  forbidden: '不能把本回执表述为新增或优化了 Skill，也不能声称引用质量提升。',
});

const ragAnswerTuned = ablationExperiment(ragAnswerBaseline, {
  id: 'enterprise-rag.answer-luna-tuned.v20', revision: 'j',
  title: 'Enterprise RAG · Tuned Profile 的 Sol / Luna 模型消融',
  evaluationKind: 'answer_evidence', status: 'rejected', effectStatus: 'neutral',
  factor: {
    name: 'model', before: 'GPT-5.6 Sol / max + 冻结 Tuned RAG', after: 'GPT-5.6 Luna / max + 同一 Tuned RAG',
    reason: '该回执只替换模型；Tuned RAG、Prompt、Skill、Tool、Workflow 与评分合同全部冻结。',
  },
  baseline: {
    runId: 'enterprise-rag-answer-evidence-sol-v16-tuned',
    metrics: { agentCaseCount: 4, agentSuccessRate: 0.5, answerCaseCount: 2, answerSuccessRate: 0.5, highLevelFactCount: 9, verifiedRequiredFactCount: 9, highLevelFactCoverage: 6 / 9, citationFactCoverage: 2 / 9, answerableCaseCount: 2, answerableCitationSupportRate: 0, infoNotFoundCaseCount: 2, infoNotFoundAbstentionRecall: 1, citationHardGatePassed: 0, outputProtocolRate: 1, tokens: 82471, toolCalls: 7, latencyMs: 210666.32 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-answer-evidence-validation-reject-20260901.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: 'Sol Max + 冻结 Tuned RAG', output: 'Agent 2/4；可回答答案 1/2；必要事实 6/9，引用事实 2/9，可回答引用支持 0/2，应拒答问题 2/2。' }],
  },
  candidate: {
    runId: 'enterprise-rag-answer-evidence-luna-v20-tuned',
    metrics: { agentCaseCount: 4, agentSuccessRate: 0.5, answerCaseCount: 2, answerSuccessRate: 0.5, highLevelFactCount: 9, verifiedRequiredFactCount: 9, highLevelFactCoverage: 6 / 9, citationFactCoverage: 2 / 9, answerableCaseCount: 2, answerableCitationSupportRate: 0, infoNotFoundCaseCount: 2, infoNotFoundAbstentionRecall: 1, citationHardGatePassed: 0, outputProtocolRate: 1, tokens: 88941, toolCalls: 7, latencyMs: 182436.769 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-validation-20260902.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '只把 Tuned profile 的模型替换为 Luna Max', output: '质量和 Tool 数不变；耗时下降，Token 增加，引用硬门仍失败。' }],
  },
  decision: 'reject', decisionReason: 'Luna 在同一 Tuned profile 上质量与 Tool 持平、耗时下降，但 Token 增加且引用硬门仍失败。',
  metricDeltas: [{ metric: 'answerSuccessRate', before: 0.5, after: 0.5, delta: 0 }, { metric: 'tokens', before: 82471, after: 88941, delta: 6470 }, { metric: 'toolCalls', before: 7, after: 7, delta: 0 }, { metric: 'latencyMs', before: 210666.32, after: 182436.769, delta: -28229.551 }],
  outputComparisons: [{ caseId: 'aggregate', before: 'Sol + Tuned：Agent 2/4、答案 1/2，引用支持 0/2。', after: 'Luna + 同一 Tuned：Agent 2/4、答案 1/2，引用支持仍为 0/2。' }],
  action: '固定 Tuned RAG profile，只把 Sol Max 替换为 Luna Max。',
  result: '质量持平；Token 82,471 → 88,941（+7.8%），Tool 7 → 7，耗时 210.7s → 182.4s（-13.4%）；引用硬门未过，Reject。',
  resumeBullet: '在冻结 Tuned RAG profile 上完成 Sol/Luna 模型消融；耗时下降但引用硬门仍失败。',
  allowed: '可说明 Luna 在这条 Tuned profile 的 Validation 上质量持平、耗时下降。',
  forbidden: '不能把本回执表述为本轮修改了 RAG 参数，也不能把 Recall@10 写成答案准确率。',
});

const ragAnswerAgentic = ablationExperiment(ragAnswerBaseline, {
  id: 'enterprise-rag.answer-luna-agentic.v20', revision: 'k',
  title: 'Enterprise RAG · Agentic Profile 的 Sol / Luna 模型消融',
  evaluationKind: 'answer_evidence', status: 'rejected', effectStatus: 'regressed',
  factor: {
    name: 'model', before: 'GPT-5.6 Sol / max + 冻结 Agentic Workflow', after: 'GPT-5.6 Luna / max + 同一 Agentic Workflow',
    reason: '该回执只替换模型；Agentic Workflow、Prompt、Skill、Tool、语料与评分合同全部冻结。',
  },
  baseline: {
    runId: 'enterprise-rag-answer-evidence-sol-v16-agentic',
    metrics: { agentCaseCount: 4, agentSuccessRate: 0, answerCaseCount: 2, answerSuccessRate: 0, highLevelFactCount: 9, verifiedRequiredFactCount: 9, highLevelFactCoverage: 0, citationFactCoverage: 0, answerableCaseCount: 2, answerableCitationSupportRate: 0, infoNotFoundCaseCount: 2, infoNotFoundAbstentionRecall: 0, citationHardGatePassed: 0, outputProtocolRate: 1, tokens: 0, tokensComplete: 0, toolCalls: 13, latencyMs: 600604.956 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-answer-evidence-validation-reject-20260901.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: 'Sol Max + 冻结 Agentic Workflow', output: 'Agent 0/4、可回答答案 0/2、必要事实 0/9、应拒答 0/2；13 次 Tool；Token 记录是失败占位值。' }],
  },
  candidate: {
    runId: 'enterprise-rag-answer-evidence-luna-v20-agentic',
    metrics: { agentCaseCount: 4, agentSuccessRate: 0, answerCaseCount: 2, answerSuccessRate: 0, highLevelFactCount: 9, verifiedRequiredFactCount: 9, highLevelFactCoverage: 0, citationFactCoverage: 0, answerableCaseCount: 2, answerableCitationSupportRate: 0, infoNotFoundCaseCount: 2, infoNotFoundAbstentionRecall: 0, citationHardGatePassed: 0, outputProtocolRate: 0, tokens: 7713, tokensComplete: 0, toolCalls: 12, latencyMs: 420642.371 },
    evidenceRefs: ['eval/interview-metrics/runs/enterprise-rag-answer-evidence-luna-max-validation-20260902.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '只把 Agentic profile 的模型替换为 Luna Max', output: 'Agent 仍为 0/4、答案 0/2、事实 0/9、拒答 0/2；输出协议退化为无合法 cases[]，Token 记录仍不完整。' }],
  },
  decision: 'reject', decisionReason: '两种模型都未完成 Agentic profile；Luna 更快且少 1 次 Tool，但输出协议进一步失败，Token 不完整不可比。',
  metricDeltas: [{ metric: 'answerSuccessRate', before: 0, after: 0, delta: 0 }, { metric: 'toolCalls', before: 13, after: 12, delta: -1 }, { metric: 'latencyMs', before: 600604.956, after: 420642.371, delta: -179962.585 }, { metric: 'outputProtocolRate', before: 1, after: 0, delta: -1 }],
  outputComparisons: [{ caseId: 'aggregate', before: 'Sol + Agentic：Agent 0/4、答案 0/2，输出仍可解析。', after: 'Luna + 同一 Agentic：Agent 0/4、答案 0/2，未形成合法 cases[]。' }],
  action: '固定 Agentic profile，只把 Sol Max 替换为 Luna Max。',
  result: '两者均 0/4；Tool 13 → 12、耗时 600.6s → 420.6s，但输出协议 100% → 0%，Reject。',
  resumeBullet: '在冻结 Agentic profile 上完成 Sol/Luna 模型消融，并因终态与输出协议失败拒绝 Luna。',
  allowed: '可说明 Luna 更快、少 1 次 Tool，但没有修复 Agentic 工作流。',
  forbidden: '不能把 7,713 个不完整 token 当成成本优化，也不能声称本轮修改了 Workflow。',
});

const cloudOpsBaseline = ablationExperiment(cloudOps, {
  id: 'cloudops.validation-baseline.v1', revision: 'l',
  title: 'CloudOps · 可评分 Baseline 建立',
  status: 'kept', effectStatus: 'unverified', candidateType: 'baseline',
  factor: {
    name: 'tool', before: '私有 Tool transport / observation hash 合同失败', after: '冻结 observation snapshot + 可解析 Tool contract',
    reason: '先让 12 个 case 真正可运行、可评分，再讨论 Prompt 或 Workflow 优化。',
  },
  baseline: {
    runId: 'cloudops-paw-baseline-root-20260901-v2',
    metrics: { formalScoreProduced: 0 },
    evidenceRefs: ['eval/interview-metrics/runs/cloudops-agent-validation-20260901.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '12 条 CloudOps case', output: '运行在 Tool/hash 合同处中断，没有正式总分。' }],
  },
  candidate: {
    runId: 'cloudops-paw-baseline-root-20260901-v3',
    metrics: { answerCoverage: 1, ca: 1, fa: 5 / 6, jra: 5 / 6, top3Jra: 5 / 6, toolCalls: 98, failedToolCalls: 0, elapsedMs: 1356582, formalScoreProduced: 1 },
    evidenceRefs: ['eval/interview-metrics/runs/cloudops-agent-validation-20260901.v1.json'],
    outputExamples: [
      { caseId: 'trial-v2', input: 'Trial v2 · 原 Tool/hash 合同', output: '运行中断，未完成 Host 正式评分。' },
      { caseId: 'trial-v3', input: 'Trial v3 · 修复 Tool/快照合同', output: '12/12 作答，CA 1.00，FA/JRA/Top-3 0.8333，98/98 Tool 成功。' },
    ],
  },
  decision: 'keep', decisionReason: '这一步是评测/Tool 合同恢复，不把“无分→有分”包装成模型质量提升；保留为后续消融的 incumbent。',
  metricDeltas: [{ metric: 'formalScoreProduced', before: 0, after: 1, delta: 1 }],
  outputComparisons: [{ caseId: 'aggregate', before: '无正式分数。', after: '12/12 可评分，CA 1.00。' }],
  action: 'Trace 定位 Tool transport 与 canonical observation hash，普通 Agent 修复后用同一 suite 复验。',
  result: '从运行失败恢复为 12/12 作答、98/98 Tool 成功的正式 Baseline。',
  resumeBullet: '修复 CloudOps Tool/Eval 合同，建立 12/12 可评分的冻结 Validation baseline。',
  allowed: '可表述为执行与评测链恢复。',
  forbidden: '不能把无分到有分写成模型准确率提升。',
});

const cloudOpsEvidenceSearch = ablationExperiment(cloudOps, {
  id: 'cloudops.evidence-search.v2', revision: 'm',
  title: 'CloudOps · Evidence-search Workflow 消融',
  status: 'rejected', effectStatus: 'regressed',
  factor: {
    name: 'workflow', before: 'Baseline 自主探索', after: 'search-first evidence workflow',
    reason: '尝试用显式搜索扩大 Top-3 根因证据覆盖，同时记录调用成本。',
  },
  baseline: cloudOps.baseline as ExperimentInput['baseline'],
  candidate: {
    runId: 'cloudops-evidence-search-validation-reject-20260901-v1',
    metrics: { answerCoverage: 1, ca: 5 / 6, jra: 5 / 6, top3Jra: 1, toolCalls: 189, searchCalls: 106, listCalls: 15, readCalls: 62, failedToolCalls: 0, elapsedMs: 996035 },
    evidenceRefs: ['eval/interview-metrics/runs/cloudops-evidence-search-validation-reject-20260901.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '只改 search-first workflow', output: 'Top3JRA 到 1.00，但 CA 降到 0.8333，Tool 增至 189。' }],
  },
  decision: 'reject', decisionReason: 'Top-3 方向更全不能抵消主 CA 回退与 Tool 近翻倍；search-first 没有两阶段故障对象→根因约束。',
  metricDeltas: [{ metric: 'ca', before: 1, after: 5 / 6, delta: -1 / 6 }, { metric: 'jra', before: 5 / 6, after: 5 / 6, delta: 0 }, { metric: 'top3Jra', before: 5 / 6, after: 1, delta: 1 / 6 }, { metric: 'toolCalls', before: 98, after: 189, delta: 91 }, { metric: 'elapsedMs', before: 1356582, after: 996035, delta: -360547 }],
  outputComparisons: [{ caseId: 'aggregate', before: 'CA 1.00，98 Tool。', after: 'CA 0.8333，189 Tool；Top3JRA 1.00。' }],
  action: '仅替换搜索工作流，模型、Tool schema、12 case 与 Host scorer 保持冻结。',
  result: '耗时下降 26.6%，但 CA 回退且 Tool +92.9%；Reject。',
  resumeBullet: '通过消融拒绝了调用翻倍且主质量回退的 search-first CloudOps workflow。',
  allowed: '可说明 Top3JRA 局部改善但整体候选失败。',
  forbidden: '不能表述为质量或成本优化成功。',
});

const cloudOpsObservationId = ablationExperiment(cloudOps, {
  id: 'cloudops.observation-id.v4', revision: 'n',
  title: 'CloudOps · observationId Tool 消融',
  status: 'rejected', effectStatus: 'regressed',
  factor: {
    name: 'tool', before: '公开长 cacheKey 容易转录失败', after: '短 observationId + Host 内部地址映射',
    reason: '只修地址型 Tool failure，验证 Tool 可靠性与诊断质量是否能分别守门。',
  },
  baseline: cloudOps.baseline as ExperimentInput['baseline'],
  candidate: {
    runId: 'cloudops-observation-id-validation-reject-20260901-v1',
    metrics: { answerCoverage: 1, ca: 0.5, fa: 7 / 12, jra: 5 / 12, top3Jra: 0.5, toolCalls: 94, searchCalls: 23, listCalls: 9, readCalls: 56, failedToolCalls: 0, elapsedMs: 1248603, publicCacheKeyReads: 0 },
    evidenceRefs: ['eval/interview-metrics/runs/cloudops-observation-id-validation-reject-20260901.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '只把长 cacheKey 换成短 observationId', output: '94/94 Tool 成功，但 CA 退至 0.50、JRA 退至 0.4167。' }],
  },
  decision: 'reject_and_stop', decisionReason: 'Tool 合同修复成功，但业务诊断质量明显回退；按预设 stop rule 拒绝并停止继续吃同一 Validation。',
  metricDeltas: [{ metric: 'ca', before: 1, after: 0.5, delta: -0.5 }, { metric: 'fa', before: 5 / 6, after: 7 / 12, delta: -0.25 }, { metric: 'jra', before: 5 / 6, after: 5 / 12, delta: -5 / 12 }, { metric: 'top3Jra', before: 5 / 6, after: 0.5, delta: -1 / 3 }, { metric: 'toolCalls', before: 98, after: 94, delta: -4 }, { metric: 'elapsedMs', before: 1356582, after: 1248603, delta: -107979 }],
  outputComparisons: [{ caseId: 'aggregate', before: 'Baseline CA 1.00、JRA 0.8333。', after: 'Tool 零失败，但 CA 0.50、JRA 0.4167。' }],
  action: '只改 Tool 地址合同；模型、Prompt、Workflow、case 与 scorer 全部冻结。',
  result: '地址可靠性通过，质量门禁失败；候选 Reject，且不再运行 V5。',
  resumeBullet: '把 Tool 可靠性与 Agent 质量分开验收，拒绝了零 Tool failure 但 CA 下降 50% 的候选。',
  allowed: '可说明 Tool 修复成功但整条候选未成功。',
  forbidden: '不能用 94/94 Tool 成功代替诊断准确率。',
});

const cloudOpsRuntimeSelectionRepair = ablationExperiment(cloudOpsLuna, {
  id: 'cloudops.runtime-selection-repair-retry3.v1', revision: 'runtime-retry3',
  title: 'CloudOps · Runtime 选择顺序修复（retry3）',
  evaluationKind: 'tool_runtime', status: 'rejected', claimStatus: 'diagnostic', effectStatus: 'improved',
  factor: {
    name: 'workflow',
    before: '运行时尚未应用 thinking 选择，就提前校验身份；retry2 在 Prompt 前被误拒绝',
    after: '先就绪 Runtime → 校验模型 → 选择 thinking → 核对选择回执 → 发送 Prompt',
    reason: '失败发生在 Prompt 之前，Trace 显示是校验时序错误，而不是 Prompt、Skill 或 CloudOps Tool 的问题。',
  },
  caseCount: 12,
  unit: '同一 12 条冻结 CloudOps Validation；retry3 在第一批 Provider 阶段停止',
  primaryMetric: '运行时身份校验到标准结果提交的阶段门禁',
  hardGates: ['Luna/max 选择回执匹配', 'Prompt 已进入 Session', 'Provider 请求成功', '产生标准结果提交', 'Host 正式 CA/JRA 可用', 'Held-out 未观察'],
  baseline: {
    runId: 'cloudops-luna-max-baseline-validation-20260902-retry2',
    metrics: { runtimeSelectionVerified: 0, promptEntered: 0, providerRequestFailures: 0, toolCalls: 0, canonicalSubmissions: 0, formalScoreProduced: 0, usageAvailable: 0 },
    evidenceRefs: ['eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry1.v1.json', 'eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry2.v1.json', 'scripts/run_cloudops_agent_eval.py', 'tests/test_run_cloudops_agent_eval.py'],
    outputExamples: [{ caseId: 'runtime-admission', input: '同一 Luna Max CloudOps Validation', output: 'retry2 在 Prompt 前因 thinking 身份的提前校验被拒绝。' }],
  },
  candidate: {
    runId: 'cloudops-luna-max-baseline-validation-20260902-retry3',
    metrics: { runtimeSelectionVerified: 1, promptEntered: 1, providerRequestFailures: 8, toolCalls: 0, canonicalSubmissions: 0, formalScoreProduced: 0, usageAvailable: 0, elapsedMs: 318845 },
    evidenceRefs: ['eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry1.v1.json', 'eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry2.v1.json', 'eval/interview-metrics/runs/cloudops-luna-max-baseline-validation-20260902-retry3.v1.json', 'scripts/run_cloudops_agent_eval.py', 'tests/test_run_cloudops_agent_eval.py'],
    outputExamples: [{ caseId: 'runtime-admission', input: '同一 Luna Max CloudOps Validation', output: 'retry3 通过 Luna/max 选择校验并进入 Prompt；随后 8 次 Provider 请求均 fetch failed，未进入 Tool 和正式评分。' }],
  },
  decision: 'reject',
  decisionReason: '校验顺序修复有效，但只证明运行越过了旧阻断；随后 8 次 Provider 网络请求失败，仍无 Tool、标准提交和正式质量分，所以整条候选 Reject。',
  metricDeltas: [
    { metric: 'runtimeSelectionVerified', before: 0, after: 1, delta: 1 },
    { metric: 'promptEntered', before: 0, after: 1, delta: 1 },
    { metric: 'providerRequestFailures', before: 0, after: 8, delta: 8 },
  ],
  outputComparisons: [{ caseId: 'runtime-admission', before: 'Prompt 前被误拒绝。', after: '进入 Prompt，但 Provider 网络请求连续失败。' }],
  action: '只重排 Runtime 就绪、模型校验、thinking 选择和 Prompt 的顺序；模型、Prompt、Skill、Tool、suite、Gold 与 scorer 保持不变。',
  result: '运行时选择从未通过到通过，Prompt 从未进入到已进入；继而暴露 8 次 Provider fetch failure，未产生业务质量分或可计价 usage。',
  resumeBullet: '用 Trace 定位并修复 CloudOps Runtime 选择时序，使候选越过 Prompt admission；Provider 网络仍失败，因此保留 Reject 回执。',
  allowed: '当前证据只支持“运行时选择顺序已修复”，不支持 CloudOps 质量或成本改善。',
  forbidden: '不能声称模型质量改善、CA/JRA 已复验、零成本、生产恢复或已应用到当前系统。',
  openGaps: ['Provider 网络仍阻断', '未产生 Host 正式 CA/JRA', 'retry3 没有可用 usage，本次失败消耗无法计价', '仅在隔离实验环境验证，尚未应用到当前系统', 'Held-out 未观察'],
});

const memoryObservedFailure = ablationExperiment(memoryMaintenance, {
  id: 'memory.maintenance-observed-failure.v0', revision: 'o',
  title: 'Memory Maintenance · 真实晚失败基线',
  status: 'diagnostic', effectStatus: 'unverified', candidateType: 'baseline',
  factor: {
    name: 'diagnostic', before: '单体 Context→Provider→JSONL→Apply', after: '未改；只冻结真实失败边界',
    reason: '先把 834.945 秒后的未闭合 JSONL 作为基线，不能直接从错误字符串猜修复收益。',
  },
  caseCount: 1, unit: '1 条真实 memory-maintenance 失败 Trace',
  baseline: {
    runId: 'memory-maintenance-observed-start', metrics: { terminalCompleted: 0, elapsedMs: 0 },
    evidenceRefs: ['eval/interview-metrics/agent-experiments.v1.json'],
    outputExamples: [{ caseId: 'observed', input: '月度长期记忆整理', output: '开始运行，但没有阶段级完成回执。' }],
  },
  candidate: {
    runId: 'memory-maintenance-observed-jsonl-failure', metrics: { terminalCompleted: 0, jsonReceiptValid: 0, elapsedMs: 834945, stageTimingAvailable: 0, modelTokensAvailable: 0 },
    evidenceRefs: ['eval/interview-metrics/agent-experiments.v1.json'],
    outputExamples: [{ caseId: 'observed', input: '同一真实整理 Run', output: '834.945 秒后因未闭合 JSONL 字符串失败；没有权威持久化结果。' }],
  },
  decision: 'reject', decisionReason: '这是需要优化的真实失败基线，不是模型质量分；后续改动只能先在 private shadow 验证。',
  metricDeltas: [{ metric: 'elapsedMs', before: 0, after: 834945, delta: 834945 }],
  outputComparisons: [{ caseId: 'observed', before: '无阶段级结果。', after: '晚失败且无有效 JSON receipt。' }],
  action: 'Trace Agent 只读定位 Runtime JSONL 截断和可观测性缺口，不直接修改生产 Memory。',
  result: '冻结 834.945 秒、JSON receipt invalid、无持久化证明的真实失败边界。',
  resumeBullet: '将长期记忆维护的晚失败转成可复现的 shadow 优化基线。',
  allowed: '可说明真实失败与后续 shadow 验证边界。',
  forbidden: '不能声称已修复生产 Memory 或定位到具体 Provider。',
});

const memoryV1 = ablationExperiment(memoryMaintenance, {
  id: 'memory.maintenance-shadow-v1', revision: 'p',
  title: 'Memory Maintenance · V1 Replay 消融',
  status: 'rejected', effectStatus: 'unverified',
  factor: {
    name: 'replay', before: '真实单体 Run 无恢复验证', after: 'private shadow + rollback + replay',
    reason: '先验证整理结果能否回滚并在相同输入上幂等重放。',
  },
  baseline: memoryObservedFailure.candidate as ExperimentInput['baseline'],
  candidate: {
    runId: 'memory-maintenance-luna-max-validation-20260902-v1',
    metrics: { curationCases: 5, curationPassed: 5, durableRecallPassed: 4, durableRecallTotal: 4, abstentionPassed: 1, abstentionTotal: 1, vectorCoverage: 0, rollbackPassed: 1, replayPassed: 0, replayOutputsReused: 0, replayStateIdentical: 0, actualModelCallElapsedMs: 224793 },
    evidenceRefs: ['eval/interview-metrics/runs/memory-maintenance-luna-max-validation-20260902.v1.json'],
    outputExamples: [{ caseId: 'aggregate', input: '5 例 public-safe shadow fixture', output: '5/5 决策和 rollback 通过，但 replay 没复用输出，也没恢复相同状态。' }],
  },
  decision: 'reject', decisionReason: 'V1 证明了整理和 rollback，但 replay 不等价、dense coverage 为 0；继续迭代而不进入生产。',
  metricDeltas: [],
  outputComparisons: [{ caseId: 'aggregate', before: '真实 Run 无结果。', after: 'Shadow 决策可验，但 replay 状态不等价。' }],
  action: '只引入隔离 fixture、rollback 和 replay harness；模型与生产数据库不变。',
  result: '整理 5/5、rollback 通过；replay 与 dense 门禁失败，Reject。',
  resumeBullet: 'V1 将 Memory 整理从晚失败推进到可回滚的 shadow 结果，并暴露 replay 不等价。',
  allowed: '可说明阶段性 harness 改善。',
  forbidden: '不能声称完整闭环或生产成功。',
});

const memoryV3 = ablationExperiment(memoryMaintenance, {
  id: 'memory.maintenance-shadow-v3', revision: 'q',
  title: 'Memory Maintenance · V3 精确快照消融',
  status: 'rejected', effectStatus: 'unverified', candidateType: 'single_factor',
  factor: {
    name: 'workflow', before: 'Replay 对残留派生状态比较', after: '保存精确 pre-run snapshot + 复用模型输出，但 replay gate 仍为 false',
    reason: '让 replay 比较同一个逻辑基线，避免重复调用模型和假失败。',
  },
  baseline: memoryV1.candidate as ExperimentInput['baseline'],
  candidate: {
    runId: 'memory-maintenance-luna-max-validation-20260902-v3',
    metrics: { curationCases: 5, curationPassed: 5, durableRecallPassed: 4, durableRecallTotal: 4, abstentionPassed: 1, abstentionTotal: 1, vectorCoverage: 0, rollbackPassed: 1, replayPassed: 0, replayOutputsReused: 1, replayStateIdentical: 1, actualModelCallElapsedMs: 114941 },
    evidenceRefs: ['eval/interview-metrics/runs/memory-maintenance-luna-max-validation-20260902.v3.json'],
    outputExamples: [{ caseId: 'aggregate', input: '同一 5 例 fixture', output: '精确快照、输出复用和状态一致都成立，但 replay.ok 布尔门仍错误为 false。' }],
  },
  decision: 'reject', decisionReason: '实质 replay 条件改善，但 gate 实现仍错误且 dense coverage 为 0；保留失败回执。',
  metricDeltas: [{ metric: 'replayOutputsReused', before: 0, after: 1, delta: 1 }, { metric: 'replayStateIdentical', before: 0, after: 1, delta: 1 }, { metric: 'actualModelCallElapsedMs', before: 224793, after: 114941, delta: -109852 }],
  outputComparisons: [{ caseId: 'aggregate', before: 'Replay 不复用且状态不同。', after: '状态相同且复用输出，但 gate 布尔值仍失败。' }],
  action: '只改 replay snapshot/复用 Workflow，不改模型、Prompt、fixture 或 dense provider。',
  result: 'Replay 实质条件闭合、模型调用耗时下降；布尔门与 dense 仍未过，Reject。',
  resumeBullet: '用精确快照和 content-addressed 复用修正 Memory replay 语义。',
  allowed: '可说明 replay 状态和效率改善。',
  forbidden: '不能因实质条件通过而忽略失败 gate。',
});

const memoryV4 = ablationExperiment(memoryMaintenance, {
  id: 'memory.maintenance-shadow-v4', revision: 'r',
  title: 'Memory Maintenance · V4 Gate 修正消融',
  status: 'rejected', effectStatus: 'unverified', candidateType: 'unknown',
  factor: {
    name: 'workflow', before: 'v3 replay gate false；vector coverage 0', after: 'v4 replay gate true；vector coverage 仍为 0',
    reason: '回执没有保留代码 diff，只能确认 replay gate 翻转，无法诚实断言是哪一行实现导致。',
  },
  baseline: memoryV3.candidate as ExperimentInput['baseline'],
  candidate: {
    runId: 'memory-maintenance-luna-max-validation-20260902-v4',
    metrics: { curationCases: 5, curationPassed: 5, durableRecallPassed: 4, durableRecallTotal: 4, abstentionPassed: 1, abstentionTotal: 1, vectorCoverage: 0, rollbackPassed: 1, replayPassed: 1, replayOutputsReused: 1, replayStateIdentical: 1, receiptJsonValid: 0, actualModelCallElapsedMs: 90642 },
    evidenceRefs: ['eval/interview-metrics/runs/memory-maintenance-luna-max-validation-20260902.v4.json'],
    outputExamples: [{ caseId: 'aggregate', input: '同一 5 例 fixture', output: 'Replay gate 通过，但 vector coverage 仍为 0，且文件并非合法 JSON receipt。' }],
  },
  decision: 'reject', decisionReason: 'V4 的 replay gate 已通过，但 dense coverage 仍为 0，且报告不是合法 JSON receipt；不能以报告中的 pass 代替完整 Promotion。',
  metricDeltas: [{ metric: 'replayPassed', before: 0, after: 1, delta: 1 }, { metric: 'actualModelCallElapsedMs', before: 114941, after: 90642, delta: -24299 }],
  outputComparisons: [{ caseId: 'aggregate', before: 'Replay gate false。', after: 'Replay gate true；dense/receipt 仍失败。' }],
  action: '保留为归因未知的 gate 候选回执；模型、Prompt、fixture 与生产边界冻结，缺代码 diff 的因果归属保持 unknown。',
  result: 'Replay 与耗时改善，但 vector coverage 0、receipt invalid；Reject。',
  resumeBullet: '修正 Memory replay evaluator 后仍由独立 dense/receipt 门禁阻止错误 Promotion。',
  allowed: '可说明 gate 修复与剩余缺口。',
  forbidden: '不能把 v4 报告中的 pass 写成最终成功。',
});

const items = [
  run(
    'enterpriseops-csm-baseline-validation-20260901-v5',
    'EnterpriseOps CSM 执行链',
    'enterpriseops-csm',
    'execution-chain-v5',
    3,
    1,
    26,
    31,
    47,
    0,
    834_945,
    [
      task('agent:preview-csm-1', '客户支持任务 1', 1, true, 11, 11, 18),
      task('agent:preview-csm-2', '客户支持任务 2', 2, false, 8, 10, 16, acceptanceExplanation('csm-2', '根据工单整理恢复计划并写回负责人。', '已完成主要写回，但有一项终态条件没有闭合。', 8, 10, [{ id: 'state', label: '最终状态', status: 'fail', failureOwner: 'agent', explanation: '缺少可复核的完成条件。' }])),
      task('agent:preview-csm-3', '客户支持任务 3', 3, false, 7, 10, 13),
    ],
  ),
  run(
    'enterpriseops-csm-suite-v2-final-state-validation-20260901',
    'EnterpriseOps state-contract Validation',
    'enterpriseops-csm',
    'state-contract-v1',
    3,
    3,
    31,
    31,
    64,
    0,
    758_437,
    [
      task('agent:preview-state-1', '状态合同任务 1', 1, true, 11, 11, 21),
      task('agent:preview-state-2', '状态合同任务 2', 2, true, 10, 10, 22),
      task('agent:preview-state-3', '状态合同任务 3', 3, true, 10, 10, 21),
    ],
  ),
  run(
    'cloudops-bounded-workflow-validation-reject-20260901-v1',
    'CloudOps 证据工作流候选',
    'cloudops-incident-diagnosis',
    'bounded-evidence-workflow',
    12,
    9,
    0,
    0,
    82,
    1,
    1_175_311,
    [task('agent:preview-cloudops-1', '故障定位批次 1', 1, false, 3, 4, 27, acceptanceExplanation('cloudops-1', '定位 checkout 延迟的根因并给出前三条证据。', '答案已生成，但证据方向没有覆盖全部要求。', 0, 1, [{ id: 'evidence', label: '根因与证据方向', status: 'fail', failureOwner: 'agent', explanation: 'Tool 数减少，但 JRA 退化。' }]), 1)],
  ),
  run(
    'memory-optimizer-case-gate-preview',
    'Memory 生命周期行为 Gate',
    'personal-memory-and-rag',
    'memory-optimizer-v3',
    16,
    16,
    48,
    48,
    0,
    0,
    37,
    [task('agent:preview-memory-1', 'Memory 行为 case（16 个独立 case）', 1, true, 48, 48, 0, acceptanceExplanation('memory-gate', '检查旧输入回声、墓碑、项目隔离与反馈。', '16 个独立 case 重复 3 轮，48/48 通过并保存 Trace。', 4, 4, [{ id: 'anti_echo', label: '旧输入不回声', status: 'pass', failureOwner: null, explanation: '未产生旧句候选。' }, { id: 'scope', label: '项目 scope 隔离', status: 'pass', failureOwner: null, explanation: '跨项目内容被过滤。' }, { id: 'tombstone', label: '墓碑不复活', status: 'pass', failureOwner: null, explanation: '已删除候选未复现。' }, { id: 'trace', label: 'Trace 可追溯', status: 'pass', failureOwner: null, explanation: '每轮都有保存回执。' }]))],
  ),
];

const experiments = [
  enterpriseOpsExecution,
  stateContract,
  modelCost,
  enterpriseRag,
  ragTagReadiness,
  ragAnswerBaseline,
  ragAnswerSkill,
  ragAnswerTuned,
  ragAnswerAgentic,
  cloudOpsBaseline,
  cloudOpsEvidenceSearch,
  cloudOps,
  cloudOpsObservationId,
  cloudOpsLuna,
  cloudOpsRuntimeSelectionRepair,
  memory,
  memoryObservedFailure,
  memoryV1,
  memoryV3,
  memoryV4,
  memoryMaintenance,
  traceAgent,
];

export function previewEvalLabRuns(): Record<string, unknown> {
  return {
    schemaVersion: 'rag-ime.eval-lab-run-list.v1',
    ok: true,
    items,
    total: items.length,
    experiments,
    experimentTotal: experiments.length,
    pathSearches: [
      {
        schemaVersion: 'rag-ime.agent-lab-path-search.v1',
        searchId: 'enterpriseops-optimal-path-preview',
        title: 'EnterpriseOps CSM · Validation 最优路径搜索',
        objectiveSummary: '先保证任务完成和 Verifier，再比较 Tool、延迟和成本。',
        metricSummary: 'taskSuccessRate ↑ 0.55、verifierPassRate ↑ 0.25、toolCalls ↓ 0.05、latencyMs ↓ 0.15、apiCostUsd ↓ 0.1',
        frozenControlCount: 5,
        selectedNodeId: 'state-contract',
        selectedPath: [
          { nodeId: 'baseline', decision: 'baseline', reason: '用户指定的质量基线。' },
          { nodeId: 'state-contract', decision: 'keep', reason: 'Validation 硬门禁通过；Held-out 结果单独显示。' },
        ],
        claimStatus: 'supporting',
        claimSummary: '当前匹配对照保留 Sol：Luna 虽将 API 成本估算降低 77.64%，但 task 3/3→2/3、verifier 31/31→30/31，质量门禁失败。',
        candidates: [
          { nodeId: 'baseline', changedFactor: 'workflow', status: 'eligible', metrics: { taskSuccessRate: 2 / 3, verifierPassRate: 28 / 31, toolCalls: 72, latencyMs: 529349.673, apiCostUsd: 3.089711 }, reason: '冻结基线。' },
          { nodeId: 'state-contract', changedFactor: 'workflow', status: 'eligible', metrics: { taskSuccessRate: 1, verifierPassRate: 1, toolCalls: 87, latencyMs: 1112646.229, apiCostUsd: 3.243385 }, reason: '当前匹配 Sol 对照通过 Validation 质量门禁；Held-out 不重跑。' },
          { nodeId: 'luna', changedFactor: 'model', status: 'rejected', metrics: { taskSuccessRate: 2 / 3, verifierPassRate: 30 / 31, toolCalls: 66, latencyMs: 929656.199, apiCostUsd: 0.725239 }, reason: '成本估算 -77.64%、耗时 -16.45%，但质量回退，故 Reject。' },
        ],
        generatedAtMs: 1_788_000_000_000,
      },
    ],
    pathSearchTotal: 1,
  };
}

/*
 * A small public evidence fixture for the mock/preview transport.  Production
 * uses the read-only Python projection; this fixture only makes the same
 * interaction demonstrable without a mounted research archive.
 */
const PREVIEW_EVIDENCE_RUNS: Record<string, any>[] = [
  {
    runId: 'preview-missing-transcript',
    title: 'EnterpriseOps · transcript 缺失',
    family: 'EnterpriseOps CSM',
    sourceId: 'preview-enterpriseops',
    sourceLabel: '预览证据（脱敏）',
    split: 'validation',
    status: 'completed',
    evidenceKind: 'unavailable',
    reportAvailable: false,
    databaseAvailable: true,
    sessionCount: 1,
    transcriptCount: 0,
    transcriptBytes: 0,
    missingTranscriptCount: 1,
    metrics: { taskSuccessCount: 0, taskCount: 1, verifierPassCount: 0, verifierCount: 2 },
    environment: { provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'high', workflowProfile: 'baseline-v1', split: 'validation', workspace: 'source-local 沙盒', network: '禁用' },
    tasks: [{ taskIndex: 1, taskLabel: 'Task 1 · transcript 缺失', title: '缺少原始 transcript 的任务', transcriptAvailable: false, transcriptSha256: '', transcriptBytes: 0, jsonlLines: 0, userMessages: 0, assistantMessages: 0, toolCalls: 3, toolFailures: 0, toolNames: ['find_customer'], externalSessionRef: '', model: 'gpt-5.6-sol', thinking: 'high', executionMode: 'per_action', createdAtMs: 1, updatedAtMs: 2, evidenceStatus: 'transcript_missing', taskSucceeded: false, terminalEvent: 'turn_completed', verifierPassed: 0, verifierTotal: 2, latencyMs: 120000 }],
    artifacts: [],
    updatedAtMs: 8,
  },
  {
    runId: 'preview-enterpriseops-execution', title: 'EnterpriseOps · 执行链修复', family: 'EnterpriseOps CSM', sourceId: 'preview-enterpriseops', sourceLabel: '预览证据（脱敏）', split: 'validation', status: 'completed', evidenceKind: 'transcript_and_report', reportAvailable: true, databaseAvailable: true, sessionCount: 1, transcriptCount: 1, transcriptBytes: 4096, metrics: { taskSuccessCount: 1, taskCount: 1, verifierPassCount: 26, verifierCount: 31, toolCalls: 47 }, environment: { provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'max', workflowProfile: 'execution-chain-v5', split: 'validation', transport: 'loopback-http-v1', timeoutSeconds: 900, executionModes: ['per_action'], workspace: 'source-local 沙盒', network: '禁用', publicConfig: { workflowProfile: 'execution-chain-v5' }, traceCount: 1 }, tasks: [{ taskIndex: 1, taskLabel: 'Task 1 · 客户支持', title: '客户支持任务', transcriptAvailable: true, transcriptSha256: HASH('a'), transcriptBytes: 4096, jsonlLines: 18, userMessages: 2, assistantMessages: 5, toolCalls: 47, toolFailures: 0, toolNames: ['find_customer', 'update_entitlement', 'create_case'], externalSessionRef: 'preview-csm-1', model: 'gpt-5.6-sol', thinking: 'max', executionMode: 'per_action', createdAtMs: 1, updatedAtMs: 2, evidenceStatus: 'available', taskSucceeded: true, terminalEvent: 'turn_completed', verifierPassed: 26, verifierTotal: 31, latencyMs: 376364, cleanupStatus: 'deleted', successfulToolCalls: 47, failedVerifierIndexes: [7, 12, 19, 23, 28] }], artifacts: [{ kind: 'report', label: '公开评测报告', available: true, bytes: 1200, sha256: HASH('b') }, { kind: 'transcripts', label: 'JSONL transcript（1 份）', available: true, bytes: 4096, sha256: '' }], updatedAtMs: 10,
  },
  {
    runId: 'preview-enterpriseops-state', title: 'EnterpriseOps · 状态合同', family: 'EnterpriseOps CSM', sourceId: 'preview-enterpriseops', sourceLabel: '预览证据（脱敏）', split: 'validation', status: 'completed', evidenceKind: 'transcript_and_report', reportAvailable: true, databaseAvailable: true, sessionCount: 1, transcriptCount: 1, transcriptBytes: 3072, metrics: { taskSuccessCount: 3, taskCount: 3, verifierPassCount: 31, verifierCount: 31, toolCalls: 64 }, environment: { provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'max', workflowProfile: 'state-contract-v1', split: 'validation', transport: 'loopback-http-v1', timeoutSeconds: 900, executionModes: ['per_action'], workspace: 'source-local 沙盒', network: '禁用', traceCount: 3 }, tasks: [{ taskIndex: 1, taskLabel: 'Task 1 · 状态合同', title: '状态合同任务', transcriptAvailable: true, transcriptSha256: HASH('c'), transcriptBytes: 3072, jsonlLines: 22, userMessages: 2, assistantMessages: 6, toolCalls: 21, toolFailures: 0, toolNames: ['find_customer', 'find_locations', 'update_case'], externalSessionRef: 'preview-state-1', model: 'gpt-5.6-sol', thinking: 'max', executionMode: 'per_action', createdAtMs: 1, updatedAtMs: 2, evidenceStatus: 'available', taskSucceeded: true, terminalEvent: 'turn_completed', verifierPassed: 11, verifierTotal: 11, latencyMs: 240000, cleanupStatus: 'deleted', successfulToolCalls: 21 }], artifacts: [{ kind: 'report', label: '公开评测报告', available: true, bytes: 1200, sha256: HASH('d') }], updatedAtMs: 9,
  },
  {
    runId: 'preview-rag-hybrid', title: 'Enterprise RAG · Hybrid + Rerank', family: 'Enterprise RAG', sourceId: 'preview-rag', sourceLabel: '预览证据（脱敏）', split: 'validation', status: 'completed', evidenceKind: 'transcript_and_report', reportAvailable: true, databaseAvailable: true, sessionCount: 1, transcriptCount: 1, transcriptBytes: 2048, metrics: { recallAt10: 0.955357, mrr: 0.867188, ndcgAt10: 0.887203 }, environment: { provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'max', workflowProfile: 'retrieval-validation', split: 'validation', executionModes: ['read_only'], workspace: 'Knowledge 沙盒', network: '禁用', knowledge: { available: true, documentCount: 5101, chunkCount: 29846, denseVectorCount: 29846, graphNodeCount: 0, graphEdgeCount: 0, parserMode: 'builtin', configRevision: 1 }, publicConfig: { candidateDepth: 40, finalDepth: 10, chunking: { strategy: 'general', size: 1200, overlap: 160 }, embedding: { dimensions: 384 }, reranker: 'Qwen3-Reranker-0.6B' }, traceCount: 1 }, tasks: [{ taskIndex: 1, taskLabel: 'Query 1 · 跨版本控制条款', title: '检索 Validation query', transcriptAvailable: true, transcriptSha256: HASH('e'), transcriptBytes: 2048, jsonlLines: 12, userMessages: 1, assistantMessages: 3, toolCalls: 6, toolFailures: 0, toolNames: ['knowledge_search', 'knowledge_read'], externalSessionRef: 'preview-rag-1', model: 'gpt-5.6-sol', thinking: 'max', executionMode: 'read_only', createdAtMs: 1, updatedAtMs: 2, evidenceStatus: 'available', taskSucceeded: true, terminalEvent: 'turn_completed', latencyMs: 120000 }], artifacts: [{ kind: 'knowledge', label: 'Knowledge 数据库快照', available: true, bytes: 263700000, sha256: HASH('f') }], updatedAtMs: 8,
  },
  {
    runId: 'preview-cloudops', title: 'CloudOps · 证据检索', family: 'CloudOps', sourceId: 'preview-cloudops', sourceLabel: '预览证据（脱敏）', split: 'validation', status: 'completed', evidenceKind: 'transcript_and_report', reportAvailable: true, databaseAvailable: true, sessionCount: 1, transcriptCount: 1, transcriptBytes: 1800, metrics: { answerCoverage: 1, ca: 0.75, jra: 0.75, toolCalls: 82, failedToolCalls: 1 }, environment: { provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'max', workflowProfile: 'evidence-search-v2', split: 'validation', executionModes: ['read_only'], workspace: 'source-local 沙盒', network: '按合同限制', publicConfig: { maxReadsPerCase: 6, searchCalls: 22, readCalls: 46 }, traceCount: 4 }, tasks: [{ taskIndex: 1, taskLabel: 'Batch 1 · 4 cases', title: 'CloudOps blind evaluation batch-1', transcriptAvailable: true, transcriptSha256: HASH('g'), transcriptBytes: 1800, jsonlLines: 20, userMessages: 1, assistantMessages: 6, toolCalls: 29, toolFailures: 1, toolNames: ['cloudops_benchmark'], externalSessionRef: 'preview-cloudops-1', model: 'gpt-5.6-sol', thinking: 'max', executionMode: 'read_only', createdAtMs: 1, updatedAtMs: 2, evidenceStatus: 'available', taskSucceeded: true, terminalEvent: 'turn_completed', verifierPassed: 0, verifierTotal: 0, latencyMs: 390000, runtimeErrorType: 'tool_failure_once' }], artifacts: [{ kind: 'report', label: 'CloudOps 报告', available: true, bytes: 1500, sha256: HASH('h') }], updatedAtMs: 7,
  },
  {
    runId: 'cloudops--cloudops-luna-max-baseline-validation-20260902',
    title: 'CloudOps · Luna Max baseline Validation（失败）',
    family: 'CloudOps',
    sourceId: 'preview-cloudops-luna',
    sourceLabel: '预览回执（仅汇总，无对话原文）',
    split: 'validation',
    status: 'failed',
    evidenceKind: 'report_only',
    reportAvailable: true,
    databaseAvailable: false,
    sessionCount: 3,
    transcriptCount: 0,
    transcriptBytes: 0,
    missingTranscriptCount: 0,
    metrics: {
      transcriptToolCalls: 278,
      failedTranscriptToolCalls: 14,
      inputTokens: 916112,
      outputTokens: 57057,
      cacheReadTokens: 18809344,
      latencyMs: 1718516,
      thirdBatchTimeout: 1,
      abortTimeout: 1,
      hostFormalCaJraAvailable: 0,
      heldOutConsumed: 0,
      sourceLocal: 1,
      installed: 0,
    },
    environment: {
      provider: 'openai-codex',
      model: 'gpt-5.6-luna',
      thinking: 'max',
      workflowProfile: 'baseline-v1',
      split: 'validation',
      transport: 'loopback-http-v1',
      timeoutSeconds: 900,
      workspace: '隔离实验环境（未应用到当前系统）',
      network: '未记录',
      publicConfig: {
        hostFormalScoring: '未运行',
        heldOutConsumed: false,
        transcriptToolCalls: 278,
        failedTranscriptToolCalls: 14,
        thirdBatchTimeout: true,
        abortTimeout: true,
      },
    },
    tasks: [],
    artifacts: [{ kind: 'report', label: 'CloudOps Luna failed Validation 回执（无对话原文）', available: true, bytes: 759, sha256: '7c0f19e7d4db783e21bb67047a160405d994f81789b63ccb8f7a0a886bb414a5' }],
    updatedAtMs: 1_788_000_000_000,
  },
  {
    runId: 'preview-memory', title: 'Memory · 生命周期行为 Gate', family: 'Memory', sourceId: 'preview-memory', sourceLabel: '预览证据（脱敏）', split: 'shadow_validation', status: 'completed', evidenceKind: 'transcript_only', reportAvailable: false, databaseAvailable: true, sessionCount: 1, transcriptCount: 1, transcriptBytes: 1400, metrics: { behaviorCases: 16, repeats: 3, traces: 48 }, environment: { provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'max', workflowProfile: 'memory-optimizer-v3', split: 'shadow_validation', executionModes: ['read_only'], workspace: 'Memory shadow 沙盒', network: '禁用', traceCount: 48 }, tasks: [{ taskIndex: 1, taskLabel: '16 cases × 3 轮', title: 'Memory behavior gate', transcriptAvailable: true, transcriptSha256: HASH('i'), transcriptBytes: 1400, jsonlLines: 16, userMessages: 4, assistantMessages: 4, toolCalls: 0, toolFailures: 0, toolNames: [], externalSessionRef: 'preview-memory-1', model: 'gpt-5.6-sol', thinking: 'max', executionMode: 'read_only', createdAtMs: 1, updatedAtMs: 2, evidenceStatus: 'available', taskSucceeded: true, terminalEvent: 'turn_completed', verifierPassed: 48, verifierTotal: 48, latencyMs: 37 }], artifacts: [], updatedAtMs: 6,
  },
  {
    runId: 'preview-memory-maintenance-v5', title: 'Memory Maintenance · Luna v5', family: 'Memory Maintenance', sourceId: 'preview-memory-maintenance', sourceLabel: '预览回执（无原文）', split: 'shadow_validation', status: 'completed', evidenceKind: 'report_only', reportAvailable: true, databaseAvailable: false, sessionCount: 0, transcriptCount: 0, transcriptBytes: 0, metrics: { curationPassed: 5, curationCases: 5, durableRecallPassed: 4, durableRecallTotal: 4, abstentionPassed: 1, abstentionTotal: 1, vectorCoverage: 1, modelTokensAvailable: 0 }, environment: { provider: 'openai-codex', model: 'gpt-5.6-luna', thinking: 'max', workflowProfile: 'memory-maintenance-shadow-v5', split: 'shadow_validation', executionModes: ['read_only'], workspace: 'private shadow', network: '按 CLI 合同', pricingUsage: 'Provider token/账单回执不可用', billing: { status: 'not_provided' } }, tasks: [], artifacts: [{ kind: 'report', label: 'Memory v5 无原文 JSON 回执', available: true, bytes: 4200, sha256: HASH('m') }], updatedAtMs: 7,
  },
  {
    runId: 'preview-luna', title: 'Sol / Luna · 质量优先成本门禁', family: 'EnterpriseOps model cost', sourceId: 'preview-cost', sourceLabel: '预览证据（脱敏）', split: 'validation', status: 'completed', evidenceKind: 'report_only', reportAvailable: true, databaseAvailable: false, sessionCount: 0, transcriptCount: 0, transcriptBytes: 0, metrics: { taskSuccessCount: 2, taskCount: 3, verifierPassCount: 30, verifierCount: 31, toolCalls: 66 }, environment: { provider: 'openai-codex', model: 'gpt-5.6-luna', thinking: 'max', workflowProfile: 'state-contract-v1', split: 'validation', executionModes: ['per_action'], workspace: 'source-local 沙盒', network: '按任务 Tool 合同', qualityGate: 'Reject：2/3 task、30/31 verifier', pricingUsage: 'Runtime DB usage + 冻结价格来源；不是账单', usageReceipt: { available: true, inputTokens: 183923, outputTokens: 33686, cachedInputTokens: 3392000, totalTokens: 3609609 }, costEstimate: { totalCostUsd: '0.725239', comparisonBaselineUsd: '3.243385', decreasePercent: '77.6394' }, billing: { status: 'not_provided' }, pricingIdentity: { model: 'gpt-5.6-luna', provider: 'openai', currency: 'USD', unit: 'per_million_tokens' } }, tasks: [], artifacts: [{ kind: 'report', label: '匹配 Luna Validation Reject 与成本估算回执', available: true, bytes: 2200, sha256: HASH('j') }], updatedAtMs: 8,
  },
  {
    runId: 'preview-trace', title: 'Trace Agent · 历史闭环', family: 'Trace Agent', sourceId: 'preview-trace', sourceLabel: '预览证据（脱敏）', split: 'historical_replay', status: 'open_gap', evidenceKind: 'report_only', reportAvailable: true, databaseAvailable: false, sessionCount: 0, transcriptCount: 0, transcriptBytes: 0, metrics: { publicHistoricalCasesPrepared: 3, realPredictionCases: 0 }, environment: { model: 'gpt-5.6-sol', thinking: 'max', workflowProfile: 'trace-skill-envelope-v1', split: 'historical_replay', workspace: 'Trace 证据沙盒', network: '禁用' }, tasks: [], artifacts: [{ kind: 'report', label: 'Trace 独立审计报告', available: true, bytes: 3400, sha256: HASH('k') }], updatedAtMs: 4,
  },
];

function experimentReportRuns(): Record<string, any>[] {
  const existing = new Set(PREVIEW_EVIDENCE_RUNS.map((run) => String(run.runId)));
  const publicTranscriptAliases = new Set([
    'enterpriseops-csm-baseline-validation-20260901-v5',
    'enterpriseops-csm-suite-v2-final-state-validation-20260901',
  ]);
  return experiments.flatMap((raw) => {
    const item = raw as Record<string, any>;
    return (['baseline', 'candidate'] as const).flatMap((sideName) => {
      const side = item[sideName] as Record<string, any> | undefined;
      const runId = String(side?.runId || '');
      // `items` is a compact preview of aggregate run outcomes, not a public
      // transcript archive. An experiment may share its runId with an item,
      // but that must not turn the aggregate row into synthetic dialogue.
      if (!runId || existing.has(runId) || publicTranscriptAliases.has(runId)) return [];
      existing.add(runId);
      const refs = Array.isArray(side?.evidenceRefs) ? side.evidenceRefs.filter((value: unknown): value is string => typeof value === 'string') : [];
      const title = `${String(item.title || item.experimentId)} · ${sideName === 'baseline' ? '基线' : '候选'}回执`;
      return [{
        runId,
        title,
        family: String(item.vertical || 'Agent Lab'),
        sourceId: `preview-experiment-${String(item.experimentId || 'unknown')}`,
        sourceLabel: '实验账本回执（原始对话未公开）',
        split: String(item.dataset?.split || 'validation'),
        status: sideName === 'baseline' ? 'baseline' : String(item.status || 'unknown'),
        evidenceKind: 'report_only',
        reportAvailable: true,
        databaseAvailable: false,
        sessionCount: 0,
        transcriptCount: 0,
        transcriptBytes: 0,
        missingTranscriptCount: 0,
        metrics: side?.metrics ?? {},
        environment: {
          workflowProfile: String(item.experimentId || ''),
          split: String(item.dataset?.split || 'validation'),
          workspace: 'source-local / public projection',
          network: '按实验合同',
          publicConfig: {
            experimentId: item.experimentId,
            relation: sideName,
            candidateType: item.candidateType,
            manifestSha256: item.dataset?.manifestSha256,
            heldOutConsumed: item.dataset?.heldOutConsumed ?? false,
            evidenceRefs: refs,
          },
        },
        tasks: [],
        artifacts: refs.map((ref: string) => ({ kind: 'report_ref', label: ref, available: true, bytes: 0, sha256: '' })),
        updatedAtMs: Number(item.importedAtMs || 1_788_000_000_000),
      }];
    });
  });
}

const ALL_PREVIEW_EVIDENCE_RUNS = [...PREVIEW_EVIDENCE_RUNS, ...experimentReportRuns()];

function previewEvidenceSources(): Record<string, unknown>[] {
  const rows = new Map<string, {
    label: string;
    runCount: number;
    sessionCount: number;
    transcriptCount: number;
    transcriptBytes: number;
    missingTranscriptCount: number;
    reportOnlyRunCount: number;
  }>();
  for (const run of ALL_PREVIEW_EVIDENCE_RUNS) {
    const sourceId = String(run.sourceId || 'unknown');
    const row = rows.get(sourceId) ?? {
      label: String(run.sourceLabel || sourceId),
      runCount: 0,
      sessionCount: 0,
      transcriptCount: 0,
      transcriptBytes: 0,
      missingTranscriptCount: 0,
      reportOnlyRunCount: 0,
    };
    row.runCount += 1;
    row.sessionCount += Number(run.sessionCount || 0);
    const reportOnly = run.evidenceKind === 'report_only';
    row.transcriptCount += reportOnly ? 0 : Number(run.transcriptCount || 0);
    row.transcriptBytes += Number(run.transcriptBytes || 0);
    row.missingTranscriptCount += reportOnly ? 0 : Math.max(0, Number(run.sessionCount || 0) - Number(run.transcriptCount || 0));
    row.reportOnlyRunCount += reportOnly && run.reportAvailable ? 1 : 0;
    rows.set(sourceId, row);
  }
  return Array.from(rows, ([sourceId, row]) => ({ sourceId, ...row, available: true }));
}

const PREVIEW_EVIDENCE_DETAILS: Record<string, Record<string, unknown>> = {
  'preview-enterpriseops-execution': {
    origin: 'preview',
    turns: [
      { kind: 'message', role: 'user', text: '请按工单要求确认客户状态并完成必要的支持操作。', timestampMs: 1, entryRef: 'u1' },
      { kind: 'tool_call', role: 'assistant', toolName: 'find_customer', text: '调用工具：find_customer', argumentKeys: ['customerId'], timestampMs: 2, entryRef: 'a1' },
      { kind: 'tool_result', role: 'tool', toolName: 'find_customer', status: 'completed', text: '返回客户当前状态与可用 entitlement。', timestampMs: 3, entryRef: 't1' },
      { kind: 'message', role: 'assistant', text: '我已先读取状态，再按依赖顺序执行写回并准备终态核验。', timestampMs: 4, entryRef: 'a2' },
      { kind: 'tool_call', role: 'assistant', toolName: 'create_case', text: '调用工具：create_case', argumentKeys: ['accountId', 'entitlementId'], timestampMs: 5, entryRef: 'a3' },
      { kind: 'tool_result', role: 'tool', toolName: 'create_case', status: 'completed', text: '创建结果已返回，未展示内部字段。', timestampMs: 6, entryRef: 't3' },
      { kind: 'message', role: 'assistant', text: '执行完成，等待 Host verifier 对终态和清理结果验收。', timestampMs: 7, entryRef: 'a4' },
    ],
    tools: [{ toolName: 'find_customer', status: 'completed', text: '返回客户状态。', timestampMs: 3 }, { toolName: 'create_case', status: 'completed', text: '创建结果已返回。', timestampMs: 6 }],
    session: { title: '客户支持任务', model: 'gpt-5.6-sol', thinking: 'max', executionMode: 'per_action', sessionMode: 'assistant', messageCount: 7 },
    environment: PREVIEW_EVIDENCE_RUNS.find((run) => run.runId === 'preview-enterpriseops-execution')!.environment,
    task: PREVIEW_EVIDENCE_RUNS.find((run) => run.runId === 'preview-enterpriseops-execution')!.tasks[0],
    report: { status: 'completed', decision: '保留公开回执', metrics: PREVIEW_EVIDENCE_RUNS.find((run) => run.runId === 'preview-enterpriseops-execution')!.metrics },
    protected: { sourceReadOnly: true, thinkingShown: false, systemPromptShown: false, hiddenGoldShown: false, rawSqlShown: false, pathsAndCredentialsShown: false, redactions: ['内部推理', '隐藏标准答案', 'SQL/凭据', '本机路径'] },
  },
};

export function previewEvalLabEvidence(request?: { query?: Record<string, string> }): Record<string, unknown> {
  const runId = request?.query?.runId || '';
  const taskIndex = Number(request?.query?.taskIndex || 1);
  const run = resolvePreviewEvidenceRun(runId);
  const selected = run ? PREVIEW_EVIDENCE_DETAILS[run.runId] : undefined;
  const generated = run ? previewDetailForRun(run, taskIndex) : undefined;
  const detail = selected
    ? { status: 'available', runId: runId || run?.runId || '', taskIndex: taskIndex || 1, ...selected }
    : generated
      ? { ...generated, runId: runId || generated.runId }
      : undefined;
  return {
    schemaVersion: 'rag-ime.eval-lab-evidence.v1',
    ok: true,
    source: { available: true, label: '预览证据（脱敏）', runCount: ALL_PREVIEW_EVIDENCE_RUNS.length, sessionCount: ALL_PREVIEW_EVIDENCE_RUNS.reduce((sum, run) => sum + run.sessionCount, 0), transcriptCount: ALL_PREVIEW_EVIDENCE_RUNS.reduce((sum, run) => sum + (run.evidenceKind === 'report_only' ? 0 : run.transcriptCount), 0), transcriptBytes: ALL_PREVIEW_EVIDENCE_RUNS.reduce((sum, run) => sum + run.transcriptBytes, 0), missingTranscriptCount: ALL_PREVIEW_EVIDENCE_RUNS.reduce((sum, run) => sum + (run.evidenceKind === 'report_only' ? 0 : Math.max(0, run.sessionCount - run.transcriptCount)), 0), reportOnlyRunCount: ALL_PREVIEW_EVIDENCE_RUNS.reduce((sum, run) => sum + (run.evidenceKind === 'report_only' && run.reportAvailable ? 1 : 0), 0), generatedAtMs: 1_788_000_000_000 },
    sources: previewEvidenceSources(),
    runs: ALL_PREVIEW_EVIDENCE_RUNS,
    total: ALL_PREVIEW_EVIDENCE_RUNS.length,
    ...(detail ? { detail } : {}),
  };
}

function resolvePreviewEvidenceRun(runId: string): Record<string, any> | undefined {
  if (!runId) return undefined;
  const exact = ALL_PREVIEW_EVIDENCE_RUNS.find((item) => item.runId === runId);
  if (exact) return exact;
  // Preview run IDs intentionally remain small and deterministic, while the
  // real ledger uses long source-local IDs.  Resolve those IDs to the same
  // public fixture so every “查看逐轮证据” button is useful in the mock app.
  const value = runId.toLocaleLowerCase();
  if (value.includes('luna') || value.includes('cost')) return PREVIEW_EVIDENCE_RUNS.find((item) => item.runId === 'preview-luna');
  if (value.includes('trace')) return PREVIEW_EVIDENCE_RUNS.find((item) => item.runId === 'preview-trace');
  if (value.includes('cloudops')) return PREVIEW_EVIDENCE_RUNS.find((item) => item.runId === 'preview-cloudops');
  if (value.includes('rag') || value.includes('retrieval')) return PREVIEW_EVIDENCE_RUNS.find((item) => item.runId === 'preview-rag-hybrid');
  if (value.includes('memory')) return PREVIEW_EVIDENCE_RUNS.find((item) => item.runId === 'preview-memory');
  if (value.includes('state-contract') || value.includes('state-validation') || value.includes('final-state')) return PREVIEW_EVIDENCE_RUNS.find((item) => item.runId === 'preview-enterpriseops-state');
  if (value.includes('enterpriseops')) return PREVIEW_EVIDENCE_RUNS.find((item) => item.runId === 'preview-enterpriseops-execution');
  return undefined;
}

function previewDetailForRun(run: Record<string, any>, taskIndex: number): Record<string, unknown> {
  const task = run.tasks?.find((item: Record<string, any>) => item.taskIndex === taskIndex) || run.tasks?.[0];
  if (!task) {
    return {
      status: 'report_only', origin: 'preview', runId: run.runId, taskIndex: 0, summary: run,
      environment: run.environment || {}, turns: [], tools: [],
      ...(run.reportAvailable ? { report: { available: true, status: run.status, metrics: run.metrics, decision: run.status === 'open_gap' ? '待补证据' : '保留这份运行回执；不代表保留候选' } } : {}),
      protected: { sourceReadOnly: true, thinkingShown: false, systemPromptShown: false, hiddenGoldShown: false, rawSqlShown: false, pathsAndCredentialsShown: false, redactions: ['内部推理', '隐藏标准答案', 'SQL/凭据', '本机路径'] },
    };
  }
  if (task.transcriptAvailable === false) {
    return {
      status: 'transcript_missing', origin: 'preview', runId: run.runId, taskIndex: task.taskIndex, task, summary: run,
      environment: run.environment || {}, turns: [], tools: [],
      ...(run.reportAvailable ? { report: { available: true, status: run.status, metrics: run.metrics, decision: '原始 transcript 缺失，保留报告边界' } } : {}),
      protected: { sourceReadOnly: true, thinkingShown: false, systemPromptShown: false, hiddenGoldShown: false, rawSqlShown: false, pathsAndCredentialsShown: false, redactions: ['内部推理', '隐藏标准答案', 'SQL/凭据', '本机路径'] },
    };
  }
  const toolNames = task.toolNames || [];
  const turns: Record<string, unknown>[] = [{ kind: 'message', role: 'user', text: `请完成 ${task.title || '这条冻结评测任务'}，并返回可验收结果。`, timestampMs: 1, entryRef: 'preview-user' }];
  toolNames.slice(0, 8).forEach((name: string, index: number) => {
    turns.push({ kind: 'tool_call', role: 'assistant', toolName: name, text: `调用工具：${name}`, argumentKeys: ['request'], timestampMs: index + 2, entryRef: `preview-call-${index}` });
    turns.push({ kind: 'tool_result', role: 'tool', toolName: name, status: index === toolNames.length - 1 && task.toolFailures ? 'failed' : 'completed', text: index === toolNames.length - 1 && task.toolFailures ? '工具失败回执（预览）' : '工具返回了可核对的结果（预览）。', timestampMs: index + 2.5, entryRef: `preview-result-${index}` });
  });
  turns.push({ kind: 'message', role: 'assistant', text: task.taskSucceeded === false ? '任务结束，保留失败项供人工复核。' : '任务结束，等待 Host 验收。', timestampMs: 20, entryRef: 'preview-assistant' });
  return {
    status: 'available', origin: 'preview', runId: run.runId, taskIndex: task.taskIndex, task,
    session: { title: task.title, model: task.model, thinking: task.thinking, executionMode: task.executionMode, sessionMode: 'assistant', messageCount: turns.length },
    environment: run.environment || {}, turns,
    tools: turns.filter((item) => item.kind === 'tool_result').map((item) => ({ toolName: item.toolName, status: item.status, text: item.text, timestampMs: item.timestampMs })),
    ...(run.reportAvailable ? { report: { status: run.status, metrics: run.metrics, decision: '预览公开报告样例' } } : {}),
    protected: { sourceReadOnly: true, thinkingShown: false, systemPromptShown: false, hiddenGoldShown: false, rawSqlShown: false, pathsAndCredentialsShown: false, redactions: ['内部推理', '隐藏标准答案', 'SQL/凭据', '本机路径'] },
  };
}
