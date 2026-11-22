import { BookOpen } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { EmptyState } from '../../components/ui/EmptyState';
import { cn } from '../../components/ui/cn';
import { useJournal, type JournalEvent, type JournalScope } from '../stats/api';
import { journalLink, journalText } from './text';

const SCOPES: readonly JournalScope[] = ['me', 'shared'];

function useWhen() {
  const { i18n } = useTranslation();
  const format = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' });
  return (iso: string) => format.format(new Date(iso));
}

function Entry({ event }: { event: JournalEvent }) {
  const { t } = useTranslation('stats');
  const when = useWhen();
  const link = journalLink(event);
  const body = (
    <span className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="break-words text-sm">{journalText(t, event)}</span>
      <span className="flex items-center gap-2 text-xs text-muted">
        <span
          className={cn(
            'rounded-full border px-2 py-0.5',
            event.actor === 'me' ? 'border-accent text-accent' : 'border-gm text-gm',
          )}
        >
          {t(`journal.actor.${event.actor}`)}
        </span>
        <time dateTime={event.created_at}>{when(event.created_at)}</time>
      </span>
    </span>
  );
  const className = 'flex w-full items-start gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-left';
  return (
    <li data-testid="journal-event" data-type={event.type} data-actor={event.actor}>
      {link ? (
        <Link to={link} className={cn(className, 'focus-visible:outline focus-visible:outline-2')}>
          {body}
        </Link>
      ) : (
        <div className={className}>{body}</div>
      )}
    </li>
  );
}

/** The Adventure Journal: my own events or our shared ones, newest first. */
export function JournalPage() {
  const { t } = useTranslation('stats');
  const [scope, setScope] = useState<JournalScope>('me');
  const journal = useJournal(scope);
  const items = journal.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <section data-testid="page-journal" className="flex flex-col gap-4 p-4">
      <h1 className="text-2xl font-bold">{t('journal.title')}</h1>
      <div role="tablist" aria-label={t('journal.scopeLabel')} className="inline-flex self-start rounded-lg border border-border p-0.5">
        {SCOPES.map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={s === scope}
            data-testid={`journal-scope-${s}`}
            onClick={() => setScope(s)}
            className={cn(
              'rounded-md px-4 py-1.5 text-sm font-semibold focus-visible:outline focus-visible:outline-2',
              s === scope ? 'bg-accent text-accent-fg' : 'text-muted',
            )}
          >
            {t(`journal.scope.${s}`)}
          </button>
        ))}
      </div>

      {journal.isPending ? (
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {t('journal.loading')}
        </p>
      ) : journal.isError ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm">
            {t('journal.error')}
          </p>
          <button type="button" onClick={() => void journal.refetch()} className="rounded-md border border-border px-3 py-1 text-sm">
            {t('journal.retry')}
          </button>
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon={<BookOpen size={32} />} title={t('journal.empty')} description={t('journal.emptyHint')} />
      ) : (
        <>
          <ul data-testid="journal-list" className="flex flex-col gap-2">
            {items.map((event) => (
              <Entry key={event.id} event={event} />
            ))}
          </ul>
          {journal.hasNextPage ? (
            <button
              type="button"
              data-testid="journal-more"
              disabled={journal.isFetchingNextPage}
              onClick={() => void journal.fetchNextPage()}
              className="self-center rounded-md border border-border px-4 py-2 text-sm disabled:opacity-50"
            >
              {t('journal.loadMore')}
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}
