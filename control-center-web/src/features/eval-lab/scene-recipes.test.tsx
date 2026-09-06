import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { HttpControlTransport } from '@/platform/http-transport';
import type { ControlTransport } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { ExperimentApplication } from './ExperimentApplication';
import {
  ENTERPRISE_RAG_RECIPE_EXPERIMENT_ID as EXPERIMENT_ID,
  ENTERPRISE_RAG_SCENE_ID as SCENE_ID,
  type SceneRecipeState,
  type SceneRecipeVersion,
} from './scene-recipes';

afterEach(() => { cleanup(); window.sessionStorage.clear(); });

const incumbent: SceneRecipeVersion = {
  schemaVersion: 'rag-ime.agent-lab-scene-recipe-version.v1', sceneId: SCENE_ID,
  versionId: 'enterprise-rag.validation.incumbent.v1', title: '内置默认', origin: 'runner_builtin',
  recipe: { provider: 'openai-codex', model: 'gpt-5.6-sol', thinkingLevel: 'max', promptProfile: 'incumbent', promptContractVersion: 'rag-agent-evidence-state-budget-routing-v19', agenticSupplementalLimit: 6, answerOnly: true, developmentOnly: true, split: 'validation', candidateAware: true, unbiasedPromotionClaimAllowed: false },
  sourceExperimentId: '', sourceCandidateRunId: '',
};
const candidate: SceneRecipeVersion = {
  ...incumbent, versionId: 'enterprise-rag.validation.luna-prompt-v4-r6.v1', title: 'Luna Prompt-v4', origin: 'registered_candidate',
  recipe: { ...incumbent.recipe, model: 'gpt-5.6-luna', promptProfile: 'coverage-balanced-evidence-gate-v4' },
  sourceExperimentId: EXPERIMENT_ID, sourceCandidateRunId: 'enterprise-rag-luna-max-coverage-balanced-v4-20260904-r4',
};

function state(revision = 0): SceneRecipeState {
  const applied = revision % 2 === 1;
  const activeVersion = applied ? candidate : incumbent;
  return {
    schemaVersion: 'rag-ime.agent-lab-scene-recipe-state.v1', ok: true, sceneId: SCENE_ID, revision,
    activeVersion, previousVersion: applied ? incumbent : null, rollbackAvailable: applied,
    candidate: { available: !applied, reasonCode: applied ? 'already_active' : '', reason: '', experimentId: EXPERIMENT_ID, version: candidate },
    lastEvent: revision ? {
      schemaVersion: 'rag-ime.agent-lab-scene-recipe-event.v1', eventId: `event-${revision}`, sceneId: SCENE_ID, revision,
      operation: applied ? 'apply' : 'rollback', clientRequestId: `accepted-${revision}`,
      fromVersionId: applied ? incumbent.versionId : candidate.versionId, versionId: activeVersion.versionId,
      sourceExperimentId: activeVersion.sourceExperimentId, sourceCandidateRunId: activeVersion.sourceCandidateRunId,
      sourceExperimentRevision: '', createdAtMs: 1000 + revision, effectScope: 'future_validation_runs',
    } : null,
    effectScope: 'future_validation_runs',
  };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const appliedReceipt = (command: Record<string, unknown>, revision = 1, replayed = false) => ({
  ...state(revision), event: { ...state(revision).lastEvent!, clientRequestId: command.clientRequestId }, replayed,
});

function mount(transport: ControlTransport, experimentId = EXPERIMENT_ID, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return {
    client,
    ...render(<QueryClientProvider client={client}><ControlTransportProvider transport={transport}><ExperimentApplication experiment={{ experimentId }} /></ControlTransportProvider></QueryClientProvider>),
  };
}

describe('Scene recipe application recovery', () => {
  it('keeps an accepted apply receipt when the follow-up state read fails', async () => {
    let accepted = false;
    let unavailable = true;
    const transport = new MockControlTransport();
    vi.spyOn(transport, 'request').mockImplementation(async (request) => {
      if (request.pathId === 'agent.eval-lab.scene-recipes.apply') {
        accepted = true;
        return appliedReceipt(request.body as Record<string, unknown>);
      }
      if (accepted && unavailable) throw new Error('read unavailable');
      return state(accepted ? 1 : 0);
    });
    mount(transport);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: '应用到场景' }));
    await screen.findByText('场景服务暂不可用，当前生效版本尚未确认。');
    expect(screen.getByLabelText('当前生效版本')).toHaveTextContent('gpt-5.6-luna');
    expect(screen.getByText('已应用候选 · 场景版本 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '返回上版' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '应用到场景' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重试应用' })).not.toBeInTheDocument();
    unavailable = false;
    await user.click(screen.getByRole('button', { name: '刷新状态' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '返回上版' })).toBeEnabled());
  });

  it.each(['network', 500, 503])('restores an uncertain %s command after reload, retries only on click, and preserves current state after an old replay', async (failure) => {
    let current = state();
    const commands: Record<string, unknown>[] = [];
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method !== 'POST') return json(current);
      const command = JSON.parse(String(init.body));
      commands.push(command);
      if (commands.length === 1) {
        current = state(1);
        if (failure === 'network') throw new TypeError('response lost after commit');
        return json({ ok: false, code: failure === 503 ? 'AGENT_LAB_SCENE_RECIPE_SERVICE_UNAVAILABLE' : 'AGENT_LAB_SCENE_RECIPE_INTERNAL_ERROR' }, Number(failure));
      }
      return json(appliedReceipt(command, 1, true));
    });
    const first = mount(new HttpControlTransport({ baseUrl: 'http://127.0.0.1:8766', fetch: fetchMock }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: '应用到场景' }));
    expect(await screen.findByRole('button', { name: '重试应用' })).toBeEnabled();
    expect(commands).toHaveLength(1);
    expect(window.sessionStorage.length).toBe(1);
    first.unmount(); first.client.clear();

    // Another admitted operation has already returned to the builtin version.
    current = state(2);
    mount(new HttpControlTransport({ baseUrl: 'http://127.0.0.1:8766/', fetch: fetchMock }));
    expect(await screen.findByLabelText('当前生效版本')).toHaveTextContent('gpt-5.6-sol');
    expect(screen.getByRole('button', { name: '重试应用' })).toBeEnabled();
    expect(commands).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: '重试应用' }));
    await screen.findByRole('button', { name: '应用到场景' });
    expect(commands).toEqual([commands[0], commands[0]]);
    expect(screen.getByLabelText('当前生效版本')).toHaveTextContent('gpt-5.6-sol');
    expect(screen.getByText('已返回上版 · 场景版本 2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '重试应用' })).not.toBeInTheDocument();
    expect(window.sessionStorage.length).toBe(0);
  });

  it('keeps an unknown operation on its HTTP connection when the app switches servers', async () => {
    const firstFetch = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') throw new TypeError('connection interrupted');
      return json(state());
    });
    const first = mount(new HttpControlTransport({ baseUrl: 'http://127.0.0.1:8766', fetch: firstFetch }));
    await userEvent.setup().click(await screen.findByRole('button', { name: '应用到场景' }));
    await screen.findByRole('button', { name: '重试应用' });
    first.unmount();
    const secondFetch = vi.fn(async () => json(state()));
    const second = mount(new HttpControlTransport({ baseUrl: 'http://127.0.0.1:9876', fetch: secondFetch }), EXPERIMENT_ID, first.client);
    expect(await screen.findByRole('button', { name: '应用到场景' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: '重试应用' })).not.toBeInTheDocument();
    expect(secondFetch.mock.calls).toHaveLength(1);
    second.unmount();
    mount(new HttpControlTransport({ baseUrl: 'http://127.0.0.1:8766', fetch: firstFetch }));
    await screen.findByRole('button', { name: '重试应用' });
    expect(firstFetch.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });

  it('does not persist commands for transports without a verifiable connection identity', async () => {
    const transport = () => new MockControlTransport({ routes: {
      'agent.eval-lab.scene-recipes.get': state(),
      'agent.eval-lab.scene-recipes.apply': () => { throw new TypeError('unknown connection'); },
    } });
    const first = mount(transport());
    await userEvent.setup().click(await screen.findByRole('button', { name: '应用到场景' }));
    await screen.findByRole('button', { name: '重试应用' });
    expect(window.sessionStorage.length).toBe(0);
    first.unmount(); first.client.clear();
    mount(transport());
    await screen.findByRole('button', { name: '应用到场景' });
    expect(screen.queryByRole('button', { name: '重试应用' })).not.toBeInTheDocument();
  });

  it.each([
    [409, 'AGENT_LAB_SCENE_RECIPE_CONFLICT'],
    [422, 'AGENT_LAB_SCENE_RECIPE_UNAVAILABLE'],
  ])('refreshes after a known %s rejection and allows a new request at the current revision', async (status, code) => {
    let current = state();
    const commands: Record<string, unknown>[] = [];
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method !== 'POST') return json(current);
      const command = JSON.parse(String(init.body)); commands.push(command);
      if (commands.length === 1) { current = state(2); return json({ ok: false, code, error: '请核对当前版本。', currentRevision: 2 }, Number(status)); }
      current = state(3); return json(appliedReceipt(command, 3));
    });
    mount(new HttpControlTransport({ baseUrl: 'http://127.0.0.1:8766', fetch: fetchMock }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: '应用到场景' }));
    await screen.findByText('已返回上版 · 场景版本 2');
    await waitFor(() => expect(screen.getByRole('button', { name: '应用到场景' })).toBeEnabled());
    expect(screen.queryByRole('button', { name: '重试应用' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '应用到场景' }));
    await screen.findByText('已应用候选 · 场景版本 3');
    expect(commands[0]?.expectedRevision).toBe(0);
    expect(commands[1]?.expectedRevision).toBe(2);
    expect(commands[1]?.clientRequestId).not.toBe(commands[0]?.clientRequestId);
    expect(window.sessionStorage.length).toBe(0);
  });

  it.each(['clientRequestId', 'operation'] as const)('does not accept a receipt whose %s belongs to a different command', async (field) => {
    const commands: Record<string, unknown>[] = [];
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method !== 'POST') return json(state());
      const command = JSON.parse(String(init.body)); commands.push(command);
      const receipt = appliedReceipt(command);
      return json({ ...receipt, event: { ...receipt.event, [field]: field === 'operation' ? 'rollback' : 'some-other-request' } });
    });
    mount(new HttpControlTransport({ baseUrl: 'http://127.0.0.1:8766', fetch: fetchMock }));
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: '应用到场景' }));
    await screen.findByRole('button', { name: '重试应用' });
    expect(screen.getByLabelText('当前生效版本')).toHaveTextContent('gpt-5.6-sol');
    await user.click(screen.getByRole('button', { name: '重试应用' }));
    await waitFor(() => expect(commands).toHaveLength(2));
    expect(commands[1]).toEqual(commands[0]);
    expect(window.sessionStorage.length).toBe(1);
  });

  it('keeps service failures readable and restores the application route through an explicit refresh', async () => {
    let unavailable = true;
    const fetchMock = vi.fn(async () => unavailable ? json({ ok: false, code: 'AGENT_LAB_SCENE_RECIPE_SERVICE_UNAVAILABLE' }, 503) : json(state()));
    mount(new HttpControlTransport({ baseUrl: 'http://127.0.0.1:8766', fetch: fetchMock }));
    await screen.findByText('场景服务暂不可用，当前生效版本尚未确认。');
    expect(screen.queryByRole('button', { name: '应用到场景' })).not.toBeInTheDocument();
    unavailable = false;
    await userEvent.setup().click(screen.getByRole('button', { name: '刷新状态' }));
    expect(await screen.findByRole('button', { name: '应用到场景' })).toBeEnabled();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not request scene recipes or offer an application action for an unsupported experiment', () => {
    const transport = new MockControlTransport();
    mount(transport, 'cloud-ops-diagnostic');
    expect(screen.getByText('这个实验尚未接入场景版本管理。实验结论与原始证据可继续查看。')).toBeInTheDocument();
    expect(transport.requests).toHaveLength(0);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
