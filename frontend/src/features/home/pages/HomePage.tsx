import { ChevronRight, Gift, Target } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { UserGreeting } from '../../auth/UserGreeting';
import { useCharacter } from '../../character/api';
import { AttributeGrid, CharacterHeader } from '../../character/CharacterHeader';
import { TodayPanel } from '../../quests/components/TodayPanel';

function QuickLink({ to, icon, label, testId }: { to: string; icon: ReactNode; label: string; testId: string }) {
  return (
    <Link
      to={to}
      data-testid={testId}
      className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3 focus-visible:outline focus-visible:outline-2"
    >
      <span aria-hidden="true" className="text-accent">
        {icon}
      </span>
      <span className="flex-1 font-medium">{label}</span>
      <ChevronRight aria-hidden="true" size={18} className="text-muted" />
    </Link>
  );
}

export function HomePage() {
  const { t } = useTranslation();
  const { t: tp } = useTranslation('profile');
  const character = useCharacter();

  return (
    <section data-testid="page-home" className="flex flex-col gap-4 p-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-muted">{t('app.title')}</h1>
        <UserGreeting />
      </header>

      {character.data ? (
        <>
          <CharacterHeader character={character.data} />
          <AttributeGrid character={character.data} />
        </>
      ) : character.isError ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm">
            {tp('character.error')}
          </p>
          <button
            type="button"
            onClick={() => void character.refetch()}
            className="rounded-md border border-border px-3 py-1 text-sm"
          >
            {tp('character.retry')}
          </button>
        </div>
      ) : (
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {tp('character.loading')}
        </p>
      )}

      <TodayPanel />

      <div className="flex flex-col gap-2">
        <QuickLink to="/me/goals" testId="home-goals-link" icon={<Target size={20} />} label={tp('home.goals')} />
        <QuickLink to="/me/wishlist" testId="home-wishlist-link" icon={<Gift size={20} />} label={tp('home.wishlist')} />
      </div>
    </section>
  );
}
