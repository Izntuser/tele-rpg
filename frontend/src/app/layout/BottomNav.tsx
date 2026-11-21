import { Home, ScrollText, ShoppingBag, Swords, Users } from 'lucide-react';
import type { ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router';

import { cn } from '../../components/ui/cn';

const TABS: { to: string; key: string; icon: ComponentType<{ size?: number }>; end?: boolean }[] = [
  { to: '/', key: 'home', icon: Home, end: true },
  { to: '/quests', key: 'quests', icon: ScrollText },
  { to: '/shop', key: 'shop', icon: ShoppingBag },
  { to: '/stats', key: 'stats', icon: Swords },
  { to: '/companion', key: 'companion', icon: Users },
];

export function BottomNav() {
  const { t } = useTranslation();
  return (
    <nav
      aria-label={t('nav.label')}
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface pb-[var(--safe-bottom)]"
    >
      <ul className="mx-auto flex max-w-md">
        {TABS.map(({ to, key, icon: Icon, end }) => (
          <li key={key} className="flex-1">
            <NavLink
              to={to}
              end={end}
              data-testid={`nav-${key}`}
              className={({ isActive }) =>
                cn(
                  'flex h-[var(--nav-height)] flex-col items-center justify-center gap-0.5 text-xs',
                  isActive ? 'font-semibold text-accent' : 'text-muted',
                )
              }
            >
              <Icon size={20} />
              <span>{t(`nav.${key}`)}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
