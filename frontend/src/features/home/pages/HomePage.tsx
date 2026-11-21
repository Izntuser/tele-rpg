import { useTranslation } from 'react-i18next';

import { UserGreeting } from '../../auth/UserGreeting';

export function HomePage() {
  const { t } = useTranslation();
  return (
    <section data-testid="page-home" className="flex flex-col items-center gap-2 p-6 pt-16 text-center">
      <h1 className="text-3xl font-bold">{t('app.title')}</h1>
      <UserGreeting />
      <p className="text-sm text-muted">{t('pages.home')}</p>
    </section>
  );
}
