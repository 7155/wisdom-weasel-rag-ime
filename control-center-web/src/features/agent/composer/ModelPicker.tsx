import { LoaderCircle, Search } from 'lucide-react';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from 'react';

import {
  Button,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import { ProviderMark } from '../marks/ConversationMarks';
import { modelSelectionFromCatalog } from '../model-selection';
import type { ModelCatalog, ThinkingLevel } from '../types';
import { ModelChoiceList, moveButtonFocus } from './ModelChoiceList';
import {
  filterModelChoiceGroups,
  modelChoiceGroupsFromCatalog,
  modelChoiceKey,
} from './model-choice';

/**
 * Model and reasoning commit through the same Pi selection contract, so the
 * composer carries them as one control: a single trigger naming both facts,
 * opening one popover with a searchable catalog section and the current
 * model's discrete reasoning levels side by side.
 */
export function ModelPicker({
  catalog,
  disabled,
  pending,
  requestOpen,
  thinkingRequestOpen = 0,
  onChange,
}: {
  catalog?: ModelCatalog;
  disabled: boolean;
  pending: boolean;
  requestOpen: number;
  thinkingRequestOpen?: number;
  onChange: (provider: string, modelId: string, level: ThinkingLevel) => void;
}) {
  const [open, setOpen] = useState(false);
  const [focusSection, setFocusSection] = useState<'model' | 'thinking'>('model');
  const [query, setQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const reasoningRef = useRef<HTMLDivElement>(null);
  const selection = catalog ? modelSelectionFromCatalog(catalog) : undefined;
  const selectedProvider = catalog?.providers.find(
    (item) => item.id === selection?.provider,
  );
  const selectedModel = selectedProvider?.models.find(
    (item) => item.id === selection?.modelId,
  );
  const thinking = selection?.level ?? catalog?.thinkingLevel ?? 'off';
  const providerName = selectedProvider?.displayName || selectedModel?.provider || '';
  const selectedLabel = selectedModel
    ? `${selectedModel.name} · ${providerName}`
    : '未选择';
  const levels = selectedModel?.thinkingLevels ?? [];
  const groups = useMemo(() => modelChoiceGroupsFromCatalog(catalog), [catalog]);
  const filteredGroups = useMemo(
    () => filterModelChoiceGroups(groups, query),
    [groups, query],
  );
  const selectedKey = selection
    ? modelChoiceKey(selection.provider, selection.modelId)
    : '';

  useEffect(() => {
    if (requestOpen <= 0 || !catalog || disabled) return;
    setQuery('');
    setFocusSection('model');
    setOpen(true);
  }, [catalog, disabled, requestOpen]);

  useEffect(() => {
    if (thinkingRequestOpen <= 0 || !catalog || disabled || levels.length === 0) return;
    setFocusSection('thinking');
    setOpen(true);
  }, [catalog, disabled, levels.length, thinkingRequestOpen]);

  useEffect(() => {
    if (!open || focusSection !== 'model') return undefined;
    const frame = window.requestAnimationFrame(() => searchRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [focusSection, open]);

  useEffect(() => {
    if (!open || focusSection !== 'thinking') return undefined;
    const frame = window.requestAnimationFrame(() => {
      const selected = reasoningRef.current?.querySelector<HTMLButtonElement>(
        '[role="radio"][aria-checked="true"]',
      );
      selected?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [focusSection, open]);

  return (
    <Popover
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (nextOpen) {
          setQuery('');
          setFocusSection('model');
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button
          aria-busy={pending || undefined}
          aria-label={`模型与推理：${selectedLabel} · ${thinkingLabel(thinking)}`}
          className="agent-composer__picker"
          disabled={!catalog || disabled}
          leadingIcon={pending
            ? <LoaderCircle className="ui-spin" size={15} />
            : (
              <ProviderMark
                displayName={selectedProvider?.displayName}
                providerId={selectedProvider?.id ?? selection?.provider}
                size={16}
              />
            )}
          size="small"
          title={`模型与推理：${selectedLabel} · ${thinkingLabel(thinking)}`}
          variant="quiet"
        >
          <span className="agent-composer__picker-text">
            {selectedModel ? selectedModel.name : '选择模型'}
          </span>
          {selectedModel && providerName ? (
            <span className="agent-composer__picker-detail"> · {providerName}</span>
          ) : null}
          <strong className="agent-composer__picker-thinking"> · {compactThinkingLabel(thinking)}</strong>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label="选择模型与推理强度"
        className="agent-model-picker"
      >
        <label className="agent-model-picker__search">
          <Search aria-hidden="true" size={15} />
          <Input
            aria-label="搜索模型"
            autoComplete="off"
            onChange={(event) => setQuery(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key !== 'ArrowDown') return;
              event.preventDefault();
              const selected = listRef.current?.querySelector<HTMLButtonElement>(
                '[role="option"][aria-selected="true"]',
              );
              const first = listRef.current?.querySelector<HTMLButtonElement>('[role="option"]');
              (selected ?? first)?.focus();
            }}
            placeholder="搜索模型"
            ref={searchRef}
            type="search"
            value={query}
          />
        </label>
        <ModelChoiceList
          ariaLabel="可用模型"
          groups={filteredGroups}
          listRef={listRef}
          onChoose={(option) => {
            setOpen(false);
            if (option.key === selectedKey) return;
            const model = catalog?.providers
              .find((item) => item.id === option.providerId)
              ?.models.find((item) => item.id === option.modelId);
            onChange(
              option.providerId,
              option.modelId,
              preferredThinkingLevel(model?.thinkingLevels ?? [], thinking),
            );
          }}
          selectedKey={selectedKey}
        />
        {levels.length > 0 ? (
          <div className="agent-model-picker__thinking">
            <p className="agent-thinking-picker__heading">
              <span>推理强度</span>
              <strong>{thinkingLabel(thinking)}</strong>
            </p>
            <ReasoningRail
              levels={levels}
              onChoose={(level) => {
                setOpen(false);
                if (!selection || level === thinking) return;
                onChange(selection.provider, selection.modelId, level);
              }}
              railRef={reasoningRef}
              selected={thinking}
            />
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

function ReasoningRail({
  levels,
  railRef,
  selected,
  onChoose,
}: {
  levels: ThinkingLevel[];
  railRef: RefObject<HTMLDivElement | null>;
  selected: ThinkingLevel;
  onChoose: (level: ThinkingLevel) => void;
}) {
  const selectedIndex = Math.max(0, levels.indexOf(selected));
  const style = {
    '--level-count': Math.max(1, levels.length),
    '--level-index': selectedIndex,
  } as ReasoningRailStyle;
  return (
    <div
      aria-label="推理强度"
      className="agent-model-picker__reasoning"
      onKeyDown={(event) => moveButtonFocus(event, '[role="radio"]')}
      ref={railRef}
      role="radiogroup"
      style={style}
    >
      <span aria-hidden="true" className="agent-model-picker__reasoning-indicator" />
      {levels.map((level) => (
        <button
          aria-checked={level === selected}
          aria-label={thinkingLabel(level)}
          key={level}
          onClick={() => onChoose(level)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            onChoose(level);
          }}
          role="radio"
          tabIndex={level === selected ? 0 : -1}
          type="button"
        >
          {compactThinkingLabel(level)}
        </button>
      ))}
    </div>
  );
}

function thinkingLabel(value: string): string {
  return ({
    off: '不启用推理',
    minimal: '最小',
    low: '低',
    medium: '中',
    high: '高',
    xhigh: '极高',
    max: 'Max',
  } as Record<string, string>)[value] ?? value;
}

function compactThinkingLabel(value: ThinkingLevel): string {
  return value === 'off' ? '关' : thinkingLabel(value);
}

function preferredThinkingLevel(
  levels: ThinkingLevel[],
  current: ThinkingLevel,
): ThinkingLevel {
  if (levels.includes(current)) return current;
  if (levels.includes('medium')) return 'medium';
  if (levels.includes('off')) return 'off';
  return levels[0] ?? 'off';
}

interface ReasoningRailStyle extends CSSProperties {
  '--level-count': number;
  '--level-index': number;
}
