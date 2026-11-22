import { useTranslation } from 'react-i18next';

import { AuthImage } from '../../files/components';
import type { QuestView } from '../api';

interface Entry {
  key: string;
  label: string;
  at: string | null;
  note?: string | null;
  /** Photo proof attached to a submission (GET /files/{id}). */
  photoId?: number | null;
}

function formatDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));
}

/** What happened to the quest, oldest first, derived from the server's timestamps. */
export function buildTimeline(view: QuestView, t: (key: string) => string): Entry[] {
  const { template, occurrence, submissions } = view;
  const entries: Entry[] = [{ key: 'offered', label: t('timeline.offered'), at: template.created_at }];
  if (occurrence?.accepted_at) {
    entries.push({ key: 'accepted', label: t('timeline.accepted'), at: occurrence.accepted_at });
  }
  for (const s of submissions) {
    entries.push({
      key: `sub-${s.id}`,
      label: t('timeline.submitted'),
      at: s.created_at,
      note: s.comment,
      photoId: s.attachment_id,
    });
    if (s.review_status === 'redo') {
      entries.push({ key: `redo-${s.id}`, label: t('timeline.redo'), at: s.reviewed_at, note: s.review_comment });
    }
  }
  if (!submissions.length && occurrence?.submitted_at) {
    entries.push({ key: 'submitted', label: t('timeline.submitted'), at: occurrence.submitted_at });
  }
  if (occurrence?.completed_at) {
    entries.push({ key: 'completed', label: t('timeline.completed'), at: occurrence.completed_at });
  }
  if (view.status === 'declined') {
    entries.push({
      key: 'declined',
      label: t('timeline.declined'),
      at: template.last_declined_revision?.decided_at ?? null,
      note: occurrence?.decline_reason ?? template.last_declined_revision?.decline_reason,
    });
  } else if (view.status === 'cancelled') {
    entries.push({ key: 'cancelled', label: t('timeline.cancelled'), at: null });
  } else if (view.status === 'expired') {
    entries.push({ key: 'expired', label: t('timeline.expired'), at: occurrence?.due_at ?? null });
  }
  return entries;
}

export function StatusTimeline({ view }: { view: QuestView }) {
  const { t, i18n } = useTranslation('quests');
  const { t: tf } = useTranslation('files');
  const entries = buildTimeline(view, t);
  return (
    <ol data-testid="quest-timeline" className="flex flex-col gap-3 border-l border-border pl-4">
      {entries.map((e) => (
        <li key={e.key} className="relative text-sm">
          <span aria-hidden="true" className="absolute -left-[21px] top-1.5 size-2 rounded-full bg-accent" />
          <p className="font-medium">{e.label}</p>
          {e.at ? <p className="text-xs text-muted">{formatDate(e.at, i18n.language)}</p> : null}
          {e.note ? <p className="mt-1 whitespace-pre-line text-muted">{e.note}</p> : null}
          {e.photoId != null ? (
            <AuthImage
              fileId={e.photoId}
              alt={tf('photo.alt')}
              testId="submission-photo"
              className="mt-2 block max-h-64 w-full max-w-xs rounded-lg"
            />
          ) : null}
        </li>
      ))}
    </ol>
  );
}
