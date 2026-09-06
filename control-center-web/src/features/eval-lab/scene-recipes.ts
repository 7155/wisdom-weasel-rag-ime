import { skipToken, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useControlTransport } from '@/app/control-transport';
import type { ControlTransport } from '@/platform/transport';

export const ENTERPRISE_RAG_SCENE_ID = 'agent-lab.enterprise-rag.validation';
export const ENTERPRISE_RAG_RECIPE_EXPERIMENT_ID = 'enterprise-rag.luna-prompt-v4-standard-r6.v1';

export type SceneRecipe = {
  provider: string;
  model: string;
  thinkingLevel: string;
  promptProfile: string;
  promptContractVersion: string;
  agenticSupplementalLimit: number;
  answerOnly: true;
  developmentOnly: true;
  split: 'validation';
  candidateAware: true;
  unbiasedPromotionClaimAllowed: false;
};

export type SceneRecipeVersion = {
  schemaVersion: 'rag-ime.agent-lab-scene-recipe-version.v1';
  sceneId: string;
  versionId: string;
  title: string;
  origin: 'runner_builtin' | 'registered_candidate';
  recipe: SceneRecipe;
  sourceExperimentId: string;
  sourceCandidateRunId: string;
};

export type SceneRecipeEvent = {
  schemaVersion: 'rag-ime.agent-lab-scene-recipe-event.v1';
  eventId: string;
  sceneId: string;
  revision: number;
  operation: 'apply' | 'rollback';
  clientRequestId: string;
  fromVersionId: string;
  versionId: string;
  sourceExperimentId: string;
  sourceCandidateRunId: string;
  sourceExperimentRevision: string;
  createdAtMs: number;
  effectScope: 'future_validation_runs';
};

export type SceneRecipeState = {
  schemaVersion: 'rag-ime.agent-lab-scene-recipe-state.v1';
  ok: true;
  sceneId: string;
  revision: number;
  activeVersion: SceneRecipeVersion;
  previousVersion: SceneRecipeVersion | null;
  rollbackAvailable: boolean;
  candidate: { available: boolean; reasonCode: string; reason: string; experimentId: string; version: SceneRecipeVersion | null };
  lastEvent: SceneRecipeEvent | null;
  effectScope: 'future_validation_runs';
};

export type SceneRecipeBinding = {
  schemaVersion: 'rag-ime.agent-lab-scene-recipe-binding.v1';
  sceneId: string;
  revision: number;
  versionId: string;
  recipe: SceneRecipe;
  effectScope: 'future_validation_runs';
};

export type SceneRecipeReceipt = SceneRecipeState & { event: SceneRecipeEvent; replayed: boolean };
export type SceneRecipeCommand = {
  operation: 'apply' | 'rollback';
  sceneId: string;
  experimentId?: string;
  expectedRevision: number;
  clientRequestId: string;
};
type PendingCommand = { command: SceneRecipeCommand; outcome: 'sending' | 'unknown' };

export function sceneRecipeIdForExperiment(experimentId: string): string | undefined {
  return experimentId === ENTERPRISE_RAG_RECIPE_EXPERIMENT_ID ? ENTERPRISE_RAG_SCENE_ID : undefined;
}

export const sceneRecipeKeys = {
  state: (connection: string, sceneId: string, experimentId = '') => ['agent-lab-scene-recipe', connection, sceneId, experimentId] as const,
  command: (connection: string, sceneId: string) => ['agent-lab-scene-recipe-command', connection, sceneId] as const,
};

export async function getSceneRecipeState(transport: ControlTransport, sceneId: string, experimentId = '', signal?: AbortSignal): Promise<SceneRecipeState> {
  const response = await transport.request({
    pathId: 'agent.eval-lab.scene-recipes.get',
    query: { sceneId, ...(experimentId ? { experimentId } : {}) },
    ...(signal ? { signal } : {}),
  });
  return parseSceneRecipeState(response, sceneId);
}

export function bindSceneRecipeState(state: SceneRecipeState): SceneRecipeBinding {
  return {
    schemaVersion: 'rag-ime.agent-lab-scene-recipe-binding.v1',
    sceneId: state.sceneId,
    revision: state.revision,
    versionId: state.activeVersion.versionId,
    recipe: { ...state.activeVersion.recipe },
    effectScope: state.effectScope,
  };
}

export async function submitSceneRecipeCommand(transport: ControlTransport, command: SceneRecipeCommand): Promise<SceneRecipeReceipt> {
  const { operation, experimentId, ...body } = command;
  const response = await transport.request({
    pathId: operation === 'apply' ? 'agent.eval-lab.scene-recipes.apply' : 'agent.eval-lab.scene-recipes.rollback',
    body: { ...body, ...(operation === 'apply' ? { experimentId } : {}) },
  });
  const state = parseSceneRecipeState(response, command.sceneId);
  const receipt = object(response);
  if (!isSceneRecipeEvent(receipt.event, command.sceneId) || typeof receipt.replayed !== 'boolean'
    || receipt.event.clientRequestId !== command.clientRequestId || receipt.event.operation !== operation) throw new Error('场景操作回执与本次请求不匹配。');
  return { ...state, event: receipt.event, replayed: receipt.replayed };
}

export function useSceneRecipeState(sceneId: string | undefined, experimentId: string) {
  const transport = useControlTransport();
  const client = useQueryClient();
  const connection = connectionKey(transport);
  const queryKey = sceneRecipeKeys.state(connection, sceneId ?? '', experimentId);
  return useQuery({
    queryKey,
    queryFn: sceneId ? async ({ signal }) => {
      const observed = await getSceneRecipeState(transport, sceneId, experimentId, signal);
      const known = client.getQueryData<SceneRecipeState>(queryKey);
      return known && known.revision > observed.revision ? known : observed;
    } : skipToken,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
}

/** Keep an uncertain command across App-step remounts until its receipt is known. */
export function useSceneRecipeActions(sceneId: string, experimentId: string) {
  const transport = useControlTransport();
  const client = useQueryClient();
  const connection = connectionKey(transport);
  const commandKey = sceneRecipeKeys.command(connection, sceneId);
  const pending = useQuery<PendingCommand | null>({ queryKey: commandKey, queryFn: skipToken, initialData: () => restoredCommand(transport, sceneId), gcTime: Infinity });
  const mutation = useMutation({
    retry: false,
    mutationFn: async (command: SceneRecipeCommand) => {
      client.setQueryData<PendingCommand>(commandKey, { command, outcome: 'sending' });
      persistCommand(transport, sceneId, command);
      try {
        const receipt = await submitSceneRecipeCommand(transport, command);
        client.setQueryData<SceneRecipeState>(sceneRecipeKeys.state(connection, sceneId, experimentId), (known) => known && known.revision > receipt.revision ? known : receipt);
        client.setQueryData(commandKey, null);
        persistCommand(transport, sceneId, null);
        return receipt;
      } catch (error) {
        client.setQueryData(commandKey, isSceneRecipeRejection(error) ? null : { command, outcome: 'unknown' });
        if (isSceneRecipeRejection(error)) persistCommand(transport, sceneId, null);
        throw error;
      }
    },
    onSettled: async (_receipt, error) => {
      // Confirm current availability after the receipt or a known rejection.
      if (!error || isSceneRecipeRejection(error)) await client.invalidateQueries({ queryKey: ['agent-lab-scene-recipe', connection, sceneId] });
    },
  });
  return {
    pending: pending.data ?? null,
    mutation,
    submit(operation: SceneRecipeCommand['operation'], revision: number) {
      const existing = client.getQueryData<PendingCommand | null>(commandKey);
      if (existing?.outcome === 'sending' || (existing && existing.command.operation !== operation)) return;
      mutation.mutate(existing?.command ?? {
        operation, sceneId, ...(operation === 'apply' ? { experimentId } : {}),
        expectedRevision: revision, clientRequestId: `lab-scene:${crypto.randomUUID()}`,
      });
    },
  };
}

export function isSceneRecipeRejection(error: unknown): boolean {
  const payload = sceneRecipeErrorPayload(error);
  return payload.code === 'AGENT_LAB_SCENE_RECIPE_CONFLICT' || payload.code === 'AGENT_LAB_SCENE_RECIPE_UNAVAILABLE';
}

export function sceneRecipeRejectionMessage(error: unknown): string {
  const payload = sceneRecipeErrorPayload(error);
  return isSceneRecipeRejection(error) && typeof payload.error === 'string' ? payload.error : '场景服务暂不可用，请刷新后重试。';
}

function sceneRecipeErrorPayload(error: unknown): Record<string, unknown> {
  const value = object(error);
  const details = object(value.details);
  return object(value.payload ?? details.payload ?? details.body ?? value.details ?? error);
}

export function isSceneRecipeBinding(value: unknown): value is SceneRecipeBinding {
  const binding = object(value);
  return binding.schemaVersion === 'rag-ime.agent-lab-scene-recipe-binding.v1'
    && binding.sceneId === ENTERPRISE_RAG_SCENE_ID && nonNegativeInteger(binding.revision)
    && text(binding.versionId) && binding.effectScope === 'future_validation_runs' && isRecipe(binding.recipe);
}

export function parseSceneRecipeState(value: unknown, sceneId: string): SceneRecipeState {
  const state = object(value);
  const candidate = object(state.candidate);
  if (state.schemaVersion !== 'rag-ime.agent-lab-scene-recipe-state.v1' || state.ok !== true
    || state.sceneId !== sceneId || !nonNegativeInteger(state.revision) || state.effectScope !== 'future_validation_runs'
    || !isVersion(state.activeVersion, sceneId) || !(state.previousVersion === null || isVersion(state.previousVersion, sceneId))
    || typeof state.rollbackAvailable !== 'boolean' || (state.rollbackAvailable && state.previousVersion === null)
    || typeof candidate.available !== 'boolean' || typeof candidate.reason !== 'string' || typeof candidate.reasonCode !== 'string' || typeof candidate.experimentId !== 'string'
    || !(candidate.version === null || isVersion(candidate.version, sceneId)) || (candidate.available && candidate.version === null)
    || !(state.lastEvent === null || isSceneRecipeEvent(state.lastEvent, sceneId))) throw new Error('场景版本状态不完整，请刷新后重试。');
  return state as SceneRecipeState;
}

function isVersion(value: unknown, sceneId: string): value is SceneRecipeVersion {
  const version = object(value);
  return version.schemaVersion === 'rag-ime.agent-lab-scene-recipe-version.v1' && version.sceneId === sceneId
    && text(version.versionId) && typeof version.title === 'string'
    && (version.origin === 'runner_builtin' || version.origin === 'registered_candidate')
    && typeof version.sourceExperimentId === 'string' && typeof version.sourceCandidateRunId === 'string' && isRecipe(version.recipe);
}

function isRecipe(value: unknown): value is SceneRecipe {
  const recipe = object(value);
  return ['provider', 'model', 'thinkingLevel', 'promptProfile', 'promptContractVersion'].every((key) => text(recipe[key]))
    && nonNegativeInteger(recipe.agenticSupplementalLimit) && recipe.answerOnly === true && recipe.developmentOnly === true
    && recipe.split === 'validation' && recipe.candidateAware === true && recipe.unbiasedPromotionClaimAllowed === false;
}

function isSceneRecipeEvent(value: unknown, sceneId: string): value is SceneRecipeEvent {
  const event = object(value);
  return event.schemaVersion === 'rag-ime.agent-lab-scene-recipe-event.v1' && event.sceneId === sceneId
    && text(event.eventId) && nonNegativeInteger(event.revision) && (event.operation === 'apply' || event.operation === 'rollback')
    && ['clientRequestId', 'fromVersionId', 'versionId'].every((key) => text(event[key]))
    && ['sourceExperimentId', 'sourceCandidateRunId', 'sourceExperimentRevision'].every((key) => typeof event[key] === 'string')
    && nonNegativeInteger(event.createdAtMs) && event.effectScope === 'future_validation_runs';
}

function object(value: unknown): Record<string, unknown> { return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {}; }
function text(value: unknown): value is string { return typeof value === 'string' && value.trim().length > 0; }
function nonNegativeInteger(value: unknown): value is number { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0; }

const transportInstances = new WeakMap<ControlTransport, string>();
function connectionKey(transport: ControlTransport): string {
  const origin = typeof window === 'undefined' ? 'non-browser' : window.location.origin;
  if (transport.connectionIdentity) return JSON.stringify([origin, transport.connectionIdentity]);
  let identity = transportInstances.get(transport);
  if (!identity) { identity = `${transport.kind}:${crypto.randomUUID()}`; transportInstances.set(transport, identity); }
  return identity;
}

function storageKey(transport: ControlTransport, sceneId: string): string | undefined {
  return transport.connectionIdentity ? `paw.lab.scene-command.v1:${connectionKey(transport)}:${sceneId}` : undefined;
}

function persistCommand(transport: ControlTransport, sceneId: string, command: SceneRecipeCommand | null): void {
  const key = storageKey(transport, sceneId);
  if (!key) return;
  try {
    if (command) window.sessionStorage.setItem(key, JSON.stringify(command));
    else window.sessionStorage.removeItem(key);
  } catch { /* The current App retains its command even if session storage is unavailable. */ }
}

function restoredCommand(transport: ControlTransport, sceneId: string): PendingCommand | null {
  const key = storageKey(transport, sceneId);
  if (!key) return null;
  try {
    const value = object(JSON.parse(window.sessionStorage.getItem(key) ?? 'null'));
    if (value.sceneId !== sceneId || !nonNegativeInteger(value.expectedRevision) || !text(value.clientRequestId)
      || value.clientRequestId.length > 240 || /[\u0000-\u001f]/u.test(value.clientRequestId)
      || (value.operation !== 'apply' && value.operation !== 'rollback')
      || (value.operation === 'apply' && value.experimentId !== ENTERPRISE_RAG_RECIPE_EXPERIMENT_ID)) return null;
    return { command: value as SceneRecipeCommand, outcome: 'unknown' };
  } catch { return null; }
}
