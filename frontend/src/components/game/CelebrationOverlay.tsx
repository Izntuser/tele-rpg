import confetti from 'canvas-confetti';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import { cn } from '../ui/cn';

export type CelebrationKind = 'levelUp' | 'questComplete' | 'purchase';

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Full-screen celebration. Under reduced motion it is a static card: no confetti, no animation. */
export function CelebrationOverlay({
  open,
  kind,
  detail,
  onDone,
}: {
  open: boolean;
  kind: CelebrationKind;
  detail?: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const animated = open && !prefersReducedMotion();

  useEffect(() => {
    if (!animated) return;
    void confetti({ particleCount: 80, spread: 70, origin: { y: 0.6 } });
  }, [animated]);

  if (!open) return null;
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={t(`game.celebration.${kind}`)}
      data-animated={animated}
      className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3 bg-black/80 p-6 text-center"
    >
      <p className={cn('text-3xl font-bold text-gold', animated && 'animate-bounce')}>
        {t(`game.celebration.${kind}`)}
      </p>
      {detail ? <p className="text-lg">{detail}</p> : null}
      <button
        type="button"
        onClick={onDone}
        className="rounded-md bg-accent px-6 py-2 font-semibold text-accent-fg"
      >
        {t('game.continue')}
      </button>
    </div>
  );
}
