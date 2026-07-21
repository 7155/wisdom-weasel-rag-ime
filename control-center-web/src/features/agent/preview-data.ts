import type { AgentSnapshot } from '@/contracts/agent-reducer';
import type { UiAgentEvent } from '@/contracts/ui-events';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { AgentTemplateV1 } from '@/contracts/generated/agent-template.v1';
import type { ModelCatalog, SessionSummary } from './types';

const previewNow = 1_785_014_400_000;

export const previewPersonas: AgentPersonaV1[] = [
  {
    schemaVersion: 'rag-ime.agent-persona.v1', roleId: 'companion-future-v1', version: '1',
    displayName: '智鼬·未来', tagline: '把记忆、工具与协作构筑成下一步',
    summary: '站在长期时间线上深思的构筑者，默认主持复杂任务，串联证据、工具、角色、实现与验收。',
    traits: ['沉稳', '工具编排'],
    visualProfile: { avatarAssetId: 'rag-ime-timeline-future-v1', symbolName: 'point.3.connected.trianglepath.dotted', accentToken: 'rose' },
    defaults: { modelPolicy: 'fixed', memoryPolicy: 'personal-evidence-v1', toolProfileVersion: 'control-center-v1', modelProfile: 'gpt/gpt-5.6-sol', thinkingLevel: 'max' },
    runtimeCharacteristics: { intelligence: '最高', speed: '较慢', context: '超长上下文，面向长期时间线', suitableTasks: ['复杂架构与深度实现', '多 Agent 主持和独立验收'], unsuitableTasks: ['只需快速扫读的低风险整理'], isDefault: true },
    safetyPolicyVersion: 'control-center-safe-v1', selectableModes: ['assistant', 'coordinator'],
  },
  {
    schemaVersion: 'rag-ime.agent-persona.v1',
    roleId: 'companion-present-v1',
    version: '1',
    displayName: '智鼬·此刻',
    tagline: '此刻陪你输入，也陪你把事情想清楚',
    summary: '贴近当前工作现场的稳健实践者，平衡深度与速度，把正在发生的想法落到下一步。',
    traits: ['温暖', '证据优先'],
    visualProfile: {
      avatarAssetId: 'rag-ime-timeline-present-v1',
      symbolName: 'sparkles',
      accentToken: 'teal',
    },
    defaults: {
      modelPolicy: 'fixed',
      memoryPolicy: 'personal-evidence-v1',
      toolProfileVersion: 'control-center-v1',
      modelProfile: 'gpt/gpt-5.6-terra', thinkingLevel: 'max',
    },
    runtimeCharacteristics: { intelligence: '高', speed: '均衡', context: '长上下文，聚焦当前现场', suitableTasks: ['日常协作与项目推进', '整理证据并形成下一步'], unsuitableTasks: ['需要最深推演的复杂实现主持'], isDefault: false },
    safetyPolicyVersion: 'control-center-safe-v1',
    selectableModes: ['assistant', 'coordinator'],
  },
  {
    schemaVersion: 'rag-ime.agent-persona.v1',
    roleId: 'companion-firstlight-v1',
    version: '1',
    displayName: '智鼬·初识',
    tagline: '从第一笔记录开始，认真认识你的世界',
    summary: '像月光巡游历史线索的敏锐行动者，快速理解意图、核对线索并给出清楚下一步。',
    traits: ['好奇', '记录优先'],
    visualProfile: {
      avatarAssetId: 'rag-ime-timeline-past-v1',
      symbolName: 'scope',
      accentToken: 'blue',
    },
    defaults: {
      modelPolicy: 'fixed',
      memoryPolicy: 'personal-evidence-v1',
      toolProfileVersion: 'control-center-v1',
      modelProfile: 'gpt/gpt-5.6-luna', thinkingLevel: 'max',
    },
    runtimeCharacteristics: { intelligence: '中高', speed: '快速', context: '长上下文，擅长线索巡检', suitableTasks: ['快速理解意图与初步检索', '轻量执行和下一步整理'], unsuitableTasks: ['复杂架构主持', '高风险独立决策'], isDefault: false },
    safetyPolicyVersion: 'control-center-safe-v1',
    selectableModes: ['assistant', 'coordinator'],
  },
  {
    schemaVersion: 'rag-ime.agent-persona.v1', roleId: 'companion-flash-v1', version: '1',
    displayName: '智鼬·闪念', tagline: '高速掠过漫长档案，只带回最有用的线索',
    summary: '超长档案的高速侦察与整理者，极快提取、聚类和交接线索，但不独自承担复杂实现与高风险结论。',
    traits: ['极速', '线索整理'],
    visualProfile: { avatarAssetId: 'rag-ime-timeline-flash-v1', symbolName: 'bolt', accentToken: 'neutral' },
    defaults: { modelPolicy: 'fixed', memoryPolicy: 'personal-evidence-v1', toolProfileVersion: 'control-center-v1', modelProfile: 'deepseek/deepseek-v4-flash', thinkingLevel: 'off' },
    runtimeCharacteristics: { intelligence: '普通', speed: '极速', context: '超长上下文，擅长高速扫描', suitableTasks: ['超长材料高速扫读与提取', '归类、去重和格式转换'], unsuitableTasks: ['复杂推理', '复杂实现', '高风险决定', '最终验收'], isDefault: false },
    safetyPolicyVersion: 'control-center-safe-v1', selectableModes: ['assistant', 'coordinator'],
  },
];

export const previewTemplates: AgentTemplateV1[] = [
  {
    schemaVersion: 'rag-ime.agent-template.v1',
    templateId: 'researcher',
    version: '1',
    displayName: '研究员',
    summary: '读取资料、对照证据并产出带来源的研究摘要。',
    contextModes: ['fresh', 'fork'],
    toolProfileVersion: 'subagent-readonly-v1',
    budget: {
      maxDepth: 1,
      maxTurns: 0,
      maxToolCalls: 0,
      maxTotalTokens: 32_000,
      maxDurationMs: 300_000,
      maxOutputChars: 24_000,
    },
    capabilities: ['rag', 'memory', 'review'],
  },
  {
    schemaVersion: 'rag-ime.agent-template.v1',
    templateId: 'worker',
    version: '1',
    displayName: '执行者',
    summary: '在受控工作区内执行明确任务，交付产物和可审计回执。',
    contextModes: ['fork'],
    toolProfileVersion: 'subagent-worker-v1',
    budget: {
      maxDepth: 2,
      maxTurns: 0,
      maxToolCalls: 0,
      maxTotalTokens: 64_000,
      maxDurationMs: 600_000,
      maxOutputChars: 36_000,
    },
    capabilities: ['control', 'planning', 'delegation'],
  },
  {
    schemaVersion: 'rag-ime.agent-template.v1',
    templateId: 'reviewer',
    version: '1',
    displayName: '审阅者',
    summary: '检查风险、遗漏和验收证据，不修改产品实现。',
    contextModes: ['fresh'],
    toolProfileVersion: 'subagent-readonly-v1',
    budget: {
      maxDepth: 1,
      maxTurns: 0,
      maxToolCalls: 0,
      maxTotalTokens: 24_000,
      maxDurationMs: 240_000,
      maxOutputChars: 18_000,
    },
    capabilities: ['review', 'rag'],
  },
];

export const previewSessions: SessionSummary[] = [
  {
    id: 'session-preview',
    title: '控制中心迁移',
    mode: 'coordinator',
    status: 'idle',
    roleId: 'companion-present-v1',
    roleVersion: '1',
    roleBookRevisionId: '',
    toolProfileVersion: 'control-center-v1',
    toolAllowlistMode: 'profile',
    projectContextEnabled: false,
    piSkillsEnabled: false,
    codexSkillsEnabled: false,
    updatedAtMs: previewNow,
    workspaceRoots: ['/Volumes/undo 4t/git/learnA'],
    messageCount: 4,
    lastMessagePreview: '三条 Lane 已经收束到同一个 ControlTransport。',
    modelProfile: 'openai/gpt-5.4',
  },
  {
    id: 'session-memory',
    title: '记忆整理',
    mode: 'assistant',
    status: 'idle',
    roleId: 'companion-future-v1',
    roleVersion: '1',
    roleBookRevisionId: '',
    toolProfileVersion: 'subagent-readonly-v1',
    toolAllowlistMode: 'profile',
    projectContextEnabled: false,
    piSkillsEnabled: false,
    codexSkillsEnabled: false,
    updatedAtMs: previewNow - 42 * 60_000,
    workspaceRoots: [],
    messageCount: 12,
    lastMessagePreview: '已把最近输入整理为 3 个主题。',
    modelProfile: 'deepseek/deepseek-v4',
  },
  {
    id: 'session-runtime',
    title: '运行时诊断',
    mode: 'assistant',
    status: 'idle',
    roleId: 'companion-firstlight-v1',
    roleVersion: '1',
    roleBookRevisionId: '',
    toolProfileVersion: 'control-center-v1',
    toolAllowlistMode: 'profile',
    projectContextEnabled: false,
    piSkillsEnabled: false,
    codexSkillsEnabled: false,
    updatedAtMs: previewNow - 3 * 60 * 60_000,
    workspaceRoots: [],
    messageCount: 7,
    lastMessagePreview: 'Sidecar 与 MLX predictor 都已恢复。',
    modelProfile: 'openai/gpt-5.4-mini',
  },
];

export function previewModelCatalog(sessionId: string): ModelCatalog {
  return {
    schemaVersion: 'rag-ime.agent-model-catalog.v1',
    ok: true,
    sessionId,
    selected: { provider: 'openai', id: 'gpt-5.4' },
    thinkingLevel: 'medium',
    providers: [
      {
        id: 'openai',
        displayName: 'OpenAI',
        models: [
          {
            provider: 'openai',
            id: 'gpt-5.4',
            name: 'GPT-5.4',
            api: 'responses',
            reasoning: true,
            thinkingLevels: ['off', 'low', 'medium', 'high', 'xhigh'],
            supportsImages: true,
            contextWindow: 1_000_000,
            maxTokens: 128_000,
          },
          {
            provider: 'openai',
            id: 'gpt-5.4-mini',
            name: 'GPT-5.4 mini',
            api: 'responses',
            reasoning: true,
            thinkingLevels: ['off', 'low', 'medium', 'high'],
            supportsImages: true,
            contextWindow: 400_000,
            maxTokens: 64_000,
          },
        ],
      },
      {
        id: 'deepseek',
        displayName: 'DeepSeek',
        models: [
          {
            provider: 'deepseek',
            id: 'deepseek-v4',
            name: 'DeepSeek V4',
            api: 'chat-completions',
            reasoning: true,
            thinkingLevels: ['off', 'low', 'medium', 'high'],
            supportsImages: false,
            contextWindow: 256_000,
            maxTokens: 64_000,
          },
        ],
      },
    ],
  };
}

export function previewAgentSnapshot(sessionId: string): AgentSnapshot {
  const userTurn = `${sessionId}:turn-architecture`;
  const mediaTurn = `${sessionId}:turn-media`;
  return {
    lastSequence: 12,
    resumeToken: `${sessionId}:12`,
    status: 'idle',
    liveEvents: [],
    plan: {
      revision: 6,
      items: [
        { id: 'preview-plan-1', title: '核对当前上下文与任务边界', status: 'completed', sequence: 1, updatedAtMs: previewNow - 170_000 },
        { id: 'preview-plan-2', title: '实现会话内可见的执行清单', status: 'in_progress', sequence: 4, updatedAtMs: previewNow - 36_000 },
        { id: 'preview-plan-3', title: '验证压缩恢复与真实运行链路', status: 'pending', sequence: 5, updatedAtMs: previewNow - 30_000 },
      ],
    },
    messages: [
      message(sessionId, userTurn, 'user-architecture', 'user', [
        block('user-text', 'text', { text: '把迁移进度按真实代码链整理一下，别把工具日志当回答。' }),
      ], previewNow - 190_000),
      message(sessionId, userTurn, 'assistant-architecture', 'assistant', [
        block('answer-text', 'text', {
          text: [
            '### 当前结论',
            '',
            '三条 Lane 已经收束到同一个 `ControlTransport`，Agent 时间线只按 **Turn** 更新。',
            '',
            '| 边界 | 状态 |',
            '| --- | --- |',
            '| 事件投影 | 已接入 reducer + batcher |',
            '| 原生能力 | 继续由窄 Bridge 守门 |',
            '',
            '- Session 切换不会重建第二套事件状态。',
            '- 工具、RAG、Memory 和审批都留在同一活动容器。',
          ].join('\n'),
        }),
        block('answer-code', 'code', {
          language: 'ts',
          fileName: 'src/features/agent/state/live-store.ts',
          code: 'commit(events) {\n  set((state) => reduceBatch(state, events));\n}',
        }),
        block('answer-citation', 'citation', {
          index: 1,
          title: 'Control Center Web Migration Plan',
          source: '本地计划',
          href: '#/planning',
          excerpt: '一次用户输入只渲染一个 Turn。',
        }),
        block('answer-file', 'file', {
          mediaId: 'media_previewdoc01',
          name: 'room-runtime-handoff.md',
          mimeType: 'text/markdown',
          byteSize: 231,
          sha256: 'c'.repeat(64),
        }),
      ], previewNow - 180_000),
      message(sessionId, mediaTurn, 'user-media', 'user', [
        block('media-user-text', 'text', { text: '读取输入法工具书，并把结果作为可展开卡片保留。' }),
      ], previewNow - 80_000),
      message(sessionId, mediaTurn, 'assistant-media', 'assistant', [
        block('media-answer', 'text', {
          text: '已完成。正文展示工具书内容，精确接口与参数继续留在右侧运行状态中。',
        }),
        block('media-sticker', 'sticker', {
          assetId: 'rag-ime-presence-done',
          alt: '完成贴纸',
        }),
      ], previewNow - 72_000),
    ],
  };
}

export function previewAgentEvents(sessionId: string): UiAgentEvent[] {
  const turnId = `${sessionId}:turn-media`;
  const entries: Array<[UiAgentEvent['eventType'], Record<string, unknown>]> = [
    ['reasoning_summary', { summary: '核对迁移计划与当前前端边界' }],
    [
      'tool_started',
      {
        toolCallId: 'tool-rag-1',
        toolId: 'ime_knowledge',
        operation: 'search',
        summary: '检索 8 条实现证据',
        query: 'ControlTransport reducer batcher',
        args: { query: 'ControlTransport reducer batcher' },
      },
    ],
    [
      'tool_finished',
      {
        toolCallId: 'tool-rag-1',
        toolId: 'ime_knowledge',
        operation: 'search',
        summary: '找到 8 条实现证据',
        args: { query: 'ControlTransport reducer batcher' },
        resultCount: 8,
        sources: ['迁移计划', 'Agent reducer', 'Transport policy'],
      },
    ],
    [
      'tool_finished',
      {
        toolCallId: 'tool-memory-1',
        toolId: 'ime_memory',
        operation: 'read',
        summary: '已读取输入法工具书',
        args: { bookId: 'book:topic:input-method' },
        result: {
          book: {
            title: '输入法与 Agent 上下文',
            summary: '记录输入缓冲、闪电联想和长期记忆整理之间的边界。',
            tags: ['输入法', '上下文', '记忆质量'],
            memories: [
              { type: 'principle', text: '单个词和未封口碎片不得进入长期 Agent 上下文。' },
              { type: 'decision', text: '闪电联想可以读取当前连续输入缓冲，但不直接持久化。' },
              { type: 'fact', text: '回车封口，同一应用内的输入按编辑事件重建，Backspace 会修正缓冲。' },
            ],
          },
        },
      },
    ],
    [
      'tool_finished',
      {
        toolCallId: 'subagent-1',
        toolId: 'subagent',
        operation: 'review',
        summary: '2 个子 Agent 完成并行核对',
        completed: 2,
        artifacts: 3,
      },
    ],
    [
      'approval_required',
      {
        approvalId: 'approval-1',
        summary: '等待确认应用词表草案',
        action: 'apply_lexicon_draft',
        risk: 'write',
        payloadSha256: 'preview-payload-sha256',
      },
    ],
    [
      'approval_resolved',
      {
        approvalId: 'approval-1',
        summary: '词表草案已批准',
        state: 'approved',
        receiptId: 'receipt-preview-1',
      },
    ],
    ['turn_completed', { summary: '本轮完成' }],
  ];
  return entries.map(([eventType, payload], index) => ({
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `${sessionId}:event-${index + 13}`,
    sessionId,
    turnId,
    sequence: index + 13,
    createdAtMs: previewNow - 175_000 + index * 2_000,
    payload,
    resumeToken: `${sessionId}:${index + 13}`,
    streamKind: 'agent',
    eventType,
  }));
}

function message(
  sessionId: string,
  turnId: string,
  id: string,
  role: 'user' | 'assistant',
  blocks: ReturnType<typeof block>[],
  createdAtMs: number,
) {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: `${sessionId}:${id}`,
    sessionId,
    turnId,
    role,
    status: 'completed',
    blocks,
    attachments: [],
    citations: [],
    createdAtMs,
    completedAtMs: createdAtMs + 8_000,
  };
}

function block(id: string, type: string, data: Record<string, unknown>) {
  return {
    id,
    type,
    status: 'completed',
    presentationKind: type === 'text' ? 'markdown' : type,
    data,
  };
}
