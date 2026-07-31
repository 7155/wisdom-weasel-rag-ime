import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { applyAgentSnapshot, createAgentProjection, type AgentSnapshot } from '@/contracts/agent-reducer';
import type { AgentEventV1 } from '@/contracts/generated/agent-event.v1';
import type { WorkspaceLspStatusV1 } from '@/contracts/generated/workspace-lsp-status.v1';
import type { CapabilityCatalog } from '@/features/plugins/capability-policy';
import type { ToolManifest } from '../types';
import {
  WorkspaceLspStatusView,
  projectWorkspaceLspStatus,
} from './WorkspaceLspStatusView';

afterEach(cleanup);

const sessionId = 'session-lsp';
const nowMs = Date.now();
const runtimeA = `workspace-lsp-${'a'.repeat(32)}`;
const runtimeB = `workspace-lsp-${'b'.repeat(32)}`;

const onlineManifest: ToolManifest = {
  schemaVersion: 'rag-ime.control-tool-manifest.v1',
  id: 'workspace_lsp',
  domain: 'workspace',
  displayName: '代码智能',
  description: '工作区语言服务器能力',
  category: 'workspace',
  riskLevel: 'R2',
  operationRisks: {
    status: 'R0', symbols: 'R0', hover: 'R0', definition: 'R0',
    references: 'R0', diagnostics: 'R0', rename: 'R2', code_action_apply: 'R2',
  },
  sessionModes: ['coordinator'],
  operations: ['status', 'symbols', 'hover', 'definition', 'references', 'diagnostics', 'rename', 'code_action_apply'],
  resultPresentation: 'tool_result',
  availability: 'online',
  version: '1',
};

describe('WorkspaceLspStatusView', () => {
  it('renders standard catalog availability without inventing frontend process state', () => {
    const disabled = projectWorkspaceLspStatus(
      [{ ...onlineManifest, availability: 'disabled' }],
      'ready',
      undefined,
      capabilityCatalog(),
      nowMs,
    );
    expect(disabled.state).toBe('unavailable');
    expect(disabled.label).toBe('已停用');

    const missing = projectWorkspaceLspStatus(
      [onlineManifest],
      'ready',
      undefined,
      capabilityCatalog(),
      nowMs,
    );
    expect(missing.state).toBe('available');
    expect(missing.summary).toContain('历史工具回执不代表当前状态');
  });

  it('renders unavailable and degraded failures only from an unexpired runtime projection', () => {
    const unavailable = projectWorkspaceLspStatus(
      [onlineManifest],
      'ready',
      undefined,
      capabilityCatalog(runtimeStatus({
        state: 'unavailable',
        roots: [{
          root: '/workspace/app',
          state: 'unavailable',
          errorCode: 'no_server_configured',
          error: 'No matching executable was found',
          servers: [],
        }],
      })),
      nowMs,
    );
    expect(unavailable.state).toBe('unavailable');
    expect(unavailable.failure).toEqual({
      code: 'no_server_configured',
      message: 'No matching executable was found',
    });
    expect(unavailable.guidance).toContain('安装并配置');

    const degraded = projectWorkspaceLspStatus(
      [onlineManifest],
      'ready',
      undefined,
      capabilityCatalog(runtimeStatus({
        state: 'degraded',
        roots: [{
          root: '/workspace/app',
          state: 'degraded',
          servers: [
            server('typescript-language-server', 'ready'),
            server('eslint', 'degraded', 'server_degraded', 'Initialization failed'),
          ],
        }],
      })),
      nowMs,
    );
    expect(degraded.state).toBe('degraded');
    expect(degraded.summary).toBe('1 / 2 个语言服务器就绪。');
    expect(degraded.failure).toEqual({ code: 'server_degraded', message: 'Initialization failed' });
  });

  it('renders ready roots and server state only inside disclosure', () => {
    const status = runtimeStatus({ roots: readyRoots() });
    render(
      <WorkspaceLspStatusView
        capabilityCatalog={capabilityCatalog(status)}
        tools={[onlineManifest]}
        catalogStatus="ready"
      />,
    );

    const liveStatus = screen.getByRole('status');
    expect(liveStatus).toHaveTextContent('workspace_lsp · 就绪');
    expect(liveStatus).toHaveTextContent('1 个语言服务器覆盖 1 个活动工作区');
    expect(screen.getByText(/查看 1 个活动工作区与 1 个语言服务器/).closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText('/workspace/app')).toBeInTheDocument();
    expect(screen.getByText('typescript-language-server')).toBeInTheDocument();
    expect(screen.getByText(/rename 与代码动作仍会先生成预览并等待审批/)).toBeInTheDocument();
  });

  it('prioritizes a governed write approval without inferring a write', () => {
    const projection = snapshotProjection(event(1, 'approval_required', {
      toolCallId: 'lsp-write-1',
      toolId: 'workspace_lsp',
      operation: 'rename',
      approvalRequired: true,
      approvalId: 'approval-lsp-1',
      approval: {
        approvalId: 'approval-lsp-1', sessionId, toolId: 'workspace_lsp', operation: 'rename',
        payloadSha256: 'c'.repeat(64), preview: { title: 'Rename symbol', summary: '1 file will change' },
        state: 'pending', riskLevel: 'R2',
      },
    }));
    const view = projectWorkspaceLspStatus(
      [onlineManifest], 'ready', projection,
      capabilityCatalog(runtimeStatus({ roots: readyRoots() })), nowMs,
    );

    expect(view.state).toBe('approval_pending');
    expect(view.summary).toContain('确认前不会写入');
    expect(view.guidance).toContain('审批卡片');
  });

  it('renders a stale preview refusal as a refusal rather than success', () => {
    const projection = snapshotProjection(event(1, 'tool_finished', {
      toolCallId: 'lsp-write-stale',
      toolName: 'workspace_lsp',
      args: { operation: 'code_action_apply' },
      isError: true,
      result: {
        schemaVersion: 'rag-ime.agent-tool-result.v1',
        ok: false,
        tool: 'workspace_lsp',
        operation: 'code_action_apply',
        error: 'workspace_lsp file changed after approval preview',
      },
    }));
    render(
      <WorkspaceLspStatusView
        capabilityCatalog={capabilityCatalog(runtimeStatus({ roots: readyRoots() }))}
        tools={[onlineManifest]}
        catalogStatus="ready"
        projection={projection}
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('预览已失效');
    expect(screen.getByRole('status')).toHaveTextContent('没有写入文件');
    const failureDisclosure = screen.getByText('查看失败信息').closest('details');
    expect(failureDisclosure).not.toHaveAttribute('open');
    expect(failureDisclosure).toHaveTextContent('workspace_lsp file changed after approval preview');
  });

  it('never treats historical status receipts as current when projection is missing or expired', () => {
    const historical = snapshotProjection(statusEvent(1, runtimeStatus({
      runtimeInstanceId: runtimeA,
      runtimeEpoch: 9,
      roots: [{ root: '/workspace/history', state: 'ready', servers: [server('history-server', 'ready')] }],
    })));
    const missing = projectWorkspaceLspStatus(
      [onlineManifest], 'ready', historical, capabilityCatalog(), nowMs,
    );
    expect(missing.label).toBe('可用 · 待确认');
    expect(missing.roots).toEqual([]);

    const expiredProjection = runtimeStatus({
      heartbeatExpiresAtMs: nowMs,
      roots: [{ root: '/workspace/expired', state: 'ready', servers: [server('expired-server', 'ready')] }],
    });
    const expired = projectWorkspaceLspStatus(
      [onlineManifest], 'ready', historical, capabilityCatalog(expiredProjection), nowMs,
    );
    expect(expired.label).toBe('状态已过期');
    expect(expired.roots).toEqual([]);
  });

  it('reconnects from the replacement catalog instance and epoch, never an older mismatched receipt', () => {
    const historical = snapshotProjection(statusEvent(1, runtimeStatus({
      runtimeInstanceId: runtimeA,
      runtimeEpoch: 99,
      roots: [{ root: '/workspace/history', state: 'ready', servers: [server('history-server', 'ready')] }],
    })));
    const first = runtimeStatus({
      runtimeInstanceId: runtimeA,
      runtimeEpoch: 1,
      roots: [{ root: '/workspace/old', state: 'ready', servers: [server('old-server', 'ready')] }],
    });
    const replacement = runtimeStatus({
      runtimeInstanceId: runtimeB,
      runtimeEpoch: 2,
      roots: readyRoots(),
    });
    const { rerender } = render(
      <WorkspaceLspStatusView
        capabilityCatalog={capabilityCatalog(first, 'catalog:1')}
        tools={[onlineManifest]}
        catalogStatus="ready"
        projection={historical}
      />,
    );
    expect(screen.getByText('/workspace/old')).toBeInTheDocument();
    expect(screen.queryByText('/workspace/history')).not.toBeInTheDocument();

    rerender(
      <WorkspaceLspStatusView
        capabilityCatalog={capabilityCatalog(replacement, 'catalog:2')}
        tools={[onlineManifest]}
        catalogStatus="ready"
        projection={historical}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('workspace_lsp · 就绪');
    expect(screen.getByText('/workspace/app')).toBeInTheDocument();
    expect(screen.queryByText('/workspace/old')).not.toBeInTheDocument();
    expect(screen.queryByText('/workspace/history')).not.toBeInTheDocument();
  });
});

function capabilityCatalog(
  runtimeProjection?: WorkspaceLspStatusV1,
  revision = 'catalog:1',
): CapabilityCatalog {
  return {
    schemaVersion: 'rag-ime.capability-catalog.v1',
    ok: true,
    revision,
    effectiveAtMs: nowMs,
    projectScope: { supported: true, identityKind: 'workspace', reason: 'fixture', projectId: 'project-1' },
    sessionPolicy: {
      sessionId,
      policyRevision: 1,
      disclosurePreferences: { globalDefault: {}, projectDefault: {}, session: {}, effective: {} },
      effectiveAtMs: nowMs,
    },
    items: [{
      id: 'workspace_lsp',
      canonicalId: 'workspace_lsp',
      kind: 'tool',
      displayName: '代码智能',
      description: '工作区语言服务器能力',
      source: { kind: 'built_in', label: 'Runtime' },
      status: 'online',
      risk: 'R2',
      requiredPermissions: ['workspace'],
      authorization: { state: 'authorized', reason: 'workspace scope' },
      disclosure: { preference: 'inherit', effective: 'enabled', state: 'disclosed', reason: 'session default' },
      effectiveScope: 'session',
      reasons: [],
      revision,
      effectiveAtMs: nowMs,
      ...(runtimeProjection ? { runtimeProjection } : {}),
    }],
  };
}

function runtimeStatus(overrides: Partial<WorkspaceLspStatusV1> = {}): WorkspaceLspStatusV1 {
  return {
    schemaVersion: 'rag-ime.workspace-lsp-status.v1',
    runtimeInstanceId: runtimeA,
    runtimeEpoch: 1,
    observedAtMs: nowMs - 1_000,
    heartbeatExpiresAtMs: nowMs + 60_000,
    current: true,
    summary: 'workspace_lsp current runtime projection',
    state: 'ready',
    roots: readyRoots(),
    ...overrides,
  };
}

function server(
  name: string,
  state: 'ready' | 'available' | 'degraded' | 'unavailable',
  errorCode?: string,
  error?: string,
): WorkspaceLspStatusV1['roots'][number]['servers'][number] {
  return {
    name,
    state,
    languageIds: ['typescript'],
    fileExtensions: ['.ts', '.tsx'],
    ...(errorCode ? { errorCode } : {}),
    ...(error ? { error } : {}),
  };
}

function readyRoots(): WorkspaceLspStatusV1['roots'] {
  return [{
    root: '/workspace/app',
    state: 'ready',
    servers: [server('typescript-language-server', 'ready')],
  }];
}

function snapshotProjection(...liveEvents: AgentEventV1[]) {
  const snapshot: AgentSnapshot = {
    lastSequence: liveEvents.length,
    resumeToken: `${sessionId}:${liveEvents.length}`,
    status: 'idle',
    messages: [],
    liveEvents,
  };
  return applyAgentSnapshot(createAgentProjection(sessionId), snapshot);
}

function statusEvent(sequence: number, status: WorkspaceLspStatusV1): AgentEventV1 {
  return event(sequence, 'tool_finished', {
    toolCallId: `lsp-status-${sequence}`,
    toolName: 'workspace_lsp',
    args: { operation: 'status' },
    result: {
      schemaVersion: 'rag-ime.agent-tool-result.v1',
      ok: true,
      tool: 'workspace_lsp',
      operation: 'status',
      result: status,
    },
  });
}

function event(
  sequence: number,
  eventType: AgentEventV1['eventType'],
  payload: Record<string, unknown>,
): AgentEventV1 {
  return {
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `lsp-event-${sequence}`,
    sessionId,
    turnId: 'turn-lsp',
    sequence,
    createdAtMs: nowMs + sequence,
    eventType,
    payload,
    resumeToken: `${sessionId}:${sequence}`,
  };
}
