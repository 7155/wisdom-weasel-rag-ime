import { describe, expect, it } from 'vitest';
import {
  canonicalToolId,
  projectPublicToolCatalog,
  projectPublicToolPreferenceMap,
  publicToolName,
  toolIntentPrompt,
} from './tool-presentation';

describe('tool presentation', () => {
  it('keeps stable runtime ids behind human-facing names', () => {
    expect(publicToolName('overview', '控制中心概览')).toBe('当前状态');
    expect(publicToolName('workspace_shell', '受控命令')).toBe('运行命令');
    expect(publicToolName('workspace_lsp', 'Workspace LSP')).toBe('代码智能');
    expect(publicToolName('read_file')).toBe('读取文件');
    expect(publicToolName('control_api')).toBe('调用控制服务');
    expect(publicToolName('custom_tool', '自定义检查')).toBe('自定义检查');
    expect(publicToolName('custom_tool', 'schema /api/private')).toBe('工具操作');
  });

  it('keeps precise read-side action labels outside the catalog projection', () => {
    expect(canonicalToolId('workspace_search')).toBe('grep');
    expect(canonicalToolId('workspace_list')).toBe('ls');
    expect(publicToolName('workspace_search')).toBe('搜索文本');
    expect(publicToolName('workspace_list')).toBe('浏览目录');
    expect(publicToolName('workspace_lsp', 'Workspace LSP')).toBe('代码智能');
  });

  it('collapses legacy and governed adapters onto the four public coding tools', () => {
    expect(canonicalToolId('workspace_read')).toBe('read');
    expect(canonicalToolId('read_file')).toBe('read');
    expect(canonicalToolId('workspace_edit')).toBe('edit');
    expect(canonicalToolId('apply_patch')).toBe('edit');
    expect(canonicalToolId('workspace_write')).toBe('write');
    expect(canonicalToolId('write_file')).toBe('write');
    expect(canonicalToolId('workspace_shell')).toBe('bash');
    expect(canonicalToolId('workspace_job')).toBe('bash');
  });

  it('turns a picker choice into a natural task instead of a tool command', () => {
    expect(toolIntentPrompt('overview', '控制中心概览')).toBe('帮我看看当前状态');
    expect(toolIntentPrompt('workspace_read', '工作区读取')).toBe('帮我读取这个项目文件');
    expect(toolIntentPrompt('custom_tool', '自定义检查')).toBe('帮我用自定义检查处理');
  });

  it('groups historical adapters into one merged public catalog entry per tool', () => {
    const projected = projectPublicToolCatalog([
      tool('workspace_read', '工作区读取', false, ['read_range']),
      tool('read_file', 'Read file', true, ['read']),
      tool('read', 'Canonical provider read', false, ['tail']),
      tool('workspace_search', '工作区搜索', false, ['search']),
      tool('workspace_list', '工作区浏览', false, ['list']),
      tool('workspace_lsp', '代码智能', false, ['symbols']),
      tool('grep', 'Grep', false, ['grep']),
      tool('find', 'Find', false, ['find']),
      tool('ls', 'List', false, ['ls']),
      tool('workspace_edit', '工作区修改', true, ['replace']),
      tool('apply_patch', 'Apply patch', false, ['patch']),
      tool('write_file', 'Write file', true, ['write']),
      tool('workspace_write', '工作区写入', false, ['create']),
      tool('workspace_shell', '受控命令', false, ['run']),
      tool('shell', 'Shell', true, ['stream']),
      tool('workspace_job', '后台任务', false, ['poll']),
      tool('input', '输入法', true, ['status']),
      capability('debugging', 'skill', '调试技能'),
      capability('browser-extension', 'extension', '浏览器扩展'),
    ]);

    expect(projected.map((item) => item.id)).toEqual([
      'read',
      'edit',
      'write',
      'bash',
      'input',
      'debugging',
      'browser-extension',
    ]);
    expect(projected.slice(0, 4).map((item) => item.displayName)).toEqual([
      '读取文件',
      '编辑文件',
      '写入文件',
      '运行命令',
    ]);
    expect(projected.find((item) => item.id === 'read')).toMatchObject({
      canonicalId: 'tool:read',
      enabled: true,
      effectiveOperations: [
        'read_range',
        'read',
        'tail',
        'search',
        'list',
        'symbols',
        'grep',
        'find',
        'ls',
      ],
    });
    expect(projected.find((item) => item.id === 'edit')?.effectiveOperations).toEqual([
      'replace',
      'patch',
    ]);
    expect(projected.find((item) => item.id === 'write')?.enabled).toBe(true);
    expect(projected.find((item) => item.id === 'bash')).toMatchObject({
      enabled: true,
      effectiveOperations: ['run', 'stream', 'poll'],
    });
    expect(projected.find((item) => item.id === 'input')).toMatchObject({
      canonicalId: 'tool:input',
      kind: 'tool',
      displayName: '输入法',
    });
    expect(projected.find((item) => item.id === 'debugging')).toMatchObject({
      canonicalId: 'skill:debugging',
      kind: 'skill',
      displayName: '调试技能',
    });
    expect(projected.find((item) => item.id === 'browser-extension')).toMatchObject({
      canonicalId: 'extension:browser-extension',
      kind: 'extension',
      displayName: '浏览器扩展',
    });
  });

  it('normalizes tool preference keys without touching skills or extensions', () => {
    expect(projectPublicToolPreferenceMap({
      'tool:workspace_read': 'disabled',
      'tool:read': 'enabled',
      'tool:workspace_search': 'disabled',
      'tool:workspace_lsp': 'disabled',
      'tool:write_file': 'enabled',
      'tool:workspace_job': 'disabled',
      'skill:debugging': 'disabled',
      'extension:browser': 'enabled',
    })).toEqual({
      'tool:read': 'enabled',
      'tool:write': 'enabled',
      'tool:bash': 'disabled',
      'skill:debugging': 'disabled',
      'extension:browser': 'enabled',
    });
  });

  it('does not treat an unspecified alias state as enabled', () => {
    const unspecified = {
      ...tool('read_file', 'Read file', false, ['read']),
      enabled: undefined,
    };
    const projected = projectPublicToolCatalog([
      tool('workspace_read', '工作区读取', false, ['read_range']),
      unspecified,
    ]);

    expect(projected).toHaveLength(1);
    expect(projected[0]).toMatchObject({ id: 'read', enabled: false });
  });
});

function tool(
  id: string,
  displayName: string,
  enabled: boolean,
  effectiveOperations: string[],
) {
  return {
    id,
    canonicalId: `tool:${id}`,
    kind: 'tool',
    displayName,
    description: `${displayName}说明`,
    enabled,
    effectiveOperations,
  };
}

function capability(
  id: string,
  kind: 'skill' | 'extension',
  displayName: string,
) {
  return {
    id,
    canonicalId: `${kind}:${id}`,
    kind,
    displayName,
    description: `${displayName}说明`,
    enabled: true,
    effectiveOperations: [],
  };
}
