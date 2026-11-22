import { useId, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ConfirmSheet } from '../../../components/ui/ConfirmSheet';
import { cn } from '../../../components/ui/cn';
import { ApiError } from '../../../lib/api/client';
import { useQuestAction, type Completion, type QuestRef, type QuestView } from '../api';
import { GmLabel } from './GmLabel';
import { SubmitForm } from './SubmitForm';

type Mode = 'decline' | 'redo' | null;

export interface ActionSet {
  accept: boolean;
  decline: boolean;
  submit: boolean;
  confirm: boolean;
  redo: boolean;
  cancel: boolean;
  /** accept/decline act on a pending revision, not on the offer. */
  revision: boolean;
}

/** Which actions the viewer may take, mirroring the server's state machine and roles. */
export function allowedActions(view: QuestView): ActionSet {
  const { status, role } = view;
  const player = role === 'player';
  const revision = status === 'active' && Boolean(view.template.pending_revision) && player;
  return {
    accept: player && (status === 'offered' || revision),
    decline: player && (status === 'offered' || revision),
    submit: player && status === 'active',
    confirm: !player && status === 'in_review',
    redo: !player && status === 'in_review',
    cancel: status === 'offered' || status === 'active',
    revision,
  };
}

function Field({
  label,
  value,
  onChange,
  testId,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  testId: string;
  required?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm text-muted">
        {label}
      </label>
      <textarea
        id={id}
        data-testid={testId}
        value={value}
        required={required}
        maxLength={1000}
        rows={2}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md border border-border bg-surface-2 px-3 py-2"
      />
    </div>
  );
}

function Button({
  children,
  onClick,
  testId,
  tone = 'primary',
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  testId: string;
  tone?: 'primary' | 'gm' | 'plain' | 'danger';
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'flex-1 rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-50',
        tone === 'primary' && 'bg-accent text-accent-fg',
        tone === 'gm' && 'bg-gm text-bg',
        tone === 'plain' && 'border border-border',
        tone === 'danger' && 'border border-danger text-danger',
      )}
    >
      {children}
    </button>
  );
}

/**
 * The actions this viewer can take on the quest right now, and only those. GM actions sit under
 * the "You are the Game Master" label.
 */
export function QuestActions({
  view,
  onCompleted,
  onSettled,
}: {
  view: QuestView;
  /** The request completed the quest (Gold and XP were paid out). */
  onCompleted: (completion: Completion) => void;
  /** Any successful action, with the template-level result where the route returned one. */
  onSettled?: () => void;
}) {
  const { t } = useTranslation('quests');
  const allowed = allowedActions(view);
  const ref: QuestRef = view.occurrence
    ? { kind: 'occurrence', id: view.occurrence.id }
    : { kind: 'template', id: view.template.id };
  const action = useQuestAction(ref);
  const [mode, setMode] = useState<Mode>(null);
  const [text, setText] = useState('');
  const [feedback, setFeedback] = useState('');
  const [confirmCancel, setConfirmCancel] = useState(false);

  const run = (body: Parameters<typeof action.mutate>[0]) => {
    action.mutate(body, {
      onSuccess: (result) => {
        setMode(null);
        setText('');
        setFeedback('');
        const completion = (result as { completion?: Completion | null }).completion;
        if (completion) onCompleted(completion);
        onSettled?.();
      },
    });
  };

  const none = !(allowed.accept || allowed.submit || allowed.confirm || allowed.cancel);
  const gmSide = view.role === 'gm' && (allowed.confirm || allowed.cancel);
  const busy = action.isPending;
  const error = action.error;
  const errorText =
    error instanceof ApiError
      ? error.status === 409
        ? t('errors.conflict')
        : typeof error.detail === 'string'
          ? error.detail
          : t('errors.generic')
      : error
        ? t('errors.generic')
        : null;

  if (none) {
    return view.status === 'in_review' ? (
      <p data-testid="quest-waiting" className="text-sm text-muted">
        {t('waitingReview')}
      </p>
    ) : null;
  }

  return (
    <section data-testid="quest-actions" aria-label={t('actions.title')} className="flex flex-col gap-3">
      {gmSide ? <GmLabel /> : null}
      {allowed.revision ? (
        <p data-testid="revision-note" className="rounded-md border border-gm px-3 py-2 text-sm">
          {t('revisionProposed')}
        </p>
      ) : null}

      {allowed.submit ? (
        <SubmitForm
          photoRequired={view.terms.photo_required}
          busy={busy}
          onSubmit={({ comment, attachmentId }) => run({ type: 'submit', comment, attachmentId })}
        />
      ) : null}

      {allowed.confirm ? (
        <>
          <Field label={t('actions.feedbackLabel')} value={feedback} onChange={setFeedback} testId="confirm-feedback" />
          <div className="flex gap-2">
            <Button testId="quest-confirm" tone="gm" disabled={busy} onClick={() => run({ type: 'confirm', feedback })}>
              {t('actions.confirm')}
            </Button>
            <Button testId="quest-redo" tone="plain" disabled={busy} onClick={() => setMode(mode === 'redo' ? null : 'redo')}>
              {t('actions.redo')}
            </Button>
          </div>
        </>
      ) : null}

      {allowed.accept ? (
        <div className="flex gap-2">
          <Button testId="quest-accept" disabled={busy} onClick={() => run({ type: 'accept' })}>
            {allowed.revision ? t('actions.acceptRevision') : t('actions.accept')}
          </Button>
          <Button testId="quest-decline" tone="plain" disabled={busy} onClick={() => setMode(mode === 'decline' ? null : 'decline')}>
            {allowed.revision ? t('actions.declineRevision') : t('actions.decline')}
          </Button>
        </div>
      ) : null}

      {mode === 'decline' ? (
        <>
          <Field label={t('actions.declineReason')} value={text} onChange={setText} testId="decline-reason" />
          <Button testId="decline-send" tone="danger" disabled={busy} onClick={() => run({ type: 'decline', reason: text })}>
            {t('actions.declineSend')}
          </Button>
        </>
      ) : null}
      {mode === 'redo' ? (
        <>
          <Field label={t('actions.redoReason')} value={text} onChange={setText} testId="redo-reason" required />
          <Button
            testId="redo-send"
            tone="gm"
            disabled={busy || !text.trim()}
            onClick={() => run({ type: 'redo', reason: text })}
          >
            {t('actions.redoSend')}
          </Button>
        </>
      ) : null}

      {allowed.cancel ? (
        <Button testId="quest-cancel" tone="danger" disabled={busy} onClick={() => setConfirmCancel(true)}>
          {t('actions.cancel')}
        </Button>
      ) : null}

      {errorText ? (
        <p role="alert" data-testid="quest-error" className="text-sm text-danger">
          {errorText}
        </p>
      ) : null}

      <ConfirmSheet
        open={confirmCancel}
        destructive
        title={t('actions.cancelTitle')}
        description={t('actions.cancelBody')}
        confirmLabel={t('actions.cancelConfirm')}
        cancelLabel={t('actions.keep')}
        onCancel={() => setConfirmCancel(false)}
        onConfirm={() => {
          setConfirmCancel(false);
          run({ type: 'cancel' });
        }}
      />
    </section>
  );
}
