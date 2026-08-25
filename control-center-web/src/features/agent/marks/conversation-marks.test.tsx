import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  permissionMarkKind,
  providerMarkInitial,
  providerMarkKind,
} from './conversation-mark-model';
import {
  CapabilityMark,
  PermissionMark,
  ProviderMark,
  WorkspaceMark,
} from './ConversationMarks';

describe('conversation mark model', () => {
  it('gives every execution mode its own permission mark', () => {
    expect(permissionMarkKind('read_only')).toBe('read-only');
    expect(permissionMarkKind('per_action')).toBe('per-action');
    expect(permissionMarkKind('workspace_managed')).toBe('workspace');
    expect(permissionMarkKind('full_trust')).toBe('full-trust');
    // An unknown or absent mode falls back to the confirming mode rather than
    // silently borrowing the 全自动 identity.
    expect(permissionMarkKind(undefined)).toBe('per-action');
    expect(permissionMarkKind('some_future_mode')).toBe('per-action');
  });

  it.each([
    ['openai', 'OpenAI', 'openai'],
    ['openai-codex', 'OpenAI Codex', 'openai'],
    ['gpt', 'GPT', 'openai'],
    ['azure-openai', 'Azure OpenAI', 'openai'],
    ['anthropic', 'Anthropic', 'anthropic'],
    ['claude-code', 'Claude Code', 'anthropic'],
    ['google', 'Gemini', 'google'],
    ['deepseek', 'DeepSeek', 'deepseek'],
    ['dashscope', '通义千问', 'qwen'],
    ['moonshot', 'Kimi', 'moonshot'],
    ['zhipu', '智谱 GLM', 'zhipu'],
    ['xai', 'Grok', 'xai'],
    ['mistral', 'Mistral', 'mistral'],
    ['ollama', 'Ollama', 'local'],
    ['lmstudio', 'LM Studio', 'local'],
    ['openrouter', 'OpenRouter', 'router'],
  ])('maps provider %s to the %s mark family', (id, displayName, expected) => {
    expect(providerMarkKind(id, displayName)).toBe(expected);
  });

  it('keeps a locally served Llama on the on-device mark rather than a vendor mark', () => {
    // `ollama` contains `llama`; ordering, not luck, has to decide this.
    expect(providerMarkKind('ollama', 'Ollama · llama3')).toBe('local');
  });

  it('falls back to an initialled generic mark for an unknown provider', () => {
    expect(providerMarkKind('acme-inference', 'Acme Inference')).toBe('generic');
    expect(providerMarkInitial('acme-inference', 'Acme Inference')).toBe('AC');
    expect(providerMarkInitial('neizhi', '内置模型')).toBe('内');
    expect(providerMarkInitial('', '')).toBe('·');
  });
});

describe('conversation marks', () => {
  it('renders one distinct mark per permission mode', () => {
    const kinds = ['read_only', 'per_action', 'workspace_managed', 'full_trust'].map((mode) => {
      const { container } = render(<PermissionMark mode={mode} />);
      const svg = container.querySelector('svg.paw-mark');
      expect(svg).not.toBeNull();
      return {
        mark: svg?.getAttribute('data-mark'),
        geometry: svg?.innerHTML,
      };
    });

    expect(kinds.map((entry) => entry.mark)).toEqual([
      'permission-read-only',
      'permission-per-action',
      'permission-workspace',
      'permission-full-trust',
    ]);
    expect(new Set(kinds.map((entry) => entry.geometry)).size).toBe(4);
  });

  it('hides an unlabelled mark from assistive technology and names a labelled one', () => {
    const { container } = render(<CapabilityMark />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');

    const labelled = render(<PermissionMark mode="full_trust" title="对话权限：全自动" />);
    const svg = labelled.container.querySelector('svg');
    expect(svg).toHaveAttribute('role', 'img');
    expect(svg).not.toHaveAttribute('aria-hidden');
    expect(svg?.querySelector('title')?.textContent).toBe('对话权限：全自动');
  });

  it('draws the provider mark at the requested collapse size', () => {
    const { container } = render(<ProviderMark providerId="anthropic" size={24} />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('width', '24');
    expect(svg).toHaveAttribute('height', '24');
    expect(svg).toHaveAttribute('viewBox', '0 0 24 24');
  });

  it('states an unbound workspace instead of dropping the chip identity', () => {
    const bound = render(<WorkspaceMark bound />).container.querySelector('svg');
    const unbound = render(<WorkspaceMark bound={false} />).container.querySelector('svg');
    expect(bound).toHaveAttribute('data-mark', 'workspace-bound');
    expect(unbound).toHaveAttribute('data-mark', 'workspace-unbound');
    expect(bound?.innerHTML).not.toBe(unbound?.innerHTML);
  });
});
