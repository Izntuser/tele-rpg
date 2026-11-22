import { useQueryClient } from '@tanstack/react-query';
import { Award } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useAuth } from '../auth/context';
import { ACHIEVEMENTS_KEY, useAchievements } from './api';

/** How long one toast stays up. */
export const TOAST_MS = 5_000;
/** Unlocks can also come from the companion's actions (e.g. "mentor"), so poll gently. */
export const ACHIEVEMENTS_POLL_MS = 60_000;

/**
 * Watches my unlocks and shows a toast for each new one. The first load of a session only
 * records what is already unlocked (no toast storm; the journal keeps every unlock); after
 * that, every successful mutation refetches the list, so an unlock earned by my own action
 * shows right away. Nothing is persisted in the browser (the app keeps no web storage).
 */
export function AchievementToaster() {
  const { t } = useTranslation('stats');
  const { state, telegram } = useAuth();
  const queryClient = useQueryClient();
  const userId = state.status === 'authenticated' && state.user.onboarded_at ? state.user.id : null;
  const achievements = useAchievements({ enabled: userId !== null, refetchInterval: ACHIEVEMENTS_POLL_MS });
  const seen = useRef<{ userId: number; codes: Set<string> } | null>(null);
  const [queue, setQueue] = useState<string[]>([]);

  useEffect(() => {
    if (userId === null) return;
    return queryClient.getMutationCache().subscribe((event) => {
      if (event.type === 'updated' && event.action.type === 'success') {
        void queryClient.invalidateQueries({ queryKey: ACHIEVEMENTS_KEY });
      }
    });
  }, [queryClient, userId]);

  const unlocks = achievements.data?.unlocks;
  useEffect(() => {
    if (userId === null || !unlocks) return;
    const codes = unlocks.map((u) => u.code);
    if (seen.current?.userId !== userId) {
      // First load this session: everything so far counts as seen.
      seen.current = { userId, codes: new Set(codes) };
      return;
    }
    const known = seen.current.codes;
    const fresh = codes.filter((c) => !known.has(c));
    if (fresh.length === 0) return;
    fresh.forEach((c) => known.add(c));
    telegram.haptic.notification('success');
    setQueue((q) => [...q, ...fresh]);
  }, [unlocks, userId, telegram]);

  const current = queue[0];
  useEffect(() => {
    if (current === undefined) return;
    const timer = window.setTimeout(() => setQueue((q) => q.slice(1)), TOAST_MS);
    return () => window.clearTimeout(timer);
  }, [current]);

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 z-40 flex justify-center px-4"
      style={{ top: 'calc(var(--safe-top) + 3.25rem)' }}
    >
      {current !== undefined ? (
        <div
          key={current}
          role="status"
          data-testid="achievement-toast"
          data-code={current}
          className="flex max-w-sm items-center gap-3 rounded-2xl border border-gold bg-surface px-4 py-3 shadow-lg"
        >
          <Award aria-hidden="true" size={28} className="shrink-0 text-gold" />
          <span className="flex min-w-0 flex-col">
            <span className="text-xs font-semibold uppercase tracking-wide text-gold">{t('achievements.toast')}</span>
            <span className="truncate text-sm font-bold">{t(`achievements.items.${current}.title`)}</span>
            <span className="truncate text-xs text-muted">{t(`achievements.items.${current}.description`)}</span>
          </span>
        </div>
      ) : null}
    </div>
  );
}
