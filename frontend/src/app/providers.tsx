import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';

import { AuthProvider } from '../features/auth/AuthProvider';
import { api as defaultApi, type ApiClient } from '../lib/api/client';
import { getTelegram, type TelegramAdapter } from '../lib/telegram';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, refetchOnWindowFocus: false },
    },
  });
}

/** App-wide providers: TanStack Query, the Telegram adapter and the auth session. */
export function Providers({
  children,
  api = defaultApi,
  telegram,
  queryClient,
}: {
  children: ReactNode;
  api?: ApiClient;
  telegram?: TelegramAdapter;
  queryClient?: QueryClient;
}) {
  const [client] = useState(() => queryClient ?? createQueryClient());
  const [adapter] = useState(() => telegram ?? getTelegram());

  useEffect(() => {
    adapter.ready();
  }, [adapter]);

  return (
    <QueryClientProvider client={client}>
      <AuthProvider api={api} telegram={adapter}>
        {children}
      </AuthProvider>
    </QueryClientProvider>
  );
}
