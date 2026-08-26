import { X } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
} from '@/components/primitives';
import {
  capabilityScopeLabel,
  type CapabilityCatalog,
  type CapabilityPreference,
} from '@/features/plugins/capability-policy';
import { CapabilityMark } from '../marks/ConversationMarks';
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
  const detail = status === 'loading'
    ? ' · 加载中'
    : status === 'failed'
      ? ' · 未加载'
      : ` · ${availableCount}`;

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
          leadingIcon={<CapabilityMark size={16} />}
        >
          <span className="agent-composer__picker-text">能力</span>
          <span className="agent-composer__picker-detail">{detail}</span>
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
            const presentation = toolPresentation(tool);
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
                  <span><strong>{presentation.name}</strong><small>{presentation.description}</small></span>
                  <i data-risk={tool.riskLevel}>
                    {available ? riskLabel(tool.riskLevel) : '当前对话不可用'}
                  </i>
                </button>
                {capability ? (
                  <div className="agent-tool-picker__preference">
                    <span
                      className="agent-tool-picker__effective"
                      data-effective={capability.disclosure.effective}
                    >
                      <strong>{capability.disclosure.effective === 'enabled' ? '已启用' : '已关闭'}</strong>
                      <small>作用域：{capabilityScopeLabel(capability.effectiveScope)}</small>
                    </span>
                    <Select
                      aria-label={`${presentation.name}的当前对话使用`}
                      disabled={adjustmentDisabled || capabilityPolicyPending}
                      onValueChange={(preference) => onCapabilityPreferenceChange(capability.canonicalId, preference)}
                      options={capabilityUsagePreferenceOptions}
                      value={capabilityCatalog?.sessionPolicy?.disclosurePreferences.session[capability.canonicalId] ?? 'inherit'}
                    />
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
        <p className="agent-picker-popover__note">
          这里控制当前对话是否使用这些能力，不改变执行授权；更改从下一轮开始生效，也不会停止正在运行的后台任务。
        </p>
      </PopoverContent>
    </Popover>
  );
}

const capabilityUsagePreferenceOptions = [
  { value: 'inherit', label: '跟随默认' },
  { value: 'enabled', label: '当前对话启用' },
  { value: 'disabled', label: '当前对话关闭' },
] as const;

function toolPresentation(tool: ToolManifest): { name: string; description: string } {
  if (tool.id === 'memory') {
    return {
      name: '记忆召回',
      description: '控制当前对话的自动个人记忆装配，也允许 Agent 显式调用记忆工具。',
    };
  }
  if (tool.id === 'knowledge') {
    return {
      name: '知识库 / Agent RAG',
      description: '启用后，Agent 可按当前问题反复检索已允许的知识库。',
    };
  }
  return { name: tool.displayName, description: tool.description };
}
