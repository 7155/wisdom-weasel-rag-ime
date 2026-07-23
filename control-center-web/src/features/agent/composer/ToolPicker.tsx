import { Wrench } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
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
    ? '受控工具：加载中'
    : status === 'failed'
      ? '受控工具目录加载失败'
      : `当前权限可用工具：${availableCount} 个`;
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
          <strong>受控工具</strong>
          <small>当前模式可用 {availableCount} / 目录共 {tools.length}</small>
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
                <span><strong>{tool.displayName}</strong><small>{tool.description}</small></span>
                <i data-risk={tool.riskLevel}>
                  {available ? riskLabel(tool.riskLevel) : '当前权限不可用'}
                </i>
              </button>
            );
          })}
        </div>
      </PopoverContent>
    </Popover>
  );
}
