import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { MemoryFeature } from './index';

afterEach(() => {
  cleanup();
  window.history.replaceState(null, '', '/');
});

describe('MemoryFeature relations', () => {
  it('keeps the personal knowledge workbench under the third memory tab', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 3, memoryItemCount: 2, memoryBookCount: 1, memoryAtomCount: 1, pendingCompileEvents: 0 },
        'memory.pages': { ok: true, items: [], nextCursor: '', limit: 50 },
        'knowledge.routeStatus': {
          ok: true,
          deepseekReady: true,
          modes: ['knowledge_answer', 'organize_database'],
          streaming: { knowledgeWorkbench: true },
          deepseekRoute: { remoteReady: true, passivePostCommitRemoteAllowed: false },
          notion: { ready: false, submitConfigured: false, pollConfigured: false },
        },
      },
    });
    renderMemory(transport);

    expect(await screen.findByRole('heading', { name: '记忆', level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '个人知识整理' })).not.toBeInTheDocument();
    await user.click(await screen.findByRole('tab', { name: '整理' }));
    expect(await screen.findByRole('heading', { name: '个人知识整理', level: 2 })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('输入一个明确的知识任务')).toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId === 'knowledge.routeStatus')).toBe(true);
  });

  it('uses the live tag field as the catalog title', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({
      routes: {
        'memory.summary': { ok: true, eventCount: 18, memoryItemCount: 14, memoryBookCount: 4, memoryAtomCount: 10, pendingCompileEvents: 2 },
        'memory.pages': (request: ControlRequest) => memoryPage(String(request.params?.kind ?? '')),
      },
    });
    renderMemory(transport);

    await user.click(await screen.findByRole('radio', { name: '标签' }));
    expect(screen.getByRole('heading', { name: '标签节点目录', level: 2 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '查看标签图谱' })).toBeInTheDocument();
    expect((await screen.findAllByText('Agent Runtime')).length).toBeGreaterThan(0);
    expect(screen.getByText('Agent 生命周期与工具边界')).toBeInTheDocument();
  });

  it('opens the real tag graph directly from the tag catalog projection', async () => {
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

    await user.click(await screen.findByRole('radio', { name: '标签' }));
    await user.click(screen.getByRole('button', { name: '查看标签图谱' }));

    expect(await screen.findByRole('heading', { name: '记忆关系', level: 2 })).toBeInTheDocument();
    expect(await screen.findByRole('group', { name: '标签当前页局部关系图' })).toBeInTheDocument();
    await waitFor(() => expect(transport.requests.some((call) =>
      call.request.pathId === 'memory.graph.get'
      && call.request.query?.plane === 'tags')).toBe(true));
  });

  it('edits the selected stable id directly and keeps bulk organization as an Agent draft', async () => {
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

    const organizeWorkflow = screen.getByText('整理记忆').closest('.mgmt-workflow');
    expect(organizeWorkflow).not.toBeNull();
    await user.click(within(organizeWorkflow as HTMLElement).getByRole('button', { name: '交给智鼬' }));
    expect(decodeURIComponent(window.location.hash)).toContain('生成一份去重、合并、归档与标签调整草案');
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
    await user.click(await screen.findByRole('tab', { name: '关系图' }));
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

    await user.click(await screen.findByRole('tab', { name: '关系图' }));
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

    await user.click(await screen.findByRole('tab', { name: '关系图' }));
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

    await user.click(await screen.findByRole('tab', { name: '关系图' }));
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

    await user.click(await screen.findByRole('tab', { name: '关系图' }));
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
    await user.click(await screen.findByRole('tab', { name: '关系图' }));
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

    await user.click(await screen.findByRole('tab', { name: '关系图' }));
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

    await user.click(await screen.findByRole('button', { name: /控制中心迁移/ }));
    expect(await screen.findAllByRole('button', { name: '暂未开放' })).not.toHaveLength(0);
    expect(screen.queryByText('后端暂不支持')).not.toBeInTheDocument();
    expect(transport.requests.some((call) => call.request.pathId.startsWith('memory.book.archive.'))).toBe(false);
  });
});

function renderMemory(transport: MockControlTransport) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter>
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
