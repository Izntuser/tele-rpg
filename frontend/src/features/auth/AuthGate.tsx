import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { useAuth } from './context';

function Centered({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center">
      {children}
    </main>
  );
}

/** Renders children only once the user is signed in; otherwise a status screen. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const { t } = useTranslation();
  switch (state.status) {
    case 'authenticated':
      return <>{children}</>;
    case 'loading':
      return (
        <Centered>
          <p role="status" aria-live="polite" className="text-sm opacity-70">
            {t('auth.signingIn')}
          </p>
        </Centered>
      );
    case 'no-telegram':
      return (
        <Centered>
          <h1 className="text-2xl font-bold">{t('app.title')}</h1>
          <p className="text-sm opacity-70">{t('auth.openFromTelegram')}</p>
        </Centered>
      );
    case 'error':
      return (
        <Centered>
          <p role="alert" className="text-sm">
            {state.message}
          </p>
          <button
            type="button"
            onClick={state.retry}
            className="rounded-md border px-4 py-2 text-sm focus-visible:outline focus-visible:outline-2"
          >
            {t('auth.retry')}
          </button>
        </Centered>
      );
  }
}
