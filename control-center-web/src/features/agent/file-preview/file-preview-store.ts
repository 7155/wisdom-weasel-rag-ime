import { create } from 'zustand';
import type { AgentFilePreviewV1 } from '@/contracts/generated/agent-file-preview.v1';
import type { ControlTransport } from '@/platform/transport';
import { safeManagedContentUrl, type FilePreviewRequest } from './file-descriptor';

type PreviewStatus = 'idle' | 'loading' | 'ready' | 'error';
export type PreviewPresentation = 'dialog' | 'inline';
const MAX_CACHED_PREVIEWS = 8;

interface FilePreviewState {
  open: boolean;
  request: FilePreviewRequest | null;
  presentation: PreviewPresentation;
  status: PreviewStatus;
  preview: AgentFilePreviewV1 | null;
  error: string;
  requestSequence: number;
  controller: AbortController | null;
  cache: Readonly<Record<string, AgentFilePreviewV1>>;
  openPreview(request: FilePreviewRequest, transport: ControlTransport, presentation?: PreviewPresentation): void;
  retry(transport: ControlTransport): void;
  close(): void;
  reset(): void;
}

const INITIAL = {
  open: false,
  request: null,
  presentation: 'dialog' as const,
  status: 'idle' as const,
  preview: null,
  error: '',
  requestSequence: 0,
  controller: null,
  cache: {} as Readonly<Record<string, AgentFilePreviewV1>>,
};

export const useFilePreviewStore = create<FilePreviewState>((set, get) => ({
  ...INITIAL,
  openPreview(request, transport, presentation = 'dialog') {
    void loadPreview(request, transport, false, presentation, set, get);
  },
  retry(transport) {
    const request = get().request;
    if (request) void loadPreview(request, transport, true, get().presentation, set, get);
  },
  close() {
    get().controller?.abort();
    set((state) => ({
      open: false,
      request: null,
      presentation: 'dialog',
      status: 'idle',
      preview: null,
      error: '',
      controller: null,
      requestSequence: state.requestSequence + 1,
    }));
  },
  reset() {
    get().controller?.abort();
    set({ ...INITIAL, cache: {} });
  },
}));

async function loadPreview(
  request: FilePreviewRequest,
  transport: ControlTransport,
  force: boolean,
  presentation: PreviewPresentation,
  set: (partial: Partial<FilePreviewState> | ((state: FilePreviewState) => Partial<FilePreviewState>)) => void,
  get: () => FilePreviewState,
): Promise<void> {
  get().controller?.abort();
  const sequence = get().requestSequence + 1;
  const key = previewCacheKey(request);
  const cached = !force ? get().cache[key] : undefined;
  if (cached) {
    set({
      open: true,
      request,
      presentation,
      status: 'ready',
      preview: cached,
      error: '',
      controller: null,
      requestSequence: sequence,
      cache: withCachedPreview(get().cache, key, cached),
    });
    return;
  }

  const controller = new AbortController();
  set({
    open: true,
    request,
    presentation,
    status: 'loading',
    preview: null,
    error: '',
    controller,
    requestSequence: sequence,
  });
  try {
    const response = await transport.request<AgentFilePreviewV1>({
      pathId: 'agent.media.preview',
      params: { mediaId: request.mediaId },
      query: {
        sessionId: request.sessionId,
        ...(request.expectedSha256 ? { sha256: request.expectedSha256 } : {}),
      },
      responseContract: 'agent-file-preview.v1',
      signal: controller.signal,
    });
    const preview = verifiedPreview(response, request);
    if (controller.signal.aborted || get().requestSequence !== sequence) return;
    set((state) => ({
      status: 'ready',
      preview,
      error: '',
      controller: null,
      cache: withCachedPreview(state.cache, key, preview),
    }));
  } catch (error) {
    if (controller.signal.aborted || get().requestSequence !== sequence || isAbortError(error)) return;
    set({
      status: 'error',
      preview: null,
      error: publicFilePreviewError(error),
      controller: null,
    });
  }
}

function verifiedPreview(
  preview: AgentFilePreviewV1,
  request: FilePreviewRequest,
): AgentFilePreviewV1 {
  const descriptor = preview.descriptor;
  if (descriptor.mediaId !== request.mediaId || descriptor.sessionId !== request.sessionId) {
    throw new TypeError('file preview authority changed during read');
  }
  if (request.expectedSha256 && descriptor.sha256 !== request.expectedSha256) {
    throw new TypeError('file preview digest changed during read');
  }
  if (request.byteSizeHint > 0 && descriptor.byteSize !== request.byteSizeHint) {
    throw new TypeError('file preview byte receipt changed during read');
  }
  if (
    request.mimeTypeHint
    && normalizedMime(descriptor.mimeType) !== normalizedMime(request.mimeTypeHint)
  ) {
    throw new TypeError('file preview MIME receipt changed during read');
  }
  const contentUrl = safeManagedContentUrl(descriptor.contentUrl, descriptor);
  if (!contentUrl) throw new TypeError('file preview returned an unmanaged content URL');
  const textKind = ['markdown', 'code', 'diff', 'html'].includes(descriptor.previewKind);
  if (textKind !== (typeof preview.content === 'string')) {
    throw new TypeError('file preview content does not match its renderer kind');
  }
  if (typeof preview.content === 'string') {
    const bytes = new TextEncoder().encode(preview.content).byteLength;
    if (bytes !== preview.previewByteSize || bytes > 524_288) {
      throw new TypeError('file preview text exceeded its bounded receipt');
    }
  } else if (preview.previewByteSize !== 0) {
    throw new TypeError('binary file preview reported unexpected text bytes');
  }
  return { ...preview, descriptor: { ...descriptor, contentUrl } };
}

function previewCacheKey(request: FilePreviewRequest): string {
  return `${request.sessionId}:${request.mediaId}:${request.expectedSha256 || 'receipt'}`;
}

function withCachedPreview(
  cache: Readonly<Record<string, AgentFilePreviewV1>>,
  key: string,
  preview: AgentFilePreviewV1,
): Readonly<Record<string, AgentFilePreviewV1>> {
  const entries = Object.entries(cache).filter(([cachedKey]) => cachedKey !== key);
  entries.push([key, preview]);
  return Object.fromEntries(entries.slice(-MAX_CACHED_PREVIEWS));
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function normalizedMime(value: string): string {
  return value.split(';', 1)[0]?.trim().toLowerCase() ?? '';
}

function publicFilePreviewError(error: unknown): string {
  const status = transportErrorStatus(error);
  if (status !== null && error instanceof Error) {
    const message = error.message.toLowerCase();
    if (message.includes('object is unavailable')) {
      return '文件收据仍在，但原始文件当前不可用。请检查外置存储是否已连接后重试。';
    }
    if (message.includes('digest') || message.includes('hash') || message.includes('byte size')) {
      return '文件内容已发生变化，旧预览收据不能继续使用。请重新生成这份文件结果。';
    }
    if (message.includes('not found for this session') || message.includes('does not belong')) {
      return '这份文件不属于当前 Session，无法跨对话读取。';
    }
    return `文件预览读取失败（HTTP ${status}）。请重试。`;
  }
  if (error instanceof TypeError && /authority|digest|receipt|mime|content url|renderer|bounded/iu.test(error.message)) {
    return '文件预览收据校验失败。请重新生成这份文件结果。';
  }
  return '文件预览读取失败。请重试。';
}

function transportErrorStatus(error: unknown): number | null {
  if (!(error instanceof Error) || !('status' in error)) return null;
  return typeof error.status === 'number' ? error.status : null;
}
