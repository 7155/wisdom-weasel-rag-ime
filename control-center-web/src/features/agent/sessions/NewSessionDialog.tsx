import { FolderOpen, LoaderCircle, MessageSquare, Plus, ShieldCheck, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import * as RadioGroup from '@radix-ui/react-radio-group';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
} from '@/components/primitives';

export interface NewSessionInput {
  title: string;
  workspaceRoots: string[];
  executionMode: 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';
  toolProfileVersion?: 'control-center-full-access-v1' | 'control-center-auto-approve-v1';
  dangerousModeConfirmed?: boolean;
}

export function NewSessionDialog({
  open,
  projects,
  defaultRoots,
  onOpenChange,
  onPickRoots,
  onCreate,
}: {
  open: boolean;
  projects: string[];
  defaultRoots: string[];
  onOpenChange: (open: boolean) => void;
  onPickRoots: () => Promise<string[] | null>;
  onCreate: (input: NewSessionInput) => Promise<boolean>;
}) {
  const [title, setTitle] = useState('');
  const [workspaceRoots, setWorkspaceRoots] = useState<string[]>([]);
  const [executionMode, setExecutionMode] = useState<NewSessionInput['executionMode']>('per_action');
  const [picking, setPicking] = useState(false);
  const [creating, setCreating] = useState(false);
  const projectOptions = useMemo(() => uniquePaths(projects), [projects]);

  useEffect(() => {
    if (!open) return;
    const initial = uniquePaths(defaultRoots);
    setTitle('');
    setWorkspaceRoots(initial);
    setExecutionMode('per_action');
  }, [defaultRoots, open]);

  async function pickRoots(): Promise<void> {
    if (picking || creating) return;
    setPicking(true);
    try {
      const picked = await onPickRoots();
      if (picked?.length) setWorkspaceRoots(uniquePaths(picked));
    } finally {
      setPicking(false);
    }
  }

  async function create(): Promise<void> {
    if (creating || picking) return;
    setCreating(true);
    try {
      const created = await onCreate({
        title: title.trim() || '新对话',
        workspaceRoots,
        executionMode,
        toolProfileVersion: executionMode === 'full_trust'
          ? 'control-center-auto-approve-v1'
          : 'control-center-full-access-v1',
        ...(executionMode === 'full_trust' ? { dangerousModeConfirmed: true } : {}),
      });
      if (created) onOpenChange(false);
    } finally {
      setCreating(false);
    }
  }

  const primaryRoot = workspaceRoots[0] ?? '';
  return (
    <Dialog open={open} onOpenChange={(next) => !creating && !picking && onOpenChange(next)}>
      <DialogContent className="agent-new-task-dialog">
        <DialogHeader>
          <DialogTitle><Plus size={18} />新建对话</DialogTitle>
          <DialogDescription>创建普通 Pi Session。工作目录与执行权限会在创建前明确显示，能力来自当前 Session 的 Package 快照。</DialogDescription>
        </DialogHeader>
        <Field htmlFor="agent-new-task-title" label="对话名称" description="不填写时会使用“新对话”，之后仍可重命名。">
          <Input
            id="agent-new-task-title"
            value={title}
            maxLength={120}
            placeholder="新对话"
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <section className="agent-new-task-dialog__projects" aria-label="起始项目（可选）">
          <header><strong>起始项目</strong><small>可选，仅用于上下文</small></header>
          <RadioGroup.Root
            aria-label="对话的起始项目"
            value={primaryRoot || NO_WORKSPACE}
            onValueChange={(value) => {
              const roots = value === NO_WORKSPACE ? [] : [value];
              setWorkspaceRoots(roots);
            }}
          >
            <RadioGroup.Item value={NO_WORKSPACE}>
              <MessageSquare size={16} />
              <span><strong>不预选项目</strong><small>仍授予整个系统权限，之后可继续提供项目上下文</small></span>
            </RadioGroup.Item>
            {projectOptions.map((path) => (
              <RadioGroup.Item key={path} value={path} title={path}>
                <FolderOpen size={16} />
                <span><strong>{pathName(path)}</strong><small>{path}</small></span>
              </RadioGroup.Item>
            ))}
          </RadioGroup.Root>
          {primaryRoot && !projectOptions.includes(primaryRoot) ? (
            <div className="agent-new-task-dialog__picked" title={workspaceRoots.join('\n')}>
              <FolderOpen size={16} />
              <span><strong>{pathName(primaryRoot)}</strong><small>{workspaceRoots.join(' · ')}</small></span>
            </div>
          ) : null}
          <Button variant="quiet" leadingIcon={picking ? <LoaderCircle className="ui-spin" size={15} /> : <FolderOpen size={15} />} onClick={() => void pickRoots()} disabled={picking || creating}>
            {primaryRoot ? '换一个项目' : '选择起始项目'}
          </Button>
        </section>
        <section className="agent-new-task-dialog__permissions" aria-label="新对话权限">
          <header><strong>执行权限</strong><small>两种模式都授予整个系统与所有 Tool</small></header>
          <RadioGroup.Root
            aria-label="新对话的执行权限"
            value={executionMode}
            onValueChange={(value) => {
              const nextMode = value as NewSessionInput['executionMode'];
              setExecutionMode(nextMode);
            }}
          >
            <RadioGroup.Item value="per_action">
              <ShieldCheck size={16} />
              <span><strong>全权限</strong><small>整个系统与所有 Tool 可用；有影响的操作逐项请求确认</small></span>
            </RadioGroup.Item>
            <RadioGroup.Item value="full_trust">
              <TriangleAlert size={16} />
              <span><strong>全自动</strong><small>整个系统与所有 Tool 可用；每个动作自动批准，仍受操作系统边界约束</small></span>
            </RadioGroup.Item>
          </RadioGroup.Root>
        </section>
        <DialogFooter>
          <Button variant="quiet" onClick={() => onOpenChange(false)} disabled={creating || picking}>取消</Button>
          <Button onClick={() => void create()} disabled={creating || picking}>
            {creating ? <><LoaderCircle className="ui-spin" size={15} />正在创建</> : executionMode === 'full_trust' ? '启用全自动并开始' : '开始对话'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const NO_WORKSPACE = '__no_workspace__';

function uniquePaths(values: string[]): string[] {
  return values.map((value) => value.trim()).filter((value, index, all) => (
    value.startsWith('/') && all.indexOf(value) === index
  )).slice(0, 4);
}

function pathName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}
