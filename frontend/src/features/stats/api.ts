import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';

type S = components['schemas'];
export type Stats = S['StatsOut'];
export type StatsPeriod = Stats['period'];
export type LifeBalance = S['LifeBalanceOut'];
export type BalancePeriod = LifeBalance['period'];
export type Who = LifeBalance['user'];
export type AttributeScore = S['AttributeScoreOut'];
export type Suggestion = S['SuggestionOut'];
export type AttributeKey = S['Attribute'];
export type Targets = S['TargetsOut'];
export type Achievements = S['AchievementsOut'];
export type Achievement = S['AchievementOut'];
export type JournalPage = S['JournalPage'];
export type JournalEvent = S['JournalEventOut'];
export type JournalScope = 'me' | 'shared';

export const ATTRIBUTES: readonly AttributeKey[] = [
  'physical',
  'intellectual',
  'discipline',
  'social',
  'creativity',
  'wellbeing',
];
export const STATS_PERIODS: readonly StatsPeriod[] = ['7d', '30d', 'all'];
export const BALANCE_PERIODS: readonly BalancePeriod[] = ['7d', '30d'];
export const MAX_WEEKLY_TARGET = 10_000;

export const STATS_KEY = ['stats'] as const;
export const LIFE_BALANCE_KEY = [...STATS_KEY, 'life-balance'] as const;
export const TARGETS_KEY = [...LIFE_BALANCE_KEY, 'targets'] as const;
export const ACHIEVEMENTS_KEY = ['achievements'] as const;
export const JOURNAL_KEY = ['journal'] as const;

const JOURNAL_PAGE_SIZE = 30;

/** GET /stats: counts, XP and quests per day, Gold earned/spent and rewards for a period. */
export function useStats(period: StatsPeriod) {
  const { api } = useAuth();
  return useQuery({
    queryKey: [...STATS_KEY, 'summary', period],
    queryFn: ({ signal }) => api.get<Stats>(`/stats?period=${period}`, { signal }),
  });
}

/** GET /stats/life-balance for me or my active companion. */
export function useLifeBalance(period: BalancePeriod, who: Who = 'me', enabled = true) {
  const { api } = useAuth();
  return useQuery({
    queryKey: [...LIFE_BALANCE_KEY, who, period],
    enabled,
    queryFn: ({ signal }) => api.get<LifeBalance>(`/stats/life-balance?period=${period}&user=${who}`, { signal }),
  });
}

export function useTargets(enabled = true) {
  const { api } = useAuth();
  return useQuery({
    queryKey: TARGETS_KEY,
    enabled,
    queryFn: ({ signal }) => api.get<Targets>('/stats/life-balance/targets', { signal }),
  });
}

/** PUT /stats/life-balance/targets: only my own weekly targets. */
export function useSetTargets() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (targets: Partial<Record<AttributeKey, number>>) =>
      api.request<Targets>('PUT', '/stats/life-balance/targets', { body: { targets } }),
    onSuccess: (data) => {
      queryClient.setQueryData(TARGETS_KEY, data);
      telegram.haptic.notification('success');
      return queryClient.invalidateQueries({ queryKey: [...LIFE_BALANCE_KEY, 'me'] });
    },
    onError: () => telegram.haptic.notification('error'),
  });
}

/** GET /achievements: every definition with my progress, plus my unlocks. */
export function useAchievements(options: { enabled?: boolean; refetchInterval?: number } = {}) {
  const { api } = useAuth();
  return useQuery({
    queryKey: ACHIEVEMENTS_KEY,
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval,
    queryFn: ({ signal }) => api.get<Achievements>('/achievements', { signal }),
  });
}

/** GET /journal: my events or our shared ones, newest first, a cursor page at a time. */
export function useJournal(scope: JournalScope) {
  const { api } = useAuth();
  return useInfiniteQuery({
    queryKey: [...JOURNAL_KEY, scope],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam, signal }) =>
      api.get<JournalPage>(
        `/journal?scope=${scope}&limit=${JOURNAL_PAGE_SIZE}${pageParam ? `&cursor=${pageParam}` : ''}`,
        { signal },
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}
