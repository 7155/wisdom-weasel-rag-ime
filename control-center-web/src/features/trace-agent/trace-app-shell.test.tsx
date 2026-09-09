import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { TraceAppShell, TraceCapabilityLibrary, TraceKnowledgeLibrary } from './trace-app-shell';

afterEach(() => { cleanup(); window.localStorage.clear(); });

it('keeps Trace navigation collapsible while preserving the current report and draft', async () => {
  const user = userEvent.setup();
  const onNavigate = vi.fn();
  render(<TraceAppShell view="report" onNavigate={onNavigate}><input aria-label="任务目标" defaultValue="保持已有草稿" /></TraceAppShell>);
  const navigation = screen.getByRole('navigation', { name: 'Trace Agent 应用导航' });
  await user.click(screen.getByRole('button', { name: '收起Trace Agent 导航' }));
  expect(navigation).not.toBeVisible();
  expect(screen.getByRole('textbox', { name: '任务目标' })).toHaveValue('保持已有草稿');
  expect(screen.getByRole('button', { name: '← 返回工作台' })).toBeVisible();
  await user.click(screen.getByRole('button', { name: '展开Trace Agent 导航' }));
  await user.click(within(navigation).getByRole('button', { name: '经验库' }));
  expect(onNavigate).toHaveBeenCalledWith('knowledge');
});

describe('Trace App libraries', () => {
  it('reads a selected project and an exact pattern revision without creating an execution', async () => {
    const transport = new MockControlTransport({ routes: {
      'observability.traceOptimization.library': (request: ControlRequest) => ({ ok: true, projects: [{ projectId: 'project:1', title: '排障项目' }], projectId: 'project:1', patterns: [{ patternId: 'pattern:1', revision: 3, title: '区分输入错误与暂时性故障', summary: '对输入错误停止重试。', status: 'supported', componentRef: 'skill:retry', evidenceCount: 2 }], truncated: false, ...(request.query?.patternId ? { pattern: { patternId: 'pattern:1', revision: 3, content: { observations: [{ statement: '两段对话重复出现同类无效重试', evidenceIds: ['evidence:1', 'evidence:2'] }], hypotheses: [{ statement: '错误分类可以减少无效调用', uncertainty: '仍需独立实例验证' }] } } } : {}) }),
    } });
    renderLibrary(<TraceKnowledgeLibrary />, transport);
    await userEvent.setup().click(await screen.findByRole('button', { name: /区分输入错误与暂时性故障/ }));
    expect(await screen.findByText('两段对话重复出现同类无效重试')).toBeInTheDocument();
    expect(screen.getByText(/仍需独立实例验证/)).toBeInTheDocument();
    expect(transport.requests.at(-1)?.request.query).toEqual({ projectId: 'project:1', patternId: 'pattern:1', revision: 3 });
    expect(transport.requests.every(({ request }) => request.pathId === 'observability.traceOptimization.library')).toBe(true);
  });

  it('keeps installed capabilities and unverified candidates distinct while reporting unavailable catalogs', async () => {
    const transport = new MockControlTransport({ routes: {
      'observability.traceOptimization.capabilities': { ok: true, items: [{ id: 'skill:1', name: '排障 Skill', kind: 'skill', status: 'installed', version: 'v3', summary: '按错误类型决定重试。' }, { id: 'tool:1', name: '查询工具候选', kind: 'tool', status: 'candidate', version: 'draft:1', summary: '待验证的实现。' }], unavailable: ['提示词目录暂不可用'] },
    } });
    renderLibrary(<TraceCapabilityLibrary />, transport);
    expect(await screen.findByText('Skill · 已安装')).toBeInTheDocument();
    expect(screen.getByText('工具 · 候选草稿')).toBeInTheDocument();
    expect(screen.getByText('提示词目录暂不可用')).toBeInTheDocument();
    await userEvent.setup().selectOptions(screen.getByRole('combobox', { name: '版本状态' }), 'candidate');
    expect(screen.queryByRole('heading', { name: '排障 Skill' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '查询工具候选' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /安装/ })).not.toBeInTheDocument();
  });

  it('shows a recoverable library error rather than treating unavailable data as an empty catalog', async () => {
    const transport = new MockControlTransport({ routes: {
      'observability.traceOptimization.library': () => { throw new Error('项目目录读取失败'); },
    } });
    renderLibrary(<TraceKnowledgeLibrary />, transport);
    const error = await screen.findByRole('alert');
    expect(error).toHaveTextContent('项目目录读取失败');
    expect(within(error).getByRole('button', { name: '重试' })).toBeInTheDocument();
    expect(screen.queryByText('此项目还没有经验记录')).not.toBeInTheDocument();
  });
});

function renderLibrary(content: React.ReactNode, transport: MockControlTransport) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<ControlTransportProvider transport={transport}><QueryClientProvider client={client}>{content}</QueryClientProvider></ControlTransportProvider>);
}
