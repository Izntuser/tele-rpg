import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';

import { useAuth, useCurrentUser } from '../../auth/context';
import { ONBOARDING_PATH } from '../../onboarding/redirect';
import { inviteProblem, useAcceptInvite, useInvitePreview } from '../api';
import { CompanionCardView } from '../CompanionCardView';

/** Location state that makes onboarding come back to this invitation when it is done. */
export interface PendingInviteState {
  deeplink?: boolean;
  inviteToken?: string;
}

/** /invite/:token — shows who invited me and lets me accept (after onboarding if needed). */
export function InvitePage() {
  const { t } = useTranslation('partnership');
  const { token = '' } = useParams();
  const user = useCurrentUser();
  const { telegram } = useAuth();
  const navigate = useNavigate();
  const preview = useInvitePreview(token);
  const accept = useAcceptInvite();
  const onboarded = Boolean(user.onboarded_at);

  const problem = preview.error ?? accept.error;

  return (
    <section data-testid="page-invite" className="flex min-h-screen flex-col gap-4 p-4">
      <header>
        <h1 className="text-2xl font-bold">{t('accept.title')}</h1>
        <p className="text-sm text-muted">{t('accept.subtitle')}</p>
      </header>

      {preview.isPending ? (
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {t('accept.loading')}
        </p>
      ) : null}

      {preview.data ? (
        <>
          <p className="text-sm">{t('accept.invitedBy')}</p>
          <CompanionCardView card={preview.data.inviter} testId="invite-inviter" />
        </>
      ) : null}

      {problem ? (
        <p role="alert" data-testid="invite-error" className="text-sm text-danger">
          {t(`accept.errors.${inviteProblem(problem)}`)}
        </p>
      ) : null}

      <div className="mt-auto flex flex-col gap-2 pb-2">
        {preview.data && !onboarded ? (
          <>
            <p className="text-sm text-muted">{t('accept.onboardFirst')}</p>
            <button
              type="button"
              data-testid="invite-onboard"
              onClick={() =>
                void navigate(ONBOARDING_PATH, {
                  replace: true,
                  state: { deeplink: true, inviteToken: token } satisfies PendingInviteState,
                })
              }
              className="rounded-md bg-accent px-4 py-3 font-semibold text-accent-fg"
            >
              {t('accept.createCharacter')}
            </button>
          </>
        ) : null}
        {preview.data && onboarded ? (
          <button
            type="button"
            data-testid="invite-accept"
            disabled={accept.isPending || accept.isSuccess}
            onClick={() =>
              accept.mutate(token, {
                onSuccess: () => {
                  telegram.haptic.notification('success');
                  void navigate('/companion', { replace: true });
                },
                onError: () => telegram.haptic.notification('error'),
              })
            }
            className="rounded-md bg-accent px-4 py-3 font-semibold text-accent-fg disabled:opacity-50"
          >
            {accept.isPending ? t('accept.accepting') : t('accept.accept')}
          </button>
        ) : null}
        {onboarded ? (
          <button
            type="button"
            data-testid="invite-dismiss"
            onClick={() => void navigate('/', { replace: true })}
            className="rounded-md border border-border px-4 py-3 text-sm"
          >
            {t('accept.notNow')}
          </button>
        ) : null}
      </div>
    </section>
  );
}
