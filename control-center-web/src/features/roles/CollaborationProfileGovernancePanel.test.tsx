import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { CollaborationProfileGovernancePanel } from './CollaborationProfileGovernancePanel';
import { collaborationProfileFixtures } from './agent-definition-fixtures';

describe('CollaborationProfileGovernancePanel', () => {
  afterEach(cleanup);

  it('shows inspect diff and compile receipt without exposing an activation command', () => {
    render(<CollaborationProfileGovernancePanel projection={collaborationProfileFixtures[0]!.governance} />);

    expect(screen.getByRole('region', { name: '角色书持久化检查' })).toHaveTextContent('profile-compile:fixture');
    expect(screen.getByRole('list', { name: '角色书安全流水线' })).toHaveTextContent('检查校验编译试运行暂存原子启用');
    expect(screen.getByRole('region', { name: '角色书能力差异' })).toHaveTextContent('收窄delegation');
    expect(screen.queryByRole('button', { name: /启用|激活|回滚|撤销/ })).not.toBeInTheDocument();
  });
});
