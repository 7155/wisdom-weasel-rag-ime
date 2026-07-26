import { FolderOpen, LoaderCircle, MessageSquare, Plus } from 'lucide-react';
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
  const [picking, setPicking] = useState(false);
  const [creating, setCreating] = useState(false);
  const projectOptions = useMemo(() => uniquePaths(projects), [projects]);

  useEffect(() => {
    if (!open) return;
    const initial = uniquePaths(defaultRoots);
    setTitle('');
    setWorkspaceRoots(initial);
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
          <DialogDescription>可以直接聊，也可以关联工作目录，让伙伴读取项目并使用工作区工具。</DialogDescription>
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
            onValueChange={(value) => setWorkspaceRoots(value === NO_WORKSPACE ? [] : [value])}
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
        <DialogFooter>
          <Button variant="quiet" onClick={() => onOpenChange(false)} disabled={creating || picking}>取消</Button>
          <Button onClick={() => void create()} disabled={creating || picking}>
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
