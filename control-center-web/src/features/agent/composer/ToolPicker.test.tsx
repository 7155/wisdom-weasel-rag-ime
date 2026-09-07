import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type {
  CapabilityCatalog,
  CapabilityPreference,
} from '@/features/plugins/capability-policy';
import { previewSessions } from '../preview-data';
import type { ToolManifest } from '../types';
import { ToolPicker } from './ToolPicker';

afterEach(cleanup);

const tools: ToolManifest[] = [
  {
    schemaVersion: 'rag-ime.control-tool-manifest.v1',
    id: 'memory',
    domain: 'memory',
    displayName: '记忆与工具书',
    description: '原始记忆工具说明',
    category: 'memory',
    riskLevel: 'R0',
    sessionModes: ['assistant', 'coordinator'],
    operations: ['status'],
    resultPresentation: 'tool_result',
    availability: 'online',
    version: '1',
  },
  {
    schemaVersion: 'rag-ime.control-tool-manifest.v1',
    id: 'knowledge',
    domain: 'knowledge',
    displayName: '知识检索',
    description: '原始知识工具说明',
    category: 'knowledge',
    riskLevel: 'R0',
    sessionModes: ['assistant', 'coordinator'],
    operations: ['status'],
    resultPresentation: 'tool_result',
    availability: 'online',
    version: '1',
  },
];

function catalog(): CapabilityCatalog {
  const items = tools.map((tool) => {
    const canonicalId = `tool:${tool.id}`;
    const disabled = tool.id === 'knowledge';
    return {
      id: tool.id,
      canonicalId,
      kind: 'tool' as const,
      displayName: tool.displayName,
      description: tool.description,
      source: { kind: 'built_in', label: 'Control Center' },
      status: 'available',
      risk: tool.riskLevel,
      requiredPermissions: [],
      authorization: { state: 'authorized' as const, reason: 'Focused picker fixture.' },
      disclosure: {
        preference: disabled ? 'disabled' as const : 'inherit' as const,
        effective: disabled ? 'disabled' as const : 'enabled' as const,
        state: disabled ? 'hidden' as const : 'disclosed' as const,
        reason: 'Focused picker fixture.',
      },
      effectiveScope: disabled ? 'session' as const : 'built_in_default' as const,
      reasons: [],
      revision: `${canonicalId}:1`,
      effectiveAtMs: 1,
    };
  });
  return {
    schemaVersion: 'rag-ime.capability-catalog.v1',
    ok: true,
    revision: 'catalog-1',
    effectiveAtMs: 1,
    projectScope: { supported: false, identityKind: 'none', reason: 'Focused picker fixture.' },
    sessionPolicy: {
      sessionId: previewSessions[0].id,
      policyRevision: 1,
      disclosurePreferences: {
        globalDefault: {},
        projectDefault: {},
        session: { 'tool:knowledge': 'disabled' },
        effective: { 'tool:memory': 'enabled', 'tool:knowledge': 'disabled' },
      },
      effectiveAtMs: 1,
    },
    items,
  };
}

function renderPicker({
  adjustmentDisabled = false,
  onCapabilityPreferenceChange,
}: {
  adjustmentDisabled?: boolean;
  onCapabilityPreferenceChange?: (
    canonicalId: string,
    preference: CapabilityPreference,
  ) => void;
} = {}) {
  const handlePreferenceChange = onCapabilityPreferenceChange ?? vi.fn();
  render(
    <ToolPicker
      adjustmentDisabled={adjustmentDisabled}
      capabilityCatalog={catalog()}
      capabilityPolicyPending={false}
      disabled={false}
      onCapabilityPreferenceChange={handlePreferenceChange}
      onSelect={() => {}}
      requestOpen={0}
      session={previewSessions[0]}
      status="ready"
      tools={tools}
    />,
  );
  return handlePreferenceChange;
}

describe('ToolPicker conversation capability presentation', () => {
  it('counts only capabilities that the current session can actually disclose', async () => {
    renderPicker();

    expect(screen.getByRole('button', { name: '这段对话可执行工具：1 个；已登记工具：2 个' })).toBeInTheDocument();
  });

  it('names Memory and Knowledge by their user-facing role while preserving canonical preferences', async () => {
    const onPreferenceChange = renderPicker();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '这段对话可执行工具：1 个；已登记工具：2 个' }));
    const dialog = screen.getByRole('dialog', { name: '当前对话工具' });

    const memoryRow = within(dialog).getByRole('button', { name: /^记忆召回/ }).closest('article')!;
    expect(memoryRow).toHaveTextContent('控制本对话的自动记忆自举、压缩后召回和记忆工具查询，从下一轮生效。');
    expect(memoryRow).toHaveTextContent('已启用');
    expect(memoryRow).toHaveTextContent('产品内置默认');

    const knowledgeRow = within(dialog).getByRole('button', { name: /^知识库 \/ Agent RAG/ }).closest('article')!;
    expect(knowledgeRow).toHaveTextContent('启用后，Agent 可按当前问题反复检索已允许的知识库。');
    expect(knowledgeRow).toHaveTextContent('已关闭');
    expect(knowledgeRow).toHaveTextContent('当前对话临时设置');

    await user.click(within(dialog).getByRole('combobox', { name: '记忆召回的当前对话使用' }));
    await user.click(await screen.findByRole('option', { name: '当前对话关闭' }));
    expect(onPreferenceChange).toHaveBeenCalledWith('tool:memory', 'disabled');
  });

  it('keeps capability use read-only while a turn is running', async () => {
    const onPreferenceChange = renderPicker({ adjustmentDisabled: true });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '这段对话可执行工具：1 个；已登记工具：2 个' }));
    const dialog = screen.getByRole('dialog', { name: '当前对话工具' });

    expect(within(dialog).getByText('当前任务正在运行；可以查看工具，但要等本轮结束后再调整。'))
      .toBeInTheDocument();
    expect(within(dialog).getByRole('combobox', { name: '记忆召回的当前对话使用' }))
      .toBeDisabled();
    expect(within(dialog).getByRole('combobox', { name: '知识库 / Agent RAG的当前对话使用' }))
      .toBeDisabled();
    expect(onPreferenceChange).not.toHaveBeenCalled();
  });
});
