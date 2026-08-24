import type {
  ProjectFieldProject,
  ProjectRoomSource,
  ProjectWayfinderDocument,
  ProjectWayfinderDocumentRole,
  ProjectWayfinderRoom,
} from './prototype-data';

/**
 * Work-document contracts for the Project Workbench field.
 *
 * The wayfinder projection ships one validated document contract per project
 * object (map, initial vision, destination, and each collaboration goal):
 * role, ref, title, SHA-256 integrity, and source-receipt coverage. This
 * module turns that contract plus the already-validated projected semantics
 * into a readable index and per-document detail, without inventing content
 * that the projection does not carry.
 */

export function deliveryStageLabel(
  stageId: string,
  deliveryState: ProjectWayfinderRoom['deliveryState'],
): string {
  if (deliveryState === 'accepted') return '已验收';
  switch (stageId) {
    case 'alignment-and-decision': return '对齐中';
    case 'implementation-planning': return '规划中';
    case 'implementation-execution': return '实现中';
    case 'quality-gate': return '待真实验收';
    case 'independent-review': return '独立复核中';
    default: return stageId;
  }
}

export function deliveryDocumentLabel(ref: string): string {
  const filename = ref.split('/').at(-1) ?? ref;
  const labels: Record<string, string> = {
    'project-field.md': '项目图谱说明',
    '01-alignment-decision-packet.md': '需求对齐记录',
    '02-implementation-plan.md': '实现规划',
    '03-work-document.md': '当前交付说明',
    '04-quality-gate-pending.md': '质量检查（待完成）',
    '05-independent-review-pending.md': '独立复核（待完成）',
    '06-current-agent-handoff.md': '当前交接说明',
  };
  return labels[filename] ?? filename.replace(/\.md$/i, '').replace(/[-_]+/g, ' ');
}

const DOCUMENT_ROLE_LABELS: Record<ProjectWayfinderDocumentRole, string> = {
  map: '项目图谱',
  'initial-vision': '初始愿景',
  destination: '愿景收敛',
  room: '协作目标文档',
};

const DOCUMENT_ROLE_PURPOSES: Record<ProjectWayfinderDocumentRole, string> = {
  map: '约定协作目标分界、连线与来源回执的项目账本。',
  'initial-vision': '项目从这份需求出发；每个协作目标都要能追溯回它。',
  destination: '项目要抵达的验收边界；在全部必需目标验收前保持未抵达。',
  room: '一个协作目标的需求、决定、验收与交付契约。',
};

export type ProjectDocumentEntry = {
  ref: string;
  role: ProjectWayfinderDocumentRole;
  roleLabel: string;
  title: string;
  sha256: string;
  sourceCount: number;
  roomId?: string;
  stageLabel?: string;
  current?: boolean;
};

export type ProjectDocumentGroup = {
  id: 'charter' | 'rooms';
  label: string;
  entries: readonly ProjectDocumentEntry[];
};

export type ProjectDocumentContracts = {
  documentCount: number;
  groups: readonly ProjectDocumentGroup[];
  provenance: {
    generatedAt: string | null;
    gitHead: string | null;
    dirtyAtCuration: boolean;
    sourceCount: number;
  };
};

export type ProjectDocumentListItem = {
  label: string;
  state?: 'verified' | 'pending';
};

export type ProjectDocumentSection =
  | { kind: 'statement'; label: string; body: string }
  | { kind: 'list'; label: string; note?: string; items: readonly ProjectDocumentListItem[] }
  | { kind: 'stage-files'; label: string; note: string; items: readonly { ref: string; label: string }[] };

export type ProjectDocumentDetail = {
  entry: ProjectDocumentEntry;
  purpose: string;
  sections: readonly ProjectDocumentSection[];
  sources: readonly ProjectRoomSource[];
};

function documentEntry(
  document: ProjectWayfinderDocument,
  project: ProjectFieldProject,
): ProjectDocumentEntry {
  const wayfinder = project.wayfinder;
  const room = document.roomId
    ? wayfinder?.rooms.find((candidate) => candidate.roomId === document.roomId)
    : undefined;
  return {
    ref: document.ref,
    role: document.role,
    roleLabel: DOCUMENT_ROLE_LABELS[document.role],
    title: document.title,
    sha256: document.sha256,
    sourceCount: document.sourceRefs.length,
    ...(document.roomId ? { roomId: document.roomId } : {}),
    ...(room ? { stageLabel: deliveryStageLabel(room.currentStage, room.deliveryState) } : {}),
    ...(document.roomId && document.roomId === wayfinder?.currentRoomId ? { current: true } : {}),
  };
}

export function projectFieldDocumentContracts(
  project: ProjectFieldProject,
): ProjectDocumentContracts | null {
  const wayfinder = project.wayfinder;
  if (!wayfinder) return null;

  const roomOrder = new Map(wayfinder.rooms.map((room) => [room.roomId, room.emergedAt]));
  const charterRoleOrder: readonly ProjectWayfinderDocumentRole[] = ['map', 'initial-vision', 'destination'];
  const charterEntries = charterRoleOrder
    .map((role) => wayfinder.documents.find((document) => document.role === role))
    .filter((document): document is ProjectWayfinderDocument => Boolean(document))
    .map((document) => documentEntry(document, project));
  const roomEntries = wayfinder.documents
    .filter((document) => document.role === 'room')
    .map((document) => documentEntry(document, project))
    .sort((left, right) => (
      (roomOrder.get(left.roomId ?? '') ?? '').localeCompare(roomOrder.get(right.roomId ?? '') ?? '')
      || left.title.localeCompare(right.title)
    ));

  return {
    documentCount: wayfinder.documents.length,
    groups: [
      { id: 'charter', label: '项目章程', entries: charterEntries },
      { id: 'rooms', label: '协作目标文档', entries: roomEntries },
    ],
    provenance: {
      generatedAt: project.reconstruction?.projection?.generatedAt ?? null,
      gitHead: project.reconstruction?.projection?.gitHead ?? null,
      dirtyAtCuration: project.reconstruction?.projection?.sourceWorktreeDirtyAtCuration ?? false,
      sourceCount: wayfinder.sourceRefs.length,
    },
  };
}

function sourceDefinitions(project: ProjectFieldProject): Map<string, ProjectRoomSource> {
  const definitions = new Map<string, ProjectRoomSource>();
  for (const room of project.rooms) {
    for (const source of room.sources ?? []) {
      if (!definitions.has(source.id)) definitions.set(source.id, source);
    }
  }
  return definitions;
}

function resolveSources(
  project: ProjectFieldProject,
  sourceRefs: readonly string[],
): ProjectRoomSource[] {
  const definitions = sourceDefinitions(project);
  return sourceRefs
    .map((sourceRef) => definitions.get(sourceRef))
    .filter((source): source is ProjectRoomSource => Boolean(source))
    .sort((left, right) => right.observedAt.localeCompare(left.observedAt));
}

function roomSections(room: ProjectWayfinderRoom): ProjectDocumentSection[] {
  const sections: ProjectDocumentSection[] = [
    { kind: 'statement', label: '整理后的需求', body: room.requirement },
    { kind: 'statement', label: '要解决的问题', body: room.problem },
    {
      kind: 'list',
      label: '已确认决定',
      items: room.decisions.map((decision) => ({ label: decision })),
    },
    {
      kind: 'list',
      label: '可观察验收',
      note: `${room.progress.completed}/${room.progress.total} 已核验`,
      items: room.progress.items.map((item) => ({ label: item.label, state: item.state })),
    },
    { kind: 'statement', label: '资料中的最近进展', body: room.currentDelivery },
    { kind: 'statement', label: '资料中记录的下一步', body: room.nextMove },
  ];
  if (room.detailDocumentRefs.length) {
    sections.push({
      kind: 'stage-files',
      label: '阶段文档',
      note: '随目标文档归档；投影只携带引用与阶段。',
      items: room.detailDocumentRefs.map((ref) => ({ ref, label: deliveryDocumentLabel(ref) })),
    });
  }
  return sections;
}

export function projectFieldDocumentDetail(
  project: ProjectFieldProject,
  ref: string,
): ProjectDocumentDetail | null {
  const wayfinder = project.wayfinder;
  if (!wayfinder) return null;
  const document = wayfinder.documents.find((candidate) => candidate.ref === ref);
  if (!document) return null;

  const entry = documentEntry(document, project);
  let sections: ProjectDocumentSection[] = [];

  if (document.role === 'map') {
    sections = [
      { kind: 'statement', label: '项目航向', body: project.heading },
      {
        kind: 'list',
        label: '演化阶段',
        note: '日期只在这里按需读取，不进入总览。',
        items: wayfinder.evolution.epochs.map((epoch) => ({
          label: `${epoch.label} · ${epoch.summary}`,
        })),
      },
    ];
  } else if (document.role === 'initial-vision') {
    sections = [
      { kind: 'statement', label: '愿景陈述', body: wayfinder.initialVision.statement },
      {
        kind: 'list',
        label: '可观察锚点',
        items: wayfinder.initialVision.observableAnchors.map((anchor) => ({ label: anchor })),
      },
    ];
  } else if (document.role === 'destination') {
    sections = [
      { kind: 'statement', label: '愿景陈述', body: wayfinder.destination.statement },
      {
        kind: 'list',
        label: '验收观察',
        note: '目的地尚未抵达',
        items: wayfinder.destination.acceptanceObservations.map((observation) => ({
          label: observation,
        })),
      },
    ];
  } else {
    const room = wayfinder.rooms.find((candidate) => candidate.roomId === document.roomId);
    if (!room) return null;
    sections = roomSections(room);
  }

  return {
    entry,
    purpose: DOCUMENT_ROLE_PURPOSES[document.role],
    sections,
    sources: resolveSources(project, document.sourceRefs),
  };
}
