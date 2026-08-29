import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { PawOsDesktopProvider } from '@/features/paw-os/surface-context';
import {
  TraceAgentHandoffButton,
  buildTraceAgentHandoffRoute,
  parseTraceAgentHandoff,
} from './handoff';

afterEach(cleanup);

describe('Trace Agent structured handoff', () => {
  it('round-trips exact diagnostic identity and evidence without flattening it into a draft', () => {
    const route = buildTraceAgentHandoffRoute({
      kind: 'memory',
      entityId: 'memory-maintenance:job-1',
      title: '记忆整理失败',
      summary: 'Pi Runtime Host 返回了不完整 JSONL。',
      error: 'Unterminated string at column 340849',
      sessionId: 'session-memory',
      roomId: 'room-memory',
      traceId: 'trace-memory',
      failureRef: 'memory-maintenance:job-1',
      sourceRoute: '/memory?view=activity',
      workspaceRoots: ['/workspace/paw'],
      refs: { phase: 'managed_memory_model', date: '2026-07-17' },
      occurredAtMs: 123,
    });

    expect(route.startsWith('/trace-agent?handoff=')).toBe(true);
    const handoff = parseTraceAgentHandoff(route.split('?', 2)[1] ?? '');
    expect(handoff).toMatchObject({
      schemaVersion: 'paw.trace-agent-handoff.v1',
      kind: 'memory',
      entityId: 'memory-maintenance:job-1',
      sessionId: 'session-memory',
      roomId: 'room-memory',
      traceId: 'trace-memory',
      failureRef: 'memory-maintenance:job-1',
      workspaceRoots: [],
      refs: { phase: 'managed_memory_model', date: '2026-07-17' },
      occurredAtMs: 123,
    });
  });

  it('opens the Trace Agent with the structured source rather than an empty page', async () => {
    const user = userEvent.setup();
    const routes: string[] = [];
    render(
      <PawOsDesktopProvider openRoute={(route) => routes.push(route)} openWindow={() => undefined}>
        <TraceAgentHandoffButton
          handoff={{
            kind: 'tool',
            entityId: 'call-edit-1',
            title: '编辑文件失败',
            summary: 'resourceRevision 不合法',
            sessionId: 'session-a',
            refs: { toolCallId: 'call-edit-1', toolName: 'edit' },
          }}
        />
      </PawOsDesktopProvider>,
    );

    await user.click(screen.getByRole('button', { name: '交给 Trace Agent' }));
    expect(routes).toHaveLength(1);
    const handoff = parseTraceAgentHandoff(routes[0].split('?', 2)[1] ?? '');
    expect(handoff).toMatchObject({
      kind: 'tool',
      entityId: 'call-edit-1',
      sessionId: 'session-a',
      refs: { toolCallId: 'call-edit-1', toolName: 'edit' },
    });
  });

  it('rejects malformed or unsupported handoffs instead of crashing the Trace app', () => {
    expect(parseTraceAgentHandoff('handoff=not-json')).toBeNull();
    expect(parseTraceAgentHandoff(`handoff=${encodeURIComponent(JSON.stringify({
      schemaVersion: 'paw.trace-agent-handoff.v0',
      kind: 'tool',
    }))}`)).toBeNull();
  });

  it('redacts sensitive error, refs, routes, and absolute workspace paths before serializing a bounded URL', () => {
    const rawError = [
      'write failed: /Users/undo/private/project/config.json',
      'Authorization: Bearer super-secret-token',
      'https://example.test/upload?api_key=raw-api-key',
      'stack line that must not be copied into the handoff',
    ].join('\n');
    const route = buildTraceAgentHandoffRoute({
      kind: 'tool',
      entityId: 'call-edit-1',
      title: '编辑文件失败',
      summary: '工具执行失败',
      error: rawError,
      sourceRoute: '/files?path=%2FUsers%2Fundo%2Fprivate%2Fproject%2Fconfig.json&token=route-secret&clientSecret=route-client-secret&authorizationHeader=route-auth&session=session-a',
      workspaceRoots: ['/Users/undo/private/project', '/Volumes/private/other'],
      refs: {
        path: '/Users/undo/private/project/config.json',
        url: 'https://example.test/private?token=url-secret',
        token: 'raw-token',
        authorization: 'Bearer raw-authorization',
        apiKey: 'raw-api-key',
        clientSecret: 'raw-client-secret',
        authorizationHeader: 'raw-auth-header',
        authToken: 'raw-auth-token',
        safeRef: 'kept for diagnosis',
      },
      occurredAtMs: 123,
    });
    const encodedPayload = route.split('handoff=', 2)[1] ?? '';
    expect(route.length).toBeLessThan(8_000);
    expect(decodeURIComponent(encodedPayload)).not.toContain('/Users/undo/private/project');
    expect(decodeURIComponent(encodedPayload)).not.toContain('raw-token');
    expect(decodeURIComponent(encodedPayload)).not.toContain('raw-api-key');
    expect(decodeURIComponent(encodedPayload)).not.toContain('raw-authorization');
    expect(decodeURIComponent(encodedPayload)).not.toContain('raw-client-secret');
    expect(decodeURIComponent(encodedPayload)).not.toContain('raw-auth-header');
    expect(decodeURIComponent(encodedPayload)).not.toContain('raw-auth-token');
    expect(decodeURIComponent(encodedPayload)).not.toContain('route-secret');
    expect(decodeURIComponent(encodedPayload)).not.toContain('route-client-secret');
    expect(decodeURIComponent(encodedPayload)).not.toContain('route-auth');

    const handoff = parseTraceAgentHandoff(route.split('?', 2)[1] ?? '');
    expect(handoff).toMatchObject({
      error: expect.stringContaining('[redacted]'),
      workspaceRoots: [],
      refs: {
        path: '[path redacted]',
        url: '[url redacted]',
        token: '[redacted]',
        authorization: '[redacted]',
        apiKey: '[redacted]',
        clientSecret: '[redacted]',
        authorizationHeader: '[redacted]',
        authToken: '[redacted]',
        safeRef: 'kept for diagnosis',
      },
    });
    expect(handoff?.sourceRoute).toContain('session=session-a');
    expect(handoff?.sourceRoute).not.toContain('route-secret');
    expect(handoff?.error).not.toContain('stack line that must not be copied');
  });

  it('re-sanitizes handoffs received from an untrusted URL', () => {
    const raw = {
      schemaVersion: 'paw.trace-agent-handoff.v1',
      kind: 'generic',
      entityId: 'job-1',
      title: '问题',
      summary: '请检查',
      error: 'Authorization: Bearer leaked',
      sourceRoute: '/memory?token=leaked&view=activity',
      workspaceRoots: ['/Users/undo/private'],
      refs: { authorization: 'Bearer leaked', path: '/Users/undo/private/file' },
      occurredAtMs: 1,
    };
    const handoff = parseTraceAgentHandoff(`handoff=${encodeURIComponent(JSON.stringify(raw))}`);
    expect(handoff).toMatchObject({
      error: 'Authorization: [redacted]',
      workspaceRoots: [],
      refs: { authorization: '[redacted]', path: '[path redacted]' },
    });
    expect(handoff?.sourceRoute).toBe('/memory?view=activity');
  });

  it('rejects machine paths and file URLs used as source routes', () => {
    for (const sourceRoute of [
      '/Users/undo/private/project/config.json?session=session-a',
      '/Volumes/private/project/config.json',
      'file:///Users/undo/private/project/config.json',
    ]) {
      const route = buildTraceAgentHandoffRoute({
        kind: 'file',
        entityId: 'unsafe-route',
        title: '文件失败',
        summary: '检查原位置',
        sourceRoute,
        occurredAtMs: 1,
      });
      const decoded = decodeURIComponent(route);
      expect(decoded).not.toContain('/Users/undo');
      expect(decoded).not.toContain('/Volumes/private');
      expect(parseTraceAgentHandoff(route.split('?', 2)[1] ?? '')?.sourceRoute).toBe('/');
    }
  });
});
