import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { BottomSheet } from '../../../components/ui/BottomSheet';

/** Pick when a requested voucher will be delivered, with an optional note. */
export function ScheduleSheet({
  open,
  title,
  initialNote,
  busy,
  onClose,
  onSubmit,
}: {
  open: boolean;
  title: string;
  initialNote?: string | null;
  busy: boolean;
  onClose: () => void;
  onSubmit: (scheduledFor: string, note: string) => void;
}) {
  const { t } = useTranslation('shop');
  const [when, setWhen] = useState('');
  const [note, setNote] = useState(initialNote ?? '');
  const date = when ? new Date(when) : null;
  const valid = date !== null && !Number.isNaN(date.getTime()) && date.getTime() > Date.now();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (valid && date) onSubmit(date.toISOString(), note);
  };

  return (
    <BottomSheet open={open} onClose={onClose} title={t('manage.scheduleTitle', { title })}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm text-muted">
          {t('manage.scheduleWhen')}
          <input
            type="datetime-local"
            data-testid="schedule-when"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            className="rounded-md border border-border bg-surface-2 px-3 py-2 text-fg"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-muted">
          {t('manage.scheduleNote')}
          <textarea
            data-testid="schedule-note"
            value={note}
            maxLength={1000}
            rows={2}
            onChange={(e) => setNote(e.target.value)}
            className="rounded-md border border-border bg-surface-2 px-3 py-2 text-fg"
          />
        </label>
        {when && !valid ? (
          <p role="alert" className="text-sm text-danger">
            {t('manage.schedulePast')}
          </p>
        ) : null}
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className="flex-1 rounded-md border border-border px-4 py-2 text-sm">
            {t('form.cancel')}
          </button>
          <button
            type="submit"
            data-testid="schedule-save"
            disabled={!valid || busy}
            className="flex-1 rounded-md bg-gm px-4 py-2 text-sm font-semibold text-bg disabled:opacity-50"
          >
            {t('manage.scheduleSave')}
          </button>
        </div>
      </form>
    </BottomSheet>
  );
}
