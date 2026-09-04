import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { previewEvalLabEvidence, previewEvalLabRuns } from '@/app/preview-eval-lab-data';
import { PawOsDesktopProvider, type PawOsWindowRequest } from '@/features/paw-os/surface-context';
import { MockControlTransport } from '@/test/mock-transport';
import { EvalLabFeature } from './index';

vi.mock('@/paw-os/apps/PawRoomWorkspace', () => ({
  PawRoomWorkspace: ({ participantProcessLocation, record, recordId }: { participantProcessLocation?: string; record?: { title?: string }; recordId: string }) => (
    <section aria-label="Agent Lab Room workspace" data-participant-process-location={participantProcessLocation} data-room-id={recordId}>
      <h3>{record?.title ?? '正在恢复 Room'}</h3>
    </section>
  ),
}));

afterEach(cleanup);

const response = {
  schemaVersion: 'rag-ime.eval-lab-run-list.v1',
  ok: true,
  total: 1,
  experimentTotal: 1,
  pathSearchTotal: 1,
  pathSearches: [{
    schemaVersion: 'rag-ime.agent-lab-path-search.v1',
    searchId: 'enterpriseops-optimal-path-v1',
    title: 'EnterpriseOps CSM · Validation 最优路径搜索',
    objectiveSummary: '完成全部任务，再比较成本；延迟只用于诊断。',
    metricSummary: 'taskSuccessRate ↑ 0.55、latencyMs ↓ 0.15、apiCostUsd ↓ 0.1',
    frozenControlCount: 5,
    selectedNodeId: 'state-contract',
    selectedPath: [
      { nodeId: 'baseline', decision: 'baseline', reason: '用户指定基线。' },
      { nodeId: 'state-contract', decision: 'keep', reason: '硬门禁通过。' },
    ],
    claimStatus: 'insufficient_evidence',
    claimSummary: '质量门禁通过，但成本回执尚未提供。',
    candidates: [
      { nodeId: 'state-contract', changedFactor: 'workflow', status: 'eligible', metrics: { taskSuccessRate: 1, verifierPassRate: 1, latencyMs: 100 }, reason: '硬门禁通过。' },
      { nodeId: 'luna', changedFactor: 'model', status: 'eligible', metrics: { taskSuccessRate: 1, verifierPassRate: 1, latencyMs: 150 }, reason: '质量持平、效率较低。' },
    ],
    generatedAtMs: 4,
  }],
  experiments: [{
    schemaVersion: 'rag-ime.agent-lab-experiment.v1',
    experimentId: 'enterpriseops-csm-v2',
    revisionSha256: 'c'.repeat(64),
    title: 'EnterpriseOps CSM workflow',
    vertical: 'enterpriseops',
    evaluationKind: 'rag_retrieval',
    status: 'kept',
    claimStatus: 'headline',
    businessProblem: '让复杂客户支持任务可以被验证。',
    whyAgent: '任务需要跨实体状态与依赖关系。',
    dataset: { datasetId: 'suite-v2', split: 'validation', caseCount: 2, unit: '冻结任务', manifestSha256: 'd'.repeat(64), heldOutConsumed: false },
    scoring: { primaryMetric: 'task success', evaluatorAuthority: 'host', goldHiddenFromAgent: true, hardGates: ['cleanup'] },
    factors: [{ name: 'workflow', before: '直接执行', after: '状态合同', reason: '跨实体任务需要终态核验。' }],
    frozenControls: [{ name: 'case_set', value: '2 条冻结任务', reason: '保证前后可比。' }],
    baseline: { runId: 'enterpriseops-suite-v2-final-validation-20260901', metrics: { taskSuccess: 0.5 }, evidenceRefs: ['receipt-baseline'] },
    candidate: { runId: 'enterpriseops-suite-v2-final-validation-20260901', metrics: { taskSuccess: 1 }, evidenceRefs: ['receipt-candidate'] },
    comparison: { decision: 'keep', decisionReason: 'Candidate completed more tasks.', metricDeltas: [{ metric: 'taskSuccess', before: 0.5, after: 1, delta: 0.5 }] },
    star: { situation: '有失败任务。', task: '找出原因。', action: '比较候选。', result: '保留候选。' },
    claim: { resumeBullet: 'Validation only.', allowed: 'Validation evidence.', forbidden: 'Production or Held-out success.' },
    openGaps: ['Held-out remains separate.'],
    importedAtMs: 3,
  }],
  items: [{
    schemaVersion: 'rag-ime.eval-lab-run.v1',
    runId: 'enterpriseops-csm-validation-20260901',
    title: 'EnterpriseOps CSM',
    suiteId: 'enterpriseops-csm',
    split: 'validation',
    workflowProfile: 'baseline-v1',
    evaluationKind: 'retrieval',
    repairPlan: { targetLayers: ['tool', 'workflow'] },
    status: 'completed',
    taskCount: 2,
    taskSuccessCount: 1,
    taskSuccessRate: 0.5,
    verifierPassCount: 14,
    verifierCount: 16,
    verifierPassRate: 0.875,
    toolCalls: 19,
    failedToolCalls: 0,
    latencyMs: 120_000,
    sourceDatabaseSha256: 'a'.repeat(64),
    sourceReportSha256: 'b'.repeat(64),
    createdAtMs: 1,
    updatedAtMs: 2,
    tasks: [
      {
        sessionId: 'agent:real-1', title: 'Task 1', taskAlias: 'Task 1', taskIndex: 1,
        taskSucceeded: true, terminalEvent: 'turn_completed', verifierPassed: 11,
        verifierTotal: 11, toolCalls: 8, failedToolCalls: 0, latencyMs: 50_000,
      },
      {
        sessionId: 'agent:real-2', title: 'Task 2', taskAlias: 'Task 2', taskIndex: 2,
        taskSucceeded: false, terminalEvent: 'turn_completed', verifierPassed: 3,
        verifierTotal: 5, toolCalls: 11, failedToolCalls: 0, latencyMs: 70_000,
        explanation: {
          caseId: 'case-csm-2',
          businessRequest: { normalizedText: '根据客户工单整理恢复计划，并说明下一步。' },
          agentOutcome: { normalizedSummary: '我会先确认影响范围，再给出负责人和时间点。' },
          acceptance: {
            passed: 1,
            total: 2,
            items: [
              { id: 'impact', label: '影响范围', status: 'pass', failureOwner: null, explanation: '已说明客户范围。' },
              { id: 'verification', label: '验收方式', status: 'fail', failureOwner: 'agent', explanation: '缺少可复核的完成条件。' },
            ],
          },
        },
      },
    ],
  }],
} as const;

const answerEvidenceResponse = {
  ...response,
  experiments: [{
    ...response.experiments[0],
    experimentId: 'enterprise-rag-answer-evidence-v1',
    title: 'Enterprise RAG answer evidence',
    evaluationKind: 'answer_evidence',
    status: 'rejected',
    claimStatus: 'diagnostic',
    effectStatus: 'regressed',
    dataset: { ...response.experiments[0].dataset, caseCount: 4, unit: '4 条冻结答案任务' },
    baseline: {
      ...response.experiments[0].baseline,
      metrics: {
        answerCaseCount: 4,
        answerJudgeCorrectnessRate: 0.5,
        highLevelFactCoverage: 2 / 3,
        citationFactCoverage: 2 / 9,
        answerableCitationSupportRate: 0,
        infoNotFoundAbstentionRecall: 1,
        citationHardGatePassed: 0,
        tokens: 25_778,
        toolCalls: 6,
        latencyMs: 63_693,
      },
    },
    candidate: {
      ...response.experiments[0].candidate,
      metrics: {
        answerCaseCount: 4,
        answerJudgeCorrectnessRate: 0,
        highLevelFactCoverage: 0,
        citationFactCoverage: 0,
        answerableCitationSupportRate: 0,
        infoNotFoundAbstentionRecall: 0,
        citationHardGatePassed: 0,
        tokens: 7_713,
        toolCalls: 12,
        latencyMs: 420_642,
      },
    },
    comparison: {
      ...response.experiments[0].comparison,
      decision: 'reject',
      decisionReason: '答案与引用门禁未通过。',
    },
  }],
} as const;

function runtimeReconciledCostEnvironment({
  sourceRunId,
  usage,
  estimate,
  pricingIdentity,
  receiptHex = 'a',
  requestCount = 1,
}: {
  sourceRunId: string;
  usage: Record<string, number>;
  estimate: Record<string, string>;
  pricingIdentity: Record<string, unknown>;
  receiptHex?: string;
  requestCount?: number;
}) {
  const sourceSha256 = receiptHex.repeat(64);
  return {
    costAuthority: 'runtime_cost_reconciled',
    usageReceipt: {
      available: true,
      ...usage,
      sourceRef: `runtime-cost:${sourceRunId}`,
      sourceSha256,
    },
    costEstimate: estimate,
    pricingIdentity,
    billing: { status: 'not_provided' },
    runtimeCostReceipt: {
      requestCount,
      runtimeDbSha256: sourceSha256,
      transcriptSha256s: [sourceSha256],
      sourceSha256,
      reportedCostUsd: {
        input: estimate.uncachedInputCostUsd,
        cacheRead: estimate.cachedInputCostUsd,
        output: estimate.outputCostUsd,
        total: estimate.totalCostUsd,
      },
    },
  };
}

describe('Agent Lab', () => {
  it('opens an in-app evidence panel with every public turn and the run environment', async () => {
    const sessionId = 'agent:real-2';
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': response,
        'agent.session.snapshot': {
          schemaVersion: 'rag-ime.agent-message-list.v1',
          ok: true,
          sessionId,
          status: 'idle',
          lastSequence: 4,
          resumeToken: `${sessionId}:4`,
          liveEvents: [],
          items: [
            {
              schemaVersion: 'rag-ime.agent-message.v1',
              id: `${sessionId}:user`,
              sessionId,
              turnId: 'turn-1',
              role: 'user',
              status: 'completed',
              blocks: [{ id: 'user-block', type: 'text', status: 'completed', data: { text: '请为客户建立工单并绑定 SLA。' } }],
              attachments: [],
              citations: [],
              createdAtMs: 100,
              completedAtMs: 100,
            },
            {
              schemaVersion: 'rag-ime.agent-message.v1',
              id: `${sessionId}:assistant`,
              sessionId,
              turnId: 'turn-1',
              role: 'assistant',
              status: 'completed',
              blocks: [{ id: 'assistant-block', type: 'text', status: 'completed', data: { text: '我先核对客户、产品和 SLA，再执行写入。' } }],
              attachments: [],
              citations: [],
              createdAtMs: 200,
              completedAtMs: 200,
            },
            {
              schemaVersion: 'rag-ime.agent-message.v1',
              id: `${sessionId}:tool`,
              sessionId,
              turnId: 'turn-1',
              role: 'toolResult',
              status: 'completed',
              blocks: [{ id: 'tool-block', type: 'tool_result', status: 'completed', data: { name: 'create_case', content: '{"case_id":"CS-0001"}' } }],
              attachments: [],
              citations: [],
              createdAtMs: 300,
              completedAtMs: 300,
            },
          ],
          toolHistoryEvents: [{ name: 'create_case', status: 'completed', createdAtMs: 300 }],
          telemetry: {
            schemaVersion: 'rag-ime.agent-session-telemetry.v1',
            model: { provider: 'openai-codex', id: 'gpt-5.6-sol', name: 'Sol' },
            context: { tokens: 1200, contextWindow: 128000, percent: 1, remainingTokens: 126800, compactAtTokens: 120000, tokensUntilCompact: 118800, reserveTokens: 8000, keepRecentTokens: 4000, autoCompactEnabled: true },
            cumulativeUsage: { input: 800, output: 400, cacheRead: 0, cacheWrite: 0, totalTokens: 1200 },
            latestUsage: { input: 800, output: 400, cacheRead: 0, cacheWrite: 0, totalTokens: 1200 },
            latestCacheHitPercent: 0,
            isCompacting: false,
            compactionCount: 0,
            updatedAtMs: 300,
          },
        },
        'agent.eval-lab.evidence': {
          schemaVersion: 'rag-ime.eval-lab-evidence.v1',
          ok: true,
          source: { available: true, label: '测试证据', runCount: 1, sessionCount: 1, transcriptCount: 1, transcriptBytes: 256 },
          runs: [],
          total: 0,
          detail: {
            status: 'available',
            runId: 'enterpriseops-csm-validation-20260901',
            taskIndex: 2,
            task: {
              taskIndex: 2,
              taskLabel: 'Task 2',
              title: 'Task 2',
              transcriptAvailable: true,
              transcriptSha256: 'e'.repeat(64),
              transcriptBytes: 256,
              jsonlLines: 4,
              userMessages: 1,
              assistantMessages: 1,
              toolCalls: 1,
              toolFailures: 0,
              toolNames: ['create_case'],
              externalSessionRef: 'session-ref',
              model: 'gpt-5.6-sol',
              thinking: 'high',
              executionMode: 'per_action',
              createdAtMs: 1,
              updatedAtMs: 2,
              evidenceStatus: 'available',
              taskSucceeded: false,
              terminalEvent: 'turn_completed',
              verifierPassed: 3,
              verifierTotal: 5,
              latencyMs: 1200,
            },
            session: { title: 'Task 2', model: 'gpt-5.6-sol', thinking: 'high', executionMode: 'per_action', sessionMode: 'assistant', messageCount: 3 },
            environment: { provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'high', workflowProfile: 'baseline-v1', split: 'validation', transport: 'loopback-http-v1', timeoutSeconds: 900, workspace: '测试沙盒', network: '禁用', tokenUsage: { inputTokens: 800, outputTokens: 400, cacheReadTokens: 0, cacheWriteTokens: 0, totalTokens: 1200 } },
            turns: [
              { kind: 'message', role: 'user', text: '请为客户建立工单并绑定 SLA。', timestampMs: 100, entryRef: 'user-block' },
              { kind: 'message', role: 'assistant', text: '我先核对客户、产品和 SLA，再执行写入。', timestampMs: 200, entryRef: 'assistant-block' },
              { kind: 'tool_call', role: 'assistant', toolName: 'create_case', text: '调用工具：create_case', argumentKeys: ['account_id'], timestampMs: 250, entryRef: 'tool-call' },
              { kind: 'tool_result', role: 'tool', toolName: 'create_case', status: 'completed', text: '工具返回了结果。', timestampMs: 300, entryRef: 'tool-result' },
            ],
            tools: [{ toolName: 'create_case', status: 'completed', text: '工具返回了结果。', timestampMs: 300 }],
            protected: { sourceReadOnly: true, thinkingShown: false, systemPromptShown: false, hiddenGoldShown: false, rawSqlShown: false, pathsAndCredentialsShown: false, redactions: ['内部推理'] },
          },
        },
        'agent.sessions.list': {
          ok: true,
          items: [{
            id: sessionId,
            title: 'Task 2',
            mode: 'assistant',
            status: 'idle',
            roleId: 'companion-present-v1',
            roleVersion: '1',
            roleBookRevisionId: '',
            modelProfile: 'openai-codex/gpt-5.6-sol',
            thinkingLevel: 'high',
            toolProfileVersion: 'subagent-readonly-v1',
            executionMode: 'per_action',
            workspaceScopeGranted: false,
            workspaceScopeSha256: '',
            workspaceScopeGrantedAtMs: 0,
            capabilityDisclosurePreferences: {},
            policyRevision: 1,
            projectContextEnabled: false,
            piSkillsEnabled: false,
            codexSkillsEnabled: false,
            createdAtMs: 1,
            updatedAtMs: 3,
            messageCount: 3,
            workspaceRoots: [],
            evaluationSnapshot: true,
          }],
        },
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('button', { name: '查看完整报告' }));
    await userEvent.setup().click((await screen.findAllByRole('button', { name: '查看逐轮证据' }))[0]);

    const proof = await screen.findByLabelText('任务证据摘要');
    expect(proof).toHaveTextContent('这条任务一眼看懂');
    expect(proof).toHaveTextContent('任务要求');
    expect(proof).toHaveTextContent('请为客户建立工单并绑定 SLA。');
    expect(proof).toHaveTextContent('Agent 最终交付');
    expect(proof).toHaveTextContent('我先核对客户、产品和 SLA，再执行写入。');
    expect(proof).toHaveTextContent('系统验收');
    expect(proof).toHaveTextContent('3/5 条通过');
    expect(proof).toHaveTextContent('真实 transcript');
    expect(await screen.findByRole('heading', { level: 3, name: '任务与结果' })).toBeInTheDocument();
    expect(screen.getAllByText('请为客户建立工单并绑定 SLA。').length).toBeGreaterThan(0);
    expect(screen.getAllByText('我先核对客户、产品和 SLA，再执行写入。').length).toBeGreaterThan(0);
    expect(screen.getByRole('tab', { name: '任务' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '运行轨迹' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '验收' })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('tab', { name: '运行轨迹' }));
    expect(screen.getByRole('heading', { level: 3, name: '运行轨迹' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 4, name: 'Agent 对话与动作' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 4, name: 'Tool 返回' })).toBeInTheDocument();
    expect(screen.getAllByText('请为客户建立工单并绑定 SLA。').length).toBeGreaterThan(0);
    expect(screen.getAllByText('create_case').length).toBeGreaterThan(0);
    expect(screen.getByRole('tab', { name: '运行环境' })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('tab', { name: '运行环境' }));
    expect(screen.getByText('gpt-5.6-sol')).toBeInTheDocument();
    expect(screen.getByText('per_action')).toBeInTheDocument();
    expect(screen.getByText(/Host verifier/)).toBeInTheDocument();
    expect(screen.getByText('3/5')).toBeInTheDocument();
  });

  it('renders one evaluation batch, then opens a real read-only Agent Session', async () => {
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.runs': response } });
    const openWindow = vi.fn<(request: PawOsWindowRequest) => void>();

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={openWindow}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('heading', { level: 1, name: 'Agent 工作流实验室' })).toBeInTheDocument();
    expect(screen.getByText('把任何能重复验收的 Agent 能力注册成测评：每个测评使用自己冻结的数据与评分标准，PAW 在统一证据框架下比较方案。')).toBeInTheDocument();
    expect(screen.getByText('1 · 选择真实任务')).toBeInTheDocument();
    expect(screen.getByText('2 · 一次只改一项')).toBeInTheDocument();
    expect(screen.getByText('模型、提示词、技能、工具、检索、记忆或协作流程')).toBeInTheDocument();
    expect(screen.getByText('3 · 按同一标准重跑')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { level: 2, name: '每一轮都回答：为什么改、改了什么、结果如何' })).toBeInTheDocument();
    expect(screen.getByText('下面按业务场景整理所有实验。先看任务是否做对、结果是否安全可靠，再比较成本；耗时只用于诊断，不阻止保留正确方案。')).toBeInTheDocument();
    const overview = screen.getByLabelText('Agent Lab 实验结果');
    expect(overview.querySelector('table')).toBeNull();
    expect(overview.querySelectorAll('.eval-lab__matrix-card')).toHaveLength(1);
    expect(screen.getByText('为什么要改')).toBeInTheDocument();
    expect(screen.getByText('本轮改了什么')).toBeInTheDocument();
    expect(screen.getByText('关键资料没有稳定排进前十条，后续回答容易漏掉真正相关的证据。')).toBeInTheDocument();
    expect(screen.getByText('质量结果')).toBeInTheDocument();
    expect(screen.getByText('可靠性与安全')).toBeInTheDocument();
    await userEvent.setup().click(await screen.findByRole('button', { name: '查看完整报告' }));
    expect(await screen.findByRole('heading', { level: 2, name: 'EnterpriseOps CSM workflow' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '从任务一路核对到新结果' })).toBeInTheDocument();
    expect(screen.getByText('所有内容都在 Agent Lab 内查看；本机文件夹只作为高级用户的次级入口。')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '任务定义' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('冻结条件')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('tab', { name: '数据集 Cases' }));
    expect(screen.getByLabelText('数据集 Case 浏览器')).toBeInTheDocument();
    expect(screen.getByText('suite-v2')).toBeInTheDocument();
    expect(screen.getByText('评测权威')).toBeInTheDocument();
    expect(screen.getByText('泄漏边界')).toBeInTheDocument();
    expect(screen.getByText('负例 / 拒答')).toBeInTheDocument();
    expect(screen.getByText('Case 正文未公开')).toBeInTheDocument();
    const recordTabs = within(screen.getByRole('tablist', { name: '选择实验档案' })).getAllByRole('tab');
    expect(recordTabs.map((tab) => tab.textContent)).toEqual(['任务定义', '数据集 Cases', '原结果', '优化', '新结果']);
    await userEvent.setup().click(screen.getByRole('tab', { name: '优化' }));
    expect(screen.getByRole('region', { name: 'Optimization Workbench' })).toBeInTheDocument();
    expect(screen.getByText('实际改动')).toBeInTheDocument();
    const changeDiff = screen.getByLabelText('改动 diff');
    expect(changeDiff).toHaveTextContent('修改前');
    expect(changeDiff).toHaveTextContent('修改后');
    expect(changeDiff).toHaveTextContent('直接执行');
    expect(changeDiff).toHaveTextContent('状态合同');
    expect(screen.getByText('受影响 Case')).toBeInTheDocument();
    expect(screen.getByText('Run 与证据链')).toBeInTheDocument();
    expect(screen.getAllByText('enterpriseops-suite-v2-final-validation-20260901').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Keep').length).toBeGreaterThan(0);
    await userEvent.setup().click(screen.getByRole('tab', { name: '新结果' }));
    expect(screen.getByText('发布 / 可靠性门禁')).toBeInTheDocument();
    expect(screen.getByText('Run ID')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '本次结论' })).toBeInTheDocument();
    expect(screen.getByText('发现的问题')).toBeInTheDocument();
    expect(screen.getByText('本轮怎么改')).toBeInTheDocument();
    expect(screen.getByText('结果怎样')).toBeInTheDocument();
    expect(screen.getByText('为什么这样决定')).toBeInTheDocument();
    expect(screen.queryByText('查看 STAR 证据')).toBeNull();
    expect(screen.getByText('查看过程复盘')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('tab', { name: '方案路径' }));
    expect(screen.getByRole('heading', { level: 2, name: '方案是怎样一步步筛出来的' })).toBeInTheDocument();
    expect(screen.getByText('完成全部任务，再比较成本；延迟只用于诊断。')).toBeInTheDocument();
    expect(screen.getByText('baseline → state-contract')).toBeInTheDocument();
    expect(screen.getByText('质量持平、效率较低。')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '任务完成' })).toBeInTheDocument();
    expect(screen.getAllByText('状态合同工作流').filter((element) => element.tagName === 'STRONG')).toHaveLength(1);
    await userEvent.setup().click(screen.getByRole('tab', { name: '对话与证据' }));
    expect(screen.getByRole('heading', { level: 2, name: '查看每轮对话、工具调用和验收报告' })).toBeInTheDocument();
    expect(screen.getByText('EnterpriseOps CSM')).toBeInTheDocument();
    expect(screen.getByText('1 个回执')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('tab', { name: '实验详情' }));
    expect(screen.getByText('为什么需要 Agent')).toBeInTheDocument();
    expect(screen.getByText('实验变量（可改）')).toBeInTheDocument();
    expect(screen.getByText('直接执行 → 状态合同')).toBeInTheDocument();
    expect(screen.getByText('冻结控制（不可改）')).toBeInTheDocument();
    expect(screen.getByText('相比原方案')).toBeInTheDocument();
    expect(screen.getByText('Validation evidence.')).toBeInTheDocument();
    expect(screen.getByText('只代表本轮调优数据。')).toBeInTheDocument();
    expect(screen.getByText('查看过程复盘')).toBeInTheDocument();
    expect(screen.queryByText(/可表述为|不能表述为|可以说|不能说/)).toBeNull();
    expect(screen.getByText('1/2')).toBeInTheDocument();
    expect(screen.getByText(/14\/16/)).toBeInTheDocument();
    expect(screen.getByText(/87\.50%/)).toBeInTheDocument();
    expect(screen.getAllByText('Production or Held-out success.')).toHaveLength(2);
    expect(screen.getByRole('heading', { level: 3, name: '任务：Task 2' })).toBeInTheDocument();
    expect(screen.getByText('根据客户工单整理恢复计划，并说明下一步。')).toBeInTheDocument();
    expect(screen.getByText('Agent 实际输出')).toBeInTheDocument();
    expect(screen.getByText('我会先确认影响范围，再给出负责人和时间点。')).toBeInTheDocument();
    expect(screen.getByText('标准答案 / 验收')).toBeInTheDocument();
    expect(screen.getByText('此处展示脱敏后的验收条件与逐项结论，不展示 raw gold、SQL 或隐藏推理。')).toBeInTheDocument();
    expect(screen.getByText('逐项对比')).toBeInTheDocument();
    expect(screen.getAllByText('缺少可复核的完成条件。')).toHaveLength(2);
    expect(screen.getByText('为什么不是 100%')).toBeInTheDocument();
    expect(screen.getByText(/报告校验码 b{12}/)).toBeInTheDocument();
    expect(screen.queryByText('尚未找到与 baseline/candidate runId 匹配的真实 Session。')).toBeNull();

    await userEvent.setup().click(screen.getAllByRole('button', { name: '查看对话' })[1]);
    expect(openWindow).toHaveBeenCalledWith({
      appId: 'agent',
      target: {
        kind: 'session',
        id: 'agent:real-2',
        title: 'EnterpriseOps CSM · Task 2',
        subtitle: '真实评测记录 · 只读',
      },
    });
  });

  it('keeps superseded failures out of the current matrix and exposes them as read-only history', async () => {
    const historicalExperiment = {
      ...response.experiments[0],
      experimentId: 'enterpriseops-csm-v1-failed',
      title: 'EnterpriseOps CSM failed baseline',
      status: 'rejected',
      claimStatus: 'diagnostic',
      projectionState: 'history',
      supersededBy: response.experiments[0].experimentId,
      importedAtMs: 2,
    } as const;
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': {
        ...response,
        experimentTotal: 2,
        experiments: [historicalExperiment, response.experiments[0]],
      },
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    const overview = await screen.findByLabelText('Agent Lab 实验结果');
    expect(overview.querySelectorAll('.eval-lab__matrix-card')).toHaveLength(1);
    expect(screen.getByText('1 个项目 · 1 个当前实验 · 1 条历史记录')).toBeInTheDocument();
    expect(screen.getByText('历史失败不参与当前结论')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /查看历史实验/ })).not.toBeVisible();

    await userEvent.setup().click(screen.getByText('查看 1 条历史记录'));
    const historyButton = screen.getByRole('button', { name: /查看历史实验/ });
    expect(historyButton).toBeVisible();
    await userEvent.setup().click(historyButton);
    expect(await screen.findByRole('heading', { level: 2, name: 'EnterpriseOps CSM failed baseline' })).toBeInTheDocument();
    expect(screen.getByText('历史记录 · 不参与当前结论')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '和 Agent 一起继续优化' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '测试新方案' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '在 Room 中继续下一轮' })).not.toBeInTheDocument();
  });

  it('groups the public ledger into four business projects without synthesizing reviewer approval', async () => {
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': previewEvalLabRuns(),
      'agent.eval-lab.evidence': previewEvalLabEvidence(),
    } });
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('4 个项目 · 12 个当前实验 · 9 条历史记录')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '企业客户支持' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '企业知识库问答' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '云上事故诊断' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: '长期记忆整理' })).toBeInTheDocument();
    expect(screen.getAllByText('项目验收：未完成')).toHaveLength(4);
    expect(screen.getAllByText('同一冻结候选尚未同时证明任务成功、质量不退化与成本下降。')).toHaveLength(4);
    expect(await screen.findAllByText('示例投影 · 不代表真实验收')).toHaveLength(3);
    expect(screen.getByText('受控 Fixture 回执；另有未验证记录 · 不代表生产结果')).toBeInTheDocument();
    expect(screen.getAllByText('独立检查回执')).toHaveLength(4);
    expect(screen.getAllByText('打开实验详情查看真实 Room 回执；没有回执时不会合成通过结论。')).toHaveLength(4);
    expect(screen.queryByText('独立检查确认关键结果和证据一致。')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Agent Lab 实验结果')).not.toHaveTextContent(/Host-private|\bcase\b|verifier/i);
    expect(screen.getByText('质量门禁未通过，候选已拒绝 · 账面成本回执标记已记录，价格身份由项目验收另行校验 · 最终盲测未使用')).toBeInTheDocument();
    expect(screen.getByText('工具调用 87 → 66 · 延迟 18m 33s → 15m 30s · 账面 API 估算 $3.2434 → $0.7252（未通过绑定价格回执门禁，不作为成本下降结论）')).toBeInTheDocument();
    expect(screen.queryByText(/API 估算 \$3\.2434 → \$0\.7252（降低 77\.6%）/)).toBeNull();
    expect(screen.getAllByText('整理通过 5/5 · 长期信息召回 4/4 · 不该记的内容成功拦截 1/1').length).toBeGreaterThan(0);
    expect(screen.getByText('模型调用 1m 25s · 模型用量未记录 · 无法计算 API 成本')).toBeInTheDocument();
    const currentMatrix = screen.getByLabelText('Agent Lab 实验结果');
    expect(currentMatrix.querySelectorAll('.eval-lab__matrix-card')).toHaveLength(12);
    expect(currentMatrix).not.toHaveTextContent('正式故障诊断评分没有运行');
    const memoryProject = screen.getByRole('heading', { level: 3, name: '长期记忆整理' }).closest('.eval-lab__project-matrix');
    expect(memoryProject).not.toBeNull();
    await user.click(within(memoryProject as HTMLElement).getAllByRole('button', { name: '查看完整报告' })[0]);
    expect(await screen.findByRole('heading', { level: 2, name: 'Luna v4 to v5 shadow gate' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: '实验结果' }));
    await user.click(screen.getByText('查看 9 条历史记录'));
    expect(screen.getAllByRole('button', { name: /查看历史实验/ })).toHaveLength(9);
    expect(screen.getByRole('button', { name: /Luna Max baseline Validation（第三批超时）/ })).toBeVisible();
    expect(screen.getByRole('button', { name: /Runtime 选择顺序修复（retry3）/ })).toBeVisible();
    const overviewTab = screen.getByRole('tab', { name: '实验结果' });
    overviewTab.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: '方案路径' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('heading', { level: 2, name: '方案是怎样一步步筛出来的' })).toBeInTheDocument();
  });

  it('keeps project qualification in an evidence-checking state until the catalog settles', async () => {
    let resolveEvidence!: (value: ReturnType<typeof previewEvalLabEvidence>) => void;
    const pendingEvidence = new Promise<ReturnType<typeof previewEvalLabEvidence>>((resolve) => {
      resolveEvidence = resolve;
    });
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': response,
      'agent.eval-lab.evidence': () => pendingEvidence,
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    const overview = await screen.findByLabelText('Agent Lab 实验结果');
    expect(within(overview).getByText('项目验收：正在核对证据')).toBeInTheDocument();
    expect(within(overview).queryByText('项目验收：未完成')).not.toBeInTheDocument();
    expect(overview).not.toHaveTextContent('缺少绑定且可核验的价格回执');

    await act(async () => {
      resolveEvidence(previewEvalLabEvidence());
    });

    expect(await within(overview).findByText('项目验收：未完成')).toBeInTheDocument();
    expect(within(overview).queryByText('项目验收：正在核对证据')).not.toBeInTheDocument();
  });

  it('keeps OAuth token-category dominance visible without treating it as price proof', async () => {
    const oauthResponse = structuredClone(response) as any;
    const experiment = oauthResponse.experiments[0];
    experiment.effectStatus = 'improved';
    experiment.baseline.metrics = {
      taskSuccessRate: 0.5,
      verifierPassRate: 0.75,
      usageReceiptAvailable: 1,
      sameProviderModelThinking: 1,
      uncachedInputTokens: 100,
      cachedInputTokens: 200,
      outputTokens: 50,
    };
    experiment.candidate.metrics = {
      taskSuccessRate: 1,
      verifierPassRate: 1,
      failedToolCalls: 0,
      usageReceiptAvailable: 1,
      sameProviderModelThinking: 1,
      uncachedInputTokens: 90,
      cachedInputTokens: 200,
      outputTokens: 40,
    };
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': oauthResponse,
      'agent.eval-lab.evidence': previewEvalLabEvidence(),
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('项目验收：未完成')).toBeInTheDocument();
    expect(screen.getByText(/用量下降，但缺少绑定且可核验的价格回执，不能证明成本下降/)).toBeInTheDocument();
  });

  it('qualifies a typed multi-stage final candidate only from bound deterministic price receipts', async () => {
    const stableResponse = structuredClone(response) as any;
    const experiment = stableResponse.experiments[0];
    experiment.effectStatus = 'neutral';
    experiment.candidateType = 'compound_repair';
    experiment.factors = [
      {
        name: 'model',
        before: 'Sol Max',
        after: 'Luna Max',
        reason: 'Model-only stage is recorded separately.',
      },
      {
        name: 'prompt',
        before: 'Sol policy',
        after: 'Luna-adapted policy',
        reason: 'Prompt-only stage is recorded separately.',
      },
    ];
    experiment.baseline = {
      ...experiment.baseline,
      runId: 'stable-cost-baseline',
      evidenceRefs: ['stable-cost-baseline-price'],
      metrics: {
        taskSuccessRate: 1,
        verifierPassRate: 1,
        failedToolCalls: 0,
        usageReceiptAvailable: 1,
        sameProviderModelThinking: 1,
        uncachedInputTokens: 100,
        cachedInputTokens: 200,
        outputTokens: 50,
      },
    };
    experiment.candidate = {
      ...experiment.candidate,
      runId: 'stable-cost-candidate',
      evidenceRefs: ['stable-cost-candidate-price'],
      metrics: {
        taskSuccessRate: 1,
        verifierPassRate: 1,
        failedToolCalls: 0,
        usageReceiptAvailable: 1,
        sameProviderModelThinking: 1,
        uncachedInputTokens: 90,
        cachedInputTokens: 180,
        outputTokens: 40,
      },
    };
    const catalog = structuredClone(previewEvalLabEvidence()) as any;
    const task = catalog.runs[0].tasks[0];
    const pricingIdentity = {
      pricingId: 'openai-api-gpt-5.6-sol-2026-09-01',
      provider: 'openai',
      model: 'gpt-5.6-sol',
      currency: 'USD',
      unit: 'per_million_tokens',
      rates: { uncachedInputUsd: '4', cachedInputUsd: '1', outputUsd: '10' },
      publishedDate: '2026-09-01',
      sourceUrl: 'https://platform.openai.com/docs/pricing',
      sourceSha256: '9'.repeat(64),
    };
    catalog.runs = [
      {
        ...catalog.runs[0], runId: 'stable-cost-baseline', updatedAtMs: 10,
        tasks: [{
          ...task, taskIndex: 1, taskLabel: 'case-csm-01', taskSucceeded: true,
          terminalEvent: 'turn_completed', verifierPassed: 11, verifierTotal: 11,
          toolFailures: 0, inputTokens: 100, cacheReadTokens: 200, outputTokens: 50,
        }],
      },
      {
        ...catalog.runs[0], runId: 'stable-cost-candidate', updatedAtMs: 11,
        tasks: [{
          ...task, taskIndex: 1, taskLabel: 'case-csm-01', taskSucceeded: true,
          terminalEvent: 'turn_completed', verifierPassed: 11, verifierTotal: 11,
          toolFailures: 0, inputTokens: 90, cacheReadTokens: 180, outputTokens: 40,
        }],
      },
      {
        ...catalog.runs[0], runId: 'stable-cost-baseline-price', updatedAtMs: 12,
        sourceId: 'checked-in-ledger', sourceLabel: '仓库公开评测回执（只读）', evidenceKind: 'report_only',
        reportAvailable: true, databaseAvailable: false, tasks: [], sessionCount: 0, transcriptCount: 0,
        environment: {
          usageReceipt: {
            available: true, uncachedInputTokens: 1_000_000, cachedInputTokens: 1_000_000, outputTokens: 100_000,
            sourceRef: 'runtime-db:stable-cost-baseline', sourceSha256: 'a'.repeat(64),
          },
          costEstimate: { uncachedInputCostUsd: '4', cachedInputCostUsd: '1', outputCostUsd: '1', totalCostUsd: '6' },
          pricingIdentity,
          billing: { status: 'not_provided' },
        },
      },
      {
        ...catalog.runs[0], runId: 'stable-cost-candidate-price', updatedAtMs: 13,
        sourceId: 'checked-in-ledger', sourceLabel: '仓库公开评测回执（只读）', evidenceKind: 'report_only',
        reportAvailable: true, databaseAvailable: false, tasks: [], sessionCount: 0, transcriptCount: 0,
        environment: {
          usageReceipt: {
            available: true, uncachedInputTokens: 500_000, cachedInputTokens: 500_000, outputTokens: 50_000,
            sourceRef: 'runtime-db:stable-cost-candidate', sourceSha256: 'b'.repeat(64),
          },
          costEstimate: { uncachedInputCostUsd: '2', cachedInputCostUsd: '0.5', outputCostUsd: '0.5', totalCostUsd: '3' },
          pricingIdentity,
          billing: { status: 'not_provided' },
        },
      },
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': stableResponse,
      'agent.eval-lab.evidence': catalog,
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('项目验收：未完成')).toBeInTheDocument();
    expect(screen.getByText(/缺少 Runtime 逐请求成本对账权限/)).toBeInTheDocument();

    cleanup();
    for (const [index, run] of catalog.runs.slice(2).entries()) {
      const environment = run.environment as any;
      const estimate = environment.costEstimate;
      const runtimeSourceSha256 = index === 0 ? 'a'.repeat(64) : 'b'.repeat(64);
      environment.costAuthority = 'runtime_cost_reconciled';
      environment.usageReceipt.sourceRef = `runtime-cost:${index === 0 ? 'stable-cost-baseline' : 'stable-cost-candidate'}`;
      environment.usageReceipt.sourceSha256 = runtimeSourceSha256;
      environment.pricingIdentity.pricingId = `pricing:sha256:${'9'.repeat(64)}`;
      environment.runtimeCostReceipt = {
        requestCount: index === 0 ? 4 : 3,
        runtimeDbSha256: (index === 0 ? 'c' : 'd').repeat(64),
        transcriptSha256s: [(index === 0 ? 'e' : 'f').repeat(64)],
        sourceSha256: runtimeSourceSha256,
        reportedCostUsd: {
          input: estimate.uncachedInputCostUsd,
          cacheRead: estimate.cachedInputCostUsd,
          output: estimate.outputCostUsd,
          total: estimate.totalCostUsd,
        },
      };
    }
    const reconciledTransport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': stableResponse,
      'agent.eval-lab.evidence': catalog,
    } });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={reconciledTransport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('项目验收：已达标')).toBeInTheDocument();
    expect(screen.getByText(/Runtime 对账 API 成本 \$6\.0000 USD → \$3\.0000 USD（降低 50\.0%）/)).toBeInTheDocument();
    expect(screen.getByText(/逐请求回执 4 → 3 次/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`价格版本 pricing:sha256:${'9'.repeat(64)}`))).toBeInTheDocument();
    expect(screen.getByText(/2026-09-01/)).toBeInTheDocument();
    expect(screen.getByText(/未缓存输入 \$4 · 缓存输入 \$1 · 输出 \$10/)).toBeInTheDocument();
    expect(screen.getByText(/Provider 账单：未提供/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: '查看完整报告' }));
    await userEvent.setup().click(screen.getByRole('tab', { name: '优化' }));
    expect(screen.getByText('case-csm-01')).toBeInTheDocument();
    expect(screen.getByText('成功 → 成功')).toBeInTheDocument();
    expect(screen.getByText(/验收 11\/11.*→.*验收 11\/11/)).toBeInTheDocument();
    expect(screen.getByText('未缓存输入 100 → 90 · 缓存输入 200 → 180 · 输出 50 → 40')).toBeInTheDocument();
  });

  it('fails closed when bound price receipts use different pricing provenance', async () => {
    const mismatched = structuredClone(response) as any;
    const experiment = mismatched.experiments[0];
    experiment.effectStatus = 'neutral';
    experiment.candidateType = 'single_factor';
    experiment.baseline = {
      ...experiment.baseline,
      runId: 'price-provenance-baseline',
      evidenceRefs: ['price-provenance-baseline-receipt'],
      metrics: { taskSuccessRate: 1, verifierPassRate: 1, failedToolCalls: 0 },
    };
    experiment.candidate = {
      ...experiment.candidate,
      runId: 'price-provenance-candidate',
      evidenceRefs: ['price-provenance-candidate-receipt'],
      metrics: { taskSuccessRate: 1, verifierPassRate: 1, failedToolCalls: 0 },
    };
    const catalog = structuredClone(previewEvalLabEvidence()) as any;
    const costRun = (runId: string, sourceRunId: string, sourceSha256: string, totalCostUsd: string) => ({
      ...catalog.runs[0],
      runId,
      sourceId: 'checked-in-ledger',
      sourceLabel: '仓库公开评测回执（只读）',
      evidenceKind: 'report_only',
      reportAvailable: true,
      databaseAvailable: false,
      tasks: [],
      sessionCount: 0,
      transcriptCount: 0,
      environment: runtimeReconciledCostEnvironment({
        sourceRunId,
        usage: { uncachedInputTokens: 1_000_000, cachedInputTokens: 0, outputTokens: 0 },
        estimate: { uncachedInputCostUsd: totalCostUsd, cachedInputCostUsd: '0', outputCostUsd: '0', totalCostUsd },
        pricingIdentity: {
          pricingId: `pricing:sha256:${sourceSha256}`, provider: 'openai', model: 'gpt-5.6-sol',
          currency: 'USD', unit: 'per_million_tokens',
          rates: { uncachedInputUsd: totalCostUsd, cachedInputUsd: '0', outputUsd: '0' },
          publishedDate: '2026-09-01', sourceUrl: 'https://platform.openai.com/docs/pricing', sourceSha256,
        },
        receiptHex: sourceSha256[0],
      }),
    });
    catalog.runs = [
      costRun('price-provenance-baseline-receipt', 'price-provenance-baseline', '1'.repeat(64), '6'),
      costRun('price-provenance-candidate-receipt', 'price-provenance-candidate', '2'.repeat(64), '3'),
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': mismatched,
      'agent.eval-lab.evidence': catalog,
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('项目验收：未完成')).toBeInTheDocument();
    expect(screen.getByText(/provenance 不一致/)).toBeInTheDocument();
  });

  it('qualifies the bound CloudOps Sol prompt run at a 53.0% Runtime-reconciled API cost reduction', async () => {
    const cloudOpsResponse = structuredClone(response) as any;
    const experiment = cloudOpsResponse.experiments[0];
    experiment.experimentId = 'cloudops.alert-first-sol-max.v1';
    experiment.title = 'CloudOps · Alert-first Prompt 成本优化';
    experiment.vertical = 'cloudops-incident-diagnosis';
    experiment.evaluationKind = 'workflow';
    experiment.status = 'kept';
    experiment.effectStatus = 'improved';
    experiment.candidateType = 'single_factor';
    experiment.factors = [{ name: 'prompt', before: 'baseline-v1', after: 'alert-first-v5', reason: '只改 Prompt' }];
    experiment.scoring.hardGates = ['12/12 canonical answers', 'FA and JRA non-regression', 'complete usage categories'];
    experiment.baseline = {
      ...experiment.baseline,
      runId: 'cloudops-sol-max-standard-baseline-20260904-r2',
      evidenceRefs: ['eval/interview-metrics/runs/agent-lab-cost-cloudops-sol-max-standard-baseline-20260904.r2.v1.json'],
      metrics: {
        answerCoverage: 1, ca: 1, fa: 5 / 6, jra: 5 / 6, top3Jra: 5 / 6, formalScoreProduced: 1,
        failedToolCalls: 0, sameProviderModelThinking: 1, usageReceiptAvailable: 1, categoryReceiptComplete: 1,
        uncachedInputTokens: 443_159, cachedInputTokens: 12_583_424, outputTokens: 40_257,
      },
    };
    experiment.candidate = {
      ...experiment.candidate,
      runId: 'cloudops-sol-max-alert-first-candidate-20260904-r7',
      evidenceRefs: ['eval/interview-metrics/runs/agent-lab-cost-cloudops-sol-max-alert-first-20260904.r7.v1.json'],
      metrics: {
        answerCoverage: 1, ca: 1, fa: 5 / 6, jra: 5 / 6, top3Jra: 1, formalScoreProduced: 1,
        failedToolCalls: 1, sameProviderModelThinking: 1, usageReceiptAvailable: 1, categoryReceiptComplete: 1,
        uncachedInputTokens: 267_606, cachedInputTokens: 4_359_552, outputTokens: 35_012,
      },
    };
    cloudOpsResponse.experiments = [experiment];
    cloudOpsResponse.experimentTotal = 1;
    const catalog = structuredClone(previewEvalLabEvidence()) as any;
    const pricingIdentity = {
      pricingId: `pricing:sha256:${'8'.repeat(64)}`, provider: 'openai', model: 'gpt-5.6-sol',
      currency: 'USD', unit: 'per_million_tokens',
      rates: { uncachedInputUsd: '5', cachedInputUsd: '0.5', outputUsd: '30' },
      publishedDate: '2026-09-01', sourceUrl: 'https://platform.openai.com/docs/pricing', sourceSha256: '8'.repeat(64),
    };
    const costRun = (runId: string, sourceRunId: string, usage: Record<string, number>, estimate: Record<string, string>, receiptHex: string) => ({
      ...catalog.runs[0], runId, sourceId: 'checked-in-ledger', sourceLabel: '仓库公开评测回执（只读）',
      evidenceKind: 'report_only', reportAvailable: true, databaseAvailable: false, tasks: [], sessionCount: 0, transcriptCount: 0,
      environment: runtimeReconciledCostEnvironment({ sourceRunId, usage, estimate, pricingIdentity, receiptHex, requestCount: 12 }),
    });
    catalog.runs = [
      costRun(
        'ledger--agent-lab-cost-cloudops-sol-max-standard-baseline-20260904.r2.v1',
        'cloudops-sol-max-standard-baseline-20260904-r2',
        { uncachedInputTokens: 443_159, cachedInputTokens: 12_583_424, outputTokens: 40_257 },
        { uncachedInputCostUsd: '2.215795', cachedInputCostUsd: '6.291712', outputCostUsd: '1.20771', totalCostUsd: '9.715217' },
        'a',
      ),
      costRun(
        'ledger--agent-lab-cost-cloudops-sol-max-alert-first-20260904.r7.v1',
        'cloudops-sol-max-alert-first-candidate-20260904-r7',
        { uncachedInputTokens: 267_606, cachedInputTokens: 4_359_552, outputTokens: 35_012 },
        { uncachedInputCostUsd: '1.33803', cachedInputCostUsd: '2.179776', outputCostUsd: '1.05036', totalCostUsd: '4.568166' },
        'b',
      ),
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': cloudOpsResponse,
      'agent.eval-lab.evidence': catalog,
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}><EvalLabFeature /></PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    const cloudOps = (await screen.findByRole('heading', { level: 3, name: '云上事故诊断' })).closest('.eval-lab__project-matrix');
    expect(cloudOps).not.toBeNull();
    expect(within(cloudOps as HTMLElement).getByText('项目验收：已达标')).toBeInTheDocument();
    expect(within(cloudOps as HTMLElement).getByText(/Runtime 对账 API 成本 \$9\.7152 USD → \$4\.5682 USD（降低 53\.0%）/)).toBeInTheDocument();
    expect(within(cloudOps as HTMLElement).getByText(/Provider 账单：未提供/)).toBeInTheDocument();
    expect(cloudOps).not.toHaveTextContent('80%');
  });

  it('qualifies the bound EnterpriseOps and Memory Sol runs with their exact API estimates', async () => {
    const retainedResponse = structuredClone(response) as any;
    const enterprise = structuredClone(retainedResponse.experiments[0]);
    enterprise.experimentId = 'enterpriseops-csm.preloaded-tool-cost.v1';
    enterprise.title = 'EnterpriseOps CSM · 已选 Tool Schema 预载成本优化';
    enterprise.vertical = 'enterprise-customer-support';
    enterprise.evaluationKind = 'workflow';
    enterprise.status = 'kept';
    enterprise.effectStatus = 'improved';
    enterprise.candidateType = 'single_factor';
    enterprise.factors = [{ name: 'tool', before: 'compact-v2', after: 'preloaded-v3', reason: '只改 Tool schema disclosure' }];
    enterprise.scoring.hardGates = ['3/3 task success', '31/31 verifier pass', 'zero Tool failure'];
    enterprise.baseline = {
      ...enterprise.baseline,
      runId: 'enterpriseops-csm-sol-max-compact-validation-20260904-v1',
      evidenceRefs: ['eval/interview-metrics/runs/agent-lab-cost-enterpriseops-sol-max-compact-baseline-20260904.v1.json'],
      metrics: {
        taskSuccessRate: 1, verifierPassRate: 1, failedToolCalls: 0, databasesCleaned: 3,
        sameProviderModelThinking: 1, usageReceiptAvailable: 1, categoryReceiptComplete: 1,
        uncachedInputTokens: 118_600, cachedInputTokens: 2_221_824, outputTokens: 18_482,
      },
    };
    enterprise.candidate = {
      ...enterprise.candidate,
      runId: 'enterpriseops-csm-sol-max-preloaded-validation-20260904-v1',
      evidenceRefs: ['eval/interview-metrics/runs/agent-lab-cost-enterpriseops-sol-max-preloaded-20260904.v1.json'],
      metrics: {
        taskSuccessRate: 1, verifierPassRate: 1, failedToolCalls: 0, databasesCleaned: 3,
        sameProviderModelThinking: 1, usageReceiptAvailable: 1, categoryReceiptComplete: 1,
        uncachedInputTokens: 91_845, cachedInputTokens: 1_179_648, outputTokens: 17_222,
      },
    };

    const memory = structuredClone(enterprise);
    memory.experimentId = 'memory.maintenance-concise-contract-sol-max.v1';
    memory.title = 'Memory Maintenance · 精简 JSON Prompt 成本优化';
    memory.vertical = 'memory-maintenance';
    memory.evaluationKind = 'memory';
    memory.factors = [{ name: 'prompt', before: 'standard-v1', after: 'concise-json-v1', reason: '只改 Prompt' }];
    memory.dataset = { ...memory.dataset, caseCount: 5 };
    memory.scoring.hardGates = ['5/5 curation and retrieval', 'rollback and replay pass', 'legal JSON receipt'];
    memory.baseline = {
      ...memory.baseline,
      runId: 'memory-maintenance-sol-max-full-json-baseline-20260904-r2',
      evidenceRefs: ['eval/interview-metrics/runs/agent-lab-cost-memory-sol-max-full-json-baseline-20260904.r2.v1.json'],
      metrics: {
        curationCases: 5, curationPassed: 5, durableRecallPassed: 4, durableRecallTotal: 4,
        abstentionPassed: 1, abstentionTotal: 1, vectorCoverage: 1, rollbackPassed: 1,
        replayPassed: 1, receiptJsonValid: 1, sameProviderModelThinking: 1,
        usageReceiptAvailable: 1, categoryReceiptComplete: 1,
        uncachedInputTokens: 39_799, cachedInputTokens: 0, outputTokens: 2_207,
      },
    };
    memory.candidate = {
      ...memory.candidate,
      runId: 'memory-maintenance-sol-max-concise-contract-candidate-20260904-r3',
      evidenceRefs: ['eval/interview-metrics/runs/agent-lab-cost-memory-sol-max-concise-contract-20260904.r3.v1.json'],
      metrics: {
        curationCases: 5, curationPassed: 5, durableRecallPassed: 4, durableRecallTotal: 4,
        abstentionPassed: 1, abstentionTotal: 1, vectorCoverage: 1, rollbackPassed: 1,
        replayPassed: 1, receiptJsonValid: 1, sameProviderModelThinking: 1,
        usageReceiptAvailable: 1, categoryReceiptComplete: 1,
        uncachedInputTokens: 39_638, cachedInputTokens: 0, outputTokens: 1_650,
      },
    };
    retainedResponse.experiments = [enterprise, memory];
    retainedResponse.experimentTotal = 2;

    const catalog = structuredClone(previewEvalLabEvidence()) as any;
    const pricingIdentity = {
      pricingId: `pricing:sha256:${'8'.repeat(64)}`, provider: 'openai', model: 'gpt-5.6-sol',
      currency: 'USD', unit: 'per_million_tokens',
      rates: { uncachedInputUsd: '5', cachedInputUsd: '0.5', outputUsd: '30' },
      publishedDate: '2026-09-01', sourceUrl: 'https://platform.openai.com/docs/pricing', sourceSha256: '8'.repeat(64),
    };
    const costRun = (runId: string, sourceRunId: string, usage: Record<string, number>, estimate: Record<string, string>, receiptHex: string) => ({
      ...catalog.runs[0], runId, sourceId: 'checked-in-ledger', sourceLabel: '仓库公开评测回执（只读）',
      evidenceKind: 'report_only', reportAvailable: true, databaseAvailable: false, tasks: [], sessionCount: 0, transcriptCount: 0,
      environment: runtimeReconciledCostEnvironment({ sourceRunId, usage, estimate, pricingIdentity, receiptHex, requestCount: 5 }),
    });
    const estimateRun = (runId: string, sourceRunId: string, model: string, usage: Record<string, number>, estimate: Record<string, string>) => ({
      ...catalog.runs[0], runId, sourceId: 'checked-in-ledger', sourceLabel: '仓库公开评测回执（只读）',
      evidenceKind: 'report_only', reportAvailable: true, databaseAvailable: false, tasks: [], sessionCount: 0, transcriptCount: 0,
      environment: {
        costAuthority: 'pricing_estimate',
        usageReceipt: { available: true, ...usage, sourceRef: `public-report:${sourceRunId}`, sourceSha256: (model.includes('luna') ? 'e' : 'd').repeat(64) },
        costEstimate: estimate,
        pricingIdentity: { ...pricingIdentity, model, pricingId: `pricing:sha256:${(model.includes('luna') ? '7' : '8').repeat(64)}`, rates: model.includes('luna') ? { uncachedInputUsd: '0.2', cachedInputUsd: '0.02', outputUsd: '1.2' } : pricingIdentity.rates },
        billing: { status: 'not_provided' },
      },
    });
    catalog.runs = [
      costRun(
        'ledger--agent-lab-cost-enterpriseops-sol-max-compact-baseline-20260904.v1',
        'enterpriseops-csm-sol-max-compact-validation-20260904-v1',
        { uncachedInputTokens: 118_600, cachedInputTokens: 2_221_824, outputTokens: 18_482 },
        { uncachedInputCostUsd: '0.593', cachedInputCostUsd: '1.110912', outputCostUsd: '0.55446', totalCostUsd: '2.258372' },
        'a',
      ),
      costRun(
        'ledger--agent-lab-cost-enterpriseops-sol-max-preloaded-20260904.v1',
        'enterpriseops-csm-sol-max-preloaded-validation-20260904-v1',
        { uncachedInputTokens: 91_845, cachedInputTokens: 1_179_648, outputTokens: 17_222 },
        { uncachedInputCostUsd: '0.459225', cachedInputCostUsd: '0.589824', outputCostUsd: '0.51666', totalCostUsd: '1.565709' },
        'b',
      ),
      estimateRun(
        'ledger--agent-lab-cost-memory-sol-max-full-json-baseline-20260904.r2.v1',
        'memory-maintenance-sol-max-full-json-baseline-20260904-r2',
        'gpt-5.6-sol',
        { uncachedInputTokens: 39_799, cachedInputTokens: 0, outputTokens: 2_207 },
        { uncachedInputCostUsd: '0.198995', cachedInputCostUsd: '0', outputCostUsd: '0.06621', totalCostUsd: '0.265205' },
      ),
      estimateRun(
        'ledger--agent-lab-cost-memory-sol-max-concise-contract-20260904.r3.v1',
        'memory-maintenance-sol-max-concise-contract-candidate-20260904-r3',
        'gpt-5.6-sol',
        { uncachedInputTokens: 39_638, cachedInputTokens: 0, outputTokens: 1_650 },
        { uncachedInputCostUsd: '0.19819', cachedInputCostUsd: '0', outputCostUsd: '0.0495', totalCostUsd: '0.24769' },
      ),
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': retainedResponse,
      'agent.eval-lab.evidence': catalog,
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}><EvalLabFeature /></PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    const enterpriseProject = (await screen.findByRole('heading', { level: 3, name: '企业客户支持' })).closest('.eval-lab__project-matrix');
    const memoryProject = screen.getByRole('heading', { level: 3, name: '长期记忆整理' }).closest('.eval-lab__project-matrix');
    expect(within(enterpriseProject as HTMLElement).getByText('项目验收：已达标')).toBeInTheDocument();
    expect(within(enterpriseProject as HTMLElement).getByText(/Runtime 对账 API 成本 \$2\.2584 USD → \$1\.5657 USD（降低 30\.7%）/)).toBeInTheDocument();
    expect(within(memoryProject as HTMLElement).getByText('项目验收：已达标')).toBeInTheDocument();
    expect(within(memoryProject as HTMLElement).getByText(/绑定用量 API 估算 \$0\.2652 USD → \$0\.2477 USD（降低 6\.6%）/)).toBeInTheDocument();
    expect(`${enterpriseProject?.textContent ?? ''}${memoryProject?.textContent ?? ''}`).not.toContain('80%');
  });

  it('uses final CloudOps task success when a recovered Tool error is not an explicit hard gate', async () => {
    const recoveredResponse = structuredClone(response) as any;
    const experiment = recoveredResponse.experiments[0];
    experiment.evaluationKind = 'workflow';
    experiment.effectStatus = 'improved';
    experiment.scoring = {
      ...experiment.scoring,
      primaryMetric: 'AnswerCoverage + CA',
      hardGates: ['12/12 canonical answers', 'CA 1.0', 'frozen scorer'],
    };
    experiment.baseline.metrics = {
      answerCoverage: 1,
      ca: 1,
      formalScoreProduced: 1,
      failedToolCalls: 0,
      usageReceiptAvailable: 1,
      sameProviderModelThinking: 1,
      uncachedInputTokens: 100,
      cachedInputTokens: 200,
      outputTokens: 50,
    };
    experiment.candidate.metrics = {
      answerCoverage: 1,
      ca: 1,
      formalScoreProduced: 1,
      failedToolCalls: 1,
      usageReceiptAvailable: 1,
      sameProviderModelThinking: 1,
      uncachedInputTokens: 90,
      cachedInputTokens: 180,
      outputTokens: 40,
    };
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': recoveredResponse,
      'agent.eval-lab.evidence': previewEvalLabEvidence(),
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('项目验收：未完成')).toBeInTheDocument();
    expect(screen.getByText(/最终任务成功且质量不退化/)).toBeInTheDocument();
    expect(screen.getByText(/用量下降，但缺少绑定且可核验的价格回执/)).toBeInTheDocument();
  });

  it('still rejects a recovered Tool error when zero failures are an explicit product hard gate', async () => {
    const hardGateResponse = structuredClone(response) as any;
    const experiment = hardGateResponse.experiments[0];
    experiment.evaluationKind = 'workflow';
    experiment.effectStatus = 'improved';
    experiment.scoring = {
      ...experiment.scoring,
      primaryMetric: 'AnswerCoverage + CA',
      hardGates: ['12/12 canonical answers', 'zero Tool failures'],
    };
    experiment.baseline.metrics = {
      answerCoverage: 1,
      ca: 1,
      formalScoreProduced: 1,
      failedToolCalls: 0,
      usageReceiptAvailable: 1,
      sameProviderModelThinking: 1,
      uncachedInputTokens: 100,
      cachedInputTokens: 200,
      outputTokens: 50,
    };
    experiment.candidate.metrics = {
      answerCoverage: 1,
      ca: 1,
      formalScoreProduced: 1,
      failedToolCalls: 1,
      usageReceiptAvailable: 1,
      sameProviderModelThinking: 1,
      uncachedInputTokens: 90,
      cachedInputTokens: 180,
      outputTokens: 40,
    };
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': hardGateResponse,
      'agent.eval-lab.evidence': previewEvalLabEvidence(),
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('项目验收：未完成')).toBeInTheDocument();
  });

  it('uses exact real evidence receipts and keeps a token-regressed candidate incomplete', async () => {
    const receiptResponse = structuredClone(response) as any;
    const experiment = receiptResponse.experiments[0];
    experiment.effectStatus = 'improved';
    experiment.baseline = {
      ...experiment.baseline,
      runId: 'cost-baseline',
      evidenceRefs: [],
      metrics: { taskSuccessRate: 0.5, verifierPassRate: 0.75 },
    };
    experiment.candidate = {
      ...experiment.candidate,
      runId: 'cost-candidate',
      evidenceRefs: [],
      metrics: { taskSuccessRate: 1, verifierPassRate: 1, failedToolCalls: 0 },
    };
    const catalog = structuredClone(previewEvalLabEvidence()) as any;
    catalog.runs = [
      {
        ...catalog.runs[0],
        runId: 'cost-baseline',
        sourceId: 'paw-local-test',
        sourceLabel: '真实测试运行',
        environment: {
          provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'max',
          usageReceipt: { source: 'transcript', input: 100, cacheRead: 200, output: 50 },
        },
      },
      {
        ...catalog.runs[0],
        runId: 'cost-candidate',
        sourceId: 'paw-local-test',
        sourceLabel: '真实测试运行',
        environment: {
          provider: 'openai-codex', model: 'gpt-5.6-sol', thinking: 'max',
          usageReceipt: { source: 'transcript', input: 110, cacheRead: 200, output: 40 },
        },
      },
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': receiptResponse,
      'agent.eval-lab.evidence': catalog,
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('项目验收：未完成')).toBeInTheDocument();
    expect(screen.getByText('同模型 OAuth 用量回执：未缓存输入 100 → 110 · 缓存输入 200 → 200 · 输出 50 → 40；用量未全面下降，且缺少绑定且可核验的价格回执')).toBeInTheDocument();
  });

  it('marks an older path receipt as historical when a newer project path exists', async () => {
    const historical = response.pathSearches[0];
    const current = {
      ...historical,
      searchId: 'enterpriseops-model-cost-path-v2',
      title: 'EnterpriseOps CSM · 质量优先模型成本路径',
      claimStatus: 'insufficient_evidence' as const,
      claimSummary: '没有候选同时通过质量门禁，保留基线。',
      generatedAtMs: 5,
    };
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': {
          ...response,
          pathSearchTotal: 2,
          pathSearches: [current, historical],
        },
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('tab', { name: '方案路径' }));
    expect(screen.getByText('历史快照')).toBeInTheDocument();
    expect(screen.getByText(/此路径已被同项目较新的回执覆盖，不代表当前选择/)).toBeInTheDocument();
    expect(screen.getByText('历史结论：')).toBeInTheDocument();
    expect(screen.getByText('当前结论：')).toBeInTheDocument();
  });

  it('includes public Trace receipt ids in the exported HTML audit', async () => {
    const traceId = 'trace:enterpriseops:validation:aggregate';
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:eval-lab-trace-audit');
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': response,
      'agent.eval-lab.evidence': {
        schemaVersion: 'rag-ime.eval-lab-evidence.v1',
        ok: true,
        source: { available: true, label: '测试证据', runCount: 1, sessionCount: 0, transcriptCount: 0, transcriptBytes: 0 },
        sources: [],
        runs: [{
          runId: 'enterpriseops-suite-v2-final-validation-20260901',
          title: 'EnterpriseOps Validation',
          family: 'EnterpriseOps CSM',
          sourceId: 'test',
          sourceLabel: '测试证据',
          split: 'validation',
          status: 'completed',
          evidenceKind: 'report_only',
          reportAvailable: true,
          databaseAvailable: false,
          reportSha256: 'f'.repeat(64),
          sessionCount: 0,
          transcriptCount: 0,
          transcriptBytes: 0,
          metrics: {},
          environment: { traceCount: 1, traceIds: [traceId] },
          tasks: [],
          updatedAtMs: 1,
        }],
        total: 1,
      },
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('button', { name: '查看完整报告' }));
    await userEvent.setup().click(await screen.findByRole('button', { name: '导出报告' }));
    const blob = createObjectURL.mock.calls[0]?.[0] as Blob;
    const html = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener('load', () => resolve(String(reader.result ?? '')));
      reader.addEventListener('error', () => reject(reader.error));
      reader.readAsText(blob);
    });

    expect(html).toContain(traceId);
    expect(html).toContain('私有 Trace 正文不写入导出文件');
    expect(html).toContain('记录范围');
    expect(html).toContain('当前结果');

    anchorClick.mockRestore();
    createObjectURL.mockRestore();
  });

  it('summarizes answer-evidence quality, gates, and usage with public labels', async () => {
    const transport = new MockControlTransport({ routes: { 'agent.eval-lab.runs': answerEvidenceResponse } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/答案通过 2\/4 → 0\/4/)).toBeInTheDocument();
    expect(screen.getByText(/高层事实覆盖 66\.67% → 0\.00%/)).toBeInTheDocument();
    expect(screen.getByText(/引用事实覆盖 22\.22% → 0\.00%/)).toBeInTheDocument();
    expect(screen.getByText(/可回答问题引用支持 0\.00% → 0\.00%/)).toBeInTheDocument();
    expect(screen.getByText(/引用门禁 未通过 → 未通过/)).toBeInTheDocument();
    expect(screen.getByText(/应拒答问题拒答 100\.00% → 0\.00%/)).toBeInTheDocument();
    expect(screen.getByText(/Token 25,778 → 7,713.*Tool 6 → 12/)).toBeInTheDocument();
    expect(screen.getByText(/耗时 1m 4s → 7m 1s/)).toBeInTheDocument();

    await userEvent.setup().click(await screen.findByRole('button', { name: '查看完整报告' }));
    expect(screen.getAllByText('答案 Judge 正确率').length).toBeGreaterThan(0);
    expect(screen.getAllByText('高层事实覆盖').length).toBeGreaterThan(0);
    expect(screen.getAllByText('可回答引用支持').length).toBeGreaterThan(0);
    expect(screen.getByText(/当前 run enterpriseops-suite-v2-final-validation-20260901 已拒绝/)).toBeInTheDocument();
    expect(screen.queryByText('当前只证明检索显著改善；最终回答的引用门禁仍未通过，因此候选被拒绝。')).not.toBeInTheDocument();
  });

  it('creates a read-only App-owned Room and embeds it in the Agent Lab Session page', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': response,
        'agent.roles.list': {
          items: [
            persona('companion-present-v1', 'Agent 1'),
            persona('companion-firstlight-v1', 'Agent 2'),
            persona('companion-future-v1', 'Agent 3'),
            persona('companion-flash-v1', 'Agent 4'),
          ],
        },
        'agent.rooms.create': {
          ok: true,
          room: {
            id: 'room-eval-lab-1',
            title: 'Agent Lab · EnterpriseOps CSM',
            participants: [],
          },
        },
        'agent.room.message': { ok: true },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });
    const openWindow = vi.fn<(request: PawOsWindowRequest) => void>();

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={openWindow}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('heading', { level: 1, name: 'Agent 工作流实验室' })).toBeInTheDocument();
    await userEvent.setup().click(await screen.findByRole('button', { name: '查看完整报告' }));
    await userEvent.setup().click(await screen.findByRole('button', { name: '在 Room 中继续下一轮' }));

    await vi.waitFor(() => expect(transport.requests.map(({ request }) => request.pathId)).toEqual(
      expect.arrayContaining(['agent.roles.list', 'agent.rooms.create', 'agent.room.message']),
    ));
    const create = transport.requests.find(({ request }) => request.pathId === 'agent.rooms.create')?.request;
    expect(create?.body).toMatchObject({
      roomKind: 'collaboration',
      routingPolicy: 'natural',
      permissionPolicy: {
        schemaVersion: 'rag-ime.room-permission-policy.v1',
        room: { executionMode: 'read_only' },
        partner: { executionMode: 'inherit' },
        toolAgent: { executionMode: 'inherit' },
      },
      ownerAppId: 'extension:agent-lab',
      surfaceKey: 'experiment.enterpriseops-csm-v2',
    });
    expect(create?.body).not.toHaveProperty('executionMode');
    const participants = (create?.body as { participants?: unknown[] } | undefined)?.participants;
    expect(participants).toHaveLength(4);
    expect(participants).toEqual(expect.arrayContaining([
      expect.objectContaining({ roleId: 'companion-present-v1', collaborationRole: 'coordinator' }),
      expect.objectContaining({ collaborationRole: 'researcher' }),
      expect.objectContaining({ collaborationRole: 'implementer' }),
      expect.objectContaining({ collaborationRole: 'reviewer' }),
    ]));
    const message = transport.requests.find(({ request }) => request.pathId === 'agent.room.message')?.request;
    expect(message?.body).toMatchObject({
      clientMessageId: expect.stringContaining('eval-lab:'),
    });
    expect(String((message?.body as Record<string, unknown> | undefined)?.message ?? '')).not.toContain(
      '$agent-eval-room-optimizer',
    );
    expect(String((create?.body as Record<string, unknown> | undefined)?.scenarioPrompt ?? '')).toContain(
      '$agent-eval-room-optimizer',
    );
    expect(String((create?.body as Record<string, unknown> | undefined)?.scenarioPrompt ?? '')).toContain(
      '只依据本轮检索到且可回跳的原始证据回答',
    );
    expect(String((create?.body as Record<string, unknown> | undefined)?.scenarioPrompt ?? '')).toContain(
      '禁止把 room/session/event ID 伪装成 sourceId/chunkId',
    );
    expect(message?.body).toMatchObject({ message: expect.stringContaining('evaluationKind: rag_retrieval') });
    expect(openWindow).not.toHaveBeenCalled();
    expect(await screen.findByLabelText('Agent Lab Room workspace')).toHaveAttribute('data-room-id', 'room-eval-lab-1');
    expect(screen.getByLabelText('Agent Lab Room workspace')).toHaveAttribute(
      'data-participant-process-location',
      'room-transcript',
    );
    expect(screen.getByRole('tab', { name: '对话与证据' })).toHaveAttribute('aria-selected', 'true');
  });

  it('shows an independently recorded Room review instead of synthesizing reviewer approval', async () => {
    const room = {
      id: 'room-reviewed-candidate',
      title: 'Agent Lab · 新候选 · EnterpriseOps CSM workflow',
      status: 'active',
      routingPolicy: 'natural',
      moderatorParticipantId: 'coordinator-1',
      updatedAtMs: 9,
      ownerAppId: 'extension:agent-lab',
      surfaceKey: 'candidate.enterpriseops-csm-v2',
      participants: [
        { id: 'reviewer-1', sessionId: 'agent:reviewer-1', roleId: 'reviewer', roleVersion: '1', displayName: '独立检查 Agent', collaborationRole: 'reviewer', status: 'idle', ordinal: 1 },
      ],
      workItems: [{
        id: 'work-1', roomId: 'room-reviewed-candidate', topicId: '', rootTurnId: '', rootWorkId: 'work-1', parentWorkId: '',
        objective: '验证候选执行链', expectedOutput: '独立结论', acceptanceCriteria: ['可运行', '满足需求'],
        accountableParticipantId: 'reviewer-1', currentOwnerParticipantId: 'reviewer-1', offeredToParticipantId: '', createdByParticipantId: 'coordinator-1', clientMessageId: 'review-1',
        state: 'done', depth: 0, revision: 1, resultSummary: '候选方案已通过独立检查。', artifactRefs: ['artifact:report'], evidenceRefs: ['trace:candidate-run'],
        review: { operabilityVerdict: 'pass', requirementVerdict: 'pass', evidenceRefs: ['trace:candidate-run', 'eval:validation-1'], reason: '执行完成，且验收条件全部满足。', reviewerParticipantId: 'reviewer-1', reviewedAtMs: 8 },
        blocker: {}, acceptedTurnId: '', createdAtMs: 2, updatedAtMs: 8, completedAtMs: 8,
      }],
    } as const;
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': response,
      'agent.eval-lab.evidence': { schemaVersion: 'rag-ime.eval-lab-evidence.v1', ok: true, source: { available: false, label: 'none', runCount: 0, sessionCount: 0, transcriptCount: 0, transcriptBytes: 0 }, runs: [], total: 0 },
      'agent.roles.list': { items: [persona('companion-present-v1', 'Agent 1')] },
      'agent.rooms.list': { ok: true, items: [room] },
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}><EvalLabFeature /></PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('button', { name: '查看完整报告' }));
    expect(await screen.findByRole('heading', { level: 3, name: '独立检查回执' })).toBeInTheDocument();
    expect(screen.getByText('候选方案已通过独立检查。')).toBeInTheDocument();
    expect(screen.getByText('执行完成，且验收条件全部满足。')).toBeInTheDocument();
    expect(screen.getByText('trace:candidate-run')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: '打开检查对话' }));
    expect(await screen.findByLabelText('Agent Lab Room workspace')).toHaveAttribute('data-room-id', 'room-reviewed-candidate');
  });

  it('opens a guided intake Room before any evaluation data exists', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': {
          schemaVersion: 'rag-ime.eval-lab-run-list.v1', ok: true, total: 0, items: [], experiments: [], experimentTotal: 0,
        },
        'agent.roles.list': {
          items: [
            persona('companion-present-v1', 'Agent 1'),
            persona('companion-firstlight-v1', 'Agent 2'),
            persona('companion-future-v1', 'Agent 3'),
          ],
        },
        'agent.rooms.create': {
          ok: true,
          room: { id: 'room-eval-wizard-1', title: 'Agent Lab · 评测向导', participants: [] },
        },
        'agent.room.message': { ok: true },
        'agent.rooms.list': { ok: true, items: [] },
      },
    });
    const openWindow = vi.fn<(request: PawOsWindowRequest) => void>();

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={openWindow}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('button', { name: '新建评测' }));
    await vi.waitFor(() => expect(transport.requests.map(({ request }) => request.pathId)).toEqual(
      expect.arrayContaining(['agent.roles.list', 'agent.rooms.create', 'agent.room.message']),
    ));
    const create = transport.requests.find(({ request }) => request.pathId === 'agent.rooms.create')?.request;
    expect(create?.body).toMatchObject({
      title: 'Agent Lab · 评测向导',
      roomKind: 'collaboration',
      permissionPolicy: {
        schemaVersion: 'rag-ime.room-permission-policy.v1',
        room: { executionMode: 'read_only' },
        partner: { executionMode: 'inherit' },
        toolAgent: { executionMode: 'inherit' },
      },
      ownerAppId: 'extension:agent-lab',
      surfaceKey: 'wizard',
    });
    expect(create?.body).not.toHaveProperty('executionMode');
    expect((create?.body as { participants?: unknown[] } | undefined)?.participants).toHaveLength(3);
    const message = transport.requests.find(({ request }) => request.pathId === 'agent.room.message')?.request;
    expect(message?.body).toMatchObject({
      message: expect.stringContaining('先提问和补数据'),
      clientMessageId: 'eval-lab:evaluation-wizard',
    });
    expect(String((message?.body as Record<string, unknown> | undefined)?.message ?? '')).not.toContain(
      '$agent-eval-room-optimizer',
    );
    expect(String((create?.body as Record<string, unknown> | undefined)?.scenarioPrompt ?? '')).toContain(
      '$agent-eval-room-optimizer',
    );
    expect(openWindow).not.toHaveBeenCalled();
    expect(await screen.findByLabelText('Agent Lab Room workspace')).toHaveAttribute('data-room-id', 'room-eval-wizard-1');
  });

  it('starts a fresh intake when the previous wizard Room failed', async () => {
    const failedWizard = {
      id: 'room-eval-wizard-failed',
      title: 'Agent Lab · 评测向导',
      status: 'active',
      routingPolicy: 'natural',
      moderatorParticipantId: '',
      updatedAtMs: 1,
      participants: [],
      ownerAppId: 'extension:agent-lab',
      surfaceKey: 'wizard',
      workItems: [{ state: 'failed', updatedAtMs: 2 }],
    };
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': {
          schemaVersion: 'rag-ime.eval-lab-run-list.v1', ok: true, total: 0, items: [], experiments: [], experimentTotal: 0,
        },
        'agent.roles.list': {
          items: [
            persona('companion-present-v1', 'Agent 1'),
            persona('companion-firstlight-v1', 'Agent 2'),
          ],
        },
        'agent.rooms.list': { ok: true, items: [{ ...failedWizard, workItems: undefined }] },
        'agent.room.get': { ok: true, room: failedWizard },
        'agent.rooms.create': {
          ok: true,
          room: { id: 'room-eval-wizard-fresh', title: 'Agent Lab · 评测向导', participants: [] },
        },
        'agent.room.message': { ok: true },
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}><EvalLabFeature /></PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('button', { name: '新建评测' }));
    await vi.waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'agent.rooms.create')).toBe(true));
    expect(await screen.findByLabelText('Agent Lab Room workspace')).toHaveAttribute('data-room-id', 'room-eval-wizard-fresh');
  });

  it('restores and switches only Agent Lab owned Rooms inside the Session page', async () => {
    const rooms = [
      { id: 'room-owned-a', title: 'Agent Lab · 诊断 A', status: 'active', routingPolicy: 'natural', moderatorParticipantId: '', updatedAtMs: 2, participants: [], ownerAppId: 'extension:agent-lab', surfaceKey: 'experiment.a' },
      { id: 'room-owned-b', title: 'Agent Lab · 候选 B', status: 'active', routingPolicy: 'natural', moderatorParticipantId: '', updatedAtMs: 1, participants: [], ownerAppId: 'extension:agent-lab', surfaceKey: 'candidate.b' },
      { id: 'room-foreign', title: '其他 App 的 Room', status: 'active', routingPolicy: 'natural', moderatorParticipantId: '', updatedAtMs: 3, participants: [], ownerAppId: 'extension:other-app', surfaceKey: 'foreign' },
    ];
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.runs': response,
      'agent.eval-lab.evidence': { schemaVersion: 'rag-ime.eval-lab-evidence.v1', ok: true, source: { available: false, label: 'none', runCount: 0, sessionCount: 0, transcriptCount: 0, transcriptBytes: 0 }, runs: [], total: 0 },
      'agent.roles.list': { items: [persona('companion-present-v1', 'Agent 1')] },
      'agent.rooms.list': { ok: true, items: rooms },
    } });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}><EvalLabFeature /></PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('tab', { name: '对话与证据' }));
    expect(await screen.findByLabelText('Agent Lab Room workspace')).toHaveAttribute('data-room-id', 'room-owned-a');
    expect(transport.requests.find(({ request }) => request.pathId === 'agent.rooms.list')?.request.query).toMatchObject({ ownerAppId: 'extension:agent-lab' });
    expect(screen.queryByRole('button', { name: '其他 App 的 Room' })).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Agent Lab · 候选 B' }));
    expect(screen.getByLabelText('Agent Lab Room workspace')).toHaveAttribute('data-room-id', 'room-owned-b');
  });

  it('creates a managed Validation Room after workspace selection without a second approval', async () => {
    const transport = new MockControlTransport({
      pickedFiles: [{ id: 'workspace', name: 'candidate', mimeType: 'inode/directory', byteSize: 0, path: '/workspace/candidate' }],
      routes: {
        'agent.eval-lab.runs': response,
        'agent.roles.list': { items: [persona('companion-present-v1', 'Agent 1'), persona('companion-firstlight-v1', 'Agent 2')] },
        'agent.rooms.create': { ok: true, room: { id: 'room-candidate-1', title: 'Agent Lab · 新候选 · EnterpriseOps CSM workflow', participants: [] } },
        'agent.room.message': { ok: true },
        'agent.rooms.list': { ok: true, items: [] },
        'agent.eval-lab.evidence': { schemaVersion: 'rag-ime.eval-lab-evidence.v1', ok: true, source: { available: false, label: 'none', runCount: 0, sessionCount: 0, transcriptCount: 0, transcriptBytes: 0 }, runs: [], total: 0 },
      },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={vi.fn()}><EvalLabFeature /></PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole('button', { name: '查看完整报告' }));
    await user.click(screen.getByRole('button', { name: '测试新方案' }));
    expect(transport.filePickCalls[0]).toMatchObject({ purpose: 'workspace-root', selection: 'directory', multiple: false });
    expect(screen.queryByRole('checkbox', { name: /我已核对以上六项/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '确认并创建候选 Room' })).not.toBeInTheDocument();
    expect(await screen.findByLabelText('Agent Lab Room workspace')).toHaveAttribute('data-room-id', 'room-candidate-1');
    const create = transport.requests.find(({ request }) => request.pathId === 'agent.rooms.create')?.request;
    expect(create?.body).toMatchObject({
      workspaceRoots: ['/workspace/candidate'],
      permissionPolicy: {
        schemaVersion: 'rag-ime.room-permission-policy.v1',
        room: { executionMode: 'workspace_managed' },
        partner: { executionMode: 'inherit' },
        toolAgent: { executionMode: 'inherit' },
      },
      workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE',
      ownerAppId: 'extension:agent-lab',
    });
    expect(create?.body).not.toHaveProperty('executionMode');
    const scenarioPrompt = String((create?.body as Record<string, unknown>)?.scenarioPrompt);
    expect(scenarioPrompt).toContain('点击“测试新方案”并选定 workspace，即构成本次 Validation dispatch 授权；无需二次批准，直接执行。');
    expect(scenarioPrompt).toContain('Validation only');
    expect(scenarioPrompt).toContain('不得读取或运行 Held-out');
    expect(scenarioPrompt).toContain('不得安装、发布或触发工作区之外的外部副作用');
    const dispatch = transport.requests.find(({ request }) => request.pathId === 'agent.room.message')?.request;
    expect(String((dispatch?.body as Record<string, unknown>)?.message)).toContain('无需二次批准，直接执行');
  });

  it('renders an experiment ledger even when no Session run has been imported yet', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': { ...response, total: 0, items: [], experimentTotal: 1 },
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={() => undefined}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('button', { name: '查看完整报告' }));
    expect(await screen.findByRole('heading', { level: 2, name: 'EnterpriseOps CSM workflow' })).toBeInTheDocument();
    expect(screen.queryByText('还没有可查看的评测批次')).toBeNull();
    expect(screen.getByText('尚未找到与 baseline/candidate runId 匹配的真实 Session。')).toBeInTheDocument();
  });

  it('does not render a copied transcript or task cards when the ledger is empty', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': {
          schemaVersion: 'rag-ime.eval-lab-run-list.v1', ok: true, total: 0, items: [], experiments: [], experimentTotal: 0,
        },
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={() => undefined}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('还没有实验')).toBeInTheDocument();
    expect(screen.queryByText('用户')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '查看对话' })).toBeNull();
  });

  it('keeps report-only task rows out of the transcript state', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': response,
        'agent.eval-lab.evidence': {
          schemaVersion: 'rag-ime.eval-lab-evidence.v1',
          ok: true,
          source: { available: true, label: '测试证据', runCount: 1, sessionCount: 3, transcriptCount: 3, transcriptBytes: 0, reportOnlyRunCount: 1 },
          runs: [{
            runId: 'report-with-tasks', title: '只有报告的批次', family: 'EnterpriseOps', sourceId: 'report-source', sourceLabel: '测试证据', split: 'validation', status: 'rejected', evidenceKind: 'report_only', reportAvailable: true, databaseAvailable: false, sessionCount: 3, transcriptCount: 3, transcriptBytes: 0,
            metrics: { taskSuccessCount: 0, taskCount: 1 }, environment: {}, tasks: [{
              taskIndex: 1, taskLabel: 'Task 1', title: 'Task 1', transcriptAvailable: false, transcriptSha256: '', transcriptBytes: 0, jsonlLines: 0, userMessages: 0, assistantMessages: 0, toolCalls: 0, toolFailures: 0, toolNames: [], externalSessionRef: '', model: '', thinking: '', executionMode: 'unknown', createdAtMs: 0, updatedAtMs: 0, evidenceStatus: 'report_only', taskSucceeded: false, terminalEvent: 'unknown', verifierPassed: 1, verifierTotal: 2,
            }], updatedAtMs: 1,
          }],
          total: 1,
          detail: {
            status: 'transcript_missing', runId: 'report-with-tasks', taskIndex: 1,
            task: { taskIndex: 1, taskLabel: 'Task 1', title: 'Task 1', transcriptAvailable: false, transcriptSha256: '', transcriptBytes: 0, jsonlLines: 0, userMessages: 0, assistantMessages: 0, toolCalls: 0, toolFailures: 0, toolNames: [], externalSessionRef: '', model: '', thinking: '', executionMode: 'unknown', createdAtMs: 0, updatedAtMs: 0, evidenceStatus: 'report_only', taskSucceeded: false, terminalEvent: 'unknown', verifierPassed: 1, verifierTotal: 2 },
            environment: {}, turns: [], tools: [], report: { status: 'rejected', decision: 'reject', metrics: { transcriptToolCalls: 12, sourceLocal: 1, installed: 0 } },
          },
        },
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={() => undefined}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('tab', { name: '对话与证据' }));
    await userEvent.setup().click(await screen.findByRole('button', { name: '查看报告证据' }));

    await vi.waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'agent.eval-lab.evidence' && request.query?.runId === 'report-with-tasks' && request.query?.taskIndex === '0')).toBe(true));
    expect((await screen.findAllByRole('heading', { level: 3, name: '运行报告' })).length).toBeGreaterThan(0);
    expect(screen.getAllByText('这条运行只有回执/报告，原始对话未公开；请按逐 case/报告核对。').length).toBeGreaterThan(0);
    expect(screen.getByText('3 个 Session 回执/报告，原文未公开')).toBeInTheDocument();
    expect(screen.queryByText('3/3 份对话')).toBeNull();
    expect(screen.getAllByText('Transcript Tool 调用').length).toBeGreaterThan(0);
    expect(screen.getAllByText('仅本机').length).toBeGreaterThan(0);
    expect(screen.queryByText('无法打开逐轮对话')).toBeNull();
  });

  it('describes a run-level report separately when the run also has transcripts', async () => {
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': response,
        'agent.eval-lab.evidence': {
          schemaVersion: 'rag-ime.eval-lab-evidence.v1', ok: true,
          source: { available: true, label: '测试证据', runCount: 1, sessionCount: 1, transcriptCount: 1, transcriptBytes: 100 },
          runs: [{
            runId: 'run-with-report', title: '有对话也有报告', family: 'EnterpriseOps', sourceId: 'source', sourceLabel: '测试证据', split: 'validation', status: 'completed', evidenceKind: 'transcript_and_report', reportAvailable: true, databaseAvailable: true, sessionCount: 1, transcriptCount: 1, transcriptBytes: 100,
            metrics: {}, environment: {}, tasks: [{ taskIndex: 1, taskLabel: 'Task 1', title: 'Task 1', transcriptAvailable: true, transcriptSha256: 'abc', transcriptBytes: 100, jsonlLines: 2, userMessages: 1, assistantMessages: 1, toolCalls: 0, toolFailures: 0, toolNames: [], externalSessionRef: 's1', model: 'gpt-5.6-sol', thinking: 'high', executionMode: 'read_only', createdAtMs: 0, updatedAtMs: 1, evidenceStatus: 'available' }], updatedAtMs: 1,
          }], total: 1,
          detail: { status: 'report_available', runId: 'run-with-report', taskIndex: 0, environment: {}, turns: [], tools: [], report: { status: 'completed' } },
        },
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={() => undefined}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('tab', { name: '对话与证据' }));
    await userEvent.setup().click(await screen.findByRole('button', { name: '查看运行报告' }));

    expect((await screen.findAllByText('这是该运行的公开报告投影；报告与逐轮 transcript 分开展示。')).length).toBeGreaterThan(0);
    expect(screen.queryByText('这条回执没有公开 Session；这里展示可复核的报告摘要和证据边界。')).toBeNull();
  });

  it('does not attach a similarly named run to an experiment without an exact receipt identity', async () => {
    const expectedRunId = 'enterpriseops-csm-state-contract-validation-20260901-v2';
    const similarlyNamedRunId = 'enterpriseops-csm-state-contract-validation-20260901-v20';
    const transport = new MockControlTransport({
      routes: {
        'agent.eval-lab.runs': {
          ...response,
          experiments: [{
            ...response.experiments[0],
            baseline: { ...response.experiments[0].baseline, runId: expectedRunId },
            candidate: { ...response.experiments[0].candidate, runId: expectedRunId },
          }],
        },
        'agent.eval-lab.evidence': {
          schemaVersion: 'rag-ime.eval-lab-evidence.v1',
          ok: true,
          source: { available: true, label: '测试证据', runCount: 1, sessionCount: 1, transcriptCount: 1, transcriptBytes: 100 },
          runs: [{
            runId: similarlyNamedRunId,
            title: 'EnterpriseOps 状态合同相似批次',
            family: 'EnterpriseOps CSM',
            sourceId: 'source',
            sourceLabel: '测试证据',
            split: 'validation',
            status: 'completed',
            evidenceKind: 'transcript_and_report',
            reportAvailable: true,
            databaseAvailable: true,
            sessionCount: 1,
            transcriptCount: 1,
            transcriptBytes: 100,
            metrics: {},
            environment: {},
            tasks: [],
            updatedAtMs: 1,
          }],
          total: 1,
        },
      },
    });

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ControlTransportProvider transport={transport}>
          <PawOsDesktopProvider openWindow={() => undefined}>
            <EvalLabFeature />
          </PawOsDesktopProvider>
        </ControlTransportProvider>
      </QueryClientProvider>,
    );

    await userEvent.setup().click(await screen.findByRole('button', { name: '查看完整报告' }));
    expect(await screen.findByText('当前没有匹配的公开 transcript')).toBeInTheDocument();
    expect(screen.queryByText(similarlyNamedRunId)).not.toBeInTheDocument();
  });
});

function persona(roleId: string, displayName: string) {
  return {
    schemaVersion: 'rag-ime.agent-persona.v1',
    roleId,
    version: '1',
    displayName,
  };
}
