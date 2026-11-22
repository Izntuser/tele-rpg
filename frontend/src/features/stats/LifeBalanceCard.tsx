import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { BALANCE_PERIODS, useLifeBalance, type BalancePeriod, type LifeBalance, type Who } from './api';
import { LifeBalanceRadar } from './charts';
import { PeriodSwitch } from './PeriodSwitch';

function Scores({ data }: { data: LifeBalance }) {
  const { t } = useTranslation('stats');
  return (
    <ul className="grid grid-cols-2 gap-2" data-testid="life-balance-scores">
      {data.attributes.map((a) => (
        <li
          key={a.attribute}
          data-testid={`balance-score-${a.attribute}`}
          data-score={a.score}
          className="flex flex-col gap-1 rounded-xl border border-border bg-surface px-3 py-2"
        >
          <span className="flex items-baseline justify-between gap-2 text-sm">
            <span className="truncate">{t(`common:game.attribute.${a.attribute}`)}</span>
            <span className="font-semibold">{t('balance.score', { score: a.score })}</span>
          </span>
          <span className="text-xs text-muted">
            {a.period_target > 0 ? t('balance.earned', { earned: a.earned_xp, target: a.period_target }) : t('balance.noTarget')}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Suggestions({ data, who, action }: { data: LifeBalance; who: Who; action?: ReactNode }) {
  const { t } = useTranslation('stats');
  if (data.balanced) {
    return (
      <p data-testid="life-balance-balanced" className="text-sm text-muted">
        {t(who === 'me' ? 'balance.balanced' : 'balance.companionBalanced')}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold text-muted">{t('balance.suggestionsTitle')}</h3>
      <ul className="flex flex-col gap-2" data-testid="life-balance-suggestions">
        {data.suggestions.map((s) => (
          <li
            key={s.attribute}
            data-testid="life-balance-suggestion"
            data-attribute={s.attribute}
            className="rounded-xl border border-border bg-surface px-3 py-2 text-sm"
          >
            {t(`balance.suggestion.${who}.${s.reason}`, { attribute: t(`common:game.attribute.${s.attribute}`) })}
          </li>
        ))}
      </ul>
      {action}
    </div>
  );
}

/** Life Balance for me or my companion: 7d / 30d switch, radar, per-attribute scores and the
 * rule-based suggestions. `actions` sits under the heading (targets editor, create quest). */
export function LifeBalanceCard({
  who,
  title,
  hint,
  headerAction,
  suggestionAction,
  testId = 'life-balance',
}: {
  who: Who;
  title: string;
  hint: string;
  headerAction?: ReactNode;
  suggestionAction?: ReactNode;
  testId?: string;
}) {
  const { t } = useTranslation('stats');
  const [period, setPeriod] = useState<BalancePeriod>('7d');
  const balance = useLifeBalance(period, who);
  return (
    <section data-testid={testId} aria-labelledby={`${testId}-title`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={`${testId}-title`} className="text-lg font-bold">
          {title}
        </h2>
        <PeriodSwitch value={period} options={BALANCE_PERIODS} onChange={setPeriod} testId={`${testId}-period`} />
      </div>
      <p className="text-xs text-muted">{hint}</p>
      {balance.data ? (
        <>
          <LifeBalanceRadar scores={balance.data.attributes} />
          {headerAction}
          <Scores data={balance.data} />
          <Suggestions data={balance.data} who={who} action={suggestionAction} />
        </>
      ) : balance.isError ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm">
            {t('balance.error')}
          </p>
          <button type="button" onClick={() => void balance.refetch()} className="rounded-md border border-border px-3 py-1 text-sm">
            {t('retry')}
          </button>
        </div>
      ) : (
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {t('balance.loading')}
        </p>
      )}
    </section>
  );
}
