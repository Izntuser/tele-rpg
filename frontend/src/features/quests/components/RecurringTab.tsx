import { Flame, Pause, Play } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { EmptyState } from '../../../components/ui/EmptyState';
import { questPath, type Template } from '../api';
import { useTemplatePause } from '../templatesApi';
import { QuestStatus } from './QuestStatus';

function Streak({ template }: { template: Template }) {
  const { t } = useTranslation('quests');
  if (!template.streak) return null;
  const { current, best } = template.streak;
  return (
    <p data-testid="recurring-streak" className="inline-flex items-center gap-1 text-sm">
      <Flame aria-hidden="true" size={14} className={current > 0 ? 'text-gold' : 'text-muted'} />
      <span>{t('recurring.streak', { count: current })}</span>
      <span className="text-xs text-muted">{t('recurring.best', { count: best })}</span>
    </p>
  );
}

function RecurringItem({ template }: { template: Template }) {
  const { t } = useTranslation('quests');
  const pause = useTemplatePause(template.id);
  const paused = template.status === 'paused';
  const canToggle = template.role === 'gm' && (template.status === 'active' || paused);
  const Icon = paused ? Play : Pause;
  return (
    <li
      data-testid="recurring-item"
      data-status={template.status}
      className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <Link
          to={questPath({ kind: 'template', id: template.id })}
          className="min-w-0 flex-1 break-words font-semibold focus-visible:outline focus-visible:outline-2"
        >
          {template.terms.title}
        </Link>
        <QuestStatus status={template.status} />
      </div>
      <p className="text-xs text-muted">
        {t(`recurrence.${template.recurrence}`)} · {template.role === 'gm' ? t('fromMe') : t('forMe')}
      </p>
      <Streak template={template} />
      {paused ? <p className="text-xs text-muted">{t('recurring.pausedHint')}</p> : null}
      {canToggle ? (
        <button
          type="button"
          data-testid={paused ? 'recurring-resume' : 'recurring-pause'}
          disabled={pause.isPending}
          onClick={() => pause.mutate(paused ? 'resume' : 'pause')}
          className="inline-flex items-center gap-2 self-start rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50"
        >
          <Icon aria-hidden="true" size={16} />
          {paused ? t('recurring.resume') : t('recurring.pause')}
        </button>
      ) : null}
      {pause.isError ? (
        <p role="alert" className="text-xs text-danger">
          {t('errors.generic')}
        </p>
      ) : null}
    </li>
  );
}

/** The Recurring tab: each recurring quest with its streak, and pause / resume for its creator. */
export function RecurringTab({ templates }: { templates: Template[] }) {
  const { t } = useTranslation('quests');
  if (!templates.length) return <EmptyState title={t('empty.recurring')} />;
  return (
    <ul className="flex flex-col gap-2" data-testid="recurring-list">
      {templates.map((template) => (
        <RecurringItem key={template.id} template={template} />
      ))}
    </ul>
  );
}
