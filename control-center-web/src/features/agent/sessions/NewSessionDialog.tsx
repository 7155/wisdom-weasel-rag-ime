import { FolderOpen, LoaderCircle, Plus } from 'lucide-react';
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
    setWorkspaceRoots(initial.length ? initial : projectOptions.slice(0, 1));
  }, [defaultRoots, open, projectOptions]);

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
    if (!workspaceRoots.length || creating || picking) return;
    setCreating(true);
    try {
      const created = await onCreate({
        title: title.trim() || '新任务',
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
          <DialogTitle><Plus size={18} />新建任务</DialogTitle>
          <DialogDescription>先指定项目路径。任务、工具权限和后续分支都归入这个项目。</DialogDescription>
        </DialogHeader>
        <Field htmlFor="agent-new-task-title" label="任务名称" description="可以稍后在对话中重命名。">
          <Input
            id="agent-new-task-title"
            value={title}
            maxLength={120}
            placeholder="新任务"
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <section className="agent-new-task-dialog__projects" aria-label="项目路径">
          <header><strong>项目路径</strong><small>必选</small></header>
          {projectOptions.length ? (
            <RadioGroup.Root
              aria-label="最近项目"
              value={primaryRoot}
              onValueChange={(value) => setWorkspaceRoots([value])}
            >
              {projectOptions.map((path) => (
                <RadioGroup.Item key={path} value={path} title={path}>
                  <FolderOpen size={16} />
                  <span><strong>{pathName(path)}</strong><small>{path}</small></span>
                </RadioGroup.Item>
              ))}
            </RadioGroup.Root>
          ) : null}
          {primaryRoot && !projectOptions.includes(primaryRoot) ? (
            <div className="agent-new-task-dialog__picked" title={workspaceRoots.join('\n')}>
              <FolderOpen size={16} />
              <span><strong>{pathName(primaryRoot)}</strong><small>{workspaceRoots.join(' · ')}</small></span>
            </div>
          ) : null}
          <Button variant="quiet" leadingIcon={picking ? <LoaderCircle className="ui-spin" size={15} /> : <FolderOpen size={15} />} onClick={() => void pickRoots()} disabled={picking || creating}>
            {primaryRoot ? '选择其他目录' : '选择项目目录'}
          </Button>
        </section>
        <DialogFooter>
          <Button variant="quiet" onClick={() => onOpenChange(false)} disabled={creating || picking}>取消</Button>
          <Button onClick={() => void create()} disabled={!workspaceRoots.length || creating || picking}>
            {creating ? <><LoaderCircle className="ui-spin" size={15} />正在创建</> : '创建任务'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function uniquePaths(values: string[]): string[] {
  return values.map((value) => value.trim()).filter((value, index, all) => (
    value.startsWith('/') && all.indexOf(value) === index
  )).slice(0, 4);
}

function pathName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) ?? path;
}
