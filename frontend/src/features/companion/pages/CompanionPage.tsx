import { useTranslation } from 'react-i18next';

import { XpBar } from '../../../components/game/XpBar';
import { EmptyState } from '../../../components/ui/EmptyState';
import { useCompanion, usePartnership, type CompanionProfile } from '../../partnership/api';
import { CompanionCardView } from '../../partnership/CompanionCardView';
import { InvitePanel } from '../../partnership/InvitePanel';

function Profile({ profile }: { profile: CompanionProfile }) {
  const { t } = useTranslation('partnership');
  return (
    <div data-testid="companion-profile" className="flex flex-col gap-4">
      <p className="self-start rounded-full border border-gm px-3 py-1 text-xs font-semibold text-gm">
        {t('companion.gmLabel')}
      </p>
      <CompanionCardView card={profile.card} testId="companion-card" />
      <XpBar level={profile.card.level} current={profile.xp_into_level} max={profile.xp_for_next_level} />
      {profile.bio ? (
        <section aria-labelledby="companion-about" className="flex flex-col gap-1">
          <h2 id="companion-about" className="text-sm font-semibold text-muted">
            {t('companion.about')}
          </h2>
          <p className="whitespace-pre-line text-sm">{profile.bio}</p>
        </section>
      ) : null}

      <section aria-labelledby="companion-attributes" className="flex flex-col gap-2">
        <h2 id="companion-attributes" className="text-sm font-semibold text-muted">
          {t('companion.attributes')}
        </h2>
        <ul className="grid grid-cols-3 gap-2" data-testid="companion-attributes">
          {profile.attributes.map((a) => (
            <li
              key={a.attribute}
              className="flex flex-col items-center rounded-xl border border-border bg-surface px-2 py-2 text-center"
            >
              <span className="text-xs text-muted">{t(`common:game.attribute.${a.attribute}`)}</span>
              <span className="text-sm font-semibold">{t('profile:character.attributeLevel', { level: a.level })}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="companion-goals" className="flex flex-col gap-2">
        <h2 id="companion-goals" className="text-sm font-semibold text-muted">
          {t('companion.goals')}
        </h2>
        {profile.goals.length ? (
          <ul className="flex flex-col gap-2" data-testid="companion-goals">
            {profile.goals.map((g) => (
              <li key={g.id} className="rounded-xl border border-border bg-surface px-3 py-2 text-sm">
                {g.title}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">{t('companion.goalsEmpty')}</p>
        )}
      </section>

      <section aria-labelledby="companion-wishlist" className="flex flex-col gap-2">
        <h2 id="companion-wishlist" className="text-sm font-semibold text-muted">
          {t('companion.wishlist')}
        </h2>
        {profile.wishlist.length ? (
          <ul className="flex flex-col gap-2" data-testid="companion-wishlist">
            {profile.wishlist.map((w) => (
              <li
                key={w.id}
                className="flex items-center justify-between gap-2 rounded-xl border border-border bg-surface px-3 py-2 text-sm"
              >
                <span className="min-w-0 truncate">{w.title}</span>
                {w.status === 'offered' ? (
                  <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted">
                    {t('companion.inShop')}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">{t('companion.wishlistEmpty')}</p>
        )}
      </section>
    </div>
  );
}

/** My companion's profile, attributes, goals and wishlist; the invite CTA while unpaired. */
export function CompanionPage() {
  const { t } = useTranslation('partnership');
  const partnership = usePartnership();
  const paired = Boolean(partnership.data?.partnership);
  const companion = useCompanion(paired);
  const failed = partnership.isError || companion.isError;

  return (
    <section data-testid="page-companion" className="flex flex-col gap-4 p-4">
      <h1 className="text-2xl font-bold">{t('companion.title')}</h1>
      {failed ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm">
            {t('companion.error')}
          </p>
          <button
            type="button"
            onClick={() => void (partnership.isError ? partnership.refetch() : companion.refetch())}
            className="rounded-md border border-border px-3 py-1 text-sm"
          >
            {t('companion.retry')}
          </button>
        </div>
      ) : partnership.data && !paired ? (
        <>
          <EmptyState title={t('companion.none')} description={t('companion.noneHint')} />
          {partnership.data.pending_invitation ? (
            <p className="text-sm text-muted" data-testid="invite-pending">
              {t('invite.pending')}
            </p>
          ) : null}
          <InvitePanel />
        </>
      ) : companion.data ? (
        <Profile profile={companion.data} />
      ) : (
        <p role="status" aria-live="polite" className="text-sm text-muted">
          {t('companion.loading')}
        </p>
      )}
    </section>
  );
}
