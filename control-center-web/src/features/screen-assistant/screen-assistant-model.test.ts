import { describe, expect, it, vi } from 'vitest';
import { createAgentProjection } from '@/contracts/agent-reducer';
import type { ControlTransport } from '@/platform/transport';
import {
  prepareScreenConversation, screenContextForMessage, latestCompletedScreenAnswer,
  type CapturePreparation, type ScreenAssistantHost,
} from './screen-assistant-model';

describe('screen conversation ownership', () => {
  it('restores the same Session and media after a renderer reload without reattaching a delivered capture', async () => {
    let remembered = {};
    const host = {
      getCapture: vi.fn().mockResolvedValue({ dataUrl: 'data:image/png;base64,YWJj', mimeType: 'image/png', pixelWidth: 1, pixelHeight: 1, sourceAppBundleId: '', capturedAtMs: 1000 }),
      getConversation: vi.fn(async () => remembered),
      rememberConversation: vi.fn(async (value) => { remembered = { ...remembered, ...value }; }),
    } as unknown as ScreenAssistantHost;
    const request = vi.fn(async (input) => input.pathId === 'agent.sessions.create'
      ? { session: { id: 'session-screen', title: '选区对话' } }
      : { items: [{ role: 'user', status: 'completed', attachments: ['media_abcdefghijklmnop'] }] });
    const pasteImages = vi.fn().mockResolvedValue([{ id: 'media_abcdefghijklmnop', name: '屏幕选区.png', mimeType: 'image/png', byteSize: 3 }]);
    const transport = { request, pasteImages } as unknown as ControlTransport;
    await prepareScreenConversation(transport, host, {});
    const restored = await prepareScreenConversation(transport, host, {});
    expect(request.mock.calls.filter(([input]) => input.pathId === 'agent.sessions.create')).toHaveLength(1);
    expect(pasteImages).toHaveBeenCalledTimes(1);
    expect(restored.session.id).toBe('session-screen');
    expect(restored.attachments[0].id).toBe('media_abcdefghijklmnop');
    expect(restored.initialAttachments).toEqual([]);
  });

  it('keeps the created Session and original bytes across an upload retry', async () => {
    const state: CapturePreparation = {};
    const getCapture = vi.fn().mockResolvedValue({ dataUrl: 'data:image/png;base64,YWJj', mimeType: 'image/png', pixelWidth: 1, pixelHeight: 1, sourceAppBundleId: 'com.example.Editor', capturedAtMs: 1000 });
    const request = vi.fn().mockResolvedValue({ session: { id: 'session-screen', title: '选区对话' } });
    const pasteImages = vi.fn().mockRejectedValueOnce(new Error('upload offline')).mockResolvedValueOnce([{ id: 'media_abcdefghijklmnop', name: '屏幕选区.png', mimeType: 'image/png', byteSize: 3 }]);
    const transport = { request, pasteImages } as unknown as ControlTransport;
    const host = { getCapture } as unknown as ScreenAssistantHost;
    await expect(prepareScreenConversation(transport, host, state)).rejects.toThrow('upload offline');
    const ready = await prepareScreenConversation(transport, host, state);
    expect(request).toHaveBeenCalledTimes(1);
    expect(getCapture).toHaveBeenCalledTimes(1);
    expect(pasteImages.mock.calls[1][0]).toMatchObject({ sessionId: 'session-screen', maxFiles: 1 });
    expect(pasteImages.mock.calls[1][0].files[0].size).toBe(3);
    expect(ready.attachments[0].id).toBe('media_abcdefghijklmnop');
    expect(request.mock.calls[0][0].pathId).toBe('agent.sessions.create');
    expect(request.mock.calls.some(([call]) => call.pathId === 'agent.session.prompt')).toBe(false);
  });

  it('removing the initial image also removes its context from the first send', () => {
    const context = { mediaId: 'media_abcdefghijklmnop', sourceAppBundleId: '', capturedAtMs: 1000 };
    expect(screenContextForMessage(context, [], createAgentProjection('session-screen'))).toBeUndefined();
    expect(screenContextForMessage(context, [context.mediaId])).toEqual(context);
  });

  it('does not offer a streaming answer as a saved note', () => {
    const projection = createAgentProjection('session-screen');
    projection.messageOrder = ['answer'];
    projection.messagesById.answer = {
      schemaVersion: 'rag-ime.agent-message.v1', id: 'answer', sessionId: 'session-screen', turnId: 'turn', role: 'assistant', status: 'streaming',
      blocks: [{ id: 'text', type: 'text', status: 'running', presentationKind: 'markdown', data: { text: '还在生成' } }],
      attachments: [], citations: [], createdAtMs: 1,
    };
    expect(latestCompletedScreenAnswer(projection)).toBe('');
    projection.messagesById.answer.status = 'completed';
    expect(latestCompletedScreenAnswer(projection)).toBe('还在生成');
  });
});
