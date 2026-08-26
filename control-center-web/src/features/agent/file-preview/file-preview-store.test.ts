import { act, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { AgentFilePreviewV1 } from '@/contracts/generated/agent-file-preview.v1';
import { ControlTransportHttpError } from '@/platform/http-transport';
import type { ControlRequest } from '@/platform/transport';
import { StubControlTransport } from '@/test/stub-control-transport';
import type { FilePreviewRequest } from './file-descriptor';
import { useFilePreviewStore } from './file-preview-store';

afterEach(() => useFilePreviewStore.getState().reset());

describe('file preview store', () => {
  it('shows loading immediately and propagates AbortSignal when another file replaces it', async () => {
    const first = deferred<AgentFilePreviewV1>();
    const second = deferred<AgentFilePreviewV1>();
    const transport = new StubControlTransport('mock', {
      'agent.media.preview': (controlRequest: ControlRequest) => (
        controlRequest.params?.mediaId === requestOne.mediaId ? first.promise : second.promise
      ),
    });

    act(() => useFilePreviewStore.getState().openPreview(requestOne, transport));
    expect(useFilePreviewStore.getState()).toMatchObject({ open: true, status: 'loading', request: requestOne });
    const firstSignal = transport.requests[0]?.signal;
    expect(firstSignal?.aborted).toBe(false);

    act(() => useFilePreviewStore.getState().openPreview(requestTwo, transport));
    expect(firstSignal?.aborted).toBe(true);
    expect(useFilePreviewStore.getState()).toMatchObject({ status: 'loading', request: requestTwo });

    second.resolve(previewFor(requestTwo, '# second'));
    await waitFor(() => expect(useFilePreviewStore.getState().status).toBe('ready'));
    expect(useFilePreviewStore.getState().preview?.descriptor.mediaId).toBe(requestTwo.mediaId);

    first.resolve(previewFor(requestOne, '# stale'));
    await Promise.resolve();
    expect(useFilePreviewStore.getState().preview?.descriptor.mediaId).toBe(requestTwo.mediaId);
  });

  it('aborts the active read when the preview closes', () => {
    const pending = deferred<AgentFilePreviewV1>();
    const transport = new StubControlTransport('mock', { 'agent.media.preview': () => pending.promise });
    act(() => useFilePreviewStore.getState().openPreview(requestOne, transport));
    const signal = transport.requests[0]?.signal;

    act(() => useFilePreviewStore.getState().close());

    expect(signal?.aborted).toBe(true);
    expect(useFilePreviewStore.getState()).toMatchObject({ open: false, status: 'idle', preview: null });
  });

  it('preserves inline presentation while retrying a failed preview', async () => {
    let calls = 0;
    const transport = new StubControlTransport('mock', {
      'agent.media.preview': () => {
        calls += 1;
        if (calls === 1) throw new Error('temporary read failure');
        return previewFor(requestOne, '# recovered');
      },
    });

    act(() => useFilePreviewStore.getState().openPreview(requestOne, transport, 'inline'));
    await waitFor(() => expect(useFilePreviewStore.getState().status).toBe('error'));
    expect(useFilePreviewStore.getState().presentation).toBe('inline');

    act(() => useFilePreviewStore.getState().retry(transport));
    await waitFor(() => expect(useFilePreviewStore.getState().status).toBe('ready'));
    expect(useFilePreviewStore.getState()).toMatchObject({
      presentation: 'inline',
      preview: expect.objectContaining({
        content: '# recovered',
      }),
    });
  });

  it('explains when the receipt exists but external media storage is unavailable', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.media.preview': () => {
        throw new ControlTransportHttpError(
          'agent.media.preview',
          400,
          'agent media object is unavailable',
        );
      },
    });

    act(() => useFilePreviewStore.getState().openPreview(requestOne, transport, 'inline'));

    await waitFor(() => expect(useFilePreviewStore.getState().status).toBe('error'));
    expect(useFilePreviewStore.getState().error)
      .toBe('文件收据仍在，但原始文件当前不可用。请检查外置存储是否已连接后重试。');
  });

  it('caches verified immutable receipts and does not read the same digest twice', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.media.preview': previewFor(requestOne, '# cached'),
    });
    act(() => useFilePreviewStore.getState().openPreview(requestOne, transport));
    await waitFor(() => expect(useFilePreviewStore.getState().status).toBe('ready'));
    act(() => useFilePreviewStore.getState().close());
    act(() => useFilePreviewStore.getState().openPreview(requestOne, transport));

    expect(useFilePreviewStore.getState().status).toBe('ready');
    expect(transport.requests).toHaveLength(1);
  });

  it('fails closed when the backend changes session, digest, URL, or byte receipt', async () => {
    const invalid = previewFor(requestOne, '# unsafe');
    invalid.descriptor.contentUrl = 'https://example.com/unsafe.md';
    const transport = new StubControlTransport('mock', { 'agent.media.preview': invalid });
    act(() => useFilePreviewStore.getState().openPreview(requestOne, transport));

    await waitFor(() => expect(useFilePreviewStore.getState().status).toBe('error'));
    expect(useFilePreviewStore.getState().preview).toBeNull();
  });
});

const requestOne: FilePreviewRequest = {
  mediaId: 'media_abcdefghijkl',
  sessionId: 'session-preview-1',
  expectedSha256: 'a'.repeat(64),
  fileNameHint: 'one.md',
  mimeTypeHint: 'text/markdown',
  byteSizeHint: 0,
};

const requestTwo: FilePreviewRequest = {
  ...requestOne,
  mediaId: 'media_mnopqrstuvwx',
  expectedSha256: 'b'.repeat(64),
  fileNameHint: 'two.md',
};

function previewFor(request: FilePreviewRequest, content: string): AgentFilePreviewV1 {
  return {
    schemaVersion: 'rag-ime.agent-file-preview.v1',
    descriptor: {
      schemaVersion: 'rag-ime.agent-file-descriptor.v1',
      mediaId: request.mediaId,
      sessionId: request.sessionId,
      fileName: request.fileNameHint,
      mimeType: request.mimeTypeHint,
      byteSize: new TextEncoder().encode(content).byteLength,
      sha256: request.expectedSha256,
      previewKind: 'markdown',
      language: '',
      contentUrl: `/api/agent/media/${request.mediaId}/content?sessionId=${request.sessionId}`,
    },
    content,
    previewByteSize: new TextEncoder().encode(content).byteLength,
    truncated: false,
  };
}

function deferred<Value>(): {
  promise: Promise<Value>;
  resolve(value: Value): void;
} {
  let resolve!: (value: Value) => void;
  return {
    promise: new Promise<Value>((done) => { resolve = done; }),
    resolve,
  };
}
