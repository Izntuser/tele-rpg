import { Plus } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { GoldBadge } from '../../../components/game/GoldBadge';
import { ConfirmSheet } from '../../../components/ui/ConfirmSheet';
import { EmptyState } from '../../../components/ui/EmptyState';
import { ApiError } from '../../../lib/api/client';
import { useInventory, useVoucherAction, voucherActions } from '../../inventory/api';
import { ActionButton, VoucherCard } from '../../inventory/VoucherCard';
import { useCompanion } from '../../partnership/api';
import { useRewardMutations, useRewards, type Reward, type Voucher } from '../api';
import { RewardSheet, type RewardDraft } from '../components/RewardForm';
import { ScheduleSheet } from '../components/ScheduleSheet';
import { LoadError, ShopFrame } from '../components/ShopFrame';

const QUEUE = ['requested', 'scheduled', 'purchased'] as const;

/** Manage my shop: my rewards, open wishes to turn into rewards, and the requests queue. */
export function ShopManagePage() {
  const { t } = useTranslation('shop');
  const rewards = useRewards('mine');
  const queue = useInventory('provider');
  const companion = useCompanion();
  const { update } = useRewardMutations();
  const act = useVoucherAction();
  const [draft, setDraft] = useState<RewardDraft | null>(null);
  const [scheduling, setScheduling] = useState<Voucher | null>(null);
  const [refunding, setRefunding] = useState<Voucher | null>(null);

  const wishes = (companion.data?.wishlist ?? []).filter((w) => w.status === 'open');
  const open = (queue.data ?? [])
    .filter((v) => (QUEUE as readonly string[]).includes(v.status))
    .sort((a, b) => QUEUE.indexOf(a.status as (typeof QUEUE)[number]) - QUEUE.indexOf(b.status as (typeof QUEUE)[number]));

  const error = act.error ?? update.error;
  const errorText = error
    ? error instanceof ApiError && error.status === 409
      ? t('errors.conflict')
      : t('errors.generic')
    : null;

  const toggle = (reward: Reward) =>
    update.mutate({ id: reward.id, body: { status: reward.status === 'hidden' ? 'active' : 'hidden' } });

  return (
    <ShopFrame testId="page-shop-manage" title={t('manage.title')}>
      <section aria-labelledby="manage-requests" className="flex flex-col gap-2">
        <h2 id="manage-requests" className="text-sm font-semibold text-muted">
          {t('manage.requests')}
        </h2>
        {queue.isError ? (
          <LoadError onRetry={() => void queue.refetch()} />
        ) : open.length === 0 ? (
          <p data-testid="requests-empty" className="text-sm text-muted">
            {t('manage.requestsEmpty')}
          </p>
        ) : (
          <ul data-testid="request-list" className="flex flex-col gap-3">
            {open.map((voucher) => {
              const allowed = voucherActions(voucher, 'provider');
              return (
                <VoucherCard
                  key={voucher.id}
                  voucher={voucher}
                  actions={
                    <>
                      {allowed.schedule ? (
                        <ActionButton testId="voucher-schedule-open" tone="gm" disabled={act.isPending} onClick={() => setScheduling(voucher)}>
                          {voucher.status === 'scheduled' ? t('manage.reschedule') : t('manage.schedule')}
                        </ActionButton>
                      ) : null}
                      {allowed.fulfill ? (
                        <ActionButton
                          testId="voucher-fulfill"
                          disabled={act.isPending}
                          onClick={() => act.mutate({ id: voucher.id, action: { type: 'fulfill' } })}
                        >
                          {t('manage.fulfill')}
                        </ActionButton>
                      ) : null}
                      {allowed.refund ? (
                        <ActionButton testId="voucher-refund" tone="danger" disabled={act.isPending} onClick={() => setRefunding(voucher)}>
                          {t('inventory.refund')}
                        </ActionButton>
                      ) : null}
                    </>
                  }
                />
              );
            })}
          </ul>
        )}
      </section>

      <section aria-labelledby="manage-rewards" className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 id="manage-rewards" className="text-sm font-semibold text-muted">
            {t('manage.myRewards')}
          </h2>
          <button
            type="button"
            data-testid="reward-add"
            onClick={() => setDraft({ kind: 'create' })}
            className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1 text-sm font-semibold text-accent-fg"
          >
            <Plus aria-hidden="true" size={14} />
            {t('manage.add')}
          </button>
        </div>
        {rewards.isError ? (
          <LoadError onRetry={() => void rewards.refetch()} />
        ) : rewards.data && rewards.data.length === 0 ? (
          <EmptyState title={t('manage.empty.title')} description={t('manage.empty.hint')} />
        ) : (
          <ul data-testid="my-reward-list" className="flex flex-col gap-3">
            {(rewards.data ?? []).map((reward) => (
              <li
                key={reward.id}
                data-testid="my-reward"
                data-status={reward.status}
                className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 flex-1 break-words font-semibold">{reward.title}</p>
                  <GoldBadge amount={reward.price} />
                </div>
                <p className="text-xs text-muted">
                  {t(`manage.status.${reward.status}`)} ·{' '}
                  {reward.quantity_remaining === null ? t('unlimited') : t('left', { count: reward.quantity_remaining })}
                </p>
                <div className="flex gap-2">
                  <ActionButton testId="reward-edit" tone="plain" onClick={() => setDraft({ kind: 'edit', reward })}>
                    {t('manage.edit')}
                  </ActionButton>
                  <ActionButton testId="reward-toggle" tone="plain" disabled={update.isPending} onClick={() => toggle(reward)}>
                    {reward.status === 'hidden' ? t('manage.show') : t('manage.hide')}
                  </ActionButton>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="manage-wishes" className="flex flex-col gap-2">
        <h2 id="manage-wishes" className="text-sm font-semibold text-muted">
          {t('manage.wishes')}
        </h2>
        {wishes.length === 0 ? (
          <p data-testid="wishes-empty" className="text-sm text-muted">
            {t('manage.wishesEmpty')}
          </p>
        ) : (
          <ul data-testid="wish-list" className="flex flex-col gap-2">
            {wishes.map((wish) => (
              <li key={wish.id} data-testid="wish-option" className="flex items-center justify-between gap-2 rounded-xl border border-border bg-surface p-3">
                <span className="min-w-0 flex-1 break-words text-sm">{wish.title}</span>
                <button
                  type="button"
                  data-testid="wish-make-reward"
                  onClick={() => setDraft({ kind: 'create', wishlistItem: wish })}
                  className="shrink-0 rounded-md border border-border px-3 py-1 text-sm"
                >
                  {t('manage.fromWish')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {errorText ? (
        <p role="alert" data-testid="manage-error" className="text-sm text-danger">
          {errorText}
        </p>
      ) : null}

      <RewardSheet draft={draft} onClose={() => setDraft(null)} />
      <ScheduleSheet
        key={scheduling?.id ?? 'none'}
        open={scheduling !== null}
        title={scheduling?.reward.title ?? ''}
        initialNote={scheduling?.schedule_note}
        busy={act.isPending}
        onClose={() => setScheduling(null)}
        onSubmit={(scheduledFor, note) => {
          const target = scheduling;
          if (!target) return;
          act.mutate(
            { id: target.id, action: { type: 'schedule', scheduledFor, note } },
            { onSuccess: () => setScheduling(null) },
          );
        }}
      />
      <ConfirmSheet
        open={refunding !== null}
        destructive
        title={t('inventory.refundTitle')}
        description={t('manage.refundBody', { title: refunding?.reward.title ?? '' })}
        confirmLabel={t('inventory.refundConfirm')}
        onCancel={() => setRefunding(null)}
        onConfirm={() => {
          const target = refunding;
          setRefunding(null);
          if (target) act.mutate({ id: target.id, action: { type: 'refund' } });
        }}
      />
    </ShopFrame>
  );
}
