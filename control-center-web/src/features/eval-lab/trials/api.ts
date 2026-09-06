import { skipToken, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useControlTransport } from '@/app/control-transport';
import type { JsonValue } from '@/platform/transport';
import { labConnectionKey, requestLabControl } from '../control-request';

const schema = 'rag-ime.agent-lab-trial.v1';
const states = ['queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled', 'interrupted'] as const;
export type TrialJob = {
  jobId: string; clientRequestId: string; sceneId: string; state: typeof states[number];
  publicSpec: Record<string, unknown>; cancelRequested: boolean; progress: string;
  sessions: Array<{ sessionId: string; turnId: string }>;
  result: Record<string, unknown> | null; error: string; createdAtMs: number; updatedAtMs: number; resumeAvailable: false;
};
type TrialList = { schemaVersion: typeof schema; jobs: TrialJob[]; registeredSceneIds: string[] };
type StartCommand = { clientRequestId: string; sceneId: string; spec: Record<string, JsonValue> };
type Pending = { command: StartCommand; outcome: 'sending' | 'unknown' };
export const activeTrial = (job: TrialJob) => ['queued', 'running', 'cancelling'].includes(job.state);
export const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0;
const record = (value: unknown) => value !== null && typeof value === 'object' && !Array.isArray(value);

function isJob(value: unknown): value is TrialJob {
  const job = object(value);
  return ['jobId', 'clientRequestId', 'sceneId'].every((key) => text(job[key]))
    && states.includes(job.state as TrialJob['state']) && record(job.publicSpec)
    && typeof job.progress === 'string' && typeof job.error === 'string'
    && typeof job.cancelRequested === 'boolean' && job.resumeAvailable === false
    && ['createdAtMs', 'updatedAtMs'].every((key) => typeof job[key] === 'number' && Number.isSafeInteger(job[key]) && job[key] >= 0)
    && Array.isArray(job.sessions) && job.sessions.every((value) => { const binding = object(value); return text(binding.sessionId) && typeof binding.turnId === 'string'; })
    && (job.result === null || record(job.result));
}

export function parseTrialList(value: unknown): TrialList {
  const data = object(value);
  if (data.schemaVersion !== schema || !Array.isArray(data.jobs) || !data.jobs.every(isJob)
    || !Array.isArray(data.registeredSceneIds) || !data.registeredSceneIds.every(text)) throw new Error('实验状态不完整，请重新读取。');
  return data as TrialList;
}

function receipt(value: unknown): TrialJob {
  const data = object(value);
  if (data.schemaVersion !== schema || !isJob(data.job)) throw new Error('实验回执不完整，请核对本次操作。');
  return data.job;
}

function rejection(error: unknown): boolean {
  const value = object(error); const details = object(value.details);
  const status = value.status ?? details.status ?? details.statusCode;
  return status === 409 || status === 422 || status === 404;
}

function restore(key: string, sceneId: string): Pending | null {
  try {
    const command = object(JSON.parse(sessionStorage.getItem(key) ?? 'null'));
    return text(command.clientRequestId) && command.sceneId === sceneId && record(command.spec)
      ? { command: command as StartCommand, outcome: 'unknown' } : null;
  } catch { return null; }
}

/** Trial records are append-only, and terminal receipts cannot be rewritten. */
function mergeJobs(previous: TrialJob[] = [], observed: TrialJob[]): TrialJob[] {
  const jobs = new Map(previous.map((job) => [job.jobId, job]));
  for (const job of observed) {
    const known = jobs.get(job.jobId);
    if (known && (!activeTrial(known) || known.updatedAtMs > job.updatedAtMs
      || known.updatedAtMs === job.updatedAtMs && states.indexOf(known.state) > states.indexOf(job.state))) continue;
    jobs.set(job.jobId, job);
  }
  return [...jobs.values()].sort((left, right) => right.createdAtMs - left.createdAtMs || right.jobId.localeCompare(left.jobId));
}

export function useSceneTrials(sceneId: string) {
  const transport = useControlTransport();
  const client = useQueryClient();
  const connection = labConnectionKey(transport);
  const queryKey = ['agent-lab-trials', connection] as const;
  const commandKey = ['agent-lab-trial-command', connection, sceneId] as const;
  const failureKey = ['agent-lab-trial-start-failure', connection, sceneId] as const;
  const viewKey = ['agent-lab-trial-view', connection, sceneId] as const;
  type View = { selectedJobId: string; resultRequestId: string; model: string; prompt: string };
  const initialView: View = { selectedJobId: '', resultRequestId: '', model: '', prompt: '' };
  // Only unfinished input and the chosen record live here. Execution stays in server receipts.
  const view = useQuery<View>({ queryKey: viewKey, queryFn: skipToken, initialData: initialView, gcTime: Infinity });
  const storageKey = `paw.lab.trial-command.v1:${connection}:${sceneId}`;
  const save = (value: Pending | null) => {
    client.setQueryData(commandKey, value);
    try { if (value) sessionStorage.setItem(storageKey, JSON.stringify(value.command)); else sessionStorage.removeItem(storageKey); } catch { /* Query cache still preserves the pending command. */ }
  };
  const observe = (job: TrialJob) => client.setQueryData<TrialList>(queryKey, (previous) => ({
    schemaVersion: schema, jobs: mergeJobs(previous?.jobs, [job]), registeredSceneIds: previous?.registeredSceneIds ?? [],
  }));
  const query = useQuery({
    queryKey, queryFn: async ({ signal }) => {
      const observed = parseTrialList(await requestLabControl(transport, { pathId: 'agent.eval-lab.trials.get', signal }));
      return { ...observed, jobs: mergeJobs(client.getQueryData<TrialList>(queryKey)?.jobs, observed.jobs) };
    },
    retry: false, refetchOnWindowFocus: true,
    refetchInterval: (query) => query.state.status !== 'error' && query.state.data?.jobs.some(activeTrial) ? 2000 : false,
    refetchIntervalInBackground: false,
  });
  const pending = useQuery<Pending | null>({ queryKey: commandKey, queryFn: skipToken, initialData: () => restore(storageKey, sceneId), gcTime: Infinity });
  const startFailure = useQuery<{ clientRequestId: string } | null>({ queryKey: failureKey, queryFn: skipToken, initialData: null, gcTime: Infinity });
  const mutation = useMutation({
    retry: false,
    mutationFn: async (command: StartCommand) => {
      save({ command, outcome: 'sending' });
      try {
        const raw = await requestLabControl(transport, { pathId: 'agent.eval-lab.trials.start', body: command });
        const job = receipt(raw);
        if (job.clientRequestId !== command.clientRequestId || job.sceneId !== command.sceneId || typeof object(raw).replayed !== 'boolean') throw new Error('实验回执与本次启动不匹配。');
        observe(job);
        save(null);
        return job;
      } catch (error) {
        if (rejection(error)) client.setQueryData(failureKey, { clientRequestId: command.clientRequestId });
        save(rejection(error) ? null : { command, outcome: 'unknown' });
        throw error;
      }
    },
    onSettled: () => client.invalidateQueries({ queryKey }),
  });
  const stop = useMutation({
    retry: false,
    mutationFn: async (jobId: string) => {
      const job = receipt(await requestLabControl(transport, { pathId: 'agent.eval-lab.trials.cancel', body: { jobId } }));
      if (job.jobId !== jobId || job.sceneId !== sceneId) throw new Error('停止回执与本次实验不匹配。');
      observe(job);
      return job;
    },
    onSettled: () => client.invalidateQueries({ queryKey }),
  });
  useEffect(() => {
    // Restore the chosen command before its matching receipt clears recovery.
    // A more recent historical job is not the result of this startup request.
    if (pending.data) client.setQueryData<View>(viewKey, (current) => current?.selectedJobId || current?.resultRequestId ? current
      : { ...initialView, ...current, resultRequestId: pending.data!.command.clientRequestId });
    if (pending.data && query.data?.jobs.some((job) => job.clientRequestId === pending.data!.command.clientRequestId && job.sceneId === sceneId)) save(null);
    // Server receipts settle only their matching command, including after reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending.data, query.data, sceneId]);
  return {
    query, mutation, stop, pending: pending.data, startFailure: startFailure.data,
    view: view.data ?? initialView,
    updateView(patch: Partial<View>) { client.setQueryData<View>(viewKey, (current) => ({ ...initialView, ...view.data, ...current, ...patch })); },
    startError: Boolean((startFailure.data || mutation.isError) && !query.data?.jobs.some((job) => job.clientRequestId === (startFailure.data?.clientRequestId ?? mutation.variables?.clientRequestId) && job.sceneId === sceneId)),
    jobs: query.data?.jobs.filter((job) => job.sceneId === sceneId) ?? [],
    registered: query.data?.registeredSceneIds.includes(sceneId) ?? false,
    start(spec: Record<string, JsonValue>) {
      if (client.getQueryData<Pending | null>(commandKey)
        || client.getQueryData<TrialList>(queryKey)?.jobs.some((job) => job.sceneId === sceneId && activeTrial(job))) return;
      const command = { clientRequestId: `lab:${crypto.randomUUID()}`, sceneId, spec: structuredClone(spec) };
      client.setQueryData<View>(viewKey, (current) => ({ ...initialView, ...current, selectedJobId: '', resultRequestId: command.clientRequestId }));
      client.setQueryData(failureKey, null);
      save({ command, outcome: 'sending' });
      mutation.mutate(command);
      return command.clientRequestId;
    },
    retryStart() {
      const current = client.getQueryData<Pending | null>(commandKey);
      if (current?.outcome === 'unknown') {
        save({ command: current.command, outcome: 'sending' });
        mutation.mutate(current.command);
      }
    },
  };
}
