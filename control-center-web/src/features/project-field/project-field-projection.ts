import type {
  ProjectFieldProject,
  ProjectRoomArea,
  ProjectRoomSource,
  ProjectWayfinderProjection,
  ProjectWayfinderStageId,
} from './prototype-data';

export const PROJECT_FIELD_PROJECTION_SCHEMA = 'personal-agent.project-field-projection.v1' as const;
export const WAYFINDER_PROJECTION_SCHEMA = 'personal-agent.project-wayfinder.v2' as const;

export type ProjectFieldProjectionSourceReceipt = {
  id: string;
  kind: ProjectRoomSource['kind'];
  observedAt: string;
  ref?: string;
  provider?: ProjectRoomSource['provider'];
  sessionId?: string;
  userMessageCount?: number;
  userMessagesSha256?: string;
  root?: 'main-release' | 'prototype-contract';
  snapshotMode?: 'git-head' | 'exact-working-file' | 'exact-prototype-file';
  sha256?: string;
  byteCount?: number;
  commit?: string;
  committedAt?: string;
  subject?: string;
};

export type ProjectFieldProjectionEnvelope = {
  schemaVersion: typeof PROJECT_FIELD_PROJECTION_SCHEMA;
  generatedAt: string;
  sourceRevision: {
    gitHead: string;
    sourceWorktreeDirtyAtCuration: boolean;
    manifestSha256: string;
    documentsSha256: string;
    sessionsSha256: string;
    commitsSha256: string;
  };
  sourceCounts: {
    projectDocuments: number;
    agentSessions: number;
    gitCommits: number;
  };
  privacy: {
    rawChatIncluded: false;
    toolResultsIncluded: false;
    assistantReasoningIncluded: false;
    absolutePathsIncluded: false;
  };
  sourceReceipts: readonly ProjectFieldProjectionSourceReceipt[];
  project: ProjectFieldProject;
};

export class ProjectFieldProjectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProjectFieldProjectionError';
  }
}

const PHASES = new Set(['foreground', 'running', 'attention', 'waiting', 'settled', 'planned']);
const AREA_STATES = new Set<ProjectRoomArea['state']>(['settled', 'active', 'attention', 'planned']);
const SOURCE_KINDS = new Set<ProjectRoomSource['kind']>(['project-document', 'agent-session', 'git-commit']);
const SOURCE_ROLES = new Set<ProjectRoomSource['role']>(['intent', 'decision', 'acceptance']);
const SOURCE_AUTHORITIES = new Set<ProjectRoomSource['authority']>(['primary', 'corroborating']);
const EDGE_KINDS = new Set(['course', 'dependency']);
const PROVIDERS = new Set(['codex', 'claude-code', 'pi', 'omp']);
const WAYFINDER_RELATION_KINDS = new Set(['refines', 'led-to', 'requires']);
const WAYFINDER_TOPOLOGY_ROLES = new Set(['room', 'release-lane']);
const WAYFINDER_PROGRESS_STATES = new Set(['verified', 'pending']);
const WAYFINDER_DELIVERY_STATES = new Set(['accepted', 'active', 'queued']);
const WAYFINDER_DOCUMENT_ROLES = new Set(['map', 'initial-vision', 'destination', 'room']);
const WAYFINDER_STAGES: readonly { id: ProjectWayfinderStageId; title: string }[] = [
  { id: 'alignment-and-decision', title: '需求对齐' },
  { id: 'implementation-planning', title: '实现规划' },
  { id: 'implementation-execution', title: '实现执行' },
  { id: 'quality-gate', title: '质量门' },
  { id: 'independent-review', title: '独立复核' },
];
const WAYFINDER_STAGE_IDS = new Set(WAYFINDER_STAGES.map(({ id }) => id));
const SHA256 = /^[a-f0-9]{64}$/;
const GIT_HEAD = /^[a-f0-9]{40}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const MARKDOWN_REF = /^(?!\/)(?!.*(?:^|\/)\.\.(?:\/|$))[A-Za-z0-9._/-]+\.md$/;
const ABSOLUTE_MACHINE_PATH = /(?:^|[\s'"])(?:\/Users\/|\/Volumes\/|[A-Za-z]:\\)/;
const FORBIDDEN_PROJECT_COPY = ['仍在迷雾中', 'assistant reasoning', 'chain of thought', '思考过程'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) throw new ProjectFieldProjectionError(`${path} 必须是对象`);
  return value;
}

function array(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new ProjectFieldProjectionError(`${path} 必须是数组`);
  return value;
}

function string(value: unknown, path: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new ProjectFieldProjectionError(`${path} 必须是非空字符串`);
  }
  if (ABSOLUTE_MACHINE_PATH.test(value)) {
    throw new ProjectFieldProjectionError(`${path} 不能包含机器绝对路径`);
  }
  return value;
}

function finiteNumber(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new ProjectFieldProjectionError(`${path} 必须是有限数字`);
  }
  return value;
}

function positiveInteger(value: unknown, path: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new ProjectFieldProjectionError(`${path} 必须是非负整数`);
  }
  return value as number;
}

function exactFalse(value: unknown, path: string): asserts value is false {
  if (value !== false) throw new ProjectFieldProjectionError(`${path} 必须明确为 false`);
}

function sha256(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (!SHA256.test(parsed)) throw new ProjectFieldProjectionError(`${path} 不是 SHA-256`);
  return parsed;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[], path: string): void {
  const actual = Object.keys(value).sort();
  const normalizedExpected = [...expected].sort();
  if (actual.length !== normalizedExpected.length || actual.some((key, index) => key !== normalizedExpected[index])) {
    throw new ProjectFieldProjectionError(`${path} 字段集合不符合 schema`);
  }
}

function uniqueStrings(value: unknown, path: string, minimum = 0): string[] {
  const parsed = array(value, path).map((item, index) => string(item, `${path}[${index}]`));
  if (parsed.length < minimum) throw new ProjectFieldProjectionError(`${path} 至少需要 ${minimum} 项`);
  if (new Set(parsed).size !== parsed.length) throw new ProjectFieldProjectionError(`${path} 不得重复`);
  return parsed;
}

function documentRef(value: unknown, path: string): string {
  const parsed = string(value, path);
  if (!MARKDOWN_REF.test(parsed)) {
    throw new ProjectFieldProjectionError(`${path} 不是安全的 Markdown 相对引用`);
  }
  return parsed;
}

function sameSet(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  return left.size === right.size && [...left].every((item) => right.has(item));
}

function validateSource(value: unknown, path: string): ProjectRoomSource {
  const source = record(value, path);
  const kind = string(source.kind, `${path}.kind`);
  const role = string(source.role, `${path}.role`);
  const authority = string(source.authority, `${path}.authority`);
  if (!SOURCE_KINDS.has(kind as ProjectRoomSource['kind'])) {
    throw new ProjectFieldProjectionError(`${path}.kind 不受支持`);
  }
  if (!SOURCE_ROLES.has(role as ProjectRoomSource['role'])) {
    throw new ProjectFieldProjectionError(`${path}.role 不受支持`);
  }
  if (!SOURCE_AUTHORITIES.has(authority as ProjectRoomSource['authority'])) {
    throw new ProjectFieldProjectionError(`${path}.authority 不受支持`);
  }
  if (source.provider !== undefined && !PROVIDERS.has(string(source.provider, `${path}.provider`))) {
    throw new ProjectFieldProjectionError(`${path}.provider 不受支持`);
  }
  string(source.id, `${path}.id`);
  string(source.label, `${path}.label`);
  string(source.detail, `${path}.detail`);
  string(source.ref, `${path}.ref`);
  string(source.observedAt, `${path}.observedAt`);
  return source as ProjectRoomSource;
}

function validateWayfinder(
  value: unknown,
  projectId: string,
  defaultRoomId: string,
  roomTitles: ReadonlyMap<string, string>,
  roomSourceIds: ReadonlyMap<string, ReadonlySet<string>>,
): ProjectWayfinderProjection {
  const path = 'project.wayfinder';
  const wayfinder = record(value, path);
  exactKeys(wayfinder, [
    'schemaVersion',
    'projectId',
    'currentRoomId',
    'initialVision',
    'destination',
    'deliveryEngine',
    'evolution',
    'rooms',
    'relations',
    'documents',
    'sourceRefs',
  ], path);
  if (wayfinder.schemaVersion !== WAYFINDER_PROJECTION_SCHEMA) {
    throw new ProjectFieldProjectionError(`${path}.schemaVersion 不受支持`);
  }
  if (wayfinder.projectId !== projectId || wayfinder.currentRoomId !== defaultRoomId) {
    throw new ProjectFieldProjectionError(`${path} 与所属 Project 不一致`);
  }

  const allSourceIds = new Set([...roomSourceIds.values()].flatMap((ids) => [...ids]));
  const sourceRefs = uniqueStrings(wayfinder.sourceRefs, `${path}.sourceRefs`, 1);
  if (!sameSet(new Set(sourceRefs), allSourceIds)) {
    throw new ProjectFieldProjectionError(`${path}.sourceRefs 必须完整覆盖 Project 来源`);
  }

  const initialVision = record(wayfinder.initialVision, `${path}.initialVision`);
  exactKeys(initialVision, ['title', 'statement', 'observableAnchors', 'documentRef', 'sourceRefs'], `${path}.initialVision`);
  string(initialVision.title, `${path}.initialVision.title`);
  string(initialVision.statement, `${path}.initialVision.statement`);
  uniqueStrings(initialVision.observableAnchors, `${path}.initialVision.observableAnchors`, 1);
  documentRef(initialVision.documentRef, `${path}.initialVision.documentRef`);
  const initialRefs = uniqueStrings(initialVision.sourceRefs, `${path}.initialVision.sourceRefs`, 1);
  if (initialRefs.some((sourceRef) => !allSourceIds.has(sourceRef))) {
    throw new ProjectFieldProjectionError(`${path}.initialVision 引用了未知来源`);
  }

  const destination = record(wayfinder.destination, `${path}.destination`);
  exactKeys(destination, ['title', 'statement', 'state', 'acceptanceObservations', 'documentRef', 'sourceRefs'], `${path}.destination`);
  string(destination.title, `${path}.destination.title`);
  string(destination.statement, `${path}.destination.statement`);
  if (destination.state !== 'unreached') {
    throw new ProjectFieldProjectionError('Destination 在所有 Room 验收前必须保持 unreached');
  }
  uniqueStrings(destination.acceptanceObservations, `${path}.destination.acceptanceObservations`, 1);
  documentRef(destination.documentRef, `${path}.destination.documentRef`);
  const destinationRefs = uniqueStrings(destination.sourceRefs, `${path}.destination.sourceRefs`, 1);
  if (destinationRefs.some((sourceRef) => !allSourceIds.has(sourceRef))) {
    throw new ProjectFieldProjectionError(`${path}.destination 引用了未知来源`);
  }

  const deliveryEngine = record(wayfinder.deliveryEngine, `${path}.deliveryEngine`);
  exactKeys(deliveryEngine, ['stages', 'innerMethod'], `${path}.deliveryEngine`);
  const stages = array(deliveryEngine.stages, `${path}.deliveryEngine.stages`);
  if (stages.length !== WAYFINDER_STAGES.length) {
    throw new ProjectFieldProjectionError(`${path}.deliveryEngine.stages 不完整`);
  }
  stages.forEach((stageValue, index) => {
    const stage = record(stageValue, `${path}.deliveryEngine.stages[${index}]`);
    exactKeys(stage, ['id', 'title'], `${path}.deliveryEngine.stages[${index}]`);
    const expected = WAYFINDER_STAGES[index];
    if (stage.id !== expected.id || stage.title !== expected.title) {
      throw new ProjectFieldProjectionError(`${path}.deliveryEngine 外层技能流漂移`);
    }
  });
  const innerMethod = record(deliveryEngine.innerMethod, `${path}.deliveryEngine.innerMethod`);
  exactKeys(innerMethod, ['id', 'parentStage', 'title'], `${path}.deliveryEngine.innerMethod`);
  if (
    innerMethod.id !== 'test-driven-implementation'
    || innerMethod.parentStage !== 'implementation-execution'
    || innerMethod.title !== '测试驱动实现'
  ) {
    throw new ProjectFieldProjectionError('测试驱动实现必须保留在 implementation-execution 内层');
  }

  const evolution = record(wayfinder.evolution, `${path}.evolution`);
  exactKeys(evolution, ['direction', 'epochs', 'releaseLane'], `${path}.evolution`);
  if (evolution.direction !== 'left-to-right') {
    throw new ProjectFieldProjectionError(`${path}.evolution 必须从左到右展开`);
  }
  const epochIds = new Set<string>();
  array(evolution.epochs, `${path}.evolution.epochs`).forEach((epochValue, epochIndex) => {
    const epochPath = `${path}.evolution.epochs[${epochIndex}]`;
    const epoch = record(epochValue, epochPath);
    exactKeys(epoch, ['id', 'range', 'label', 'summary'], epochPath);
    const epochId = string(epoch.id, `${epochPath}.id`);
    if (epochIds.has(epochId)) throw new ProjectFieldProjectionError(`${epochPath}.id 重复`);
    epochIds.add(epochId);
    string(epoch.range, `${epochPath}.range`);
    string(epoch.label, `${epochPath}.label`);
    string(epoch.summary, `${epochPath}.summary`);
  });
  if (!epochIds.size) throw new ProjectFieldProjectionError(`${path}.evolution.epochs 不能为空`);
  const releaseLane = record(evolution.releaseLane, `${path}.evolution.releaseLane`);
  exactKeys(releaseLane, ['roomId', 'checkpoints'], `${path}.evolution.releaseLane`);
  const releaseLaneRoomId = string(releaseLane.roomId, `${path}.evolution.releaseLane.roomId`);
  let previousCheckpointDate = '';
  const checkpoints = array(releaseLane.checkpoints, `${path}.evolution.releaseLane.checkpoints`);
  if (!checkpoints.length) throw new ProjectFieldProjectionError(`${path}.evolution.releaseLane.checkpoints 不能为空`);
  checkpoints.forEach((checkpointValue, checkpointIndex) => {
    const checkpointPath = `${path}.evolution.releaseLane.checkpoints[${checkpointIndex}]`;
    const checkpoint = record(checkpointValue, checkpointPath);
    exactKeys(checkpoint, ['observedAt', 'label', 'sourceRefs'], checkpointPath);
    const observedAt = string(checkpoint.observedAt, `${checkpointPath}.observedAt`);
    if (!ISO_DATE.test(observedAt) || observedAt < previousCheckpointDate) {
      throw new ProjectFieldProjectionError(`${checkpointPath}.observedAt 必须按时间排序`);
    }
    previousCheckpointDate = observedAt;
    string(checkpoint.label, `${checkpointPath}.label`);
    uniqueStrings(checkpoint.sourceRefs, `${checkpointPath}.sourceRefs`, 1).forEach((sourceRef) => {
      if (!allSourceIds.has(sourceRef)) {
        throw new ProjectFieldProjectionError(`${checkpointPath}.sourceRefs 引用了未知来源`);
      }
    });
  });

  const projectedRooms = array(wayfinder.rooms, `${path}.rooms`);
  if (projectedRooms.length !== roomTitles.size) {
    throw new ProjectFieldProjectionError(`${path}.rooms 必须覆盖全部 Room`);
  }
  const projectedRoomIds: string[] = [];
  let acceptedCount = 0;
  projectedRooms.forEach((roomValue, roomIndex) => {
    const roomPath = `${path}.rooms[${roomIndex}]`;
    const room = record(roomValue, roomPath);
    exactKeys(room, [
      'roomId',
      'title',
      'requirement',
      'problem',
      'decisions',
      'acceptanceObservations',
      'currentStage',
      'deliveryState',
      'emergedAt',
      'epochId',
      'topologyRole',
      'progress',
      'currentDelivery',
      'nextMove',
      'documentRef',
      'detailDocumentRefs',
      'sourceRefs',
    ], roomPath);
    const roomId = string(room.roomId, `${roomPath}.roomId`);
    if (!roomTitles.has(roomId) || projectedRoomIds.includes(roomId)) {
      throw new ProjectFieldProjectionError(`${roomPath}.roomId 重复或未知`);
    }
    projectedRoomIds.push(roomId);
    if (room.title !== roomTitles.get(roomId)) {
      throw new ProjectFieldProjectionError(`${roomPath}.title 与 Room 边界不一致`);
    }
    string(room.requirement, `${roomPath}.requirement`);
    string(room.problem, `${roomPath}.problem`);
    uniqueStrings(room.decisions, `${roomPath}.decisions`, 1);
    const acceptanceObservations = uniqueStrings(room.acceptanceObservations, `${roomPath}.acceptanceObservations`, 1);
    const emergedAt = string(room.emergedAt, `${roomPath}.emergedAt`);
    if (!ISO_DATE.test(emergedAt)) throw new ProjectFieldProjectionError(`${roomPath}.emergedAt 无效`);
    if (!epochIds.has(string(room.epochId, `${roomPath}.epochId`))) {
      throw new ProjectFieldProjectionError(`${roomPath}.epochId 未在时间层中定义`);
    }
    if (!WAYFINDER_TOPOLOGY_ROLES.has(string(room.topologyRole, `${roomPath}.topologyRole`))) {
      throw new ProjectFieldProjectionError(`${roomPath}.topologyRole 不受支持`);
    }
    if (!WAYFINDER_STAGE_IDS.has(room.currentStage as ProjectWayfinderStageId)) {
      throw new ProjectFieldProjectionError(`${roomPath}.currentStage 不受支持`);
    }
    if (!WAYFINDER_DELIVERY_STATES.has(room.deliveryState as string)) {
      throw new ProjectFieldProjectionError(`${roomPath}.deliveryState 不受支持`);
    }
    acceptedCount += Number(room.deliveryState === 'accepted');
    if (room.deliveryState === 'accepted' && room.currentStage !== 'independent-review') {
      throw new ProjectFieldProjectionError(`${roomPath} 已验收但未完成独立复核`);
    }
    string(room.currentDelivery, `${roomPath}.currentDelivery`);
    string(room.nextMove, `${roomPath}.nextMove`);
    documentRef(room.documentRef, `${roomPath}.documentRef`);
    uniqueStrings(room.detailDocumentRefs, `${roomPath}.detailDocumentRefs`)
      .forEach((ref, index) => documentRef(ref, `${roomPath}.detailDocumentRefs[${index}]`));
    const refs = uniqueStrings(room.sourceRefs, `${roomPath}.sourceRefs`, 1);
    if (!sameSet(new Set(refs), roomSourceIds.get(roomId) ?? new Set())) {
      throw new ProjectFieldProjectionError(`${roomPath}.sourceRefs 与 Room 来源不一致`);
    }
    const progress = record(room.progress, `${roomPath}.progress`);
    exactKeys(progress, ['basis', 'completed', 'total', 'items'], `${roomPath}.progress`);
    if (progress.basis !== 'acceptance-evidence') {
      throw new ProjectFieldProjectionError(`${roomPath}.progress 必须以验收证据为基准`);
    }
    const completed = positiveInteger(progress.completed, `${roomPath}.progress.completed`);
    const total = positiveInteger(progress.total, `${roomPath}.progress.total`);
    const progressLabels: string[] = [];
    let verified = 0;
    const progressItems = array(progress.items, `${roomPath}.progress.items`);
    progressItems.forEach((itemValue, itemIndex) => {
      const itemPath = `${roomPath}.progress.items[${itemIndex}]`;
      const item = record(itemValue, itemPath);
      exactKeys(item, ['label', 'state', 'sourceRefs'], itemPath);
      const label = string(item.label, `${itemPath}.label`);
      if (progressLabels.includes(label)) throw new ProjectFieldProjectionError(`${itemPath}.label 重复`);
      progressLabels.push(label);
      const state = string(item.state, `${itemPath}.state`);
      if (!WAYFINDER_PROGRESS_STATES.has(state)) throw new ProjectFieldProjectionError(`${itemPath}.state 不受支持`);
      verified += Number(state === 'verified');
      uniqueStrings(item.sourceRefs, `${itemPath}.sourceRefs`, 1).forEach((sourceRef) => {
        if (!refs.includes(sourceRef)) throw new ProjectFieldProjectionError(`${itemPath}.sourceRefs 越过 Room 边界`);
      });
    });
    if (
      total < 1
      || total !== progressItems.length
      || completed !== verified
      || progressLabels.some((label, index) => label !== acceptanceObservations[index])
    ) {
      throw new ProjectFieldProjectionError(`${roomPath}.progress 与可观察验收不一致`);
    }
  });
  if (!sameSet(new Set(projectedRoomIds), new Set(roomTitles.keys()))) {
    throw new ProjectFieldProjectionError(`${path}.rooms 未完整覆盖 Room 边界`);
  }
  if (acceptedCount === projectedRooms.length) {
    throw new ProjectFieldProjectionError('所有 Room 已验收时 Destination 不应仍为 unreached');
  }
  const currentRoom = projectedRooms.find((room) => record(room, 'current room').roomId === defaultRoomId);
  if (!currentRoom || record(currentRoom, 'current room').deliveryState !== 'active') {
    throw new ProjectFieldProjectionError('当前 Room 必须处于 active 交付状态');
  }
  const releaseRooms = projectedRooms.filter(
    (room) => record(room, 'release room').topologyRole === 'release-lane',
  );
  if (releaseRooms.length !== 1 || record(releaseRooms[0], 'release room').roomId !== releaseLaneRoomId) {
    throw new ProjectFieldProjectionError('Project 必须有且只有一个匹配的真实验收轨道');
  }

  const relations = array(wayfinder.relations, `${path}.relations`);
  if (!relations.length) throw new ProjectFieldProjectionError(`${path}.relations 不能为空`);
  const relationKeys = new Set<string>();
  const adjacency = new Map<string, Set<string>>([['@origin', new Set()]]);
  roomTitles.forEach((_title, roomId) => adjacency.set(roomId, new Set()));
  const originTargets = new Set<string>();
  relations.forEach((relationValue, relationIndex) => {
    const relationPath = `${path}.relations[${relationIndex}]`;
    const relation = record(relationValue, relationPath);
    exactKeys(relation, ['from', 'to', 'kind', 'label', 'sourceRefs'], relationPath);
    const from = string(relation.from, `${relationPath}.from`);
    const to = string(relation.to, `${relationPath}.to`);
    const kind = string(relation.kind, `${relationPath}.kind`);
    string(relation.label, `${relationPath}.label`);
    if ((from !== '@origin' && !roomTitles.has(from)) || !roomTitles.has(to) || from === to) {
      throw new ProjectFieldProjectionError(`${relationPath} 端点无效`);
    }
    if (!WAYFINDER_RELATION_KINDS.has(kind)) {
      throw new ProjectFieldProjectionError(`${relationPath}.kind 不受支持`);
    }
    uniqueStrings(relation.sourceRefs, `${relationPath}.sourceRefs`, 1).forEach((sourceRef) => {
      if (!allSourceIds.has(sourceRef)) throw new ProjectFieldProjectionError(`${relationPath}.sourceRefs 引用了未知来源`);
    });
    const key = `${from}:${to}:${kind}`;
    if (relationKeys.has(key)) throw new ProjectFieldProjectionError(`${relationPath} 重复`);
    relationKeys.add(key);
    adjacency.get(from)?.add(to);
    if (from === '@origin') originTargets.add(to);
  });
  if (originTargets.size !== 1) {
    throw new ProjectFieldProjectionError('初始愿景必须只通过第一个真实 Room 进入历史图');
  }
  const reachable = new Set(['@origin']);
  const queue = ['@origin'];
  while (queue.length) {
    const from = queue.shift();
    if (!from) break;
    adjacency.get(from)?.forEach((to) => {
      if (!reachable.has(to)) {
        reachable.add(to);
        queue.push(to);
      }
    });
  }
  if ([...roomTitles.keys()].some((roomId) => !reachable.has(roomId))) {
    throw new ProjectFieldProjectionError('每个 Room 都必须能从初始愿景到达');
  }
  const indegree = new Map([...adjacency.keys()].map((node) => [node, 0]));
  adjacency.forEach((targets) => targets.forEach((target) => indegree.set(target, (indegree.get(target) ?? 0) + 1)));
  const topologicalQueue = [...indegree].filter(([, degree]) => degree === 0).map(([node]) => node);
  let visitedCount = 0;
  while (topologicalQueue.length) {
    const from = topologicalQueue.shift();
    if (!from) break;
    visitedCount += 1;
    adjacency.get(from)?.forEach((to) => {
      const nextDegree = (indegree.get(to) ?? 0) - 1;
      indegree.set(to, nextDegree);
      if (nextDegree === 0) topologicalQueue.push(to);
    });
  }
  if (visitedCount !== adjacency.size) throw new ProjectFieldProjectionError('Room 连线必须保持无环');

  const documents = array(wayfinder.documents, `${path}.documents`);
  if (documents.length !== roomTitles.size + 3) {
    throw new ProjectFieldProjectionError(`${path}.documents 必须覆盖地图、愿景、目的地和全部 Room`);
  }
  const documentRefs = new Set<string>();
  const documentSources = new Set<string>();
  const roomDocumentIds = new Set<string>();
  const roleCounts = new Map<string, number>();
  documents.forEach((documentValue, documentIndex) => {
    const documentPath = `${path}.documents[${documentIndex}]`;
    const document = record(documentValue, documentPath);
    const role = string(document.role, `${documentPath}.role`);
    exactKeys(
      document,
      role === 'room'
        ? ['role', 'ref', 'title', 'sha256', 'sourceRefs', 'roomId']
        : ['role', 'ref', 'title', 'sha256', 'sourceRefs'],
      documentPath,
    );
    if (!WAYFINDER_DOCUMENT_ROLES.has(role)) {
      throw new ProjectFieldProjectionError(`${documentPath}.role 不受支持`);
    }
    roleCounts.set(role, (roleCounts.get(role) ?? 0) + 1);
    const ref = documentRef(document.ref, `${documentPath}.ref`);
    if (documentRefs.has(ref)) throw new ProjectFieldProjectionError(`${documentPath}.ref 重复`);
    documentRefs.add(ref);
    string(document.title, `${documentPath}.title`);
    sha256(document.sha256, `${documentPath}.sha256`);
    uniqueStrings(document.sourceRefs, `${documentPath}.sourceRefs`, 1).forEach((sourceRef) => {
      if (!allSourceIds.has(sourceRef)) {
        throw new ProjectFieldProjectionError(`${documentPath}.sourceRefs 引用了未知来源`);
      }
      documentSources.add(sourceRef);
    });
    if (role === 'room') {
      const roomId = string(document.roomId, `${documentPath}.roomId`);
      if (!roomTitles.has(roomId) || roomDocumentIds.has(roomId)) {
        throw new ProjectFieldProjectionError(`${documentPath}.roomId 重复或未知`);
      }
      roomDocumentIds.add(roomId);
    }
  });
  if (
    roleCounts.get('map') !== 1
    || roleCounts.get('initial-vision') !== 1
    || roleCounts.get('destination') !== 1
    || roleCounts.get('room') !== roomTitles.size
  ) {
    throw new ProjectFieldProjectionError(`${path}.documents 角色覆盖漂移`);
  }
  if (!sameSet(roomDocumentIds, new Set(roomTitles.keys())) || !sameSet(documentSources, allSourceIds)) {
    throw new ProjectFieldProjectionError(`${path}.documents 未完整覆盖 Room 或来源`);
  }

  const serialized = JSON.stringify(wayfinder).toLocaleLowerCase();
  FORBIDDEN_PROJECT_COPY.forEach((forbidden) => {
    if (serialized.includes(forbidden.toLocaleLowerCase())) {
      throw new ProjectFieldProjectionError(`${path} 包含不应进入项目界面的过程文字`);
    }
  });
  return wayfinder as unknown as ProjectWayfinderProjection;
}

function validateProject(value: unknown): ProjectFieldProject {
  const project = record(value, 'project');
  const projectId = string(project.id, 'project.id');
  string(project.name, 'project.name');
  string(project.compactTitle, 'project.compactTitle');
  string(project.shortName, 'project.shortName');
  string(project.subtitle, 'project.subtitle');
  string(project.destination, 'project.destination');
  string(project.heading, 'project.heading');
  string(project.origin, 'project.origin');
  const defaultRoomId = string(project.defaultRoomId, 'project.defaultRoomId');
  const rooms = array(project.rooms, 'project.rooms');
  if (!rooms.length) throw new ProjectFieldProjectionError('project.rooms 不能为空');

  const roomIds = new Set<string>();
  const roomTitles = new Map<string, string>();
  const roomSourceIds = new Map<string, Set<string>>();
  const sourceDefinitions = new Map<string, string>();
  let foregroundCount = 0;
  rooms.forEach((roomValue, roomIndex) => {
    const path = `project.rooms[${roomIndex}]`;
    const room = record(roomValue, path);
    const roomId = string(room.id, `${path}.id`);
    if (roomIds.has(roomId)) throw new ProjectFieldProjectionError(`Room id 重复：${roomId}`);
    roomIds.add(roomId);
    roomTitles.set(roomId, string(room.title, `${path}.title`));
    string(room.goal, `${path}.goal`);
    string(room.phaseLabel, `${path}.phaseLabel`);
    string(room.recentResult, `${path}.recentResult`);
    string(room.unresolved, `${path}.unresolved`);
    string(room.nextStep, `${path}.nextStep`);
    const phase = string(room.phase, `${path}.phase`);
    if (!PHASES.has(phase)) throw new ProjectFieldProjectionError(`${path}.phase 不受支持`);
    foregroundCount += Number(phase === 'foreground');
    finiteNumber(room.x, `${path}.x`);
    finiteNumber(room.y, `${path}.y`);
    if (![1, 2, 3, 4].includes(room.shape as number)) {
      throw new ProjectFieldProjectionError(`${path}.shape 必须是 1 到 4`);
    }
    const areas = array(room.areas, `${path}.areas`);
    if (!areas.length) throw new ProjectFieldProjectionError(`${path}.areas 不能为空`);
    areas.forEach((areaValue, areaIndex) => {
      const areaPath = `${path}.areas[${areaIndex}]`;
      const area = record(areaValue, areaPath);
      string(area.title, `${areaPath}.title`);
      string(area.note, `${areaPath}.note`);
      const state = string(area.state, `${areaPath}.state`);
      if (!AREA_STATES.has(state as ProjectRoomArea['state'])) {
        throw new ProjectFieldProjectionError(`${areaPath}.state 不受支持`);
      }
    });
    array(room.workflow, `${path}.workflow`).forEach((item, index) => string(item, `${path}.workflow[${index}]`));
    array(room.keywords, `${path}.keywords`).forEach((item, index) => string(item, `${path}.keywords[${index}]`));
    const sources = array(room.sources, `${path}.sources`);
    if (!sources.length) throw new ProjectFieldProjectionError(`${path}.sources 不能为空`);
    const ids = new Set<string>();
    sources.forEach((sourceValue, sourceIndex) => {
      const source = validateSource(sourceValue, `${path}.sources[${sourceIndex}]`);
      if (ids.has(source.id)) throw new ProjectFieldProjectionError(`${path}.sources id 重复：${source.id}`);
      ids.add(source.id);
      const serialized = JSON.stringify(source);
      const existing = sourceDefinitions.get(source.id);
      if (existing !== undefined && existing !== serialized) {
        throw new ProjectFieldProjectionError(`来源定义不一致：${source.id}`);
      }
      sourceDefinitions.set(source.id, serialized);
    });
    roomSourceIds.set(roomId, ids);
  });

  if (!roomIds.has(defaultRoomId)) throw new ProjectFieldProjectionError('project.defaultRoomId 不存在');
  if (foregroundCount !== 1) throw new ProjectFieldProjectionError('项目必须恰好有一个 foreground Room');
  array(project.edges, 'project.edges').forEach((edgeValue, edgeIndex) => {
    const path = `project.edges[${edgeIndex}]`;
    const edge = record(edgeValue, path);
    const from = string(edge.from, `${path}.from`);
    const to = string(edge.to, `${path}.to`);
    const kind = string(edge.kind, `${path}.kind`);
    if (!roomIds.has(from) || !roomIds.has(to)) {
      throw new ProjectFieldProjectionError(`${path} 引用了不存在的 Room`);
    }
    if (!EDGE_KINDS.has(kind)) throw new ProjectFieldProjectionError(`${path}.kind 不受支持`);
  });
  const routeCamera = record(project.routeCamera, 'project.routeCamera');
  finiteNumber(routeCamera.x, 'project.routeCamera.x');
  finiteNumber(routeCamera.y, 'project.routeCamera.y');
  finiteNumber(routeCamera.scale, 'project.routeCamera.scale');
  validateWayfinder(project.wayfinder, projectId, defaultRoomId, roomTitles, roomSourceIds);
  return project as unknown as ProjectFieldProject;
}

export function parseProjectFieldProjection(value: unknown): ProjectFieldProjectionEnvelope {
  if (ABSOLUTE_MACHINE_PATH.test(JSON.stringify(value))) {
    throw new ProjectFieldProjectionError('投影包含机器绝对路径');
  }
  const envelope = record(value, 'projection');
  if (envelope.schemaVersion !== PROJECT_FIELD_PROJECTION_SCHEMA) {
    throw new ProjectFieldProjectionError(`不支持的投影版本：${String(envelope.schemaVersion)}`);
  }
  string(envelope.generatedAt, 'projection.generatedAt');
  const revision = record(envelope.sourceRevision, 'projection.sourceRevision');
  const gitHead = string(revision.gitHead, 'projection.sourceRevision.gitHead');
  if (!GIT_HEAD.test(gitHead)) throw new ProjectFieldProjectionError('projection.sourceRevision.gitHead 无效');
  if (typeof revision.sourceWorktreeDirtyAtCuration !== 'boolean') {
    throw new ProjectFieldProjectionError('projection.sourceRevision.sourceWorktreeDirtyAtCuration 必须是布尔值');
  }
  sha256(revision.manifestSha256, 'projection.sourceRevision.manifestSha256');
  sha256(revision.documentsSha256, 'projection.sourceRevision.documentsSha256');
  sha256(revision.sessionsSha256, 'projection.sourceRevision.sessionsSha256');
  sha256(revision.commitsSha256, 'projection.sourceRevision.commitsSha256');

  const counts = record(envelope.sourceCounts, 'projection.sourceCounts');
  const expectedCounts = {
    'project-document': positiveInteger(counts.projectDocuments, 'projection.sourceCounts.projectDocuments'),
    'agent-session': positiveInteger(counts.agentSessions, 'projection.sourceCounts.agentSessions'),
    'git-commit': positiveInteger(counts.gitCommits, 'projection.sourceCounts.gitCommits'),
  } as const;
  const privacy = record(envelope.privacy, 'projection.privacy');
  exactFalse(privacy.rawChatIncluded, 'projection.privacy.rawChatIncluded');
  exactFalse(privacy.toolResultsIncluded, 'projection.privacy.toolResultsIncluded');
  exactFalse(privacy.assistantReasoningIncluded, 'projection.privacy.assistantReasoningIncluded');
  exactFalse(privacy.absolutePathsIncluded, 'projection.privacy.absolutePathsIncluded');

  const receiptIds = new Set<string>();
  const actualCounts = { 'project-document': 0, 'agent-session': 0, 'git-commit': 0 };
  array(envelope.sourceReceipts, 'projection.sourceReceipts').forEach((receiptValue, index) => {
    const path = `projection.sourceReceipts[${index}]`;
    const receipt = record(receiptValue, path);
    const id = string(receipt.id, `${path}.id`);
    const kind = string(receipt.kind, `${path}.kind`) as ProjectRoomSource['kind'];
    if (receiptIds.has(id)) throw new ProjectFieldProjectionError(`来源回执 id 重复：${id}`);
    if (!SOURCE_KINDS.has(kind)) throw new ProjectFieldProjectionError(`${path}.kind 不受支持`);
    receiptIds.add(id);
    actualCounts[kind] += 1;
    string(receipt.observedAt, `${path}.observedAt`);
    if (kind === 'project-document') sha256(receipt.sha256, `${path}.sha256`);
    if (kind === 'agent-session') sha256(receipt.userMessagesSha256, `${path}.userMessagesSha256`);
    if (kind === 'git-commit' && !GIT_HEAD.test(string(receipt.commit, `${path}.commit`))) {
      throw new ProjectFieldProjectionError(`${path}.commit 无效`);
    }
  });
  SOURCE_KINDS.forEach((kind) => {
    if (actualCounts[kind] !== expectedCounts[kind]) {
      throw new ProjectFieldProjectionError(`来源回执数量不匹配：${kind}`);
    }
  });

  const project = validateProject(envelope.project);
  const citedSourceIds = new Set(project.rooms.flatMap((room) => (room.sources ?? []).map((source) => source.id)));
  if (citedSourceIds.size !== receiptIds.size || [...citedSourceIds].some((id) => !receiptIds.has(id))) {
    throw new ProjectFieldProjectionError('Room 引用来源与来源回执不一致');
  }
  if (
    project.reconstruction?.sourceCounts.projectDocuments !== expectedCounts['project-document']
    || project.reconstruction.sourceCounts.agentSessions !== expectedCounts['agent-session']
    || project.reconstruction.sourceCounts.gitCommits !== expectedCounts['git-commit']
  ) {
    throw new ProjectFieldProjectionError('项目重建计数与投影回执不一致');
  }
  return envelope as unknown as ProjectFieldProjectionEnvelope;
}
