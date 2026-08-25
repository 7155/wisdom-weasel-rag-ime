import {
  Check,
  FolderOpen,
  LockKeyhole,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import * as Checkbox from '@radix-ui/react-checkbox';
import * as RadioGroup from '@radix-ui/react-radio-group';
import { useEffect, useState } from 'react';

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { PermissionMark } from '../marks/ConversationMarks';
import type {
  AgentPermissionSelection,
  SessionSummary,
  ToolManifest,
} from '../types';
import {
  PERMISSION_PRESETS,
  permissionPreset,
} from './permission-policy';
import { toolAvailableForPolicy } from './tool-policy';

export function PermissionPicker({
  session,
  persona,
  tools,
  disabled,
  requestOpen,
  onChange,
  onWorkspaceRootsChange,
}: {
  session?: SessionSummary;
  persona?: AgentPersonaV1;
  tools: ToolManifest[];
  disabled: boolean;
  requestOpen: number;
  onChange: (selection: AgentPermissionSelection) => void;
  onWorkspaceRootsChange: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [dangerousOpen, setDangerousOpen] = useState(false);
  const [dangerousAcknowledged, setDangerousAcknowledged] = useState(false);
  const profile = session?.toolProfileVersion ?? 'control-center-v1';
  const current = permissionPreset(session?.executionMode, profile);
  const sessionMode = session?.mode ?? 'assistant';
  const workspaceRoots = session?.workspaceRoots ?? [];
  // Session ownership and the runtime policy decide whether a user
  // conversation can enter coordinator mode. Persona is optional metadata and
  // must never grant or withhold execution permissions.
  const canCoordinate = Boolean(session && !session.roomParticipant);

  useEffect(() => {
    if (requestOpen > 0 && session && !disabled) setOpen(true);
  }, [disabled, requestOpen, session]);

  useEffect(() => {
    if (!disabled) return;
    setOpen(false);
    setDangerousOpen(false);
  }, [disabled]);

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            aria-label={`对话权限：${current.label}`}
            className="agent-composer__picker"
            data-permission={current.id}
            size="small"
            title={disabled
              ? '请先结束或停止当前任务，再调整运行权限。'
              : `对话权限：${current.label}`}
            variant="quiet"
            disabled={!session || disabled}
            leadingIcon={<PermissionMark mode={current.executionMode} size={16} />}
          >
            <span className="agent-composer__picker-text">{current.label}</span>
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="agent-picker-popover">
          <header>
            <LockKeyhole size={16} />
            <span><strong>对话权限</strong><small>模式、工具范围与审批共同生效</small></span>
          </header>
          <RadioGroup.Root
            className="agent-picker-popover__options"
            aria-label="对话权限模式"
            value={current.id}
            onValueChange={(presetId) => {
              const preset = PERMISSION_PRESETS.find((item) => item.id === presetId);
              if (!preset) return;
              if (preset.id === 'dangerous') {
                setOpen(false);
                setDangerousAcknowledged(false);
                setDangerousOpen(true);
                return;
              }
              const mode = preset.executionMode === 'workspace_managed'
                ? 'coordinator'
                : sessionMode;
              onChange({
                mode,
                toolProfileVersion: preset.toolProfileVersion,
                executionMode: preset.executionMode,
                workspaceScopeConfirmed: preset.executionMode === 'workspace_managed',
              });
              setOpen(false);
            }}
          >
            {PERMISSION_PRESETS.map((preset) => {
              const selected = current.id === preset.id;
              const requiresCoordinator = preset.executionMode === 'workspace_managed'
                || preset.executionMode === 'full_trust';
              const available = !requiresCoordinator || canCoordinate;
              const effectiveMode = requiresCoordinator ? 'coordinator' : sessionMode;
              const toolCount = tools.filter(
                (tool) => toolAvailableForPolicy(
                  tool,
                  effectiveMode,
                  preset.toolProfileVersion,
                ),
              ).length;
              return (
                <RadioGroup.Item
                  className="agent-picker-popover__option"
                  data-danger={preset.id === 'dangerous' || undefined}
                  value={preset.id}
                  key={preset.id}
                  disabled={disabled || !available}
                >
                  <PermissionMark mode={preset.executionMode} size={18} />
                  <span>
                    <strong>{preset.label}</strong>
                    <small>
                      {available
                        ? `${preset.description} · ${toolCount} 个工具`
                        : '当前会话未开放协调权限'}
                    </small>
                  </span>
                  {selected ? <Check size={15} /> : null}
                </RadioGroup.Item>
              );
            })}
          </RadioGroup.Root>
          {canCoordinate ? (
            <section className="agent-picker-popover__workspace" aria-label="授权工作区">
              <FolderOpen size={16} />
              <span>
                <strong>授权工作区</strong>
                <small title={workspaceRoots.join('\n')}>
                  {workspaceRoots.length > 0
                    ? `${workspaceRoots.length} 个目录 · ${workspaceRoots.map(shortPath).join('、')}`
                    : '尚未授权目录，工作区工具无法运行'}
                </small>
              </span>
              <Button
                size="small"
                variant="quiet"
                disabled={disabled}
                onClick={onWorkspaceRootsChange}
              >
                {workspaceRoots.length > 0 ? '更改目录' : '选择目录'}
              </Button>
            </section>
          ) : null}
          {session?.toolAllowlistMode === 'explicit' ? (
            <p className="agent-picker-popover__note">
              当前会话还受 {session.allowedTools?.length ?? 0} 项自定义工具上限约束；选择预设后恢复该预设的完整工具范围。
            </p>
          ) : null}
        </PopoverContent>
      </Popover>
      <Dialog
        open={dangerousOpen}
        onOpenChange={(nextOpen) => {
          setDangerousOpen(nextOpen);
          if (!nextOpen) setDangerousAcknowledged(false);
        }}
      >
        <DialogContent className="agent-dangerous-permission-dialog">
          <DialogHeader>
            <span className="agent-dangerous-permission-dialog__symbol">
              <PermissionMark mode="full_trust" size={22} />
            </span>
            <DialogTitle>启用全自动模式？</DialogTitle>
            <DialogDescription>
              读取等无需审批的操作会直接进行；所有原本需要审批的操作都由独立审批 Agent（Luna Max）自动判定。
            </DialogDescription>
          </DialogHeader>
          <div className="agent-dangerous-permission-dialog__limits">
            <p>
              <ShieldCheck size={16} />
              <span><strong>审批上下文相互隔离</strong> Luna Max 只读取用户请求、当前任务与结构化审批历史，不读取当前 Agent 的输出或推理</span>
            </p>
            <p>
              <ShieldCheck size={16} />
              <span><strong>模型不能扩大权限</strong> 工作区边界、取消栅栏、哈希复验与审计回执始终有效；删库、灾难性破坏和敏感数据外传仍由代码阻止</span>
            </p>
            <p>
              <TriangleAlert size={16} />
              <span><strong>不会再等待你逐项确认</strong> Luna Max 拒绝或不可用时原操作不执行，Agent 会尝试更安全的替代方案</span>
            </p>
          </div>
          <label className="agent-dangerous-permission-dialog__check">
            <Checkbox.Root
              checked={dangerousAcknowledged}
              onCheckedChange={(checked) => setDangerousAcknowledged(checked === true)}
            >
              <Checkbox.Indicator><Check size={14} /></Checkbox.Indicator>
            </Checkbox.Root>
            <span>我确认让此对话全自动执行，并由独立审批 Agent（Luna Max）判定所有待审批操作</span>
          </label>
          <DialogFooter>
            <Button variant="quiet" onClick={() => setDangerousOpen(false)}>
              取消
            </Button>
            <Button
              variant="danger"
              disabled={!dangerousAcknowledged}
              leadingIcon={<TriangleAlert size={15} />}
              onClick={() => {
                onChange({
                  mode: 'coordinator',
                  toolProfileVersion: 'control-center-v1',
                  executionMode: 'full_trust',
                  dangerousModeConfirmed: true,
                });
                setDangerousOpen(false);
              }}
            >
              启用全自动
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function shortPath(path: string): string {
  const parts = path.split('/').filter(Boolean);
  return parts.at(-1) || path;
}
