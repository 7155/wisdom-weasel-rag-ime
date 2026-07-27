import { Bell, Inbox, MoreHorizontal, Plus } from 'lucide-react';
import { useState } from 'react';
import { Button } from './Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from './Dialog';
import { EmptyState } from './EmptyState';
import { Field, Input } from './Field';
import { IconButton } from './IconButton';
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from './Menu';
import { Popover, PopoverContent, PopoverTrigger } from './Popover';
import { SegmentedControl } from './SegmentedControl';
import { Skeleton } from './Skeleton';
import { Switch } from './Switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './Tabs';
import { Tooltip } from './Tooltip';
import { useToast } from './Toast';

export function PrimitivesShowcase() {
  const [density, setDensity] = useState<'compact' | 'comfortable'>('compact');
  const [enabled, setEnabled] = useState(true);
  const pushToast = useToast();

  return (
    <main className="ui-showcase" aria-label="Design system preview">
      <header className="ui-showcase__header">
        <div>
          <p className="ui-showcase__eyebrow">PERSONAL AGENT WORKBENCH</p>
          <h1>界面原语</h1>
        </div>
        <SegmentedControl
          aria-label="界面密度"
          items={[
            { value: 'compact', label: '紧凑' },
            { value: 'comfortable', label: '舒展' },
          ]}
          onValueChange={setDensity}
          value={density}
        />
      </header>

      <section className="ui-showcase__section" aria-labelledby="showcase-actions">
        <h2 id="showcase-actions">Actions</h2>
        <div className="ui-showcase__row">
          <Button leadingIcon={<Plus size={16} />} variant="primary">新建任务</Button>
          <Button>运行检查</Button>
          <Button variant="quiet">取消</Button>
          <Button variant="danger">停止运行</Button>
          <Tooltip content="打开通知">
            <IconButton icon={<Bell size={17} />} label="通知" />
          </Tooltip>
          <Menu>
            <MenuTrigger asChild>
              <IconButton icon={<MoreHorizontal size={17} />} label="更多操作" />
            </MenuTrigger>
            <MenuContent align="end">
              <MenuItem>重新连接</MenuItem>
              <MenuItem>复制诊断摘要</MenuItem>
              <MenuSeparator />
              <MenuItem>打开诊断</MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </section>

      <section className="ui-showcase__section" aria-labelledby="showcase-inputs">
        <h2 id="showcase-inputs">Inputs</h2>
        <div className="ui-showcase__grid">
          <Field description="仅保存到本机配置。" htmlFor="showcase-profile" label="Profile">
            <Input defaultValue="workbench" id="showcase-profile" />
          </Field>
          <Switch
            checked={enabled}
            description="暂停时不会影响基础 Rime 候选。"
            label="启用辅助候选"
            onCheckedChange={setEnabled}
          />
        </div>
      </section>

      <section className="ui-showcase__section" aria-labelledby="showcase-overlays">
        <h2 id="showcase-overlays">Overlays & feedback</h2>
        <div className="ui-showcase__row">
          <Popover>
            <PopoverTrigger asChild><Button>连接详情</Button></PopoverTrigger>
            <PopoverContent align="start">Sidecar 8766 · Mock transport</PopoverContent>
          </Popover>
          <Dialog>
            <DialogTrigger asChild><Button>打开确认框</Button></DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>应用设置变更</DialogTitle>
                <DialogDescription>变更会先生成预览，并在确认后写入配置。</DialogDescription>
              </DialogHeader>
              <DialogFooter><Button variant="primary">继续</Button></DialogFooter>
            </DialogContent>
          </Dialog>
          <Button onClick={() => pushToast({ title: '设置已保存', description: '本机配置已更新。', tone: 'success' })}>
            显示通知
          </Button>
        </div>
      </section>

      <section className="ui-showcase__section" aria-labelledby="showcase-states">
        <h2 id="showcase-states">States</h2>
        <Tabs defaultValue="loading">
          <TabsList><TabsTrigger value="loading">加载</TabsTrigger><TabsTrigger value="empty">空态</TabsTrigger></TabsList>
          <TabsContent value="loading"><Skeleton style={{ width: '68%', height: 14 }} /></TabsContent>
          <TabsContent value="empty"><EmptyState description="调整筛选条件后重试。" icon={Inbox} title="没有匹配记录" /></TabsContent>
        </Tabs>
      </section>
    </main>
  );
}
