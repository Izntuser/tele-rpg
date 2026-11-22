import { Bell, CheckCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';

import { EmptyState } from '../../../components/ui/EmptyState';
import { cn } from '../../../components/ui/cn';
import { deeplinkToRoute } from '../../../lib/deeplink';
import { useAuth } from '../../auth/context';
import { useInbox, useMarkAllRead, useMarkRead, type NotificationItem } from '../api';
import { notificationText } from '../text';

function useWhen() {
  const { i18n } = useTranslation();
  const format = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' });
  return (iso: string) => format.format(new Date(iso));
}

function Item({ item, onOpen }: { item: NotificationItem; onOpen: (item: NotificationItem) => void }) {
  const { t } = useTranslation('notifications');
  const when = useWhen();
  const unread = item.read_at === null;
  return (
    <li>
      <button
        type="button"
        data-testid="notification-item"
        data-type={item.type}
        data-unread={unread}
        onClick={() => onOpen(item)}
        className={cn(
          'flex w-full items-start gap-3 rounded-xl border px-4 py-3 text-left focus-visible:outline focus-visible:outline-2',
          unread ? 'border-accent bg-surface' : 'border-border bg-bg',
        )}
      >
        <span
          aria-hidden="true"
          className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', unread ? 'bg-accent' : 'bg-transparent')}
        />
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className={cn('break-words text-sm', unread && 'font-semibold')}>
            {notificationText(t, item)}
          </span>
          <span className="text-xs text-muted">
            <time dateTime={item.created_at}>{when(item.created_at)}</time>
            {unread ? <span className="sr-only">, {t('unread')}</span> : null}
          </span>
        </span>
      </button>
    </li>
  );
}

/** The inbox: newest first, tap to open the screen it is about (and mark it read). */
export function NotificationsPage() {
  const { t } = useTranslation('notifications');
  const { telegram } = useAuth();
  const navigate = useNavigate();
  const inbox = useInbox();
  const markRead = useMarkRead();
  const markAllRead = useMarkAllRead();
  const items = inbox.data?.pages.flatMap((page) => page.items) ?? [];
  const unreadCount = inbox.data?.pages[0]?.unread_count ?? 0;

  const open = (item: NotificationItem) => {
    telegram.haptic.selection();
    if (item.read_at === null) markRead.mutate(item.id);
    void navigate(deeplinkToRoute(item.deep_link));
  };

  return (
    <section data-testid="page-notifications" className="flex flex-col gap-4 p-4">
      <header className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">{t('title')}</h1>
        {unreadCount > 0 ? (
          <button
            type="button"
            data-testid="notifications-read-all"
            disabled={markAllRead.isPending}
            onClick={() => markAllRead.mutate()}
            className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            <CheckCheck aria-hidden="true" size={16} />
            {t('markAllRead')}
          </button>
        ) : null}
      </header>

      {inbox.isPending ? (
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {t('loading')}
        </p>
      ) : inbox.isError ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm">
            {t('error')}
          </p>
          <button
            type="button"
            onClick={() => void inbox.refetch()}
            className="rounded-md border border-border px-3 py-1 text-sm"
          >
            {t('retry')}
          </button>
        </div>
      ) : items.length === 0 ? (
        <EmptyState icon={<Bell size={32} />} title={t('empty')} description={t('emptyHint')} />
      ) : (
        <>
          <ul data-testid="notification-list" className="flex flex-col gap-2">
            {items.map((item) => (
              <Item key={item.id} item={item} onOpen={open} />
            ))}
          </ul>
          {inbox.hasNextPage ? (
            <button
              type="button"
              data-testid="notifications-more"
              disabled={inbox.isFetchingNextPage}
              onClick={() => void inbox.fetchNextPage()}
              className="self-center rounded-md border border-border px-4 py-2 text-sm disabled:opacity-50"
            >
              {t('loadMore')}
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}
