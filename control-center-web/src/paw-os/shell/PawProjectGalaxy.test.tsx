import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PawProjectGalaxy } from './PawProjectGalaxy';
import type { WayfinderWorkItem, WayfinderWorkProject } from './wayfinder-work-projection';

vi.mock('./PawProjectGalaxyScene', () => ({
  PawProjectGalaxyScene: ({ model, selectedId, onPick }: { model: import('./project-galaxy-model').ProjectGalaxyModel; selectedId: string | null; onPick(id: string): void }) => <div>
    {model.bodies.map((body) => <button key={body.id} aria-label={`${body.title}，${body.subtitle}`} aria-pressed={selectedId === body.id} data-running={body.motion.working} onClick={() => onPick(body.id)}>{body.title}</button>)}
  </div>,
}));

afterEach(cleanup);

function item(index: number, overrides: Partial<WayfinderWorkItem> = {}): WayfinderWorkItem {
  return {
    key: `session:${String(index).padStart(2, '0')}`, projectKey: 'paw', workspaceRoots: ['/work/paw'],
    kind: 'session', id: `session-${index}`, title: `任务 ${index}`, project: 'paw', updatedAtMs: 100,
    activity: 'idle', runtimeRunning: false, statusLabel: '就绪', detail: `最近结果 ${index}`, agents: [], repeats: [],
    ...overrides,
  };
}

function project(items: WayfinderWorkItem[]): WayfinderWorkProject {
  return { id: 'paw', label: 'PAW', workspaceRoots: ['/work/paw'], items, buckets: [], sessionCount: items.filter((entry) => entry.kind === 'session').length, roomCount: items.filter((entry) => entry.kind === 'room').length, runningCount: items.filter((entry) => entry.runtimeRunning).length, attentionCount: items.filter((entry) => entry.activity === 'attention').length };
}

function props(items: WayfinderWorkItem[]) {
  return { project: project(items), onClose: vi.fn(), onOpen: vi.fn(), onOpenProject: vi.fn(), documents: <button type="button">PROJECT.md</button> };
}

describe('PawProjectGalaxy', () => {
  it('selects a real planet with keyboard and opens that canonical conversation', async () => {
    const user = userEvent.setup();
    const second = item(2, { activity: 'attention', runtimeRunning: true, statusLabel: '需要处理', detail: '阻塞：等待服务恢复' });
    const options = props([item(1), second]);
    render(<PawProjectGalaxy {...options} />);
    expect(screen.getByRole('dialog', { name: 'PAW · 项目星系' })).toBeInTheDocument();
    const planet = screen.getByRole('button', { name: '任务 2，需要处理 · 运行中' });
    planet.focus();
    await user.keyboard('{Enter}');
    expect(planet).toHaveAttribute('aria-pressed', 'true');
    const inspector = screen.getByRole('complementary', { name: '行星详情与项目文档' });
    expect(within(inspector).getByText('阻塞：等待服务恢复')).toBeInTheDocument();
    expect(within(inspector).getByText('正在运行')).toBeInTheDocument();
    await user.click(within(inspector).getByRole('button', { name: '打开对话' }));
    expect(options.onOpen).toHaveBeenCalledWith(second);
    expect(screen.queryByRole('progressbar')).toBeNull();
  });

  it('keeps identity positions stable across live updates and renders only supplied Room counts', () => {
    const first = item(1, { kind: 'room', progress: { completed: 2, total: 5 } });
    const second = item(2);
    const options = props([second, first]);
    const result = render(<PawProjectGalaxy {...options} />);
    fireEvent.click(screen.getByRole('button', { name: '任务 1，就绪 · 2/5 项' }));
    expect(screen.getByRole('progressbar', { name: '协作任务完成进度' })).toHaveAttribute('value', '2');
    expect(screen.getByRole('progressbar')).toHaveAttribute('max', '5');
    result.rerender(<PawProjectGalaxy {...options} project={project([{ ...first, updatedAtMs: 999, runtimeRunning: true, activity: 'running', statusLabel: '进行中', progress: { completed: 3, total: 5 } }, second])} />);
    expect(screen.getByRole('button', { name: '任务 1，进行中 · 3/5 项' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '3');
    expect(screen.queryByText(/\d+%/)).toBeNull();
  });

  it('bounds the map to twelve planets, pages all records and searches beyond the visible page', async () => {
    const user = userEvent.setup();
    render(<PawProjectGalaxy {...props(Array.from({ length: 25 }, (_, index) => item(index + 1)))} />);
    const map = screen.getByRole('region', { name: '项目行星地图' });
    expect(within(map).getAllByRole('button', { name: /^任务 / })).toHaveLength(12);
    expect(screen.getByRole('navigation', { name: '行星分页' })).toHaveTextContent('1–12 / 25');
    await user.click(screen.getByRole('button', { name: '下一组行星' }));
    expect(screen.getByRole('navigation', { name: '行星分页' })).toHaveTextContent('13–24 / 25');
    await user.type(screen.getByRole('searchbox', { name: '搜索项目对话' }), '任务 25');
    expect(within(map).getByRole('button', { name: '任务 25，就绪' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: '行星分页' })).toHaveTextContent('1–1 / 1');
  });

  it('keeps document actions supplied by the owner, supports disclosure, project settings and Escape', async () => {
    const user = userEvent.setup();
    const options = props([item(1)]);
    render(<PawProjectGalaxy {...options} />);
    expect(screen.queryByRole('region', { name: '项目文档' })).toBeNull();
    await user.click(screen.getByRole('button', { name: '项目 docs' }));
    expect(screen.getByRole('region', { name: '项目文档' })).toHaveTextContent('PROJECT.md');
    await user.click(screen.getByRole('button', { name: '收起详情与项目文档' }));
    expect(screen.queryByRole('region', { name: '项目文档' })).toBeNull();
    await user.click(screen.getByRole('button', { name: '项目 docs' }));
    expect(screen.getByRole('button', { name: 'PROJECT.md' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '项目设置' }));
    expect(options.onOpenProject).toHaveBeenCalledOnce();
    await user.keyboard('{Escape}');
    expect(options.onClose).toHaveBeenCalledOnce();
  });

  it('pauses ambient work when hidden and removes the running signal on a terminal update', () => {
    let visibility: DocumentVisibilityState = 'visible';
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
    try {
      const options = props([item(1, { activity: 'running', runtimeRunning: true, statusLabel: '进行中' })]);
      const result = render(<PawProjectGalaxy {...options} />);
      expect(screen.getByRole('dialog')).toHaveAttribute('data-ambient', 'true');
      visibility = 'hidden';
      act(() => fireEvent(document, new Event('visibilitychange')));
      expect(screen.getByRole('dialog')).toHaveAttribute('data-ambient', 'false');
      result.rerender(<PawProjectGalaxy {...options} project={project([item(1)])} />);
      expect(screen.getByRole('button', { name: '任务 1，就绪' })).toHaveAttribute('data-running', 'false');
    } finally {
      delete (document as unknown as Record<string, unknown>).visibilityState;
    }
  });

  it('keeps project documents reachable when there are no conversations', () => {
    render(<PawProjectGalaxy {...props([])} />);
    expect(screen.getByText('这个项目还没有对话。可以先从项目 docs 开始。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '项目 docs' }));
    expect(screen.getByRole('button', { name: 'PROJECT.md' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开对话' })).toBeNull();
  });
});
