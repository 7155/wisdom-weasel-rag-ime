import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ControlTransportProvider } from '@/app/control-transport';
import type { CollaborationProfileCommandReceiptV1 } from '@/contracts/generated/collaboration-profile-command-receipt.v1';
import type { CollaborationProfileProjectionV1 } from '@/contracts/generated/collaboration-profile-projection.v1';
import type { ControlRequest, FrontendCapabilities } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { CollaborationProfileGovernancePanel } from './CollaborationProfileGovernancePanel';

const PROFILE_ROUTE_HASH = 'sha256:53186f4ad0acfd089d4215b79ff3ffa535f12be751f42fd95b9a388059907e13';

describe('CollaborationProfileGovernancePanel', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('loads the canonical projection and renders long Profile text, diff, signature, pointer and receipts accessibly', async () => {
    const projection = profileProjection();
    projection.inspection = inspection({ promptGuidance: ['先核验证据。'.repeat(30), '再独立复核。'] });
    const mock = transport({ projection });
    renderPanel(mock);

    const plane = await screen.findByRole('region', { name: '高级：角色书管理' });
    const details = screen.getByText('高级：角色书管理').closest('details');
    expect(details).not.toHaveAttribute('open');
    await openAdvanced();
    await screen.findByText('角色书当前设置已同步');
    expect(plane).toHaveTextContent('当前版本第 4 版');
    expect(plane).toHaveTextContent('sha256:aaaaaaa');
    expect(screen.getByRole('region', { name: '角色书能力差异' })).toHaveTextContent('基线rag · review · control有效rag · review收窄control拒绝control');
    const prompt = screen.getByLabelText('角色书说明（高级只读）');
    prompt.focus();
    expect(prompt).toHaveFocus();
    expect(prompt).toHaveTextContent('先核验证据');
    expect(screen.getByText(/默认只影响新开始的对话/)).toBeInTheDocument();
    expect(screen.getByText(/正在进行的任务：root-running/)).toBeInTheDocument();
    expect(screen.getByText(/普通伙伴和未绑定角色书的协作不会受影响/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '撤销…' }));
    expect(screen.getByRole('dialog', { name: '确认撤销' })).toHaveTextContent('这个版本不能再次启用');
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(mock.requests.some((call) => call.request.pathId === 'agent.collaborationProfile.command')).toBe(false);
  });

  it('fails closed on route hash mismatch and an unauthenticated remote caller', async () => {
    const projection = profileProjection({ routeHash: `sha256:${'0'.repeat(64)}` });
    renderPanel(transport({ projection }));
    await openAdvanced();
    expect(await screen.findByText('角色书内容已经变化，请刷新后重试')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '恢复上个版本' })).toBeDisabled();

    cleanup();
    const capabilities = capabilityValue();
    (capabilities.raw as { client: Record<string, unknown> }).client = {
      remote: true, deviceAuthenticated: false, grantedScopes: ['agent.write', 'agent.approve'],
    };
    renderPanel(transport({ capabilities }));
    await openAdvanced();
    expect(await screen.findByText('请先完成设备验证，并授予角色书管理权限')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '恢复上个版本' })).toBeDisabled();
  });

  it('submits one typed pipeline command on a double click and verifies the receipt binding', async () => {
    let resolveReceipt!: (value: CollaborationProfileCommandReceiptV1) => void;
    const command = vi.fn((request: ControlRequest) => new Promise<CollaborationProfileCommandReceiptV1>((resolve) => {
      resolveReceipt = resolve;
      const body = request.body as unknown as Record<string, unknown>;
      queueMicrotask(async () => resolveReceipt(receipt(body, { candidateId: 'profile-candidate:1', contentHash: `sha256:${'b'.repeat(64)}`, stage: 'inspected' }, await commandHash(body))));
    }));
    const mock = transport({ command });
    renderPanel(mock);
    await openAdvanced();
    await screen.findByText('角色书当前设置已同步');
    fireEvent.change(screen.getByLabelText('角色书配置（高级 JSON）'), { target: { value: JSON.stringify(bundle()) } });
    const inspect = screen.getByRole('button', { name: '检查' });
    fireEvent.click(inspect);
    fireEvent.click(inspect);
    await waitFor(() => expect(command).toHaveBeenCalledTimes(1));
    expect(command.mock.calls[0]?.[0].body).toMatchObject({
      schemaVersion: 'rag-ime.collaboration-profile-command.v1', action: 'inspect', actorRef: 'control-center:administrator',
    });
    expect(await screen.findByText(/检查 · 已应用/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '验证签名' })).toBeEnabled());
  });

  it('carries the typed candidate through validate, compile, dry-run, stage and new-roots-only activate', async () => {
    const command = vi.fn(async (request: ControlRequest) => {
      const body = request.body as unknown as Record<string, unknown>;
      const action = String(body.action);
      const stage = ({ inspect: 'inspected', validate: 'validated', compile: 'compiled', dry_run: 'dry_run', stage: 'staged' } as Record<string, string>)[action];
      const result = action === 'activate'
        ? { activeContentHash: `sha256:${'b'.repeat(64)}`, pointerRevision: 5, activationScope: body.activationScope, affectedRootIds: ['root-running'] }
        : { candidateId: 'profile-candidate:flow', contentHash: `sha256:${'b'.repeat(64)}`, stage };
      return receipt(body, result, await commandHash(body));
    });
    renderPanel(transport({ command }));
    await openAdvanced();
    await screen.findByText('角色书当前设置已同步');
    fireEvent.change(screen.getByLabelText('角色书配置（高级 JSON）'), { target: { value: JSON.stringify(bundle()) } });
    for (const label of ['检查', '验证签名', '准备内容', '试运行', '待启用']) {
      const button = screen.getByRole('button', { name: label });
      await waitFor(() => expect(button).toBeEnabled());
      fireEvent.click(button);
    }
    const activate = screen.getByRole('button', { name: '启用' });
    await waitFor(() => expect(activate).toBeEnabled());
    fireEvent.click(activate);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(await screen.findByText(/启用 · 已应用/)).toBeInTheDocument();
    const body = command.mock.calls.at(-1)?.[0].body as unknown as Record<string, unknown>;
    expect(body).toMatchObject({
      action: 'activate', activationScope: 'new_roots_only', expectedPointerRevision: 4,
      adminConfirmation: 'ACTIVATE PROFILE', contentHash: `sha256:${'b'.repeat(64)}`,
    });
  });

  it('shows stale revision, hash mismatch, active Root blocker and unknown outcomes without deriving applied', async () => {
    const errors = [
      Object.assign(new Error('profile active pointer revision changed'), { status: 409 }),
      Object.assign(new Error('profile content hash is invalid'), { status: 400 }),
      Object.assign(new Error('active Root pins this profile; use new_roots_only'), { status: 409 }),
      new Error('connection closed before receipt'),
    ];
    for (const [index, error] of errors.entries()) {
      const command = vi.fn(() => { throw error; });
      renderPanel(transport({ command }));
      await openAdvanced();
      await screen.findByText('角色书当前设置已同步');
      fireEvent.click(screen.getByRole('button', { name: '恢复上个版本' }));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      const expected = index === 0 ? /当前版本已经变化/ : index === 1 ? /内容或签名校验未通过/ : index === 2 ? /仍有进行中的任务/ : /操作结果暂时无法确认/;
      expect(await screen.findByText(expected)).toBeInTheDocument();
      expect(screen.queryByText(/恢复上个版本 · 已应用/)).not.toBeInTheDocument();
      cleanup();
      vi.restoreAllMocks();
    }
  });

  it('keeps missing Profile and ordinary non-Room Agents on the fallback path', async () => {
    const missing = Object.assign(new Error('not found'), { status: 404 });
    renderPanel(transport({ get: () => { throw missing; } }));
    await openAdvanced();
    expect(await screen.findByText(/这份角色书尚未安装/)).toBeInTheDocument();
    expect(screen.getByText(/普通伙伴和未绑定角色书的协作会继续/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '启用' })).not.toBeInTheDocument();
  });
});

function renderPanel(mock: MockControlTransport) {
  return render(<ControlTransportProvider transport={mock}><CollaborationProfileGovernancePanel profileId="evidence-review" /></ControlTransportProvider>);
}

async function openAdvanced() {
  fireEvent.click(await screen.findByText('高级：角色书管理'));
}

function transport(options: { projection?: CollaborationProfileProjectionV1; command?: (request: ControlRequest) => unknown; capabilities?: FrontendCapabilities; get?: () => unknown } = {}) {
  return new MockControlTransport({
    capabilities: options.capabilities ?? capabilityValue(),
    routes: {
      'agent.collaborationProfile.get': options.get ?? (() => options.projection ?? profileProjection()),
      'agent.collaborationProfile.command': options.command ?? ((request: ControlRequest) => receipt(request.body as unknown as Record<string, unknown>, {})),
    },
  });
}

function capabilityValue(): FrontendCapabilities {
  return {
    schemaVersion: 'rag-ime.control-capabilities.v1', transport: 'http',
    routeIds: ['agent.collaborationProfile.get', 'agent.collaborationProfile.command'], features: {},
    native: { pickFiles: false, managedAgentImageImport: false, revealPath: false, approvedExternalActions: false, keychain: false, tcc: false },
    raw: {
      client: { remote: false, deviceAuthenticated: false, grantedScopes: [] },
      routes: [
        route('agent.collaborationProfile.get', 'GET', ['profileId'], ['agent.read']),
        route('agent.collaborationProfile.command', 'POST', [], ['agent.write', 'agent.approve']),
      ],
    },
  };
}

function route(pathId: string, method: string, params: string[], remoteScopes: string[]) {
  return { pathId, method, remoteSafe: true, subscription: false, params, query: [], remoteScopes };
}

function profileProjection(overrides: Partial<CollaborationProfileProjectionV1> = {}): CollaborationProfileProjectionV1 {
  return {
    schemaVersion: 'rag-ime.collaboration-profile-projection.v1', profileId: 'evidence-review', routeHash: PROFILE_ROUTE_HASH,
    requiredReadScopes: ['agent.read'], requiredWriteScopes: ['agent.write', 'agent.approve'], guardEpoch: 3,
    normalAgentFallback: true, inspection: inspection(), recentReceipts: [activateReceipt() as unknown as Record<string, unknown>, compileReceipt() as unknown as Record<string, unknown>], ...overrides,
  };
}

function inspection(manifestOverrides: Record<string, unknown> = {}) {
  const manifest = {
    schemaVersion: 'rag-ime.collaboration-profile.v1', profileId: 'evidence-review', version: '2', displayName: '证据复核',
    summary: '研究后独立复核。', collaborationRoleRefs: ['researcher@1'], capabilityRequests: ['rag', 'review', 'control'],
    requiredGateIds: ['evidence-required'], promptGuidance: ['区分事实与推断'], trustTier: 'signed', ...manifestOverrides,
  };
  return {
    schemaVersion: 'rag-ime.collaboration-profile-inspection.v1', profileId: 'evidence-review', pointerRevision: 4,
    active: { profileId: 'evidence-review', version: '2', contentHash: `sha256:${'a'.repeat(64)}`, pointerRevision: 4, compileReceiptId: 'profile-compile:aaaaaaaaaaaaaaaaaaaaaaaa', bindingRevision: 'binding-9' },
    versions: [{ contentHash: `sha256:${'a'.repeat(64)}`, version: '2', manifest, compileReceiptId: 'profile-compile:aaaaaaaaaaaaaaaaaaaaaaaa', revoked: false, revokeReason: '', stagedAtMs: 2 }],
  };
}

function compileReceipt() {
  return receipt({ commandId: 'profile-command:compile:1', action: 'compile' }, {
    receiptId: 'profile-compile:aaaaaaaaaaaaaaaaaaaaaaaa', bindingRevision: 'binding-9',
    baselineCapabilities: ['rag', 'review', 'control'], effectiveCapabilities: ['rag', 'review'], rejectedCapabilities: ['control'],
  });
}

function activateReceipt() {
  return receipt({ commandId: 'profile-command:activate:1', action: 'activate' }, {
    activeContentHash: `sha256:${'a'.repeat(64)}`, previousContentHash: null, pointerRevision: 4,
    activationScope: 'new_roots_only', affectedRootIds: ['root-running'], guardEpoch: 3,
  });
}

function receipt(command: Record<string, unknown>, result: Record<string, unknown>, hash = `sha256:${'d'.repeat(64)}`): CollaborationProfileCommandReceiptV1 {
  return {
    schemaVersion: 'rag-ime.collaboration-profile-command-receipt.v1', receiptId: `profile-command-receipt:${'c'.repeat(24)}`,
    commandId: String(command.commandId || 'profile-command:fixture:1'), commandHash: hash,
    action: (command.action || 'inspect') as CollaborationProfileCommandReceiptV1['action'], status: 'applied',
    profileId: 'evidence-review', routeHash: PROFILE_ROUTE_HASH, guardEpoch: 3, result, createdAtMs: 3,
  };
}

async function commandHash(value: Record<string, unknown>) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalJson(value)));
  return `sha256:${Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, '0')).join('')}`;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (typeof value === 'object' && value !== null) {
    const item = value as Record<string, unknown>;
    return `{${Object.keys(item).filter((key) => item[key] !== undefined).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(item[key])}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

function bundle() {
  return {
    manifest: { schemaVersion: 'rag-ime.collaboration-profile.v1', profileId: 'evidence-review', version: '3', displayName: '证据复核', summary: 'new', collaborationRoleRefs: ['researcher@1'], capabilityRequests: ['rag'], requiredGateIds: ['evidence-required'], promptGuidance: ['核验证据'], trustTier: 'signed' },
    files: { 'README.md': '声明式说明' }, signature: { signerId: 'admin', value: `hmac-sha256:${'e'.repeat(64)}` },
  };
}
