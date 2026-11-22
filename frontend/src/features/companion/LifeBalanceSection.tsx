import { Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { LifeBalanceCard } from '../stats/LifeBalanceCard';

/** The companion's recent activity radar with encouraging, optional quest ideas. */
export function LifeBalanceSection() {
  const { t } = useTranslation('stats');
  return (
    <LifeBalanceCard
      who="companion"
      testId="companion-life-balance"
      title={t('balance.companionTitle')}
      hint={t('balance.companionHint')}
      suggestionAction={
        <Link
          to="/quests/new"
          data-testid="suggestion-create-quest"
          className="inline-flex items-center gap-1 self-start rounded-md border border-gm px-3 py-1.5 text-sm font-semibold text-gm"
        >
          <Plus aria-hidden="true" size={16} />
          {t('balance.createQuest')}
        </Link>
      }
    />
  );
}
