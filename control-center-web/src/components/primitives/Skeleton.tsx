import type { HTMLAttributes } from 'react';
import { cn } from './utils';

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn('ui-skeleton', className)} {...props} />;
}
