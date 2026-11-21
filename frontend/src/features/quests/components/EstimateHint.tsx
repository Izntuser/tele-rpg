import { useTranslation } from 'react-i18next';

import { useEstimate, type Recurrence } from '../api';

/** Inflation guidance for a recurring quest: the most Gold it can mint a week and a month. */
export function EstimateHint({ gold, recurrence }: { gold: number; recurrence: Recurrence }) {
  const { t } = useTranslation('quests');
  const estimate = useEstimate(gold, recurrence, recurrence !== 'once');
  if (recurrence === 'once') return null;
  return (
    <div data-testid="quest-estimate" className="rounded-md border border-gold px-3 py-2 text-sm" aria-live="polite">
      <p className="font-semibold text-gold">{t('estimate.title')}</p>
      {estimate.data ? (
        <p>
          {t('estimate.body', { weekly: estimate.data.weekly, monthly: estimate.data.monthly })}
        </p>
      ) : estimate.isError ? (
        <p className="text-muted">{t('estimate.error')}</p>
      ) : (
        <p className="text-muted">{t('estimate.loading')}</p>
      )}
    </div>
  );
}
