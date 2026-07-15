import * as SwitchPrimitive from '@radix-ui/react-switch';
import { forwardRef, useId, type ComponentPropsWithoutRef, type ComponentRef, type ReactNode } from 'react';
import { cn } from './utils';

export const Switch = forwardRef<
  ComponentRef<typeof SwitchPrimitive.Root>,
  ComponentPropsWithoutRef<typeof SwitchPrimitive.Root> & {
    label: ReactNode;
    description?: ReactNode;
  }
>(function Switch({ className, description, id, label, ...props }, ref) {
  const generatedId = useId();
  const controlId = id ?? generatedId;

  return (
    <div className={cn('ui-switch-field', className)}>
      <div className="ui-switch-field__copy">
        <label className="ui-switch-field__label" htmlFor={controlId}>
          {label}
        </label>
        {description ? <span className="ui-switch-field__description">{description}</span> : null}
      </div>
      <SwitchPrimitive.Root ref={ref} id={controlId} className="ui-switch" {...props}>
        <SwitchPrimitive.Thumb className="ui-switch__thumb" />
      </SwitchPrimitive.Root>
    </div>
  );
});
