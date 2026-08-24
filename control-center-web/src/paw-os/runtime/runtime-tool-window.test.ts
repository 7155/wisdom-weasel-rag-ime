import { describe, expect, it, vi } from 'vitest';

import {
  backgroundJobWindowRequest,
  createRuntimeToolWindowProjector,
  runtimeToolWindowRequest,
  shouldAutoOpenRuntimeToolWindow,
} from './runtime-tool-window';
import { createPawDesktopStore } from './desktop-store';

describe('runtime tool window projection', () => {
  it('binds a process view to one authoritative run without starting another command', () => {
    expect(runtimeToolWindowRequest({
      eventType: 'tool_started',
      sessionId: 'session-1',
      payload: {
        toolCallId: 'call-shell-1',
        toolName: 'bash',
        args: { command: 'pnpm test', cwd: '/workspace/paw' },
      },
    })).toEqual({
      appId: 'terminal',
      background: true,
      target: {
        kind: 'process-terminal',
        id: 'call-shell-1',
        title: 'pnpm test',
        sessionId: 'session-1',
        toolCallId: 'call-shell-1',
        command: 'pnpm test',
        cwd: '/workspace/paw',
      },
    });
  });

  it('uses toolCallId before a durable runtime id arrives, then enriches the same target', () => {
    expect(runtimeToolWindowRequest({
      eventType: 'tool_finished',
      sessionId: 'session-1',
      payload: {
        toolCallId: 'call-shell-1',
        toolName: 'workspace_job',
        args: { command: 'pnpm dev', cwd: '/workspace/paw' },
        result: { details: { result: { jobId: 'bg_0123456789abcdef0123456789abcdef' } } },
      },
    })?.target).toMatchObject({
      kind: 'process-terminal',
      id: 'call-shell-1',
      runId: 'bg_0123456789abcdef0123456789abcdef',
    });
  });

  it('projects the authoritative background-job event by durable job id', () => {
    expect(runtimeToolWindowRequest({
      eventType: 'background_job_started',
      sessionId: 'session-1',
      payload: {
        jobId: 'bg_0123456789abcdef0123456789abcdef',
        status: 'running',
        job: {
          jobId: 'bg_0123456789abcdef0123456789abcdef',
          sessionId: 'session-1',
          command: 'pnpm dev',
          cwd: '/workspace/paw',
          status: 'running',
          pid: 42,
        },
      },
    })?.target).toMatchObject({
      kind: 'process-terminal',
      id: 'bg_0123456789abcdef0123456789abcdef',
      runId: 'bg_0123456789abcdef0123456789abcdef',
      command: 'pnpm dev',
      cwd: '/workspace/paw',
      runStatus: 'running',
    });
  });

  it('correlates the real background-job event back to the initial toolCall window', () => {
    const project = createRuntimeToolWindowProjector();
    const started = project({
      eventType: 'tool_started', sessionId: 'session-1',
      payload: { toolCallId: 'call-job-1', toolName: 'workspace_job', args: { command: 'pnpm dev', cwd: '/workspace/paw' } },
    });
    const running = project({
      eventType: 'background_job_started', sessionId: 'session-1',
      payload: { jobId: 'bg_0123456789abcdef0123456789abcdef', job: { jobId: 'bg_0123456789abcdef0123456789abcdef', command: 'pnpm dev', cwd: '/workspace/paw' } },
    });
    expect(started?.target.id).toBe('call-job-1');
    expect(running?.target).toMatchObject({ id: 'call-job-1', runId: 'bg_0123456789abcdef0123456789abcdef' });
  });

  it('enriches one existing desktop window instead of opening a second process', () => {
    const project = createRuntimeToolWindowProjector();
    const store = createPawDesktopStore();
    const started = project({
      eventType: 'tool_started', sessionId: 'session-1',
      payload: { toolCallId: 'call-job-1', toolName: 'workspace_job', args: { command: 'pnpm dev' } },
    })!;
    store.getState().openApp(started.appId, { entityId: started.target.id, target: started.target });
    const running = project({
      eventType: 'background_job_started', sessionId: 'session-1',
      payload: { jobId: 'bg_0123456789abcdef0123456789abcdef', job: { jobId: 'bg_0123456789abcdef0123456789abcdef', command: 'pnpm dev' } },
    })!;
    store.getState().openApp(running.appId, { entityId: running.target.id, target: running.target });
    expect(Object.keys(store.getState().windows)).toEqual(['terminal:call-job-1']);
    expect(store.getState().windows['terminal:call-job-1']?.target).toMatchObject({
      kind: 'process-terminal',
      runId: 'bg_0123456789abcdef0123456789abcdef',
    });
  });

  it('keeps Session composer focus and places a Room process in its Focus information rail', () => {
    const sessionProject = createRuntimeToolWindowProjector();
    const sessionStore = createPawDesktopStore();
    const sessionMain = sessionStore.getState().openApp('agent', {
      entityId: 'session-1',
      target: { kind: 'session', id: 'session-1', title: 'Session' },
    });
    const sessionRequest = sessionProject({
      eventType: 'background_job_started', sessionId: 'session-1',
      payload: { job: { jobId: 'bg_22222222222222222222222222222222', command: 'pnpm test', status: 'running' } },
    })!;
    sessionStore.getState().openApp(sessionRequest.appId, {
      background: sessionRequest.background,
      entityId: sessionRequest.target.id,
      target: sessionRequest.target,
    });
    expect(sessionStore.getState().activeWindowId).toBe(sessionMain);

    const roomProject = createRuntimeToolWindowProjector();
    const roomStore = createPawDesktopStore();
    const roomMain = roomStore.getState().openApp('agent', {
      entityId: 'room-1',
      target: { kind: 'room', id: 'room-1', title: 'Room' },
    });
    const roomRequest = roomProject({
      eventType: 'participant_activity',
      roomId: 'room-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-room-worker',
      payload: {
        sourceEventType: 'background_job_started',
        data: {
          job: {
            jobId: 'bg_33333333333333333333333333333333',
            command: 'pnpm build',
            status: 'running',
            causalMetadata: { roomBound: true, turnId: 'room-root-1' },
          },
        },
      },
    })!;
    roomStore.getState().openApp(roomRequest.appId, {
      background: roomRequest.background,
      entityId: roomRequest.target.id,
      target: roomRequest.target,
    });
    expect(roomStore.getState().activeWindowId).toBe(roomMain);
    expect(roomStore.getState().collaborationFocusGroup).toBe('room:room-1');
    expect(roomRequest.target).toMatchObject({
      sessionId: 'session-room-worker',
      runId: 'bg_33333333333333333333333333333333',
      roomBound: true,
      roomTurnId: 'room-root-1',
    });
  });

  it('binds Browser to the exact target and preserves Room ownership', () => {
    expect(runtimeToolWindowRequest({
      eventType: 'participant_activity',
      roomId: 'room-1',
      participantId: 'participant-1',
      sourceSessionId: 'session-1',
      payload: {
        sourceEventType: 'tool_started',
        data: {
          toolCallId: 'call-browser-1',
          toolName: 'browser',
          targetId: 'CDP-target-1',
          args: { tabId: 7 },
        },
      },
    })).toEqual({
      appId: 'browser',
      background: true,
      target: {
        kind: 'browser-target',
        id: 'CDP-target-1',
        title: 'Browser',
        sessionId: 'session-1',
        roomId: 'room-1',
        participantId: 'participant-1',
        toolCallId: 'call-browser-1',
        targetId: 'CDP-target-1',
        provisional: false,
        tabId: 7,
      },
    });
  });

  it('opens the built-in Browser before the guest target exists, then binds the exact target', () => {
    const project = createRuntimeToolWindowProjector();
    const store = createPawDesktopStore();
    const pending = project({
      eventType: 'tool_started',
      sessionId: 'session-1',
      payload: {
        toolCallId: 'call-browser-1',
        toolName: 'browser',
        args: { action: 'navigate', url: 'https://example.com' },
      },
    });
    expect(pending?.target).toMatchObject({
      kind: 'browser-target',
      id: 'call-browser-1',
      targetId: '',
      provisional: true,
    });
    store.getState().openApp(pending!.appId, {
      entityId: pending!.target.id,
      target: pending!.target,
    });

    const exact = project({
      eventType: 'tool_progress',
      sessionId: 'session-1',
      payload: {
        toolCallId: 'call-browser-1',
        toolName: 'browser',
        targetId: 'target-1',
      },
    });
    expect(exact?.target).toMatchObject({
      kind: 'browser-target',
      id: 'call-browser-1',
      targetId: 'target-1',
      provisional: false,
    });
    store.getState().openApp(exact!.appId, {
      entityId: exact!.target.id,
      target: exact!.target,
    });
    expect(Object.keys(store.getState().windows)).toEqual(['browser:call-browser-1']);
    expect(store.getState().windows['browser:call-browser-1']?.target).toMatchObject({
      kind: 'browser-target',
      targetId: 'target-1',
    });
  });

  it('opens Browser as soon as an exact target appears', () => {
    expect(runtimeToolWindowRequest({
      eventType: 'tool_progress',
      sessionId: 'session-1',
      payload: { toolCallId: 'call-browser-1', toolName: 'browser', targetId: 'target-1' },
    })?.target).toMatchObject({ kind: 'browser-target', targetId: 'target-1' });
  });

  it('keeps process projections silent while routing exact Browser targets into the built-in Browser', () => {
    const process = runtimeToolWindowRequest({
      eventType: 'background_job_started',
      sessionId: 'session-1',
      payload: {
        job: {
          jobId: 'bg_0123456789abcdef0123456789abcdef',
          command: 'pnpm test',
          status: 'running',
        },
      },
    });
    const browser = runtimeToolWindowRequest({
      eventType: 'tool_progress',
      sessionId: 'session-1',
      payload: {
        toolCallId: 'call-browser-1',
        toolName: 'browser',
        targetId: 'target-1',
      },
    });

    expect(process?.target.kind).toBe('process-terminal');
    expect(shouldAutoOpenRuntimeToolWindow(process!)).toBe(false);
    expect(browser?.target.kind).toBe('browser-target');
    expect(shouldAutoOpenRuntimeToolWindow(browser!)).toBe(true);
  });

  it('opens an existing background run by durable id without starting another command', () => {
    const request = backgroundJobWindowRequest({
      schemaVersion: 'rag-ime.agent-background-job.v1',
      jobId: 'bg_0123456789abcdef0123456789abcdef',
      sessionId: 'session-1',
      label: '构建项目',
      status: 'running',
      command: 'pnpm build',
      commandSha256: 'a'.repeat(64),
      cwd: '/workspace',
      networkAllowed: false,
      maxRunSeconds: 120,
      pid: 42,
      createdAtMs: 100,
      startedAtMs: 110,
      updatedAtMs: 120,
      endedAtMs: 0,
      exitCode: null,
      outputBytes: 0,
      logStartCursor: 0,
      logTruncated: false,
      cancelRequestedAtMs: 0,
      error: '',
      approvalId: 'approval-1',
      causalMetadata: {
        todoId: 'todo-1',
        todoRevision: 1,
        goalId: 'goal-1',
        goalRevision: 1,
        turnId: 'turn-1',
        roomBound: true,
      },
      roomLineage: {
        roomId: 'room-1',
        rootId: 'room-root-1',
        generation: 1,
        taskId: 'task-1',
        dispatchId: 'dispatch-1',
      },
    }, { roomId: 'room-1', participantId: 'participant-1' });

    expect(request).toMatchObject({
      appId: 'terminal',
      background: false,
      target: {
        kind: 'process-terminal',
        id: 'bg_0123456789abcdef0123456789abcdef',
        runId: 'bg_0123456789abcdef0123456789abcdef',
        sessionId: 'session-1',
        roomId: 'room-1',
        participantId: 'participant-1',
        roomBound: true,
        roomTurnId: 'room-root-1',
        command: 'pnpm build',
      },
    });
  });
});
