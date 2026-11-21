import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { ApiError, type ApiClient, type AuthResponse } from '../../lib/api/client';
import type { components } from '../../lib/api/schema';
import { AUTH_QUERY_KEY } from '../auth/AuthProvider';
import { useAuth } from '../auth/context';
import { CHARACTER_QUERY_KEY, type Character } from '../character/api';

type CharacterUpdate = components['schemas']['CharacterUpdate'];

export const DELETE_CONFIRM_TEXT = 'DELETE';

/** PATCH /character for locale/timezone; the session user is updated too, so the UI language
 * (AppLayout reads user.locale) switches right away. */
export function useUpdatePreferences() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Pick<CharacterUpdate, 'locale' | 'timezone'>) => api.patch<Character>('/character', body),
    onSuccess: (character) => {
      queryClient.setQueryData(CHARACTER_QUERY_KEY, character);
      queryClient.setQueryData<AuthResponse>(AUTH_QUERY_KEY, (old) =>
        old ? { ...old, user: { ...old.user, locale: character.locale, timezone: character.timezone } } : old,
      );
    },
  });
}

/** Downloads GET /account/export as a JSON file. */
export function useExportData() {
  const { api } = useAuth();
  return useMutation({
    mutationFn: async () => {
      const data = await api.get<unknown>('/account/export');
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      if (typeof URL.createObjectURL !== 'function') return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'tele-rpg-export.json';
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
}

/**
 * After a deletion the session must end here: drop the JWT and every cached query, and put the
 * session query into a "deleted" error state. Otherwise the next 401 would silently log in
 * again and create a fresh account; the AuthGate retry button does that only on purpose.
 */
export function endDeletedSession(queryClient: QueryClient, api: ApiClient): void {
  api.logout();
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== AUTH_QUERY_KEY[0] });
  const session = queryClient.getQueryCache().find({ queryKey: AUTH_QUERY_KEY });
  session?.setState({
    status: 'error',
    data: undefined,
    error: new ApiError(403, 'Account deleted'),
    fetchStatus: 'idle',
  });
}

export function useDeleteAccount() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.request<void>('DELETE', '/account', { body: { confirm_text: DELETE_CONFIRM_TEXT } }),
    onSuccess: () => endDeletedSession(queryClient, api),
  });
}
