import { Repeat } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { AttributeChip, DifficultyChip } from '../../../components/game/chips';
import { GoldBadge } from '../../../components/game/GoldBadge';
import type { Recurrence, Terms } from '../api';

/** The agreed terms of a quest (or a proposed revision of them). */
export function TermsCard({
  terms,
  recurrence,
  testId = 'quest-terms',
}: {
  terms: Terms;
  recurrence: Recurrence;
  testId?: string;
}) {
  const { t, i18n } = useTranslation('quests');
  return (
    <div data-testid={testId} className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4">
      <h2 className="break-words text-xl font-bold">{terms.title}</h2>
      {terms.description ? <p className="whitespace-pre-line text-sm">{terms.description}</p> : null}
      <div className="flex flex-wrap items-center gap-2">
        <AttributeChip attribute={terms.attribute} />
        <DifficultyChip difficulty={terms.difficulty} />
        <GoldBadge amount={terms.gold} />
        <span className="text-sm text-muted">{t('xp', { amount: terms.xp })}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted">{t('terms.recurrence')}</dt>
        <dd className="inline-flex items-center gap-1">
          {recurrence !== 'once' ? <Repeat aria-hidden="true" size={12} /> : null}
          {t(`recurrence.${recurrence}`)}
        </dd>
        <dt className="text-muted">{t('terms.confirmation')}</dt>
        <dd>{t(`confirmation.${terms.confirmation}`)}</dd>
        <dt className="text-muted">{t('terms.photo')}</dt>
        <dd>{terms.photo_required ? t('terms.photoRequired') : t('terms.photoOptional')}</dd>
        {terms.deadline ? (
          <>
            <dt className="text-muted">{t('terms.deadline')}</dt>
            <dd>
              {new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(
                new Date(terms.deadline),
              )}
            </dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}
