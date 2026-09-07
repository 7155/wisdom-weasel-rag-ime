import { QueryClient, QueryClientProvider, type UseQueryResult } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import type { ReactNode } from 'react';
import { ControlTransportProvider } from '@/app/control-transport';
import { MockControlTransport } from '@/test/mock-transport';
import { useLabArtifact, useLabProjects } from './api';
import type { LabProject } from './types';

const project = (patch: Partial<LabProject> = {}): LabProject => ({
  schemaVersion: 'rag-ime.agent-lab-project.v1', projectId: 'project-1', revision: 1, title: '售后助手', description: '让客服依据新的规则完成任务', briefVersion: 1,
  materialCount: 0, artifactCount: 0, guideSessionId: '', createdAtMs: 1, updatedAtMs: 1, materialSetId: '',
  materialSet: { materialSetId: '', version: 0, materials: [], createdAtMs: null }, materialVersions: [],
  intake: { state: 'needs_materials', requestedPath: '', resolvedPath: '', readCount: 0, readBytes: 0, skippedCount: 0, partial: false, issues: [], checkedAtMs: null },
  artifacts: [], bindings: [], workspace: { artifactOrder: [], primaryArtifactId: '', layout: 'split' }, workspaceBinding: null, ...patch,
});

const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });
it.each(['catalog', 'artifact'] as const)('recovers the initial %s read automatically and stops polling after success', async (kind) => {
  let offline = true;
  const artifact = { artifactId: 'artifact-1', revision: 1, title: '观察', kind: 'investigation', view: 'markdown', content: '已恢复的成果', summary: '', templateRef: null, actions: [], createdAtMs: 1, updatedAtMs: 1 };
  const transport = new MockControlTransport({ routes: { 'agent.eval-lab.projects.get': () => {
    if (offline) throw new Error('Failed to fetch');
    return { ok: true, items: [], project: kind === 'artifact' ? project() : null, supportedViews: ['markdown'], ...(kind === 'artifact' ? { artifact } : {}) };
  } } });
  const client = new QueryClient(); clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}><ControlTransportProvider transport={transport}>{children}</ControlTransportProvider></QueryClientProvider>;
  const useRead: () => UseQueryResult<unknown, Error> = kind === 'artifact' ? () => useLabArtifact('project-1', 'artifact-1', 1) : () => useLabProjects('').catalog;
  const { result } = renderHook(useRead, { wrapper });
  await waitFor(() => expect(result.current.isError).toBe(true));
  offline = false;
  await waitFor(() => expect(result.current.isSuccess).toBe(true), { timeout: 4500 });
  const settledReads = transport.requests.length;
  await new Promise((resolve) => setTimeout(resolve, 3300));
  expect(transport.requests).toHaveLength(settledReads);
  expect(transport.requests.every(({ request }) => request.pathId === 'agent.eval-lab.projects.get')).toBe(true);
});
