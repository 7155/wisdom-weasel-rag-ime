import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  ProjectFieldFeature,
  projectFieldCameraCenterXForViewport,
  projectFieldInitialCamera,
  projectFieldText,
  projectFieldShouldReduceMotion,
} from './index';
import { projectFieldProjects } from './prototype-data';
import { personalAgentProjectFieldProjection } from './reconstructed-personal-agent-project';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';

describe('Project Field prototype', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    delete document.documentElement.dataset.reduceMotion;
  });

  it('projects eight outcome Rooms reconstructed from documents and primary Agent sessions', () => {
    const { container } = render(<ProjectFieldFeature />);

    expect(screen.getByRole('heading', { name: '个人助手工作台 项目场' })).toBeInTheDocument();
    const projectIdentity = container.querySelector('.project-field__identity strong');
    expect(projectIdentity).not.toHaveAttribute('aria-label');
    expect(projectIdentity).toHaveAttribute('title', '个人助手工作台');
    expect(projectIdentity?.querySelector('.project-field__identity-name--full')).toHaveTextContent('个人助手工作台');
    expect(projectIdentity?.querySelector('.project-field__identity-name--compact')).toHaveTextContent('个人助手工作台');
    expect(screen.getByLabelText('已根据本机资料整理')).toBeInTheDocument();
    expect(screen.getByText('交互预览')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-room-id]')).toHaveLength(8);
    const currentRoom = screen.getByRole('button', { name: '协作导航与项目图谱，当前协作目标' });
    expect(currentRoom).toBeInTheDocument();
    expect(within(currentRoom).getByText('需求')).toBeInTheDocument();
    expect(within(currentRoom).getByText(/八个正确的结果型协作目标/)).toBeInTheDocument();
    expect(within(currentRoom).queryByText('验收')).not.toBeInTheDocument();
    expect(within(currentRoom).queryByText(/每个 Room 在未展开时就能说明/)).not.toBeInTheDocument();
    expect(within(currentRoom).getByText('查看详情')).toBeInTheDocument();
    const currentProgress = within(currentRoom).getByRole('progressbar', { name: /验收证据进度：/ });
    expect(currentProgress).toHaveAttribute('aria-valuemin', '0');
    expect(currentProgress).toHaveAttribute('aria-valuemax', '6');
    expect(currentProgress).toHaveAttribute('aria-valuenow', '5');
    expect(currentProgress).toHaveTextContent('证据 5/6');
    expect(currentProgress.querySelector('.room-requirement-card__progress-fill')).toBeInTheDocument();
    expect(within(currentRoom).queryByRole('list', { name: /交付进度/ })).not.toBeInTheDocument();
    expect(within(currentRoom).getByText('实现中')).toBeInTheDocument();
    expect(screen.queryByLabelText('在当前协作目标继续')).not.toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: '航线图例' })).not.toBeInTheDocument();
    expect(currentRoom.closest('.room-island')).toHaveAttribute('data-surface', 'paper');
    expect(currentRoom.closest('.room-island')).toHaveAttribute('data-layout', 'timeline-paper');
    expect(currentRoom.closest('.room-island')?.querySelector('.room-island__terrain')).not.toBeInTheDocument();
    const backgroundRoom = screen.getByRole('button', { name: '统一产品工作台，实现中' });
    expect(within(backgroundRoom).getByRole('progressbar', { name: /验收证据进度：/ })).toHaveTextContent('证据 2/3');
    expect(within(backgroundRoom).queryByRole('list', { name: /交付进度/ })).not.toBeInTheDocument();
    expect(backgroundRoom.closest('.room-island')).toHaveAttribute('data-surface', 'paper');
    expect(container).not.toHaveTextContent('汇聚门');
    expect(currentRoom.closest('.room-island')).toHaveAttribute('data-wayfinder', 'true');
    expect(container.querySelectorAll('.room-island[data-wayfinder="true"]')).toHaveLength(7);
    expect(container.querySelectorAll('.room-island[data-layout="timeline-paper"]')).toHaveLength(7);
    const releaseLane = screen.getByRole('button', { name: /真实使用与发布长期验收/ });
    expect(releaseLane).toBeInTheDocument();
    expect(within(releaseLane).getByText('把已实现能力推进成可安装、可验证、可恢复并能公开交付的真实产品。')).toBeVisible();
    expect(screen.queryByLabelText('项目演化时间轴')).not.toBeInTheDocument();
    expect(container).not.toHaveTextContent(/7 月 1 日|8 月 4 日以后|07\.01|08\.04/);
    expect(screen.getAllByRole('progressbar')).toHaveLength(8);
    expect(container.querySelector('.project-field__map-viewport')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '放大画布' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '缩小画布' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '复位当前视图' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'AI 工程实验室' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '现有工作台' })).toHaveAttribute('href', '#/agent');
    expect(screen.getByRole('link', { name: '设置' })).toHaveAttribute('href', '#/configuration');
    expect(container).not.toHaveTextContent(/\b(?:Issue|Ticket|Spec)\b/i);
  });

  it('opens the current project as a PAWOS entity window without changing projects', async () => {
    const user = userEvent.setup();
    const requests: unknown[] = [];
    render(
      <PawOsDesktopProvider openWindow={(request) => requests.push(request)}>
        <ProjectFieldFeature />
      </PawOsDesktopProvider>,
    );

    await user.click(screen.getByRole('button', { name: '在独立窗口中打开当前项目' }));

    expect(requests).toEqual([{
      appId: 'project-workbench',
      target: expect.objectContaining({
        kind: 'project',
        id: 'personal-agent-workbench',
        title: '个人助手工作台',
      }),
    }]);
    expect(screen.getByRole('heading', { name: '个人助手工作台 项目场' })).toBeInTheDocument();
  });

  it('shows a branching start and an explicitly unreached destination without process copy', () => {
    const { container } = render(<ProjectFieldFeature />);

    expect(screen.getByText('可靠的 macOS AI 输入辅助')).toBeInTheDocument();
    expect(screen.getByText('可持续交付的个人助手工作台')).toBeInTheDocument();
    expect(screen.getByLabelText('项目目的地：尚未抵达')).toHaveTextContent('全部必需协作目标通过质量检查、独立复核与用户验收后连接。');
    expect(container.querySelector('.project-field__origin')).toHaveAttribute('data-surface', 'paper');
    expect(container.querySelector('.project-field__destination')).toHaveAttribute('data-surface', 'paper');
    expect(screen.queryByRole('region', { name: '统一产品架构' })).not.toBeInTheDocument();
    expect(screen.queryByText(/仍在迷雾中|模拟技能|当前前沿/)).not.toBeInTheDocument();
  });

  it('keeps the real reconstruction source contract bounded and internally consistent', () => {
    const project = projectFieldProjects.find((candidate) => candidate.id === 'personal-agent-workbench');
    const sources = project?.rooms.flatMap((room) => room.sources ?? []) ?? [];
    const uniqueSources = new Map(sources.map((source) => [source.id, source]));

    expect(project?.reconstruction).toMatchObject({
      label: '真实资料回顾重建',
      sourceCounts: { projectDocuments: 7, agentSessions: 12, gitCommits: 16 },
      projection: {
        state: 'verified-local-evidence',
        schemaVersion: 'personal-agent.project-field-projection.v1',
        gitHead: '8a50a6b21ced9edb1a46b1cb4dc2b004ba0ee771',
      },
    });
    expect(project?.compactTitle).toBe('个人助手工作台');
    expect(personalAgentProjectFieldProjection.privacy).toEqual({
      rawChatIncluded: false,
      toolResultsIncluded: false,
      assistantReasoningIncluded: false,
      absolutePathsIncluded: false,
    });
    expect([...uniqueSources.values()].filter((source) => source.kind === 'project-document')).toHaveLength(7);
    expect([...uniqueSources.values()].filter((source) => source.kind === 'agent-session')).toHaveLength(12);
    expect([...uniqueSources.values()].filter((source) => source.kind === 'git-commit')).toHaveLength(16);
    expect(sources.every((source) => !source.ref.includes('/Users/'))).toBe(true);
  });

  it('presents projection progress as a dated record rather than a live control', async () => {
    const user = userEvent.setup();
    render(<ProjectFieldFeature />);

    await user.click(screen.getByRole('button', { name: '协作导航与项目图谱，当前协作目标' }));
    const workspace = screen.getByRole('article', { name: '协作导航与项目图谱协作目标工作区' });

    expect(workspace).toHaveTextContent('资料中的最近进展');
    expect(workspace).toHaveTextContent('资料中记录的下一步');
    expect(within(workspace).queryByLabelText('继续推进这个目标')).not.toBeInTheDocument();
    expect(within(workspace).queryByRole('button', { name: '更新预览说明' })).not.toBeInTheDocument();
  });

  it('uses one map view without a redundant view switcher', () => {
    const { container } = render(<ProjectFieldFeature />);

    const viewport = container.querySelector('.project-field__viewport');
    expect(screen.queryByRole('button', { name: '当前航程' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '完整全景' })).not.toBeInTheDocument();
    expect(viewport).toHaveAttribute('data-mode', 'route');
    expect(screen.getByRole('group', { name: '画布控制' })).toBeInTheDocument();
  });

  it('opens the reconstructed project on the current voyage and its destination', () => {
    const project = projectFieldProjects.find((candidate) => candidate.id === 'personal-agent-workbench');
    expect(project).toBeDefined();

    expect(projectFieldInitialCamera(project!)).toEqual({
      centerX: 1895,
      centerY: 420,
      scale: 1,
    });

    const camera = projectFieldInitialCamera(project!);
    expect(projectFieldCameraCenterXForViewport(project!, camera, 338, 0.68)).toBeCloseTo(2013.24, 2);
    expect(projectFieldCameraCenterXForViewport(project!, camera, 1200, 0.68)).toBe(camera.centerX);
  });

  it('uses the application motion preference before the operating-system fallback', () => {
    document.documentElement.dataset.reduceMotion = 'true';
    expect(projectFieldShouldReduceMotion()).toBe(true);

    document.documentElement.dataset.reduceMotion = 'false';
    expect(projectFieldShouldReduceMotion()).toBe(false);
  });

  it('translates internal runtime terms without changing real product names', () => {
    expect(projectFieldText('Context Provider 通过 Qwen Provider 在 Pi Runtime 的 Session 和 Room 中恢复')).toBe(
      '上下文服务通过 Qwen 模型服务在 Pi 运行环境的对话和协作目标中恢复',
    );
  });

  it('translates technical prototype copy at every visible Project Field boundary', async () => {
    const user = userEvent.setup();
    const { container } = render(<ProjectFieldFeature />);

    await user.click(screen.getByRole('button', { name: 'AI 工程实验室' }));
    expect(screen.getByRole('button', { name: /模型服务与工具循环/ })).toBeInTheDocument();
    const visibleAreaTitles = [...container.querySelectorAll('.room-landmark-card__scope [title]')]
      .map((element) => element.getAttribute('title'));
    expect(visibleAreaTitles).toContain('请求构造 · 追到模型服务边界。');

    await user.click(screen.getByRole('button', { name: /上下文与压缩，当前协作目标/ }));
    const contextWorkspace = screen.getByRole('article', { name: '上下文与压缩协作目标工作区' });
    expect(contextWorkspace).toHaveTextContent('当前协作目标');
    expect(contextWorkspace).toHaveTextContent('对话、压缩与恢复边界已串联。');
    expect(contextWorkspace).toHaveTextContent('连接对话连续性。');
    expect(contextWorkspace).not.toHaveTextContent(/\b(?:Provider|Session|Room|Runtime)\b/i);

    await user.click(screen.getByRole('button', { name: /Wisdom Weasel/ }));
    await user.click(screen.getByRole('button', { name: /可移植上下文/ }));
    const portableWorkspace = screen.getByRole('article', { name: '可移植上下文协作目标工作区' });
    expect(portableWorkspace).toHaveTextContent('上下文服务边界已形成。');
    expect(portableWorkspace).toHaveTextContent('跨运行环境读取');
    expect(portableWorkspace).not.toHaveTextContent(/\b(?:Context Provider|Provider|Session|Room|Runtime)\b/i);

    const sourceRoom = projectFieldProjects
      .find((project) => project.id === 'wisdom-weasel')
      ?.rooms.find((room) => room.id === 'portable-context');
    expect(sourceRoom?.recentResult).toBe('Context Provider 边界已形成。');
  });

  it('uses translated Room titles in completion and undo feedback', async () => {
    const user = userEvent.setup();
    const { container } = render(<ProjectFieldFeature />);

    await user.click(screen.getByRole('button', { name: 'AI 工程实验室' }));
    fireEvent.change(screen.getByLabelText('想继续推进什么？'), { target: { value: 'provider' } });
    await user.click(screen.getByRole('button', { name: '预览合适目标' }));

    const proposal = screen.getByRole('region', { name: '推荐处理位置' });
    expect(within(proposal).getByText('模型服务与工具循环')).toBeInTheDocument();
    await user.click(within(proposal).getByRole('button', { name: '预览归入这里' }));

    expect(screen.getByRole('status')).toHaveTextContent('已在预览中归入「模型服务与工具循环」');
    expect(container.querySelector('.project-field__live')).toHaveTextContent('已在预览中归入「模型服务与工具循环」，可撤销。');
    expect(screen.getByRole('article', { name: '模型服务与工具循环协作目标工作区' })).toHaveTextContent('模型服务');

    await user.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(screen.queryByRole('article', { name: /模型服务与工具循环/ })).not.toBeInTheDocument());
    expect(screen.getByLabelText('想继续推进什么？')).toHaveValue('provider');
  });

  it('expands a Room in place and returns to the same Project Field with Escape', async () => {
    const user = userEvent.setup();
    render(<ProjectFieldFeature />);

    await user.click(screen.getByRole('button', { name: '协作导航与项目图谱，当前协作目标' }));
    const workspace = screen.getByRole('article', { name: '协作导航与项目图谱协作目标工作区' });

    expect(within(workspace).getByRole('region', { name: '需求与问题' })).toHaveTextContent('整理后的需求');
    expect(within(workspace).getByRole('region', { name: '需求与问题' })).toHaveTextContent(
      '八个正确的结果型协作目标',
    );
    expect(within(workspace).getByRole('region', { name: '已确认决定' })).toHaveTextContent('由真实历史决定从左到右的 DAG 拓扑');
    expect(within(workspace).getByRole('region', { name: '可观察验收' })).toHaveTextContent('真实使用与发布作为贯穿式轨道');
    expect(within(workspace).getByRole('region', { name: '当前交付' })).toHaveTextContent('下一步');
    expect(within(workspace).getByRole('region', { name: '交付链' })).toHaveTextContent('实现执行');
    expect(within(workspace).getByRole('region', { name: '交付链' })).toHaveTextContent('测试驱动实现');
    expect(within(workspace).getByRole('region', { name: '交付文档' })).toHaveTextContent('项目图谱说明');
    expect(within(workspace).getByRole('region', { name: '交付文档' })).toHaveTextContent('当前交付说明');
    expect(within(workspace).getByRole('region', { name: '需求来源' })).toHaveTextContent('Codex');
    expect(within(workspace).getByRole('region', { name: '需求来源' })).toHaveTextContent('可追溯回执');
    expect(within(workspace).getByRole('button', { name: '返回项目场' })).toBeInTheDocument();
    expect(within(workspace).queryByRole('button', { name: '查看 Room 历史' })).not.toBeInTheDocument();
    expect(within(workspace).queryByRole('button', { name: '更多 Room 操作' })).not.toBeInTheDocument();
    expect(workspace).not.toHaveTextContent('/Users/undo');
    expect(within(workspace).queryByTitle(/agent-session:|git:/)).not.toBeInTheDocument();
    await waitFor(() => expect(workspace).toHaveFocus());

    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('article', { name: /协作导航与项目图谱/ })).not.toBeInTheDocument());
    const restoredRoom = screen.getByRole('button', { name: '协作导航与项目图谱，当前协作目标' });
    expect(restoredRoom).toBeInTheDocument();
    await waitFor(() => expect(restoredRoom).toHaveFocus());
  });

  it('routes a new request to an existing Room and keeps the original input undoable', async () => {
    const user = userEvent.setup();
    render(<ProjectFieldFeature />);

    const navigator = screen.getByLabelText('想继续推进什么？');
    // Chinese IMEs commit the composed value as one input/change update.  A
    // character-by-character keyboard simulation is both inaccurate and
    // timing-sensitive when the whole frontend suite runs concurrently.
    fireEvent.change(navigator, { target: { value: '删除后旧候选偶尔还会回来' } });
    await user.click(screen.getByRole('button', { name: '预览合适目标' }));

    const proposal = screen.getByRole('region', { name: '推荐处理位置' });
    expect(within(proposal).getByText('输入体验闭环')).toBeInTheDocument();
    await user.click(within(proposal).getByRole('button', { name: '预览归入这里' }));

    const workspace = screen.getByRole('article', { name: '输入体验闭环协作目标工作区' });
    expect(workspace).toHaveTextContent('删除后旧候选偶尔还会回来');
    expect(screen.getByRole('button', { name: '撤销' })).toBeInTheDocument();

    expect(screen.getByRole('status')).toHaveTextContent('已在预览中归入「输入体验闭环」');

    await user.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(screen.queryByRole('article', { name: /输入体验闭环/ })).not.toBeInTheDocument());
    expect(screen.getByLabelText('想继续推进什么？')).toHaveValue('删除后旧候选偶尔还会回来');
  });

  it('lets people recover from an empty field search without a dead end', async () => {
    const user = userEvent.setup();
    render(<ProjectFieldFeature />);

    const search = screen.getByLabelText('搜索协作目标');
    await user.type(search, 'zzzzzz');
    expect(screen.getByText('没有找到匹配的协作目标')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '清除搜索' }));

    expect(search).toHaveValue('');
    expect(screen.queryByRole('region', { name: '搜索结果' })).not.toBeInTheDocument();
  });

  it('keeps every matching Room reachable inside the compact search window', async () => {
    const user = userEvent.setup();
    render(<ProjectFieldFeature />);

    await user.type(screen.getByLabelText('搜索协作目标'), '的');
    const results = screen.getByRole('region', { name: '搜索结果' });

    expect(within(results).getByText('7 个匹配目标')).toBeInTheDocument();
    expect(within(results).getAllByRole('button')).toHaveLength(7);
  });

  it('routes an internal functional direction back to its containing Room island', async () => {
    const user = userEvent.setup();
    render(<ProjectFieldFeature />);

    fireEvent.change(screen.getByLabelText('想继续推进什么？'), {
      target: { value: '后台注意力不要打断当前工作' },
    });
    await user.click(screen.getByRole('button', { name: '预览合适目标' }));

    const proposal = screen.getByRole('region', { name: '推荐处理位置' });
    expect(within(proposal).getByText('协作导航与项目图谱')).toBeInTheDocument();
    expect(within(proposal).queryByText('后台注意力')).not.toBeInTheDocument();
  });

  it('opens real attention without stealing the focused result', async () => {
    const user = userEvent.setup();
    render(<ProjectFieldFeature />);

    await user.click(screen.getByRole('button', { name: '协作导航与项目图谱，当前协作目标' }));
    const foreground = screen.getByRole('article', { name: '协作导航与项目图谱协作目标工作区' });
    expect(foreground).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '2 件事需要你' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: '需要你的协作目标' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '2 件事需要你' }));
    const drawer = screen.getByRole('complementary', { name: '需要你的协作目标' });
    expect(drawer).toHaveTextContent('输入体验闭环');
    expect(foreground).toBeInTheDocument();
  });

  it('restores a focused Room after switching projects', async () => {
    const user = userEvent.setup();
    render(<ProjectFieldFeature />);

    await user.click(screen.getByRole('button', { name: '协作导航与项目图谱，当前协作目标' }));
    await user.click(screen.getByRole('button', { name: /Wisdom Weasel/ }));
    expect(screen.getByRole('heading', { name: '记忆检索 项目场' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /个人助手工作台/ }));
    expect(screen.getByRole('article', { name: '协作导航与项目图谱协作目标工作区' })).toBeInTheDocument();
  });
});
