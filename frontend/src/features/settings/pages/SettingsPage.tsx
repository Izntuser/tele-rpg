import { useId, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ConfirmSheet } from '../../../components/ui/ConfirmSheet';
import { LOCALES } from '../../../i18n';
import { useAuth, useCurrentUser } from '../../auth/context';
import { AvatarPicker } from '../../character/AvatarPicker';
import { LEAVE_CONFIRM_TEXT, useLeavePartnership, usePartnership } from '../../partnership/api';
import { DELETE_CONFIRM_TEXT, useDeleteAccount, useExportData, useUpdatePreferences } from '../api';

function timezoneOptions(current: string): string[] {
  let all: string[] = [];
  try {
    all = Intl.supportedValuesOf('timeZone');
  } catch {
    all = [];
  }
  return Array.from(new Set([current, 'UTC', ...all])).sort();
}

function Card({ title, children, testId }: { title: string; children: ReactNode; testId: string }) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      data-testid={testId}
      className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4"
    >
      <h2 id={id} className="font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

const selectClass = 'rounded-md border border-border bg-surface-2 px-3 py-2';
const dangerButton = 'rounded-md border border-danger px-4 py-2 text-sm font-semibold text-danger disabled:opacity-50';

/** Avatar, language, timezone, partnership, data export, privacy note and the danger zone. */
export function SettingsPage() {
  const { t } = useTranslation('settings');
  const user = useCurrentUser();
  const { telegram } = useAuth();
  const ids = useId();
  const preferences = useUpdatePreferences();
  const partnership = usePartnership();
  const leave = useLeavePartnership();
  const exportData = useExportData();
  const deleteAccount = useDeleteAccount();
  const [sheet, setSheet] = useState<'leave' | 'delete' | null>(null);
  const options = useMemo(() => timezoneOptions(user.timezone), [user.timezone]);
  const companion = partnership.data?.partnership?.companion ?? null;

  const save = (body: { locale?: 'en' | 'uk'; timezone?: string }) =>
    preferences.mutate(body, {
      onSuccess: () => telegram.haptic.notification('success'),
      onError: () => telegram.haptic.notification('error'),
    });

  return (
    <section data-testid="page-settings" className="flex flex-col gap-4 p-4">
      <h1 className="text-2xl font-bold">{t('title')}</h1>

      <Card title={t('files:avatar.label')} testId="settings-avatar">
        <AvatarPicker name={user.display_name} fileId={user.avatar_file_id} fallbackUrl={user.avatar_url} />
      </Card>

      <Card title={t('language.title')} testId="settings-language">
        <label htmlFor={`${ids}-locale`} className="text-sm font-medium">
          {t('language.label')}
        </label>
        <select
          id={`${ids}-locale`}
          data-testid="settings-locale"
          value={user.locale}
          disabled={preferences.isPending}
          onChange={(e) => save({ locale: e.target.value as 'en' | 'uk' })}
          className={selectClass}
        >
          {LOCALES.map((locale) => (
            <option key={locale} value={locale}>
              {t(`language.${locale}`)}
            </option>
          ))}
        </select>
      </Card>

      <Card title={t('timezone.title')} testId="settings-timezone-card">
        <label htmlFor={`${ids}-tz`} className="text-sm font-medium">
          {t('timezone.label')}
        </label>
        <select
          id={`${ids}-tz`}
          data-testid="settings-timezone"
          value={user.timezone}
          disabled={preferences.isPending}
          onChange={(e) => save({ timezone: e.target.value })}
          className={selectClass}
        >
          {options.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted">{t('timezone.hint')}</p>
      </Card>

      {preferences.isError ? (
        <p role="alert" className="text-sm text-danger">
          {t('saveError')}
        </p>
      ) : preferences.isSuccess ? (
        <p role="status" className="text-sm text-muted">
          {t('saved')}
        </p>
      ) : null}

      <Card title={t('partnership.title')} testId="settings-partnership">
        {companion ? (
          <>
            <p className="text-sm" data-testid="settings-companion">
              {t('partnership.with', { name: companion.character_name ?? companion.display_name })}
            </p>
            <button
              type="button"
              data-testid="settings-leave"
              disabled={leave.isPending}
              onClick={() => setSheet('leave')}
              className={dangerButton}
            >
              {t('partnership.leave')}
            </button>
          </>
        ) : (
          <p className="text-sm text-muted">{t('partnership.none')}</p>
        )}
        {leave.isError ? (
          <p role="alert" className="text-sm text-danger">
            {t('partnership.leaveError')}
          </p>
        ) : null}
      </Card>

      <Card title={t('data.title')} testId="settings-data">
        <p className="text-sm text-muted" data-testid="settings-privacy">
          {t('data.privacy')}
        </p>
        <button
          type="button"
          data-testid="settings-export"
          disabled={exportData.isPending}
          onClick={() => exportData.mutate()}
          className="rounded-md border border-border px-4 py-2 text-sm disabled:opacity-50"
        >
          {exportData.isPending ? t('data.exporting') : t('data.export')}
        </button>
        {exportData.isError ? (
          <p role="alert" className="text-sm text-danger">
            {t('data.exportError')}
          </p>
        ) : null}
      </Card>

      <Card title={t('danger.title')} testId="settings-danger">
        <button
          type="button"
          data-testid="settings-delete"
          disabled={deleteAccount.isPending}
          onClick={() => setSheet('delete')}
          className={dangerButton}
        >
          {t('danger.delete')}
        </button>
        {deleteAccount.isError ? (
          <p role="alert" className="text-sm text-danger">
            {t('danger.deleteError')}
          </p>
        ) : null}
      </Card>

      <ConfirmSheet
        open={sheet === 'leave'}
        title={t('partnership.leaveTitle')}
        description={t('partnership.leaveDescription')}
        confirmLabel={t('partnership.leave')}
        destructive
        requireText={LEAVE_CONFIRM_TEXT}
        onCancel={() => setSheet(null)}
        onConfirm={() => {
          setSheet(null);
          leave.mutate(undefined, {
            onSuccess: () => telegram.haptic.notification('success'),
            onError: () => telegram.haptic.notification('error'),
          });
        }}
      />
      <ConfirmSheet
        open={sheet === 'delete'}
        title={t('danger.deleteTitle')}
        description={t('danger.deleteDescription')}
        confirmLabel={t('danger.delete')}
        destructive
        requireText={DELETE_CONFIRM_TEXT}
        onCancel={() => setSheet(null)}
        onConfirm={() => {
          setSheet(null);
          deleteAccount.mutate();
        }}
      />
    </section>
  );
}
