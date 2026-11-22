import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { BottomSheet } from '../../components/ui/BottomSheet';
import { ATTRIBUTES, MAX_WEEKLY_TARGET, useSetTargets, useTargets, type AttributeKey } from './api';

type Draft = Record<AttributeKey, string>;

function parse(value: string): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const n = Number(value.trim());
  return n <= MAX_WEEKLY_TARGET ? n : null;
}

function TargetsForm({ initial, onDone }: { initial: Record<AttributeKey, number>; onDone: () => void }) {
  const { t } = useTranslation('stats');
  const save = useSetTargets();
  const [draft, setDraft] = useState<Draft>(
    () => Object.fromEntries(ATTRIBUTES.map((a) => [a, String(initial[a] ?? 100)])) as Draft,
  );
  const parsed = ATTRIBUTES.map((a) => [a, parse(draft[a])] as const);
  const valid = parsed.every(([, n]) => n !== null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    save.mutate(Object.fromEntries(parsed) as Record<AttributeKey, number>, { onSuccess: onDone });
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" data-testid="targets-form" noValidate>
      <p className="text-sm text-muted">{t('targets.hint')}</p>
      <div className="grid grid-cols-2 gap-3">
        {ATTRIBUTES.map((a) => (
          <label key={a} className="flex flex-col gap-1 text-sm">
            <span>{t(`common:game.attribute.${a}`)}</span>
            <input
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_WEEKLY_TARGET}
              step={10}
              aria-label={t('targets.field', { attribute: t(`common:game.attribute.${a}`) })}
              data-testid={`target-${a}`}
              value={draft[a]}
              onChange={(e) => setDraft((d) => ({ ...d, [a]: e.target.value }))}
              className="rounded-md border border-border bg-bg px-3 py-2"
            />
          </label>
        ))}
      </div>
      {!valid ? (
        <p role="alert" className="text-sm text-danger">
          {t('targets.invalid')}
        </p>
      ) : null}
      {save.isError ? (
        <p role="alert" className="text-sm text-danger">
          {t('targets.error')}
        </p>
      ) : null}
      <button
        type="submit"
        data-testid="targets-save"
        disabled={!valid || save.isPending}
        className="rounded-lg bg-accent px-4 py-2 font-semibold text-accent-fg disabled:opacity-50"
      >
        {t('targets.save')}
      </button>
    </form>
  );
}

/** Bottom sheet editing my own weekly XP targets. */
export function TargetsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation('stats');
  const targets = useTargets(open);
  return (
    <BottomSheet open={open} onClose={onClose} title={t('targets.title')}>
      {targets.data ? (
        <TargetsForm initial={targets.data.targets as Record<AttributeKey, number>} onDone={onClose} />
      ) : targets.isError ? (
        <p role="alert" className="text-sm">
          {t('balance.error')}
        </p>
      ) : (
        <p role="status" className="text-sm text-muted">
          {t('loading')}
        </p>
      )}
    </BottomSheet>
  );
}
