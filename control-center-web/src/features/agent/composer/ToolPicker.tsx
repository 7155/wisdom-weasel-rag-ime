import { Wrench, X } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
} from '@/components/primitives';
import {
  capabilityPreferenceOptions,
  type CapabilityCatalog,
  type CapabilityPreference,
} from '@/features/plugins/capability-policy';
import type { SessionSummary, ToolManifest } from '../types';
import { riskLabel, toolAvailableForCurrentSession } from './tool-policy';

export function ToolPicker({
  adjustmentDisabled,
  capabilityCatalog,
  capabilityPolicyPending,
  tools,
  status,
  session,
  disabled,
  requestOpen,
  onCapabilityPreferenceChange,
  onSelect,
}: {
  adjustmentDisabled: boolean;
  capabilityCatalog?: CapabilityCatalog;
  capabilityPolicyPending: boolean;
  tools: ToolManifest[];
  status: 'loading' | 'ready' | 'failed';
  session?: SessionSummary;
  disabled: boolean;
  requestOpen: number;
  onCapabilityPreferenceChange: (canonicalId: string, preference: CapabilityPreference) => void;
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
    ? '能力列表正在读取'
    : status === 'failed'
      ? '能力列表暂不可用'
      : `这段对话可用工具：${availableCount} 个`;
  const text = status === 'loading'
    ? '能力 · 加载中'
    : status === 'failed'
      ? '能力 · 未加载'
      : `能力 · ${availableCount}`;

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
      <PopoverContent
        align="start"
        aria-labelledby="agent-tool-picker-title"
        className="agent-tool-picker"
      >
        <header>
          <span>
            <strong id="agent-tool-picker-title">当前对话能力</strong>
            <small>可用 {availableCount} 项，共发现 {capabilityCatalog?.items.length ?? tools.length} 项能力</small>
          </span>
          <button
            aria-label="关闭当前对话能力"
            className="agent-tool-picker__close"
            onClick={() => setOpen(false)}
            type="button"
          >
            <X aria-hidden="true" size={18} />
          </button>
        </header>
        {adjustmentDisabled ? (
          <p className="agent-picker-popover__note" data-tone="warning">
            当前任务正在运行；可以查看能力，但要等本轮结束后再调整。
          </p>
        ) : null}
        <div>
          {tools.map((tool) => {
            const available = toolAvailableForCurrentSession(tool, session);
            const capability = capabilityCatalog?.items.find(
              (item) => item.kind === 'tool' && item.id === tool.id,
            );
            return (
              <article className="agent-tool-picker__row" key={tool.id}>
                <button
                  type="button"
                  disabled={!available || adjustmentDisabled}
                  onClick={() => {
                    setOpen(false);
                    onSelect(tool);
                  }}
                >
                  <span><strong>{tool.displayName}</strong><small>{tool.description}</small></span>
                  <i data-risk={tool.riskLevel}>
                    {available ? riskLabel(tool.riskLevel) : '当前对话不可用'}
                  </i>
                </button>
                {capability ? (
                  <Select
                    aria-label={`${tool.displayName}的当前对话披露`}
                    disabled={adjustmentDisabled || capabilityPolicyPending}
                    onValueChange={(preference) => onCapabilityPreferenceChange(capability.canonicalId, preference)}
                    options={capabilityPreferenceOptions}
                    value={capabilityCatalog?.sessionPolicy?.disclosurePreferences.session[capability.canonicalId] ?? 'inherit'}
                  />
                ) : null}
              </article>
            );
          })}
        </div>
        <p className="agent-picker-popover__note">
          披露不等于授权；更改从下一次打开或下一轮开始生效，也不会停止正在运行的后台任务。
        </p>
      </PopoverContent>
    </Popover>
  );
}
