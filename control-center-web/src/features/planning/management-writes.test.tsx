import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import { TooltipProvider } from '@/components/primitives';
import type { ControlPathId } from '@/platform/routes';
import type {
  ControlEventObserver,
  ControlRequest,
  ControlSubscription,
  ControlTransport,
  FrontendCapabilities,
} from '@/platform/transport';
import { PlanningFeature } from '.';

const now = 1_784_006_400_000;
const saveHash = 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const actionHash = 'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

afterEach(cleanup);

describe('Planning WorkContract UI', () => {
  it('derives the companion workbench from the live dashboard', async () => {
    renderPlanning();
    expect(await screen.findByText('完成 Web 迁移', { selector: '.planning-companion__focus strong' })).toBeInTheDocument();
    expect(screen.getByText('继续：完成管理页')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '交给智鼬整理' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '请智鼬拆解' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '一起复盘' })).toBeEnabled();
  });

  it('binds task save preview to apply receipt and rollback', async () => {
    const user = userEvent.setup();
    const transport = renderPlanning();
    await screen.findByRole('heading', { name: '规划', level: 1 });

    await user.type(await screen.findByPlaceholderText('例如：完成前台输入 smoke'), '验证真实 Planning 写入');
    const detail = document.getElementById('planning-task-detail');
    expect(detail).not.toBeNull();
    await user.type(detail as HTMLElement, '先预览，再应用并回滚');
    const workflow = screen.getByText('创建任务', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '预览操作' }));

    await waitFor(() => expect(findRequest(transport, 'planning.mutation.preview')).toMatchObject({
      body: {
        kind: 'task.save',
        expectedRuntimeRevision: 7,
        payload: { title: '验证真实 Planning 写入', detail: '先预览，再应用并回滚' },
      },
    }));
    expect(await within(workflow as HTMLElement).findByText('保存任务影响')).toBeInTheDocument();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '进入确认' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox', { name: '只执行上方已绑定的变更' }));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认并应用' }));

    expect(await within(workflow as HTMLElement).findByText('receipt-task-save')).toBeInTheDocument();
    expect(findRequest(transport, 'planning.task.save')).toMatchObject({
      body: {
        title: '验证真实 Planning 写入',
        previewToken: 'preview-task-save',
        payloadSha256: saveHash,
        confirmText: 'apply',
        expectedRuntimeRevision: 7,
      },
    });
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '回滚' }));
    expect(await within(workflow as HTMLElement).findByText('receipt-task-save-rollback')).toBeInTheDocument();
    expect(findRequest(transport, 'planning.mutation.rollback')).toMatchObject({
      body: {
        receiptId: 'receipt-task-save',
        rollbackToken: 'rollback-task-save',
        payloadSha256: saveHash,
        confirmText: 'rollback',
      },
    });
  });

  it('uses the task action event receipt as the only undo authority', async () => {
    const user = userEvent.setup();
    const transport = renderPlanning();
    await screen.findByRole('heading', { name: '规划', level: 1 });
    const taskSection = (await screen.findByRole('heading', { name: '任务', level: 2 })).closest('section');
    expect(taskSection).not.toBeNull();
    await user.click(within(taskSection as HTMLElement).getByRole('button', { name: /完成管理页/ }));

    const workflow = screen.getByText('完成所选任务', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '预览操作' }));
    await within(workflow as HTMLElement).findByText('任务状态影响');
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '进入确认' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认并应用' }));
    expect(await within(workflow as HTMLElement).findByText('receipt-task-action')).toBeInTheDocument();

    expect(findRequest(transport, 'planning.task.action')).toMatchObject({
      body: {
        taskId: 'task-1',
        action: 'complete',
        previewToken: 'preview-task-action',
        payloadSha256: actionHash,
      },
    });
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '回滚' }));
    expect(await within(workflow as HTMLElement).findByText('receipt-task-undo')).toBeInTheDocument();
    expect(findRequest(transport, 'planning.taskEvent.undo')).toMatchObject({
      body: {
        eventId: 'task-event:1',
        receiptId: 'receipt-task-action',
        rollbackToken: 'rollback-task-action',
        payloadSha256: actionHash,
        confirmText: 'undo',
      },
    });
  });

  it('keeps a rejected apply visible and does not invent a receipt', async () => {
    const user = userEvent.setup();
    renderPlanning(true);
    await user.type(await screen.findByPlaceholderText('例如：完成前台输入 smoke'), '触发版本冲突');
    const workflow = screen.getByText('创建任务', { selector: 'strong' }).closest('.mgmt-workflow');
    expect(workflow).not.toBeNull();
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '预览操作' }));
    await within(workflow as HTMLElement).findByText('保存任务影响');
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '进入确认' }));
    await user.click(within(workflow as HTMLElement).getByRole('checkbox'));
    await user.click(within(workflow as HTMLElement).getByRole('button', { name: '确认并应用' }));
    expect(await within(workflow as HTMLElement).findByText('运行版本已变化，请重新预览。')).toBeInTheDocument();
    expect(within(workflow as HTMLElement).queryByText(/receipt-task-save/)).not.toBeInTheDocument();
  });
});

class PlanningTransport implements ControlTransport {
  readonly kind = 'mock' as const;
  readonly requests: ControlRequest[] = [];

  constructor(private readonly failTaskSave = false) {}

  async capabilities(): Promise<FrontendCapabilities> {
    return {
      schemaVersion: 'rag-ime.control-frontend-capabilities.v1',
      transport: 'mock',
      routeIds: [
        'planning.dashboard',
        'planning.mutation.preview',
        'planning.task.save',
        'planning.task.action',
        'planning.taskEvent.undo',
        'planning.mutation.rollback',
      ] as unknown as ControlPathId[],
      features: { managementWorkContract: true, planningWorkContract: true },
      native: { pickFiles: false, managedAgentImageImport: false, revealPath: false, approvedExternalActions: false, keychain: false, tcc: false },
    };
  }

  async request<Response = unknown>(request: ControlRequest): Promise<Response> {
    this.requests.push(request);
    const pathId = String(request.pathId);
    if (pathId === 'planning.dashboard') return planningDashboard() as Response;
    if (pathId === 'planning.mutation.preview') {
      const body = request.body as { kind?: unknown };
      const action = body.kind === 'task.action';
      return previewResponse(
        action ? 'planning.task.action' : 'planning.task.save',
        action ? 'preview-task-action' : 'preview-task-save',
        action ? actionHash : saveHash,
        action ? '任务状态影响' : '保存任务影响',
      ) as Response;
    }
    if (pathId === 'planning.task.save' && this.failTaskSave) return { ok: false, error: '运行版本已变化，请重新预览。', code: 'stale_revision' } as Response;
    if (pathId === 'planning.task.save') return receipt('planning.task.save', saveHash, 'receipt-task-save', 'rollback-task-save') as Response;
    if (pathId === 'planning.task.action') return {
      ...receipt('planning.task.action', actionHash, 'receipt-task-action', 'rollback-task-action'),
      eventId: 'task-event:1',
    } as Response;
    if (pathId === 'planning.mutation.rollback') return receipt('planning.mutation.rollback', saveHash, 'receipt-task-save-rollback', '', false) as Response;
    if (pathId === 'planning.taskEvent.undo') return receipt('planning.taskEvent.undo', actionHash, 'receipt-task-undo', '', false) as Response;
    throw new Error(`Unexpected request: ${pathId}`);
  }

  subscribe<Event = unknown>(_request: ControlSubscription, _observer: ControlEventObserver<Event>): () => void {
    return () => {};
  }
}

function renderPlanning(failTaskSave = false): PlanningTransport {
  const transport = new PlanningTransport(failTaskSave);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <MemoryRouter>
      <TooltipProvider delayDuration={0}>
        <ControlTransportProvider transport={transport}>
          <QueryClientProvider client={client}><PlanningFeature /></QueryClientProvider>
        </ControlTransportProvider>
      </TooltipProvider>
    </MemoryRouter>,
  );
  return transport;
}

function findRequest(transport: PlanningTransport, pathId: string): ControlRequest | undefined {
  return transport.requests.find((request) => String(request.pathId) === pathId);
}

function planningDashboard() {
  return {
    ok: true,
    runtimeRevision: 7,
    date: '2026-07-14',
    plan: { intention: '完成 Web 迁移', notes: '', reflection: '', project: 'wisdom-weasel-rag-ime' },
    tasks: [{ id: 'task-1', title: '完成管理页', detail: '接通真实写入', status: 'in_progress', source: 'manual' }],
    goals: [],
    pendingCompletionSuggestions: [],
    recentDetectedCompletion: null,
    summary: { taskCount: 1, openTaskCount: 1, completedTaskCount: 0, goalCount: 0, progress: 0 },
    assistant: { message: '把写入链路收束为一条可回滚路径。' },
  };
}

function previewResponse(pathId: string, previewToken: string, payloadSha256: string, title: string) {
  return {
    schemaVersion: 'rag-ime.management-work-preview.v1',
    ok: true,
    previewToken,
    pathId,
    payloadSha256,
    expectedRevision: { runtimeRevision: 7 },
    expiresAtMs: Date.now() + 60_000,
    requiredConfirm: 'apply',
    summary: { title, items: ['核对绑定字段', '写入后返回可验证收据'], risk: 'R1' },
  };
}

function receipt(pathId: string, payloadSha256: string, receiptId: string, rollbackToken: string, rollbackAvailable = true) {
  return {
    ok: true,
    receiptId,
    pathId,
    payloadSha256,
    appliedAtMs: now,
    auditId: 11,
    rollbackAvailable,
    rollbackToken,
    restartComponents: [],
  };
}
