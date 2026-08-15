import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlPathId } from '@/platform/routes';
import type { FilePickOptions, PickedFile } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { ConfigurationFeature } from '.';

afterEach(cleanup);

const configurationHash = `sha256:${'b'.repeat(64)}`;
const restoreToken = 'c'.repeat(64);

describe('configuration file migration workflows', () => {
  it('binds native file selection to import preview, confirmation, and apply', async () => {
    const user = userEvent.setup();
    const transport = renderConfiguration();
    await openPortabilityPanel(user);

    const importWorkflow = (await screen.findByText('导入配置', { selector: 'strong' })).closest('.mgmt-workflow');
    expect(importWorkflow).not.toBeNull();
    await user.click(within(importWorkflow as HTMLElement).getByRole('button', { name: '选择并校验' }));
    expect(await screen.findByText('rag-ime.config.yaml')).toBeInTheDocument();
    expect(screen.getByText('上下文容量')).toBeInTheDocument();
    expect(screen.getByText('1024')).toBeInTheDocument();
    expect(screen.getByText('2048')).toBeInTheDocument();
    expect(screen.getByText('包含远程模型开关')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '查看影响并继续' }));
    const dialog = await screen.findByRole('dialog', { name: /确认导入/ });
    expect(within(dialog).getByRole('button', { name: '确认并导入' })).toBeDisabled();
    await user.click(within(dialog).getByRole('checkbox'));
    await user.click(within(dialog).getByRole('button', { name: '确认并导入' }));

    expect(await screen.findByText('配置已导入')).toBeInTheDocument();
    expect(requestBody(transport, 'configuration.import.preview')).toEqual({
      path: '/trusted/rag-ime.config.yaml',
    });
    expect(requestBody(transport, 'configuration.import.apply')).toEqual({
      path: '/trusted/rag-ime.config.yaml',
      expectedRuntimeRevision: 4,
      previewToken: configurationHash,
      confirmText: 'IMPORT RAG-IME CONFIGURATION',
      confirmRemoteModel: 'ALLOW REMOTE MODEL',
    });
    expect(transport.filePickCalls[0]).toMatchObject({
      purpose: 'configuration-import',
      maxFiles: 1,
    });
  });

  it('imports ordinary settings directly after the user has reviewed the file diff', async () => {
    const user = userEvent.setup();
    const transport = renderConfiguration({
      providers: {},
      requiresRemoteModelConfirmation: false,
    });
    await openPortabilityPanel(user);
    const workflow = (await screen.findByText('导入配置', { selector: 'strong' })).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();

    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '选择并校验' }));
    expect(await within(workflow as HTMLElement).findByRole('button', { name: '导入配置' })).toBeEnabled();
    expect(screen.queryByRole('dialog', { name: /确认导入/ })).not.toBeInTheDocument();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '导入配置' }));

    expect(await screen.findByText('配置已导入')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: /确认导入/ })).not.toBeInTheDocument();
    expect(requestBody(transport, 'configuration.import.apply')).toEqual({
      path: '/trusted/rag-ime.config.yaml',
      expectedRuntimeRevision: 4,
      previewToken: configurationHash,
      confirmText: 'IMPORT RAG-IME CONFIGURATION',
    });
  });

  it('exports to a native-selected directory and shows the real receipt path', async () => {
    const user = userEvent.setup();
    const transport = renderConfiguration();
    await openPortabilityPanel(user);

    await user.click(await screen.findByRole('button', { name: '选择目录并导出' }));

    expect(await screen.findByText('/trusted/Backups/rag-ime-backup.ragime-backup')).toBeInTheDocument();
    expect(screen.getByText(/2 个 Rime 文件/)).toBeInTheDocument();
    expect(requestBody(transport, 'configuration.backup.export')).toEqual({
      destination: '/trusted/Backups',
    });
    expect(transport.filePickCalls[0]).toMatchObject({ purpose: 'export-destination' });
  });

  it('shows restore scope and sends the bound token and runtime revision only after confirmation', async () => {
    const user = userEvent.setup();
    const transport = renderConfiguration();
    await openPortabilityPanel(user);

    const restoreWorkflow = (await screen.findByText('恢复可移植备份', { selector: 'strong' })).closest('.mgmt-workflow');
    expect(restoreWorkflow).not.toBeNull();
    await user.click(within(restoreWorkflow as HTMLElement).getByRole('button', { name: '选择并校验' }));
    expect(await screen.findByText('backup.ragime-backup')).toBeInTheDocument();
    expect(screen.getByText('API keys and access tokens')).toBeInTheDocument();
    expect(screen.getByText(/恢复前会自动生成当前数据的回滚包/)).toBeInTheDocument();

    await user.click(within(restoreWorkflow as HTMLElement).getByRole('button', { name: '查看并确认恢复' }));
    const dialog = await screen.findByRole('dialog', { name: /确认恢复/ });
    await user.click(within(dialog).getByRole('checkbox'));
    await user.click(within(dialog).getByRole('button', { name: '确认并恢复' }));

    expect(await screen.findByText('/trusted/rag-ime-rollback-1.ragime-backup')).toBeInTheDocument();
    expect(requestBody(transport, 'configuration.restore.apply')).toEqual({
      path: '/trusted/backup.ragime-backup',
      restoreToken,
      confirmText: 'RESTORE RAG-IME',
      expectedRuntimeRevision: 4,
    });
  });
});

async function openPortabilityPanel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByText('导入、备份与恢复'));
}

class PortabilityTransport extends MockControlTransport {
  override async pickFiles(options: FilePickOptions): Promise<PickedFile[]> {
    this.filePickCalls.push({ ...options });
    const receipts: Record<FilePickOptions['purpose'], PickedFile[]> = {
      attachment: [],
      'knowledge-import': [],
      'room-artifact': [],
      'configuration-import': [{
        id: 'config-file-1',
        name: 'rag-ime.config.yaml',
        mimeType: 'application/yaml',
        byteSize: 512,
        path: '/trusted/rag-ime.config.yaml',
      }],
      'export-destination': [{
        id: 'backup-directory-1',
        name: 'Backups',
        mimeType: 'application/octet-stream',
        byteSize: 0,
        path: '/trusted/Backups',
      }],
      'workspace-root': [],
      'plugin-source': [],
      restore: [{
        id: 'backup-file-1',
        name: 'backup.ragime-backup',
        mimeType: 'application/zip',
        byteSize: 4096,
        path: '/trusted/backup.ragime-backup',
      }],
    };
    return receipts[options.purpose];
  }
}

function renderConfiguration(importOverrides: Record<string, unknown> = {}): PortabilityTransport {
  const routeIds: ControlPathId[] = [
    'configuration.settings',
    'configuration.schema',
    'configuration.import.preview',
    'configuration.import.apply',
    'configuration.backup.export',
    'configuration.restore.preview',
    'configuration.restore.apply',
  ];
  const transport = new PortabilityTransport({
    pickedFiles: [{ id: 'capability', name: 'capability', mimeType: 'text/plain', byteSize: 1, path: '/trusted/capability' }],
    capabilities: { routeIds },
    routes: {
      'configuration.settings': {
        ok: true,
        settings: { context: { tokenBudget: 1024 } },
        runtimeConfig: { runtimeRevision: 4 },
      },
      'configuration.schema': { ok: true, sections: [] },
      'configuration.import.preview': {
        ok: true,
        valid: true,
        errors: [],
        warnings: ['配置会保留未覆盖的设置'],
        settings: { context: { tokenBudget: 2048 } },
        providers: { knowledge: { provider: 'openai' } },
        settingCount: 1,
        requiresRemoteModelConfirmation: true,
        configurationHash,
        requiresConfirmation: 'IMPORT RAG-IME CONFIGURATION',
        runtimeRevision: 4,
        ...importOverrides,
      },
      'configuration.import.apply': {
        ok: true,
        changedKeys: ['context.tokenBudget'],
        requiresRestart: true,
      },
      'configuration.backup.export': {
        ok: true,
        path: '/trusted/Backups/rag-ime-backup.ragime-backup',
        sizeBytes: 2048,
        rimeFileCount: 2,
        secretsIncluded: false,
      },
      'configuration.restore.preview': {
        ok: true,
        valid: true,
        restoreToken,
        runtimeRevision: 4,
        databaseCounts: { input_events: 20, memory_items: 8, planning_tasks: 3 },
        databaseMigrationVersion: 7,
        rimeFileCount: 2,
        exclusions: ['API keys and access tokens', 'model weights'],
        requiresConfirmation: 'RESTORE RAG-IME',
        requiresRestart: true,
      },
      'configuration.restore.apply': {
        ok: true,
        rollbackPath: '/trusted/rag-ime-rollback-1.ragime-backup',
        requiresRestart: true,
      },
    },
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}>
            <ConfigurationFeature />
          </QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  return transport;
}

function requestBody(transport: PortabilityTransport, pathId: ControlPathId) {
  return transport.requests.find(({ request }) => request.pathId === pathId)?.request.body;
}
