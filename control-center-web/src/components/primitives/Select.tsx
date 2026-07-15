import * as RadixSelect from '@radix-ui/react-select';
import { Check, ChevronDown } from 'lucide-react';
import type { ReactNode } from 'react';

const emptyValue = '__rag-ime-select-empty__';

export interface SelectOption<T extends string> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
}

export function Select<T extends string>({
  'aria-label': ariaLabel,
  className = '',
  disabled,
  id,
  onValueChange,
  options,
  placeholder,
  value,
}: {
  'aria-label'?: string;
  className?: string;
  disabled?: boolean;
  id?: string;
  onValueChange: (value: T) => void;
  options: readonly SelectOption<T>[];
  placeholder?: string;
  value?: T;
}) {
  const radixValue = value === '' ? emptyValue : value;
  return (
    <RadixSelect.Root
      disabled={disabled}
      onValueChange={(next) => onValueChange((next === emptyValue ? '' : next) as T)}
      value={radixValue}
    >
      <RadixSelect.Trigger aria-label={ariaLabel} className={`ui-select__trigger ${className}`.trim()} id={id}>
        <RadixSelect.Value placeholder={placeholder} />
        <RadixSelect.Icon className="ui-select__icon"><ChevronDown aria-hidden="true" size={14} /></RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content className="ui-select__content" collisionPadding={8} position="popper" sideOffset={4}>
          <RadixSelect.Viewport className="ui-select__viewport">
            {options.map((option) => (
              <RadixSelect.Item
                className="ui-select__item"
                disabled={option.disabled}
                key={option.value || emptyValue}
                value={option.value === '' ? emptyValue : option.value}
              >
                <RadixSelect.ItemIndicator className="ui-select__indicator"><Check aria-hidden="true" size={13} /></RadixSelect.ItemIndicator>
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
