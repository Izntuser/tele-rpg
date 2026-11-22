import { Award, Lock } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { cn } from '../../components/ui/cn';
import { useAchievements } from './api';

/** Every achievement: unlocked ones highlighted, locked ones with their progress. */
export function AchievementsSection() {
  const { t } = useTranslation('stats');
  const achievements = useAchievements();
  const list = achievements.data?.definitions ?? [];
  const unlocked = list.filter((a) => a.unlocked_at).length;
  return (
    <section aria-labelledby="achievements-title" data-testid="achievements" className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="achievements-title" className="text-lg font-bold">
          {t('achievements.title')}
        </h2>
        {achievements.data ? (
          <span className="text-xs text-muted" data-testid="achievements-count">
            {t('achievements.count', { count: unlocked, total: list.length })}
          </span>
        ) : null}
      </div>
      {achievements.isError ? (
        <p role="alert" className="text-sm">
          {t('error')}
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-2">
          {list.map((a) => {
            const done = Boolean(a.unlocked_at);
            return (
              <li
                key={a.code}
                data-testid="achievement"
                data-code={a.code}
                data-unlocked={done}
                className={cn(
                  'flex flex-col gap-1 rounded-xl border px-3 py-2',
                  done ? 'border-gold bg-surface' : 'border-border bg-bg',
                )}
              >
                <span className="flex items-center gap-2 text-sm font-semibold">
                  {done ? (
                    <Award aria-hidden="true" size={16} className="shrink-0 text-gold" />
                  ) : (
                    <Lock aria-hidden="true" size={14} className="shrink-0 text-muted" />
                  )}
                  <span className="min-w-0 truncate">{t(`achievements.items.${a.code}.title`)}</span>
                </span>
                <span className="text-xs text-muted">{t(`achievements.items.${a.code}.description`)}</span>
                <span className="text-xs">
                  <span className="sr-only">{t(done ? 'achievements.unlocked' : 'achievements.locked')}, </span>
                  {done ? null : t('achievements.progress', { progress: a.progress, target: a.target })}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
