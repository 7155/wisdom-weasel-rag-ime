import * as RadioGroup from '@radix-ui/react-radio-group';
import {
  BookOpenText,
  Check,
  Layers3,
  LoaderCircle,
} from 'lucide-react';
import { useState } from 'react';

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import {
  CONTEXT_RESOURCE_PROFILES,
  contextResourceProfileId,
  contextResourceProfileLabel,
  contextResourceSelection,
  type ContextResourceSelection,
} from '../context-resource-profile';
import type { SessionSummary } from '../types';

export function ContextResourcesPicker({
  session,
  disabled,
  pending,
  onChange,
}: {
  session?: SessionSummary;
  disabled: boolean;
  pending: boolean;
  onChange: (selection: ContextResourceSelection) => void;
}) {
  const [open, setOpen] = useState(false);
  const selection = contextResourceSelection(session);
  const profileId = contextResourceProfileId(selection);
  const profileLabel = contextResourceProfileLabel(selection);

  function choose(value: string): void {
    const profile = CONTEXT_RESOURCE_PROFILES.find((item) => item.id === value);
    if (!profile) return;
    setOpen(false);
    onChange(profile.selection);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          aria-busy={pending || undefined}
          aria-label={`上下文资源：${profileLabel}`}
          className="agent-composer__picker agent-composer__project-context"
          data-enabled={profileId !== 'core' || undefined}
          size="small"
          title={`上下文资源：${profileLabel}`}
          variant="quiet"
          disabled={!session || disabled}
          leadingIcon={pending
            ? <LoaderCircle className="ui-spin" size={15} />
            : <BookOpenText size={15} />}
        >
          上下文 · {profileLabel}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-picker-popover agent-project-context-picker">
        <header>
          <BookOpenText size={16} />
          <span><strong>上下文资源</strong><small>统一装入同一套 Pi 资源目录</small></span>
        </header>
        <RadioGroup.Root
          aria-label="上下文资源范围"
          className="agent-project-context-picker__profiles"
          value={profileId === 'custom' ? '' : profileId}
          onValueChange={choose}
        >
          {CONTEXT_RESOURCE_PROFILES.map((profile) => (
            <RadioGroup.Item
              key={profile.id}
              value={profile.id}
              disabled={disabled}
            >
              <Layers3 size={15} aria-hidden="true" />
              <span>
                <strong>{profile.label}</strong>
                <small>{profile.description}</small>
              </span>
              {profileId === profile.id ? <Check size={15} aria-hidden="true" /> : null}
            </RadioGroup.Item>
          ))}
        </RadioGroup.Root>
        {profileId === 'custom' ? (
          <p className="agent-project-context-picker__custom" role="status">
            当前为旧版自定义组合；选择上方任一范围即可统一。
          </p>
        ) : null}
        <p className="agent-picker-popover__note">
          本项目 Skills 始终可用；选择会立即显示，空闲 Runtime 在后台换代，历史消息不变。
        </p>
      </PopoverContent>
    </Popover>
  );
}
