import { describe, expect, it } from 'vitest';
import {
  deliveryDocumentLabel,
  deliveryStageLabel,
  projectFieldDocumentContracts,
  projectFieldDocumentDetail,
} from './project-documents';
import { projectFieldProjects } from './prototype-data';

const SHA256 = /^[a-f0-9]{64}$/;

function reconstructedProject() {
  const project = projectFieldProjects.find((candidate) => candidate.id === 'personal-agent-workbench');
  if (!project) throw new Error('missing reconstructed project fixture');
  return project;
}

describe('Project work-document contracts', () => {
  it('indexes every validated document contract with role, integrity, and source coverage', () => {
    const project = reconstructedProject();
    const contracts = projectFieldDocumentContracts(project);

    expect(contracts).not.toBeNull();
    expect(contracts?.documentCount).toBe(11);
    expect(contracts?.groups.map((group) => group.id)).toEqual(['charter', 'rooms']);

    const charter = contracts?.groups[0];
    expect(charter?.label).toBe('项目章程');
    expect(charter?.entries.map((entry) => entry.role)).toEqual(['map', 'initial-vision', 'destination']);

    const rooms = contracts?.groups[1];
    expect(rooms?.entries).toHaveLength(8);
    const emergedOrder = rooms?.entries.map((entry) => {
      const room = project.wayfinder?.rooms.find((candidate) => candidate.roomId === entry.roomId);
      return room?.emergedAt ?? '';
    }) ?? [];
    expect([...emergedOrder].sort((left, right) => left.localeCompare(right))).toEqual(emergedOrder);

    for (const entry of [...(charter?.entries ?? []), ...(rooms?.entries ?? [])]) {
      expect(entry.sha256).toMatch(SHA256);
      expect(entry.sourceCount).toBeGreaterThan(0);
      expect(entry.ref.endsWith('.md')).toBe(true);
    }
    for (const entry of rooms?.entries ?? []) {
      expect(entry.roomId).toBeTruthy();
      expect(entry.stageLabel).toBeTruthy();
    }

    const currentEntries = rooms?.entries.filter((entry) => entry.current) ?? [];
    expect(currentEntries).toHaveLength(1);
    expect(currentEntries[0]?.ref).toBe('rooms/project-field.md');
  });

  it('reports the projection provenance as repository state, not document meaning', () => {
    const contracts = projectFieldDocumentContracts(reconstructedProject());

    expect(contracts?.provenance.gitHead).toBe('8a50a6b21ced9edb1a46b1cb4dc2b004ba0ee771');
    expect(contracts?.provenance.generatedAt).toBeTruthy();
    expect(typeof contracts?.provenance.dirtyAtCuration).toBe('boolean');
    expect(contracts?.provenance.sourceCount).toBe(35);
  });

  it('returns no contracts for prototype projects without a validated projection', () => {
    const prototype = projectFieldProjects.find((candidate) => candidate.id === 'wisdom-weasel');
    expect(prototype).toBeDefined();
    expect(projectFieldDocumentContracts(prototype!)).toBeNull();
    expect(projectFieldDocumentDetail(prototype!, 'rooms/anything.md')).toBeNull();
  });

  it('projects a collaboration-goal document into its accepted semantics and receipts', () => {
    const project = reconstructedProject();
    const detail = projectFieldDocumentDetail(project, 'rooms/project-field.md');

    expect(detail).not.toBeNull();
    expect(detail?.entry.roomId).toBe('project-field');
    expect(detail?.entry.current).toBe(true);
    expect(detail?.sections.map((section) => section.label)).toEqual([
      '整理后的需求',
      '要解决的问题',
      '已确认决定',
      '可观察验收',
      '资料中的最近进展',
      '资料中记录的下一步',
      '阶段文档',
    ]);

    const acceptance = detail?.sections.find((section) => section.label === '可观察验收');
    expect(acceptance?.kind).toBe('list');
    if (acceptance?.kind === 'list') {
      expect(acceptance.note).toBe('5/6 已核验');
      expect(acceptance.items.filter((item) => item.state === 'verified')).toHaveLength(5);
      expect(acceptance.items.filter((item) => item.state === 'pending')).toHaveLength(1);
    }

    const stageFiles = detail?.sections.find((section) => section.kind === 'stage-files');
    expect(stageFiles?.kind).toBe('stage-files');
    if (stageFiles?.kind === 'stage-files') {
      expect(stageFiles.items.map((item) => item.label)).toEqual([
        '需求对齐记录',
        '实现规划',
        '当前交付说明',
        '质量检查（待完成）',
        '独立复核（待完成）',
      ]);
    }

    expect(detail?.sources).toHaveLength(detail?.entry.sourceCount ?? -1);
    const observedOrder = detail?.sources.map((source) => source.observedAt) ?? [];
    expect([...observedOrder].sort((left, right) => right.localeCompare(left))).toEqual(observedOrder);
    expect(detail?.sources.every((source) => !source.ref.includes('/Users/'))).toBe(true);
  });

  it('projects charter documents from the validated vision and destination', () => {
    const project = reconstructedProject();

    const vision = projectFieldDocumentDetail(project, 'project/00-initial-vision.md');
    expect(vision?.entry.roomId).toBeUndefined();
    expect(vision?.sections.map((section) => section.label)).toEqual(['愿景陈述', '可观察锚点']);

    const destination = projectFieldDocumentDetail(project, 'project/01-destination.md');
    const observations = destination?.sections.find((section) => section.label === '验收观察');
    expect(observations?.kind).toBe('list');
    if (observations?.kind === 'list') {
      expect(observations.note).toBe('目的地尚未抵达');
      expect(observations.items.every((item) => item.state === undefined)).toBe(true);
    }

    const map = projectFieldDocumentDetail(project, '00-map.md');
    const epochs = map?.sections.find((section) => section.label === '演化阶段');
    expect(epochs?.kind).toBe('list');
    if (epochs?.kind === 'list') {
      expect(epochs.items.length).toBeGreaterThan(0);
    }
  });

  it('rejects unknown document refs instead of inventing content', () => {
    expect(projectFieldDocumentDetail(reconstructedProject(), 'rooms/not-a-document.md')).toBeNull();
  });

  it('keeps the delivery stage and stage-document language stable', () => {
    expect(deliveryStageLabel('quality-gate', 'active')).toBe('待真实验收');
    expect(deliveryStageLabel('quality-gate', 'accepted')).toBe('已验收');
    expect(deliveryDocumentLabel('rooms/project-field.md')).toBe('项目图谱说明');
    expect(deliveryDocumentLabel('03-work-document.md')).toBe('当前交付说明');
  });
});
