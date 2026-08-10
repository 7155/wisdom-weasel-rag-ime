import { describe, expect, it } from 'vitest';
import generatedProjection from './generated/personal-agent-workbench.v1.json';
import {
  parseProjectFieldProjection,
  ProjectFieldProjectionError,
} from './project-field-projection';

function cloneProjection(): Record<string, unknown> {
  return structuredClone(generatedProjection) as unknown as Record<string, unknown>;
}

function projectWayfinder(projection: Record<string, unknown>): Record<string, unknown> {
  const project = projection.project as Record<string, unknown>;
  return project.wayfinder as Record<string, unknown>;
}

describe('Project Field projection boundary', () => {
  it('accepts the generated real-project projection and exposes only bounded receipts', () => {
    const projection = parseProjectFieldProjection(generatedProjection);

    expect(projection.project.rooms).toHaveLength(8);
    expect(projection.project.compactTitle).toBe('个人助手工作台');
    expect(projection.sourceReceipts).toHaveLength(35);
    expect(projection.sourceCounts).toEqual({
      projectDocuments: 7,
      agentSessions: 12,
      gitCommits: 16,
    });
    expect(projection.project).not.toHaveProperty('fog');
    expect(projection.project).not.toHaveProperty('frontier');
    expect(projection.project.wayfinder).not.toHaveProperty('sharedArchitecture');
    expect(JSON.stringify(projection)).not.toContain('/Users/');
    expect(JSON.stringify(projection)).not.toContain('userExcerpts');
  });

  it('fails closed when privacy, schema, or source receipts drift', () => {
    const wrongSchema = cloneProjection();
    wrongSchema.schemaVersion = 'personal-agent.project-field-projection.v2';
    expect(() => parseProjectFieldProjection(wrongSchema)).toThrow(ProjectFieldProjectionError);

    const rawChat = cloneProjection();
    (rawChat.privacy as Record<string, unknown>).rawChatIncluded = true;
    expect(() => parseProjectFieldProjection(rawChat)).toThrow(/rawChatIncluded/);

    const missingReceipt = cloneProjection();
    (missingReceipt.sourceReceipts as unknown[]).pop();
    expect(() => parseProjectFieldProjection(missingReceipt)).toThrow(/来源回执数量不匹配/);

    const missingCompactTitle = cloneProjection();
    delete (missingCompactTitle.project as Record<string, unknown>).compactTitle;
    expect(() => parseProjectFieldProjection(missingCompactTitle)).toThrow(/compactTitle/);
  });

  it('rejects machine paths even when they are hidden in display content', () => {
    const projection = cloneProjection();
    const project = projection.project as Record<string, unknown>;
    project.heading = '读取 /Users/example/private/session.jsonl';

    expect(() => parseProjectFieldProjection(projection)).toThrow(/机器绝对路径/);
  });

  it('fails closed when any authoritative Wayfinder dimension drifts', () => {
    const missingInitialVision = cloneProjection();
    (projectWayfinder(missingInitialVision).initialVision as Record<string, unknown>).statement = '';
    expect(() => parseProjectFieldProjection(missingInitialVision)).toThrow(/initialVision/);

    const missingDestination = cloneProjection();
    (projectWayfinder(missingDestination).destination as Record<string, unknown>).state = 'reached';
    expect(() => parseProjectFieldProjection(missingDestination)).toThrow(/Destination/);

    const missingRequirement = cloneProjection();
    ((projectWayfinder(missingRequirement).rooms as Record<string, unknown>[])[0]).requirement = '';
    expect(() => parseProjectFieldProjection(missingRequirement)).toThrow(/requirement/);

    const missingAcceptance = cloneProjection();
    ((projectWayfinder(missingAcceptance).rooms as Record<string, unknown>[])[0]).acceptanceObservations = [];
    expect(() => parseProjectFieldProjection(missingAcceptance)).toThrow(/acceptanceObservations/);

    const invalidProgress = cloneProjection();
    (((projectWayfinder(invalidProgress).rooms as Record<string, unknown>[])[0]).progress as Record<string, unknown>).completed = 99;
    expect(() => parseProjectFieldProjection(invalidProgress)).toThrow(/progress/);

    const invalidEpoch = cloneProjection();
    ((projectWayfinder(invalidEpoch).rooms as Record<string, unknown>[])[0]).epochId = 'unknown';
    expect(() => parseProjectFieldProjection(invalidEpoch)).toThrow(/epochId/);

    const invalidEvolution = cloneProjection();
    (projectWayfinder(invalidEvolution).evolution as Record<string, unknown>).direction = 'top-to-bottom';
    expect(() => parseProjectFieldProjection(invalidEvolution)).toThrow(/evolution/);

    const missingDecisions = cloneProjection();
    ((projectWayfinder(missingDecisions).rooms as Record<string, unknown>[])[0]).decisions = [];
    expect(() => parseProjectFieldProjection(missingDecisions)).toThrow(/decisions/);

    const connectedDestination = cloneProjection();
    ((projectWayfinder(connectedDestination).relations as Record<string, unknown>[])[0]).to = '@destination';
    expect(() => parseProjectFieldProjection(connectedDestination)).toThrow(/端点/);

    const missingRelationReceipt = cloneProjection();
    ((projectWayfinder(missingRelationReceipt).relations as Record<string, unknown>[])[0]).sourceRefs = [];
    expect(() => parseProjectFieldProjection(missingRelationReceipt)).toThrow(/sourceRefs/);

    const invalidSkill = cloneProjection();
    ((projectWayfinder(invalidSkill).rooms as Record<string, unknown>[])[0]).currentStage = 'unknown';
    expect(() => parseProjectFieldProjection(invalidSkill)).toThrow(/currentStage/);

    const invalidTddParent = cloneProjection();
    const deliveryEngine = projectWayfinder(invalidTddParent).deliveryEngine as Record<string, unknown>;
    (deliveryEngine.innerMethod as Record<string, unknown>).parentStage = 'quality-gate';
    expect(() => parseProjectFieldProjection(invalidTddParent)).toThrow(/测试驱动实现/);

    const unknownSource = cloneProjection();
    ((projectWayfinder(unknownSource).documents as Record<string, unknown>[])[0].sourceRefs as string[])
      .push('source-missing');
    expect(() => parseProjectFieldProjection(unknownSource)).toThrow(/未知来源/);
  });

  it('binds vision, requirement Rooms, relations, delivery stages, docs, and receipts', () => {
    const projection = parseProjectFieldProjection(generatedProjection);
    const wayfinder = projection.project.wayfinder;
    const room = wayfinder?.rooms.find((candidate) => candidate.roomId === 'project-field');

    expect(wayfinder?.schemaVersion).toBe('personal-agent.project-wayfinder.v2');
    expect(wayfinder?.rooms.map(({ roomId }) => roomId)).toEqual([
      'input-experience',
      'governed-memory',
      'unified-workbench',
      'room-delivery',
      'agent-continuity',
      'workflow-system',
      'project-field',
      'release-journey',
    ]);
    expect(wayfinder?.destination).toMatchObject({
      title: '可持续交付的个人 Agent 工作台',
      state: 'unreached',
    });
    expect(wayfinder?.deliveryEngine.stages.map(({ id, title }) => [id, title])).toEqual([
      ['alignment-and-decision', '需求对齐'],
      ['implementation-planning', '实现规划'],
      ['implementation-execution', '实现执行'],
      ['quality-gate', '质量门'],
      ['independent-review', '独立复核'],
    ]);
    expect(wayfinder?.deliveryEngine.innerMethod).toMatchObject({
      id: 'test-driven-implementation',
      parentStage: 'implementation-execution',
    });
    expect(room).toMatchObject({
      currentStage: 'implementation-execution',
      deliveryState: 'active',
      epochId: 'project-field',
      topologyRole: 'room',
    });
    expect(room?.progress.completed).toBeLessThan(room?.progress.total ?? 0);
    expect(wayfinder?.evolution).toMatchObject({
      direction: 'left-to-right',
      releaseLane: { roomId: 'release-journey' },
    });
    expect(room?.decisions).toContain(
      '主图由真实历史决定从左到右的 DAG 拓扑；Room 可以分化、细化和依赖，但连线必须是有来源回执的 refines、led-to 或 requires，不能为视觉效果随意连接。总览不显示时间轴、日期刻度或卡片日期，日期只在详情和来源 receipts 中按需读取。',
    );
    expect(wayfinder?.relations.filter(({ from }) => from === '@origin')).toHaveLength(1);
    expect(new Set(wayfinder?.relations.map(({ kind }) => kind))).toEqual(new Set(['refines', 'led-to', 'requires']));
    expect(wayfinder?.relations.every(({ sourceRefs }) => sourceRefs.length > 0)).toBe(true);
    expect(wayfinder?.documents).toHaveLength(11);
    expect(new Set(wayfinder?.sourceRefs)).toEqual(
      new Set(projection.project.rooms.flatMap((candidate) => candidate.sources?.map((source) => source.id) ?? [])),
    );
  });
});
