import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import {
  requireSessionCapabilityCatalog,
  type CapabilityCatalog,
} from '@/features/plugins/capability-policy';
import { CapabilitySessionView } from './CapabilitySessionView';

afterEach(cleanup);

describe('CapabilitySessionView', () => {
  it('opens a searchable current-conversation dialog and applies only a temporary override', async () => {
    const user = userEvent.setup();
    const onPreferenceChange = vi.fn();
    render(
      <MemoryRouter>
        <CapabilitySessionView
          busy={false}
          catalog={catalog()}
          status="ready"
          onPreferenceChange={onPreferenceChange}
          onRetryCatalog={() => {}}
          onRetryMutation={() => {}}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText('当前对话会提供 1 项能力')).toBeVisible();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    const manageButton = screen.getByRole('button', { name: '管理当前对话的工具与技能' });
    await user.click(manageButton);

    const dialog = screen.getByRole('dialog', { name: '管理当前对话的工具与技能' });
    expect(screen.getByRole('link', { name: '管理所有对话与当前项目默认' }))
      .toHaveAttribute('href', '/plugins?sessionId=session-capability');
    const preference = screen.getByRole('combobox', { name: '我的记忆的当前对话临时设置' });
    expect(preference).toHaveTextContent('继承默认');
    await user.click(preference);
    await user.click(await screen.findByRole('option', { name: '不向伙伴披露' }));
    expect(onPreferenceChange).toHaveBeenCalledWith('tool:memory', 'disabled');
    expect(dialog).toHaveTextContent('当前对话临时设置在下一次打开或下一轮对话时生效');
    expect(dialog).toHaveTextContent('披露能力不代表已获得执行授权');
    expect(dialog).toHaveTextContent('受控变更');
    await user.click(screen.getByText('查看来源、权限和生效依据'));
    expect(dialog).toHaveTextContent('已由现有策略授权');
    expect(dialog).toHaveTextContent('需要逐项确认');
    expect(screen.getByText('项目默认').closest('div')).toHaveTextContent('向伙伴披露');

    const search = screen.getByRole('searchbox', { name: '搜索工具、技能或扩展' });
    await user.type(search, '没有这项能力');
    expect(screen.getByText('没有匹配的能力')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '清除搜索' }));
    expect(screen.getByText('我的记忆')).toBeVisible();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(manageButton).toHaveFocus();
  });

  it('rejects a catalog owned by another Session instead of projecting its preferences', () => {
    expect(() => requireSessionCapabilityCatalog(catalog(), 'session-other'))
      .toThrow('能力目录不属于当前对话；不会显示或修改其他对话的设置。');
    expect(requireSessionCapabilityCatalog(catalog(), 'session-capability').sessionPolicy?.sessionId)
      .toBe('session-capability');
  });

  it('disables current-conversation changes while the Agent Loop is active', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <CapabilitySessionView
          busy
          catalog={catalog()}
          status="ready"
          onPreferenceChange={() => {}}
          onRetryCatalog={() => {}}
          onRetryMutation={() => {}}
        />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: '管理当前对话的工具与技能' }));

    expect(screen.getByRole('combobox', { name: '我的记忆的当前对话临时设置' })).toBeDisabled();
    expect(screen.getByText(/当前响应仍在进行，暂不能调整/)).toBeVisible();
  });

  it('reports a strict catalog version mismatch and retries without guessing old fields', async () => {
    const user = userEvent.setup();
    const onRetryCatalog = vi.fn();
    render(
      <MemoryRouter>
        <CapabilitySessionView
          busy={false}
          error="能力目录版本不匹配：当前前端需要 rag-ime.capability-catalog.v1，后端返回 rag-ime.control-tool-list.v1。不会按旧目录猜测披露状态或发送修改。"
          status="failed"
          onPreferenceChange={() => {}}
          onRetryCatalog={onRetryCatalog}
          onRetryMutation={() => {}}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('rag-ime.control-tool-list.v1');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(onRetryCatalog).toHaveBeenCalledTimes(1);
  });

  it('shows the owning mutation failure and retries the exact current-conversation setting', async () => {
    const user = userEvent.setup();
    const onRetryMutation = vi.fn();
    render(
      <MemoryRouter>
        <CapabilitySessionView
          busy={false}
          catalog={catalog()}
          mutation={{
            canonicalId: 'tool:memory',
            preference: 'disabled',
            status: 'failed',
            message: '策略修订冲突',
          }}
          status="ready"
          onPreferenceChange={() => {}}
          onRetryCatalog={() => {}}
          onRetryMutation={onRetryMutation}
        />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: '管理当前对话的工具与技能' }));

    expect(screen.getByRole('alert')).toHaveTextContent('策略修订冲突');
    await user.click(screen.getByRole('button', { name: '重试这项调整' }));
    expect(onRetryMutation).toHaveBeenCalledTimes(1);
  });
});

function catalog(): CapabilityCatalog {
  return {
    schemaVersion: 'rag-ime.capability-catalog.v1',
    ok: true,
    revision: `sha256:${'a'.repeat(64)}`,
    effectiveAtMs: 1,
    projectScope: {
      supported: true,
      identityKind: 'workspace_scope_sha256',
      projectId: `workspace-${'b'.repeat(64)}`,
      reason: 'session_workspace_scope',
    },
    sessionPolicy: {
      sessionId: 'session-capability',
      policyRevision: 2,
      disclosurePreferences: {
        globalDefault: { 'tool:memory': 'disabled' },
        projectDefault: { 'tool:memory': 'enabled' },
        session: {},
        effective: { 'tool:memory': 'enabled' },
      },
      effectiveAtMs: 1,
    },
    items: [{
      id: 'memory',
      canonicalId: 'tool:memory',
      kind: 'tool',
      displayName: '我的记忆',
      description: '检索已治理记忆',
      source: { kind: 'product', label: 'Personal Agent Workbench' },
      status: 'online',
      risk: 'R1',
      requiredPermissions: ['native_approval'],
      authorization: { state: 'authorized', reason: 'existing_session_policy_authorizes_tool' },
      disclosure: {
        preference: 'inherit',
        effective: 'enabled',
        state: 'disclosed',
        reason: 'inherited_project_default',
      },
      effectiveScope: 'project_default',
      reasons: ['inherited_project_default'],
      revision: 'tool-spec:1',
      effectiveAtMs: 1,
    }],
  };
}
