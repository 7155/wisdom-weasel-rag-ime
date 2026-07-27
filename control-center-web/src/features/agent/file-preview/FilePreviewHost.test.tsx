import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import { StubControlTransport } from '@/test/stub-control-transport';
import { AgentFileBlock } from './AgentFileBlock';
import { FilePreviewHost } from './FilePreviewHost';
import { useFilePreviewStore } from './file-preview-store';

afterEach(() => {
  cleanup();
  useFilePreviewStore.getState().reset();
});

describe('file preview interaction', () => {
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

  it('keeps a file disabled when no authoritative parent session is available', () => {
    render(<AgentFileBlock data={{ mediaId: MEDIA_ID, fileName: 'orphan.diff' }} />);
    expect(screen.getByRole('button', { name: 'orphan.diff 的预览回执不可用' })).toBeDisabled();
  });
});

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
