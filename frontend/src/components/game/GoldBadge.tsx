import { Coins } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { cn } from '../ui/cn';

export function GoldBadge({ amount, className }: { amount: number; className?: string }) {
  const { t } = useTranslation();
  return (
    <span
      aria-label={t('game.gold', { amount })}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border border-gold px-2 py-0.5 text-sm font-semibold text-gold',
        className,
      )}
    >
      <Coins aria-hidden="true" size={14} />
      <span>{amount}</span>
    </span>
  );
}
