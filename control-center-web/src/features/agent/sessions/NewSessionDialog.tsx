import { Check, Eye, FolderOpen, LoaderCircle, MessageSquare, Plus, ShieldCheck, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import * as Checkbox from '@radix-ui/react-checkbox';
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
  const [dangerousModeConfirmed, setDangerousModeConfirmed] = useState(false);
  const [picking, setPicking] = useState(false);
  const [creating, setCreating] = useState(false);
  const projectOptions = useMemo(() => uniquePaths(projects), [projects]);

  useEffect(() => {
    if (!open) return;
    const initial = uniquePaths(defaultRoots);
    setTitle('');
    setWorkspaceRoots(initial);
    setExecutionMode('per_action');
    setDangerousModeConfirmed(false);
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
        ...(executionMode === 'full_trust' ? { dangerousModeConfirmed } : {}),
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
        <section className="agent-new-task-dialog__projects" aria-label="关联工作目录">
          <header><strong>关联工作目录</strong><small>可选</small></header>
          <RadioGroup.Root
            aria-label="对话的工作目录"
            value={primaryRoot || NO_WORKSPACE}
            onValueChange={(value) => {
              const roots = value === NO_WORKSPACE ? [] : [value];
              setWorkspaceRoots(roots);
              if (!roots.length && (executionMode === 'workspace_managed' || executionMode === 'full_trust')) {
                setExecutionMode('per_action');
                setDangerousModeConfirmed(false);
              }
            }}
          >
            <RadioGroup.Item value={NO_WORKSPACE}>
              <MessageSquare size={16} />
              <span><strong>直接聊天</strong><small>不读取项目；之后需要时仍可关联目录</small></span>
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
            {primaryRoot ? '换一个目录' : '选择工作目录'}
          </Button>
        </section>
        <section className="agent-new-task-dialog__permissions" aria-label="新对话权限">
          <header><strong>执行权限</strong><small>全自动需要工作目录与明确确认</small></header>
          <RadioGroup.Root
            aria-label="新对话的执行权限"
            value={executionMode}
            onValueChange={(value) => {
              setExecutionMode(value as NewSessionInput['executionMode']);
              setDangerousModeConfirmed(false);
            }}
          >
            <RadioGroup.Item value="per_action">
              <ShieldCheck size={16} />
              <span><strong>逐项确认</strong><small>读取可直接进行；写入与命令按风险请求确认</small></span>
            </RadioGroup.Item>
            <RadioGroup.Item value="read_only">
              <Eye size={16} />
              <span><strong>只读</strong><small>适合检查、理解和规划，不允许修改工作区</small></span>
            </RadioGroup.Item>
            <RadioGroup.Item value="workspace_managed" disabled={!primaryRoot}>
              <FolderOpen size={16} />
              <span><strong>工作区托管</strong><small>{primaryRoot ? '仅在上方明确选择的目录内工作' : '先选择工作目录后可用'}</small></span>
            </RadioGroup.Item>
            <RadioGroup.Item value="full_trust" disabled={!primaryRoot}>
              <TriangleAlert size={16} />
              <span><strong>全自动</strong><small>{primaryRoot ? '由独立审批 Agent 自动判定待审批操作' : '先选择工作目录后可用'}</small></span>
            </RadioGroup.Item>
          </RadioGroup.Root>
          {executionMode === 'full_trust' ? (
            <label className="agent-dangerous-permission-dialog__check">
              <Checkbox.Root
                checked={dangerousModeConfirmed}
                onCheckedChange={(checked) => setDangerousModeConfirmed(checked === true)}
              >
                <Checkbox.Indicator><Check size={14} /></Checkbox.Indicator>
              </Checkbox.Root>
              <span>我确认让此对话全自动执行，并由独立审批 Agent 判定待审批操作</span>
            </label>
          ) : null}
        </section>
        <DialogFooter>
          <Button variant="quiet" onClick={() => onOpenChange(false)} disabled={creating || picking}>取消</Button>
          <Button onClick={() => void create()} disabled={creating || picking || (executionMode === 'full_trust' && !dangerousModeConfirmed)}>
            {creating ? <><LoaderCircle className="ui-spin" size={15} />正在创建</> : '开始对话'}
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
