import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { StubControlTransport } from '@/test/stub-control-transport';
import { AgentFileBlock } from './AgentFileBlock';
import { FilePreviewHost } from './FilePreviewHost';
import { RichHtmlPreview } from './RichHtmlPreview';
import { useFilePreviewStore } from './file-preview-store';

afterEach(() => {
  cleanup();
  useFilePreviewStore.getState().reset();
  delete window.webkit;
  vi.restoreAllMocks();
});

describe('file preview interaction', () => {
  it('renders an explicit HTML artifact as a sandboxed managed report preview', async () => {
    const content = '<!doctype html><h1>项目介绍</h1><script>window.pwned = true</script>';
    const createObjectUrl = vi.spyOn(URL, 'createObjectURL');
    const transport = new StubControlTransport('mock', {
      'agent.media.preview': htmlPreview(content),
    });
    const user = userEvent.setup();
    render(
      <StrictMode>
        <TooltipProvider>
          <ControlTransportProvider transport={transport}>
            <AgentFileBlock
              data={{
                mediaId: MEDIA_ID,
                fileName: 'project-intro.html',
                mimeType: 'text/html',
                byteSize: new TextEncoder().encode(content).byteLength,
                sha256: SHA256,
              }}
              sessionId={SESSION_ID}
            />
            <FilePreviewHost />
          </ControlTransportProvider>
        </TooltipProvider>
      </StrictMode>,
    );

    expect(screen.getByText('HTML 报告')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '预览报告' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('project-intro.html')).toBeInTheDocument();
    const frame = within(dialog).getByTitle('project-intro.html 交互预览');
    expect(frame.getAttribute('sandbox')).toContain('allow-scripts');
    expect(frame.getAttribute('sandbox')).toContain('allow-forms');
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin');
    expect(previewSource(frame)).toContain('<h1>项目介绍</h1>');
    expect(frame).not.toHaveAttribute('srcdoc');
    expect(createObjectUrl).not.toHaveBeenCalled();
  });

  it('expands a managed Markdown file in its message instead of opening a dialog', async () => {
    const transport = new StubControlTransport('mock', {
      'agent.media.preview': preview('# 交付\n\n- 类型检查通过'),
    });
    const user = userEvent.setup();
    render(
      <TooltipProvider>
        <ControlTransportProvider transport={transport}>
          <AgentFileBlock
            data={{
              mediaId: MEDIA_ID,
              fileName: 'acceptance.md',
              mimeType: 'text/markdown',
              sha256: SHA256,
            }}
            sessionId={SESSION_ID}
          />
          <FilePreviewHost />
        </ControlTransportProvider>
      </TooltipProvider>,
    );

    await user.click(screen.getByRole('button', { name: '展开 acceptance.md' }));

    const inline = await screen.findByRole('region', { name: 'acceptance.md 内联预览' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(within(inline).getByRole('heading', { name: '交付' })).toBeInTheDocument();
    expect(within(inline).getByText('类型检查通过')).toBeInTheDocument();
    expect(transport.requests[0]).toMatchObject({
      pathId: 'agent.media.preview',
      params: { mediaId: MEDIA_ID },
      query: { sessionId: SESSION_ID, sha256: SHA256 },
    });

    await user.click(screen.getByRole('button', { name: '收起 acceptance.md' }));
    expect(screen.queryByRole('region', { name: 'acceptance.md 内联预览' })).not.toBeInTheDocument();
  });

  it('keeps the isolated loopback transport for the native WebKit host', () => {
    window.webkit = {
      messageHandlers: {
        ragImeNativeBridge: { postMessage: () => undefined },
      },
    };
    render(
      <StrictMode>
        <RichHtmlPreview content="<h1>原生报告</h1>" title="native-report.html" />
      </StrictMode>,
    );

    const frame = screen.getByTitle('native-report.html 交互预览');
    expect(frame.getAttribute('src')).toMatch(/^\/__paw_html_preview#/u);
    expect(previewSource(frame)).toContain('<h1>原生报告</h1>');
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin');
    expect(frame).not.toHaveAttribute('srcdoc');
  });

  it('keeps a file disabled when no authoritative parent session is available', () => {
    render(<AgentFileBlock data={{ mediaId: MEDIA_ID, fileName: 'orphan.diff' }} />);
    expect(screen.getByRole('button', { name: 'orphan.diff 的预览回执不可用' })).toBeDisabled();
  });
});

function previewSource(frame: HTMLElement): string {
  const source = frame.getAttribute('src');
  if (!source) throw new Error('preview URL is missing');
  const encoded = new URL(source, window.location.href).hash.slice(1).replaceAll('-', '+').replaceAll('_', '/');
  const padded = encoded + '='.repeat((4 - encoded.length % 4) % 4);
  const binary = window.atob(padded);
  return new TextDecoder().decode(Uint8Array.from(binary, (character) => character.charCodeAt(0)));
}

const MEDIA_ID = 'media_abcdefghijkl';
const SESSION_ID = 'session-preview-1';
const SHA256 = 'a'.repeat(64);

function preview(content: string) {
  return {
    schemaVersion: 'rag-ime.agent-file-preview.v1',
    descriptor: {
      schemaVersion: 'rag-ime.agent-file-descriptor.v1',
      mediaId: MEDIA_ID,
      sessionId: SESSION_ID,
      fileName: 'acceptance.md',
      mimeType: 'text/markdown',
      byteSize: new TextEncoder().encode(content).byteLength,
      sha256: SHA256,
      previewKind: 'markdown',
      language: '',
      contentUrl: `/api/agent/media/${MEDIA_ID}/content?sessionId=${SESSION_ID}`,
    },
    content,
    previewByteSize: new TextEncoder().encode(content).byteLength,
    truncated: false,
  };
}

function htmlPreview(content: string) {
  return {
    schemaVersion: 'rag-ime.agent-file-preview.v1',
    descriptor: {
      schemaVersion: 'rag-ime.agent-file-descriptor.v1',
      mediaId: MEDIA_ID,
      sessionId: SESSION_ID,
      fileName: 'project-intro.html',
      mimeType: 'text/html',
      byteSize: new TextEncoder().encode(content).byteLength,
      sha256: SHA256,
      previewKind: 'html',
      language: 'html',
      contentUrl: `/api/agent/media/${MEDIA_ID}/content?sessionId=${SESSION_ID}`,
    },
    content,
    previewByteSize: new TextEncoder().encode(content).byteLength,
    truncated: false,
  };
}
