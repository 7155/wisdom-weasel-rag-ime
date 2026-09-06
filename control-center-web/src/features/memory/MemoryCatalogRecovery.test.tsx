import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { MemoryFeature } from './index';

afterEach(cleanup);

describe('Memory catalog recovery', () => {
  it.each(['pending', 'error'])('keeps readable records available while summary is %s', async (state) => {
    renderMemory(new MockControlTransport({ routes: {
      'memory.summary': () => state === 'pending' ? new Promise(() => {}) : Promise.reject(new Error('summary unavailable')),
      'memory.pages': { items: [{ id: 'atom-1', title: '保留的记忆', text: '这条正文已经读到。', status: 'current' }], nextCursor: '' },
    } }));

    expect(await screen.findByRole('button', { name: /保留的记忆/ })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: '搜索' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '记忆 · 已整理记忆 · 计数暂不可用' })).toHaveTextContent('—');
  });

  it('keeps the focused search control mounted while filtered results are loading', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'memory.summary': { memoryAtomCount: 1 },
      'memory.pages': (request: ControlRequest) => request.query?.query ? new Promise(() => {}) : { items: [], nextCursor: '' },
    } });
    renderMemory(transport);
    const search = await screen.findByRole('textbox', { name: '搜索' });
    await user.type(search, '输入');
    await waitFor(() => expect(transport.requests.some(({ request }) => request.pathId === 'memory.pages' && request.query?.query === '输入')).toBe(true));

    expect(screen.getByRole('textbox', { name: '搜索' })).toBe(search);
    expect(search).toHaveFocus();
    await user.click(screen.getByRole('button', { name: '清除搜索' }));
    expect(search).toHaveValue('');
    expect(search).toHaveFocus();
  });

  it('recovers a filtered empty catalog with one clear-filters action', async () => {
    const user = userEvent.setup();
    const transport = new MockControlTransport({ routes: {
      'memory.summary': { memoryAtomCount: 0 },
      'memory.pages': { items: [], nextCursor: '' },
    } });
    renderMemory(transport);
    await user.type(await screen.findByRole('textbox', { name: '搜索' }), '无结果');
    expect(await screen.findByRole('heading', { name: '没有匹配结果' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '清除筛选' }));

    expect(screen.getByRole('textbox', { name: '搜索' })).toHaveValue('');
    expect(await screen.findByText('记忆从工作回执沉淀')).toBeInTheDocument();
    expect(transport.requests.every(({ request }) => !request.pathId.includes('run') && !request.pathId.includes('build'))).toBe(true);
  });
});

function renderMemory(transport: MockControlTransport) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<MemoryRouter initialEntries={['/memory?layer=atoms']}><TooltipProvider><ControlTransportProvider transport={transport}><QueryClientProvider client={client}><MemoryFeature /></QueryClientProvider></ControlTransportProvider></TooltipProvider></MemoryRouter>);
}
