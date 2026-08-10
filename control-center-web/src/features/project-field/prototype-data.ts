import { reconstructedPersonalAgentProject } from './reconstructed-personal-agent-project';

export type ProjectRoomPhase =
  | 'foreground'
  | 'running'
  | 'attention'
  | 'waiting'
  | 'settled'
  | 'planned';

export type ProjectRoomAreaState = 'settled' | 'active' | 'attention' | 'planned';

export type ProjectRoomArea = {
  title: string;
  note: string;
  state: ProjectRoomAreaState;
};

export type ProjectWayfinderStageId =
  | 'alignment-and-decision'
  | 'implementation-planning'
  | 'implementation-execution'
  | 'quality-gate'
  | 'independent-review';

export type ProjectWayfinderStage = {
  id: ProjectWayfinderStageId;
  title: string;
};

export type ProjectWayfinderDocumentRole =
  | 'map'
  | 'initial-vision'
  | 'destination'
  | 'room';

export type ProjectWayfinderDocument = {
  role: ProjectWayfinderDocumentRole;
  ref: string;
  title: string;
  sha256: string;
  sourceRefs: readonly string[];
  roomId?: string;
};

export type ProjectWayfinderRoom = {
  roomId: string;
  title: string;
  requirement: string;
  problem: string;
  decisions: readonly string[];
  acceptanceObservations: readonly string[];
  currentStage: ProjectWayfinderStageId;
  deliveryState: 'accepted' | 'active' | 'queued';
  emergedAt: string;
  epochId: string;
  topologyRole: 'room' | 'release-lane';
  progress: {
    basis: 'acceptance-evidence';
    completed: number;
    total: number;
    items: readonly {
      label: string;
      state: 'verified' | 'pending';
      sourceRefs: readonly string[];
    }[];
  };
  currentDelivery: string;
  nextMove: string;
  documentRef: string;
  detailDocumentRefs: readonly string[];
  sourceRefs: readonly string[];
};

export type ProjectWayfinderRelation = {
  from: '@origin' | string;
  to: string;
  kind: 'refines' | 'led-to' | 'requires';
  label: string;
  sourceRefs: readonly string[];
};

export type ProjectWayfinderProjection = {
  schemaVersion: 'personal-agent.project-wayfinder.v2';
  projectId: string;
  currentRoomId: string;
  initialVision: {
    title: string;
    statement: string;
    observableAnchors: readonly string[];
    documentRef: string;
    sourceRefs: readonly string[];
  };
  destination: {
    title: string;
    statement: string;
    state: 'unreached';
    acceptanceObservations: readonly string[];
    documentRef: string;
    sourceRefs: readonly string[];
  };
  deliveryEngine: {
    stages: readonly ProjectWayfinderStage[];
    innerMethod: {
      id: 'test-driven-implementation';
      parentStage: 'implementation-execution';
      title: '测试驱动实现';
    };
  };
  evolution: {
    direction: 'left-to-right';
    epochs: readonly {
      id: string;
      range: string;
      label: string;
      summary: string;
    }[];
    releaseLane: {
      roomId: string;
      checkpoints: readonly {
        observedAt: string;
        label: string;
        sourceRefs: readonly string[];
      }[];
    };
  };
  rooms: readonly ProjectWayfinderRoom[];
  relations: readonly ProjectWayfinderRelation[];
  documents: readonly ProjectWayfinderDocument[];
  sourceRefs: readonly string[];
};

export type ProjectRoomSourceKind = 'project-document' | 'agent-session' | 'git-commit';

export type ProjectRoomSourceRole = 'intent' | 'decision' | 'acceptance';

export type ProjectRoomSource = {
  id: string;
  kind: ProjectRoomSourceKind;
  role: ProjectRoomSourceRole;
  label: string;
  detail: string;
  ref: string;
  observedAt: string;
  provider?: 'codex' | 'claude-code' | 'pi' | 'omp';
  authority: 'primary' | 'corroborating';
};

export type ProjectReconstruction = {
  label: string;
  sourceWindow: string;
  snapshotRef: string;
  method: string;
  sourceCounts: {
    projectDocuments: number;
    agentSessions: number;
    gitCommits: number;
  };
  projection?: {
    state: 'verified-local-evidence';
    schemaVersion: string;
    generatedAt: string;
    gitHead: string;
    sourceWorktreeDirtyAtCuration: boolean;
  };
};

export type ProjectRoom = {
  id: string;
  title: string;
  goal: string;
  phase: ProjectRoomPhase;
  phaseLabel: string;
  x: number;
  y: number;
  shape: 1 | 2 | 3 | 4;
  recentResult: string;
  unresolved: string;
  nextStep: string;
  areas: readonly ProjectRoomArea[];
  workflow: readonly string[];
  keywords: readonly string[];
  sources?: readonly ProjectRoomSource[];
  retrospective?: boolean;
};

export type ProjectFieldEdge = {
  from: string;
  to: string;
  kind: 'course' | 'dependency';
};

export type ProjectFieldProject = {
  id: string;
  name: string;
  compactTitle: string;
  shortName: string;
  subtitle: string;
  destination: string;
  heading: string;
  origin: string;
  rooms: readonly ProjectRoom[];
  edges: readonly ProjectFieldEdge[];
  fog?: readonly string[];
  frontier?: string;
  defaultRoomId: string;
  routeCamera: { x: number; y: number; scale: number };
  reconstruction?: ProjectReconstruction;
  wayfinder?: ProjectWayfinderProjection;
};

export const projectFieldProjects: readonly ProjectFieldProject[] = [
  reconstructedPersonalAgentProject,
  {
    id: 'wisdom-weasel',
    name: 'Wisdom Weasel',
    compactTitle: '记忆检索',
    shortName: 'WW',
    subtitle: '记忆证据与检索',
    destination: '让长期记忆保持可验证、可恢复、不过时',
    heading: '从证据到账本，再到受控检索与回滚',
    origin: '从本机检索实验开始',
    rooms: [
      {
        id: 'evidence-ledger', title: '证据账本', goal: '保留事实来源而不把模型输出当事实。', phase: 'settled', phaseLabel: '稳定', x: 280, y: 590, shape: 1,
        recentResult: '来源与晋升状态可以独立追溯。', unresolved: '跨产品导入仍需显式边界。', nextStep: '保持只读适配器。', workflow: ['收集', '去噪', '追溯'], keywords: ['证据', '账本'],
        areas: [
          { title: '来源记录', note: '保留事实出处。', state: 'settled' },
          { title: '晋升记录', note: '区分候选与正式知识。', state: 'settled' },
          { title: '只读导入', note: '跨产品写回需要授权。', state: 'planned' },
        ],
      },
      {
        id: 'stale-results', title: '陈旧结果防线', goal: '任何版本漂移都让检索结果失败关闭。', phase: 'attention', phaseLabel: '需要验证', x: 590, y: 362, shape: 2,
        recentResult: 'revision 与 fingerprint 已进入读路径。', unresolved: '长时运行仍需回放。', nextStep: '验证真实恢复场景。', workflow: ['版本围栏', '失败关闭', '回放'], keywords: ['陈旧', 'revision'],
        areas: [
          { title: '版本围栏', note: '任何漂移都失败关闭。', state: 'settled' },
          { title: '缓存失效', note: '旧投影不能继续服务。', state: 'active' },
          { title: '恢复回放', note: '长时运行仍待验证。', state: 'attention' },
        ],
      },
      {
        id: 'memory-review', title: '记忆审阅', goal: '让模型整理成为可编辑草稿。', phase: 'foreground', phaseLabel: '当前 Room', x: 890, y: 430, shape: 3,
        recentResult: '草稿、应用和回滚边界已清楚。', unresolved: '批量审阅仍显机械。', nextStep: '优化低风险确认体验。', workflow: ['整理', '审阅', '应用'], keywords: ['记忆', '审阅'],
        areas: [
          { title: '候选整理', note: '模型先生成草稿。', state: 'active' },
          { title: '人工审阅', note: '高影响内容由用户确认。', state: 'active' },
          { title: '应用回滚', note: '正式变更保持可撤销。', state: 'settled' },
        ],
      },
      {
        id: 'portable-context', title: '可移植上下文', goal: '用有界投影服务不同 Agent runtime。', phase: 'planned', phaseLabel: '前沿', x: 1180, y: 242, shape: 4,
        recentResult: 'Context Provider 边界已形成。', unresolved: '写回仍需用户授权。', nextStep: '完成只读集成验证。', workflow: ['投影', '检索', '授权'], keywords: ['context', 'provider'],
        areas: [
          { title: '有界投影', note: '只发送需要的上下文。', state: 'active' },
          { title: '跨 Runtime 读取', note: '保持来源信息。', state: 'planned' },
          { title: '受控写回', note: '写入需要用户授权。', state: 'planned' },
        ],
      },
    ],
    edges: [
      { from: 'evidence-ledger', to: 'stale-results', kind: 'course' },
      { from: 'stale-results', to: 'memory-review', kind: 'course' },
      { from: 'memory-review', to: 'portable-context', kind: 'course' },
    ],
    fog: ['哪些低风险知识可以免打扰晋升？'],
    frontier: '验证跨 Runtime 读取不改变原始证据',
    defaultRoomId: 'memory-review',
    routeCamera: { x: -70, y: 26, scale: 0.88 },
  },
  {
    id: 'agent-engineering',
    name: 'Agent Engineering Lab',
    compactTitle: 'Agent 工程实验室',
    shortName: 'AE',
    subtitle: '源码学习与面试',
    destination: '把真实 Agent 工程经验变成可解释、可复现的能力',
    heading: '从真实调用链出发，不背脱离代码的结论',
    origin: '从 Pi 工具循环开始',
    rooms: [
      {
        id: 'provider-loop', title: 'Provider 与工具循环', goal: '追清请求、工具结果和下一轮模型调用。', phase: 'settled', phaseLabel: '已掌握', x: 280, y: 530, shape: 2,
        recentResult: '调用链已经能从命令追到执行点。', unresolved: '不同 Provider 的兼容边界仍需补例。', nextStep: '补充失败回放。', workflow: ['源码追踪', '数据样例', '失败分析'], keywords: ['provider', 'tool loop'],
        areas: [
          { title: '请求构造', note: '追到 Provider 边界。', state: 'settled' },
          { title: '工具回写', note: '解释结果如何进入下一轮。', state: 'settled' },
          { title: '失败回放', note: '补充兼容性样例。', state: 'attention' },
        ],
      },
      {
        id: 'context-compaction', title: '上下文与压缩', goal: '解释上下文预算、恢复与缓存的真实权衡。', phase: 'foreground', phaseLabel: '当前 Room', x: 660, y: 330, shape: 1,
        recentResult: 'Session、压缩与恢复边界已串联。', unresolved: '还需要更短的面试表达。', nextStep: '用项目故障案例收束。', workflow: ['机制', '代码链', '面试表达'], keywords: ['压缩', '上下文'],
        areas: [
          { title: '上下文预算', note: '解释内容取舍。', state: 'settled' },
          { title: '压缩恢复', note: '连接 Session 连续性。', state: 'active' },
          { title: '面试表达', note: '用故障案例收束。', state: 'attention' },
        ],
      },
      {
        id: 'permission-cancel', title: '权限与取消', goal: '把自治执行放在可停止、可审计的边界内。', phase: 'running', phaseLabel: '整理中', x: 960, y: 548, shape: 4,
        recentResult: '批准、取消与终态责任已分离。', unresolved: '跨进程取消仍需更多证据。', nextStep: '完成边界表。', workflow: ['权限', '执行', '终态'], keywords: ['权限', '取消'],
        areas: [
          { title: '操作批准', note: '高风险执行需要授权。', state: 'settled' },
          { title: '运行取消', note: '进程树必须可停止。', state: 'active' },
          { title: '终态责任', note: '结束状态只有一个 owner。', state: 'active' },
        ],
      },
      {
        id: 'interview-map', title: '项目面试地图', goal: '把高价值问题连接到真实实现与证据。', phase: 'planned', phaseLabel: '下一站', x: 1190, y: 250, shape: 3,
        recentResult: '单一问题索引已经建立。', unresolved: '项目故事仍需按能力聚类。', nextStep: '形成系统复习路线。', workflow: ['问题筛选', '证据链接', '复习'], keywords: ['面试', '问题'],
        areas: [
          { title: '问题索引', note: '保持单一入口。', state: 'settled' },
          { title: '项目故事', note: '按能力而非文件归类。', state: 'planned' },
          { title: '复习路线', note: '从机制走到证据。', state: 'planned' },
        ],
      },
    ],
    edges: [
      { from: 'provider-loop', to: 'context-compaction', kind: 'course' },
      { from: 'context-compaction', to: 'permission-cancel', kind: 'dependency' },
      { from: 'context-compaction', to: 'interview-map', kind: 'course' },
    ],
    fog: ['哪些案例最能证明工程判断？'],
    frontier: '把一条真实故障链讲到验证边界',
    defaultRoomId: 'context-compaction',
    routeCamera: { x: -68, y: 20, scale: 0.88 },
  },
] as const;

export function roomPhaseOrder(phase: ProjectRoomPhase): number {
  return { attention: 0, foreground: 1, running: 2, waiting: 3, planned: 4, settled: 5 }[phase];
}
