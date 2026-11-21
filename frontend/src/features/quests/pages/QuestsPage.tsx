import { Plus } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate } from 'react-router';

import { EmptyState } from '../../../components/ui/EmptyState';
import { cn } from '../../../components/ui/cn';
import { usePartnership } from '../../partnership/api';
import { InvitePanel } from '../../partnership/InvitePanel';
import { CreateQuestSheet, EMPTY_FORM, type QuestForm } from '../CreateQuestSheet';
import { bucketQuests, questPath, useQuestList, useTemplateList, type QuestBuckets } from '../api';
import { QuestCard } from '../components/QuestCard';
import { RecurringTab } from '../components/RecurringTab';

const TABS = ['active', 'offers', 'recurring', 'assigned', 'toConfirm', 'completed'] as const;
type Tab = (typeof TABS)[number];

function isForm(value: unknown): value is QuestForm {
  return typeof value === 'object' && value !== null && 'title' in value && 'gold' in value;
}

/**
 * Six tabs over my partnership's quests. `creating` (the /quests/new route) opens the create
 * sheet over the list; a duplicated quest arrives as router state.
 */
export function QuestsPage({ creating = false }: { creating?: boolean }) {
  const { t } = useTranslation('quests');
  const navigate = useNavigate();
  const location = useLocation();
  const partnership = usePartnership();
  const paired = Boolean(partnership.data?.partnership);
  const quests = useQuestList();
  const templates = useTemplateList();
  const [tab, setTab] = useState<Tab>('active');
  const prefill = (location.state as { prefill?: unknown } | null)?.prefill;

  const buckets: QuestBuckets | null =
    quests.data && templates.data ? bucketQuests(quests.data, templates.data) : null;
  const failed = partnership.isError || quests.isError || templates.isError;
  const items = buckets ? buckets[tab] : [];

  return (
    <section data-testid="page-quests" className="flex flex-col gap-4 p-4">
      <h1 className="text-2xl font-bold">{t('title')}</h1>
      {partnership.data && !paired ? (
        <>
          <EmptyState title={t('unpaired.title')} description={t('unpaired.hint')} />
          <InvitePanel />
        </>
      ) : failed ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm">
            {t('error')}
          </p>
          <button
            type="button"
            onClick={() => {
              void partnership.refetch();
              void quests.refetch();
              void templates.refetch();
            }}
            className="rounded-md border border-border px-3 py-1 text-sm"
          >
            {t('retry')}
          </button>
        </div>
      ) : (
        <>
          <div
            role="tablist"
            aria-label={t('tabsLabel')}
            className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1"
          >
            {TABS.map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                id={`quest-tab-${id}`}
                data-testid={`quest-tab-${id}`}
                aria-selected={tab === id}
                aria-controls="quest-tabpanel"
                onClick={() => setTab(id)}
                className={cn(
                  'shrink-0 rounded-full border px-3 py-1 text-sm',
                  tab === id ? 'border-accent bg-accent text-accent-fg' : 'border-border',
                )}
              >
                {t(`tabs.${id}`)}
                {buckets && id !== 'completed' && buckets[id].length ? ` (${buckets[id].length})` : ''}
              </button>
            ))}
          </div>
          <div
            role="tabpanel"
            id="quest-tabpanel"
            aria-labelledby={`quest-tab-${tab}`}
            data-testid="quest-list"
            className="flex flex-col gap-2"
          >
            {!buckets ? (
              <p role="status" aria-live="polite" className="text-sm text-muted">
                {t('loading')}
              </p>
            ) : tab === 'recurring' ? (
              <RecurringTab templates={buckets.recurring} />
            ) : items.length ? (
              items.map((q) => <QuestCard key={`${'partnership_id' in q ? 't' : 'o'}${q.id}`} quest={q} />)
            ) : (
              <EmptyState title={t(`empty.${tab}`)} />
            )}
          </div>
        </>
      )}

      {paired ? (
        <Link
          to="/quests/new"
          data-testid="quest-fab"
          className="fixed right-4 z-30 inline-flex items-center gap-2 rounded-full bg-gm px-4 py-3 text-sm font-semibold text-bg shadow-lg"
          style={{ bottom: 'calc(var(--nav-height) + var(--safe-bottom) + 1rem)' }}
        >
          <Plus aria-hidden="true" size={18} />
          {t('newQuest')}
        </Link>
      ) : null}

      <CreateQuestSheet
        open={creating && paired}
        initial={isForm(prefill) ? prefill : EMPTY_FORM}
        onClose={() => void navigate('/quests', { replace: true })}
        onCreated={({ template, occurrence }) =>
          void navigate(
            questPath(occurrence ? { kind: 'occurrence', id: occurrence.id } : { kind: 'template', id: template.id }),
            { replace: true },
          )
        }
      />
    </section>
  );
}
