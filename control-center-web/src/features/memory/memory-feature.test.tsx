import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { previewPersonas } from '@/features/agent/preview-data';
import { MemoryFeature } from './index';

afterEach(() => {
  cleanup();
  window.history.replaceState(null, '', '/');
});

describe('MemoryFeature relations', () => {
  it('shows automatic timeline publication and keeps an immediate manual control', async () => {
    const user = userEvent.setup();
    const date = localCalendarDate();
    let status = 'draft';
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': {
          ok: true,
          memoryBookCount: 3,
          memoryAtomCount: 8,
          activityTimelineCounts: { draft: 1 },
          roleBookRevisionCounts: { active: 1 },
          projection: { fresh: true, retrievalDocuments: 12, backlog: 0 },
        },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'memory.activityTimeline.get': () => ({ ok: true, timeline: activityTimeline(status, date) }),
        'memory.activityTimeline.approve': (request: ControlRequest) => {
          expect(request.body).toEqual({
            timelineId: `timeline:${date}`,
            expectedSourceEventHash: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            confirmText: 'approve',
          });
          status = 'approved';
          return { ok: true, decision: 'accepted', timeline: activityTimeline(status, date) };
        },
        'memory.activityTimeline.build': (request: ControlRequest) => {
          expect(request.body).toEqual({ date });
          status = 'draft';
          return { ok: true, timeline: activityTimeline(status, date) };
        },
        'memory.activityTimeline.reject': (request: ControlRequest) => {
          expect(request.body).toEqual({
            timelineId: `timeline:${date}`,
            reason: '时段划分需要调整',
            confirmText: 'reject',
          });
          status = 'rejected';
          return { ok: true, decision: 'rejected', timeline: activityTimeline(status, date) };
        },
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '时间线' }));
    expect(await screen.findByText('实现最终输入框捕获并核对三条记忆消费路径。')).toBeInTheDocument();
    expect(screen.getByText('2 个语义任务')).toBeInTheDocument();
    expect(screen.getByText('后台会自动发布；仅在时间类问题中按需召回')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '立即发布' }));
    const dialog = await screen.findByRole('dialog', { name: /发布/ });
    await user.click(within(dialog).getByRole('button', { name: '发布到时间线' }));

    expect(await screen.findByText('已发布')).toBeInTheDocument();
    expect(screen.getByText('已进入独立时间线索引')).toBeInTheDocument();
    expect(transport.requests.filter((call) => call.request.pathId === 'memory.activityTimeline.approve')).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: '重新整理' }));
    expect(await screen.findByText('待自动发布')).toBeInTheDocument();
    expect(transport.requests.filter((call) => call.request.pathId === 'memory.activityTimeline.build')).toHaveLength(1);

    await user.click(screen.getByRole('button', { name: '驳回' }));
    const rejectDialog = await screen.findByRole('dialog', { name: '驳回当天整理' });
    await user.type(within(rejectDialog).getByLabelText('原因'), '时段划分需要调整');
    await user.click(within(rejectDialog).getByRole('button', { name: '确认驳回' }));

    expect(await screen.findByText('已删除')).toBeInTheDocument();
    expect(screen.getByText('本次整理未进入长期上下文')).toBeInTheDocument();
    expect(transport.requests.filter((call) => call.request.pathId === 'memory.activityTimeline.reject')).toHaveLength(1);
  });

  it('fails closed without the activity timeline read capability', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      capabilities: { routeIds: ['memory.summary', 'memory.pages'] },
      routes: {
        'memory.summary': { ok: true, memoryBookCount: 1, memoryAtomCount: 2 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '时间线' }));
    expect(await screen.findByText('当前服务未开放每日活动读取')).toBeInTheDocument();
    expect(screen.queryByText('正在读取当天活动')).not.toBeInTheDocument();
    expect(screen.queryByText('尚未生成时间线')).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'memory.activityTimeline.get')).toBe(false);
  });

  it('keeps Agent memory curation under the 治理 tab instead of knowledge tasks', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 3, memoryItemCount: 2, memoryBookCount: 1, memoryAtomCount: 1, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'agent.memoryMaintenance.run': (request: ControlRequest) => request.query?.runId
          ? memoryCurationRun()
          : memoryCurationStatus(),
      },
    });
    renderMemory(transport);

    expect(await screen.findByRole('heading', { name: '记忆', level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '记忆整理审核' })).not.toBeInTheDocument();
    await user.click(await screen.findByRole('tab', { name: '治理' }));
    expect(await screen.findByRole('heading', { name: '记忆整理审核', level: 2 })).toBeInTheDocument();
    expect(await screen.findByRole('list', { name: '记忆整理建议' })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('输入一个明确的知识任务')).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.memoryMaintenance.run')).toBe(true);
    expect(transport.requests.some((call) => call.request.pathId === 'knowledge.routeStatus')).toBe(false);
  });

  it('updates only the selected Agent draft item before any database apply', async () => {
    const user = userEvent.setup();
    let secondSelected = false;
    const transport = new MockControlTransport({
      capabilities: { features: { managementWorkContract: true, knowledgeDatabaseWorkContract: true } },
      routes: {
        'memory.summary': { ok: true, appCount: 1, completeInputCount: 3, memoryBookCount: 1, memoryAtomCount: 1, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'agent.memoryMaintenance.run': (request: ControlRequest) => {
          if (!request.query?.runId) return memoryCurationStatus();
          const result = memoryCurationRun();
          const changes = ((result.run as Record<string, unknown>).changes as Record<string, unknown>[]);
          changes[1] = { ...changes[1], selected: secondSelected, status: secondSelected ? 'approved' : 'rejected' };
          return result;
        },
        'knowledge.database.draft.edit': (request: ControlRequest) => {
          expect(request.body).toEqual({ runId: 'memory_book_test', diffId: 2, selected: true });
          secondSelected = true;
          return { ok: true, runId: 'memory_book_test', diffId: 2, selected: true };
        },
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '治理' }));
    const checkbox = await screen.findByRole('checkbox', { name: '选择 合并输入法同义标签' });
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);

    await waitFor(() => expect(checkbox).toBeChecked());
    expect(screen.getByText('2 / 2 已选择')).toBeInTheDocument();
    expect(transport.requests.filter((call) => call.request.pathId === 'knowledge.database.draft.edit')).toHaveLength(1);
    expect(transport.requests.some((call) => call.request.pathId === 'knowledge.database.apply')).toBe(false);
  });

  it('keeps only evidence, current facts, and topic books in the primary memory chain', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, pendingCompileEvents: 2 },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
        'memory.graph.get': (request: ControlRequest) => memoryGraph(String(request.query?.plane ?? '')),
        'memory.entity.get': (request: ControlRequest) => memoryEntity(
          String(request.params?.kind ?? ''),
          String(request.params?.entityId ?? ''),
        ),
      },
    });
    renderMemory(transport);

    const layerSelector = await screen.findByRole('radiogroup', { name: '事实链层级' });
    expect(within(layerSelector).getAllByRole('radio').map((item) => item.textContent)).toEqual([
      '证据',
      '当前事实',
      '主题书',
    ]);
    expect(within(layerSelector).queryByRole('radio', { name: '应用' })).not.toBeInTheDocument();
    expect(within(layerSelector).queryByRole('radio', { name: '标签' })).not.toBeInTheDocument();
    expect(within(layerSelector).queryByRole('radio', { name: '短语' })).not.toBeInTheDocument();
    expect(within(layerSelector).queryByRole('radio', { name: '负反馈' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: '关系索引' }));
    expect(await screen.findByRole('heading', { name: '记忆关系', level: 2 })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /Agent Runtime，11 条记忆/ })).toBeInTheDocument();
  });

  it('labels active Agent evidence as audit-only instead of active memory', async () => {
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, memoryBookCount: 1, memoryAtomCount: 1 },
        'memory.pages': (request: ControlRequest) => ({
          ok: true,
          items: request.params?.kind === 'evidence' ? [{
            id: 'evidence:workflow-noise',
            title: 'curation_prepare 流程回执',
            detail: 'user_message',
            status: 'active',
            source: { kind: 'agent_memory_evidence', id: 'evidence:workflow-noise' },
            ownerKind: 'agent',
            ownerId: 'zhiyou-v1',
          }] : [],
          nextCursor: '',
          limit: 50,
        }),
      },
    });
    renderMemory(transport, '/memory?layer=evidence');

    expect(await screen.findByText('审计保留')).toBeInTheDocument();
    expect(screen.queryByText('使用中')).not.toBeInTheDocument();
  });

  it('starts from active memory and keeps preserved history inspectable', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, memoryBookCount: 10, memoryAtomCount: 103, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
      },
    });
    renderMemory(transport);

    await waitFor(() => {
      const request = transport.requests.find((call) => call.request.pathId === 'memory.pages');
      expect(request?.request.query?.status).toBe('active');
    });
    await user.click(await screen.findByRole('combobox', { name: '状态' }));
    expect(await screen.findByRole('option', { name: '历史保留' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '已合并' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '碎片证据' })).toBeInTheDocument();
  });

  it('normalizes structured source and sourceType/sourceId evidence references', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, memoryBookCount: 1, memoryAtomCount: 1 },
        'memory.pages': {
          ok: true,
          items: [{
            atomId: 'atom:structured-source',
            text: '最终输入框内容优先进入记忆',
            status: 'active',
            source: { type: 'input_event', id: 'input-memory:42' },
            ref: { kind: 'atom', referenceId: 'atom:structured-source' },
            evidenceRefs: [{ sourceType: 'input_event', sourceId: 'input-memory:42', textPreview: 'AX 最终输入' }],
          }],
          nextCursor: '',
          limit: 50,
        },
        'memory.reference.get': (request: ControlRequest) => {
          expect(request.params).toEqual({ kind: 'event', referenceId: 'input-memory:42' });
          return {
            ok: true,
            ref: { kind: 'event', referenceId: 'input-memory:42', status: 'active' },
            source: { type: 'ax_focused_value', id: 'input-memory:42' },
            item: { title: 'AX 最终输入', status: 'active', text: '最终输入框内容优先进入记忆' },
            evidenceRefs: [],
          };
        },
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('button', { name: /最终输入框内容优先进入记忆/ }));
    const detail = screen.getByRole('region', { name: '最终输入框内容优先进入记忆 详情' });
    expect(within(detail).getByText('输入记录')).toBeInTheDocument();
    await user.click(within(detail).getByRole('button', { name: /AX 最终输入/ }));
    const dialog = await screen.findByRole('dialog', { name: 'AX 最终输入' });
    expect(within(dialog).getByText('ax_focused_value')).toBeInTheDocument();
  });

  it('keeps App counts as source-index statistics instead of a peer memory layer', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': {
          ok: true,
          appCount: 1,
          completeInputCount: 8,
          blockedFragmentCount: 44,
          memoryBookCount: 1,
          memoryAtomCount: 2,
          memoryAtomTotalCount: 8,
          memoryAtomArchivedCount: 4,
          memoryAtomSourceArchiveCount: 2,
          pendingCompileEvents: 0,
        },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
      },
    });
    renderMemory(transport);

    expect(await screen.findByText('共 8 条 · 历史 4 · 碎片证据 2')).toBeInTheDocument();
    expect(screen.getByText('8 条完整输入')).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: '应用' })).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.params?.kind === 'apps')).toBe(false);
  });

  it('opens every overview layer and routes role books independently', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, pendingCompileEvents: 2 },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
        'agent.roles.list': { ok: true, items: [] },
      },
    });
    renderMemory(transport);

    const pipeline = await screen.findByLabelText('个人上下文数据层');
    await user.click(within(pipeline).getByRole('button', { name: /可追溯证据/ }));
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'memory.pages' && call.request.params?.kind === 'evidence'
    ))).toBe(true));
    await user.click(within(screen.getByLabelText('个人上下文数据层')).getByRole('button', { name: /主题书/ }));
    await waitFor(() => expect(transport.requests.some((call) => (
      call.request.pathId === 'memory.pages' && call.request.params?.kind === 'books'
    ))).toBe(true));
    await user.click(within(screen.getByLabelText('个人上下文数据层')).getByRole('button', { name: /角色书/ }));
    expect(await screen.findByRole('heading', { name: '角色书', level: 3 })).toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'agent.roles.list')).toBe(true);
  });

  it('opens role-book entries and their evidence without mixing them into personal facts', async () => {
    const user = userEvent.setup();
    const persona = previewPersonas[0]!;
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, memoryBookCount: 1, memoryAtomCount: 2 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'agent.roles.list': { ok: true, items: [persona] },
        'agent.roleBook.get': {
          ok: true,
          active: {
            revisionId: 'revision:role-current',
            revisionNumber: 3,
            displayName: persona.displayName,
            mission: '保持角色工作连续性',
            status: 'active',
            sections: {
              personality: [],
              capabilities: [],
              recentWork: [{
                itemId: 'recent-work:1',
                text: '完成记忆事实链重构',
                evidenceIds: ['evidence:role-work'],
                provenance: { sourceType: 'daily_session_summary', sourceId: 'session:1' },
              }],
              lessonsAndLimits: [],
              activeCommitments: [],
            },
          },
          history: [],
          dailyDrafts: [],
        },
        'memory.reference.get': (request: ControlRequest) => ({
          ok: true,
          ref: { kind: request.params?.kind, referenceId: request.params?.referenceId, status: 'active' },
          item: { title: '角色工作证据', status: 'active', text: '已完成事实链重构并通过测试。' },
          evidenceRefs: [],
        }),
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '角色书' }));
    expect(await screen.findByRole('heading', { name: persona.displayName, level: 3 })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /完成记忆事实链重构/ }));
    const detail = screen.getByLabelText('近期工作条目详情');
    expect(within(detail).getByText('daily_session_summary')).toBeInTheDocument();
    await user.click(within(detail).getByRole('button', { name: /evidence:role-work/ }));
    expect(await screen.findByRole('dialog', { name: '角色工作证据' })).toBeInTheDocument();
    expect(transport.requests.some((call) => (
      call.request.pathId === 'memory.reference.get'
      && call.request.params?.kind === 'evidence'
      && call.request.params?.referenceId === 'evidence:role-work'
    ))).toBe(true);
  });

  it.each([
    { layer: 'atoms', id: 'atom:deep-link', kind: 'atom', tab: '事实链' },
    { layer: 'books', id: 'book:deep-link', kind: 'book', tab: '事实链' },
    { layer: 'evidence', id: 'evidence:deep-link', kind: 'evidence', tab: '事实链' },
    { layer: 'timelines', id: 'timeline:2026-07-18', kind: 'timeline', tab: '时间线' },
    { layer: 'role-books', id: 'revision:deep-link', kind: 'role_book_revision', tab: '角色书' },
  ])('opens the $layer deep link and selects its stable reference', async ({ id, kind, layer, tab }) => {
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, memoryBookCount: 1, memoryAtomCount: 1 },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
        'memory.reference.get': (request: ControlRequest) => {
          expect(request.params).toEqual({ kind, referenceId: id });
          return {
            ok: true,
            ref: { kind, referenceId: id, status: 'active' },
            item: { id, title: `深链 ${layer}`, status: 'active', text: '公开详情' },
            evidenceRefs: [],
          };
        },
        'agent.roles.list': { ok: true, items: [] },
      },
    });
    renderMemory(transport, `/memory?layer=${layer}&id=${encodeURIComponent(id)}`);

    expect(await screen.findByRole('tab', { name: tab, hidden: true })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('dialog', { name: `深链 ${layer}` })).toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'memory.reference.get')).toBe(true);
  });

  it('recursively opens evidence references, blocks cycles, and explains redaction', async () => {
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, memoryBookCount: 1, memoryAtomCount: 1 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'memory.reference.get': (request: ControlRequest) => {
          if (request.params?.kind === 'event') {
            return {
              ok: true,
              item: { title: '原始事件', status: 'archived' },
              evidenceRefs: [{ kind: 'evidence', referenceId: 'evidence:redacted', label: '返回根节点' }],
            };
          }
          return {
            ok: true,
            redacted: true,
            item: {
              title: '已脱敏证据',
              status: 'not_for_memory',
              sensitive: true,
              text: 'SECRET SHOULD NEVER RENDER',
            },
            evidenceRefs: [{ kind: 'event', referenceId: 'event:1', label: '原始输入' }],
          };
        },
      },
    });
    renderMemory(transport, '/memory?layer=evidence&id=evidence%3Aredacted');

    const dialog = await screen.findByRole('dialog', { name: '已脱敏证据' });
    expect(within(dialog).getByText('内容已脱敏')).toBeInTheDocument();
    expect(within(dialog).queryByText('SECRET SHOULD NEVER RENDER')).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('button', { name: /原始输入/ }));
    expect(await within(dialog).findByRole('heading', { name: '原始事件' })).toBeInTheDocument();
    expect(within(dialog).getByText('已在路径中')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /返回根节点/ })).toBeDisabled();
  });

  it('edits the selected topic-book stable id directly', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, runtimeRevision: 7, eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, pendingCompileEvents: 2 },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
        'memory.edit': (request: ControlRequest) => {
          expect(request.body).toEqual({
            kind: 'books',
            id: 'book-1',
            title: '控制中心真实迁移',
            summary: 'React 页面与本机事务',
            tags: ['控制中心', '真实环境'],
          });
          return { schemaVersion: 'rag-ime.memory-edit.v1', ok: true, kind: 'books', id: 'book-1' };
        },
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('radio', { name: '主题书' }));
    await user.click(await screen.findByRole('button', { name: /控制中心迁移/ }));
    const editWorkflow = screen.getByText('编辑内容').closest('.mgmt-workflow');
    expect(editWorkflow).not.toBeNull();
    await user.click(within(editWorkflow as HTMLElement).getByRole('button', { name: '编辑' }));
    const dialog = await screen.findByRole('dialog', { name: '编辑主题书' });
    const title = within(dialog).getByRole('textbox', { name: '标题' });
    const summary = within(dialog).getByRole('textbox', { name: '摘要' });
    const tags = within(dialog).getByRole('textbox', { name: '标签' });
    expect(title).toHaveValue('控制中心迁移');
    expect(summary).toHaveValue('React 页面与受控接口');
    await user.clear(title);
    await user.type(title, '控制中心真实迁移');
    await user.clear(summary);
    await user.type(summary, 'React 页面与本机事务');
    await user.clear(tags);
    await user.type(tags, '控制中心，真实环境');
    await user.click(within(dialog).getByRole('button', { name: '保存' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '编辑主题书' })).not.toBeInTheDocument());
    expect(transport.requests.filter((call) => call.request.pathId === 'memory.edit')).toHaveLength(1);
    expect(document.body).not.toHaveTextContent('book-1');
  });

  it('keeps a failed edit draft and replaces internal errors with friendly copy', async () => {
    const user = userEvent.setup();
    const internal = '/Users/private/memory.sqlite pathId=memory.edit schemaVersion rawJson';
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, runtimeRevision: 7, eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, pendingCompileEvents: 2 },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
        'memory.edit': () => Promise.reject(new Error(internal)),
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('radio', { name: '主题书' }));
    await user.click(await screen.findByRole('button', { name: /控制中心迁移/ }));
    await user.click(within(screen.getByText('编辑内容').closest('.mgmt-workflow') as HTMLElement).getByRole('button', { name: '编辑' }));
    const dialog = await screen.findByRole('dialog', { name: '编辑主题书' });
    const summary = within(dialog).getByRole('textbox', { name: '摘要' });
    await user.clear(summary);
    await user.type(summary, '失败后仍应保留的草稿');
    await user.click(within(dialog).getByRole('button', { name: '保存' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('保存失败。草稿已保留');
    expect(summary).toHaveValue('失败后仍应保留的草稿');
    expect(document.body).not.toHaveTextContent(internal);
    expect(document.body).not.toHaveTextContent('pathId');
    expect(document.body).not.toHaveTextContent('schemaVersion');
    expect(document.body).not.toHaveTextContent('rawJson');
  });

  it('restores forgotten input evidence without exposing a raw-memory edit form', async () => {
    const user = userEvent.setup();
    let disposition = 'not_for_memory';
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': {
          ok: true,
          eventCount: 18,
          memoryItemCount: 14,
          memoryBookCount: 4,
          memoryAtomCount: 10,
          evidenceSourceCount: 1,
          forgottenSourceCount: 1,
          needsReviewSourceCount: 0,
          owners: [{ ownerKind: 'user', ownerId: 'default', itemCount: 1 }],
        },
        'memory.pages': (request: ControlRequest) => {
          if (request.params?.kind !== 'evidence') {
            return { ok: true, items: [], nextCursor: '', limit: 50 };
          }
          return {
            ok: true,
            items: [{
              id: 'input-memory:42',
              title: '嗯嗯那个这个',
              detail: 'input_noise_filler',
              status: disposition,
              disposition,
              source: 'squirrel_rime_commit_burst',
              type: 'user_final',
              ownerKind: 'user',
              ownerId: 'default',
              updatedAtMs: 1_900_000_100_020,
            }],
            nextCursor: '',
            limit: 50,
          };
        },
        'memory.source.disposition': (request: ControlRequest) => {
          expect(request.body).toEqual({
            sourceId: 'input-memory:42',
            disposition: 'pending',
          });
          disposition = 'pending';
          return { ok: true, changed: true };
        },
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('radio', { name: '证据' }));
    await user.click(await screen.findByRole('button', { name: /嗯嗯那个这个/ }));
    expect(screen.queryByText('编辑内容')).not.toBeInTheDocument();
    const workflow = screen.getByText('恢复证据').closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '恢复' }));

    await waitFor(() => expect(
      transport.requests.filter((call) => call.request.pathId === 'memory.source.disposition'),
    ).toHaveLength(1));
    expect(await screen.findByText('遗忘证据')).toBeInTheDocument();
  });

  it('loads bounded tag/group graphs and links keyboard node selection to accessible tables', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, pendingCompileEvents: 2 },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
        'memory.graph.get': (request: ControlRequest) => {
          const plane = String(request.query?.plane ?? '');
          const query = String(request.query?.query ?? '');
          if (plane === 'tags' && query === 'Memory') {
            return graphEnvelope(
              'tags',
              [graphNode('tag:memory', 'tag', 'Memory', 5, '记忆组织与检索')],
              [],
              false,
            );
          }
          if (plane === 'groups' && query) return graphEnvelope('groups', [], [], false);
          return memoryGraph(plane);
        },
        'memory.entity.get': (request: ControlRequest) => memoryEntity(
          String(request.params?.kind ?? ''),
          String(request.params?.entityId ?? ''),
        ),
      },
    });
    renderMemory(transport);

    expect(await screen.findByRole('heading', { name: '记忆', level: 1 })).toBeInTheDocument();
    await user.click(await screen.findByRole('tab', { name: '关系索引' }));
    expect(await screen.findByText(/共 2 项 · 1 条关系/)).toBeInTheDocument();
    expect(screen.getByText('还有更多关系未显示')).toBeInTheDocument();

    await waitFor(() => {
      const graphRequests = transport.requests.filter((call) =>
        call.request.pathId === 'memory.graph.get');
      expect(graphRequests).toHaveLength(2);
      for (const call of graphRequests) {
        expect(call.request.query).toMatchObject({ depth: 1, minWeight: 0 });
      }
    });

    const memoryNode = screen.getByRole('button', { name: /Memory，5 条记忆/ });
    fireEvent.keyDown(memoryNode, { key: 'Enter' });
    expect(screen.getByRole('heading', { name: 'Memory', level: 3 })).toBeInTheDocument();
    await waitFor(() => {
      expect(transport.requests.some((call) =>
        call.request.pathId === 'memory.graph.get'
        && call.request.query?.plane === 'tags'
        && call.request.query?.focusId === 'memory')).toBe(true);
    });
    expect(within(screen.getByRole('complementary', { name: '标签节点列表' })).queryByText('Group only')).not.toBeInTheDocument();
    const memoryDetails = screen.getByRole('region', { name: 'Memory 详情' });
    expect(await within(memoryDetails).findByText('已存关系')).toBeInTheDocument();
    expect(await within(memoryDetails).findByRole('button', { name: 'Agent Runtime' })).toBeInTheDocument();
    expect(within(memoryDetails).getAllByText('本地记忆').length).toBeGreaterThan(0);

    await user.type(screen.getByRole('textbox', { name: '筛选分组或标签' }), 'Memory');
    await waitFor(() => {
      expect(within(screen.getByRole('complementary', { name: '标签节点列表' })).getAllByRole('button')).toHaveLength(1);
      expect(transport.requests.some((call) =>
        call.request.pathId === 'memory.graph.get'
        && call.request.query?.plane === 'tags'
        && call.request.query?.query === 'Memory'
        && !call.request.query?.focusId)).toBe(true);
    });
    await user.clear(screen.getByRole('textbox', { name: '筛选分组或标签' }));

    await user.click(screen.getByRole('radio', { name: '分组 / 标签' }));
    expect(within(screen.getByRole('complementary', { name: '分组与标签列表' })).getByText('Group only')).toBeInTheDocument();
    const groupNode = screen.getByRole('button', { name: /分组 Agent 工程，12 个成员/ });
    await user.click(groupNode);
    await waitFor(() => {
      expect(transport.requests.some((call) =>
        call.request.pathId === 'memory.graph.get'
        && call.request.query?.plane === 'groups'
        && call.request.query?.focusId === 'agent')).toBe(true);
    });
    const groupDetails = screen.getByRole('region', { name: 'Agent 工程 详情' });
    expect(await within(groupDetails).findByText(/成员 · 当前 2 \/ 12/)).toBeInTheDocument();
    expect(within(groupDetails).getAllByRole('button', { name: 'Agent Runtime' }).length).toBeGreaterThan(0);

    await user.click(screen.getByRole('radio', { name: '分组 / 主题书' }));
    const bookList = screen.getByRole('complementary', { name: '分组与主题书列表' });
    expect(within(bookList).getByText('输入法知识册')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /主题书 输入法知识册，6 条记忆/ }));
    const bookDetails = screen.getByRole('region', { name: '输入法知识册 详情' });
    expect(await within(bookDetails).findByText('候选与上下文')).toBeInTheDocument();
    expect(within(bookDetails).getByText('为保护原始记忆内容，此处只显示成员计数。')).toBeInTheDocument();
    const relationFilter = screen.getByRole('textbox', { name: '筛选分组或标签' });
    await user.type(relationFilter, '不存在的主题');
    expect(await screen.findByText('当前筛选没有匹配分组或主题书。')).toBeInTheDocument();
    await user.clear(relationFilter);

    await waitFor(() => {
      const entityRequests = transport.requests.filter((call) => call.request.pathId === 'memory.entity.get');
      expect(entityRequests.length).toBeGreaterThanOrEqual(2);
      const bookRequest = entityRequests.find((call) =>
        call.request.params?.kind === 'book' && call.request.params?.entityId === 'book:input');
      expect(bookRequest?.request.query).toMatchObject({ connectionsLimit: 40, membersLimit: 40 });
    });
  });

  it('searches the full backend graph instead of filtering only the first response', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 2, memoryItemCount: 2, memoryBookCount: 0, memoryAtomCount: 0, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'memory.graph.get': (request: ControlRequest) => {
          const plane = String(request.query?.plane ?? '');
          const query = String(request.query?.query ?? '');
          if (plane === 'tags') {
            const node = query
              ? graphNode('tag:remote', 'tag', '远端标签', 7, '不在首批响应中')
              : graphNode('tag:first', 'tag', '首批标签', 1, '首批响应');
            return graphEnvelope('tags', [node], [], false);
          }
          const group = query
            ? graphNode('group:remote', 'group', '远端分组', 9, '不在首批响应中')
            : graphNode('group:first', 'group', '首批分组', 1, '首批响应');
          return graphEnvelope('groups', [group], [], false);
        },
        'memory.entity.get': (request: ControlRequest) => memoryEntity(
          String(request.params?.kind ?? ''),
          String(request.params?.entityId ?? ''),
        ),
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '关系索引' }));
    expect(await screen.findByRole('button', { name: /首批标签，1 条记忆/ })).toBeInTheDocument();
    const search = screen.getByRole('textbox', { name: '筛选分组或标签' });
    await user.type(search, '远端标签');
    expect(await screen.findByRole('button', { name: /远端标签，7 条记忆/ })).toBeInTheDocument();
    await waitFor(() => {
      expect(transport.requests.some((call) =>
        call.request.pathId === 'memory.graph.get'
        && call.request.query?.plane === 'tags'
        && call.request.query?.query === '远端标签')).toBe(true);
    });

    await user.clear(search);
    await user.click(screen.getByRole('radio', { name: '分组 / 标签' }));
    await user.type(search, '远端分组');
    expect(await screen.findByRole('button', { name: /分组 远端分组，9 个成员/ })).toBeInTheDocument();
    await waitFor(() => {
      expect(transport.requests.some((call) =>
        call.request.pathId === 'memory.graph.get'
        && call.request.query?.plane === 'groups'
        && call.request.query?.query === '远端分组')).toBe(true);
    });
  });

  it('isolates tag and group failures and never exposes a transport error', async () => {
    const user = userEvent.setup();
    const internal = '/Users/private/memory.sqlite GET /api/memory/graph traceback';
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 1, memoryItemCount: 1, memoryBookCount: 0, memoryAtomCount: 0, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'memory.graph.get': (request: ControlRequest) => {
          if (request.query?.plane === 'tags') return Promise.reject(new Error(internal));
          return memoryGraph('groups');
        },
        'memory.entity.get': (request: ControlRequest) => memoryEntity(
          String(request.params?.kind ?? ''),
          String(request.params?.entityId ?? ''),
        ),
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '关系索引' }));
    expect(await screen.findByText('读取失败')).toBeInTheDocument();
    expect(screen.getByText('当前关系读取失败，请稍后重试。')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(internal);

    await user.click(screen.getByRole('radio', { name: '分组 / 标签' }));
    expect(await screen.findByRole('button', { name: /分组 Agent 工程，12 个成员/ })).toBeInTheDocument();
    expect(screen.queryByText('读取失败')).not.toBeInTheDocument();
  });

  it('keeps tag relations usable when the group route fails', async () => {
    const user = userEvent.setup();
    const internal = 'sqlite traceback /api/memory/graph groups';
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 1, memoryItemCount: 1, memoryBookCount: 0, memoryAtomCount: 0, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'memory.graph.get': (request: ControlRequest) => {
          if (request.query?.plane === 'groups') return Promise.reject(new Error(internal));
          return graphEnvelope(
            'tags',
            [graphNode('tag:solo', 'tag', '可用标签', 1, '标签路由正常')],
            [],
            false,
          );
        },
        'memory.entity.get': () => memoryEntity('tag', 'solo'),
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '关系索引' }));
    expect(await screen.findByRole('button', { name: /可用标签，1 条记忆/ })).toBeInTheDocument();
    expect(screen.queryByText('读取失败')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(internal);

    await user.click(screen.getByRole('radio', { name: '分组 / 标签' }));
    expect(await screen.findByText('读取失败')).toBeInTheDocument();
    expect(screen.getByText('当前关系读取失败，请稍后重试。')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(internal);
  });

  it('loads additional connection and member pages from their real cursors', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 1, memoryItemCount: 5, memoryBookCount: 0, memoryAtomCount: 0, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'memory.graph.get': (request: ControlRequest) => request.query?.plane === 'tags'
          ? graphEnvelope('tags', [graphNode('tag:agent', 'tag', 'Agent Runtime', 5, 'Agent 生命周期与工具边界')], [], false)
          : graphEnvelope('groups', [], [], false),
        'memory.entity.get': pagedMemoryEntity,
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '关系索引' }));
    const details = await screen.findByRole('region', { name: 'Agent Runtime 详情' });
    const connectionSection = within(details).getByRole('heading', { name: '已存关系' }).closest('section');
    expect(connectionSection).not.toBeNull();
    await user.click(within(connectionSection as HTMLElement).getByRole('button', { name: '加载更多' }));
    expect(await within(connectionSection as HTMLElement).findByText('深入关系')).toBeInTheDocument();

    const memberSection = within(details).getByRole('heading', { name: /成员 · 当前 1 \/ 5/ }).closest('section');
    expect(memberSection).not.toBeNull();
    await user.click(within(memberSection as HTMLElement).getByRole('button', { name: '加载更多' }));
    expect(await within(memberSection as HTMLElement).findByText('成员二')).toBeInTheDocument();

    expect(transport.requests.some((call) =>
      call.request.pathId === 'memory.entity.get'
      && call.request.query?.connectionsCursor === '40')).toBe(true);
    expect(transport.requests.some((call) =>
      call.request.pathId === 'memory.entity.get'
      && call.request.query?.membersCursor === '40')).toBe(true);
  });

  it('shows isolated nodes without inventing an edge', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 1, memoryItemCount: 1, memoryBookCount: 0, memoryAtomCount: 0, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'memory.graph.get': (request: ControlRequest) => {
          const plane = String(request.query?.plane ?? '');
          return plane === 'tags'
            ? graphEnvelope('tags', [graphNode('tag:solo', 'tag', '孤立标签', 1, '没有边')], [], false)
            : graphEnvelope('groups', [], [], false);
        },
        'memory.entity.get': () => memoryEntity('tag', 'solo'),
      },
    });
    renderMemory(transport);
    await user.click(await screen.findByRole('tab', { name: '关系索引' }));
    expect(await screen.findByText('1 项记忆目前没有已记录关系。')).toBeInTheDocument();
    expect(document.querySelectorAll('.memory-graph__edge')).toHaveLength(0);
  });

  it('fails with public error copy and never renders internal memory fields', async () => {
    const user = userEvent.setup();
    const internal = '/Users/private/memory.sqlite SELECT prompt reasoning rawJson';
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 1, memoryItemCount: 1, memoryBookCount: 0, memoryAtomCount: 0, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'memory.graph.get': (request: ControlRequest) => {
          const plane = String(request.query?.plane ?? '');
          if (plane === 'groups') return graphEnvelope('groups', [], [], false);
          return graphEnvelope('tags', [
            graphNode('tag:solo', 'tag', '孤立标签', 1, '公开摘要'),
          ], [], false);
        },
        'memory.entity.get': () => Promise.reject(new Error(internal)),
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('tab', { name: '关系索引' }));
    expect(await screen.findByRole('heading', { name: '孤立标签', level: 3 })).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('实体详情读取失败，请稍后重试。');
    expect(document.body).not.toHaveTextContent(internal);
    expect(document.body).not.toHaveTextContent('reasoning');
    expect(document.body).not.toHaveTextContent('rawJson');
  });

  it('archives and rolls back a real topic book through the bound work contract', async () => {
    const user = userEvent.setup();
    const payloadSha256 = `sha256:${'c'.repeat(64)}`;
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': {
          ok: true,
          runtimeRevision: 7,
          eventCount: 18,
          memoryItemCount: 14,
          memoryBookCount: 4,
          memoryAtomCount: 10,
          pendingCompileEvents: 2,
        },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
        'memory.book.archive.preview': (request: ControlRequest) => {
          expect(request.body).toEqual({
            bookId: 'book-1',
            archived: true,
            reason: 'control_center_archive',
            expectedRuntimeRevision: 7,
          });
          return {
            schemaVersion: 'rag-ime.management-work-preview.v1',
            ok: true,
            previewToken: 'preview-memory-book',
            pathId: 'memory.book.archive.apply',
            payloadSha256,
            expectedRevision: { runtimeRevision: 7, subjectRevision: 'sha256:book-before' },
            expiresAtMs: Date.now() + 60_000,
            requiredConfirm: 'apply',
            summary: {
              title: '归档主题记忆',
              items: ['主题：控制中心迁移', '归档后退出日常自动召回。'],
              risk: 'R2',
            },
          };
        },
        'memory.book.archive.apply': (request: ControlRequest) => {
          expect(request.body).toMatchObject({
            bookId: 'book-1',
            archived: true,
            reason: 'control_center_archive',
            expectedRuntimeRevision: 7,
            previewToken: 'preview-memory-book',
            payloadSha256,
            confirmText: 'apply',
          });
          return workReceipt('memory.book.archive.apply', payloadSha256, true);
        },
        'memory.book.archive.rollback': (request: ControlRequest) => {
          expect(request.body).toEqual({
            receiptId: 'receipt-memory-book',
            rollbackToken: 'rollback-memory-book',
            payloadSha256,
            confirmText: 'rollback',
          });
          return workReceipt('memory.book.archive.rollback', payloadSha256, false);
        },
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('radio', { name: '主题书' }));
    const book = await screen.findByRole('button', { name: /控制中心迁移/ });
    await user.click(book);
    const details = screen.getByRole('region', { name: '控制中心迁移 详情' });
    expect(within(details).getByText('React 页面与受控接口')).toBeInTheDocument();
    expect(screen.queryByText('book-1')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '预览操作' }));
    expect(await screen.findByText('主题：控制中心迁移')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '进入确认' }));
    await user.click(screen.getByRole('checkbox', { name: '只执行上方已绑定的变更' }));
    await user.click(screen.getByRole('button', { name: '确认并应用' }));
    expect(await screen.findByText('已应用')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '撤销这次操作' }));
    expect(await screen.findByText('已撤销')).toBeInTheDocument();

    expect(transport.requests.filter((call) => call.request.pathId === 'memory.book.archive.preview')).toHaveLength(1);
    expect(transport.requests.filter((call) => call.request.pathId === 'memory.book.archive.apply')).toHaveLength(1);
    expect(transport.requests.filter((call) => call.request.pathId === 'memory.book.archive.rollback')).toHaveLength(1);
  });

  it('fails closed without archive routes and does not show an implementation placeholder', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      capabilities: {
        routeIds: ['memory.summary', 'memory.pages', 'memory.graph.get', 'memory.entity.get'],
      },
      routes: {
        'memory.summary': {
          ok: true,
          runtimeRevision: 7,
          eventCount: 18,
          memoryItemCount: 14,
          memoryBookCount: 4,
          memoryAtomCount: 10,
          pendingCompileEvents: 2,
        },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('radio', { name: '主题书' }));
    await user.click(await screen.findByRole('button', { name: /控制中心迁移/ }));
    expect(await screen.findAllByRole('button', { name: '暂未开放' })).not.toHaveLength(0);
    expect(screen.queryByText('后端暂不支持')).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId.startsWith('memory.book.archive.'))).toBe(false);
  });
});

function renderMemory(transport: MockControlTransport, initialEntry = '/') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}>
            <MemoryFeature />
          </QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
}

function activityTimeline(status: string, date: string): Record<string, unknown> {
  const [year, month, day] = date.split('-').map(Number);
  const start = new Date(year, month - 1, day, 9, 0).getTime();
  const segment = (position: number, app: string, summary: string) => ({
    segmentId: `segment:${position}`,
    position,
    app,
    sourceKinds: ['squirrel_input_segment', 'pi_agent'],
    contextGroupIds: ['group:personal-context'],
    startMs: start + position * 3_600_000,
    endMs: start + (position + 1) * 3_600_000,
    eventCount: 4,
    sourceEventIds: [position + 1],
    sourceEventHash: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    summary,
    redactedEventCount: 0,
  });
  return {
    schemaVersion: 'rag-ime.daily-activity-timeline.v1',
    timelineId: `timeline:${date}`,
    project: 'wisdom-weasel-rag-ime',
    date,
    timezone: 'Asia/Shanghai',
    status,
    sourceEventIds: [1, 2],
    sourceEventHash: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    segments: [
      segment(0, 'com.openai.codex', '实现最终输入框捕获并核对三条记忆消费路径。'),
      segment(1, 'com.mitchellh.ghostty', '运行后端、Web 与输入法验证。'),
    ],
    summary: '当天完成个人上下文主链改造与验证。',
    eventCount: 8,
    segmentCount: 2,
    approvedBookId: '',
    approvedBy: status === 'approved' ? 'control-center-user' : '',
    approvedAtMs: status === 'approved' ? start + 10_000 : 0,
    createdAtMs: start,
    updatedAtMs: start + 20_000,
    policy: {
      derivedFromInputEvents: true,
      longTermFact: false,
      automaticPromotion: true,
      explicitApprovalRequired: false,
    },
  };
}

function localCalendarDate(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function memoryCurationStatus(): Record<string, unknown> {
  return {
    ok: true,
    policy: 'review',
    autoApply: false,
    pendingDraftCount: 1,
    runs: [{ runId: 'memory_book_test', status: 'draft', diffCount: 2, createdAtMs: 1_784_006_400_000 }],
  };
}

function memoryCurationRun(): Record<string, unknown> {
  return {
    ok: true,
    stale: false,
    canApply: true,
    canRollback: false,
    run: {
      runId: 'memory_book_test',
      status: 'draft',
      createdAtMs: 1_784_006_400_000,
      diffCount: 2,
      pendingDiffCount: 1,
      changes: [
        {
          diffId: 1,
          operation: 'upsert_memory_atom',
          operationLabel: '更新记忆条目',
          status: 'pending',
          selected: true,
          title: '输入封口边界',
          detail: 'Backspace 修改缓冲区，Enter 后才写入完整段落。',
          sourceCount: 3,
        },
        {
          diffId: 2,
          operation: 'merge_semantic_tag',
          operationLabel: '合并标签',
          status: 'rejected',
          selected: false,
          title: '合并输入法同义标签',
          detail: '保留用户命名作为别名。',
          sourceCount: 2,
        },
      ],
    },
  };
}

function memoryGraph(plane: string): Record<string, unknown> {
  const tagAgent = graphNode('tag:agent', 'tag', 'Agent Runtime', 11, 'Agent 生命周期与工具边界');
  const tagMemory = graphNode('tag:memory', 'tag', 'Memory', 5, '记忆组织与检索');
  if (plane === 'tags') {
    return graphEnvelope('tags', [tagAgent, tagMemory], [{
      id: 'edge:agent-memory',
      kind: 'tagRelation',
      sourceId: 'tag:agent',
      targetId: 'tag:memory',
      sourceKind: 'tag',
      targetKind: 'tag',
      relation: 'related_to',
      weight: 0.9,
      directionBias: 0,
      evidenceCount: 6,
      source: 'sqlite',
      updatedAtMs: 1,
    }], true);
  }
  const groupOnly = graphNode('tag:group-only', 'tag', 'Group only', 3, '只由 Group plane 返回');
  const book = graphNode('book:input', 'book', '输入法知识册', 6, '候选与上下文');
  return graphEnvelope(
    'groups',
    [graphNode('group:agent', 'group', 'Agent 工程', 12, 'Agent 陪伴与恢复'), tagAgent, tagMemory, groupOnly, book],
    [...[tagAgent, tagMemory, groupOnly].map((tag) => ({
      id: `membership:${String(tag.id)}`,
      kind: 'groupMember',
      sourceId: 'group:agent',
      targetId: tag.id,
      sourceKind: 'group',
      targetKind: 'tag',
      relation: 'contains',
      weight: 1,
      directionBias: 0,
      evidenceCount: 1,
      source: 'sqlite',
      updatedAtMs: 1,
    })), {
      id: 'membership:book:input',
      kind: 'groupMember',
      sourceId: 'group:agent',
      targetId: book.id,
      sourceKind: 'group',
      targetKind: 'book',
      relation: 'contains',
      weight: .8,
      directionBias: 1,
      evidenceCount: 1,
      source: 'sqlite',
      updatedAtMs: 1,
    }],
    false,
  );
}

function graphEnvelope(
  plane: 'tags' | 'groups',
  nodes: Record<string, unknown>[],
  edges: Record<string, unknown>[],
  truncated: boolean,
): Record<string, unknown> {
  return {
      schemaVersion: 'rag-ime.memory-graph.v1',
    ok: true,
    settingsRevision: 'settings:test',
    runtimeRevision: 1,
    graphRevision: `sha256:${'a'.repeat(64)}`,
    plane,
    project: 'wisdom-weasel-rag-ime',
    filters: { status: 'active', query: '', focusId: '', minWeight: 0 },
    nodes,
    edges,
    truncated: { nodes: truncated, edges: false },
    limits: { nodeLimit: 80, edgeLimit: 160, depth: 1 },
  };
}

function graphNode(
  id: string,
  kind: 'tag' | 'group' | 'book',
  label: string,
  memberCount: number,
  description: string,
): Record<string, unknown> {
  return {
    id,
    entityId: kind === 'book' ? id : id.split(':').at(-1),
    kind,
    label,
    description,
    color: kind === 'group' ? 'blue' : 'teal',
    status: 'active',
    source: 'sqlite',
    project: 'wisdom-weasel-rag-ime',
    qualityScore: 1,
    memberCount,
    edgeCount: 1,
    updatedAtMs: 1,
  };
}

function memoryPage(kind: string): Record<string, unknown> {
  if (kind === 'tags') {
    return {
      ok: true,
      items: [
        {
          id: 'tag-agent',
          tag: 'Agent Runtime',
          description: 'Agent 生命周期与工具边界',
          item_count: 11,
          edge_count: 1,
          color_token: 'teal',
          connections: [{ id: 'tag-memory', tag: 'Memory', type: 'related_to', weight: 0.9, evidenceCount: 6 }],
        },
        {
          id: 'tag-memory',
          tag: 'Memory',
          description: '记忆组织与检索',
          item_count: 5,
          edge_count: 1,
          color_token: 'green',
          connections: [{ id: 'tag-agent', tag: 'Agent Runtime', type: 'related_to', weight: 0.9, evidenceCount: 6 }],
        },
      ],
      nextCursor: 'tag-next',
      limit: 50,
    };
  }
  if (kind === 'groups') {
    return {
      ok: true,
      items: [
        {
          id: 'group:agent',
          title: 'Agent 工程',
          note: 'Agent 陪伴与恢复',
          tags: ['Agent Runtime', 'Memory'],
          event_count: 12,
          color_token: 'blue',
        },
      ],
      nextCursor: '',
      limit: 50,
    };
  }
  return {
    ok: true,
    items: [{
      id: 'book-1',
      type: 'topic',
      title: '控制中心迁移',
      summary: 'React 页面与受控接口',
      status: 'active',
      source: 'dsv4',
      tags: ['控制中心', '迁移'],
      updatedAtMs: 1_900_000_100_020,
    }],
    nextCursor: '',
    limit: 50,
  };
}

function workReceipt(pathId: string, payloadSha256: string, rollbackAvailable: boolean) {
  return {
    schemaVersion: 'rag-ime.management-work-receipt.v1',
    ok: true,
    receiptId: pathId.endsWith('rollback') ? 'receipt-memory-book-rollback' : 'receipt-memory-book',
    pathId,
    payloadSha256,
    appliedAtMs: Date.now(),
    auditId: 11,
    rollbackAvailable,
    rollbackToken: rollbackAvailable ? 'rollback-memory-book' : '',
    rollbackAuthority: { bookId: 'book-1' },
    restartComponents: [],
    result: { status: pathId.endsWith('rollback') ? 'active' : 'archived' },
  };
}

function memoryEntity(kind: string, entityId: string): Record<string, unknown> {
  const isGroup = kind === 'group';
  const isBook = kind === 'book';
  const label = isGroup ? 'Agent 工程' : isBook ? '输入法知识册' : entityId === 'memory' ? 'Memory' : entityId === 'solo' ? '孤立标签' : 'Agent Runtime';
  const node = graphNode(`${kind}:${entityId}`, isGroup ? 'group' : isBook ? 'book' : 'tag', label, isGroup ? 12 : isBook ? 6 : 5, isBook ? '候选与上下文' : `${label} detail`);
  const relatedTag = graphNode('tag:agent', 'tag', 'Agent Runtime', 11, 'Agent 生命周期与工具边界');
  const relatedMemory = graphNode('tag:memory', 'tag', 'Memory', 5, '记忆组织与检索');
  const connections = isGroup || entityId === 'solo' ? [] : isBook ? [{
    node: graphNode('group:agent', 'group', 'Agent 工程', 12, 'Agent 陪伴与恢复'),
    edge: entityEdge('group-member:book', 'groupMember', 'group:agent', 'book:book:input', 'contains'),
  }] : [{
    node: entityId === 'memory' ? relatedTag : relatedMemory,
    edge: entityEdge('tag-relation:test', 'tagRelation', `tag:${entityId}`, entityId === 'memory' ? 'tag:agent' : 'tag:memory', 'related_to'),
  }];
  const members = isGroup ? [relatedTag, relatedMemory].map((member) => ({
    node: member,
    edge: entityEdge(`group-member:${String(member.id)}`, 'groupMember', 'group:agent', String(member.id), 'contains'),
  })) : [];
  return {
    schemaVersion: 'rag-ime.memory-entity.v1',
    ok: true,
    settingsRevision: 'settings:test',
    runtimeRevision: 1,
    kind,
    entityId,
    entityRevision: `sha256:${'b'.repeat(64)}`,
    project: 'wisdom-weasel-rag-ime',
    entity: node,
    attributes: { type: isGroup ? 'semantic' : isBook ? 'topic' : 'concept', aliases: isGroup || isBook ? [] : ['记忆'], tags: isBook ? ['输入法'] : [] },
    connections: { items: connections, nextCursor: '', limit: 40, hasMore: false },
    members: { items: members, nextCursor: '', limit: 40, hasMore: false },
    limits: { connectionsLimit: 40, membersLimit: 40 },
  };
}

function pagedMemoryEntity(request: ControlRequest): Record<string, unknown> {
  const kind = String(request.params?.kind ?? 'tag');
  const entityId = String(request.params?.entityId ?? 'agent');
  const payload = memoryEntity(kind, entityId);
  const connectionsCursor = String(request.query?.connectionsCursor ?? '');
  const membersCursor = String(request.query?.membersCursor ?? '');
  const relatedMemory = graphNode('tag:memory', 'tag', 'Memory', 5, '记忆组织与检索');
  const deepRelation = graphNode('tag:deep', 'tag', '深入关系', 3, '第二页关系');
  const memberOne = graphNode('tag:member-one', 'tag', '成员一', 1, '第一页成员');
  const memberTwo = graphNode('tag:member-two', 'tag', '成员二', 1, '第二页成员');

  if (connectionsCursor) {
    payload.connections = {
      items: [{
        node: deepRelation,
        edge: entityEdge('tag-relation:deep', 'tagRelation', 'tag:agent', 'tag:deep', 'related_to'),
      }],
      nextCursor: '',
      limit: 40,
      hasMore: false,
    };
    payload.members = { items: [], nextCursor: '', limit: 1, hasMore: false };
    return payload;
  }
  if (membersCursor) {
    payload.connections = { items: [], nextCursor: '', limit: 1, hasMore: false };
    payload.members = {
      items: [{
        node: memberTwo,
        edge: entityEdge('tag-member:two', 'groupMember', 'group:test', 'tag:member-two', 'contains'),
      }],
      nextCursor: '',
      limit: 40,
      hasMore: false,
    };
    return payload;
  }

  payload.connections = {
    items: [{
      node: relatedMemory,
      edge: entityEdge('tag-relation:memory', 'tagRelation', 'tag:agent', 'tag:memory', 'related_to'),
    }],
    nextCursor: '40',
    limit: 40,
    hasMore: true,
  };
  payload.members = {
    items: [{
      node: memberOne,
      edge: entityEdge('tag-member:one', 'groupMember', 'group:test', 'tag:member-one', 'contains'),
    }],
    nextCursor: '40',
    limit: 40,
    hasMore: true,
  };
  return payload;
}

function entityEdge(id: string, kind: 'tagRelation' | 'groupMember', sourceId: string, targetId: string, relation: string) {
  return {
    id,
    kind,
    sourceId,
    targetId,
    sourceKind: kind === 'groupMember' ? 'group' : 'tag',
    targetKind: 'tag',
    relation,
    weight: .9,
    directionBias: 0,
    evidenceCount: 2,
    source: 'sqlite',
    updatedAtMs: 1,
  };
}
