import { LoaderCircle } from 'lucide-react';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import { ProviderMark } from '../marks/ConversationMarks';
import { modelSelectionFromCatalog } from '../model-selection';
import type { ModelCatalog, ThinkingLevel } from '../types';
import { ModelChoiceList, moveButtonFocus } from './ModelChoiceList';
import { modelChoiceGroupsFromCatalog, modelChoiceKey } from './model-choice';

/**
 * Model + reasoning is one decision, so it is one flat panel: every Provider's
 * models are listed at once under quiet group headings, and the reasoning rail
 * for the current model stays docked at the foot of the same surface. Nothing
 * navigates — picking a model and dialling its reasoning are both a single
 * gesture from the moment the panel opens.
 *
 * Provider identity rides on the mark plus the grouping heading rather than a
 * row of pill tabs, so a large catalog stays scannable without hiding the rest
 * of it behind a filter the user has to discover.
 */
export function ModelPicker({
  catalog,
  disabled,
  pending,
  requestOpen,
  onChange,
}: {
  catalog?: ModelCatalog;
  disabled: boolean;
  pending: boolean;
  requestOpen: number;
  onChange: (provider: string, modelId: string, level: ThinkingLevel) => void;
}) {
  const [open, setOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
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
  const selectedKey = selection
    ? modelChoiceKey(selection.provider, selection.modelId)
    : '';

  useEffect(() => {
    if (requestOpen > 0 && catalog && !disabled) setOpen(true);
  }, [catalog, disabled, requestOpen]);

  // The trigger already names the current model; the panel opens with the
  // keyboard on that same row so arrow keys continue the sentence instead of
  // restarting at the top of the catalog.
  useEffect(() => {
    if (!open) return undefined;
    const frame = window.requestAnimationFrame(() => {
      const list = listRef.current;
      const target = list?.querySelector<HTMLButtonElement>(
        '[role="option"][aria-selected="true"]',
      ) ?? list?.querySelector<HTMLButtonElement>('[role="option"]');
      target?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  function choose(provider: string, modelId: string, level: ThinkingLevel): void {
    setOpen(false);
    onChange(provider, modelId, level);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          aria-busy={pending || undefined}
          aria-label={`模型：${selectedLabel}，思考强度：${thinkingLabel(thinking)}`}
          className="agent-composer__picker"
          size="small"
          title={`模型：${selectedLabel}，思考强度：${thinkingLabel(thinking)}`}
          variant="quiet"
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
        >
          {/* The provider name and the reasoning level fold away before the
              model name does; the mark keeps the provider legible after the
              text is gone. */}
          <span className="agent-composer__picker-text">
            {selectedModel ? selectedModel.name : '选择模型'}
          </span>
          {selectedModel && providerName ? (
            <span className="agent-composer__picker-detail"> · {providerName}</span>
          ) : null}
          <span className="agent-composer__picker-detail"> · {thinkingLabel(thinking)}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label="模型与推理强度"
        className="agent-model-picker"
      >
        <div className="agent-model-picker__panel">
          <header className="agent-model-picker__header">
            <ProviderMark
              displayName={selectedProvider?.displayName}
              providerId={selectedProvider?.id ?? selection?.provider}
              size={20}
            />
            <span>
              <small>模型与推理强度</small>
              <strong>{selectedLabel}</strong>
            </span>
            {pending ? (
              <LoaderCircle
                aria-label="正在核对 Pi 返回的状态"
                className="ui-spin"
                size={15}
              />
            ) : null}
          </header>
          <ModelChoiceList
            ariaLabel="可用模型"
            groups={groups}
            listRef={listRef}
            selectedKey={selectedKey}
            onChoose={(option) => {
              // Re-picking the current model is a confirmation, not a second
              // request: close and leave Pi's state untouched.
              if (option.key === selectedKey) {
                setOpen(false);
                return;
              }
              const model = catalog?.providers
                .find((item) => item.id === option.providerId)
                ?.models.find((item) => item.id === option.modelId);
              choose(
                option.providerId,
                option.modelId,
                preferredThinkingLevel(model?.thinkingLevels ?? [], thinking),
              );
            }}
          />
          <footer className="agent-model-picker__reasoning-bar">
            <p className="agent-model-picker__reasoning-copy">
              <span>推理强度</span>
              <strong>{thinkingLabel(thinking)}</strong>
            </p>
            {levels.length > 0 ? (
              <ReasoningRail
                levels={levels}
                selected={thinking}
                onChoose={(level) => {
                  if (!selection || level === thinking) {
                    setOpen(false);
                    return;
                  }
                  choose(selection.provider, selection.modelId, level);
                }}
              />
            ) : (
              <small className="agent-model-picker__reasoning-empty">
                {selectedModel ? '当前模型不提供推理档位' : '先选择一个模型'}
              </small>
            )}
          </footer>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ReasoningRail({
  levels,
  selected,
  onChoose,
}: {
  levels: ThinkingLevel[];
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
      className="agent-model-picker__reasoning"
      role="radiogroup"
      aria-label="推理强度"
      style={style}
      onKeyDown={(event) => moveButtonFocus(event, '[role="radio"]')}
    >
      <span className="agent-model-picker__reasoning-indicator" aria-hidden="true" />
      {levels.map((level) => (
        <button
          type="button"
          role="radio"
          key={level}
          aria-checked={level === selected}
          aria-label={thinkingLabel(level)}
          tabIndex={level === selected ? 0 : -1}
          onClick={() => onChoose(level)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            onChoose(level);
          }}
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
