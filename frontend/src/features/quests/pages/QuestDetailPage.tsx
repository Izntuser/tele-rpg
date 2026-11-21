import { Copy } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';

import { EmptyState } from '../../../components/ui/EmptyState';
import { formFromTerms } from '../CreateQuestSheet';
import { parseQuestRef, useQuest, type Completion } from '../api';
import { QuestActions } from '../components/QuestActions';
import { QuestCelebration } from '../components/QuestCelebration';
import { QuestStatus } from '../components/QuestStatus';
import { StatusTimeline } from '../components/StatusTimeline';
import { TermsCard } from '../components/TermsCard';

export function QuestDetailPage() {
  const { t } = useTranslation('quests');
  const { id } = useParams();
  const navigate = useNavigate();
  const ref = parseQuestRef(id);
  const quest = useQuest(ref);
  const [completion, setCompletion] = useState<Completion | null>(null);
  const view = quest.data;

  return (
    <section data-testid="page-quest-detail" className="flex flex-col gap-4 p-4">
      <h1 className="text-2xl font-bold">{t('detail.title')}</h1>
      {!ref ? (
        <EmptyState title={t('detail.notFound')} />
      ) : quest.isError ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm">
            {t('detail.error')}
          </p>
          <button
            type="button"
            onClick={() => void quest.refetch()}
            className="rounded-md border border-border px-3 py-1 text-sm"
          >
            {t('retry')}
          </button>
        </div>
      ) : !view ? (
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {t('loading')}
        </p>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <QuestStatus status={view.status} />
            <span className="text-sm text-muted">{view.role === 'gm' ? t('fromMe') : t('forMe')}</span>
          </div>
          <TermsCard terms={view.terms} recurrence={view.template.recurrence} />

          {view.template.pending_revision && view.template.status === 'active' ? (
            <div className="flex flex-col gap-2">
              <h2 className="text-sm font-semibold text-gm">
                {view.role === 'gm' ? t('detail.yourProposal') : t('detail.proposedTerms')}
              </h2>
              <TermsCard
                testId="quest-revision"
                terms={view.template.pending_revision.terms}
                recurrence={view.template.recurrence}
              />
            </div>
          ) : null}

          {view.status === 'declined' && view.template.last_declined_revision?.decline_reason ? (
            <p data-testid="decline-note" className="rounded-md border border-danger px-3 py-2 text-sm">
              {t('detail.declinedBecause', { reason: view.template.last_declined_revision.decline_reason })}
            </p>
          ) : null}

          <section aria-labelledby="timeline-heading" className="flex flex-col gap-2">
            <h2 id="timeline-heading" className="text-sm font-semibold text-muted">
              {t('detail.timeline')}
            </h2>
            <StatusTimeline view={view} />
          </section>

          <QuestActions view={view} onCompleted={setCompletion} />

          {view.role === 'gm' ? (
            <button
              type="button"
              data-testid="quest-duplicate"
              onClick={() =>
                void navigate('/quests/new', {
                  state: { prefill: formFromTerms(view.template.terms, view.template.recurrence) },
                })
              }
              className="inline-flex items-center justify-center gap-2 rounded-md border border-border px-4 py-2 text-sm"
            >
              <Copy aria-hidden="true" size={16} />
              {t('detail.duplicate')}
            </button>
          ) : null}
        </>
      )}
      {completion ? (
        <QuestCelebration completion={completion} self={view?.role === 'player'} onDone={() => setCompletion(null)} />
      ) : null}
    </section>
  );
}
