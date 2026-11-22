import { useTranslation } from 'react-i18next';

import { cn } from '../../components/ui/cn';
import type { AttributeScore } from './api';

const SIZE = { width: 320, height: 270 };
const CENTER = { x: 160, y: 135 };
const RADIUS = 88;
const LABEL_RADIUS = 106;
const RINGS = [25, 50, 75, 100];

function point(index: number, count: number, radius: number): [number, number] {
  // The first axis points straight up; the rest go clockwise.
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / count;
  return [CENTER.x + radius * Math.cos(angle), CENTER.y + radius * Math.sin(angle)];
}

const path = (points: [number, number][]) => points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');

/** Six-axis radar of activity scores (0-100). The scores are also listed next to it, so the
 * chart is never the only way to read them. */
export function LifeBalanceRadar({ scores, testId = 'life-balance-radar' }: { scores: AttributeScore[]; testId?: string }) {
  const { t } = useTranslation('stats');
  const n = scores.length;
  const summary = scores
    .map((s) => t('balance.scoreItem', { attribute: t(`common:game.attribute.${s.attribute}`), score: s.score }))
    .join(', ');
  const shape = scores.map((s, i) => point(i, n, (RADIUS * Math.max(0, Math.min(100, s.score))) / 100));
  return (
    <svg
      data-testid={testId}
      role="img"
      aria-label={t('balance.radarLabel', { summary })}
      viewBox={`0 0 ${SIZE.width} ${SIZE.height}`}
      className="mx-auto w-full max-w-xs text-muted"
    >
      {RINGS.map((ring) => (
        <polygon
          key={ring}
          points={path(scores.map((_, i) => point(i, n, (RADIUS * ring) / 100)))}
          fill="none"
          stroke="var(--border)"
          strokeWidth={1}
        />
      ))}
      {scores.map((s, i) => {
        const [x, y] = point(i, n, RADIUS);
        return <line key={s.attribute} x1={CENTER.x} y1={CENTER.y} x2={x} y2={y} stroke="var(--border)" strokeWidth={1} />;
      })}
      <polygon
        data-testid="radar-shape"
        points={path(shape)}
        fill="var(--accent)"
        fillOpacity={0.28}
        stroke="var(--accent)"
        strokeWidth={2}
        strokeLinejoin="round"
      />
      {shape.map(([x, y], i) => (
        <circle key={scores[i]!.attribute} cx={x} cy={y} r={4} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2}>
          <title>{t('balance.scoreItem', { attribute: t(`common:game.attribute.${scores[i]!.attribute}`), score: scores[i]!.score })}</title>
        </circle>
      ))}
      {scores.map((s, i) => {
        const [x, y] = point(i, n, LABEL_RADIUS);
        const anchor = Math.abs(x - CENTER.x) < 4 ? 'middle' : x > CENTER.x ? 'start' : 'end';
        return (
          <text
            key={s.attribute}
            x={x}
            y={y}
            textAnchor={anchor}
            dominantBaseline="middle"
            fontSize={12}
            fill="var(--fg-muted)"
            aria-hidden="true"
          >
            {t(`common:game.attribute.${s.attribute}`)}
          </text>
        );
      })}
    </svg>
  );
}

/** One bar per day (single series), with each value in a hover title and the total in the
 * accessible name. */
export function DailyBars({
  title,
  days,
  testId,
  className,
}: {
  title: string;
  days: { date: string; value: number }[];
  testId: string;
  className?: string;
}) {
  const { t, i18n } = useTranslation('stats');
  const max = Math.max(0, ...days.map((d) => d.value));
  const total = days.reduce((sum, d) => sum + d.value, 0);
  const format = new Intl.DateTimeFormat(i18n.language, { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const label = (date: string) => format.format(new Date(`${date}T00:00:00Z`));
  return (
    <figure data-testid={testId} data-total={total} className={cn('flex flex-col gap-2', className)}>
      <figcaption className="flex items-baseline justify-between text-sm">
        <span className="font-semibold">{title}</span>
        <span className="text-xs text-muted">{t('charts.total', { total })}</span>
      </figcaption>
      <div
        role="img"
        aria-label={`${title}: ${t('charts.total', { total })}`}
        className="flex h-24 items-end gap-[2px] border-b border-border"
      >
        {days.map((d) => (
          <div
            key={d.date}
            title={t('charts.day', { date: label(d.date), value: d.value })}
            className="flex h-full min-w-0 flex-1 items-end"
          >
            <div
              className={cn('w-full rounded-t', d.value > 0 ? 'bg-xp' : 'bg-transparent')}
              style={{ height: max > 0 && d.value > 0 ? `${Math.max(4, (d.value / max) * 100)}%` : 0 }}
            />
          </div>
        ))}
      </div>
      {days.length > 0 ? (
        <div className="flex justify-between text-xs text-muted" aria-hidden="true">
          <span>{label(days[0]!.date)}</span>
          <span>{label(days[days.length - 1]!.date)}</span>
        </div>
      ) : null}
    </figure>
  );
}
