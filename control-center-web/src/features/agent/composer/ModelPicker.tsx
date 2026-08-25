import {
  Check,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
} from 'lucide-react';
import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
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

type PickerView = 'models' | 'reasoning';

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
  const [view, setView] = useState<PickerView>('models');
  const [activeProviderId, setActiveProviderId] = useState('');
  const reasoningRailRef = useRef<HTMLDivElement>(null);
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
  const defaultProviderId = selectedProvider?.id ?? catalog?.providers[0]?.id ?? '';
  const activeProvider = catalog?.providers.find(
    (provider) => provider.id === activeProviderId,
  ) ?? selectedProvider ?? catalog?.providers[0];
  const models = activeProvider?.models ?? [];

  useEffect(() => {
    if (requestOpen > 0 && catalog && !disabled) {
      setView('models');
      setActiveProviderId(defaultProviderId);
      setOpen(true);
    }
  }, [catalog, defaultProviderId, disabled, requestOpen]);

  useEffect(() => {
    if (!open || view !== 'reasoning') return undefined;
    const frame = window.requestAnimationFrame(() => {
      reasoningRailRef.current
        ?.querySelector<HTMLButtonElement>('[role="radio"][aria-checked="true"]')
        ?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [open, thinking, view]);

  function choose(provider: string, modelId: string, level: ThinkingLevel): void {
    setOpen(false);
    onChange(provider, modelId, level);
  }

  function handleOpenChange(nextOpen: boolean): void {
    if (nextOpen) {
      setView('models');
      setActiveProviderId(defaultProviderId);
    }
    setOpen(nextOpen);
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
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
        {view === 'models' ? (
          <div className="agent-model-picker__pane" data-view="models">
            <header className="agent-model-picker__header">
              <span>
                <strong>模型与推理强度</strong>
                <small>{pending ? '正在核对 Pi 返回的状态' : selectedLabel}</small>
              </span>
              <button
                type="button"
                className="agent-model-picker__reasoning-link"
                disabled={!selectedModel}
                onClick={() => setView('reasoning')}
              >
                <span>推理</span>
                <strong>{thinkingLabel(thinking)}</strong>
                <ChevronRight size={14} />
              </button>
            </header>
            <div className="agent-model-picker__browser">
              <div
                className="agent-model-picker__providers"
                role="tablist"
                aria-label="模型服务"
              >
                {catalog?.providers.map((providerItem) => (
                  <button
                    type="button"
                    role="tab"
                    key={providerItem.id}
                    aria-selected={providerItem.id === activeProvider?.id}
                    aria-controls={`agent-model-provider-${safeId(providerItem.id)}`}
                    aria-label={`查看 ${providerItem.displayName} 的 ${providerItem.models.length} 个模型`}
                    onClick={() => setActiveProviderId(providerItem.id)}
                  >
                    <ProviderMark
                      displayName={providerItem.displayName}
                      providerId={providerItem.id}
                      size={16}
                    />
                    <span>{providerItem.displayName}</span>
                    <small>{providerItem.models.length}</small>
                  </button>
                ))}
              </div>
              <section
                key={activeProvider?.id ?? 'empty'}
                id={`agent-model-provider-${safeId(activeProvider?.id ?? 'empty')}`}
                className="agent-model-picker__provider-panel"
                role="tabpanel"
                aria-label={activeProvider?.displayName ?? '当前模型服务'}
              >
                <header>
                  <strong>{activeProvider?.displayName ?? '模型'}</strong>
                  <small>{models.length} 个模型</small>
                </header>
                <div
                  className="agent-model-picker__models"
                  role="listbox"
                  aria-label={`${activeProvider?.displayName ?? ''} 模型`}
                  onKeyDown={moveModelFocus}
                >
                  {models.map((modelItem) => {
                    const selected = (
                      activeProvider?.id === selection?.provider
                      && modelItem.id === selection?.modelId
                    );
                    return (
                      <button
                        type="button"
                        role="option"
                        id={modelOptionId(
                          activeProvider?.id ?? modelItem.provider,
                          modelItem.id,
                        )}
                        key={modelItem.id}
                        aria-selected={selected}
                        aria-label={`选择模型 ${modelItem.name}`}
                        onClick={() => {
                          if (selected) {
                            setView('reasoning');
                            return;
                          }
                          choose(
                            activeProvider?.id ?? modelItem.provider,
                            modelItem.id,
                            preferredThinkingLevel(modelItem.thinkingLevels, thinking),
                          );
                        }}
                      >
                        <span>
                          <strong>{modelItem.name}</strong>
                          <small>
                            {modelItem.reasoning
                              ? `${modelItem.thinkingLevels.length} 档推理`
                              : '直接生成'}
                          </small>
                        </span>
                        {selected ? <Check size={14} /> : <ChevronRight size={14} />}
                      </button>
                    );
                  })}
                  {models.length === 0 ? <p>当前 Provider 没有可用模型</p> : null}
                </div>
              </section>
            </div>
          </div>
        ) : (
          <div className="agent-model-picker__pane" data-view="reasoning">
            <header className="agent-model-picker__header">
              <button
                type="button"
                className="agent-model-picker__back"
                aria-label="返回模型列表"
                onClick={() => setView('models')}
              >
                <ChevronLeft size={16} />
              </button>
              <span>
                <strong>推理强度</strong>
                <small>{selectedModel?.name ?? '当前模型'}</small>
              </span>
              {pending ? <LoaderCircle className="ui-spin" size={15} aria-label="正在核对模型状态" /> : null}
            </header>
            <div className="agent-model-picker__reasoning-copy">
              <strong>{thinkingLabel(thinking)}</strong>
              <small>选择后立即用于当前对话，并以实际返回状态为准</small>
            </div>
            <ReasoningRail
              ref={reasoningRailRef}
              levels={selectedModel?.thinkingLevels ?? []}
              selected={thinking}
              onChoose={(level) => {
                if (!selection) return;
                choose(selection.provider, selection.modelId, level);
              }}
            />
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

const ReasoningRail = forwardRef<HTMLDivElement, {
  levels: ThinkingLevel[];
  selected: ThinkingLevel;
  onChoose: (level: ThinkingLevel) => void;
}>(function ReasoningRail({
  levels,
  selected,
  onChoose,
}, ref) {
  const selectedIndex = Math.max(0, levels.indexOf(selected));
  const style = {
    '--level-count': Math.max(1, levels.length),
    '--level-index': selectedIndex,
  } as ReasoningRailStyle;
  return (
    <div
      ref={ref}
      className="agent-model-picker__reasoning"
      role="radiogroup"
      aria-label="推理强度"
      style={style}
      onKeyDown={moveReasoningFocus}
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
});

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

function modelOptionId(provider: string, modelId: string): string {
  return `agent-model-${safeId(provider)}-${safeId(modelId)}`;
}

function safeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/gu, '-');
}

function moveModelFocus(event: KeyboardEvent<HTMLDivElement>): void {
  moveButtonFocus(event, '[role="option"]');
}

function moveReasoningFocus(event: KeyboardEvent<HTMLDivElement>): void {
  moveButtonFocus(event, '[role="radio"]');
}

function moveButtonFocus(
  event: KeyboardEvent<HTMLDivElement>,
  selector: string,
): void {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
  const options = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(selector));
  if (options.length === 0) return;
  event.preventDefault();
  const current = options.findIndex((option) => option === document.activeElement);
  const next = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? options.length - 1
      : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
        ? Math.max(0, (current < 0 ? 0 : current) - 1)
        : Math.min(options.length - 1, (current < 0 ? -1 : current) + 1);
  options[next]?.focus();
}

interface ReasoningRailStyle extends CSSProperties {
  '--level-count': number;
  '--level-index': number;
}
