import { useEffect, useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { cn } from './cn';

/** Modal sheet anchored to the bottom edge. Escape or a tap on the backdrop closes it. */
export function BottomSheet({
  open,
  onClose,
  title,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children?: ReactNode;
  className?: string;
}) {
  const { t } = useTranslation();
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <button
        type="button"
        data-testid="sheet-backdrop"
        aria-label={t('ui.close')}
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cn(
          'relative w-full max-w-md rounded-t-2xl border border-border bg-surface p-4',
          'pb-[calc(1rem+var(--safe-bottom))]',
          className,
        )}
      >
        <h2 id={titleId} className="mb-3 text-lg font-semibold">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
