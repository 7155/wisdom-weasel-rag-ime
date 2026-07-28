import { BrainCircuit, Check, ChevronRight, LoaderCircle } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/primitives';
import { modelSelectionFromCatalog } from '../model-selection';
import type { ModelCatalog, ThinkingLevel } from '../types';

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
  useEffect(() => {
    if (requestOpen > 0 && catalog && !disabled) setOpen(true);
  }, [catalog, disabled, requestOpen]);
  const selection = catalog ? modelSelectionFromCatalog(catalog) : undefined;
  const selectedProvider = catalog?.providers.find(
    (item) => item.id === selection?.provider,
  );
  const selectedModel = selectedProvider?.models.find(
    (item) => item.id === selection?.modelId,
  );
  const thinking = selection?.level ?? catalog?.thinkingLevel ?? 'off';
  const selectedLabel = selectedModel
    ? `${selectedModel.name} · ${selectedProvider?.displayName || selectedModel.provider}`
    : '未选择';

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
            : <BrainCircuit size={15} />}
        >
          {selectedModel ? selectedLabel : '选择模型'} · {thinkingLabel(thinking)}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="agent-model-tree">
        <header>
          <strong>模型与推理强度</strong>
          {pending ? <small role="status">正在应用上一项选择</small> : null}
        </header>
        {catalog?.providers.map((providerItem) => (
          <details key={providerItem.id} open={providerItem.id === selection?.provider}>
            <summary>{providerItem.displayName}<ChevronRight size={14} /></summary>
            {providerItem.models.map((modelItem) => (
              <details key={modelItem.id} open={modelItem.id === selection?.modelId}>
                <summary
                  aria-label={`选择模型 ${modelItem.name}`}
                  onClick={(event) => {
                    if (
                      providerItem.id === selection?.provider
                      && modelItem.id === selection.modelId
                    ) return;
                    event.preventDefault();
                    choose(
                      providerItem.id,
                      modelItem.id,
                      preferredThinkingLevel(modelItem.thinkingLevels, thinking),
                    );
                  }}
                >
                  {modelItem.name}
                  {modelItem.id === selection?.modelId
                    ? <Check size={14} />
                    : <ChevronRight size={14} />}
                </summary>
                <div className="agent-model-tree__levels">
                  {modelItem.thinkingLevels.map((level) => (
                    <button
                      type="button"
                      key={level}
                      aria-current={(
                        providerItem.id === selection?.provider
                        && modelItem.id === selection.modelId
                        && level === thinking
                      ) || undefined}
                      onClick={() => choose(providerItem.id, modelItem.id, level)}
                    >
                      {thinkingLabel(level)}
                    </button>
                  ))}
                </div>
              </details>
            ))}
          </details>
        ))}
      </PopoverContent>
    </Popover>
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

function preferredThinkingLevel(
  levels: ThinkingLevel[],
  current: ThinkingLevel,
): ThinkingLevel {
  if (levels.includes(current)) return current;
  if (levels.includes('medium')) return 'medium';
  if (levels.includes('off')) return 'off';
  return levels[0] ?? 'off';
}
