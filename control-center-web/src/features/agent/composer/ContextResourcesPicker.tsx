import { BookOpenText } from 'lucide-react';
import * as Switch from '@radix-ui/react-switch';

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import type { SessionSummary } from '../types';

export function ContextResourcesPicker({
  session,
  disabled,
  onProjectContextChange,
  onPiSkillsChange,
  onCodexSkillsChange,
}: {
  session?: SessionSummary;
  disabled: boolean;
  onProjectContextChange: (enabled: boolean) => void;
  onPiSkillsChange: (enabled: boolean) => void;
  onCodexSkillsChange: (enabled: boolean) => void;
}) {
  const projectContextEnabled = session?.projectContextEnabled === true;
  const piSkillsEnabled = session?.piSkillsEnabled === true;
  const codexSkillsEnabled = session?.codexSkillsEnabled === true;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          aria-label={`项目指令：${projectContextEnabled ? '已加载' : '未加载'}`}
          className="agent-composer__picker agent-composer__project-context"
          data-enabled={projectContextEnabled || piSkillsEnabled || codexSkillsEnabled || undefined}
          size="small"
          title="项目指令与 Skill 来源"
          variant="quiet"
          disabled={!session || disabled}
          leadingIcon={<BookOpenText size={15} />}
        >
          项目指令
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-picker-popover agent-project-context-picker">
        <header>
          <BookOpenText size={16} />
          <span><strong>上下文资源</strong><small>当前对话的项目指令与 Skill 来源</small></span>
        </header>
        <label className="agent-project-context-picker__toggle">
          <span>
            <strong>加载 AGENTS.md / CLAUDE.md</strong>
            <small>从全局目录和当前工作区祖先目录按 Pi 原生顺序读取</small>
          </span>
          <Switch.Root
            aria-label="加载 AGENTS.md / CLAUDE.md"
            checked={projectContextEnabled}
            disabled={disabled}
            onCheckedChange={onProjectContextChange}
          >
            <Switch.Thumb />
          </Switch.Root>
        </label>
        <label className="agent-project-context-picker__toggle">
          <span>
            <strong>加载 Pi Skills</strong>
            <small>读取 Pi 用户 Skill 目录；输入法自己的 Skills 不受此开关影响</small>
          </span>
          <Switch.Root
            aria-label="加载 Pi Skills"
            checked={piSkillsEnabled}
            disabled={disabled}
            onCheckedChange={onPiSkillsChange}
          >
            <Switch.Thumb />
          </Switch.Root>
        </label>
        <label className="agent-project-context-picker__toggle">
          <span>
            <strong>加载 Codex Skills</strong>
            <small>读取 Codex 与通用 Agents Skill 目录；默认关闭</small>
          </span>
          <Switch.Root
            aria-label="加载 Codex Skills"
            checked={codexSkillsEnabled}
            disabled={disabled}
            onCheckedChange={onCodexSkillsChange}
          >
            <Switch.Thumb />
          </Switch.Root>
        </label>
        <p className="agent-picker-popover__note">
          切换后会重建 Pi Runtime；历史消息不变，下一轮使用新的上下文资源设置。
        </p>
      </PopoverContent>
    </Popover>
  );
}
