import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ATTRIBUTES, AttributeChip, DIFFICULTIES, DifficultyChip, type AttributeKey, type DifficultyKey } from '../../components/game/chips';
import { GoldBadge } from '../../components/game/GoldBadge';
import { BottomSheet } from '../../components/ui/BottomSheet';
import { ApiError } from '../../lib/api/client';
import { usePresetMutations, useCreateQuest, type Preset, type QuestCreated, type Recurrence, type Terms } from './api';
import { EstimateHint } from './components/EstimateHint';
import { GmLabel } from './components/GmLabel';
import { PresetPicker } from './components/PresetPicker';

export interface QuestForm {
  title: string;
  description: string;
  attribute: AttributeKey | null;
  difficulty: DifficultyKey;
  gold: number;
  recurrence: Recurrence;
  /** `datetime-local` value, local time. */
  deadline: string;
  confirmation: 'manual' | 'auto';
  photoRequired: boolean;
}

export const EMPTY_FORM: QuestForm = {
  title: '',
  description: '',
  attribute: null,
  difficulty: 'normal',
  gold: 50,
  recurrence: 'once',
  deadline: '',
  confirmation: 'manual',
  photoRequired: false,
};

/** Duplicate quest: the same terms, ready to edit and offer again (no deadline carried over). */
export function formFromTerms(terms: Terms, recurrence: Recurrence): QuestForm {
  return {
    ...EMPTY_FORM,
    title: terms.title,
    description: terms.description ?? '',
    attribute: terms.attribute,
    difficulty: terms.difficulty,
    gold: terms.gold,
    recurrence,
    confirmation: terms.confirmation,
    photoRequired: terms.photo_required,
  };
}

function formFromPreset(preset: Preset, current: QuestForm): QuestForm {
  return {
    ...current,
    title: preset.title,
    description: preset.description ?? '',
    attribute: preset.attribute,
    difficulty: preset.difficulty,
    gold: preset.gold,
    recurrence: preset.recurrence,
    deadline: preset.recurrence === 'once' ? current.deadline : '',
    confirmation: preset.confirmation,
    photoRequired: preset.photo_required,
  };
}

function QuestFormBody({
  initial,
  onCreated,
}: {
  initial: QuestForm;
  onCreated: (created: QuestCreated) => void;
}) {
  const { t } = useTranslation('quests');
  const ids = { title: useId(), gold: useId(), description: useId(), recurrence: useId(), deadline: useId(), confirmation: useId() };
  const [form, setForm] = useState<QuestForm>(initial);
  const [more, setMore] = useState(
    () => initial.recurrence !== 'once' || initial.confirmation !== 'manual' || initial.photoRequired || initial.description !== '',
  );
  const [pickerOpen, setPickerOpen] = useState(false);
  const create = useCreateQuest();
  const { save } = usePresetMutations();
  const set = <K extends keyof QuestForm>(key: K, value: QuestForm[K]) => setForm((f) => ({ ...f, [key]: value }));

  const valid = form.title.trim().length > 0 && form.attribute !== null;
  const terms = () => ({
    title: form.title.trim(),
    description: form.description.trim() || null,
    attribute: form.attribute!,
    difficulty: form.difficulty,
    gold: form.gold,
    recurrence: form.recurrence,
    confirmation: form.confirmation,
    photo_required: form.photoRequired,
  });

  const submit = () => {
    if (!valid) return;
    const deadline = form.recurrence === 'once' && form.deadline ? new Date(form.deadline) : null;
    create.mutate(
      { ...terms(), deadline_at: deadline ? deadline.toISOString() : null },
      { onSuccess: onCreated },
    );
  };

  const error = create.error;
  const errorText =
    error instanceof ApiError
      ? error.status === 409
        ? t('create.errors.limit')
        : t('create.errors.invalid')
      : error
        ? t('create.errors.generic')
        : null;

  const input = 'rounded-md border border-border bg-surface-2 px-3 py-2';
  return (
    <form
      data-testid="create-quest-form"
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <GmLabel />
      <button
        type="button"
        data-testid="preset-toggle"
        aria-expanded={pickerOpen}
        onClick={() => setPickerOpen((v) => !v)}
        className="self-start rounded-md border border-border px-3 py-1 text-sm"
      >
        {t('create.presets')}
      </button>
      {pickerOpen ? (
        <PresetPicker
          onPick={(preset) => {
            setForm((f) => formFromPreset(preset, f));
            if (preset.recurrence !== 'once') setMore(true);
            setPickerOpen(false);
          }}
        />
      ) : null}

      <div className="flex flex-col gap-1">
        <label htmlFor={ids.title} className="text-sm text-muted">
          {t('create.title')}
        </label>
        <input
          id={ids.title}
          data-testid="quest-title"
          value={form.title}
          maxLength={200}
          onChange={(event) => set('title', event.target.value)}
          className={input}
        />
      </div>

      <div role="group" aria-label={t('create.attribute')} className="flex flex-wrap gap-2">
        {ATTRIBUTES.map((a) => (
          <AttributeChip key={a} attribute={a} selected={form.attribute === a} onSelect={() => set('attribute', a)} />
        ))}
      </div>
      <div role="group" aria-label={t('create.difficulty')} className="flex flex-wrap gap-2">
        {DIFFICULTIES.map((d) => (
          <DifficultyChip key={d} difficulty={d} selected={form.difficulty === d} onSelect={() => set('difficulty', d)} />
        ))}
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <label htmlFor={ids.gold} className="text-sm text-muted">
            {t('create.gold')}
          </label>
          <GoldBadge amount={form.gold} />
        </div>
        <input
          id={ids.gold}
          data-testid="quest-gold"
          type="range"
          min={0}
          max={1000}
          step={5}
          value={form.gold}
          onChange={(event) => set('gold', Number(event.target.value))}
        />
      </div>

      <button
        type="button"
        data-testid="more-options"
        aria-expanded={more}
        onClick={() => setMore((v) => !v)}
        className="self-start text-sm text-accent"
      >
        {more ? t('create.fewer') : t('create.more')}
      </button>

      {more ? (
        <div data-testid="more-fields" className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor={ids.description} className="text-sm text-muted">
              {t('create.description')}
            </label>
            <textarea
              id={ids.description}
              value={form.description}
              maxLength={2000}
              rows={2}
              onChange={(event) => set('description', event.target.value)}
              className={input}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={ids.recurrence} className="text-sm text-muted">
              {t('create.recurrence')}
            </label>
            <select
              id={ids.recurrence}
              data-testid="quest-recurrence"
              value={form.recurrence}
              onChange={(event) => set('recurrence', event.target.value as Recurrence)}
              className={input}
            >
              {(['once', 'daily', 'weekly'] as const).map((r) => (
                <option key={r} value={r}>
                  {t(`recurrence.${r}`)}
                </option>
              ))}
            </select>
          </div>
          {form.recurrence === 'once' ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={ids.deadline} className="text-sm text-muted">
                {t('create.deadline')}
              </label>
              <input
                id={ids.deadline}
                data-testid="quest-deadline"
                type="datetime-local"
                value={form.deadline}
                onChange={(event) => set('deadline', event.target.value)}
                className={input}
              />
            </div>
          ) : null}
          <div className="flex flex-col gap-1">
            <label htmlFor={ids.confirmation} className="text-sm text-muted">
              {t('create.confirmation')}
            </label>
            <select
              id={ids.confirmation}
              data-testid="quest-confirmation"
              value={form.confirmation}
              onChange={(event) => set('confirmation', event.target.value as 'manual' | 'auto')}
              className={input}
            >
              <option value="manual">{t('confirmation.manual')}</option>
              <option value="auto">{t('confirmation.auto')}</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              data-testid="quest-photo"
              checked={form.photoRequired}
              onChange={(event) => set('photoRequired', event.target.checked)}
            />
            {t('create.photo')}
          </label>
        </div>
      ) : null}

      <EstimateHint gold={form.gold} recurrence={form.recurrence} />

      {errorText ? (
        <p role="alert" data-testid="create-error" className="text-sm text-danger">
          {errorText}
        </p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="button"
          data-testid="save-template"
          disabled={!valid || save.isPending || save.isSuccess}
          onClick={() => save.mutate(terms())}
          className="flex-1 rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50"
        >
          {save.isSuccess ? t('create.templateSaved') : t('create.saveTemplate')}
        </button>
        <button
          type="submit"
          data-testid="quest-create"
          disabled={!valid || create.isPending}
          className="flex-1 rounded-md bg-gm px-4 py-2 text-sm font-semibold text-bg disabled:opacity-50"
        >
          {create.isPending ? t('create.creating') : t('create.submit')}
        </button>
      </div>
    </form>
  );
}

/** "New quest" bottom sheet. The form remounts every time the sheet opens. */
export function CreateQuestSheet({
  open,
  onClose,
  onCreated,
  initial = EMPTY_FORM,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (created: QuestCreated) => void;
  initial?: QuestForm;
}) {
  const { t } = useTranslation('quests');
  return (
    <BottomSheet open={open} onClose={onClose} title={t('create.heading')} className="max-h-[92vh] overflow-y-auto">
      <QuestFormBody initial={initial} onCreated={onCreated} />
    </BottomSheet>
  );
}
