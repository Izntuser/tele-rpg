import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  CATEGORIES,
  useEnableBotMessages,
  usePreferences,
  useUpdatePreferences,
  type Preferences,
  type PreferencesUpdate,
} from '../notifications/api';

const DEFAULT_QUIET = { start: '23:00', end: '08:00' };
const inputClass = 'rounded-md border border-border bg-surface-2 px-3 py-2';

function Toggle({
  id,
  label,
  checked,
  disabled,
  testId,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  disabled: boolean;
  testId: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <label htmlFor={id} className="text-sm">
        {label}
      </label>
      <input
        id={id}
        type="checkbox"
        role="switch"
        data-testid={testId}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-5 w-5 accent-[var(--accent)]"
      />
    </div>
  );
}

function QuietHours({
  prefs,
  disabled,
  save,
}: {
  prefs: Preferences;
  disabled: boolean;
  save: (body: PreferencesUpdate) => void;
}) {
  const { t } = useTranslation('notifications');
  const ids = useId();
  const enabled = prefs.quiet_hours_start !== null && prefs.quiet_hours_end !== null;
  // Remember the last bounds so turning quiet hours back on restores them.
  const [last, setLast] = useState({
    start: prefs.quiet_hours_start ?? DEFAULT_QUIET.start,
    end: prefs.quiet_hours_end ?? DEFAULT_QUIET.end,
  });
  const setBound = (which: 'start' | 'end', value: string) => {
    if (!/^\d{2}:\d{2}$/.test(value)) return;
    const next = { ...last, [which]: value };
    setLast(next);
    save({ quiet_hours_start: next.start, quiet_hours_end: next.end });
  };
  return (
    <div className="flex flex-col gap-2">
      <Toggle
        id={`${ids}-quiet`}
        label={t('settings.quietHours')}
        checked={enabled}
        disabled={disabled}
        testId="settings-quiet-toggle"
        onChange={(on) =>
          save(
            on
              ? { quiet_hours_start: last.start, quiet_hours_end: last.end }
              : { quiet_hours_start: null, quiet_hours_end: null },
          )
        }
      />
      {enabled ? (
        <div className="flex items-center gap-3">
          <label htmlFor={`${ids}-from`} className="text-sm">
            {t('settings.quietFrom')}
          </label>
          <input
            id={`${ids}-from`}
            type="time"
            data-testid="settings-quiet-start"
            value={prefs.quiet_hours_start ?? ''}
            disabled={disabled}
            onChange={(e) => setBound('start', e.target.value)}
            className={inputClass}
          />
          <label htmlFor={`${ids}-to`} className="text-sm">
            {t('settings.quietTo')}
          </label>
          <input
            id={`${ids}-to`}
            type="time"
            data-testid="settings-quiet-end"
            value={prefs.quiet_hours_end ?? ''}
            disabled={disabled}
            onChange={(e) => setBound('end', e.target.value)}
            className={inputClass}
          />
        </div>
      ) : null}
      <p className="text-xs text-muted">{t('settings.quietHoursHint')}</p>
    </div>
  );
}

/** Settings section: categories, quiet hours, the daily summary and enabling bot messages. */
export function NotificationSettings() {
  const { t } = useTranslation('notifications');
  const ids = useId();
  const prefs = usePreferences();
  const update = useUpdatePreferences();
  const enableBot = useEnableBotMessages();
  const save = (body: PreferencesUpdate) => update.mutate(body);
  const data = prefs.data;
  const busy = update.isPending;

  return (
    <section
      aria-labelledby={`${ids}-title`}
      data-testid="settings-notifications"
      className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4"
    >
      <h2 id={`${ids}-title`} className="font-semibold">
        {t('settings.title')}
      </h2>
      {prefs.isPending ? (
        <p role="status" className="text-sm text-muted">
          {t('settings.loading')}
        </p>
      ) : !data ? (
        <p className="text-sm text-danger" data-testid="settings-notifications-error">
          {t('settings.error')}
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-2 rounded-xl border border-border p-3" data-testid="settings-bot">
            <p className="text-sm font-medium">{t('settings.botTitle')}</p>
            <p className="text-sm text-muted" data-testid="settings-bot-status">
              {data.can_message ? t('settings.botEnabled') : t('settings.botDisabled')}
            </p>
            {!data.can_message ? (
              <button
                type="button"
                data-testid="settings-enable-bot"
                disabled={enableBot.isPending}
                onClick={() => enableBot.mutate()}
                className="self-start rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-fg disabled:opacity-50"
              >
                {t('settings.enableBot')}
              </button>
            ) : null}
            {enableBot.data && !enableBot.data.allowed ? (
              <p role="status" className="text-xs text-muted">
                {t('settings.enableBotDenied')}
              </p>
            ) : null}
            {enableBot.isError ? (
              <p role="alert" className="text-xs text-danger">
                {t('settings.saveError')}
              </p>
            ) : null}
          </div>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium">{t('settings.categoriesLabel')}</legend>
            {CATEGORIES.map((category) => (
              <Toggle
                key={category}
                id={`${ids}-category-${category}`}
                label={t(`settings.categories.${category}`)}
                checked={data.categories?.[category] ?? true}
                disabled={busy}
                testId={`settings-category-${category}`}
                onChange={(on) => save({ categories: { [category]: on } })}
              />
            ))}
          </fieldset>

          <QuietHours prefs={data} disabled={busy} save={save} />

          <Toggle
            id={`${ids}-daily-summary`}
            label={t('settings.dailySummary')}
            checked={data.daily_summary}
            disabled={busy}
            testId="settings-daily-summary"
            onChange={(on) => save({ daily_summary: on })}
          />

          {update.isError ? (
            <p role="alert" className="text-sm text-danger">
              {t('settings.saveError')}
            </p>
          ) : update.isSuccess ? (
            <p role="status" className="text-sm text-muted">
              {t('settings.saved')}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
