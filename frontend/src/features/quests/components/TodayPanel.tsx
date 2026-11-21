import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { usePartnership } from '../../partnership/api';
import { bucketQuests, useQuestList, useTemplateList, type Occurrence, type Template } from '../api';
import { QuestCard } from './QuestCard';

const MAX_SHOWN = 3;

function Section({
  id,
  title,
  items,
}: {
  id: string;
  title: string;
  items: (Occurrence | Template)[];
}) {
  const { t } = useTranslation('quests');
  if (!items.length) return null;
  return (
    <section aria-labelledby={`today-${id}`} data-testid={`today-${id}`} className="flex flex-col gap-2">
      <h3 id={`today-${id}`} className="text-sm font-semibold text-muted">
        {title} ({items.length})
      </h3>
      {items.slice(0, MAX_SHOWN).map((q) => (
        <QuestCard key={`${'partnership_id' in q ? 't' : 'o'}${q.id}`} quest={q} />
      ))}
      {items.length > MAX_SHOWN ? (
        <Link to="/quests" className="text-sm text-accent">
          {t('today.more', { count: items.length - MAX_SHOWN })}
        </Link>
      ) : null}
    </section>
  );
}

/** Home: my active quests, quests offered to me, and quests waiting for my confirmation. */
export function TodayPanel() {
  const { t } = useTranslation('quests');
  const partnership = usePartnership();
  const paired = Boolean(partnership.data?.partnership);
  const quests = useQuestList();
  const templates = useTemplateList();
  if (!paired) return null;

  const buckets = quests.data && templates.data ? bucketQuests(quests.data, templates.data) : null;
  const empty = buckets && !buckets.active.length && !buckets.offers.length && !buckets.toConfirm.length;
  return (
    <section aria-labelledby="today-heading" data-testid="today-panel" className="flex flex-col gap-3">
      <h2 id="today-heading" className="text-lg font-semibold">
        {t('today.title')}
      </h2>
      {quests.isError || templates.isError ? (
        <p role="alert" className="text-sm">
          {t('error')}
        </p>
      ) : !buckets ? (
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {t('loading')}
        </p>
      ) : empty ? (
        <p className="text-sm text-muted">{t('today.empty')}</p>
      ) : (
        <>
          <Section id="active" title={t('today.active')} items={buckets.active} />
          <Section id="offers" title={t('today.offers')} items={buckets.offers} />
          <Section id="confirm" title={t('today.toConfirm')} items={buckets.toConfirm} />
        </>
      )}
    </section>
  );
}
