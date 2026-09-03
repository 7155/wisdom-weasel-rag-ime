import {
  BriefcaseBusiness,
  CircleAlert,
  MessagesSquare,
  ShieldCheck,
  Sparkles,
  UsersRound,
  Wrench,
} from 'lucide-react';
import { Select } from '@/components/primitives';
import { roomCollaborationRoleLabel } from './room-copy';
import { roomParticipantPlanetName } from './room-participant-identity';
import {
  effectiveRoomPermissionPolicy,
  roomPermissionModeFitsParent,
  updateRoomPermissionPolicy,
  type RoomCollaborationRole,
  type RoomExecutionMode,
  type RoomKind,
  type RoomPermissionChildExecutionMode,
  type RoomPermissionLayer,
  type RoomPermissionPolicy,
  type RoomSummary,
  type RoomWorkState,
} from './room-types';

export function pathName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}

export function roomPathName(room: RoomSummary): string {
  return room.workspaceRoots?.[0] ? pathName(room.workspaceRoots[0]) : '未选择工作目录';
}

export function roomExecutionModeOptions(roomKind: RoomKind): Array<{
  value: RoomExecutionMode;
  label: string;
  description: string;
}> {
  if (roomKind === 'roleplay') {
    return [
      { value: 'read_only', label: '只读', description: '可以查看文件；写入和命令都不执行' },
      { value: 'per_action', label: '每次确认', description: '沿用角色 Session 边界；有影响的操作逐项确认' },
    ];
  }
  return [
    {
      value: 'read_only',
      label: '只读',
      description: '可以读取已授权上下文；写入、命令和其他有影响的操作被阻止',
    },
    {
      value: 'per_action',
      label: '全权限',
      description: '整个系统与所有 Tool 可用；有影响的操作逐项请求确认',
    },
    {
      value: 'workspace_managed',
      label: '工作区托管',
      description: '仅已批准的工作区范围；范围内自动执行，越界时请求确认',
    },
    {
      value: 'full_trust',
      label: '全自动',
      description: '整个系统与所有 Tool 可用；每个动作自动批准，仍受操作系统边界约束',
    },
  ];
}

export function roomWorkspaceViewOptions(roomKind: RoomKind | undefined) {
  if (roomKind === 'roleplay') {
    return [
      { value: 'posts' as const, label: '对话' },
      { value: 'sessions' as const, label: '伙伴' },
    ];
  }
  return [
    { value: 'posts' as const, label: '对话' },
    { value: 'execution' as const, label: '任务' },
    { value: 'sessions' as const, label: '伙伴' },
  ];
}

export function roomExecutionModeLabel(
  value: RoomExecutionMode | undefined,
  roomKind: RoomKind | undefined = 'collaboration',
): string {
  if ((value ?? 'per_action') === 'per_action') {
    return roomKind === 'roleplay' ? '每次确认' : '全权限';
  }
  return {
    per_action: '全权限',
    read_only: '只读',
    workspace_managed: '工作区托管',
    full_trust: '全自动',
  }[value ?? 'full_trust'];
}

const ROOM_PERMISSION_LAYERS: readonly RoomPermissionLayer[] = [
  'room',
  'partner',
  'toolAgent',
];

const ROOM_PERMISSION_CHILD_MODES: readonly RoomExecutionMode[] = [
  'read_only',
  'per_action',
  'workspace_managed',
  'full_trust',
];

export interface RoomPermissionLayerPresentation {
  configuredLabel: string;
  effectiveLabel: string;
  inheritanceLabel: string;
  workspaceScope: string;
  toolScope: string;
  approvalBehavior: string;
}

export function roomPermissionLayerLabel(layer: RoomPermissionLayer): string {
  return {
    room: 'Room 边界',
    partner: '行星 / Partner',
    toolAgent: '卫星 / Tool Agent',
  }[layer];
}

export function roomPermissionConfiguredModeLabel(
  value: RoomPermissionChildExecutionMode,
  roomKind: RoomKind = 'collaboration',
): string {
  return value === 'inherit'
    ? '继承（Inherit）'
    : roomExecutionModeLabel(value, roomKind);
}

export function roomPermissionLayerOptions(
  policy: RoomPermissionPolicy,
  layer: RoomPermissionLayer,
  roomKind: RoomKind,
): Array<{
  value: RoomPermissionChildExecutionMode;
  label: string;
  disabled?: boolean;
}> {
  if (layer === 'room') {
    const current = policy.room.executionMode;
    const ordinary = roomExecutionModeOptions(roomKind);
    return ordinary.some((option) => option.value === current)
      ? ordinary
      : [
          {
            value: current,
            label: `${roomExecutionModeLabel(current, roomKind)}（旧配置）`,
            disabled: true,
          },
          ...ordinary,
        ];
  }
  const effective = effectiveRoomPermissionPolicy(policy);
  const parentMode = layer === 'partner' ? effective.room : effective.partner;
  return [
    { value: 'inherit', label: '继承（Inherit）' },
    ...ROOM_PERMISSION_CHILD_MODES.map((value) => ({
      value,
      label: roomExecutionModeLabel(value, roomKind),
      disabled: !roomPermissionModeFitsParent(value, parentMode),
    })),
  ];
}

export function roomPermissionLayerPresentation(
  policy: RoomPermissionPolicy,
  layer: RoomPermissionLayer,
  roomKind: RoomKind,
): RoomPermissionLayerPresentation {
  const effective = effectiveRoomPermissionPolicy(policy);
  const configuredMode = layer === 'room'
    ? policy.room.executionMode
    : policy[layer].executionMode;
  const effectiveMode = effective[layer];
  const modeDetails = roomPermissionModeDetails(effectiveMode, roomKind);
  const inheritanceLabel = configuredMode !== 'inherit'
    ? '未继承，直接配置'
    : layer === 'partner'
      ? '继承 Room 边界'
      : policy.partner.executionMode === 'inherit'
        ? '继承 行星 / Partner（其继承 Room 边界）'
        : '继承 行星 / Partner';
  return {
    configuredLabel: roomPermissionConfiguredModeLabel(configuredMode, roomKind),
    effectiveLabel: roomExecutionModeLabel(effectiveMode, roomKind),
    inheritanceLabel,
    ...modeDetails,
  };
}

export function RoomPermissionPolicyEditor({
  policy,
  roomKind,
  onChange,
  compact = false,
  menuSelect = false,
}: {
  policy?: RoomPermissionPolicy;
  roomKind: RoomKind;
  onChange?: (policy: RoomPermissionPolicy) => void;
  compact?: boolean;
  menuSelect?: boolean;
}) {
  if (!policy) {
    return <section
      aria-label="Room 分层权限不可用"
      className="room-permission-policy__unavailable"
      role="status"
    >
      <CircleAlert aria-hidden="true" size={18} />
      <span>
        <strong>分层权限尚不可用</strong>
        <small>
          这个旧 Room 没有返回可验证的 Room 边界、行星 / Partner 与卫星 / Tool Agent
          策略。界面不会猜测或补成全权限；迁移后再在这里调整。
        </small>
      </span>
    </section>;
  }
  return <section
    aria-label="Room 分层权限"
    className="room-permission-policy"
    data-compact={compact || undefined}
  >
    <p className="room-permission-policy__intro">
      权限从 Room 向下传递；行星与卫星可以继承或收窄，不能超过上一层。
    </p>
    <div className="room-permission-policy__layers">
      {ROOM_PERMISSION_LAYERS.map((layer) => {
        const configuredMode = layer === 'room'
          ? policy.room.executionMode
          : policy[layer].executionMode;
        const presentation = roomPermissionLayerPresentation(policy, layer, roomKind);
        const options = roomPermissionLayerOptions(policy, layer, roomKind);
        const LayerIcon = layer === 'room'
          ? ShieldCheck
          : layer === 'partner'
            ? UsersRound
            : Wrench;
        return <article className="room-permission-layer" data-layer={layer} key={layer}>
          <div className="room-permission-layer__identity">
            <span className="room-permission-layer__mark"><LayerIcon aria-hidden="true" size={16} /></span>
            <span>
              <strong>{roomPermissionLayerLabel(layer)}</strong>
              <small>{presentation.inheritanceLabel}</small>
            </span>
            {onChange ? <div className="room-permission-layer__control">
              <span>配置模式</span>
              {menuSelect ? <Select<RoomPermissionChildExecutionMode>
                aria-label={`${roomPermissionLayerLabel(layer)}配置模式`}
                className="room-permission-layer__select"
                onValueChange={(value) => onChange(updateRoomPermissionPolicy(
                  policy,
                  layer,
                  value,
                ))}
                options={options}
                value={configuredMode}
              /> : <select
                aria-label={`${roomPermissionLayerLabel(layer)}配置模式`}
                onChange={(event) => onChange(updateRoomPermissionPolicy(
                  policy,
                  layer,
                  event.target.value as RoomPermissionChildExecutionMode,
                ))}
                value={configuredMode}
              >
                {options.map((option) => <option
                  disabled={option.disabled}
                  key={option.value}
                  value={option.value}
                >{option.label}</option>)}
              </select>}
            </div> : null}
            <p className="room-permission-layer__modes">
              <span>配置：{presentation.configuredLabel}</span>
              <span>生效：{presentation.effectiveLabel}</span>
            </p>
          </div>
          <dl className="room-permission-layer__facts">
            <div><dt>工作区范围</dt><dd>{presentation.workspaceScope}</dd></div>
            <div><dt>Tool 范围</dt><dd>{presentation.toolScope}</dd></div>
            <div><dt>审批方式</dt><dd>{presentation.approvalBehavior}</dd></div>
          </dl>
        </article>;
      })}
    </div>
  </section>;
}

function roomPermissionModeDetails(
  mode: RoomExecutionMode,
  roomKind: RoomKind,
): Pick<
  RoomPermissionLayerPresentation,
  'workspaceScope' | 'toolScope' | 'approvalBehavior'
> {
  if (mode === 'read_only') {
    return {
      workspaceScope: '可读取授权上下文，不允许写入',
      toolScope: '仅当前可用的读取与核对能力',
      approvalBehavior: '写入、命令和其他有影响的操作被阻止',
    };
  }
  if (roomKind === 'roleplay' && mode === 'per_action') {
    return {
      workspaceScope: '沿用角色 Session 的既有边界，不提升到整个系统',
      toolScope: '仅当前角色 Session 已有的可用能力',
      approvalBehavior: '有影响的操作逐项请求确认',
    };
  }
  if (mode === 'per_action') {
    return {
      workspaceScope: '整个系统（/）；所选项目只提供上下文',
      toolScope: '所有当前可用的 Tool 与 Skill',
      approvalBehavior: '有影响的操作逐项请求确认',
    };
  }
  if (mode === 'workspace_managed') {
    return {
      workspaceScope: '仅已批准的工作区范围',
      toolScope: '该范围内适用且已启用的 Tool 与 Skill',
      approvalBehavior: '范围内自动执行，越界时请求确认',
    };
  }
  return {
    workspaceScope: '整个系统（/）；所选项目只提供上下文',
    toolScope: '所有当前可用的 Tool 与 Skill',
    approvalBehavior: '每个动作自动批准；OS、TCC、Unix 权限与 Tool 可用性仍是硬边界',
  };
}

export function recommendedCreateRole(
  roleId: string,
  _selectedRoleIds: string[],
  coordinatorRoleId: string,
): RoomCollaborationRole {
  if (roleId === coordinatorRoleId) return 'coordinator';
  return 'implementer';
}

export function roomCreateParticipantLabel(
  roomKind: RoomKind,
  selected: boolean,
  roleId: string,
  selectedRoleIds: string[],
  coordinatorRoleId: string,
): string {
  if (!selected) return '可邀请';
  if (roomKind === 'roleplay') return '一起聊天';
  return roomCollaborationRoleLabel(
    recommendedCreateRole(roleId, selectedRoleIds, coordinatorRoleId),
  );
}

export function participantName(room: RoomSummary, participantId: string): string {
  const participant = room.participants.find((item) => item.id === participantId);
  return participant ? roomParticipantPlanetName(participant) : '待接收';
}

export function roomWorkStateLabel(state: RoomWorkState): string {
  return {
    queued: '待接收',
    active: '执行中',
    review: '等待汇合',
    blocked: '已阻塞',
    done: '已完成',
    failed: '未完成',
    cancelled: '已取消',
  }[state];
}

export function roomAvatarOptions(): { value: string; label: string }[] {
  return [
    { value: 'briefcase', label: '任务' },
    { value: 'members', label: '伙伴' },
    { value: 'sparkles', label: '灵感' },
    { value: 'messages', label: '对话' },
  ];
}

export function roomCollaborationRoleOptions(
  currentRole?: RoomCollaborationRole,
): { value: RoomCollaborationRole; label: string; disabled?: boolean }[] {
  const options: { value: RoomCollaborationRole; label: string; disabled?: boolean }[] = [
    { value: 'coordinator', label: roomCollaborationRoleLabel('coordinator') },
    { value: 'implementer', label: roomCollaborationRoleLabel('implementer') },
    { value: 'researcher', label: roomCollaborationRoleLabel('researcher') },
    { value: 'reviewer', label: roomCollaborationRoleLabel('reviewer') },
  ];
  if (currentRole === 'specialist') {
    options.push({
      value: 'specialist',
      label: roomCollaborationRoleLabel('specialist'),
      disabled: true,
    });
  }
  return options;
}

export function roomAvatarIcon(room: RoomSummary) {
  if (room.avatar === 'sparkles' || room.roomKind === 'roleplay') return <Sparkles size={16} />;
  if (room.avatar === 'briefcase') return <BriefcaseBusiness size={16} />;
  if (room.avatar === 'messages') return <MessagesSquare size={16} />;
  return <UsersRound size={16} />;
}
