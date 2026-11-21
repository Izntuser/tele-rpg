import { useTranslation } from 'react-i18next';

import { cn } from './cn';

export const STATUSES = [
  'offered',
  'active',
  'submitted',
  'completed',
  'declined',
  'cancelled',
  'expired',
] as const;
export type Status = (typeof STATUSES)[number];

const TONE: Record<Status, string> = {
  offered: 'border-accent text-accent',
  active: 'border-accent text-accent',
  submitted: 'border-gold text-gold',
  completed: 'border-xp text-xp',
  declined: 'border-danger text-danger',
  cancelled: 'border-border text-muted',
  expired: 'border-border text-muted',
};

export function StatusPill({ status, className }: { status: Status; className?: string }) {
  const { t } = useTranslation();
  return (
    <span
      data-status={status}
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
        TONE[status],
        className,
      )}
    >
      {t(`game.status.${status}`)}
    </span>
  );
}
