import { useTranslation } from 'react-i18next';

/** Marks GM-only actions and quests I created: the Game Master accent. */
export function GmLabel({ className }: { className?: string }) {
  const { t } = useTranslation('quests');
  return (
    <p
      data-testid="gm-label"
      className={`self-start rounded-full border border-gm px-3 py-1 text-xs font-semibold text-gm ${className ?? ''}`}
    >
      {t('gmLabel')}
    </p>
  );
}
