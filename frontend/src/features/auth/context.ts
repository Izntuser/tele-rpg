import { createContext, useContext } from 'react';

import type { ApiClient, User } from '../../lib/api/client';
import type { TelegramAdapter } from '../../lib/telegram';

export type AuthState =
  | { status: 'loading' }
  | { status: 'no-telegram' }
  | { status: 'error'; message: string; retry: () => void }
  | { status: 'authenticated'; user: User; startParam: string | null };

export interface AuthContextValue {
  state: AuthState;
  api: ApiClient;
  telegram: TelegramAdapter;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}

/** The signed-in user; only valid below <AuthGate>. */
export function useCurrentUser(): User {
  const { state } = useAuth();
  if (state.status !== 'authenticated') throw new Error('useCurrentUser needs <AuthGate>');
  return state.user;
}
