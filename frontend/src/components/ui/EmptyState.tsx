import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { cn } from './cn';

export function EmptyState({
  title,
  description,
  icon,
  action,
  className,
}: {
  title?: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <div
      data-testid="empty-state"
      className={cn('flex flex-col items-center gap-2 p-8 text-center', className)}
    >
      {icon ? (
        <div aria-hidden="true" className="text-muted">
          {icon}
        </div>
      ) : null}
      <p className="text-base font-semibold">{title ?? t('ui.empty')}</p>
      {description ? <p className="text-sm text-muted">{description}</p> : null}
      {action}
    </div>
  );
}
