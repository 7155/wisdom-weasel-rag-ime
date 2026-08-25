import * as LabelPrimitive from '@radix-ui/react-label';
import {
  createContext,
  forwardRef,
  useContext,
  useId,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react';
import { cn } from './utils';

/* `<label for>` only names labelable form controls. A control the Field wraps
   may instead be a button carrying an ARIA role — a Radix Select trigger is
   role="combobox" on a <button> — and such a control silently ignores the
   label and falls back to naming itself from its own text, i.e. its current
   value. Publishing the label's id lets those controls point at it. */
const FieldLabelContext = createContext<string | undefined>(undefined);

export function useFieldLabelId(): string | undefined {
  return useContext(FieldLabelContext);
}

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
  const labelId = `${htmlFor}-label`;

  return (
    <div className={cn('ui-field', className)} data-invalid={Boolean(error) || undefined} {...props}>
      <LabelPrimitive.Root className="ui-field__label" htmlFor={htmlFor} id={labelId}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </LabelPrimitive.Root>
      {description ? (
        <span className="ui-field__description" id={descriptionId}>
          {description}
        </span>
      ) : null}
      <FieldLabelContext.Provider value={labelId}>{children}</FieldLabelContext.Provider>
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
