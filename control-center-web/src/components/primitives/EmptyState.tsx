import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

export function EmptyState({
  action,
  description,
  icon: Icon,
  title,
}: {
  action?: ReactNode;
  description: ReactNode;
  icon: LucideIcon;
  title: ReactNode;
}) {
  return (
    <div className="ui-empty-state">
      <span className="ui-empty-state__icon" aria-hidden="true">
        <Icon size={22} strokeWidth={1.8} />
      </span>
      <h2 className="ui-empty-state__title">{title}</h2>
      <p className="ui-empty-state__description">{description}</p>
      {action ? <div className="ui-empty-state__action">{action}</div> : null}
    </div>
  );
}
