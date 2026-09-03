import { describe, expect, it } from 'vitest';
import { publicToolName, toolIntentPrompt } from './tool-presentation';

describe('tool presentation', () => {
  it('keeps stable runtime ids behind human-facing names', () => {
    expect(publicToolName('overview', '控制中心概览')).toBe('当前状态');
    expect(publicToolName('workspace_shell', '受控命令')).toBe('运行项目命令');
    expect(publicToolName('workspace_lsp', 'Workspace LSP')).toBe('代码智能');
    expect(publicToolName('custom_tool', '自定义检查')).toBe('自定义检查');
    expect(publicToolName('custom_tool', 'schema /api/private')).toBe('工具操作');
  });

  it('turns a picker choice into a natural task instead of a tool command', () => {
    expect(toolIntentPrompt('overview', '控制中心概览')).toBe('帮我看看当前状态');
    expect(toolIntentPrompt('workspace_read', '工作区读取')).toBe('帮我读取这个项目文件');
    expect(toolIntentPrompt('custom_tool', '自定义检查')).toBe('帮我用自定义检查处理');
  });

  it('uses explicit business labels for EnterpriseOps evaluation tools', () => {
    expect(publicToolName('find_user')).toBe('查找用户');
    expect(publicToolName('update_entitlement')).toBe('更新服务权益');
    expect(publicToolName('link_new_case_sla')).toBe('关联工单 SLA');
  });
});
