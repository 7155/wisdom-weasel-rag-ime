import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  defaultRoomPermissionPolicy,
  effectiveRoomPermissionPolicy,
  parseRoomPermissionPolicy,
  updateRoomPermissionPolicy,
} from './room-types';
import {
  RoomPermissionPolicyEditor,
  recommendedCreateRole,
  roomExecutionModeLabel,
  roomExecutionModeOptions,
  roomPermissionLayerOptions,
} from './room-presentation';

afterEach(cleanup);

describe('recommendedCreateRole', () => {
  it('keeps every non-facilitator peer available for implementation', () => {
    const selected = [
      'companion-future-v1',
      'companion-present-v1',
      'companion-firstlight-v1',
      'companion-flash-v1',
    ];

    expect(recommendedCreateRole(selected[0], selected, selected[0])).toBe('coordinator');
    expect(selected.slice(1).map((roleId) => recommendedCreateRole(roleId, selected, selected[0])))
      .toEqual(['implementer', 'implementer', 'implementer']);
  });
});

describe('Room permission presentation', () => {
  it('exposes every supported Room permission mode for collaboration Rooms', () => {
    expect(roomExecutionModeOptions('collaboration')).toEqual([
      {
        value: 'read_only',
        label: '只读（沙箱）',
        description: 'macOS 沙箱内可以读取已授权上下文；写入、命令和其他有影响的操作被阻止',
      },
      {
        value: 'per_action',
        label: '全权限',
        description: '整个系统与所有 Tool 可用；有影响的操作逐项请求确认',
      },
      {
        value: 'workspace_managed',
        label: '工作区托管（沙箱）',
        description: 'macOS 沙箱仅开放已批准的工作区范围；范围内自动执行，越界时请求确认',
      },
      {
        value: 'full_trust',
        label: '全自动',
        description: '整个系统与所有 Tool 可用；每个动作自动批准，仍受操作系统边界约束',
      },
    ]);
    expect(roomExecutionModeLabel('per_action', 'collaboration')).toBe('全权限');
  });

  it('keeps roleplay permission labels distinct from collaboration access', () => {
    expect(roomExecutionModeOptions('roleplay').map((option) => option.label))
      .toEqual(['只读（沙箱）', '每次确认']);
    expect(roomExecutionModeLabel('per_action', 'roleplay')).toBe('每次确认');
  });

  it('parses the exact policy contract and resolves both inheritance hops', () => {
    const policy = defaultRoomPermissionPolicy('collaboration');

    expect(policy).toEqual({
      schemaVersion: 'rag-ime.room-permission-policy.v1',
      room: { executionMode: 'full_trust' },
      partner: { executionMode: 'inherit' },
      toolAgent: { executionMode: 'inherit' },
    });
    expect(parseRoomPermissionPolicy(policy, 'collaboration')).toEqual(policy);
    expect(effectiveRoomPermissionPolicy(policy)).toEqual({
      room: 'full_trust',
      partner: 'full_trust',
      toolAgent: 'full_trust',
    });
  });

  it('rejects missing, malformed, elevated-child, and elevated-roleplay policies instead of guessing', () => {
    expect(parseRoomPermissionPolicy(undefined, 'collaboration')).toBeUndefined();
    const valid = defaultRoomPermissionPolicy('collaboration');
    expect(parseRoomPermissionPolicy({ ...valid, unexpected: true }, 'collaboration'))
      .toBeUndefined();
    expect(parseRoomPermissionPolicy({
      ...valid,
      room: { ...valid.room, unexpected: true },
    }, 'collaboration')).toBeUndefined();
    expect(parseRoomPermissionPolicy({
      schemaVersion: 'rag-ime.room-permission-policy.v1',
      room: { executionMode: 'read_only' },
      partner: { executionMode: 'full_trust' },
      toolAgent: { executionMode: 'inherit' },
    }, 'collaboration')).toBeUndefined();
    expect(parseRoomPermissionPolicy({
      schemaVersion: 'rag-ime.room-permission-policy.v1',
      room: { executionMode: 'full_trust' },
      partner: { executionMode: 'inherit' },
      toolAgent: { executionMode: 'inherit' },
    }, 'roleplay')).toBeUndefined();
  });

  it('shows all three layers with configured, effective, scope, Tool, approval, and inheritance facts', () => {
    render(<RoomPermissionPolicyEditor
      onChange={vi.fn()}
      policy={defaultRoomPermissionPolicy('collaboration')}
      roomKind="collaboration"
    />);

    expect(screen.getByLabelText('Room 分层权限')).toBeInTheDocument();
    expect(screen.getByText('Room 边界')).toBeInTheDocument();
    expect(screen.getByText('行星 / Partner')).toBeInTheDocument();
    expect(screen.getByText('卫星 / Tool Agent')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Room 边界配置模式' })).toHaveValue('full_trust');
    expect(screen.getByRole('combobox', { name: '行星 / Partner配置模式' })).toHaveValue('inherit');
    expect(screen.getByRole('combobox', { name: '卫星 / Tool Agent配置模式' })).toHaveValue('inherit');
    expect(screen.getAllByText('配置：继承（Inherit）')).toHaveLength(2);
    expect(screen.getAllByText('生效：全自动')).toHaveLength(3);
    expect(screen.getAllByText('所有当前可用的 Tool 与 Skill')).toHaveLength(3);
    expect(screen.getAllByText(/每个动作自动批准；OS、TCC、Unix 权限/)).toHaveLength(3);
  });

  it('lets a child narrow access and disables every mode above its effective parent', () => {
    const onChange = vi.fn();
    const policy = defaultRoomPermissionPolicy('collaboration');
    render(<RoomPermissionPolicyEditor
      onChange={onChange}
      policy={policy}
      roomKind="collaboration"
    />);

    fireEvent.change(
      screen.getByRole('combobox', { name: '行星 / Partner配置模式' }),
      { target: { value: 'per_action' } },
    );
    const narrowed = updateRoomPermissionPolicy(policy, 'partner', 'per_action');
    expect(onChange).toHaveBeenCalledWith(narrowed);
    expect(effectiveRoomPermissionPolicy(narrowed).partner).toBe('per_action');
    expect(roomPermissionLayerOptions(narrowed, 'toolAgent', 'collaboration')).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ value: 'workspace_managed', disabled: true }),
        expect.objectContaining({ value: 'full_trust', disabled: true }),
      ]),
    );
    expect(updateRoomPermissionPolicy(narrowed, 'toolAgent', 'full_trust').toolAgent.executionMode)
      .toBe('inherit');
  });

  it('renders an explicit migration warning when the server policy is missing', () => {
    render(<RoomPermissionPolicyEditor policy={undefined} roomKind="collaboration" />);

    expect(screen.getByLabelText('Room 分层权限不可用')).toHaveTextContent('分层权限尚不可用');
    expect(screen.getByText(/界面不会猜测或补成全权限/)).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});
