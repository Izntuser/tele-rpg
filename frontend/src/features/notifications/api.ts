import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';

type S = components['schemas'];
export type NotificationItem = S['NotificationOut'];
export type Inbox = S['InboxOut'];
export type Preferences = S['PreferencesOut'];
export type PreferencesUpdate = S['PreferencesUpdate'];
export type Category = NotificationItem['category'];

export const CATEGORIES: readonly Category[] = ['quests', 'reviews', 'rewards', 'reminders', 'summary'];

export const NOTIFICATIONS_KEY = ['notifications'] as const;
export const INBOX_KEY = [...NOTIFICATIONS_KEY, 'inbox'] as const;
export const UNREAD_KEY = [...NOTIFICATIONS_KEY, 'unread'] as const;
export const PREFERENCES_KEY = [...NOTIFICATIONS_KEY, 'preferences'] as const;

/** How often the bell asks for the unread count while the app is open. */
export const UNREAD_POLL_MS = 60_000;
const PAGE_SIZE = 30;

export function invalidateInbox(queryClient: QueryClient): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: INBOX_KEY }),
    queryClient.invalidateQueries({ queryKey: UNREAD_KEY }),
  ]);
}

/** The inbox, newest first, one cursor page at a time. */
export function useInbox() {
  const { api } = useAuth();
  return useInfiniteQuery({
    queryKey: INBOX_KEY,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam, signal }) =>
      api.get<Inbox>(`/notifications?limit=${PAGE_SIZE}${pageParam ? `&cursor=${pageParam}` : ''}`, { signal }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/** The header bell's badge. */
export function useUnreadCount(enabled = true) {
  const { api } = useAuth();
  return useQuery({
    queryKey: UNREAD_KEY,
    enabled,
    refetchInterval: UNREAD_POLL_MS,
    queryFn: ({ signal }) => api.get<{ count: number }>('/notifications/unread-count', { signal }),
    select: (data) => data.count,
  });
}

export function useMarkRead() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<NotificationItem>(`/notifications/${id}/read`),
    onSettled: () => invalidateInbox(queryClient),
  });
}

export function useMarkAllRead() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ updated: number }>('/notifications/read-all'),
    onSuccess: () => telegram.haptic.notification('success'),
    onSettled: () => invalidateInbox(queryClient),
  });
}

export function usePreferences() {
  const { api } = useAuth();
  return useQuery({
    queryKey: PREFERENCES_KEY,
    queryFn: ({ signal }) => api.get<Preferences>('/notifications/preferences', { signal }),
  });
}

export function useUpdatePreferences() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PreferencesUpdate) => api.patch<Preferences>('/notifications/preferences', body),
    onSuccess: (prefs) => {
      queryClient.setQueryData(PREFERENCES_KEY, prefs);
      telegram.haptic.notification('success');
    },
    onError: () => telegram.haptic.notification('error'),
  });
}

/** Ask Telegram to let the bot write to me, then record the answer (can_message). */
export function useEnableBotMessages() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const allowed = await telegram.requestWriteAccess();
      const prefs = await api.post<Preferences>('/notifications/write-access', { allowed });
      return { allowed, prefs };
    },
    onSuccess: ({ allowed, prefs }) => {
      queryClient.setQueryData(PREFERENCES_KEY, prefs);
      telegram.haptic.notification(allowed ? 'success' : 'warning');
    },
    onError: () => telegram.haptic.notification('error'),
  });
}
