import * as RadioGroup from '@radix-ui/react-radio-group';
import type { ReactNode } from 'react';
import { cn } from './utils';

export type SegmentedControlItem<T extends string> = {
  value: T;
  label: ReactNode;
  disabled?: boolean;
};

export function SegmentedControl<T extends string>({
  'aria-label': ariaLabel,
  className,
  disabled,
  items,
  onValueChange,
  value,
}: {
  'aria-label': string;
  className?: string;
  disabled?: boolean;
  items: readonly SegmentedControlItem<T>[];
  onValueChange: (value: T) => void;
  value: T;
}) {
  return (
    <RadioGroup.Root
      aria-label={ariaLabel}
      className={cn('ui-segmented', className)}
      disabled={disabled}
      onValueChange={(next) => onValueChange(next as T)}
      orientation="horizontal"
      value={value}
    >
      {items.map((item) => (
        <RadioGroup.Item
          key={item.value}
          className="ui-segmented__item"
          disabled={item.disabled}
          value={item.value}
        >
          {item.label}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  );
}
