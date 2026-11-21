import { useTranslation } from 'react-i18next';

import { cn } from '../ui/cn';

export function XpBar({
  level,
  current,
  max,
  className,
}: {
  level: number;
  current: number;
  max: number;
  className?: string;
}) {
  const { t } = useTranslation();
  const percent = max > 0 ? Math.min(100, Math.max(0, Math.round((current / max) * 100))) : 0;
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div className="flex justify-between text-sm">
        <span className="font-semibold">{t('game.level', { level })}</span>
        <span className="text-muted">{t('game.xp', { current, max })}</span>
      </div>
      <div
        role="progressbar"
        aria-label={t('game.level', { level })}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={Math.min(current, max)}
        className="h-2 overflow-hidden rounded-full bg-surface-2"
      >
        <div className="h-full bg-xp transition-[width]" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
