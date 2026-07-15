import * as LabelPrimitive from '@radix-ui/react-label';
import {
  forwardRef,
  useId,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react';
import { cn } from './utils';

export function Field({
  children,
  className,
  description,
  error,
  htmlFor,
  label,
  required,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  htmlFor: string;
  label: ReactNode;
  required?: boolean;
}) {
  const descriptionId = `${htmlFor}-description`;
  const errorId = `${htmlFor}-error`;

  return (
    <div className={cn('ui-field', className)} data-invalid={Boolean(error) || undefined} {...props}>
      <LabelPrimitive.Root className="ui-field__label" htmlFor={htmlFor}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </LabelPrimitive.Root>
      {description ? (
        <span className="ui-field__description" id={descriptionId}>
          {description}
        </span>
      ) : null}
      {children}
      {error ? (
        <span className="ui-field__error" id={errorId} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, id, ...props },
  ref,
) {
  const generatedId = useId();
  return <input ref={ref} id={id ?? generatedId} className={cn('ui-input', className)} {...props} />;
});

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function TextArea({ className, id, ...props }, ref) {
    const generatedId = useId();
    return <textarea ref={ref} id={id ?? generatedId} className={cn('ui-input ui-textarea', className)} {...props} />;
  },
);
