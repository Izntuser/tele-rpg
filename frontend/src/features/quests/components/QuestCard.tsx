import { Repeat } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { AttributeChip, DifficultyChip } from '../../../components/game/chips';
import { GoldBadge } from '../../../components/game/GoldBadge';
import { isTemplate, questPath, type Occurrence, type Template } from '../api';
import { QuestStatus } from './QuestStatus';

/** One quest in a list: terms at a glance, linking to its detail page. */
export function QuestCard({ quest }: { quest: Occurrence | Template }) {
  const { t } = useTranslation('quests');
  const template = isTemplate(quest);
  const to = questPath(template ? { kind: 'template', id: quest.id } : { kind: 'occurrence', id: quest.id });
  const pending = !template && quest.has_pending_revision;
  return (
    <Link
      to={to}
      data-testid="quest-card"
      className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3 focus-visible:outline focus-visible:outline-2"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 flex-1 break-words font-semibold">{quest.terms.title}</p>
        <QuestStatus status={quest.status} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <AttributeChip attribute={quest.terms.attribute} />
        <DifficultyChip difficulty={quest.terms.difficulty} />
        <GoldBadge amount={quest.terms.gold} />
        <span className="text-xs text-muted">{t('xp', { amount: quest.terms.xp })}</span>
        {quest.recurrence !== 'once' ? (
          <span className="inline-flex items-center gap-1 text-xs text-muted">
            <Repeat aria-hidden="true" size={12} />
            {t(`recurrence.${quest.recurrence}`)}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-muted">
        {quest.role === 'gm' ? t('fromMe') : t('forMe')}
        {pending ? ` · ${t('revisionPending')}` : ''}
      </p>
    </Link>
  );
}
