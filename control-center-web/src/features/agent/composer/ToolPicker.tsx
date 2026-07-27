import { Wrench } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import { publicToolName } from '../tool-presentation';
import type { SessionSummary, ToolManifest } from '../types';
import { riskLabel, toolAvailableForCurrentSession } from './tool-policy';

export function ToolPicker({
  tools,
  status,
  session,
  disabled,
  requestOpen,
  onSelect,
}: {
  tools: ToolManifest[];
  status: 'loading' | 'ready' | 'failed';
  session?: SessionSummary;
  disabled: boolean;
  requestOpen: number;
  onSelect: (tool: ToolManifest) => void;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (requestOpen > 0 && status === 'ready' && !disabled) setOpen(true);
  }, [disabled, requestOpen, status]);

  const availableCount = tools.filter(
    (tool) => toolAvailableForCurrentSession(tool, session),
  ).length;
  const label = status === 'loading'
    ? '工具列表正在读取'
    : status === 'failed'
      ? '工具列表暂不可用'
      : `这段对话可用工具：${availableCount} 个`;
  const text = status === 'loading'
    ? '工具 · 加载中'
    : status === 'failed'
      ? '工具 · 未加载'
      : `工具 · ${availableCount}`;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          aria-label={label}
          className="agent-composer__picker"
          data-status={status}
          size="small"
          title={label}
          variant="quiet"
          disabled={status !== 'ready' || !tools.length || disabled}
          leadingIcon={<Wrench size={15} />}
        >
          {text}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-tool-picker">
        <header>
          <strong>可用工具</strong>
          <small>这段对话可用 {availableCount} 个，共发现 {tools.length} 个</small>
        </header>
        <div>
          {tools.map((tool) => {
            const available = toolAvailableForCurrentSession(tool, session);
            return (
              <button
                type="button"
                key={tool.id}
                disabled={!available}
                onClick={() => onSelect(tool)}
              >
                <span><strong>{publicToolName(tool.id, tool.displayName)}</strong><small>{publicToolDescription(tool)}</small></span>
                <i data-risk={tool.riskLevel}>
                  {available ? riskLabel(tool.riskLevel) : '当前对话不可用'}
                </i>
              </button>
            );
          })}
        </div>
        <p className="agent-picker-popover__note">
          标签说明操作会带来的影响；是否需要确认，由当前对话权限决定。
        </p>
      </PopoverContent>
    </Popover>
  );
}

function publicToolDescription(tool: ToolManifest): string {
  return ({
    ime_overview: '查看伙伴、模型、记忆、输入和近期活动',
    ime_voice: '查看语音输入状态，并按当前权限切换已配置的转写引擎',
    ime_memory: '查找过去的输入、偏好、决定和有来源的长期记忆；变更会先进入审阅',
    agent_role_book: '查看伙伴形成的工作习惯和边界；新的成长内容会先成为待确认草案',
    ime_browser: '查看已连接的浏览器页面，并按当前权限执行可追踪操作',
    ime_runtime: '检查后台服务、连接和运行状态',
    ime_configuration: '查看设置和变更记录',
    ime_agents: '邀请其他伙伴协作，并查看交接与交付',
  } as Record<string, string>)[tool.id] ?? tool.description;
}
