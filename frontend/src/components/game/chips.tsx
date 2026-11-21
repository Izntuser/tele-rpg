import { useTranslation } from 'react-i18next';

import { cn } from '../ui/cn';

export const ATTRIBUTES = [
  'physical',
  'intellectual',
  'discipline',
  'social',
  'creativity',
  'wellbeing',
] as const;
export type AttributeKey = (typeof ATTRIBUTES)[number];

export const DIFFICULTIES = ['easy', 'normal', 'hard', 'epic'] as const;
export type DifficultyKey = (typeof DIFFICULTIES)[number];

interface ChipProps {
  selected?: boolean;
  /** When set the chip is a toggle button (aria-pressed); otherwise it is a static label. */
  onSelect?: () => void;
  className?: string;
}

function Chip({
  label,
  tone,
  selected = false,
  onSelect,
  className,
  testId,
}: ChipProps & { label: string; tone: string; testId: string }) {
  const base = cn(
    'inline-flex items-center rounded-full border px-3 py-1 text-sm',
    selected ? 'border-accent bg-accent text-accent-fg' : cn('border-border', tone),
    className,
  );
  if (!onSelect) {
    return (
      <span data-testid={testId} className={base}>
        {label}
      </span>
    );
  }
  return (
    <button type="button" data-testid={testId} aria-pressed={selected} onClick={onSelect} className={base}>
      {label}
    </button>
  );
}

export function AttributeChip({ attribute, ...rest }: ChipProps & { attribute: AttributeKey }) {
  const { t } = useTranslation();
  return <Chip {...rest} testId={`attribute-${attribute}`} tone="text-fg" label={t(`game.attribute.${attribute}`)} />;
}

const DIFFICULTY_TONE: Record<DifficultyKey, string> = {
  easy: 'text-xp',
  normal: 'text-accent',
  hard: 'text-gold',
  epic: 'text-gm',
};

export function DifficultyChip({ difficulty, ...rest }: ChipProps & { difficulty: DifficultyKey }) {
  const { t } = useTranslation();
  return (
    <Chip
      {...rest}
      testId={`difficulty-${difficulty}`}
      tone={DIFFICULTY_TONE[difficulty]}
      label={t(`game.difficulty.${difficulty}`)}
    />
  );
}
