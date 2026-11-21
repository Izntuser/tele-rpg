import { useQuery } from '@tanstack/react-query';
import { useMemo, type ReactNode } from 'react';

import { ApiError, NoInitDataError, type ApiClient } from '../../lib/api/client';
import type { TelegramAdapter } from '../../lib/telegram';
import { AuthContext, type AuthState } from './context';

export const AUTH_QUERY_KEY = ['auth', 'session'] as const;

function describe(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return 'Telegram sign-in was rejected. Please reopen the app from Telegram.';
  }
  if (error instanceof ApiError && error.status === 403) {
    return 'This account has been deleted.';
  }
  if (error instanceof ApiError && error.status === 429) {
    return 'Too many attempts. Please wait a moment and try again.';
  }
  return 'Could not sign in. Check your connection and try again.';
}

/** Logs in with Telegram initData once on start and exposes the session via useAuth(). */
export function AuthProvider({
  api,
  telegram,
  children,
}: {
  api: ApiClient;
  telegram: TelegramAdapter;
  children: ReactNode;
}) {
  const hasInitData = telegram.getInitData() !== '';
  const session = useQuery({
    queryKey: AUTH_QUERY_KEY,
    queryFn: () => api.login(),
    enabled: hasInitData,
    retry: (count, error) =>
      count < 1 && !(error instanceof NoInitDataError) && !(error instanceof ApiError),
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const { data, error, refetch } = session;
  const state: AuthState = useMemo(() => {
    if (!hasInitData) return { status: 'no-telegram' };
    if (data) return { status: 'authenticated', user: data.user, startParam: data.start_param };
    if (error) return { status: 'error', message: describe(error), retry: () => void refetch() };
    return { status: 'loading' };
  }, [hasInitData, data, error, refetch]);

  const value = useMemo(() => ({ state, api, telegram }), [state, api, telegram]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
