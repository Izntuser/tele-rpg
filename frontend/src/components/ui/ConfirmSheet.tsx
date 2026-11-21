import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { BottomSheet } from './BottomSheet';
import { cn } from './cn';

/**
 * In-app replacement for window.confirm. With `requireText` the confirm button stays disabled
 * until the user types that exact text (leave partnership, delete account).
 */
export function ConfirmSheet({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  destructive = false,
  requireText,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  requireText?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const inputId = useId();
  const [typed, setTyped] = useState('');
  const confirmed = requireText === undefined || typed === requireText;

  const cancel = () => {
    setTyped('');
    onCancel();
  };

  return (
    <BottomSheet open={open} onClose={cancel} title={title}>
      {description ? <p className="mb-3 text-sm text-muted">{description}</p> : null}
      {requireText !== undefined ? (
        <div className="mb-3 flex flex-col gap-1">
          <label htmlFor={inputId} className="text-sm">
            {t('ui.typeToConfirm', { text: requireText })}
          </label>
          <input
            id={inputId}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
            autoCapitalize="off"
            className="rounded-md border border-border bg-surface-2 px-3 py-2"
          />
        </div>
      ) : null}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={cancel}
          className="flex-1 rounded-md border border-border px-4 py-2 text-sm"
        >
          {cancelLabel ?? t('ui.cancel')}
        </button>
        <button
          type="button"
          disabled={!confirmed}
          onClick={() => {
            setTyped('');
            onConfirm();
          }}
          className={cn(
            'flex-1 rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-50',
            destructive ? 'bg-danger text-bg' : 'bg-accent text-accent-fg',
          )}
        >
          {confirmLabel ?? t('ui.confirm')}
        </button>
      </div>
    </BottomSheet>
  );
}
