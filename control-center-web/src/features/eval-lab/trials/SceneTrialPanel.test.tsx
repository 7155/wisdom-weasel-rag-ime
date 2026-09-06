import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import { SceneTrialPanel } from './SceneTrialPanel';
import { parseTrialList, type TrialJob } from './api';
import { trialMetrics } from './trial-result';

const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); sessionStorage.clear(); });
const job = (state: TrialJob['state'], request = 'request-1'): TrialJob => ({
  jobId: 'trial-1', clientRequestId: request, sceneId: 'cloudops', state,
  publicSpec: { model: 'gpt-5.6-luna' }, progress: state === 'running' ? '正在执行第 2/3 批案例' : '',
  cancelRequested: state === 'cancelling', sessions: [{ sessionId: 'agent:one', turnId: 'turn:one' }],
  result: state === 'completed' ? { caseCount: 12, metrics: { JRA: 1 }, cost: { available: true, totalCostUsd: '0.3341084', currency: 'USD' } } : null,
  error: '', resumeAvailable: false, createdAtMs: 1000, updatedAtMs: 2000,
});
const read = (jobs: TrialJob[] = [], registeredSceneIds = ['cloudops']) => ({ schemaVersion: 'rag-ime.agent-lab-trial.v1', jobs, registeredSceneIds });

function mount(transport: MockControlTransport, sceneId = 'cloudops', client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  clients.push(client);
  return render(<QueryClientProvider client={client}><ControlTransportProvider transport={transport}><SceneTrialPanel sceneId={sceneId} /></ControlTransportProvider></QueryClientProvider>);
}

describe('scene trial execution', () => {
  it('keeps a restored startup request selected when its receipt is older than another completed trial', async () => {
    let jobs: TrialJob[] = [];
    let requestId = '';
    const transport = new MockControlTransport({ routes: {
      'agent.eval-lab.trials.get': () => read(jobs),
      'agent.eval-lab.trials.start': (request: { body: unknown }) => { requestId = String((request.body as Record<string, unknown>).clientRequestId); throw new TypeError('lost startup receipt'); },
    } });
    const original = mount(transport);
    fireEvent.click(await screen.findByRole('button', { name: '运行验证' }));
    await screen.findByRole('button', { name: '核对本次启动' });
    original.unmount();
    jobs = [{ ...job('completed'), jobId: 'later-trial', createdAtMs: 3000 }, { ...job('completed', requestId), jobId: 'restored-trial' }];
    mount(transport);
    await waitFor(() => expect(screen.queryByRole('button', { name: '核对本次启动' })).not.toBeInTheDocument());
    expect(screen.getByText('restored-trial')).toBeInTheDocument();
    expect(screen.queryByText('later-trial')).not.toBeInTheDocument();
    expect(transport.requests.filter(({ request }) => request.pathId === 'agent.eval-lab.trials.start')).toHaveLength(1);
  });

  it('restores a scene draft and selected history after the Run tab remounts', async () => {
    const transport = new MockControlTransport();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const calls = vi.spyOn(transport, 'request').mockResolvedValue(read([
      { ...job('completed'), jobId: 'latest', createdAtMs: 3000 }, job('cancelled'),
    ], ['cloudops', 'memory']));
    const view = mount(transport, 'cloudops', client);
    fireEvent.change(await screen.findByLabelText('执行模型'), { target: { value: 'draft-model' } });
    fireEvent.change(screen.getByLabelText('候选补充提示词'), { target: { value: '还未提交的规则' } });
    fireEvent.click(screen.getByText('此前的执行 · 2 次'));
    fireEvent.click(screen.getByRole('button', { name: /已停止/u }));
    view.unmount();
    const otherScene = mount(transport, 'memory', client);
    expect(await screen.findByLabelText('执行模型')).toHaveValue('');
    otherScene.unmount();
    mount(transport, 'cloudops', client);
    expect(await screen.findByLabelText('执行模型')).toHaveValue('draft-model');
    expect(screen.getByLabelText('候选补充提示词')).toHaveValue('还未提交的规则');
    expect(screen.getByText('已停止', { selector: 'strong' })).toBeInTheDocument();
    expect(calls.mock.calls.every(([request]) => request.pathId === 'agent.eval-lab.trials.get')).toBe(true);
  });

  it('keeps an active execution reachable while inspecting terminal history', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockResolvedValue(read([
      job('running'), { ...job('completed'), jobId: 'previous', createdAtMs: 500 },
    ]));
    mount(transport);
    await screen.findByRole('button', { name: '停止实验' });
    fireEvent.click(screen.getByText('此前的执行 · 2 次'));
    fireEvent.click(screen.getByRole('button', { name: /已完成/u }));
    expect(await screen.findByText('已完成', { selector: 'strong' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看当前执行' }));
    expect(await screen.findByRole('button', { name: '停止实验' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '运行验证' })).not.toBeInTheDocument();
  });

  it('formats declared rates as percentages while preserving recall counts and unknown units', () => {
    const metrics = trialMetrics({ metrics: { durableRecallPassed: 1, durableRecallTotal: 1, durableRecallRate: 1, customRecallBudget: 0.5 } });
    expect(Object.fromEntries(metrics.map(({ key, value }) => [key, value]))).toEqual({
      ':durableRecallPassed': '1', ':durableRecallTotal': '1', ':durableRecallRate': '100%', ':customRecallBudget': '0.5',
    });
  });

  it('does not offer a paid start for an unregistered scene', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockResolvedValue(read([], []));
    mount(transport);
    expect(await screen.findByText('这个场景尚未连接执行环境。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '运行验证' })).not.toBeInTheDocument();
  });

  it('projects actual progress and keeps stopping until a terminal receipt', async () => {
    const transport = new MockControlTransport();
    let current = job('running');
    const calls = vi.spyOn(transport, 'request').mockImplementation(async (request) => {
      if (request.pathId === 'agent.eval-lab.trials.cancel') { current = job('cancelling'); return { schemaVersion: 'rag-ime.agent-lab-trial.v1', job: current }; }
      return read([current]);
    });
    mount(transport);
    expect(await screen.findByText('正在执行第 2/3 批案例')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '停止实验' }));
    expect(await screen.findByText('正在停止')).toBeInTheDocument();
    expect(screen.queryByText('已停止')).not.toBeInTheDocument();
    expect(calls.mock.calls.filter(([request]) => request.pathId === 'agent.eval-lab.trials.cancel')).toHaveLength(1);
    current = job('cancelled');
    fireEvent.click(screen.getByRole('button', { name: '刷新执行状态' }));
    expect(await screen.findByText('已停止')).toBeInTheDocument();
  });

  it('retries an uncertain start with the same frozen command', async () => {
    const transport = new MockControlTransport();
    let attempts = 0;
    const calls = vi.spyOn(transport, 'request').mockImplementation(async (request) => {
      if (request.pathId !== 'agent.eval-lab.trials.start') return read();
      if (++attempts === 1) throw new Error('connection lost after admission');
      const command = request.body as { clientRequestId: string };
      return { schemaVersion: 'rag-ime.agent-lab-trial.v1', job: job('queued', command.clientRequestId), replayed: true };
    });
    mount(transport);
    fireEvent.click(await screen.findByRole('button', { name: '运行验证' }));
    fireEvent.click(await screen.findByRole('button', { name: '核对本次启动' }));
    await waitFor(() => expect(attempts).toBe(2));
    const commands = calls.mock.calls.filter(([request]) => request.pathId === 'agent.eval-lab.trials.start').map(([request]) => request.body);
    expect(commands[1]).toEqual(commands[0]);
  });

  it('keeps the admitted job when the follow-up list cannot be read', async () => {
    const transport = new MockControlTransport();
    let admitted = false;
    vi.spyOn(transport, 'request').mockImplementation(async (request) => {
      if (request.pathId === 'agent.eval-lab.trials.start') {
        admitted = true;
        return { schemaVersion: 'rag-ime.agent-lab-trial.v1', job: job('queued', (request.body as { clientRequestId: string }).clientRequestId), replayed: false };
      }
      if (admitted) throw new Error('read unavailable');
      return read();
    });
    mount(transport);
    fireEvent.click(await screen.findByRole('button', { name: '运行验证' }));
    expect(await screen.findByText('等待执行')).toBeInTheDocument();
    expect(await screen.findByText('上次读取的状态，当前进展尚未确认。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '运行验证' })).not.toBeInTheDocument();
  });

  it('retains a cancellation receipt when a later observation is stale', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockImplementation(async (request) => request.pathId === 'agent.eval-lab.trials.cancel'
      ? { schemaVersion: 'rag-ime.agent-lab-trial.v1', job: { ...job('cancelling'), updatedAtMs: 3000 } }
      : read([job('running')]));
    mount(transport);
    fireEvent.click(await screen.findByRole('button', { name: '停止实验' }));
    expect(await screen.findByText('正在停止')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新执行状态' })).not.toBeDisabled());
    expect(screen.queryByRole('button', { name: '停止实验' })).not.toBeInTheDocument();
    expect(screen.queryByText('已停止')).not.toBeInTheDocument();
  });

  it('does not treat an unrelated admission receipt as this launch', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockImplementation(async (request) => request.pathId === 'agent.eval-lab.trials.start'
      ? { schemaVersion: 'rag-ime.agent-lab-trial.v1', job: job('completed', 'another-request'), replayed: true }
      : read());
    mount(transport);
    fireEvent.click(await screen.findByRole('button', { name: '运行验证' }));
    expect(await screen.findByRole('button', { name: '核对本次启动' })).toBeInTheDocument();
    expect(screen.queryByText('已完成')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '运行验证' })).not.toBeInTheDocument();
  });

  it('restores an uncertain launch after reload and only retries the original command on request', async () => {
    const transport = Object.assign(new MockControlTransport(), { connectionIdentity: 'trial-test:restore' });
    const calls = vi.spyOn(transport, 'request').mockImplementation(async (request) => {
      if (request.pathId === 'agent.eval-lab.trials.start') throw new Error('lost receipt');
      return read();
    });
    const view = mount(transport);
    fireEvent.change(await screen.findByLabelText('执行模型'), { target: { value: 'frozen-model' } });
    fireEvent.change(screen.getByLabelText('候选补充提示词'), { target: { value: 'frozen prompt' } });
    fireEvent.click(screen.getByRole('button', { name: '运行验证' }));
    await screen.findByRole('button', { name: '核对本次启动' });
    const original = calls.mock.calls.find(([request]) => request.pathId === 'agent.eval-lab.trials.start')![0].body;
    view.unmount();

    const restored = Object.assign(new MockControlTransport(), { connectionIdentity: 'trial-test:restore' });
    const restoredCalls = vi.spyOn(restored, 'request').mockImplementation(async (request) => request.pathId === 'agent.eval-lab.trials.start'
      ? { schemaVersion: 'rag-ime.agent-lab-trial.v1', job: job('running', (request.body as { clientRequestId: string }).clientRequestId), replayed: true }
      : read());
    mount(restored);
    const retry = await screen.findByRole('button', { name: '核对本次启动' });
    expect(restoredCalls.mock.calls.every(([request]) => request.pathId === 'agent.eval-lab.trials.get')).toBe(true);
    expect(screen.queryByRole('button', { name: '运行验证' })).not.toBeInTheDocument();
    fireEvent.click(retry);
    expect(await screen.findByText('正在运行')).toBeInTheDocument();
    expect(restoredCalls.mock.calls.find(([request]) => request.pathId === 'agent.eval-lab.trials.start')![0].body).toEqual(original);
    expect(sessionStorage.length).toBe(0);
  });

  it('settles an uncertain launch from its exact server record without displaying a rejected launch', async () => {
    const transport = new MockControlTransport();
    let admitted: TrialJob | undefined;
    const calls = vi.spyOn(transport, 'request').mockImplementation(async (request) => {
      if (request.pathId === 'agent.eval-lab.trials.start') {
        admitted = job('running', (request.body as { clientRequestId: string }).clientRequestId);
        throw new Error('lost receipt after admission');
      }
      return read(admitted ? [admitted] : []);
    });
    mount(transport);
    fireEvent.click(await screen.findByRole('button', { name: '运行验证' }));
    expect(await screen.findByText('正在运行')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('button', { name: '核对本次启动' })).not.toBeInTheDocument());
    expect(screen.queryByText('这组设置未能启动。请检查模型与场景执行环境后重试。')).not.toBeInTheDocument();
    expect(calls.mock.calls.filter(([request]) => request.pathId === 'agent.eval-lab.trials.start')).toHaveLength(1);
  });

  it('shows a retained running job before newer terminal history on restoration', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockResolvedValue(read([
      { ...job('completed'), jobId: 'newer-completed', createdAtMs: 3000 },
      job('running'),
    ]));
    mount(transport);
    expect(await screen.findByRole('button', { name: '停止实验' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '运行验证' })).not.toBeInTheDocument();
  });

  it.each(['failed', 'interrupted', 'cancelled'] as const)('keeps %s separate from successful evaluation and retains actual cost', async (state) => {
    const transport = new MockControlTransport();
    const current = { ...job(state), result: { status: state, qualityVerdict: 'reject', cost: { available: true, estimatedCostUsd: 0.12, currency: 'USD' } } };
    vi.spyOn(transport, 'request').mockResolvedValue(read([current]));
    mount(transport);
    expect(await screen.findByText({ failed: '执行失败', interrupted: '执行中断', cancelled: '已停止' }[state])).toBeInTheDocument();
    expect(screen.getByText('本次执行已记录的估算 API 成本')).toBeInTheDocument();
    expect(screen.getByText('$0.1200')).toBeInTheDocument();
    expect(screen.queryByText('已完成')).not.toBeInTheDocument();
    expect(screen.queryByText('未达到验收标准')).not.toBeInTheDocument();
  });

  it('shows a quality-negative report as completed evaluation without implying it passed', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockResolvedValue(read([{ ...job('completed'), result: {
      status: 'completed', metrics: { agentic: { citationFactCoverage: 0.75 } },
      signals: { qualityVerdict: 'reject', candidateAware: true }, cost: { available: false },
    } }]));
    mount(transport);
    expect(await screen.findByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('未达到验收标准')).toBeInTheDocument();
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(screen.queryByText('验收通过')).not.toBeInTheDocument();
    expect(screen.getByText('本次使用已参与调优的验证案例，不能代表独立评测结果。')).toBeInTheDocument();
  });

  it('projects Memory report fields and marks synthetic evidence explicitly', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockResolvedValue(read([{ ...job('completed'), sceneId: 'memory', result: {
      qualityVerdict: 'pass', metrics: { curation: { sourceCount: 5, ok: true }, retrieval: { caseCount: 4, passed: false } },
      signals: { syntheticFixture: true }, cost: { available: true, estimatedCostUsd: 0.02, currency: 'USD' },
    } }], ['memory']));
    mount(transport, 'memory');
    expect(await screen.findByText('验收通过')).toBeInTheDocument();
    expect(screen.getByText('记忆维护 · 来源数')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('未通过')).toBeInTheDocument();
    expect(screen.getByText('$0.0200')).toBeInTheDocument();
    expect(screen.getByText('本次使用合成案例，仅验证记忆流程。')).toBeInTheDocument();
    expect(screen.queryByLabelText('候选补充提示词')).not.toBeInTheDocument();
  });

  it.each(['', -1, '-0.1'])('leaves absent verdicts and invalid cost %j unavailable', async (totalCostUsd) => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockResolvedValue(read([{ ...job('completed'), result: { caseCount: -1, cost: { available: true, totalCostUsd, currency: 'USD' } } }]));
    mount(transport);
    expect(await screen.findByText('尚无可核对的质量结论')).toBeInTheDocument();
    expect(screen.queryByText('$0.0000')).not.toBeInTheDocument();
    expect(screen.queryByText('-1 个')).not.toBeInTheDocument();
  });

  it('does not describe a missing report as measured results', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockResolvedValue(read([{ ...job('completed'), result: null }]));
    mount(transport);
    expect(await screen.findByText('执行已结束，但尚无可核对的评测报告。')).toBeInTheDocument();
    expect(screen.queryByText(/本次结果来自所选验证案例/u)).not.toBeInTheDocument();
  });

  it('clears a definitively rejected launch and leaves the settings available for correction', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockImplementation(async (request) => {
      if (request.pathId === 'agent.eval-lab.trials.start') throw Object.assign(new Error('host assets unavailable'), { status: 422 });
      return read();
    });
    mount(transport);
    fireEvent.click(await screen.findByRole('button', { name: '运行验证' }));
    expect(await screen.findByText('这组设置未能启动。请检查模型与场景执行环境后重试。')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '核对本次启动' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '运行验证' })).toBeEnabled();
    expect(sessionStorage.length).toBe(0);
  });

  it('shows measured results without declaring an improvement over another run', async () => {
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockResolvedValue(read([job('completed')]));
    mount(transport);
    expect(await screen.findByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('联合根因命中（JRA）')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByText('$0.3341')).toBeInTheDocument();
    expect(screen.queryByText(/节省|最优配置|提升了/u)).not.toBeInTheDocument();
  });

  it('rejects malformed list states instead of displaying fabricated running jobs', () => {
    expect(() => parseTrialList({ ...read(), jobs: [{ ...job('running'), state: 'made-up' }] })).toThrow();
    expect(() => parseTrialList({ ...read(), registeredSceneIds: null })).toThrow();
  });
});
