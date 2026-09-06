import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { lazy, Suspense, type ReactElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PawProjectGalaxyScene } from './PawProjectGalaxyScene';
import { PawProjectGalaxy } from './PawProjectGalaxy';
import { projectGalaxyScene } from './project-galaxy-model';
import type { WayfinderWorkItem, WayfinderWorkProject } from './wayfinder-work-projection';

const engine = vi.hoisted(() => ({ instances: [] as Array<{ setModel: ReturnType<typeof vi.fn>; setMotion: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }> }));
vi.mock('./project-galaxy-stage', () => ({ ProjectGalaxyStage: class {
  setModel = vi.fn(); setMotion = vi.fn(); setSelected = vi.fn(); resize = vi.fn(); dispose = vi.fn();
  constructor() { engine.instances.push(this); }
} }));
afterEach(() => { cleanup(); engine.instances.length = 0; delete document.documentElement.dataset.reduceMotion; vi.unstubAllGlobals(); });
const item: WayfinderWorkItem = { id: 's1', key: 'session:s1', projectKey: 'paw', project: 'PAW', workspaceRoots: [],
  kind: 'session', title: '真实任务', updatedAtMs: 0, activity: 'running', runtimeRunning: true, statusLabel: '进行中', detail: '正在读取项目', agents: [], repeats: [] };
const setup = () => { vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }); };

describe('project universe lifecycle', () => {
  it('pauses and changes simulation speed without changing task execution state', async () => {
    setup();
    const project: WayfinderWorkProject = { id: 'paw', label: 'PAW', items: [item], workspaceRoots: [], buckets: [], sessionCount: 1, roomCount: 0, runningCount: 1, attentionCount: 0 };
    render(<PawProjectGalaxy project={project} onClose={vi.fn()} onOpen={vi.fn()} onOpenProject={vi.fn()} documents={null} />);
    await waitFor(() => expect(engine.instances[0]?.setMotion).toHaveBeenCalledWith(true, false, 1));
    fireEvent.click(screen.getByRole('button', { name: '暂停轨道模拟' }));
    expect(engine.instances[0]!.setMotion).toHaveBeenLastCalledWith(true, false, 0);
    expect(screen.getByRole('button', { name: '真实任务，进行中' })).toHaveAttribute('data-running', 'true');
    fireEvent.change(screen.getByRole('combobox', { name: '模拟时间倍率' }), { target: { value: '4' } });
    expect(engine.instances[0]!.setMotion).toHaveBeenLastCalledWith(true, false, 0);
    fireEvent.click(screen.getByRole('button', { name: '继续轨道模拟' }));
    expect(engine.instances[0]!.setMotion).toHaveBeenLastCalledWith(true, false, 4);
    expect(engine.instances).toHaveLength(1);
  });

  it('keeps the galaxy visible while its document panel loads for the first time', async () => {
    setup();
    let finish = () => {};
    const Documents = lazy(() => new Promise<{ default: () => ReactElement }>((resolve) => {
      finish = () => resolve({ default: () => <p>PROJECT.md</p> });
    }));
    const project: WayfinderWorkProject = { id: 'paw', label: 'PAW', items: [item], workspaceRoots: [], buckets: [], sessionCount: 1, roomCount: 0, runningCount: 1, attentionCount: 0 };
    render(<Suspense fallback={<p>正在打开项目星系…</p>}><PawProjectGalaxy project={project} onClose={vi.fn()} onOpen={vi.fn()} onOpenProject={vi.fn()} documents={<Documents />} /></Suspense>);
    await waitFor(() => expect(engine.instances[0]?.setModel).toHaveBeenCalled());
    const map = screen.getByRole('region', { name: '项目行星地图' });
    const canvas = document.querySelector('canvas');
    fireEvent.click(screen.getByRole('button', { name: '项目 docs' }));
    try {
      expect(map).toBeVisible();
      expect(screen.queryByText('正在打开项目星系…')).toBeNull();
    } finally { await act(async () => { finish(); }); }
    expect(screen.getByText('PROJECT.md')).toBeVisible();
    expect(document.querySelector('canvas')).toBe(canvas);
    expect(engine.instances).toHaveLength(1);
    expect(engine.instances[0]!.dispose).not.toHaveBeenCalled();
  });

  it.each(['page', 'search'] as const)('keeps the same renderer and canvas when navigating by %s', async (navigation) => {
    setup();
    const items = Array.from({ length: 25 }, (_, index) => ({ ...item, id: `s${index}`, key: `session:${String(index).padStart(2, '0')}`, title: `任务 ${index}` }));
    const project: WayfinderWorkProject = { id: 'paw', label: 'PAW', items, workspaceRoots: [], buckets: [], sessionCount: 25, roomCount: 0, runningCount: 25, attentionCount: 0 };
    const onOpen = vi.fn();
    const result = render(<PawProjectGalaxy project={project} onClose={vi.fn()} onOpen={onOpen} onOpenProject={vi.fn()} documents={null} />);
    await waitFor(() => expect(engine.instances[0]?.setModel).toHaveBeenCalled());
    const canvas = document.querySelector('canvas');
    if (navigation === 'page') fireEvent.click(screen.getByRole('button', { name: '下一组行星' }));
    else {
      await act(async () => { fireEvent.change(screen.getByRole('searchbox', { name: '搜索项目对话' }), { target: { value: '任务 2' } }); });
      await act(async () => { fireEvent.change(screen.getByRole('searchbox', { name: '搜索项目对话' }), { target: { value: '任务 24' } }); });
    }
    const expected = navigation === 'page' ? items[12]! : items[24]!;
    await waitFor(() => expect(engine.instances.at(-1)?.setModel).toHaveBeenLastCalledWith(expect.objectContaining({ bodies: expect.arrayContaining([expect.objectContaining({ id: expected.key })]) })));
    expect(engine.instances).toHaveLength(1);
    expect(document.querySelector('canvas')).toBe(canvas);
    expect(engine.instances[0]!.dispose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: `${expected.title}，进行中` }));
    fireEvent.click(screen.getByRole('button', { name: '打开对话' }));
    expect(onOpen).toHaveBeenCalledWith(expected);
    result.unmount();
    expect(engine.instances[0]!.dispose).toHaveBeenCalledOnce();
  });

  it('updates live records in one renderer and releases it on close', async () => {
    setup();
    const options = { onPick: vi.fn(), onFallback: vi.fn(), selectedId: null };
    const result = render(<PawProjectGalaxyScene {...options} model={projectGalaxyScene('paw', 'PAW', [item])} running />);
    await waitFor(() => expect(engine.instances[0]?.setModel).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: '真实任务，进行中' })).toHaveAttribute('data-running', 'true');
    result.rerender(<PawProjectGalaxyScene {...options} model={projectGalaxyScene('paw', 'PAW', [{ ...item, activity: 'idle', runtimeRunning: false, statusLabel: '就绪' }])} running />);
    expect(engine.instances).toHaveLength(1);
    expect(screen.getByRole('button', { name: '真实任务，就绪' })).toHaveAttribute('data-running', 'false');
    const stage = engine.instances[0]!;
    result.unmount();
    expect(stage.dispose).toHaveBeenCalledOnce();
  });
  it('stops background rendering and honors a changed reduce-motion preference', async () => {
    setup();
    const options = { model: projectGalaxyScene('paw', 'PAW', [item]), onPick: vi.fn(), onFallback: vi.fn(), selectedId: null };
    const result = render(<PawProjectGalaxyScene {...options} running />);
    await waitFor(() => expect(engine.instances[0]?.setMotion).toHaveBeenCalledWith(true, false, 1));
    result.rerender(<PawProjectGalaxyScene {...options} running={false} />);
    expect(engine.instances[0]!.setMotion).toHaveBeenLastCalledWith(false, false, 1);
    await act(async () => { document.documentElement.dataset.reduceMotion = 'true'; });
    expect(engine.instances[0]!.setMotion).toHaveBeenLastCalledWith(false, true, 1);
  });
});
