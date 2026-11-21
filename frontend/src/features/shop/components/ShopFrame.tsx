import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router';

import { GoldBadge } from '../../../components/game/GoldBadge';
import { EmptyState } from '../../../components/ui/EmptyState';
import { cn } from '../../../components/ui/cn';
import { useCharacter } from '../../character/api';
import { usePartnership } from '../../partnership/api';
import { InvitePanel } from '../../partnership/InvitePanel';

const TABS = [
  { id: 'shop', to: '/shop', end: true },
  { id: 'inventory', to: '/shop/inventory', end: false },
  { id: 'manage', to: '/shop/manage', end: false },
] as const;

/**
 * The shared frame of the three shop screens: title, my balance, the screen switcher, and the
 * invite CTA instead of the content while I have no companion.
 */
export function ShopFrame({
  testId,
  title,
  children,
}: {
  testId: string;
  title: string;
  children: ReactNode;
}) {
  const { t } = useTranslation('shop');
  const partnership = usePartnership();
  const character = useCharacter();
  const unpaired = Boolean(partnership.data) && !partnership.data?.partnership;

  return (
    <section data-testid={testId} className="flex flex-col gap-4 p-4">
      <header className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">{title}</h1>
        {character.data ? (
          <span data-testid="shop-balance" className="flex items-center gap-1 text-sm text-muted">
            {t('balance')}
            <GoldBadge amount={character.data.gold} />
          </span>
        ) : null}
      </header>
      <nav aria-label={t('nav.label')} className="flex gap-2">
        {TABS.map((tab) => (
          <NavLink
            key={tab.id}
            to={tab.to}
            end={tab.end}
            data-testid={`shop-nav-${tab.id}`}
            className={({ isActive }) =>
              cn(
                'rounded-full border px-3 py-1 text-sm',
                isActive ? 'border-accent bg-accent text-accent-fg' : 'border-border',
              )
            }
          >
            {t(`nav.${tab.id}`)}
          </NavLink>
        ))}
      </nav>
      {unpaired ? (
        <>
          <EmptyState title={t('unpaired.title')} description={t('unpaired.hint')} />
          <InvitePanel />
        </>
      ) : partnership.isError ? (
        <p role="alert" className="text-sm">
          {t('error')}
        </p>
      ) : (
        partnership.data ? children : null
      )}
    </section>
  );
}

export function LoadError({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation('shop');
  return (
    <div className="flex flex-col items-start gap-2">
      <p role="alert" className="text-sm">
        {t('error')}
      </p>
      <button type="button" onClick={onRetry} className="rounded-md border border-border px-3 py-1 text-sm">
        {t('retry')}
      </button>
    </div>
  );
}

/** A date and time in the viewer's language. */
export function useFormatDate(): (iso: string) => string {
  const { i18n } = useTranslation();
  return (iso) =>
    new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));
}
