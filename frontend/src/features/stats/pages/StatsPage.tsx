import { BookOpen, Target } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { useCharacter, type Character } from '../../character/api';
import { AchievementsSection } from '../AchievementsSection';
import { STATS_PERIODS, useStats, type Stats, type StatsPeriod } from '../api';
import { DailyBars } from '../charts';
import { LifeBalanceCard } from '../LifeBalanceCard';
import { PeriodSwitch } from '../PeriodSwitch';
import { TargetsSheet } from '../TargetsSheet';

function Tile({ label, value, testId, tone }: { label: string; value: number; testId: string; tone?: 'gold' | 'xp' }) {
  return (
    <div data-testid={testId} className="flex flex-col gap-0.5 rounded-xl border border-border bg-surface px-3 py-2">
      <span className="text-xs text-muted">{label}</span>
      <span className={tone === 'gold' ? 'text-lg font-bold text-gold' : tone === 'xp' ? 'text-lg font-bold text-xp' : 'text-lg font-bold'}>
        {value.toLocaleString()}
      </span>
    </div>
  );
}

function Summary({ stats }: { stats: Stats }) {
  const { t } = useTranslation('stats');
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-2" data-testid="stats-summary">
        <Tile testId="stat-quests" label={t('summary.questsCompleted')} value={stats.quests_completed} />
        <Tile testId="stat-xp" label={t('summary.xpPeriod')} value={stats.xp_period} tone="xp" />
        <Tile testId="stat-gold-earned" label={t('summary.goldEarned')} value={stats.gold_earned} tone="gold" />
        <Tile testId="stat-quests-week" label={t('summary.questsWeek')} value={stats.quests_completed_week} />
        <Tile testId="stat-quests-month" label={t('summary.questsMonth')} value={stats.quests_completed_month} />
        <Tile testId="stat-quests-total" label={t('summary.questsTotal')} value={stats.quests_completed_total} />
        <Tile testId="stat-xp-total" label={t('summary.xpTotal')} value={stats.xp_total} />
        <Tile testId="stat-gold-earned-total" label={t('summary.goldEarnedTotal')} value={stats.gold_earned_total} />
        <Tile testId="stat-gold-spent" label={t('summary.goldSpent')} value={stats.gold_spent} />
        <Tile testId="stat-gold-balance" label={t('summary.goldBalance')} value={stats.gold_balance} tone="gold" />
        <Tile testId="stat-rewards-purchased" label={t('summary.rewardsPurchased')} value={stats.rewards_purchased} />
        <Tile testId="stat-rewards-fulfilled" label={t('summary.rewardsFulfilled')} value={stats.rewards_fulfilled} />
      </div>
      <DailyBars testId="chart-xp" title={t('charts.xpPerDay')} days={stats.xp_per_day} />
      <DailyBars testId="chart-quests" title={t('charts.questsPerDay')} days={stats.quests_per_day} />
    </div>
  );
}

function AttributeProgress({ character }: { character: Character }) {
  const { t } = useTranslation('stats');
  return (
    <section aria-labelledby="attribute-progress-title" className="flex flex-col gap-2">
      <h2 id="attribute-progress-title" className="text-lg font-bold">
        {t('attributes.title')}
      </h2>
      <ul className="flex flex-col gap-2" data-testid="attribute-progress">
        {character.attributes.map((a) => {
          const name = t(`common:game.attribute.${a.attribute}`);
          const pct = a.xp_for_next_level > 0 ? Math.min(100, Math.round((a.xp_into_level / a.xp_for_next_level) * 100)) : 0;
          return (
            <li key={a.attribute} className="flex flex-col gap-1">
              <span className="flex justify-between text-sm">
                <span>{name}</span>
                <span className="font-semibold">{t('attributes.level', { level: a.level })}</span>
              </span>
              <div
                role="progressbar"
                aria-label={name}
                aria-valuetext={t('attributes.progress', { current: a.xp_into_level, max: a.xp_for_next_level })}
                aria-valuemin={0}
                aria-valuemax={a.xp_for_next_level}
                aria-valuenow={Math.min(a.xp_into_level, a.xp_for_next_level)}
                className="h-2 overflow-hidden rounded-full bg-surface-2"
              >
                <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** /stats: my summary and charts per period, attribute progress, Life Balance (with my
 * targets) and achievements. */
export function StatsPage() {
  const { t } = useTranslation('stats');
  const [period, setPeriod] = useState<StatsPeriod>('7d');
  const [editing, setEditing] = useState(false);
  const stats = useStats(period);
  const character = useCharacter();

  return (
    <section data-testid="page-stats" className="flex flex-col gap-6 p-4">
      <header className="flex items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">{t('title')}</h1>
        <Link
          to="/stats/journal"
          data-testid="stats-journal-link"
          className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm"
        >
          <BookOpen aria-hidden="true" size={16} />
          {t('journalLink')}
        </Link>
      </header>

      <section aria-labelledby="summary-title" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="summary-title" className="text-lg font-bold">
            {t('summary.title')}
          </h2>
          <PeriodSwitch value={period} options={STATS_PERIODS} onChange={setPeriod} testId="stats-period" />
        </div>
        {stats.data ? (
          <Summary stats={stats.data} />
        ) : stats.isError ? (
          <div className="flex flex-col items-start gap-2">
            <p role="alert" className="text-sm">
              {t('error')}
            </p>
            <button type="button" onClick={() => void stats.refetch()} className="rounded-md border border-border px-3 py-1 text-sm">
              {t('retry')}
            </button>
          </div>
        ) : (
          <p role="status" aria-live="polite" className="text-sm text-muted">
            {t('loading')}
          </p>
        )}
      </section>

      <LifeBalanceCard
        who="me"
        title={t('balance.title')}
        hint={t('balance.hint')}
        headerAction={
          <button
            type="button"
            data-testid="targets-edit"
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-1 self-start rounded-md border border-border px-3 py-1.5 text-sm"
          >
            <Target aria-hidden="true" size={16} />
            {t('balance.editTargets')}
          </button>
        }
      />
      <TargetsSheet open={editing} onClose={() => setEditing(false)} />

      {character.data ? <AttributeProgress character={character.data} /> : null}

      <AchievementsSection />
    </section>
  );
}
