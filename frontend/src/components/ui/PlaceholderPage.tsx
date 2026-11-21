import { useTranslation } from 'react-i18next';

import { EmptyState } from './EmptyState';

/** Stand-in body for a route whose real screen lands in a later stage. */
export function PlaceholderPage({ titleKey, testId }: { titleKey: string; testId: string }) {
  const { t } = useTranslation();
  return (
    <section data-testid={testId} className="flex flex-col gap-2 p-4">
      <h1 className="text-2xl font-bold">{t(titleKey)}</h1>
      <EmptyState title={t('pages.placeholder')} />
    </section>
  );
}
