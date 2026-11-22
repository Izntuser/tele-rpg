import { Bell } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { useUnreadCount } from './api';

/** Header bell: links to the inbox and shows how many notifications are unread. */
export function NotificationBell() {
  const { t } = useTranslation('notifications');
  const unread = useUnreadCount();
  const count = unread.data ?? 0;
  return (
    <Link
      to="/notifications"
      data-testid="notification-bell"
      data-unread={count}
      aria-label={count > 0 ? t('bellUnread', { count }) : t('bell')}
      className="relative inline-flex h-10 w-10 items-center justify-center rounded-full text-fg focus-visible:outline focus-visible:outline-2"
    >
      <Bell aria-hidden="true" size={22} />
      {count > 0 ? (
        <span
          data-testid="notification-badge"
          aria-hidden="true"
          className="absolute right-0.5 top-0.5 min-w-5 rounded-full bg-danger px-1 text-center text-xs font-bold leading-5 text-white"
        >
          {count > 99 ? '99+' : count}
        </span>
      ) : null}
    </Link>
  );
}
