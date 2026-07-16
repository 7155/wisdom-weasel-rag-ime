import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Tooltip } from './Tooltip';
import { cn } from './utils';

export type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children' | 'aria-label'> & {
  label: string;
  icon: ReactNode;
  size?: 'small' | 'medium' | 'large';
  tooltip?: boolean;
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left';
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  {
    className,
    icon,
    label,
    size = 'medium',
    tooltip = false,
    tooltipSide = 'bottom',
    type = 'button',
    onPointerUp,
    ...props
  },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type={type}
      className={cn('ui-icon-button', className)}
      data-size={size}
      aria-label={label}
      onPointerUp={(event) => {
        onPointerUp?.(event);
        if (!event.defaultPrevented) event.currentTarget.blur();
      }}
      {...props}
    >
      <span aria-hidden="true">{icon}</span>
    </button>
  );

  return tooltip ? (
    <Tooltip content={label} side={tooltipSide}>
      {button}
    </Tooltip>
  ) : (
    button
  );
});
