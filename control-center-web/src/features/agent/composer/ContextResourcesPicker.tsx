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
          aria-label={`工作资料：${profileLabel}`}
          className="agent-composer__picker agent-composer__project-context"
          data-enabled={profileId !== 'core' || undefined}
          size="small"
          title={`工作资料：${profileLabel}`}
          variant="quiet"
          disabled={!session || disabled}
          leadingIcon={pending
            ? <LoaderCircle className="ui-spin" size={15} />
            : <BookOpenText size={15} />}
        >
          工作资料 · {profileLabel}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-picker-popover agent-project-context-picker">
        <header>
          <BookOpenText size={16} />
          <span>
            <strong>这段对话的工作资料</strong>
            <small>选择项目指令与可发现的技能来源</small>
          </span>
        </header>
        <RadioGroup.Root
          aria-label="工作资料范围"
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
          产品自带能力始终可用。更改从下一轮对话开始生效，不改动已有消息。
        </p>
      </PopoverContent>
    </Popover>
  );
}
