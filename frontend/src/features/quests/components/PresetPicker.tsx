import { Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { GoldBadge } from '../../../components/game/GoldBadge';
import { usePresetMutations, usePresets, type Preset } from '../api';

/** Built-in presets (localized by the server) and my saved templates; picking one fills the form. */
export function PresetPicker({ onPick }: { onPick: (preset: Preset) => void }) {
  const { t } = useTranslation('quests');
  const presets = usePresets();
  const { remove } = usePresetMutations();

  if (presets.isError) {
    return (
      <p role="alert" className="text-sm text-danger">
        {t('presets.error')}
      </p>
    );
  }
  if (!presets.data) {
    return (
      <p role="status" className="text-sm text-muted">
        {t('presets.loading')}
      </p>
    );
  }

  const row = (preset: Preset) => (
    <li key={preset.key} className="flex items-center gap-2">
      <button
        type="button"
        data-testid="preset-option"
        onClick={() => onPick(preset)}
        className="flex min-w-0 flex-1 items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-left text-sm"
      >
        <span className="min-w-0 break-words">{preset.title}</span>
        <GoldBadge amount={preset.gold} />
      </button>
      {preset.saved_id !== null ? (
        <button
          type="button"
          data-testid="preset-delete"
          aria-label={t('presets.delete', { title: preset.title })}
          disabled={remove.isPending}
          onClick={() => remove.mutate(preset.saved_id!)}
          className="rounded-md border border-border p-2 text-danger"
        >
          <Trash2 aria-hidden="true" size={16} />
        </button>
      ) : null}
    </li>
  );

  return (
    <div data-testid="preset-picker" className="flex max-h-60 flex-col gap-2 overflow-y-auto rounded-md border border-border p-2">
      {presets.data.saved.length ? (
        <>
          <h3 className="text-xs font-semibold uppercase text-muted">{t('presets.saved')}</h3>
          <ul className="flex flex-col gap-1">{presets.data.saved.map(row)}</ul>
        </>
      ) : null}
      <h3 className="text-xs font-semibold uppercase text-muted">{t('presets.builtin')}</h3>
      <ul className="flex flex-col gap-1">{presets.data.builtin.map(row)}</ul>
    </div>
  );
}
