import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

export function EmptyState({
  action,
  description,
  headingLevel = 2,
  icon: Icon,
  title,
}: {
  action?: ReactNode;
  description: ReactNode;
  headingLevel?: 2 | 3 | 4;
  icon: LucideIcon;
  title: ReactNode;
}) {
  const Heading = `h${headingLevel}` as const;
  return (
    <div className="ui-empty-state">
      <span className="ui-empty-state__icon" aria-hidden="true">
        <Icon size={22} strokeWidth={1.8} />
      </span>
      <Heading className="ui-empty-state__title">{title}</Heading>
      <p className="ui-empty-state__description">{description}</p>
      {action ? <div className="ui-empty-state__action">{action}</div> : null}
    </div>
  );
}
