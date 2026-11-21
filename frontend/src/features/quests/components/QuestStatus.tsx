import { useTranslation } from 'react-i18next';

import { StatusPill, type Status } from '../../../components/ui/StatusPill';
import type { Occurrence, Template } from '../api';

type Raw = Occurrence['status'] | Template['status'];

/** The shared StatusPill for every status it knows; a paused quest gets its own label. */
export function QuestStatus({ status }: { status: Raw }) {
  const { t } = useTranslation('quests');
  if (status === 'paused') {
    return (
      <span
        data-status="paused"
        className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs font-medium text-muted"
      >
        {t('status.paused')}
      </span>
    );
  }
  return <StatusPill status={status === 'in_review' ? 'submitted' : (status as Status)} />;
}
