import { useTranslation } from 'react-i18next';

import { cn } from '../../components/ui/cn';

/** A small segmented control (radio semantics) for a period. */
export function PeriodSwitch<P extends string>({
  value,
  options,
  onChange,
  testId,
}: {
  value: P;
  options: readonly P[];
  onChange: (next: P) => void;
  testId: string;
}) {
  const { t } = useTranslation('stats');
  return (
    <div role="radiogroup" aria-label={t('period.label')} data-testid={testId} className="inline-flex rounded-lg border border-border p-0.5">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={option === value}
          data-testid={`${testId}-${option}`}
          onClick={() => onChange(option)}
          className={cn(
            'rounded-md px-3 py-1 text-xs font-semibold focus-visible:outline focus-visible:outline-2',
            option === value ? 'bg-accent text-accent-fg' : 'text-muted',
          )}
        >
          {t(`period.${option}`)}
        </button>
      ))}
    </div>
  );
}
