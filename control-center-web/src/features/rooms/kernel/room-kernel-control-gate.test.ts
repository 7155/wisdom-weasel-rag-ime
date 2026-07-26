import { describe, expect, it } from 'vitest';
import type { FrontendCapabilities } from '@/platform/transport';
import { evaluateRoomKernelControlGate } from './room-kernel-control-gate';

describe('Room Kernel production control gate', () => {
  it('enables Stop only when read, authorization, capability and route hash match', async () => {
    const gate = await evaluateRoomKernelControlGate(capabilities());
    expect(gate).toMatchObject({ readEnabled: true, commandEnabled: true, panicEnabled: false });
    expect(gate.commandRouteHash).toBe(gate.expectedCommandRouteHash);
    expect(gate.commandRouteHash).toMatch(/^sha256:[a-f0-9]{64}$/);
  });

  it('fails closed when the server command manifest changes', async () => {
    const value = capabilities();
    const raw = value.raw as { routes: Array<Record<string, unknown>> };
    raw.routes.find((item) => item.pathId === 'agent.room.kernel.command')!.method = 'PATCH';
    const gate = await evaluateRoomKernelControlGate(value);
    expect(gate.commandEnabled).toBe(false);
    expect(gate.reason).toBe('停止任务的控制通道已发生变化，请刷新或更新应用');
  });

  it('denies an unpaired remote caller even if a command route is present', async () => {
    const value = capabilities();
    (value.raw as { client: Record<string, unknown> }).client = {
      remote: true, deviceAuthenticated: false, grantedScopes: ['agent.write'],
    };
    const gate = await evaluateRoomKernelControlGate(value);
    expect(gate.commandEnabled).toBe(false);
    expect(gate.reason).toBe('当前连接可以查看任务，但没有停止任务的权限');
  });

  it('never enables panic without both explicit feature and admin scope', async () => {
    const value = capabilities();
    (value.raw as { features: Record<string, unknown>; client: Record<string, unknown> }).features = { roomKernelPanic: true };
    (value.raw as { client: Record<string, unknown> }).client = {
      remote: true, deviceAuthenticated: true, grantedScopes: ['agent.read', 'agent.write'],
    };
    expect((await evaluateRoomKernelControlGate(value)).panicEnabled).toBe(false);
    (value.raw as { client: Record<string, unknown> }).client = {
      remote: true, deviceAuthenticated: true, grantedScopes: ['agent.read', 'agent.write', 'agent.admin'],
    };
    expect((await evaluateRoomKernelControlGate(value)).panicEnabled).toBe(true);
  });
});

function capabilities(): FrontendCapabilities {
  return {
    schemaVersion: 'rag-ime.control-capabilities.v1', transport: 'http',
    routeIds: ['agent.room.kernel.snapshot', 'agent.room.kernel.events', 'agent.room.kernel.command'],
    features: {}, native: {
      pickFiles: false, managedAgentImageImport: false, revealPath: false,
      approvedExternalActions: false, keychain: false, tcc: false,
    },
    raw: {
      client: { remote: false, deviceAuthenticated: false, grantedScopes: [] },
      features: {},
      routes: [
        route('agent.room.kernel.snapshot', 'GET', false, ['agent.read'], []),
        route('agent.room.kernel.events', 'GET', true, ['agent.read'], ['lastEventId']),
        route('agent.room.kernel.command', 'POST', false, ['agent.write'], []),
      ],
    },
  };
}

function route(pathId: string, method: string, subscription: boolean, remoteScopes: string[], query: string[]) {
  return { pathId, method, remoteSafe: true, subscription, params: ['roomId'], query, remoteScopes };
}
