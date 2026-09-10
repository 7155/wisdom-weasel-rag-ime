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
import { countAvailableTools } from './tool-policy';

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
  capabilityCatalog = catalog(),
  onCapabilityPreferenceChange,
  onSelect = () => {},
}: {
  adjustmentDisabled?: boolean;
  capabilityCatalog?: CapabilityCatalog;
  onCapabilityPreferenceChange?: (
    canonicalId: string,
    preference: CapabilityPreference,
  ) => void;
  onSelect?: (tool: ToolManifest) => void;
} = {}) {
  const handlePreferenceChange = onCapabilityPreferenceChange ?? vi.fn();
  render(
    <ToolPicker
      adjustmentDisabled={adjustmentDisabled}
      capabilityCatalog={capabilityCatalog}
      capabilityPolicyPending={false}
      disabled={false}
      onCapabilityPreferenceChange={handlePreferenceChange}
      onSelect={onSelect}
      requestOpen={0}
      session={previewSessions[0]}
      status="ready"
      tools={tools}
    />,
  );
  return handlePreferenceChange;
}

describe('ToolPicker conversation capability presentation', () => {
  it('exposes an actual plugin preference without mixing it into tool rows', async () => {
    const value = catalog();
    value.items.push({ ...value.items[0]!, id: 'session-review', canonicalId: 'extension:session-review', kind: 'extension', displayName: '对话复盘', description: '复盘插件' });
    const changed = renderPicker({ capabilityCatalog: value });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '当前对话插件与技能' }));
    await user.click(screen.getByRole('combobox', { name: '对话复盘的当前对话使用' }));
    await user.click(screen.getByRole('option', { name: '当前对话关闭' }));
    expect(changed).toHaveBeenCalledWith('extension:session-review', 'disabled');
    expect(screen.queryByRole('combobox', { name: '记忆召回的当前对话使用' })).not.toBeInTheDocument();
  });
  it('keeps a stale Session catalog out of the current memory label and controls', () => {
    const stale = catalog();
    stale.sessionPolicy!.sessionId = 'previous-session';
    renderPicker({ capabilityCatalog: stale });
    expect(screen.getByRole('button', { name: '能力列表正在读取' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /当前对话记忆/ })).not.toBeInTheDocument();
  });

  it('uses the matching backend capability policy before Session display metadata arrives', () => {
    const coordinatorTool = { ...tools[0], sessionModes: ['coordinator'] as const } as ToolManifest;
    const provisional = { ...previewSessions[0], mode: 'assistant' as const, toolProfileVersion: undefined };
    expect(countAvailableTools([coordinatorTool], provisional, catalog())).toBe(1);
  });

  it('does not use another Session capability policy to count executable tools', () => {
    const wrongOwner = catalog();
    wrongOwner.sessionPolicy!.sessionId = 'different-session';
    expect(countAvailableTools(tools, previewSessions[0], wrongOwner)).toBe(0);
  });

  it('shows the current memory state before opening the menu and jumps directly to its control', async () => {
    const change = renderPicker();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '当前对话记忆已开启，打开记忆开关' }));
    expect(screen.getByRole('textbox', { name: '搜索工具' })).toHaveValue('记忆');
    expect(screen.getByRole('combobox', { name: '记忆召回的当前对话使用' })).toBeVisible();
    expect(screen.queryByRole('combobox', { name: '知识库 / Agent RAG的当前对话使用' })).not.toBeInTheDocument();
    expect(change).not.toHaveBeenCalled();
  });

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
    expect(memoryRow).toHaveTextContent('把相关记忆加入对话，并允许 Agent 查询记忆。关闭后从下一轮停止使用；不会删除已保存的记忆。');
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

  it('finds a tool by its role or original name, and recovers from an empty search', async () => {
    renderPicker();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '这段对话可执行工具：1 个；已登记工具：2 个' }));
    const search = screen.getByRole('textbox', { name: '搜索工具' });
    expect(search).toHaveFocus();
    await user.type(search, '自举');
    expect(screen.getByRole('button', { name: '记忆召回' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '知识库 / Agent RAG' })).not.toBeInTheDocument();
    await user.clear(search);
    await user.type(search, '记忆与工具书');
    expect(screen.getByRole('button', { name: '记忆召回' })).toBeInTheDocument();
    await user.clear(search);
    await user.type(search, '没有这个工具');
    expect(screen.getByRole('status')).toHaveTextContent('没有找到工具');
    await user.click(screen.getByRole('button', { name: '清空工具搜索' }));
    expect(search).toHaveFocus();
    expect(screen.getByRole('button', { name: '知识库 / Agent RAG' })).toBeInTheDocument();
  });

  it('keeps selecting an available tool separate from changing its preference', async () => {
    const onSelect = vi.fn();
    const onPreferenceChange = renderPicker({ onSelect });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '这段对话可执行工具：1 个；已登记工具：2 个' }));
    await user.click(screen.getByRole('button', { name: '记忆召回' }));
    expect(onSelect).toHaveBeenCalledWith(tools[0]);
    expect(onPreferenceChange).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: '当前对话工具' })).not.toBeInTheDocument();
  });
});
