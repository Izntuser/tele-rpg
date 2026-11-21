import { useTranslation } from 'react-i18next';

import { InvitePanel } from '../partnership/InvitePanel';

/** Last onboarding step (the character already exists): invite a companion, or skip for now. */
export function InviteStep({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation('partnership');
  return (
    <div data-testid="onboarding-step-invite" className="flex flex-1 flex-col gap-4">
      <p className="text-sm text-muted">{t('onboarding.hint')}</p>
      <InvitePanel />
      <div className="mt-auto pb-2">
        <button
          type="button"
          data-testid="onboarding-start"
          onClick={onDone}
          className="w-full rounded-md border border-border px-4 py-3 text-sm font-semibold"
        >
          {t('onboarding.start')}
        </button>
      </div>
    </div>
  );
}
