import {
  Check,
  FolderOpen,
  LockKeyhole,
  Network,
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
import type {
  AgentPermissionSelection,
  SessionSummary,
  ToolManifest,
} from '../types';
import {
  PERMISSION_PRESETS,
  permissionPreset,
  type PermissionPreset,
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
  const canCoordinate = persona?.selectableModes.includes('coordinator') ?? false;

  useEffect(() => {
    if (requestOpen > 0 && session && !disabled) setOpen(true);
  }, [disabled, requestOpen, session]);

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            aria-label={`对话权限：${current.label}`}
            className="agent-composer__picker"
            data-permission={current.id}
            size="small"
            title={`对话权限：${current.label}`}
            variant="quiet"
            disabled={!session || disabled}
            leadingIcon={permissionIcon(current.icon, 15)}
          >
            {current.label}
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
                  disabled={!available}
                >
                  {permissionIcon(preset.icon, 17)}
                  <span>
                    <strong>{preset.label}</strong>
                    <small>
                      {available
                        ? `${preset.description} · ${toolCount} 个工具`
                        : '当前角色未开放协调权限'}
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
                {workspaceRoots.length > 0 ? '更改' : '选择'}
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
              <TriangleAlert size={20} />
            </span>
            <DialogTitle>启用完全信任？</DialogTitle>
            <DialogDescription>
              当前工作区内符合策略的写入与命令会根据结构化预览自动批准；系统级危险动作仍保留人工门禁。
            </DialogDescription>
          </DialogHeader>
          <div className="agent-dangerous-permission-dialog__limits">
            <p>
              <ShieldCheck size={16} />
              <span><strong>仍然保留</strong> 工作区和路径边界、取消栅栏、哈希复验、审计回执与危险动作禁区</span>
            </p>
            <p>
              <TriangleAlert size={16} />
              <span><strong>不再保留</strong> 每次写操作前的人工确认机会</span>
            </p>
          </div>
          <label className="agent-dangerous-permission-dialog__check">
            <Checkbox.Root
              checked={dangerousAcknowledged}
              onCheckedChange={(checked) => setDangerousAcknowledged(checked === true)}
            >
              <Checkbox.Indicator><Check size={14} /></Checkbox.Indicator>
            </Checkbox.Root>
            <span>我确认让此对话自动批准全部受控写操作</span>
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
              启用完全信任
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function permissionIcon(icon: PermissionPreset['icon'], size: number) {
  if (icon === 'network') return <Network size={size} />;
  if (icon === 'lock') return <LockKeyhole size={size} />;
  if (icon === 'danger') return <TriangleAlert size={size} />;
  return <ShieldCheck size={size} />;
}

function shortPath(path: string): string {
  const parts = path.split('/').filter(Boolean);
  return parts.at(-1) || path;
}
