import { useEffect } from 'react';
import { TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useRouteError } from 'react-router';

/**
 * Root route `errorElement`: a render error shows this instead of React Router's default
 * (developer) error page. Reload restarts the Mini App; the cause goes to the console only.
 */
export function RouteError() {
  const { t } = useTranslation();
  const error = useRouteError();
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <section
      role="alert"
      data-testid="route-error"
      className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center"
    >
      <TriangleAlert aria-hidden="true" size={40} className="text-danger" />
      <h1 className="text-xl font-bold">{t('error.title')}</h1>
      <p className="max-w-xs text-sm text-muted">{t('error.hint')}</p>
      <button
        type="button"
        data-testid="route-error-reload"
        onClick={() => window.location.reload()}
        className="rounded-md border border-border px-4 py-2 text-sm font-semibold"
      >
        {t('error.reload')}
      </button>
    </section>
  );
}
